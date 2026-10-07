"""Проверка собранной программы: тестовый скан в папке с русскими буквами
и пробелами → PDFtoWord.exe --cli → проверка результата.

    python tests/smoke_exe.py dist/PDFtoWord.exe
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import make_scan  # noqa: E402


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass
    exe = os.path.abspath(sys.argv[1])
    base = os.environ.get("RUNNER_TEMP") or tempfile.gettempdir()
    folder = os.path.join(base, "Тестовая папка со сканами")
    os.makedirs(folder, exist_ok=True)
    pdf = os.path.join(folder, "скан акта сверки.pdf")
    out = os.path.join(folder, "результат распознавания.docx")
    if os.path.exists(out):
        os.remove(out)
    make_scan.main(pdf)
    t0 = time.time()
    proc = subprocess.run([exe, "--cli", pdf, "-o", out], timeout=900)
    print(f"код возврата: {proc.returncode}, время: {time.time() - t0:.1f} с")
    if proc.returncode != 0 or not os.path.isfile(out):
        print("ОШИБКА: файл не создан")
        return 1
    check = subprocess.run([sys.executable, os.path.join(HERE, "check_docx.py"), out,
                            os.path.splitext(pdf)[0] + ".txt"])
    return check.returncode


if __name__ == "__main__":
    sys.exit(main())
