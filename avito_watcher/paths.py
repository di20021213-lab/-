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


def venv_hint(exc: BaseException) -> str:
    """Объяснение вместо голого ModuleNotFoundError.

    Зависимости живут в .venv, а по привычке набирается `python3 скрипт.py` —
    системный питон, где ничего этого нет. Голая трассировка про 'dotenv' не
    подсказывает, что делать, поэтому подсказываем сами и называем готовую
    команду с путём именно к этому скрипту.
    """
    venv = app_dir() / ".venv" / "bin" / "python"
    script = Path(sys.argv[0]).name or "скрипт.py"
    lines = [
        f"Не хватает библиотеки: {exc}",
        "",
        "Похоже, запущено системным питоном. Зависимости стоят в виртуальном",
        "окружении проекта — запускать надо его питоном:",
        "",
        f"    {venv if venv.exists() else '.venv/bin/python'} {script} "
        + " ".join(sys.argv[1:]),
    ]
    if not venv.exists():
        lines += ["", "Окружения нет вовсе — собери его:",
                  "    python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"]
    return "\n".join(lines)
