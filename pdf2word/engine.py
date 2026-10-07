"""Обёртка над Tesseract OCR: поиск движка, запуск, разбор TSV.

Картинки передаются через stdin, результат читается из stdout, а папка с
моделями указывается относительным путём из рабочей папки процесса. Так
программа работает и когда путь к ней содержит русские буквы (например,
C:\\Users\\Иван\\...), с которыми консольный tesseract.exe дружит плохо.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass


class OcrError(RuntimeError):
    pass


class Cancelled(Exception):
    """Пользователь нажал «Отмена»."""


@dataclass
class TWord:
    page: int
    block: int
    par: int
    line: int
    x0: int
    y0: int
    x1: int
    y1: int
    conf: float
    text: str


def _resource_roots() -> list[str]:
    roots = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        roots.append(meipass)
    if getattr(sys, "frozen", False):
        roots.append(os.path.dirname(sys.executable))
    here = os.path.dirname(os.path.abspath(__file__))
    roots.append(os.path.dirname(here))
    roots.append(here)
    return roots


class Engine:
    """Один экземпляр на всё приложение; потокобезопасен."""

    def __init__(self, langs: str = "rus"):
        self.langs = langs
        self.exe, self.tessdata = self._locate()
        self._procs: set[subprocess.Popen] = set()
        self._lock = threading.Lock()
        self.cancelled = threading.Event()

    # ------------------------------------------------------------------ setup
    @staticmethod
    def _locate() -> tuple[str, str | None]:
        exe_name = "tesseract.exe" if os.name == "nt" else "tesseract"
        env_exe = os.environ.get("PDF2WORD_TESSERACT")
        env_data = os.environ.get("PDF2WORD_TESSDATA")
        if env_exe and os.path.isfile(env_exe):
            return env_exe, env_data
        for root in _resource_roots():
            exe = os.path.join(root, "tesseract", exe_name)
            if os.path.isfile(exe):
                data = env_data or os.path.join(root, "tesseract", "tessdata")
                return exe, data if os.path.isdir(data) else None
        exe = shutil.which("tesseract")
        if not exe and os.name == "nt":
            for base in (os.environ.get("ProgramFiles", r"C:\Program Files"),
                         os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")):
                cand = os.path.join(base, "Tesseract-OCR", exe_name)
                if os.path.isfile(cand):
                    exe = cand
                    break
        if not exe:
            raise OcrError(
                "Не найден движок распознавания Tesseract. "
                "Скачайте готовую сборку программы (в ней всё уже есть).")
        return exe, env_data

    def available_langs(self) -> set[str]:
        out = self._run(b"", ["--list-langs"], use_stdin=False)
        return {ln.strip() for ln in out.splitlines()[1:] if ln.strip() and " " not in ln.strip()}

    # -------------------------------------------------------------- execution
    def cancel(self):
        self.cancelled.set()
        with self._lock:
            procs = list(self._procs)
        for p in procs:
            try:
                p.kill()
            except OSError:
                pass

    def check(self):
        if self.cancelled.is_set():
            raise Cancelled()

    def _run(self, data: bytes, args: list[str], use_stdin: bool = True,
             timeout: float = 900) -> str:
        self.check()
        cmd = [self.exe]
        if use_stdin:
            cmd += ["stdin", "stdout"]
        cwd = None
        if self.tessdata:
            # относительный путь к моделям: не зависит от букв в пути
            cwd = os.path.dirname(self.tessdata)
            cmd += ["--tessdata-dir", os.path.basename(self.tessdata)]
        cmd += args
        env = dict(os.environ)
        env["OMP_THREAD_LIMIT"] = "1"
        flags = 0
        if os.name == "nt":
            flags = 0x08000000  # CREATE_NO_WINDOW
        proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, cwd=cwd, env=env, creationflags=flags)
        with self._lock:
            self._procs.add(proc)
        try:
            out, err = proc.communicate(data, timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            raise OcrError("Tesseract не ответил за отведённое время")
        finally:
            with self._lock:
                self._procs.discard(proc)
        self.check()
        if proc.returncode != 0:
            msg = err.decode("utf-8", "replace").strip()
            raise OcrError(f"Ошибка Tesseract ({proc.returncode}): {msg[-500:]}")
        return out.decode("utf-8", "replace")

    # ---------------------------------------------------------------- queries
    def osd(self, png: bytes, dpi: int) -> tuple[int, float, str, float]:
        """(на сколько градусов по часовой повернуть, уверенность, письменность,
        уверенность в письменности)."""
        try:
            out = self._run(png, ["--psm", "0", "-l", "osd", "--dpi", str(dpi)])
        except OcrError:
            return 0, 0.0, "", 0.0
        rot = re.search(r"Rotate:\s*(\d+)", out)
        conf = re.search(r"Orientation confidence:\s*([\d.]+)", out)
        script = re.search(r"Script:\s*(\w+)", out)
        sconf = re.search(r"Script confidence:\s*([\d.]+)", out)
        if not rot:
            return 0, 0.0, "", 0.0
        return (int(rot.group(1)) % 360, float(conf.group(1)) if conf else 0.0,
                script.group(1) if script else "", float(sconf.group(1)) if sconf else 0.0)

    _langs_cache: set[str] | None = None

    def has_lang(self, lang: str) -> bool:
        if self._langs_cache is None:
            try:
                self._langs_cache = self.available_langs()
            except OcrError:
                self._langs_cache = set()
        return lang in self._langs_cache

    def tsv(self, image: bytes, psm: int, dpi: int, langs: str | None = None,
            extra: list[str] | None = None) -> list[TWord]:
        args = ["--psm", str(psm), "--oem", "1", "-l", langs or self.langs,
                "--dpi", str(dpi)]
        if extra:
            args += extra
        # без файла конфигурации «tsv»: его может не быть рядом с моделями
        args += ["-c", "tessedit_create_tsv=1", "-c", "tessedit_create_txt=0"]
        return parse_tsv(self._run(image, args))


def parse_tsv(text: str) -> list[TWord]:
    words: list[TWord] = []
    for row in text.splitlines()[1:]:
        parts = row.split("\t")
        if len(parts) < 12 or parts[0] != "5":
            continue
        txt = parts[11].strip()
        if not txt:
            continue
        try:
            page, block, par, line = (int(parts[i]) for i in (1, 2, 3, 4))
            left, top, width, height = (int(parts[i]) for i in (6, 7, 8, 9))
            conf = float(parts[10])
        except ValueError:
            continue
        words.append(TWord(page, block, par, line, left, top,
                           left + width, top + height, conf, txt))
    return words
