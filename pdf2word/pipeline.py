"""Конвейер: страница PDF → распознанная структура → документ Word."""

from __future__ import annotations

import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from statistics import median
from typing import Callable

import cv2
import numpy as np

from . import imageops, layout, metrics, tables as tbl, textfix
from .engine import Cancelled, Engine, OcrError, TWord
from .layout import ColumnGroup, Line, Para, Word

XH_RATIO = 0.447         # высота строчных / кегль (Times New Roman)
LINE_H = 1.149           # высота строки при одинарном интервале / кегль (TNR)
COMMON_SIZES = [6, 7, 8, 9, 10, 11, 12, 14, 16, 18, 20, 22, 24, 26, 28, 36, 48, 72]
DUAL_PASS = 0.375        # с такой силы повышения резкости сверяем с вариантом без неё


@dataclass
class Options:
    remove_stamps: bool = True       # стирать синие печати и подписи
    langs: str = "rus"
    workers: int = 0                 # 0 — по числу ядер (не больше 4)


@dataclass
class PageResult:
    index: int
    width_px: int
    height_px: int
    dpi: float
    elements: list = field(default_factory=list)   # Para | ColumnGroup | Table
    body: tuple = (0, 0, 0, 0)                     # x0, y0, x1, y1 содержимого
    body_size: float = 12.0
    rotated: int = 0
    ocr_score: float = 0.0                         # сколько текста прочитано уверенно


ProgressFn = Callable[[float, str], None]


# --------------------------------------------------------------------------

