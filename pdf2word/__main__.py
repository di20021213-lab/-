"""Запуск из командной строки: python -m pdf2word файл.pdf [-o результат.docx]"""

import argparse
import os
import sys
import time

from .pipeline import Options, convert


def _utf8_console():
    """В консоли Windows с кодировкой cp1251/cp866 русские буквы не должны
    ронять программу."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


def main(argv=None):
    _utf8_console()
    ap = argparse.ArgumentParser(prog="pdf2word", description="Распознать PDF/скан в Word (.docx)")
    ap.add_argument("files", nargs="+", help="PDF или картинки (JPG, PNG, TIFF)")
    ap.add_argument("-o", "--output", help="имя выходного .docx (для одного файла)")
    ap.add_argument("--keep-stamps", action="store_true", help="не стирать синие печати и подписи")
    ap.add_argument("--lang", default="rus", help="языки Tesseract (rus, rus+eng, ...), по умолчанию rus")
    ap.add_argument("--workers", type=int, default=0, help="сколько страниц распознавать параллельно")
    args = ap.parse_args(argv)
    opts = Options(remove_stamps=not args.keep_stamps, langs=args.lang, workers=args.workers)
    rc = 0
    for path in args.files:
        out = args.output if (args.output and len(args.files) == 1) else \
            os.path.splitext(path)[0] + ".docx"
        t0 = time.time()

        def progress(frac, msg):
            try:
                print(f"\r[{frac * 100:5.1f}%] {msg}        ", end="", flush=True)
            except (OSError, UnicodeError):
                pass

        try:
            convert(path, out, opts, progress)
            print(f"\n{path} -> {out} ({time.time() - t0:.1f} с)")
        except Exception as exc:  # noqa: BLE001
            print(f"\nОшибка: {path}: {exc}", file=sys.stderr)
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
