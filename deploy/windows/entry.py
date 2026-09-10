"""Точка входа для собранного exe.

Нужна отдельным файлом: PyInstaller собирает скрипт, а не модуль, и запуск
через `python -m` внутри exe недоступен.
"""

import sys

from avito_watcher.main import run

if __name__ == "__main__":
    sys.exit(run())