def _orient(engine: Engine, gray: np.ndarray, dpi: int, blurred: bool = False) -> tuple[int, str]:
    """На сколько градусов (по часовой) повернуть страницу и какая письменность."""
    rot, conf, script, sconf = engine.osd(imageops.png_bytes(gray, dpi), dpi)
    script = script if sconf >= 1.0 else ""
    # на размытом скане определитель поворота ошибается уверенно (и видит
    # «иврит» в русском тексте) — ему верим только при большом запасе,
    # иначе проверяем распознаванием
    if blurred:
        trusted = conf >= 5.0 and script in ("Cyrillic", "Latin")
    else:
        trusted = conf >= 1.5
    if trusted:
        return rot, script
    ink = imageops.binarize(gray)
    vertical = imageops.text_is_vertical(ink)
    if vertical is None:
        return (rot if conf >= 1.5 else 0), script
    candidates = [90, 270] if vertical else [0, 180]
    # сравниваем, сколько текста читается уверенно в фрагменте в полстраницы
    # вокруг середины текста; зерно и соринки убираем — на них Tesseract
    # ищет буквы долго и впустую
    h, w = gray.shape
    ys, xs = np.nonzero(ink[::4, ::4])
    if len(ys) < 50:
        return (rot if conf >= 1.5 else 0), script
    y0 = int(min(max(0, 4 * np.median(ys) - h // 4), h - h // 2))
    x0 = int(min(max(0, 4 * np.median(xs) - w // 4), w - w // 2))
    cink = ink[y0:y0 + h // 2, x0:x0 + w // 2]
    n, lab, st, _ = cv2.connectedComponentsWithStats(cink, connectivity=8)
    specks = np.where(st[:, cv2.CC_STAT_AREA] < max(12, int(30 * (dpi / 300.0) ** 2)))[0]
    crop = np.where(cink > 0, 0, 255).astype(np.uint8)
    crop[np.isin(lab, specks[specks > 0])] = 255
    scores = {}
    for c in candidates:
        words = engine.tsv(imageops.png_bytes(imageops.rotate90(crop, c), dpi), 6, dpi)
        scores[c] = sum(len(wd.text) for wd in words if len(wd.text) >= 3 and wd.conf >= 60)
    best, other = sorted(candidates, key=lambda c: -scores[c])
    if scores[best] < max(15, 1.3 * scores[other]) and rot in candidates and conf >= 1.5:
        return rot, script          # распознавание не решило — слово за определителем
    return best, script


def _short_segments(ink: np.ndarray, xh: float, exclude: np.ndarray) -> list[tbl.Segment]:
    """Короткие горизонтальные линии: подчёркивания и поля «______»."""
    k = int(max(2.8 * xh, 40))
    opened = cv2.morphologyEx(ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (k, 1)))
    if exclude is not None:
        opened[exclude > 0] = 0
    n, _, stats, _ = cv2.connectedComponentsWithStats(opened, connectivity=8)
    segs = []
    max_t = max(8, int(0.6 * xh))
    for i in range(1, n):
        x, y, w, h, _ = stats[i]
        if w >= k and h <= max_t:
            segs.append(tbl.Segment(x, y, x + w, y + h, True))
    return segs


def _remove_specks(gray: np.ndarray, ink: np.ndarray, max_area: int) -> None:
    n, labels, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    small = np.where(stats[1:, cv2.CC_STAT_AREA] <= max_area)[0] + 1
    if len(small):
        mask = np.isin(labels, small)
        gray[mask] = 255
        ink[mask] = 0


def _lines_from_words(twords: list[TWord], offset=(0, 0), key_prefix=()) -> list[Line]:
    groups: dict[tuple, list[Word]] = {}
    ox, oy = offset
    for t in twords:
        key = key_prefix + (t.page, t.block, t.par, t.line)
        x0, y0 = max(0, t.x0 + ox), max(0, t.y0 + oy)
        x1, y1 = max(x0 + 1, t.x1 + ox), max(y0 + 1, t.y1 + oy)
        groups.setdefault(key, []).append(Word(t.text, x0, y0, x1, y1, t.conf))
    lines = []
    for key, ws in groups.items():
        ws.sort(key=lambda w: w.x0)
        lines.append(Line(_join_split_letters(ws), key=key))
    return lines


STANDALONE = set("АВИКОСУЯ")


def _join_split_letters(ws: list[Word]) -> list[Word]:
    """«П редставитель» → «Представитель»: первая буква оторвалась от слова."""
    out: list[Word] = []
    for w in ws:
        if out:
            p = out[-1]
            h = max(p.y1 - p.y0, w.y1 - w.y0)
            if len(p.text) == 1 and p.text.isupper() and p.text not in STANDALONE and \
                    textfix.CYR.match(p.text) and re.match(r"[а-яё]", w.text) and \
                    w.x0 - p.x1 < 0.45 * h:
                out[-1] = Word(p.text + w.text, p.x0, min(p.y0, w.y0), w.x1, max(p.y1, w.y1),
                               min(p.conf, w.conf))
                continue
        out.append(w)
    return out


def _clean_cell_crop(crop: np.ndarray, pad: int) -> None:
    """Стирает остатки линий таблицы, попавшие в вырезку ячейки: тонкие
    длинные штрихи вдоль краёв и сквозные линии. Такие обрывки сбивают
    распознавание одиночных цифр («2» с чертой сверху читалась как «Волл»)."""
    inner = crop[pad:-pad, pad:-pad]
    H, W = inner.shape
    if H < 6 or W < 6:
        return
    ink = cv2.threshold(inner, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    ink[inner > 200] = 0
    n, labels, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    edge = 9
    for i in range(1, n):
        x, y, w, h, _ = stats[i]
        horiz = h <= 6 and (w >= 0.85 * W or (w >= 0.4 * W and (y <= edge or y + h >= H - edge)))
        vert = w <= 6 and (h >= 0.95 * H or (h >= 0.4 * H and (x <= edge or x + w >= W - edge)))
        if horiz or vert:
            inner[labels == i] = 255


def _glyph_crop(crop: np.ndarray, xh: float, scale: float = 1.5, faint: float = 140.0):
    """Плотная вырезка вокруг символов: бледный фон и обрывки линий убраны,
    добавлены поля, картинка увеличена — так Tesseract увереннее читает
    одиночные цифры и короткие слова. faint — порог «настоящей» краски
    (на размытом скане буквы светлее)."""
    if int(np.count_nonzero(crop < faint)) < 15:
        return None             # только бледные следы линий — букв нет
    dark_px = crop[crop < 250]
    dark = float(np.percentile(dark_px, 5))
    thr = dark + 0.6 * (255 - dark)
    c = crop.copy()
    c[c > thr] = 255
    ink = (c < thr).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    strong = dark + 0.35 * (255 - dark)
    keep = []
    for i in range(1, n):
        x, y, w, h, area = st[i]
        if area < 6:
            continue
        if h <= 6 and w >= 3 * max(h, 1) and w > 1.2 * xh:
            continue            # горизонтальный обрывок линии
        if w <= 6 and h >= 2.5 * xh:
            continue            # вертикальный обрывок линии
        if c[y:y + h, x:x + w][lab[y:y + h, x:x + w] == i].min() > strong:
            continue            # бледный след линии рядом с чёткой цифрой
        keep.append(i)
    if not keep:
        return None
    x0 = min(st[i, 0] for i in keep)
    y0 = min(st[i, 1] for i in keep)
    x1 = max(st[i, 0] + st[i, 2] for i in keep)
    y1 = max(st[i, 1] + st[i, 3] for i in keep)
    if y1 - y0 > 2.4 * xh or y1 - y0 < 0.3 * xh:
        return None             # несколько строк или пылинка
    out = np.full_like(c, 255)
    mask = np.isin(lab, keep)
    out[mask] = c[mask]
    pad = int(max(12, 0.8 * xh))
    out = cv2.copyMakeBorder(out[y0:y1, x0:x1], pad, pad, pad, pad,
                             cv2.BORDER_CONSTANT, value=255)
    if scale != 1.0:
        out = cv2.resize(out, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    return out, (int(x0) - pad, int(y0) - pad, scale)


def _alnum_count(words) -> int:
    return sum(ch.isalnum() for w in words for ch in w.text)


NUMBER = re.compile(r"[\d\s.,/\-–]*\d[\d\s.,/\-–]*")
ONE_LIKE = re.compile(r"[lI|!ı]")


def _is_number(text: str) -> bool:
    return bool(NUMBER.fullmatch(text.strip()))


def _reading_conf(words: list[TWord]) -> float:
    """Уверенность прочтения — по словам с буквами и цифрами: уверенно
    прочитанный обрывок линии «——» не должен вытягивать мусор рядом."""
    core = [w.conf for w in words if any(ch.isalnum() for ch in w.text)] or [w.conf for w in words]
    return float(np.mean(core))


def _numeric_columns(cands: dict[int, list[tuple]], jobs: list) -> set[tuple[int, int]]:
    """Столбцы таблиц, где почти все заполненные ячейки — числа (номера
    строк, количество, суммы). Ячейка считается числовой, если хоть одно её
    достаточно уверенное прочтение — число."""
    stats: dict[tuple[int, int], list[int]] = {}
    for i, (ti, cell, _) in enumerate(jobs):
        cs = cands.get(i)
        if not cs or cell.c1 - cell.c0 != 1:
            continue
        st = stats.setdefault((ti, cell.c0), [0, 0])
        st[0] += any(_is_number(c[0]) and c[1] >= 50 for c in cs)
        st[1] += 1
    return {key for key, (num, total) in stats.items() if num >= 2 and num >= 0.6 * total}


def _pick_reading(cands: list[tuple], numeric: bool):
    """Выбор между прочтениями ячейки: (текст, уверенность, слова, модель),
    модель — "old" (первый проход), "rus" или "eng" (повтор по вырезке)."""
    old = next((c for c in cands if c[3] == "old"), None)
    rus = [c for c in cands if c[3] != "eng"]
    ok = []
    for c in cands:
        if c[3] == "eng" and textfix.LAT.search(c[0]):
            if any(textfix.looks_same(r[0], c[0]) >= 0.8 for r in rus):
                continue        # «п/п» → «n/n»: те же буквы латиницей
            if any(r[1] >= 60 for r in rus):
                continue        # «шт.» → «LUT.»: русское прочтение уверенное
        if old is not None and c is not old and _is_number(old[0]) and \
                sum(ch.isdigit() for ch in c[0]) < sum(ch.isdigit() for ch in old[0]):
            continue            # «1» не меняем на «l», «12» — на «1»
        ok.append(c)
    if not ok:
        return None
    if numeric:
        # в столбце чисел («№», «Кол-во») буква вместо цифры — почти всегда ошибка;
        # одиночные «l», «I», «|» там — это единица
        ok = [(ONE_LIKE.sub("1", c[0]), c[1],
               [TWord(w.page, w.block, w.par, w.line, w.x0, w.y0, w.x1, w.y1, w.conf,
                      ONE_LIKE.sub("1", w.text)) for w in c[2]], c[3])
              if ONE_LIKE.fullmatch(c[0]) else c for c in ok]
        nums = [c for c in ok if _is_number(c[0]) and c[1] >= 40]
        if nums:
            ok = nums

    def norm(t: str) -> str:
        return t.replace(" ", "")

    def score(c) -> float:
        sc = c[1]
        sc += 15 * sum(1 for o in ok if o is not c and norm(o[0]) == norm(c[0]))
        if c is old:
            sc += 3                 # замена — только при заметном перевесе
        if c[3] == "eng":
            sc -= 5                 # английской модели верим чуть меньше
        if old is not None and c is not old and _is_number(old[0]) and not _is_number(c[0]):
            sc -= 20                # число на буквы меняем только при явном перевесе
        return sc

    return max(ok, key=score)


def _lone_one(img: np.ndarray, xh: float) -> tuple[int, int, int, int] | None:
    """Единственный тонкий вертикальный штрих высотой с цифру — «1»
    (одиночную единицу Tesseract часто не читает вовсе). Рамка штриха или None."""
    ink = cv2.threshold(img, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    n, _, st, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    big = [st[i] for i in range(1, n) if st[i][cv2.CC_STAT_AREA] >= 0.05 * xh * xh]
    if len(big) != 1:
        return None
    x, y, w, h, _ = big[0]
    if 0.9 * xh <= h <= 2.0 * xh and w >= 2 and w <= 0.5 * h:
        return int(x), int(y), int(x + w), int(y + h)
    return None


def _retry_short_cells(engine: Engine, words: list[TWord], crops: list[np.ndarray],
                       jobs: list, dpi: int, langs: str, xh: float,
                       faint: float = 140.0) -> list[TWord]:
    """Ячейки с одной короткой строкой («1», «шт.», «500») распознаём ещё раз
    по плотной увеличенной вырезке русской и английской моделями и выбираем
    прочтение: по уверенности, по совпадению вариантов и по соседним ячейкам
    столбца (в столбце номеров строк ждём число)."""
    by_page: dict[int, list[TWord]] = {}
    for w in words:
        by_page.setdefault(w.page, []).append(w)
    retry, tight = [], []
    for i, crop in enumerate(crops):
        ws = by_page.get(i + 1, [])
        chars = sum(len(w.text) for w in ws)
        weak = any(w.conf < 85 for w in ws)
        if ws and chars > 4 and not (weak and chars <= 12):
            continue
        g = _glyph_crop(crop, xh, faint=faint)
        if g is None:
            continue
        retry.append((i, g[1]))
        tight.append(g[0])
    if not tight:
        return words
    stack = imageops.tiff_stack(tight, int(dpi * 1.5))
    variants = [("rus", engine.tsv(stack, 7, int(dpi * 1.5), langs))]
    if "eng" not in langs and engine.has_lang("eng"):
        variants.append(("eng", engine.tsv(stack, 7, int(dpi * 1.5), "eng")))
    results = []
    for model, res in variants:
        d: dict[int, list[TWord]] = {}
        for w in res:
            d.setdefault(w.page, []).append(w)
        results.append((model, d))
    # прочтения каждой ячейки: (текст, уверенность, слова, модель)
    cands: dict[int, list[tuple]] = {}
    for i in range(len(crops)):
        old = by_page.get(i + 1, [])
        if old:
            cands[i] = [(" ".join(w.text for w in old), _reading_conf(old), old, "old")]
    for k, (i, (ox, oy, sc)) in enumerate(retry):
        for model, d in results:
            new = d.get(k + 1, [])
            # «о 3»: соринка с почти нулевой уверенностью рядом с цифрой
            new = [t for t in new if t.conf >= 20 or len(t.text) > 2] or new
            if not new or not _alnum_count(new):
                continue
            placed = [TWord(i + 1, 1, 1, 1, int(t.x0 / sc) + ox, int(t.y0 / sc) + oy,
                            int(t.x1 / sc) + ox, int(t.y1 / sc) + oy, t.conf, t.text)
                      for t in new]
            cands.setdefault(i, []).append(
                (" ".join(w.text for w in new), _reading_conf(new), placed, model))
    numeric = _numeric_columns(cands, jobs)
    for k, (i, (ox, oy, sc)) in enumerate(retry):
        ti, cell, _ = jobs[i]
        in_numeric = (ti, cell.c0) in numeric and cell.c1 - cell.c0 == 1
        if in_numeric and not cands.get(i):
            # в столбце чисел ничего не прочитано, а в клетке один тонкий
            # штрих высотой с цифру — это «1»
            box = _lone_one(tight[k], xh * sc)
            if box is not None:
                bx0, by0, bx1, by1 = box
                by_page[i + 1] = [TWord(i + 1, 1, 1, 1, int(bx0 / sc) + ox, int(by0 / sc) + oy,
                                        int(bx1 / sc) + ox, int(by1 / sc) + oy, 60.0, "1")]
                continue
        best = _pick_reading(cands.get(i, []), in_numeric)
        if best is not None and best[3] != "old":
            by_page[i + 1] = best[2]
    out: list[TWord] = []
    for page in sorted(by_page):
        out.extend(by_page[page])
    return out


SUSPECT_CHARS = set("\\[]{}$!|@#^~<>")


def _suspect(w: TWord) -> bool:
    letters = sum(ch.isalpha() for ch in w.text)
    if not letters:
        return False
    if w.conf < 75:
        return True
    inner = w.text[1:-1]
    return w.conf < 90 and any(ch in SUSPECT_CHARS for ch in inner)


def _latin_pass(engine: Engine, words: list[TWord], image_of: Callable[[int], np.ndarray],
                dpi: int, xh: float, skip=None) -> list[TWord]:
    """Второй проход для английских слов.

    Русская модель превращает «Lenovo» в «Гепоуо» с низкой уверенностью.
    Такие куски строки распознаём ещё раз английской моделью и берём
    вариант, в котором Tesseract заметно увереннее."""
    if not words or not engine.has_lang("eng"):
        return words
    lines: dict[tuple, list[TWord]] = {}
    for w in words:
        lines.setdefault((w.page, w.block, w.par, w.line), []).append(w)
    runs = []
    for key, ws in lines.items():
        ws.sort(key=lambda w: w.x0)
        cur: list[TWord] = []
        for w in ws:
            if _suspect(w):
                cur.append(w)
            else:
                if cur:
                    runs.append(cur)
                cur = []
        if cur:
            runs.append(cur)
    if not runs:
        return words
    crops, meta = [], []
    border = 12
    for run in runs:
        rus_conf = float(np.mean([w.conf for w in run]))
        junk = any(ch in SUSPECT_CHARS for w in run for ch in w.text[1:-1])
        if rus_conf >= 40 and not junk:
            continue                    # русское прочтение достаточно уверенное
        if all(w.text.strip(".,;:!?()«»\"'") in textfix.SHORT_WORDS for w in run):
            continue                    # «в», «и», «с» — не трогаем
        if skip is not None and skip(run):
            continue                    # следы печатей и подписей
        img = image_of(run[0].page)
        if img is None:
            continue
        pad = int(max(6, 0.4 * xh))
        x0 = max(0, min(w.x0 for w in run) - pad)
        y0 = max(0, min(w.y0 for w in run) - pad)
        x1 = min(img.shape[1], max(w.x1 for w in run) + pad)
        y1 = min(img.shape[0], max(w.y1 for w in run) + pad)
        if x1 - x0 < 4 or y1 - y0 < 4:
            continue
        piece = img[y0:y1, x0:x1].copy()
        dark_px = piece[piece < 250]
        if dark_px.size:
            dark = float(np.percentile(dark_px, 5))
            piece[piece > dark + 0.6 * (255 - dark)] = 255     # бледный фон и обрывки линий
        crop = cv2.copyMakeBorder(piece, border, border, border, border,
                                  cv2.BORDER_CONSTANT, value=255)
        crop = cv2.resize(crop, None, fx=1.5, fy=1.5, interpolation=cv2.INTER_CUBIC)
        crops.append(crop)
        meta.append((run, x0 - border, y0 - border))
    if not crops:
        return words
    second = engine.tsv(imageops.tiff_stack(crops, int(dpi * 1.5)), 7, int(dpi * 1.5), "eng")
    by_page: dict[int, list[TWord]] = {}
    for w in second:
        by_page.setdefault(w.page, []).append(w)
    replace: dict[int, list[TWord]] = {}
    drop: set[int] = set()
    for k, (run, ox, oy) in enumerate(meta):
        new = by_page.get(k + 1, [])
        if not new or not any(textfix.LAT.search(w.text) for w in new):
            continue
        # медиана, а не среднее: одно плохо прочитанное слово (артикул
        # на размытом скане) не должно перечёркивать «Lenovo» рядом
        rus_conf = float(np.median([w.conf for w in run]))
        eng_conf = float(np.median([w.conf for w in new]))
        if eng_conf < 80 or eng_conf < rus_conf + 30:
            continue
        rus_text = " ".join(w.text for w in run)
        eng_text = " ".join(w.text for w in new)
        if textfix.looks_same(rus_text, eng_text) >= 0.8:
            continue                    # те же буквы, только «латиницей»
        first = run[0]
        for w in run:
            drop.add(id(w))
        replace[id(first)] = [TWord(first.page, first.block, first.par, first.line,
                                    int(w.x0 / 1.5) + ox, int(w.y0 / 1.5) + oy,
                                    int(w.x1 / 1.5) + ox, int(w.y1 / 1.5) + oy, w.conf, w.text)
                              for w in new]
    if not replace:
        return words
    out: list[TWord] = []
    for w in words:
        if id(w) in replace:
            out.extend(replace[id(w)])
        elif id(w) not in drop:
            out.append(w)
    return out


def _smooth_xh(lines: list[Line], page_xh: float) -> None:
    if not lines:
        return
    ordered = sorted(lines, key=lambda l: l.base)
    for i, ln in enumerate(ordered):
        n = sum(len(w.text) for w in ln.words if not w.fill)
        if n >= 14 or ln.sure:
            continue        # длинная строка или много строчных букв — мерили точно
        neigh = [o.xh for o in ordered[max(0, i - 3):i + 4] if o is not ln and
                 sum(len(w.text) for w in o.words) >= 14]
        ref = float(median(neigh)) if neigh else page_xh
        # занижение — почти всегда ошибка измерения; завышение может быть
        # настоящим заголовком крупным шрифтом, его не трогаем
        if ref and ln.xh < 0.75 * ref:
            ln.xh = ref


def _in_zone(zone, w: Word) -> float:
    if zone is None:
        return 0.0
    crop = zone[w.y0:w.y1, w.x0:w.x1]
    return cv2.countNonZero(crop) / max(1, crop.size)


def _clean_lines(lines: list[Line], ink: np.ndarray, page_xh: float = 0.0,
                 zone=None) -> list[Line]:
    out = []
    for ln in lines:
        if zone is not None:
            # следы печатей и подписей: одиночные знаки в зоне стёртого цвета
            ws = ln.words
            kept = []
            for i, w in enumerate(ws):
                if w.fill or _in_zone(zone, w) < 0.3:
                    kept.append(w)
                    continue
                n = sum(ch.isalnum() for ch in w.text)
                if n == 0 and w.conf < 90:
                    continue
                if w.conf < 50 and n <= 3:
                    continue
                kept.append(w)
            # одиночная буква в зоне — только если стоит между словами
            final = []
            for i, w in enumerate(kept):
                n = sum(ch.isalnum() for ch in w.text)
                if not w.fill and n == 1 and w.conf < 85 and _in_zone(zone, w) >= 0.3:
                    xh0 = ln.xh or 20
                    left = kept[i - 1] if i > 0 else None
                    right = kept[i + 1] if i + 1 < len(kept) else None
                    ok = left is not None and right is not None and \
                        w.x0 - left.x1 < 1.5 * xh0 and right.x0 - w.x1 < 1.5 * xh0 and \
                        sum(ch.isalpha() for ch in left.text) >= 2 and \
                        sum(ch.isalpha() for ch in right.text) >= 2
                    if not ok:
                        continue
                final.append(w)
            ln.words = final
            if not final:
                continue
        if page_xh and ln.xh < 0.45 * page_xh and \
                sum(len(w.text) for w in ln.words if not w.fill) < 5:
            continue        # крошечные «буквы» — точки и обрывки печати
        keep = []
        for w in ln.words:
            if w.fill:
                keep.append(w)
                continue
            if textfix.is_noise(w.text, w.conf):
                continue
            if w.conf < 50 and len(w.text) <= 3 and textfix.LAT.search(w.text) and \
                    not textfix.CYR.search(w.text):
                continue     # обрывки латиницы от подписей и печатей
            if textfix.is_dash_only(w.text):
                crop = ink[w.y0:w.y1, w.x0:w.x1]
                dens = cv2.countNonZero(crop) / max(1, crop.size)
                if dens < 0.12 or w.text in ("|", "||") or (w.text == "_" and dens < 0.3):
                    continue
                if w.text in ("-", "–", "—") and ln.xh:
                    rel = (w.x1 - w.x0) / ln.xh
                    w.text = "-" if rel < 0.85 else ("–" if rel < 1.6 else "—")
            keep.append(w)
        # одинокие знаки препинания вдали от слов — мусор
        xh = ln.xh or 20
        gaps = [b.x0 - a.x1 for a, b in zip(keep, keep[1:])]
        typical_gap = float(median(gaps)) if gaps else xh
        filtered = []
        for i, w in enumerate(keep):
            if not w.fill and not any(ch.isalnum() for ch in w.text) and \
                    not textfix.is_dash_only(w.text):
                left = keep[i - 1] if i > 0 else None
                right = keep[i + 1] if i + 1 < len(keep) else None
                gl = w.x0 - left.x1 if left else 1e9
                gr = right.x0 - w.x1 if right else 1e9
                isolated = min(gl, gr) > max(1.2 * xh, 2.5 * typical_gap)
                meaningful = w.text in textfix.SYMBOLS and w.conf >= 70
                if w.conf < 60 or (isolated and not meaningful):
                    continue
            filtered.append(w)
        keep = filtered
        if not keep:
            continue
        real = [w for w in keep if not w.fill]
        if real and not any(w.fill for w in keep):
            confs = [w.conf for w in real]
            letters = sum(sum(ch.isalnum() for ch in w.text) for w in real)
            if np.mean(confs) < 35 and letters < 6:
                continue
            if np.mean(confs) < 20:
                continue
        ln.words = keep
        out.append(ln)
    return out


def _attach_fills(lines: list[Line], fills: list[tbl.Segment], xh: float) -> list[Line]:
    """Линии «______» превращаются в подчёркивания-«слова» своей строки.

    Если на линии уже написан текст («Организация: АО ...» на длинной
    черте), остаток линии справа и слева от текста становится полем."""
    em = xh / XH_RATIO

    def fill_word(x0, x1, s):
        n = max(3, int(round((x1 - x0) / (0.5 * em))))
        return Word("_" * n, int(x0), int(s.y0 - 0.9 * xh), int(x1), s.y1, 100.0, fill=True)

    for s in fills:
        # 1) текст, стоящий прямо на линии
        host = None
        for ln in lines:
            lxh = ln.xh or xh
            base = ln.base or ln.y1
            if any(w.fill for w in ln.words):
                continue
            if s.y0 - 0.9 * lxh <= base <= s.y1 + 0.4 * lxh and \
                    any(o.x0 < s.x1 and o.x1 > s.x0 for o in ln.words):
                host = ln
                break
        if host is not None:
            busy = sorted((o.x0 - 0.5 * xh, o.x1 + 0.5 * xh) for o in host.words
                          if o.x0 < s.x1 and o.x1 > s.x0)
            pos = s.x0
            free = []
            for a0, a1 in busy:
                if a0 > pos:
                    free.append((pos, a0))
                pos = max(pos, a1)
            if pos < s.x1:
                free.append((pos, s.x1))
            for f0, f1 in free:
                if f1 - f0 >= 2 * xh:
                    host.words.append(fill_word(f0, f1, s))
            host.words.sort(key=lambda q: q.x0)
            continue
        # 2) линия рядом с текстом на той же высоте
        w = fill_word(s.x0, s.x1, s)
        target = None
        best = 1e9
        for ln in lines:
            lxh = ln.xh or xh
            base = ln.base or ln.y1
            if ln.y0 - 0.3 * lxh <= s.y0 <= base + 1.3 * lxh:
                gap = max(0, ln.x0 - s.x1, s.x0 - ln.x1)
                if gap < best and not any(o.x0 < s.x1 and o.x1 > s.x0 for o in ln.words):
                    best, target = gap, ln
        if target is not None and best < 0.4 * (s.x1 - s.x0) + 6 * xh:
            target.words.append(w)
            target.words.sort(key=lambda q: q.x0)
        else:
            lines.append(Line([w], xh=xh, base=s.y1, key=("fill", s.x0, s.y0)))
    return lines


def _mark_underlines(lines: list[Line], unders: list[tbl.Segment]) -> None:
    if not unders:
        return
    for ln in lines:
        xh = ln.xh or 20
        for w in ln.words:
            if w.fill:
                continue
            for s in unders:
                y = (s.y0 + s.y1) / 2
                if not (ln.base - 0.35 * xh <= y <= ln.base + 0.75 * xh):
                    continue
                ov = min(w.x1, s.x1) - max(w.x0, s.x0)
                if ov >= 0.5 * (w.x1 - w.x0):
                    w.underline = True
                    break


def _merge_fills(fills: list[tbl.Segment], xh: float) -> list[tbl.Segment]:
    """Склеивает куски одной линии «______», разорванной печатью."""
    fills = sorted(fills, key=lambda s: (round((s.y0 + s.y1) / 2 / (0.5 * xh)), s.x0))
    out: list[tbl.Segment] = []
    for s in fills:
        if out:
            p = out[-1]
            if abs((p.y0 + p.y1) / 2 - (s.y0 + s.y1) / 2) < 0.4 * xh and 0 <= s.x0 - p.x1 < 3 * xh:
                out[-1] = tbl.Segment(p.x0, min(p.y0, s.y0), s.x1, max(p.y1, s.y1), True)
                continue
        out.append(s)
    return out


def _width_size(p: Para, dpi: float) -> float | None:
    """Кегль Times New Roman, при котором слова займут ту же ширину, что на скане."""
    ws = [w for ln in p.lines for w in ln.words if not w.fill]
    if sum(len(w.text) for w in ws) < 8:
        return None
    em = sum(metrics.ink_width(w.text, w.bold) for w in ws)
    if em <= 0:
        return None
    return sum(w.x1 - w.x0 for w in ws) / em / dpi * 72.0


def _assign_sizes(paras: list[Para], dpi: float) -> None:
    """Кегль — по ширине слов (так текст в Word ложится в те же строки и
    ячейки, даже если на скане другой шрифт), у коротких абзацев — по высоте
    строчных букв с поправкой по остальным абзацам. Интервал — по шагу строк."""
    by_width = []
    for p in paras:
        p.size = p.xh / dpi * 72.0 / XH_RATIO
        sw = _width_size(p, dpi)
        # сильное расхождение — ошибка распознавания или текст вразрядку
        by_width.append(sw if sw and 0.7 <= sw / p.size <= 1.35 else None)
    ratios = [sw / p.size for p, sw in zip(paras, by_width) if sw]
    k = min(1.1, max(0.8, float(median(ratios)))) if ratios else 1.0
    for p, sw in zip(paras, by_width):
        p.size = sw if sw else p.size * k
        p.spacing = 1.0
        if len(p.lines) >= 2:
            pitches = [b.base - a.base for a, b in zip(p.lines, p.lines[1:])]
            m = median(pitches) / (LINE_H * p.size * dpi / 72.0)
            if m < 1.07:
                p.spacing = 1.0
            elif m < 1.3:
                p.spacing = 1.15
            elif m < 1.75:
                p.spacing = 1.5
            elif m < 2.3:
                p.spacing = 2.0


def _all_paras(elements) -> list[Para]:
    out = []
    for el in elements:
        if isinstance(el, Para):
            out.append(el)
        elif isinstance(el, ColumnGroup):
            for cell in el.cells:
                out.extend(cell)
        elif isinstance(el, tbl.Table):
            for cell in el.cells:
                out.extend(cell.paragraphs)
    return out


def _text_len(p: Para) -> int:
    return sum(len(w.text) for ln in p.lines for w in ln.words if not w.fill)


def _snap(size: float) -> float:
    return float(min(COMMON_SIZES, key=lambda c: abs(size - c) / c))


def _is_caption(p: Para) -> bool:
    """Подпись под линией бланка: «(подпись)», «(расшифровка подписи)»."""
    text = " ".join(ln.text for ln in p.lines).strip()
    return len(text) <= 40 and text.startswith("(") and text.endswith(")")


def _dominant(paras: list[Para]) -> float | None:
    weights: dict[float, int] = {}
    for p in paras:
        if _text_len(p) <= 4 or _is_caption(p):
            continue
        s = _snap(p.size)
        weights[s] = weights.get(s, 0) + _text_len(p)
    return max(weights, key=weights.get) if weights else None


def finalize_sizes(pages: list["PageResult"]) -> float:
    """Приводит кегли к стандартным значениям по всему документу."""
    flow_paras: list[Para] = []
    tables: list[tbl.Table] = []
    for page in pages:
        for el in page.elements:
            if isinstance(el, Para):
                flow_paras.append(el)
            elif isinstance(el, ColumnGroup):
                for cell in el.cells:
                    flow_paras.extend(cell)
            elif isinstance(el, tbl.Table):
                tables.append(el)
    all_paras = flow_paras + [p for t in tables for c in t.cells for p in c.paragraphs]
    body = _dominant(flow_paras) or _dominant(all_paras) or 12.0
    # кегли, которыми набран заметный текст документа
    used = sorted({_snap(p.size) for p in all_paras if _text_len(p) >= 8})

    def settle(p: Para, ref: float, tol: float):
        raw = p.size
        if abs(raw - ref) <= tol * ref:
            p.size = ref
        elif _text_len(p) < 8:
            # у короткой надписи кегль измерен грубо: берём ближайший
            # из уже встречающихся в документе
            near = [s for s in used if abs(raw - s) <= 0.15 * s]
            p.size = min(near, key=lambda s: abs(raw - s)) if near else _snap(raw)
        else:
            p.size = _snap(raw)

    # совсем короткие надписи («1», «шт.», «Сдал») меряются ненадёжно —
    # им достаётся кегль соседей
    for p in flow_paras:
        if _text_len(p) <= 4:
            p.size = body
        else:
            settle(p, body, 0.08)
    for t in tables:
        paras = [p for c in t.cells for p in c.paragraphs]
        ref = _dominant(paras) or body
        for p in paras:
            if _text_len(p) > 4:
                settle(p, ref, 0.12)       # в таблице текст обычно одного кегля
        for c in t.cells:
            mates = [p.size for o in t.cells if o is not c and o.r0 < c.r1 and c.r0 < o.r1
                     for p in o.paragraphs if _text_len(p) >= 8]
            short_ref = max(set(mates), key=mates.count) if mates else ref
            for p in c.paragraphs:
                if _text_len(p) <= 4:
                    p.size = short_ref
    for page in pages:
        page.body_size = body
    return body


def _fit_fills(pages: list["PageResult"]) -> None:
    """Число знаков «_» в линиях для заполнения подгоняем под итоговый кегль,
    чтобы линия в Word была той же длины, что на скане (с небольшим запасом,
    иначе длинная линия перескочит на новую строку)."""
    for page in pages:
        for p in _all_paras(page.elements):
            ch = 0.5 * p.size * page.dpi / 72.0      # ширина «_» в Times New Roman
            for ln in p.lines:
                for w in ln.words:
                    if w.fill:
                        w.text = "_" * max(3, int(0.95 * (w.x1 - w.x0) / ch))


def _space_before(seq: list, dpi: float, start_y: float | None) -> None:
    """Вертикальные промежутки между элементами → интервал перед абзацем."""
    prev_bottom = start_y
    prev_base = None
    for el in seq:
        top = el.y0
        if isinstance(el, Para):
            first = el.lines[0]
            pitch = 1.15 * el.size * dpi / 72.0
            if prev_base is not None:
                extra = (first.base - prev_base) - pitch
            elif prev_bottom is not None:
                extra = top - prev_bottom - 0.25 * pitch
            else:
                extra = 0.0
            el.space_before = max(0.0, extra) if extra > 0.35 * pitch else 0.0
            prev_base = el.lines[-1].base
            prev_bottom = el.y1
        else:
            if prev_bottom is not None:
                gap = top - prev_bottom
                el.space_before = max(0.0, gap) if not isinstance(el, tbl.Table) else gap
            prev_base = None
            prev_bottom = el.y1


# --------------------------------------------------------------------------

def process_page(engine: Engine, src: imageops.PageSource, index: int,
                 opts: Options, step: Callable[[float], None] | None = None) -> PageResult:
    step = step or (lambda f: None)
    bgr, info = src.render(index)
    dpi = int(round(info.dpi))
    engine.check()
    step(0.05)

    gray0 = imageops.to_gray(bgr)
    # размытый скан (не в фокусе, смаз, низкое разрешение): перед
    # распознаванием повышаем резкость
    flat0 = imageops.flatten_background(gray0)
    blur = imageops.estimate_blur(flat0, dpi)
    amount = imageops.sharpen_amount(blur)
    noise = imageops.estimate_noise(flat0) if amount >= 0.1 else 0.0
    del flat0
    rot, script = _orient(engine, imageops.sharpen(gray0, amount, dpi, noise), dpi,
                          blurred=blur >= 1.5)
    langs = opts.langs
    if script == "Latin" and "eng" not in langs and engine.has_lang("eng"):
        langs = "eng+" + langs          # английский документ
    step(0.15)
    if rot:
        bgr = imageops.rotate90(bgr, rot)
    color_mask = None
    if opts.remove_stamps and bgr.ndim == 3:
        bgr, color_mask = imageops.remove_color_ink(bgr)
    gray = imageops.flatten_background(imageops.to_gray(bgr))
    del bgr, gray0

    def part(f0: float, f1: float) -> Callable[[float], None]:
        return lambda f: step(f0 + (f1 - f0) * (f - 0.15) / 0.85)

    if amount < DUAL_PASS:
        return _recognize(engine, imageops.sharpen(gray, amount, dpi, noise), color_mask, index,
                          rot, dpi, langs, blur, step)
    # заметно размытый скан: резкость помогает не всегда (смазанному при
    # съёмке может и навредить) — распознаём оба варианта, берём тот,
    # где уверенно прочитано больше текста
    sharp = _recognize(engine, imageops.sharpen(gray, amount, dpi, noise),
                       None if color_mask is None else color_mask.copy(), index, rot, dpi, langs,
                       blur, part(0.15, 0.57))
    plain = _recognize(engine, gray, color_mask, index, rot, dpi, langs, blur, part(0.57, 1.0))
    if plain.ocr_score - sharp.ocr_score > max(20.0, 0.1 * abs(sharp.ocr_score)):
        return plain
    return sharp


def _recognize(engine: Engine, gray: np.ndarray, color_mask: np.ndarray | None, index: int,
               rot: int, dpi: int, langs: str, blur: float,
               step: Callable[[float], None]) -> PageResult:
    """Распознавание подготовленной (повёрнутой, без печатей) страницы."""
    ink = imageops.binarize(gray)
    angle = imageops.estimate_skew(ink)
    if abs(angle) >= 0.08:
        gray = imageops.rotate_small(gray, angle)
        ink = imageops.binarize(gray)
        if color_mask is not None:
            color_mask = imageops.rotate_small(color_mask, angle, 0)
    engine.check()

    step(0.25)
    H, W = gray.shape
    xh = imageops.estimate_xheight(ink)
    zone = None
    if color_mask is not None:
        color_mask[color_mask < 128] = 0
        k = max(3, int(0.8 * xh))
        zone = cv2.dilate(color_mask, np.ones((k, k), np.uint8))
    _remove_specks(gray, ink, max(3, int((dpi / 300.0) ** 2 * 6)))

    tables = tbl.detect_tables(ink, xh)
    grid_mask = np.zeros_like(ink)
    for t in tables:
        grid_mask |= t.line_mask
    tables = [t for t in tables if not t.frame]   # линии рамки стираем, текст — обычный

    segs = _short_segments(ink, xh, grid_mask)
    # обрывки линий таблицы (продолжение границы) — не подчёркивания:
    # они лежат на линии сетки и упираются в вертикальную линию или край
    tol = max(6, int(0.35 * xh))

    def grid_fragment(sg) -> bool:
        cy = (sg.y0 + sg.y1) / 2
        for t in tables:
            if not (t.x0 - tol <= sg.x1 and sg.x0 <= t.x1 + tol):
                continue
            inside = min(sg.x1, t.x1 + tol) - max(sg.x0, t.x0 - tol)
            if inside < 0.5 * (sg.x1 - sg.x0):
                continue        # линия в основном вне таблицы — это поле бланка
            if not any(abs(cy - y) <= tol for y in t.ys):
                continue
            if any(abs(sg.x0 - x) <= tol or abs(sg.x1 - x) <= tol for x in t.xs) or \
                    sg.x0 < t.x0 or sg.x1 > t.x1:
                return True
        return False

    segs = [sg for sg in segs if not grid_fragment(sg)]
    seg_mask = np.zeros_like(ink)
    for s in segs:
        cv2.rectangle(seg_mask, (s.x0 - 1, s.y0 - 2), (s.x1 + 1, s.y1 + 2), 255, -1)
    lines_removed = cv2.bitwise_or(grid_mask, seg_mask)
    clean = gray.copy()
    clean[lines_removed > 0] = 255
    clean_ink = ink.copy()
    clean_ink[lines_removed > 0] = 0

    # подчёркивание (над линией есть текст) или поле для заполнения (пусто)
    unders, fills = [], []
    for s in segs:
        y_top = max(0, int(s.y0 - 1.1 * xh))
        band = clean_ink[y_top:max(y_top + 1, s.y0 - 1), s.x0:s.x1]
        dens = cv2.countNonZero(band) / max(1, band.size)
        # подчёркнутый текст стоит над всей линией, а у поля с надписью в
        # начале («Организация: АО ... ______») текст занимает лишь часть
        cover = float((band.max(axis=0) > 0).mean()) if band.size else 0.0
        (unders if dens > 0.035 and cover >= 0.5 else fills).append(s)

    # --- распознавание текста вне таблиц
    text_img = clean.copy()
    for t in tables:
        cv2.rectangle(text_img, (t.x0 - 4, t.y0 - 4), (t.x1 + 4, t.y1 + 4), 255, -1)

    cell_jobs = []   # (table_idx, cell, crop_offset)
    crops = []
    pad = 20
    for ti, t in enumerate(tables):
        for cell in t.cells:
            inset = max(5, int(0.25 * xh))
            x0, y0 = cell.x0 + inset, cell.y0 + inset
            x1, y1 = cell.x1 - inset, cell.y1 - inset
            if x1 - x0 < 8 or y1 - y0 < 8:
                continue
            region_ink = clean_ink[y0:y1, x0:x1]
            if cv2.countNonZero(region_ink) < 15:
                continue
            crop = np.full((y1 - y0 + 2 * pad, x1 - x0 + 2 * pad), 255, np.uint8)
            crop[pad:-pad, pad:-pad] = clean[y0:y1, x0:x1]
            _clean_cell_crop(crop, pad)
            cell_jobs.append((ti, cell, (x0 - pad, y0 - pad)))
            crops.append(crop)

    step(0.3)

    def ocr_text():
        if cv2.countNonZero(cv2.threshold(text_img, 200, 255, cv2.THRESH_BINARY_INV)[1]) < 30:
            return []
        return engine.tsv(imageops.png_bytes(text_img, dpi), 3, dpi, langs)

    def ocr_cells():
        if not crops:
            return []
        return engine.tsv(imageops.tiff_stack(crops, dpi), 6, dpi, langs)

    with ThreadPoolExecutor(max_workers=2) as pool:
        f_text = pool.submit(ocr_text)
        f_cells = pool.submit(ocr_cells)
        text_words = f_text.result()
        cell_words = f_cells.result()
    step(0.8)
    # «настоящая» краска — темнее середины между чернилами и бумагой
    dark = clean[clean < 200]
    faint = min(200.0, (float(np.percentile(dark, 5)) + 255.0) / 2.0) if dark.size else 140.0
    cell_words = _retry_short_cells(engine, cell_words, crops, cell_jobs, dpi, langs, xh, faint)
    if "eng" not in langs:
        # английские названия и артикулы внутри русского текста
        def in_stamp(run):
            if zone is None:
                return False
            x0, y0 = min(w.x0 for w in run), min(w.y0 for w in run)
            x1, y1 = max(w.x1 for w in run), max(w.y1 for w in run)
            crop = zone[max(0, y0):y1, max(0, x0):x1]
            return crop.size > 0 and cv2.countNonZero(crop) > 0.2 * crop.size

        text_words = _latin_pass(engine, text_words, lambda page: text_img, dpi, xh, in_stamp)
        cell_words = _latin_pass(engine, cell_words,
                                 lambda page: crops[page - 1] if 0 < page <= len(crops) else None,
                                 dpi, xh)
    step(0.85)
    # уверенно прочитанные знаки минус сомнительные — мера качества прочтения
    ocr_score = 0.0
    for w in text_words + cell_words:
        if len(w.text) >= 2:
            ocr_score += len(w.text) if w.conf >= 75 else (-len(w.text) if w.conf < 50 else 0)

    # --- строки
    text_lines = _lines_from_words(text_words, key_prefix=("text",))
    cell_lines: dict[int, list[Line]] = {}
    by_page: dict[int, list[TWord]] = {}
    for t in cell_words:
        by_page.setdefault(t.page, []).append(t)
    for job_i, (ti, cell, off) in enumerate(cell_jobs):
        ws = by_page.get(job_i + 1, [])
        if ws:
            cell_lines[id(cell)] = _lines_from_words(ws, offset=off, key_prefix=("cell", job_i))

    def in_any_table(s: tbl.Segment):
        for t in tables:
            if t.x0 <= s.x0 and s.x1 <= t.x1 and t.y0 <= s.y0 <= t.y1:
                return t
        return None

    # строки, слитые Tesseract из разных колонок, режем сразу и меряем
    text_lines = [seg for ln in text_lines for seg in layout.split_line(ln)]
    for k in list(cell_lines):
        cell_lines[k] = [seg for ln in cell_lines[k] for seg in layout.split_line(ln)]
    for ln in text_lines:
        layout.measure_line(ln, clean_ink)
    for v in cell_lines.values():
        for ln in v:
            layout.measure_line(ln, clean_ink)
    xhs = [ln.xh for ln in text_lines + [l for v in cell_lines.values() for l in v]
           if len(ln.words) >= 3]
    page_xh = float(median(xhs)) if xhs else xh
    # у коротких строк высота меряется ненадёжно: сверяем с соседями
    for group in [text_lines] + list(cell_lines.values()):
        _smooth_xh(group, page_xh)
    text_lines = _clean_lines(text_lines, clean_ink, page_xh, zone)
    for k in list(cell_lines):
        cell_lines[k] = _clean_lines(cell_lines[k], clean_ink, page_xh, zone)

    fills = _merge_fills(fills, page_xh)
    text_fills = [s for s in fills if in_any_table(s) is None]
    text_lines = _attach_fills(text_lines, text_fills, page_xh)
    for t in tables:
        for cell in t.cells:
            cf = [s for s in fills if cell.x0 < s.x0 and s.x1 < cell.x1 and cell.y0 < s.y0 < cell.y1]
            if cf:
                cell_lines[id(cell)] = _attach_fills(cell_lines.get(id(cell), []), cf, page_xh)

    all_lines = list(text_lines)
    for v in cell_lines.values():
        all_lines.extend(v)
    _mark_underlines(all_lines, unders)
    stroke_ink = clean_ink
    if blur >= 1.5:
        # на размытом скане штрихи после порога Оцу толще настоящих, а у
        # мелкого шрифта — заметно толще (ложный жирный): толщину меряем по
        # середине перепада между чернилами и бумагой
        dark = clean[clean < 200]
        if dark.size:
            mid = (float(np.percentile(dark, 5)) + 255.0) / 2.0
            stroke_ink = np.where((clean < mid) & (lines_removed == 0), 255, 0).astype(np.uint8)
    layout.mark_bold(all_lines, stroke_ink)
    # высота строчных у соседнего текста: у страницы и у каждой таблицы своя
    layout.fix_words(text_lines, page_xh)
    for t in tables:
        lines = [ln for c in t.cells for ln in cell_lines.get(id(c), [])]
        ref = [ln.xh for ln in lines if ln.sure or len(ln.words) >= 3]
        layout.fix_words(lines, float(median(ref)) if ref else 0.0)

    # --- границы содержимого
    xs0 = [ln.x0 for ln in text_lines] + [t.x0 for t in tables]
    xs1 = [ln.x1 for ln in text_lines] + [t.x1 for t in tables]
    ys0 = [ln.y0 for ln in text_lines] + [t.y0 for t in tables]
    ys1 = [ln.y1 for ln in text_lines] + [t.y1 for t in tables]
    if xs0:
        L = float(np.percentile(xs0, 3)) if len(xs0) > 10 else float(min(xs0))
        R = float(np.percentile(xs1, 97)) if len(xs1) > 10 else float(max(xs1))
        if tables:
            L = min(L, min(t.x0 for t in tables))
            R = max(R, max(t.x1 for t in tables))
        body = (int(L), int(min(ys0)), int(R), int(max(ys1)))
    else:
        L, R = W * 0.1, W * 0.9
        body = (int(L), int(H * 0.1), int(R), int(H * 0.9))

    # --- таблицы бланков: подписи слева от узкой таблицы и место на листе
    text_lines = [seg for ln in text_lines for seg in layout.split_line(ln)]
    text_lines = _attach_side_labels(tables, text_lines, cell_lines, L, R, page_xh)
    for t in tables:
        t.place = _table_place(t, L, R)
        # текст сбоку от таблицы (в Word он встанет под ней): высоту строк
        # такой таблицы по скану не задаём, чтобы страница не разрослась
        t.beside_text = any(min(ln.y1, t.y1) - max(ln.y0, t.y0) > 0.5 * (ln.y1 - ln.y0)
                            for ln in text_lines)

    # --- раскладка
    elements: list = []
    elements.extend(layout.layout_region(text_lines, L, R))
    cell_pad = 0.19 / 2.54 * dpi          # поле ячейки Word по умолчанию
    for t in tables:
        for cell in t.cells:
            lines = cell_lines.get(id(cell), [])
            cl, cr = cell.x0 + cell_pad, cell.x1 - cell_pad
            if lines:
                # текст может немного заходить за стандартные поля
                cl = min(cl, min(ln.x0 for ln in lines))
                long_r = max(ln.x1 for ln in lines)
                if long_r > cr or (len(lines) >= 3 and cr - long_r < 1.5 * xh):
                    cr = long_r
            cell.paragraphs = layout.segment_paragraphs(lines, cl, cr, cell=True)
            if cell.borderless:
                for p in cell.paragraphs:       # подписи бланка прижаты к таблице
                    p.align, p.left, p.first = "right", 0.0, 0.0
            _assign_sizes(cell.paragraphs, dpi)
        elements.append(t)
    _drop_page_numbers(elements, H)
    _harmonize_alignment([e for e in elements if isinstance(e, Para)], L)
    for t in tables:
        for cell in t.cells:
            _harmonize_alignment(cell.paragraphs, None)
    paras = _all_paras(elements)
    _assign_sizes(paras, dpi)
    body_size = 12.0
    elements.sort(key=lambda e: e.y0)

    # интервалы между элементами (в основном потоке и внутри ячеек/колонок)
    _space_before(elements, dpi, None)
    for el in elements:
        if isinstance(el, tbl.Table):
            for cell in el.cells:
                _space_before(cell.paragraphs, dpi, None)
                if cell.paragraphs:
                    cell.paragraphs[0].space_before = 0.0
        elif isinstance(el, ColumnGroup):
            for cell in el.cells:
                _space_before(cell, dpi, el.y0)
    return PageResult(index, W, H, dpi, elements, body, body_size, rot, ocr_score)


def _harmonize_alignment(paras: list[Para], L: float | None) -> None:
    """Однострочные абзацы подстраиваем под соседей.

    Строка с обычной «красной строкой», случайно оказавшаяся по центру,
    становится обычным абзацем; в документе «по ширине» однострочные
    абзацы тоже делаются по ширине."""
    multi = [p for p in paras if len(p.lines) >= 2 and p.segments is None]
    firsts = [p.first for p in multi if p.first > 0]
    if L is not None and firsts:
        ind = median(firsts)
        for p in paras:
            if len(p.lines) == 1 and p.align == "center" and p.segments is None:
                xh = p.lines[0].xh or 20
                if abs((p.lines[0].x0 - L) - ind) < 1.0 * xh:
                    p.align = "left"
                    p.first = ind
                    p.left = 0.0
    if not multi:
        return
    just = sum(p.align == "justify" for p in multi)
    if just < 0.6 * len(multi):
        return
    for p in paras:
        if len(p.lines) == 1 and p.align == "left" and p.segments is None and p.left == 0:
            p.align = "justify"


def _table_place(t: tbl.Table, L: float, R: float) -> tuple[str, float]:
    width = max(1.0, R - L)
    tw = t.x1 - t.x0
    if tw >= 0.9 * width:
        return "left", 0.0
    if abs((t.x0 + t.x1) / 2 - (L + R) / 2) < 0.04 * width:
        return "center", 0.0
    if t.x1 >= R - 0.03 * width:
        return "right", 0.0
    return "left", max(0.0, t.x0 - L)


def _attach_side_labels(tables: list[tbl.Table], text_lines: list[Line],
                        cell_lines: dict, L: float, R: float, page_xh: float) -> list[Line]:
    """Подписи слева от узкой таблицы бланка («Форма по ОКУД», «по ОКПО»,
    «АКТ» перед номером документа) становятся её первым столбцом без рамки,
    чтобы стоять напротив своих клеток, как в оригинале."""
    width = max(1.0, R - L)
    used: set[int] = set()
    for t in tables:
        if t.x1 - t.x0 > 0.45 * width:
            continue
        labels: dict[int, list[Line]] = {}
        for ln in text_lines:
            if id(ln) in used or all(w.fill for w in ln.words):
                continue
            xh = ln.xh or page_xh
            cy = (ln.y0 + ln.y1) / 2
            if not (t.y0 <= cy <= t.y1 and t.x0 - 8 * xh <= ln.x1 <= t.x0 + 0.5 * xh):
                continue
            if ln.x1 - ln.x0 > 0.4 * width:
                continue
            r = max(i for i in range(t.nrows) if t.ys[i] <= cy)
            labels.setdefault(r, []).append(ln)
        if not labels:
            continue
        lab = [ln for v in labels.values() for ln in v]
        x0 = int(min(ln.x0 for ln in lab) - page_xh)
        for c in t.cells:
            c.c0 += 1
            c.c1 += 1
        new_cells = []
        for r in range(t.nrows):
            gc = tbl.GridCell(r, 0, r + 1, 1, x0, t.ys[r], t.xs[0], t.ys[r + 1])
            gc.borderless = True
            lines = labels.get(r, [])
            if lines:
                cell_lines[id(gc)] = lines
                top = min(ln.y0 for ln in lines) - gc.y0
                bottom = gc.y1 - max(ln.y1 for ln in lines)
                h = max(1, gc.y1 - gc.y0)
                gc.valign = "bottom" if bottom < 0.25 * h < top else \
                    ("top" if top < 0.25 * h < bottom else "center")
            new_cells.append(gc)
        t.cells = sorted(new_cells + t.cells, key=lambda c: (c.r0, c.c0))
        t.xs = [x0] + t.xs
        used.update(id(ln) for ln in lab)
    return [ln for ln in text_lines if id(ln) not in used]


def _drop_page_numbers(elements: list, H: int) -> None:
    """Убирает номера страниц и колонтитулы вида «- 2 -», «Страница 2 из 5»."""
    pat = re.compile(r"^(стр\.?|страница|лист|page)?\s*[-–—]?\s*\d{1,4}\s*[-–—]?\s*(из\s*\d+)?$", re.I)
    for el in list(elements):
        if not isinstance(el, Para) or len(el.lines) != 1:
            continue
        txt = el.lines[0].text.strip()
        if el.y1 < 0.08 * H or el.y0 > 0.92 * H:
            if pat.match(txt):
                elements.remove(el)


# --------------------------------------------------------------------------

@dataclass
class SectionBreak:
    page: PageResult


def merge_pages(pages: list[PageResult]) -> list:
    """Склеивает страницы в один поток: переносы таблиц и абзацев.

    Если ориентация листа меняется, вставляется SectionBreak."""
    flow: list = []
    prev_landscape = None
    for page in pages:
        landscape = page.width_px > page.height_px
        els = list(page.elements)
        if prev_landscape is not None and landscape != prev_landscape:
            flow.append(SectionBreak(page))
        elif flow and els:
            last, first = flow[-1], els[0]
            if isinstance(last, tbl.Table) and isinstance(first, tbl.Table) and \
                    _same_columns(last, first):
                _append_table(last, first)
                els = els[1:]
            elif isinstance(last, Para) and isinstance(first, Para) and _continues(last, first):
                last.lines.extend(first.lines)
                if first.align == "justify":
                    last.align = "justify"
                els = els[1:]
            else:
                # промежуток до первого элемента новой страницы — это поле листа
                first.space_before = 0.0
        flow.extend(els)
        prev_landscape = landscape
    return flow


def _same_columns(a: tbl.Table, b: tbl.Table) -> bool:
    if a.ncols != b.ncols:
        return False
    wa = a.x1 - a.x0
    wb = b.x1 - b.x0
    if abs(wa - wb) > 0.05 * max(wa, wb):
        return False
    for xa, xb in zip(a.xs, b.xs):
        if abs((xa - a.x0) / wa - (xb - b.x0) / wb) > 0.03:
            return False
    return True


def _append_table(a: tbl.Table, b: tbl.Table) -> None:
    # повтор шапки на новой странице не нужен
    def row_text(t, r):
        cells = [c for c in t.cells if c.r0 == r]
        return [" ".join(layout.para_text(p) for p in c.paragraphs) for c in cells]

    skip_first = b.nrows > 1 and row_text(a, 0) == row_text(b, 0)
    start = 1 if skip_first else 0
    # строка, разорванная переходом страницы: в первом столбце пусто, а
    # в других столбцах есть продолжение текста — доклеиваем к последней
    first_cells = [c for c in b.cells if c.r0 == start]
    last_cells = {c.c0: c for c in a.cells if c.r1 == a.nrows}
    continuation = (
        first_cells and b.nrows - start >= 1 and
        all(c.r1 == start + 1 for c in first_cells) and
        not any(c.paragraphs for c in first_cells if c.c0 == 0) and
        any(c.paragraphs for c in first_cells) and
        all(c.c0 in last_cells for c in first_cells if c.paragraphs))
    if continuation:
        for c in first_cells:
            if not c.paragraphs:
                continue
            target = last_cells[c.c0]
            if target.paragraphs and c.paragraphs and \
                    _continues(target.paragraphs[-1], c.paragraphs[0]):
                target.paragraphs[-1].lines.extend(c.paragraphs[0].lines)
                target.paragraphs.extend(c.paragraphs[1:])
            else:
                target.paragraphs.extend(c.paragraphs)
        start += 1
    shift = a.nrows - start
    offset_y = a.ys[-1] - b.ys[start] if start < len(b.ys) else 0
    for c in b.cells:
        if c.r0 < start:
            continue
        c.r0 += shift
        c.r1 += shift
        a.cells.append(c)
    a.ys = a.ys + [y + offset_y for y in b.ys[start + 1:]]
    a.cells.sort(key=lambda c: (c.r0, c.c0))


def _continues(a: Para, b: Para) -> bool:
    if a.segments is not None or b.segments is not None:
        return False
    text_a = a.lines[-1].text.rstrip()
    text_b = b.lines[0].text.lstrip()
    if not text_a or not text_b:
        return False
    if text_a[-1] in ".!?:;»\"":
        return False
    if b.first > 0 or b.align in ("center", "right"):
        return False
    return bool(re.match(r"[a-zа-яё(«\d]", text_b)) and abs(a.size - b.size) < 1


# --------------------------------------------------------------------------

def convert(path: str, out_path: str, opts: Options | None = None,
            progress: ProgressFn | None = None, engine: Engine | None = None) -> str:
    from . import docxwriter

    opts = opts or Options()
    engine = engine or Engine(opts.langs)
    report = progress or (lambda f, m: None)
    report(0.0, "Открываю файл…")
    src = imageops.PageSource(path)
    try:
        n = src.count
        if n == 0:
            raise ValueError("В файле нет страниц")
        workers = opts.workers or max(1, min(4, (os.cpu_count() or 2)))
        workers = min(workers, n)
        done = 0
        results: list[PageResult | None] = [None] * n
        fractions = [0.0] * n
        lock = threading.Lock()

        def stepper(i):
            def step(f):
                with lock:
                    fractions[i] = f
                    total = sum(fractions) / n
                report(0.02 + 0.93 * total, f"Распознаю страницы: {done} из {n} готово")
            return step

        report(0.02, f"Распознаю страницы: 0 из {n} готово")
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(process_page, engine, src, i, opts, stepper(i)): i
                       for i in range(n)}
            try:
                for fut in _as_completed(futures):
                    i = futures[fut]
                    try:
                        results[i] = fut.result()
                    except (OcrError, ValueError, cv2.error, MemoryError) as exc:
                        # одна плохая страница не должна губить весь документ
                        results[i] = _failed_page(i, exc)
                    done += 1
                    with lock:
                        fractions[i] = 1.0
                        total = sum(fractions) / n
                    report(0.02 + 0.93 * total, f"Распознаю страницы: {done} из {n} готово")
            except BaseException:
                engine.cancel()
                for f in futures:
                    f.cancel()
                raise
        report(0.96, "Собираю документ Word…")
        pages = [r for r in results if r is not None]
        finalize_sizes(pages)
        _fit_fills(pages)
        docxwriter.write(pages, merge_pages(pages), out_path,
                         title=os.path.splitext(os.path.basename(path))[0])
        report(1.0, "Готово")
        return out_path
    finally:
        src.close()


def _failed_page(index: int, exc: Exception) -> PageResult:
    text = f"[Страница {index + 1} не распознана: {exc}]"
    line = Line([Word(text, 0, 0, 100, 30)], xh=14.0, base=30.0)
    para = Para([line], align="left", size=12.0)
    return PageResult(index, 2480, 3508, 300.0, [para], (295, 236, 2303, 3272))


def _as_completed(futures):
    from concurrent.futures import as_completed
    return as_completed(futures)


__all__ = ["convert", "Options", "Cancelled", "process_page", "merge_pages", "SectionBreak"]
