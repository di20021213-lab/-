"""Kinescope Downloader — простое окно: вставил ссылку, нажал «Скачать».

Качает видео с Kinescope в 1080p. ffmpeg вшит внутрь exe (при сборке через
GitHub Actions), поэтому ничего доустанавливать не нужно.

Скачивай только то, на что у тебя есть права. Ролики с DRM не поддерживаются.
"""

from __future__ import annotations

import json
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
import zipfile
from pathlib import Path
from urllib.parse import urlparse

import tkinter as tk
from tkinter import filedialog, ttk

import requests

import capture_server
import kinescope_dl as kd

APP_TITLE = "Kinescope Downloader"
DONATE_URL = ""
FONT = "Tahoma"
MONO = "Lucida Console"
COLORS = {
    "bg": "#ECE9D8",
    "surface": "#ECE9D8",
    "surface2": "#FFFFFF",
    "text": "#000000",
    "muted": "#4A4A3D",
    "accent": "#316AC5",
    "accent_hover": "#3B7DD8",
    "accent_active": "#2857A8",
    "success": "#4EA24E",
    "border": "#7F9DB9",
    "banner_top": "#2A63C8",
    "banner_bottom": "#4E8DF0",
    "btn_face": "#ECE9D8",
    "btn_light": "#FFFFFF",
    "btn_dark": "#716F64",
    "log_bg": "#FFFFFF",
    "log_fg": "#000000",
}


