"""Где лежат файлы бота — одинаково при запуске из папки и из собранного exe."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def app_dir() -> Path:
    """Папка, относительно которой ищем config.yaml, .env и базу.

    Собранный exe запускают двойным щелчком или Планировщиком задач, и рабочей
    папкой в этих случаях бывает что угодно — вплоть до C:\\Windows\\System32.
    Поэтому у замороженной сборки точка отсчёта — папка самого exe, а не cwd.
    В обычном запуске из исходников поведение прежнее: текущая папка.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path.cwd()


def resolve(path: str | os.PathLike) -> str:
    """Достраивает относительный путь до полного от app_dir(). Полный — не трогает."""
    p = Path(path)
    return str(p if p.is_absolute() else app_dir() / p)


def setup_bundled_browsers() -> Path | None:
    """Указывает Playwright на браузер рядом с exe, если он туда положен.

    Так собранную папку можно перенести на другой компьютер целиком, не запуская
    там `playwright install`. Если папки нет — ничего не меняем, и Playwright
    ищет браузер там, где обычно.
    """
    if os.getenv("PLAYWRIGHT_BROWSERS_PATH"):
        return None                      # пользователь задал сам — не спорим
    bundled = app_dir() / "browsers"
    if not bundled.is_dir():
        return None
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(bundled)
    return bundled
