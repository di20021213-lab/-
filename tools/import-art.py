# -*- coding: utf-8 -*-
"""Готовит присланную картинку животного к игре: снимает фон, обрезает, ужимает.

Картинки приходят квадратными (обычно 1024×1024) и с «прозрачным» фоном,
который на деле нарисован шашечками или просто белый. Плюс под ногами часто
лежит серый эллипс-тень — она своя у каждой картинки и во дворе выглядит
блином, поэтому её тоже срезаем и подставляем общую мягкую тень.

Фон ищется заливкой от краёв по признаку «серое и светлое»: тушка животного
цветная, а шашечки и тень — нейтральные, поэтому заливка до них не достаёт.

Запуск из корня проекта:
    python3 tools/import-art.py картинка.png rusbel
    python3 tools/import-art.py картинка.png rusbel --keep-shadow
    python3 tools/import-art.py картинка.png rusbel --flip      # смотрит влево
"""
from PIL import Image, ImageDraw, ImageFilter
from collections import deque
import os, sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
OUT = os.path.join(ROOT, "public", "img", "iso")
WIDTH = 200                       # столько же, сколько у остальных пород


def is_backdrop(px, bright=168, spread=14):
    """Нейтральный и светлый — значит фон или тень, а не животное."""
    r, g, b = px[:3]
    return max(r, g, b) >= bright and max(r, g, b) - min(r, g, b) <= spread


def cut_background(im):
    """Заливка от краёв: всё связное с рамкой и похожее на фон становится дырой."""
    im = im.convert("RGBA")
    w, h = im.size
    px = im.load()
    alpha = Image.new("L", (w, h), 255)
    ap = alpha.load()

    seen = bytearray(w * h)
    q = deque()

    def push(x, y):
        i = y * w + x
        if seen[i]:
            return
        seen[i] = 1
        if px[x, y][3] == 0 or is_backdrop(px[x, y]):
            ap[x, y] = 0
            q.append((x, y))

    for x in range(w):
        push(x, 0); push(x, h - 1)
    for y in range(h):
        push(0, y); push(w - 1, y)

    while q:
        x, y = q.popleft()
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= nx < w and 0 <= ny < h:
                push(nx, ny)

    # JPEG оставляет по контуру светлую кайму: подчищаем полупрозрачную кромку
    alpha = alpha.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(0.6))
    im.putalpha(alpha)
    return im


def drop_ground(im, band=0.12):
    """Срезает нарисованную под ногами тень.

    Тень бывает не серой, а тёплой — у белого гуся (232,216,206). По цвету её
    от белого пера не отличить, по строкам тоже: в строках со ступнёй лежат и
    лапа, и тень. Зато тень всегда стелется вокруг ног, а не выше.

    Поэтому ищем нижнюю точку самого зверя — последний непрозрачный пиксель,
    который не бледный (лапы оранжевые, копыта тёмные), — и в полосе вокруг неё
    гасим всё бледное. Туша выше этой полосы и не страдает.
    """
    w, h = im.size
    px = im.load()

    def pale(p):
        r, g, b, a = p
        return a > 40 and min(r, g, b) >= 160 and (max(r, g, b) - min(r, g, b)) <= 38

    feet = 0
    for y in range(h):
        for x in range(w):
            p = px[x, y]
            if p[3] > 40 and not pale(p):
                feet = y
                break
        else:
            continue
    y0 = max(0, feet - int(h * band))
    for y in range(y0, h):
        for x in range(w):
            p = px[x, y]
            if pale(p) or (p[3] and is_backdrop(p[:3], bright=150, spread=18)):
                px[x, y] = (p[0], p[1], p[2], 0)
    return im


def shadow(im):
    """Общая мягкая тень — такая же, как у отрисованных пород."""
    box = im.getbbox()
    if not box:
        return im
    x0, y0, x1, y1 = box
    pad = Image.new("RGBA", (im.width, im.height + 24), (0, 0, 0, 0))
    pad.alpha_composite(im)
    d = ImageDraw.Draw(pad)
    sh = Image.new("RGBA", pad.size, (0, 0, 0, 0))
    ds = ImageDraw.Draw(sh)
    cx, half = (x0 + x1) / 2, (x1 - x0) * 0.36
    ds.ellipse([cx - half, y1 - 14, cx + half, y1 + 18], fill=(40, 34, 20, 95))
    sh = sh.filter(ImageFilter.GaussianBlur(9))
    sh.alpha_composite(pad)
    return sh


def prepare(path, keep_shadow=False, flip=False):
    im = Image.open(path)
    im = cut_background(im)
    if flip:
        im = im.transpose(Image.FLIP_LEFT_RIGHT)   # во дворе все смотрят вправо
    if not keep_shadow:
        im = drop_ground(im)
    box = im.getbbox()
    if not box:
        raise SystemExit("после обрезки ничего не осталось — проверь картинку")
    im = im.crop(box)
    im = im.resize((WIDTH, max(1, round(im.height * WIDTH / im.width))), Image.LANCZOS)
    return shadow(im)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) < 2:
        raise SystemExit(__doc__)
    src, key = args[0], args[1]
    im = prepare(src, keep_shadow="--keep-shadow" in sys.argv, flip="--flip" in sys.argv)
    os.makedirs(OUT, exist_ok=True)
    dst = os.path.join(OUT, "breed-" + key + ".png")
    im.save(dst, optimize=True)
    print("готово:", dst, im.size)
