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
    python3 tools/recolor.py пакет.jpg green готовый.png --only 0
"""
from PIL import Image, ImageChops
import sys

# Светлая часть переводится в вилку «тень — свет», тёмная просто гасится.
PALETTES = {
    # Гнедая: тело каштановое, грива и хвост почти чёрные.
    "bay": {"lo": (112, 60, 32), "hi": (168, 96, 52), "dark": 0.42, "split": 175},
}

# Смена тона: цветным пикселям задаётся новый тон, светотень и насыщенность
# остаются свои. Так сорта корма разводятся цветом от одного пакета — четыре
# отдельные генерации дали бы четыре разные формы, и цветовой код развалился
# бы. Серое и белое не трогаем: под них попадают фон, блики и тёмный контур.
HUES = {"red": 0, "green": 85, "blue": 145, "purple": 190}


def rehue(src, hue, only=None, width=12):
    """Перекрашивает насыщенные пиксели в заданный тон (0–255 по шкале PIL).

    `only` сужает перекраску до пикселей, чей тон лежит около заданного —
    иначе вместе с пакетом корма перекрасится и картинка на этикетке, и
    выйдет синяя корова на синей траве. Тон замкнут в кольцо, поэтому
    расстояние считаем по кольцу: красный лежит и около 0, и около 255.
    """
    hsv = src.convert("RGB").convert("HSV")
    h, s, v = hsv.split()
    mask = s.point(lambda x: 255 if x > 40 else 0)
    if only is not None:
        ring = [255 if min(abs(i - only), 256 - abs(i - only)) <= width else 0
                for i in range(256)]
        mask = ImageChops.multiply(mask, h.point(ring))
    h = Image.composite(Image.new("L", src.size, hue), h, mask)
    return Image.merge("HSV", (h, s, v)).convert("RGB")


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
    if len(sys.argv) < 4 or (sys.argv[2] not in PALETTES and sys.argv[2] not in HUES):
        raise SystemExit(__doc__ + "\nмасти: " + ", ".join(PALETTES) +
                         "\nтона: " + ", ".join(HUES))
    src, name, dst = sys.argv[1], sys.argv[2], sys.argv[3]
    # «--only <тон>» — перекрашивать лишь то, что уже этого тона: так у пакета
    # корма меняется цвет мешка, а картинка на этикетке остаётся своей.
    only = None
    if "--only" in sys.argv:
        only = int(sys.argv[sys.argv.index("--only") + 1])
    out = (rehue(Image.open(src), HUES[name], only) if name in HUES
           else recolor(Image.open(src), PALETTES[name]))
    out.save(dst)
    print("готово:", dst)
