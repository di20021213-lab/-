# -*- coding: utf-8 -*-
"""Готовит иконки разделов из game-icons.net.

Сайт отдаёт глиф белым по чёрному квадрату; здесь подложка убирается,
а глиф перекрашивается под дерево интерфейса. Лицензия CC BY 3.0 —
авторы указаны в CREDITS.md и в окне «Об игре».

Скачивание (по одному файлу на иконку):
    curl -o gi/<ключ>.svg "https://game-icons.net/icons/ffffff/000000/1x1/<автор>/<имя>.svg"
Запуск: python3 tools/make-ui-icons.py <папка со скачанными svg>
"""
import os, re, sys

SRC = sys.argv[1] if len(sys.argv) > 1 else "gi"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "public", "img", "ui")
INK = "#4a2f12"          # тёмное дерево, как у надписей в интерфейсе
os.makedirs(OUT, exist_ok=True)

n = 0
for f in sorted(os.listdir(SRC)):
    if not f.endswith(".svg"):
        continue
    s = open(os.path.join(SRC, f), encoding="utf-8").read()
    if "<svg" not in s:
        continue
    s = re.sub(r'<path d="M0 0h512v512H0z"\s*/>', "", s)      # чёрная подложка
    s = s.replace('fill="#fff"', 'fill="%s"' % INK)
    s = s.replace('fill="#ffffff"', 'fill="%s"' % INK)
    open(os.path.join(OUT, f), "w", encoding="utf-8").write(s)
    n += 1
print("иконок готово:", n, "->", os.path.normpath(OUT))
