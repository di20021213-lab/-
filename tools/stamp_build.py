"""Записывает дату сборки в pdf2word/_build.py — она видна в заголовке окна
программы и в свойствах готового .docx. Запускается сборкой .exe на GitHub."""

from __future__ import annotations

import datetime
import os

here = os.path.dirname(os.path.abspath(__file__))
stamp = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=3))).strftime("%d.%m.%Y")
sha = os.environ.get("GITHUB_SHA", "")[:7]
build = f"{stamp} {sha}".strip()
with open(os.path.join(here, "..", "pdf2word", "_build.py"), "w", encoding="utf-8") as f:
    f.write(f'BUILD = "{build}"\n')
print("BUILD =", build)