def resource_path(name: str) -> str:
    """Путь к вложенному ресурсу (работает и в exe, и в исходниках)."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


FFMPEG_URL = (
    "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/"
    "ffmpeg-master-latest-win64-gpl.zip"
)


def app_cache_dir() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    d = os.path.join(base, "KinescopeDownloader")
    os.makedirs(d, exist_ok=True)
    return d


def find_ffmpeg() -> "str | None":
    """Ищет ffmpeg: вшитый рядом с exe, в системе или в кэше приложения."""
    for name in ("ffmpeg.exe", "ffmpeg"):
        cand = resource_path(name)
        if os.path.isfile(cand):
            return cand
    cached = os.path.join(app_cache_dir(), "ffmpeg.exe")
    if os.path.isfile(cached):
        return cached
    return kd._which("ffmpeg")


def _download_file(url: str, dest: str, verify: bool = True) -> None:
    """Качает файл через requests (учитывает системные сертификаты)."""
    with requests.get(url, stream=True, timeout=120, verify=verify) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=1048576):
                if chunk:
                    f.write(chunk)


def ensure_ffmpeg(log) -> "str | None":
    """Возвращает путь к ffmpeg, при необходимости скачивая его один раз."""
    existing = find_ffmpeg()
    if existing:
        return existing
    cached = os.path.join(app_cache_dir(), "ffmpeg.exe")
    zip_path = os.path.join(app_cache_dir(), "ffmpeg.zip")
    log("Первый запуск: скачиваю ffmpeg (~40 МБ, один раз)…")
    try:
        try:
            _download_file(FFMPEG_URL, zip_path, verify=True)
        except requests.exceptions.SSLError:
            log(
                "Проблема с сертификатом (похоже, корпоративная сеть). "
                "Повторяю без проверки TLS…"
            )
            _download_file(FFMPEG_URL, zip_path, verify=False)
        with zipfile.ZipFile(zip_path) as z:
            member = next(
                n for n in z.namelist()
                if n.replace("\\", "/").endswith("bin/ffmpeg.exe")
            )
            with z.open(member) as src, open(cached, "wb") as dst:
                shutil.copyfileobj(src, dst)
    except Exception as exc:  # noqa: BLE001
        log(f"Не удалось скачать ffmpeg: {exc}")
        if os.path.exists(zip_path):
            os.remove(zip_path)
        return None
    finally:
        if os.path.exists(zip_path):
            os.remove(zip_path)
    log("ffmpeg установлен.")
    return cached


def _is_ssl_error(exc: BaseException) -> bool:
    """Похоже ли исключение на ошибку проверки TLS-сертификата."""
    text = f"{type(exc).__name__}: {exc}".upper()
    return (
        "CERTIFICATE_VERIFY_FAILED" in text
        or "SSLERROR" in text
        or "CERTIFICATE" in text
        or "SSL:" in text
    )


def default_download_dir() -> str:
    downloads = Path.home() / "Downloads"
    return str(downloads if downloads.is_dir() else Path.home())


def _output_name(url: str) -> str:
    """Имя выходного файла по URL манифеста (или дата-время, если общее)."""
    stem = os.path.splitext(os.path.basename(urlparse(url).path))[0]
    generic = {"", "mpd", "index", "master", "manifest", "playlist", "chunklist"}
    if stem.lower() in generic:
        return "video_" + time.strftime("%Y%m%d_%H%M%S")
    safe = re.sub(r"[^\w.-]+", "_", stem)[:60]
    return safe or ("video_" + time.strftime("%Y%m%d_%H%M%S"))


# --------------------------------------------------------------------------- #
# Оформление в стиле Windows XP (Luna) и вставка из буфера.
# --------------------------------------------------------------------------- #

def apply_theme(root: tk.Misc) -> None:
    """Оформление в стиле Windows XP (Luna): бежевые диалоги, 3D-кнопки,
    Tahoma, зелёный прогресс, синие вкладки."""
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    c = COLORS
    root.option_add("*Font", (FONT, 9))

    style.configure(".", background=c["bg"], foreground=c["text"],
                    font=(FONT, 9))
    style.configure("TFrame", background=c["bg"])
    style.configure("TLabel", background=c["bg"], foreground=c["text"],
                    font=(FONT, 9))
    style.configure("Header.TLabel", background=c["bg"], foreground=c["text"],
                    font=(FONT, 15, "bold"))
    style.configure("Status.TLabel", background=c["bg"], foreground=c["muted"],
                    font=(FONT, 8))

    style.configure("TLabelframe", background=c["bg"], bordercolor=c["border"],
                    relief="groove")
    style.configure("TLabelframe.Label", background=c["bg"],
                    foreground=c["accent_active"], font=(FONT, 9, "bold"))

    style.configure("TButton", background=c["btn_face"], foreground=c["text"],
                    font=(FONT, 9), relief="raised", padding=(10, 4),
                    bordercolor=c["btn_dark"])
    style.map("TButton", background=[("active", c["btn_light"])])

    style.configure("Accent.TButton", background=c["accent"],
                    foreground="#FFFFFF", font=(FONT, 10, "bold"),
                    padding=(16, 6), relief="raised", bordercolor=c["accent_active"])
    style.map("Accent.TButton",
              background=[("active", c["accent_hover"]),
                          ("pressed", c["accent_active"]),
                          ("disabled", c["btn_dark"])])

    style.configure("Ghost.TButton", background=c["btn_face"],
                    foreground=c["text"], font=(FONT, 9), padding=(8, 3))
    style.map("Ghost.TButton", background=[("active", c["btn_light"])])

    style.configure("TCheckbutton", background=c["bg"], foreground=c["text"],
                    font=(FONT, 9))
    style.map("TCheckbutton", background=[("active", c["bg"])])

    style.configure("TEntry", fieldbackground=c["surface2"],
                    foreground=c["text"], bordercolor=c["border"])
    style.configure("Big.TEntry", fieldbackground=c["surface2"],
                    foreground=c["text"], bordercolor=c["border"],
                    padding=2)

    style.configure("TNotebook", background=c["bg"], bordercolor=c["border"])
    style.configure("TNotebook.Tab", background=c["btn_face"],
                    foreground=c["text"], font=(FONT, 9), padding=(10, 4))
    style.map("TNotebook.Tab",
              background=[("selected", c["surface2"])],
              foreground=[("selected", c["accent_active"])])

    style.configure("Horizontal.TProgressbar", background=c["success"],
                    troughcolor=c["surface2"], bordercolor=c["border"])


def paste_into(root, entry):
    """Вставляет текст из буфера обмена в поле (замена выделения)."""
    try:
        text = root.clipboard_get()
    except tk.TclError:
        return "break"
    try:
        entry.delete("sel.first", "sel.last")
    except tk.TclError:
        pass
    entry.insert("insert", text)
    return "break"


def enable_paste(root, entry):
    """Вставка при любой раскладке: Ctrl+V, Shift+Insert, правый клик, меню."""
    def on_ctrl(event: "tk.Event") -> "Optional[str]":  # noqa: F821
        if event.keycode == 86 or event.keysym.lower() in ("v", "cyrillic_em"):
            return paste_into(root, entry)
        return None

    entry.bind("<Control-KeyPress>", on_ctrl)
    entry.bind("<Shift-Insert>", lambda e: paste_into(root, entry))

    menu = tk.Menu(root, tearoff=0)
    menu.add_command(label="Вставить", command=lambda: paste_into(root, entry))

    def show_menu(e):
        try:
            menu.tk_popup(e.x_root, e.y_root)
        finally:
            menu.grab_release()

    entry.bind("<Button-3>", show_menu)


class DownloaderApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.log_queue = queue.Queue()
        self.job_queue = queue.Queue()
        self.worker = None
        self.capture_enabled = False
        self.capture = capture_server.CaptureServer(self._on_captured_threadsafe)

        root.title(APP_TITLE)
        root.geometry("720x660")
        root.minsize(640, 600)
        root.configure(bg=COLORS["bg"])
        self._setup_style()
        self._build_banner(root)

        notebook = ttk.Notebook(root)
        notebook.pack(fill="both", expand=True, padx=10, pady=(8, 10))
        dl = ttk.Frame(notebook, style="TFrame", padding=(18, 16))
        notebook.add(dl, text="   Загрузка   ")
        self._build_download_tab(dl)
        donate = ttk.Frame(notebook, style="TFrame", padding=(24, 26))
        notebook.add(donate, text="   ♥ Поддержать   ")
        self._build_donate_tab(donate)
        self._poll_log()

    # ------------------------------------------------------------------ #
    # Оформление
    # ------------------------------------------------------------------ #
    def _setup_style(self) -> None:
        apply_theme(self.root)

    def _build_banner(self, root: tk.Tk) -> None:
        canvas = tk.Canvas(root, height=54, highlightthickness=0, bd=0)
        canvas.pack(fill="x")

        def paint(event=None):
            canvas.delete("all")
            w = canvas.winfo_width() or root.winfo_width() or 720
            steps = 54
            for i in range(steps):
                t = i / steps
                r1, g1, b1 = root.winfo_rgb(COLORS["banner_top"])
                r2, g2, b2 = root.winfo_rgb(COLORS["banner_bottom"])
                r = int(r1 + (r2 - r1) * t) >> 8
                g = int(g1 + (g2 - g1) * t) >> 8
                b = int(b1 + (b2 - b1) * t) >> 8
                canvas.create_line(0, i, w, i, fill=f"#{r:02x}{g:02x}{b:02x}")
            canvas.create_text(
                16, 27, anchor="w", text=APP_TITLE,
                fill="#FFFFFF", font=(FONT, 15, "bold"),
            )
            canvas.create_text(
                w - 14, 33, anchor="e", text="Скачивание видео в 1080p — бесплатно",
                fill="#E6EEFF", font=(FONT, 8),
            )

        canvas.bind("<Configure>", paint)
        paint()

    # ------------------------------------------------------------------ #
    # Вкладки
    # ------------------------------------------------------------------ #
    def _build_download_tab(self, wrap: ttk.Frame) -> None:
        box = ttk.Labelframe(wrap, text="Ссылки на видео (по одной в строке)",
                             padding=(10, 6))
        box.pack(fill="x", pady=(0, 8))
        self.url_text = tk.Text(
            box, height=4, wrap="none", relief="sunken", borderwidth=2,
            bg=COLORS["surface2"], fg=COLORS["text"],
            insertbackground=COLORS["text"], font=(FONT, 10),
            padx=4, pady=4, highlightthickness=0,
        )
        self.url_text.pack(fill="x")
        enable_paste(self.root, self.url_text)
        self.url_text.focus()

        # Кнопка: вытащить ссылки из сохранённого JSON/HAR-файла.
        file_row = ttk.Frame(box, style="TFrame")
        file_row.pack(fill="x", pady=(6, 0))
        ttk.Button(file_row, text="📂 Из файла (JSON/HAR)…",
                   style="Ghost.TButton",
                   command=self.load_from_file).pack(side="left")
        ttk.Label(file_row,
                  text="конфиг плеера или HAR из вкладки Network браузера",
                  style="Status.TLabel").pack(side="left", padx=(8, 0))

        opts = ttk.Labelframe(wrap, text="Параметры", padding=(10, 8))
        opts.pack(fill="x", pady=(0, 8))

        folder_row = ttk.Frame(opts, style="TFrame")
        folder_row.pack(fill="x", pady=(0, 6))
        ttk.Label(folder_row, text="Папка:").pack(side="left")
        self.folder_var = tk.StringVar(value=default_download_dir())
        ttk.Entry(folder_row, textvariable=self.folder_var,
                  style="Big.TEntry").pack(side="left", fill="x", expand=True,
                                           padx=(6, 6), ipady=2)
        ttk.Button(folder_row, text="Обзор…", style="Ghost.TButton",
                   command=self.choose_folder).pack(side="left")

        ref_row = ttk.Frame(opts, style="TFrame")
        ref_row.pack(fill="x")
        ttk.Label(ref_row, text="Referer:").pack(side="left")
        self.referer_var = tk.StringVar()
        ref_entry = ttk.Entry(ref_row, textvariable=self.referer_var,
                              style="Big.TEntry")
        ref_entry.pack(side="left", fill="x", expand=True, padx=(6, 0), ipady=2)
        self._enable_paste(ref_entry)

        action = ttk.Frame(wrap, style="TFrame")
        action.pack(fill="x", pady=(0, 8))
        self.download_btn = ttk.Button(
            action, text="Скачать в 1080p", style="Accent.TButton",
            command=self.start_download,
        )
        self.download_btn.pack(side="left")
        self.capture_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            action, text="Ловить ссылки из браузера",
            style="TCheckbutton", variable=self.capture_var,
            command=self.toggle_capture,
        ).pack(side="left", padx=(12, 0))

        wm_row = ttk.Frame(wrap, style="TFrame")
        wm_row.pack(fill="x", pady=(0, 8))
        self.watermark_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            wm_row, text="Водяной знак в углу", style="TCheckbutton",
            variable=self.watermark_var,
        ).pack(side="left")
        ttk.Label(wm_row, text="подпись:", style="Status.TLabel").pack(
            side="left", padx=(12, 4))
        self.watermark_label_var = tk.StringVar(value="Gomer\\nSimpson")
        wm_entry = ttk.Entry(wm_row, textvariable=self.watermark_label_var,
                             style="Big.TEntry", width=18)
        wm_entry.pack(side="left")
        self._enable_paste(wm_entry)

        prog = ttk.Labelframe(wrap, text="Ход выполнения", padding=(10, 8))
        prog.pack(fill="both", expand=True)
        self.overall = ttk.Label(prog, text="Жду ссылки…", style="Status.TLabel")
        self.overall.pack(anchor="w", pady=(0, 4))
        self.progress = ttk.Progressbar(
            prog, style="Horizontal.TProgressbar", maximum=100,
        )
        self.progress.pack(fill="x", pady=(0, 8))
        self.log = tk.Text(
            prog, height=8, wrap="word", relief="sunken", borderwidth=2,
            bg=COLORS["log_bg"], fg=COLORS["log_fg"], font=(MONO, 9),
            padx=4, pady=4, state="disabled", highlightthickness=0,
        )
        self.log.pack(fill="both", expand=True)

    def _build_donate_tab(self, wrap: ttk.Frame) -> None:
        ttk.Label(wrap, text="♥", background=COLORS["bg"],
                  foreground=COLORS["accent"], font=(FONT, 40)).pack(pady=(6, 4))
        ttk.Label(wrap, text="Спасибо, что пользуешься!",
                  style="Header.TLabel").pack()
        ttk.Label(
            wrap,
            text=("Программа бесплатная. Если она тебе пригодилась — можно "
                  "поддержать автора. Ссылку добавим позже."),
            style="Status.TLabel", wraplength=520, justify="center",
        ).pack(pady=(8, 20))
        self.donate_btn = ttk.Button(
            wrap, text="Открыть страницу поддержки", style="Accent.TButton",
            command=self.open_donate,
        )
        self.donate_btn.pack(ipady=4)
        self.donate_status = ttk.Label(wrap, text="", style="Status.TLabel")
        self.donate_status.pack(pady=(14, 0))

    def open_donate(self) -> None:
        if DONATE_URL:
            webbrowser.open(DONATE_URL)
            self.donate_status.configure(text="Открыл страницу в браузере. Спасибо! ♥")
        else:
            self.donate_status.configure(
                text="Ссылка для доната пока не задана — появится позже."
            )

    # ------------------------------------------------------------------ #
    # Вспомогательное
    # ------------------------------------------------------------------ #
    def _enable_paste(self, entry: ttk.Entry) -> None:
        enable_paste(self.root, entry)

    def choose_folder(self) -> None:
        d = filedialog.askdirectory(initialdir=self.folder_var.get())
        if d:
            self.folder_var.set(d)

    def load_from_file(self) -> None:
        """Достаёт ссылки на видео из выбранных JSON/HAR-файлов и кладёт в список.

        Понимает и HAR (тогда для каждого манифеста подтягивает Referer/Cookie
        и название ролика), и любой JSON/текст с адресами манифестов внутри.
        """
        paths = filedialog.askopenfilenames(
            title="Выбери один или несколько JSON/HAR-файлов",
            filetypes=[
                ("JSON и HAR", "*.json *.har"),
                ("Все файлы", "*.*"),
            ],
        )
        if not paths:
            return

        existing = {ln.strip()
                    for ln in self.url_text.get("1.0", "end").splitlines()}
        self._capture_meta = getattr(self, "_capture_meta", {})
        added = 0
        empty_files = 0
        for path in paths:
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                    text = fh.read()
            except OSError as exc:
                self._log(f"Не смог прочитать {os.path.basename(path)}: {exc}")
                continue

            meta_from_har = self._parse_har(text)  # url -> {referer,cookies,title}
            file_title = self._title_from_json(text)  # запасной заголовок файла
            urls = kd.extract_sources_from_text(text)
            if not urls:
                empty_files += 1
                continue

            for url in urls:
                norm = kd.normalize_manifest_url(url)
                if norm in existing:
                    continue
                existing.add(norm)
                info = dict(meta_from_har.get(norm, {}))
                if not info.get("title") and file_title:
                    info["title"] = file_title
                if info:
                    self._capture_meta[norm] = info
                self.url_text.insert("end", norm + "\n")
                added += 1

        if added:
            self._log(
                f"📂 Из файлов ({len(paths)} шт.) добавил ссылок: {added}. "
                f"Имя файла возьмётся из названия ролика. Жми «Скачать»."
            )
        elif empty_files:
            self._log(
                "В файлах не нашёл ссылок на видео (ни манифестов m3u8/mpd, "
                "ни id Kinescope). Это точно конфиги плеера или HAR?"
            )
        else:
            self._log("Все ссылки из файлов уже есть в списке.")

    @staticmethod
    def _title_from_json(text: str) -> str:
        """Достаёт название ролика из поля \"title\" в JSON-конфиге плеера."""
        for m in re.finditer(r'"title"\s*:\s*"((?:[^"\\]|\\.)*)"', text):
            raw = m.group(1)
            try:
                title = json.loads('"' + raw + '"')
            except ValueError:
                title = raw
            title = title.strip()
            if len(title) >= 3 and title.lower() not in ("kinescope", "video"):
                return title
        return ""

    @staticmethod
    def _parse_har(text: str) -> dict:
        """Если это HAR — для каждого манифеста собирает Referer, Cookie и
        название страницы (заголовок вкладки = название вебинара/урока)."""
        meta: dict = {}
        try:
            data = json.loads(text)
        except (ValueError, TypeError):
            return meta
        log = (data or {}).get("log") or {}
        pages = {}
        for pg in log.get("pages") or []:
            try:
                pages[str(pg.get("id"))] = str(pg.get("title") or "").strip()
            except (AttributeError, TypeError):
                continue
        entries = log.get("entries") or []
        if not isinstance(entries, list):
            return meta
        for entry in entries:
            try:
                req = entry.get("request") or {}
                url = str(req.get("url") or "")
                low = url.split("?")[0].lower()
                if not (low.endswith(".m3u8") or low.endswith(".mpd")):
                    continue
                referer = ""
                cookies = ""
                for h in req.get("headers") or []:
                    name = str(h.get("name") or "").lower()
                    if name == "referer":
                        referer = str(h.get("value") or "")
                    elif name == "cookie":
                        cookies = str(h.get("value") or "")
                title = pages.get(str(entry.get("pageref")), "")
                norm = kd.normalize_manifest_url(url)
                meta[norm] = {
                    "referer": referer,
                    "cookies": cookies,
                    "title": title,
                }
            except (AttributeError, TypeError):
                continue
        return meta

    def _log(self, msg: str) -> None:
        self.log_queue.put(msg)

    def _poll_log(self) -> None:
        try:
            while True:
                msg = self.log_queue.get_nowait()
                self.log.configure(state="normal")
                self.log.insert("end", msg + "\n")
                self.log.see("end")
                self.log.configure(state="disabled")
        except queue.Empty:
            pass
        self.root.after(100, self._poll_log)

    def _set_progress(self, value: float) -> None:
        self.root.after(0, lambda: self.progress.configure(value=value))

    def _set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        text = "СКАЧИВАЮ…" if busy else "Скачать в 1080p"
        self.root.after(
            0, lambda: self.download_btn.configure(state=state, text=text)
        )

    def _set_overall(self, text: str) -> None:
        self.root.after(0, lambda: self.overall.configure(text=text))

    # ------------------------------------------------------------------ #
    # Очередь и скачивание
    # ------------------------------------------------------------------ #
    def start_download(self) -> None:
        raw = self.url_text.get("1.0", "end")
        meta = getattr(self, "_capture_meta", {})
        added = 0
        for line in raw.splitlines():
            line = line.strip()
            if line:
                job = {"url": line}
                job.update(meta.get(line, {}))  # referer/cookies/title
                self.job_queue.put(job)
                added += 1
        if added == 0:
            self._log("Вставь одну или несколько ссылок (по одной в строке).")
            return
        self.url_text.delete("1.0", "end")
        self._ensure_worker()

    def _ensure_worker(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        self.worker = threading.Thread(target=self._worker_loop, daemon=True)
        self.worker.start()

    def _worker_loop(self) -> None:
        ffmpeg = ensure_ffmpeg(self._log)
        if not ffmpeg:
            self._log(
                "ffmpeg недоступен. В собранном exe он вшит; при запуске из "
                "исходников положи ffmpeg.exe рядом или установи в систему."
            )
            return

        while True:
            try:
                job = self.job_queue.get(timeout=0.5)
            except queue.Empty:
                break
            remaining = self.job_queue.qsize()
            self._set_busy(True)
            self._set_progress(0)
            self._set_overall(
                "Скачиваю…" + (f" в очереди ещё {remaining}" if remaining else "")
            )
            self._log(f"→ {job['url']}")
            try:
                self._download_one(job, ffmpeg)
            except Exception as exc:  # noqa: BLE001
                self._log(f"  ✗ Ошибка: {exc}")
            finally:
                self.job_queue.task_done()
            if self.job_queue.empty():
                self._set_busy(False)
                self._set_overall(
                    "Жду ссылки из браузера…" if self.capture_enabled
                    else "Готово. Очередь пуста."
                )

    def _download_one(self, job: dict, ffmpeg: str) -> None:
        try:
            self._perform(job, ffmpeg, insecure=False)
        except Exception as exc:  # noqa: BLE001
            if _is_ssl_error(exc):
                self._log("  Сертификат не прошёл проверку — повтор без TLS…")
                self._perform(job, ffmpeg, insecure=True)
            else:
                raise

    # ------------------------------------------------------------------ #
    # Захват ссылок из браузера
    # ------------------------------------------------------------------ #
    def toggle_capture(self) -> None:
        self.capture_enabled = bool(self.capture_var.get())
        if self.capture_enabled:
            try:
                self.capture.start()
            except OSError as exc:
                self.capture_enabled = False
                self.capture_var.set(False)
                self._log(f"Не удалось включить приём ссылок: {exc}")
                return
            self._log(
                f"🌐 Ловлю ссылки из браузера (порт "
                f"{capture_server.CAPTURE_PORT}). Запусти видео на Kinescope "
                f"или МТС Линк — ссылка добавится в список. Выстави галки и "
                f"жми «Скачать»."
            )
            self._set_overall("Жду ссылки из браузера…")
        else:
            self.capture.stop()
            self._log("Приём ссылок из браузера выключен.")

    def _on_captured_threadsafe(self, payload) -> None:
        self.root.after(0, self._on_captured, payload)

    def _on_captured(self, payload) -> None:
        if isinstance(payload, str):
            payload = {"url": payload}
        url = kd.normalize_manifest_url(payload.get("url", ""))
        if not url:
            return
        existing = {ln.strip() for ln in self.url_text.get("1.0", "end").splitlines()}
        if url in existing:
            return
        if payload.get("referer") or payload.get("cookies") or payload.get("title"):
            self._capture_meta = getattr(self, "_capture_meta", {})
            self._capture_meta[url] = {
                "referer": payload.get("referer", ""),
                "cookies": payload.get("cookies", ""),
                "title": payload.get("title", ""),
            }
        self.url_text.insert("end", url + "\n")
        self._log("🎯 Поймал ссылку — добавил в список. Нажми «Скачать».")

    def _make_session(self, insecure: bool, referer: str, cookies: str):
        session = requests.Session()
        session.verify = not insecure
        headers = dict(kd.DEFAULT_HEADERS)
        if referer:
            headers["Referer"] = referer
        if cookies:
            headers["Cookie"] = cookies
        session.headers.update(headers)
        return session

    def _watermark_path(self) -> "str | None":
        if not self.watermark_var.get():
            return None
        base = os.path.dirname(
            sys.executable if getattr(sys, "frozen", False)
            else os.path.abspath(__file__)
        )
        custom = os.path.join(base, "watermark.png")  # пользовательский приоритетнее
        if os.path.isfile(custom):
            return custom
        bundled = resource_path("watermark.png")
        return bundled if os.path.isfile(bundled) else None

    def _build_watermark_image(self) -> "str | None":
        """Собирает картинку знака (иконка + текст в 2 строки) через Pillow."""
        icon = self._watermark_path()
        if not icon:
            return None
        label = (self.watermark_label_var.get() or "").strip().replace("\\n", "\n")
        font = resource_path("font.ttf")
        if not label or not os.path.isfile(font):
            return icon
        try:
            from PIL import Image, ImageDraw, ImageFont
        except Exception:  # noqa: BLE001
            return icon
        try:
            img = Image.open(icon).convert("RGBA")
            ih = 110
            img = img.resize((max(1, int(img.width * ih / img.height)), ih),
                             Image.LANCZOS)
            fnt = ImageFont.truetype(font, 46)
            lines = label.split("\n") or [""]
            probe = ImageDraw.Draw(Image.new("RGBA", (4, 4)))
            widths = [probe.textlength(ln, font=fnt) for ln in lines]
            line_h = fnt.size + 8
            text_w = int(max(widths)) if widths else 0
            text_h = line_h * len(lines)
            gap = 16
            width = text_w + gap + img.width
            height = max(text_h, img.height)
            canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            draw = ImageDraw.Draw(canvas)
            ty = (height - text_h) // 2
            for i, ln in enumerate(lines):
                draw.text((0, ty + i * line_h), ln, font=fnt,
                          fill=(255, 255, 255, 255), stroke_width=3,
                          stroke_fill=(0, 0, 0, 200))
            canvas.alpha_composite(img, (text_w + gap, (height - img.height) // 2))
            fd, out = tempfile.mkstemp(suffix=".png")
            os.close(fd)
            canvas.save(out)
            return out
        except Exception as exc:  # noqa: BLE001
            self._log(f"Не удалось собрать знак с текстом: {exc}")
            return icon

    def _unique_path(self, out_dir: str, name: str) -> str:
        """Полный путь к .mp4; если файл занят — добавляет (2), (3)…"""
        candidate = os.path.join(out_dir, f"{name}.mp4")
        if not os.path.exists(candidate):
            return candidate
        for i in range(2, 1000):
            candidate = os.path.join(out_dir, f"{name} ({i}).mp4")
            if not os.path.exists(candidate):
                return candidate
        return os.path.join(out_dir, f"{name} ({int(time.time())}).mp4")

    def _perform(self, job: dict, ffmpeg: str, insecure: bool) -> None:
        url = kd.normalize_manifest_url(job["url"])
        referer = self.referer_var.get().strip() or job.get("referer", "")
        cookies = job.get("cookies", "")
        wm = self._build_watermark_image()
        if wm:
            self._log("Водяной знак включён — видео будет перекодировано (дольше).")

        out_dir = self.folder_var.get().strip() or default_download_dir()
        os.makedirs(out_dir, exist_ok=True)

        path = urlparse(url).path.lower()
        is_manifest = path.endswith(".m3u8") or path.endswith(".mpd")

        title = (job.get("title") or "").strip()

        if is_manifest:
            session = self._make_session(insecure, referer, cookies)
            name = kd.safe_filename(title, fallback=_output_name(url))
            output = self._unique_path(out_dir, name)
            self._log("Качаю по манифесту (m3u8/mpd)…")
            kd.download_manifest(
                url, session, output, ffmpeg,
                progress=lambda f: self._set_progress(f * 100), watermark=wm,
            )
            self._log(f"✓ Готово! Файл сохранён: {output}")
            return

        video_id = kd.extract_video_id(url)
        referer = referer or f"{kd.BASE_URL}/{video_id}"
        session = self._make_session(insecure, referer, cookies)
        self._log(f"Ищу видео {video_id}…")
        if not title:
            try:
                title = kd.fetch_title(video_id, referer, session)
            except Exception:  # noqa: BLE001
                title = ""
        manifests = kd.resolve_manifests(video_id, referer, session)
        if not manifests:
            raise RuntimeError(
                "не удалось найти видео (нужен Referer, DRM или изменилась "
                "разметка Kinescope)."
            )
        name = kd.safe_filename(title, fallback=video_id)
        output = self._unique_path(out_dir, name)
        if manifests.dash:
            self._log("Нашёл манифест, качаю в 1080p…")
            kd.download_dash(
                manifests.dash[0], session, output, ffmpeg,
                progress=lambda f: self._set_progress(f * 100), watermark=wm,
            )
        else:
            self._log("Нашёл манифест (HLS), качаю…")
            kd.download_hls(
                manifests.hls[0], session, output, ffmpeg,
                progress=lambda f: self._set_progress(f * 100), watermark=wm,
            )
        self._log(f"✓ Готово! Файл сохранён: {output}")

    def _run_ffmpeg(
        self, ffmpeg: str, manifest_url: str, output: str, referer: str
    ) -> None:
        headers = f"Referer: {referer}\r\nOrigin: {kd.BASE_URL}\r\n"
        cmd = [
            ffmpeg, "-y",
            "-headers", headers,
            "-user_agent", kd.DEFAULT_HEADERS["User-Agent"],
            "-i", manifest_url,
            "-c", "copy",
            "-bsf:a", "aac_adtstoasc",
            "-progress", "pipe:1", "-nostats",
            output,
        ]
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
            creationflags=creationflags,
        )
        duration = None
        dur_re = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
        time_re = re.compile(r"out_time=(\d+):(\d+):(\d+(?:\.\d+)?)")
        for line in proc.stdout:  # type: ignore[union-attr]
            if duration is None:
                md = dur_re.search(line)
                if md:
                    h, m, s = md.groups()
                    duration = int(h) * 3600 + int(m) * 60 + float(s)
            mt = time_re.search(line)
            if mt and duration:
                h, m, s = mt.groups()
                cur = int(h) * 3600 + int(m) * 60 + float(s)
                self._set_progress(min(99.0, cur / duration * 100))
        proc.wait()
        if proc.returncode != 0 or not os.path.exists(output):
            raise RuntimeError(
                f"ffmpeg завершился с кодом {proc.returncode}. "
                "Проверь доступ к видео и ссылку."
            )


def main() -> int:
    try:
        import truststore
        truststore.inject_into_ssl()
    except Exception:  # noqa: BLE001
        pass
    root = tk.Tk()
    DownloaderApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
