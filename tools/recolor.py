# -*- coding: utf-8 -*-
"""Меняет масть на присланной картинке, сохраняя её светотень.

Нужен, когда генератор наотрез не пропускает цвет: на лошадь подряд упали
четыре формулировки, и прошла только та, где цвета не было вовсе. Картинки
приходят с плоской палитрой, поэтому масть переводится в лоб — по яркости,
без разбора формы.

Нейтральные пиксели не трогаем: под них попадают фон, белок глаза и копыта,
а их перекрашивать не надо.

Запуск из корня проекта:
    python3 tools/recolor.py assets-src/art/vladimir.jpg bay готовый.png
"""
from PIL import Image
import sys

# Светлая часть переводится в вилку «тень — свет», тёмная просто гасится.
PALETTES = {
    # Гнедая: тело каштановое, грива и хвост почти чёрные.
    "bay": {"lo": (112, 60, 32), "hi": (168, 96, 52), "dark": 0.42, "split": 175},
}


def lerp(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def recolor(src, pal):
    im = src.convert("RGB")
    px = im.load()
    w, h = im.size
    for y in range(h):
        for x in range(w):
            r, g, b = px[x, y]
            if max(r, g, b) - min(r, g, b) <= 20:
                continue                      # фон, белок глаза, копыта
            if r >= pal["split"]:
                t = min(1.0, max(0.0, (r - pal["split"]) / 80))
                px[x, y] = lerp(pal["lo"], pal["hi"], t)
            else:
                k = pal["dark"]
                px[x, y] = (round(r * k), round(g * k), round(b * k))
    return im


if __name__ == "__main__":
    if len(sys.argv) < 4 or sys.argv[2] not in PALETTES:
        raise SystemExit(__doc__ + "\nмасти: " + ", ".join(PALETTES))
    recolor(Image.open(sys.argv[1]), PALETTES[sys.argv[2]]).save(sys.argv[3])
    print("готово:", sys.argv[3])
