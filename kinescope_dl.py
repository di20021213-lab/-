"""Kinescope video downloader.

Достаёт из embed-страницы / JSON плеера Kinescope ссылку на потоковый
манифест (DASH `.mpd` или HLS `.m3u8`) и скачивает видео целым файлом,
подставляя корректный заголовок Referer.

Скачивай только то, на что у тебя есть права: свои материалы, купленные
курсы и т.п. Ролики с DRM (Widevine/FairPlay) этот инструмент не
поддерживает — без легальных ключей их скачать нельзя.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Callable, Optional
from urllib.parse import urljoin, urlparse

try:
    import requests
except ImportError:  # pragma: no cover - зависимость проверяется в рантайме
    print(
        "Не найден модуль 'requests'. Установи зависимости:\n"
        "    pip install -r requirements.txt",
        file=sys.stderr,
    )
    raise SystemExit(1)


BASE_URL = "https://kinescope.io"

# Заголовки, максимально похожие на реальный браузерный плеер: без них
# Kinescope часто отвечает 403.
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "ru,en;q=0.9",
    "Origin": BASE_URL,
}

# Ссылки на манифесты, которые встречаются внутри JSON/JS плеера.
MANIFEST_RE = re.compile(r'https?://[^\s"\'\\<>]+?\.(?:mpd|m3u8)[^\s"\'\\<>]*')


class KinescopeError(RuntimeError):
    """Ошибка, понятная пользователю (без трейсбека)."""


@dataclass
class Manifests:
    """Найденные ссылки на манифесты видео."""

    dash: list[str] = field(default_factory=list)
    hls: list[str] = field(default_factory=list)

    @property
    def best(self) -> Optional[str]:
        """Предпочитаем DASH (у Kinescope там обычно все качества), иначе HLS."""
        if self.dash:
            return self.dash[0]
        if self.hls:
            return self.hls[0]
        return None

    def __bool__(self) -> bool:
        return bool(self.dash or self.hls)


def extract_video_id(url_or_id: str) -> str:
    """Достаёт ID видео из полного URL или возвращает как есть, если это уже ID."""
    url_or_id = url_or_id.strip()
    if "kinescope.io" not in url_or_id and "/" not in url_or_id:
        return url_or_id
    path = urlparse(url_or_id).path
    parts = [p for p in path.split("/") if p and p != "embed"]
    if not parts:
        raise KinescopeError(f"Не смог разобрать ID видео из: {url_or_id!r}")
    return parts[-1]


def safe_filename(name: str, fallback: str = "video", max_len: int = 120) -> str:
    """Готовит из произвольного заголовка корректное имя файла для Windows.

    Убирает запрещённые символы \\/:*?"<>|, схлопывает пробелы, срезает точки
    и пробелы по краям и ограничивает длину. Если после чистки ничего не
    осталось — возвращает fallback.
    """
    name = (name or "").strip()
    # Часто в <title> висит хвост " — Kinescope" или " | МТС Линк" и т.п.
    for sep in (" — ", " – ", " | ", " · "):
        idx = name.find(sep)
        if idx > 0 and len(name) - idx < 40:
            name = name[:idx].strip()
    # Заменяем запрещённые в Windows символы на дефис.
    name = re.sub(r'[\\/:*?"<>|]+', "-", name)
    # Управляющие символы и переводы строк — прочь.
    name = re.sub(r"[\x00-\x1f]+", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    # Windows не любит завершающие точки/пробелы.
    name = name.strip(". ")
    if len(name) > max_len:
        name = name[:max_len].strip(". ")
    # Зарезервированные имена устройств Windows (CON, PRN, COM1…) — не годятся.
    reserved = {"con", "prn", "aux", "nul"}
    reserved |= {f"com{i}" for i in range(1, 10)}
    reserved |= {f"lpt{i}" for i in range(1, 10)}
    if name.lower() in reserved:
        name = name + "_"
    return name or fallback


def fetch_title(video_id: str, referer: str, session) -> str:
    """Пытается достать название ролика Kinescope со страницы плеера."""
    candidates = [
        f"{BASE_URL}/embed/{video_id}",
        f"{BASE_URL}/{video_id}",
    ]
    for url in candidates:
        try:
            resp = session.get(
                url,
                headers={**DEFAULT_HEADERS, "Referer": referer},
                timeout=30,
            )
        except requests.RequestException:
            continue
        if resp.status_code != 200 or not resp.text:
            continue
        text = resp.text
        # 1) og:title / meta title — самое чистое название.
        for pat in (
            r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']',
            r'<meta[^>]+name=["\']title["\'][^>]+content=["\']([^"\']+)["\']',
            r'"title"\s*:\s*"((?:[^"\\]|\\.)+)"',
            r"<title>([^<]+)</title>",
        ):
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                title = m.group(1)
                title = (
                    title.replace("\\u0026", "&")
                    .replace('\\"', '"')
                    .replace("\\/", "/")
                    .strip()
                )
                # Пропускаем безликие болванки.
                if title and title.lower() not in ("kinescope", "video"):
                    return title
    return ""


def _find_manifests(text: str) -> Manifests:
    """Вытаскивает из произвольного текста (JSON/JS/HTML) ссылки на манифесты."""
    m = Manifests()
    seen: set[str] = set()
    for url in MANIFEST_RE.findall(text):
        # Обрезаем возможный экранированный хвост \u0026 -> &
        url = url.replace("\\u0026", "&").replace("\\/", "/")
        if url in seen:
            continue
        seen.add(url)
        if ".mpd" in url:
            m.dash.append(url)
        else:
            m.hls.append(url)
    return m


# id Kinescope из embed-ссылки или из master.mpd — так получаем публичный id,
# а не внутренний uuid под-плейлистов.
_KINESCOPE_EMBED_RE = re.compile(r"kinescope\.io\\?/embed\\?/([A-Za-z0-9]{6,})")
_KINESCOPE_MASTER_RE = re.compile(
    r"kinescope\.io\\?/([A-Za-z0-9]{6,})\\?/master\.mpd"
)


def extract_sources_from_text(text: str) -> list[str]:
    """Достаёт из произвольного текста (JSON/HAR/HTML) ссылки для скачивания.

    Возвращает список готовых к очереди адресов: прямые манифесты m3u8/mpd и
    страницы Kinescope по публичному id. Дубликаты отсеиваются.
    """
    urls: list[str] = []
    seen: set[str] = set()

    def add(u: str) -> None:
        if u and u not in seen:
            seen.add(u)
            urls.append(u)

    # В JSON/HAR слэши часто экранированы (https:\/\/…). Ищем и в исходном
    # тексте (для id с экранированием), и в «распакованной» копии (для URL).
    unescaped = text.replace("\\/", "/").replace("\\u0026", "&")
    manifests = _find_manifests(unescaped)
    manifest_ids: set[str] = set()
    for u in manifests.dash + manifests.hls:
        add(u)
        mm = re.search(r"kinescope\.io/([A-Za-z0-9]{6,})/", u)
        if mm:
            manifest_ids.add(mm.group(1))
    # id Kinescope добавляем, только если тот же ролик ещё не пришёл манифестом,
    # иначе одно видео попадёт в список дважды.
    for source in (text, unescaped):
        for regex in (_KINESCOPE_EMBED_RE, _KINESCOPE_MASTER_RE):
            for mid in regex.findall(source):
                if mid not in manifest_ids:
                    add(f"{BASE_URL}/{mid}")
    return urls


def classify_manifest_body(url: str, body: str) -> Optional[str]:
    """Определяет, является ли сам ответ манифестом (по URL + началу тела).

    Kinescope отдаёт master.mpd без XML-пролога — сразу с тега <MPD>, —
    поэтому проверять только `<?xml` недостаточно.
    """
    head = body.lstrip()[:200]
    upper = head.upper()
    if url.endswith(".mpd") and ("<MPD" in upper or upper.startswith("<?XML")):
        return "dash"
    if url.endswith(".m3u8") and head.startswith("#EXTM3U"):
        return "hls"
    return None


def resolve_manifests(
    video_id: str,
    referer: str,
    session: requests.Session,
    verbose: bool = False,
) -> Manifests:
    """Скачивает страницы/JSON плеера и собирает из них ссылки на манифесты."""
    candidates = [
        f"{BASE_URL}/{video_id}",
        f"{BASE_URL}/embed/{video_id}",
        f"{BASE_URL}/{video_id}/master.mpd",
    ]
    found = Manifests()
    for url in candidates:
        try:
            resp = session.get(
                url,
                headers={**DEFAULT_HEADERS, "Referer": referer},
                timeout=30,
            )
        except requests.RequestException as exc:
            if verbose:
                print(f"  [skip] {url}: {exc}", file=sys.stderr)
            continue

        if verbose:
            print(f"  [{resp.status_code}] {url}", file=sys.stderr)

        if resp.status_code != 200 or not resp.text:
            continue

        # Если сам ответ — это уже манифест (Kinescope отдаёт master.mpd
        # без XML-пролога, сразу с тега <MPD>).
        kind = classify_manifest_body(url, resp.text)
        if kind == "dash":
            if url not in found.dash:
                found.dash.append(url)
            continue
        if kind == "hls":
            if url not in found.hls:
                found.hls.append(url)
            continue

        page = _find_manifests(resp.text)
        found.dash.extend(u for u in page.dash if u not in found.dash)
        found.hls.extend(u for u in page.hls if u not in found.hls)

    return found


# --------------------------------------------------------------------------- #
# Скачивание DASH силами Python (сегменты качает requests, склейка — ffmpeg
# локально). Так весь сетевой трафик идёт через системный прокси и доверенные
# сертификаты Windows — в отличие от ffmpeg, который ходит в сеть напрямую и в
# корпоративных сетях блокируется.
# --------------------------------------------------------------------------- #

_DASH_NS = "urn:mpeg:dash:schema:mpd:2011"


def _q(elem, tag):
    return elem.find(f"{{{_DASH_NS}}}{tag}")


def _qa(elem, tag):
    return elem.findall(f"{{{_DASH_NS}}}{tag}")


def _select_representations(root):
    """Выбирает видеодорожку 1080p (или ближайшую снизу) и лучший звук."""
    videos, audios = [], []
    for aset in root.iter(f"{{{_DASH_NS}}}AdaptationSet"):
        mime = aset.get("mimeType") or ""
        for rep in _qa(aset, "Representation"):
            kind = mime or (rep.get("mimeType") or "")
            if "video" in kind:
                videos.append(rep)
            elif "audio" in kind:
                audios.append(rep)
    if not videos:
        return (None, None)
    height = lambda r: int(r.get("height") or 0)
    band = lambda r: int(r.get("bandwidth") or 0)
    le1080 = [v for v in videos if height(v) <= 1080] or videos
    video = max(le1080, key=lambda r: (height(r), band(r)))
    audio = max(audios, key=band) if audios else None
    return (video, audio)


def _segment_count(rep) -> int:
    sl = _q(rep, "SegmentList")
    if sl is not None:
        return len(_qa(sl, "SegmentURL"))
    return 0


def _download_representation(rep, session, dest, on_segment) -> None:
    base = _q(rep, "BaseURL")
    sl = _q(rep, "SegmentList")
    if base is None or sl is None:
        raise KinescopeError(
            "неподдерживаемый формат манифеста (нет BaseURL/SegmentList)."
        )
    base_url = base.text
    with open(dest, "wb") as f:
        init = _q(sl, "Initialization")
        if init is not None and init.get("range"):
            src = init.get("sourceURL") or ""
            resp = session.get(
                base_url + src,
                headers={"Range": f"bytes={init.get('range')}"},
                timeout=120,
            )
            resp.raise_for_status()
            f.write(resp.content)
        for seg in _qa(sl, "SegmentURL"):
            media = seg.get("media") or ""
            rng = seg.get("mediaRange")
            headers = {"Range": f"bytes={rng}"} if rng else {}
            resp = session.get(base_url + media, headers=headers, timeout=120)
            resp.raise_for_status()
            f.write(resp.content)
            on_segment()


def _run_ffmpeg_progress(args: list, output: str, progress) -> None:
    """Запускает ffmpeg с -progress и обновляет прогресс (для перекодирования)."""
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=creationflags,
    )
    duration = None
    dur_re = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
    time_re = re.compile(r"out_time=(\d+):(\d+):(\d+(?:\.\d+)?)")
    for line in proc.stdout:  # type: ignore[union-attr]
        if duration is None:
            m = dur_re.search(line)
            if m:
                h, mi, s = m.groups()
                duration = int(h) * 3600 + int(mi) * 60 + float(s)
        m = time_re.search(line)
        if m and duration and progress:
            h, mi, s = m.groups()
            cur = int(h) * 3600 + int(mi) * 60 + float(s)
            progress(min(0.999, cur / duration))
    proc.wait()
    if proc.returncode != 0 or not os.path.exists(output):
        raise KinescopeError(
            f"ffmpeg (водяной знак) завершился с кодом {proc.returncode}."
        )


def _ff_escape_path(path: str) -> str:
    """Экранирует путь для filtergraph ffmpeg (слэши + двоеточие диска)."""
    return path.replace("\\", "/").replace(":", "\\:")


def _run_mux(
    ffmpeg,
    input_files,
    video_stream,
    audio_stream,
    output,
    audio_bsf=False,
    watermark=None,
    progress=None,
    label=None,
    font=None,
) -> None:
    """Склеивает дорожки в mp4. Если задан watermark — накладывает его в углу
    (с перекодированием видео), иначе быстрый ремукс без перекодирования."""
    args = [ffmpeg, "-y"]
    for path in input_files:
        args += ["-i", path]
    if watermark and os.path.isfile(watermark):
        wm_idx = len(input_files)
        args += ["-i", watermark]
        fc = (
            f"[{wm_idx}:v][0:v]scale2ref=w=oh*mdar:h=ih*0.08[wm][base];"
            "[wm]format=rgba,colorchannelmixer=aa=0.40[wmt];"
            "[base][wmt]overlay=W-w-16:H-h-16[v]"
        )
        args += ["-filter_complex", fc, "-map", "[v]"]
        if audio_stream:
            args += ["-map", audio_stream]
        args += [
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
            "-pix_fmt", "yuv420p", "-c:a", "copy",
        ]
        if audio_bsf:
            args += ["-bsf:a", "aac_adtstoasc"]
        args += ["-progress", "pipe:1", "-nostats", output]
        _run_ffmpeg_progress(args, output, progress)
        return

    args += ["-map", video_stream]
    if audio_stream:
        args += ["-map", audio_stream]
    args += ["-c", "copy"]
    if audio_bsf:
        args += ["-bsf:a", "aac_adtstoasc"]
    args += [output]
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.run(
        args, capture_output=True, text=True, creationflags=creationflags
    )
    if proc.returncode != 0 or not os.path.exists(output):
        tail = (proc.stderr or "")[-300:]
        raise KinescopeError(
            f"ffmpeg (склейка) завершился с кодом {proc.returncode}. {tail}"
        )


def download_dash(
    mpd_url,
    session,
    output,
    ffmpeg,
    progress=None,
    watermark=None,
    label=None,
    font=None,
) -> None:
    """Качает DASH-манифест (video 1080p + audio) и склеивает в mp4."""
    root = ET.fromstring(session.get(mpd_url, timeout=60).text)
    video, audio = _select_representations(root)
    if video is None:
        raise KinescopeError("в манифесте не найдено видео.")
    total = _segment_count(video) + (
        _segment_count(audio) if audio is not None else 0
    )
    done = 0
    dl_span = 0.5 if watermark else 0.98

    def bump():
        nonlocal done
        done += 1
        if progress and total:
            progress(min(dl_span, done / total * dl_span))

    mux_prog = None
    if watermark and progress:
        mux_prog = lambda f: progress(0.5 + f * 0.5)
    tmp = tempfile.mkdtemp(prefix="kinescope_")
    try:
        video_path = os.path.join(tmp, "video.mp4")
        _download_representation(video, session, video_path, bump)
        input_files = [video_path]
        audio_stream = None
        if audio is not None:
            audio_path = os.path.join(tmp, "audio.mp4")
            _download_representation(audio, session, audio_path, bump)
            input_files.append(audio_path)
            audio_stream = "1:a:0"
        _run_mux(
            ffmpeg, input_files, "0:v:0", audio_stream, output,
            watermark=watermark, progress=mux_prog, label=label, font=font,
        )
        if progress:
            progress(1)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _parse_m3u8_attrs(line: str) -> dict:
    """Разбирает атрибуты вида KEY=VALUE,KEY="VALUE" из строки тега."""
    attrs = {}
    for m in re.finditer(r'([A-Z0-9-]+)=("[^"]*"|[^,]*)', line):
        attrs[m.group(1)] = m.group(2).strip('"')
    return attrs


def _select_hls_variant(text: str, base_url: str):
    """Из master-плейлиста выбирает поток ≤1080p и, если есть, аудиогруппу."""
    variants = []
    audios = {}
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("#EXT-X-MEDIA:"):
            a = _parse_m3u8_attrs(line)
            if a.get("TYPE") == "AUDIO" and a.get("URI"):
                gid = a.get("GROUP-ID", "")
                slot = audios.setdefault(gid, {})
                slot["any"] = urljoin(base_url, a["URI"])
                if a.get("DEFAULT", "").upper() == "YES":
                    slot["default"] = urljoin(base_url, a["URI"])
        elif line.startswith("#EXT-X-STREAM-INF:"):
            a = _parse_m3u8_attrs(line)
            uri = ""
            for j in range(i + 1, len(lines)):
                if lines[j].strip() and not lines[j].startswith("#"):
                    uri = lines[j].strip()
                    break
            height = 0
            if a.get("RESOLUTION") and "x" in a["RESOLUTION"]:
                try:
                    height = int(a["RESOLUTION"].split("x")[1])
                except ValueError:
                    height = 0
            variants.append({
                "uri": urljoin(base_url, uri),
                "bandwidth": int(a.get("BANDWIDTH") or 0),
                "height": height,
                "audio": a.get("AUDIO"),
            })
    if not variants:
        return (base_url, None)
    ok = [v for v in variants if v["height"] <= 1080] or variants
    best = max(ok, key=lambda v: (v["height"], v["bandwidth"]))
    audio_uri = None
    if best.get("audio") and best["audio"] in audios:
        slot = audios[best["audio"]]
        audio_uri = slot.get("default") or slot.get("any")
    if audio_uri is None and audios:
        slot = next(iter(audios.values()))
        audio_uri = slot.get("default") or slot.get("any")
    return (best["uri"], {"uri": audio_uri} if audio_uri else None)


def normalize_manifest_url(url: str) -> str:
    """Сводит дорожки МТС Линк/вебинаров (v1/a1) к мастер-плейлисту.

    .../{hash}.mp4/v1/index.m3u8  ->  .../{hash}.mp4/playlist.m3u8
    """
    m = re.match(r"(https?://[^?#]+\.mp4/)(?:v\d+|a\d+)/index\.m3u8", url)
    if m:
        return m.group(1) + "playlist.m3u8"
    return url


def _byterange_header(spec: str, prev_end: int):
    """EXT-X-BYTERANGE 'len[@offset]' -> заголовок Range и новый prev_end."""
    if "@" in spec:
        length, offset = spec.split("@")
        offset = int(offset)
    else:
        length, offset = spec, prev_end
    length = int(length)
    end = offset + length - 1
    return ({"Range": f"bytes={offset}-{end}"}, end + 1)


def _download_hls_media(playlist_url, session, dest, on_progress) -> bool:
    """Скачивает media-плейлист (init-сегмент + сегменты, +AES-128, +byterange).

    Возвращает True, если это fMP4 (есть EXT-X-MAP) — для выбора битстрим-фильтра.
    """
    text = session.get(playlist_url, timeout=60).text
    lines = text.splitlines()
    media_seq = 0
    for line in lines:
        if line.startswith("#EXT-X-MEDIA-SEQUENCE:"):
            try:
                media_seq = int(line.split(":", 1)[1])
            except ValueError:
                media_seq = 0
    init = None
    segments = []
    cur_key, cur_iv = None, None
    pending_range = None
    seq = media_seq
    for line in lines:
        if line.startswith("#EXT-X-MAP:"):
            a = _parse_m3u8_attrs(line)
            init = (urljoin(playlist_url, a.get("URI", "")), a.get("BYTERANGE"))
        elif line.startswith("#EXT-X-KEY:"):
            a = _parse_m3u8_attrs(line)
            method = a.get("METHOD", "NONE")
            if method == "NONE":
                cur_key = None
            elif method == "AES-128" and a.get("URI"):
                cur_key = session.get(
                    urljoin(playlist_url, a["URI"]), timeout=30
                ).content
                iv = a.get("IV")
                if iv and iv.lower().startswith("0x"):
                    cur_iv = bytes.fromhex(iv[2:])
                else:
                    cur_iv = None
            else:
                raise KinescopeError(f"неподдерживаемое шифрование HLS: {method}")
        elif line.startswith("#EXT-X-BYTERANGE:"):
            pending_range = line.split(":", 1)[1].strip()
        elif line and not line.startswith("#"):
            iv_use = cur_iv if cur_iv is not None else seq.to_bytes(16, "big")
            segments.append(
                (urljoin(playlist_url, line), cur_key, iv_use, pending_range)
            )
            pending_range = None
            seq += 1
    if not segments:
        raise KinescopeError("в HLS-плейлисте не найдено сегментов.")
    total = len(segments)
    with open(dest, "wb") as f:
        if init:
            iurl, ibr = init
            headers = {}
            if ibr:
                headers, _ = _byterange_header(ibr, 0)
            f.write(session.get(iurl, headers=headers, timeout=120).content)
        prev_end = 0
        for idx, (url, key, iv, br) in enumerate(segments, 1):
            headers = {}
            if br:
                headers, prev_end = _byterange_header(br, prev_end)
            else:
                prev_end = 0
            data = session.get(url, headers=headers, timeout=120).content
            if key:
                data = _aes128_decrypt(data, key, iv)
            f.write(data)
            on_progress(idx, total)
    return init is not None


def _aes128_decrypt(data: bytes, key: bytes, iv: bytes) -> bytes:
    try:
        from cryptography.hazmat.primitives.ciphers import (
            Cipher, algorithms, modes,
        )
    except ImportError as exc:
        raise KinescopeError(
            "для зашифрованного HLS нужен пакет cryptography "
            "(pip install cryptography)."
        ) from exc
    decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    out = decryptor.update(data) + decryptor.finalize()
    pad = out[-1] if out else 0
    if 1 <= pad <= 16 and out[-pad:] == bytes([pad]) * pad:
        out = out[:-pad]
    return out


def download_hls(
    manifest_url,
    session,
    output,
    ffmpeg,
    progress=None,
    manifest_text=None,
    watermark=None,
    label=None,
    font=None,
) -> None:
    """Качает HLS (m3u8): выбирает поток ≤1080p (+звук) и склеивает в mp4."""
    text = (
        manifest_text
        if manifest_text is not None
        else session.get(manifest_url, timeout=60).text
    )
    video_url, audio = _select_hls_variant(text, manifest_url)
    tmp = tempfile.mkdtemp(prefix="hls_")
    try:
        cap = 0.5 if watermark else 0.97
        v_span = cap * (0.62 if audio else 0.98)

        def v_prog(i, n):
            if progress:
                progress(min(v_span, i / n * v_span))

        video_file = os.path.join(tmp, "video.bin")
        v_fmp4 = _download_hls_media(video_url, session, video_file, v_prog)
        input_files = [video_file]
        video_stream = "0:v:0"
        audio_stream = "0:a:0?"
        audio_fmp4 = v_fmp4
        if audio and audio.get("uri"):
            audio_file = os.path.join(tmp, "audio.bin")

            def a_prog(i, n):
                if progress:
                    progress(min(cap, v_span + i / n * (cap - v_span)))

            audio_fmp4 = _download_hls_media(
                audio["uri"], session, audio_file, a_prog
            )
            input_files = [video_file, audio_file]
            audio_stream = "1:a:0"
        mux_prog = None
        if watermark and progress:
            mux_prog = lambda f: progress(0.5 + f * 0.5)
        _run_mux(
            ffmpeg, input_files, video_stream, audio_stream, output,
            audio_bsf=not audio_fmp4, watermark=watermark,
            progress=mux_prog, label=label, font=font,
        )
        if progress:
            progress(1)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def download_manifest(
    manifest_url,
    session,
    output,
    ffmpeg,
    progress=None,
    watermark=None,
    label=None,
    font=None,
) -> None:
    """Скачивает произвольный манифест: DASH (.mpd) или HLS (.m3u8)."""
    head = ""
    if not (manifest_url.endswith(".mpd") or manifest_url.endswith(".m3u8")):
        head = session.get(manifest_url, timeout=60).text
    if manifest_url.endswith(".mpd") or "<MPD" in head[:400].upper():
        download_dash(
            manifest_url, session, output, ffmpeg, progress,
            watermark=watermark, label=label, font=font,
        )
        return
    download_hls(
        manifest_url, session, output, ffmpeg, progress,
        manifest_text=head or None, watermark=watermark, label=label, font=font,
    )


def _which(*names: str) -> Optional[str]:
    for n in names:
        path = shutil.which(n)
        if path:
            return path
    return None


def download_with_ytdlp(
    manifest_url: str, output: str, referer: str, quality
) -> bool:
    ytdlp = _which("yt-dlp", "youtube-dl")
    if not ytdlp:
        return False
    fmt = quality or "bv*+ba/b"
    cmd = [
        ytdlp, "--referer", referer, "--add-header", f"Origin:{BASE_URL}",
        "-f", fmt, "--merge-output-format", "mp4", "-o", output, manifest_url,
    ]
    print(f"→ Качаю через yt-dlp: {' '.join(cmd)}")
    return subprocess.run(cmd).returncode == 0


def download_with_ffmpeg(manifest_url: str, output: str, referer: str) -> bool:
    ffmpeg = _which("ffmpeg")
    if not ffmpeg:
        return False
    headers = f"Referer: {referer}\r\nOrigin: {BASE_URL}\r\n"
    cmd = [
        ffmpeg, "-y", "-headers", headers,
        "-user_agent", DEFAULT_HEADERS["User-Agent"],
        "-i", manifest_url, "-c", "copy", "-bsf:a", "aac_adtstoasc", output,
    ]
    print(f"→ Качаю через ffmpeg: {manifest_url}")
    return subprocess.run(cmd).returncode == 0


def download(
    manifest_url: str, output: str, referer: str, quality
) -> None:
    if download_with_ytdlp(manifest_url, output, referer, quality):
        return
    if download_with_ffmpeg(manifest_url, output, referer):
        return
    raise KinescopeError(
        "Не найден ни yt-dlp, ни ffmpeg — нечем скачивать.\n"
        "Установи один из них:\n"
        "    pip install yt-dlp        # рекомендуется (выбор качества, DASH+HLS)\n"
        "    # либо системный ffmpeg (apt/brew/choco install ffmpeg)"
    )


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Скачивание видео с Kinescope (без обхода DRM).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Примеры:\n"
            "  # Автоопределение по ссылке на видео:\n"
            "  python kinescope_dl.py https://kinescope.io/xxxxxxxx "
            "-r https://site-s-kursom.ru/lesson\n\n"
            "  # Ручной режим: манифест пойман в DevTools -> Network:\n"
            "  python kinescope_dl.py --manifest 'https://.../master.mpd' "
            "-r https://site.ru -o out.mp4\n\n"
            "  # Только показать найденные ссылки, не качать:\n"
            "  python kinescope_dl.py https://kinescope.io/xxxxxxxx --list\n"
        ),
    )
    parser.add_argument(
        "video", nargs="?",
        help="URL видео или его ID (можно опустить, если задан --manifest).",
    )
    parser.add_argument(
        "-r", "--referer", default="",
        help="Referer — страница, где встроен плеер. Часто обязателен, "
             "иначе Kinescope отдаёт 403.",
    )
    parser.add_argument(
        "-o", "--output", default="",
        help="Имя выходного файла (по умолчанию <video_id>.mp4).",
    )
    parser.add_argument(
        "-f", "--quality", default=None,
        help="Формат/качество для yt-dlp (например 'bv*[height<=720]+ba'). "
             "По умолчанию — лучшее.",
    )
    parser.add_argument(
        "--manifest", default="",
        help="Прямая ссылка на .mpd/.m3u8 (ручной режим, автоопределение "
             "пропускается).",
    )
    parser.add_argument(
        "--list", action="store_true",
        help="Только найти и вывести ссылки на манифесты, не скачивать.",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Подробный лог запросов.",
    )
    args = parser.parse_args(argv)
    if not args.video and not args.manifest:
        parser.error("нужно указать URL/ID видео или --manifest")

    session = requests.Session()
    try:
        if args.manifest:
            manifest_url = args.manifest
            referer = args.referer or BASE_URL
            video_id = "video"
        else:
            video_id = extract_video_id(args.video)
            referer = args.referer or f"{BASE_URL}/{video_id}"
            print(f"Ищу манифесты для видео {video_id}...")
            manifests = resolve_manifests(
                video_id, referer, session, verbose=args.verbose
            )
            if not manifests:
                raise KinescopeError(
                    "Не удалось найти ссылку на манифест.\n"
                    "Причины и что делать:\n"
                    "  • Видео защищено DRM — скачать нельзя.\n"
                    "  • Нужен корректный --referer (страница с плеером).\n"
                    "  • Kinescope изменил разметку — поймай .mpd/.m3u8 вручную\n"
                    "    в DevTools -> Network и передай через --manifest."
                )
            print("Найдены манифесты:")
            for u in manifests.dash:
                print(f"  [DASH] {u}")
            for u in manifests.hls:
                print(f"  [HLS ] {u}")
            if args.list:
                return 0
            manifest_url = manifests.best
        if args.list:
            print(manifest_url)
            return 0
        output = args.output or f"{video_id}.mp4"
        download(manifest_url, output, referer, args.quality)
        print(f"✓ Готово: {output}")
        return 0
    except KinescopeError as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nПрервано.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
