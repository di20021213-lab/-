# -*- coding: utf-8 -*-
"""Рисует живность в том же стиле, что двор: плоская заливка, тёмный контур.

Причина: в наборе ODDBLOT животных нет вовсе, а пиксельные спрайты Kenney
приходилось перекрашивать — все куры выходили одинаковыми, гусь был крашеной
курицей, а конь крашеной коровой. Здесь каждая порода рисуется параметрами:
своя масть, размер, пятна, гребень, рога, грива.

Породы берутся из public/content.js, чтобы список не разъезжался с игрой.
Запуск из корня проекта:
    python3 tools/make-animals.py
"""
from PIL import Image, ImageDraw, ImageFilter
import math, os, re

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
OUT = os.path.join(ROOT, "public", "img", "iso")
os.makedirs(OUT, exist_ok=True)

INK = (48, 48, 56, 255)
W = H = 440                      # рисуем крупно, ужимаем в конце
LINE = 9                         # толщина контура


def catmull(pts, steps=14, closed=True):
    """Гладкая кривая через заданные точки. Ровные эллипсы дают «шарик на
    палочках», а по опорным точкам получается силуэт с холкой, крупом и грудью."""
    p = list(pts)
    if closed:
        p = [p[-1]] + p + [p[0], p[1]]
    else:
        p = [p[0]] + p + [p[-1]]
    out = []
    for i in range(len(p) - 3):
        p0, p1, p2, p3 = p[i], p[i + 1], p[i + 2], p[i + 3]
        for s in range(steps):
            t = s / steps
            t2, t3 = t * t, t * t * t
            x = 0.5 * ((2 * p1[0]) + (-p0[0] + p2[0]) * t +
                       (2 * p0[0] - 5 * p1[0] + 4 * p2[0] - p3[0]) * t2 +
                       (-p0[0] + 3 * p1[0] - 3 * p2[0] + p3[0]) * t3)
            y = 0.5 * ((2 * p1[1]) + (-p0[1] + p2[1]) * t +
                       (2 * p0[1] - 5 * p1[1] + 4 * p2[1] - p3[1]) * t2 +
                       (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * t3)
            out.append((x, y))
    return out


def shape(d, pts, fill, w=LINE):
    """Замкнутый силуэт по опорным точкам."""
    c = catmull(pts)
    d.polygon(c, fill=fill, outline=INK)
    d.line(c + [c[0]], fill=INK, width=w, joint="curve")
    return c


def shade(c, k):
    return tuple(max(0, min(255, round(v * k))) for v in c[:3]) + (255,)


def blob(d, box, fill, w=LINE):
    d.ellipse(box, fill=fill, outline=INK, width=w)


def poly(d, pts, fill, w=LINE):
    d.polygon(pts, fill=fill, outline=INK, width=w)


def leg(d, x, y, h, wdt, hoof, col):
    """Нога: столбик с копытом или лапой."""
    d.line([(x, y), (x, y + h)], fill=INK, width=wdt + LINE)
    d.line([(x, y), (x, y + h)], fill=col, width=wdt)
    d.line([(x, y + h - wdt), (x, y + h)], fill=INK, width=wdt + LINE - 2)
    d.line([(x, y + h - wdt), (x, y + h)], fill=hoof, width=wdt)


def eye(d, x, y, r=9):
    d.ellipse([x - r, y - r, x + r, y + r], fill=INK)
    d.ellipse([x - r * 0.35, y - r * 0.6, x + r * 0.15, y - r * 0.1], fill=(255, 255, 255, 220))


def spots(d, cx, cy, rx, ry, col, seed, n=5, size=0.3):
    """Пятна по корпусу — по ним породы и различаются."""
    rnd = __import__("random").Random(seed)
    for _ in range(n):
        a = rnd.random() * math.tau
        r = rnd.random() ** 0.5
        x = cx + math.cos(a) * rx * r * 0.62
        y = cy + math.sin(a) * ry * r * 0.62
        s = rnd.uniform(0.6, 1.0) * min(rx, ry) * size
        d.ellipse([x - s, y - s * 0.8, x + s, y + s * 0.8], fill=col)


def ground(im):
    """Мягкая тень под ногами. Рисуем по ширине самого зверя, иначе тень шире
    рисунка и после обрезки по содержимому спрайт болтается в пустой плитке."""
    box = im.getbbox()
    if not box:
        return im
    x0, y0, x1, y1 = box
    sh = Image.new("RGBA", im.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(sh)
    cx, half = (x0 + x1) / 2, (x1 - x0) * 0.34
    d.ellipse([cx - half, y1 - 16, cx + half, y1 + 12], fill=(40, 34, 20, 95))
    sh = sh.filter(ImageFilter.GaussianBlur(6))
    sh.alpha_composite(im)
    return sh


# ------------------------------------------------------------------- птица
def bird(body, comb, beak, legs_col, goose=False, big=1.0, spot=None, seed=1,
         neck_col=None, legfeather=False):
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    dark, light = shade(body, 0.80), shade(body, 1.08)
    neck_col = neck_col or body
    cx, cy = W * 0.44, H * 0.56
    bw, bh = W * 0.24 * big, H * 0.19 * big
    foot = H * 0.84

    # шея и голова рисуются первыми: корпус ляжет поверх и стыка не видно
    if goose:
        nx, ny = cx + bw * 1.05, cy - bh * 2.5
        nw, hr = 40, W * 0.072 * big
    else:
        nx, ny = cx + bw * 0.95, cy - bh * 1.35
        nw, hr = 52, W * 0.085 * big
    d.line([(cx + bw * 0.3, cy), (nx, ny)], fill=INK, width=nw + LINE)
    d.line([(cx + bw * 0.3, cy), (nx, ny)], fill=neck_col, width=nw)

    # голова: не круг, а капля с затылком
    head = [(nx - hr, ny - hr * 0.2), (nx - hr * 0.55, ny - hr * 1.05),
            (nx + hr * 0.5, ny - hr * 1.0), (nx + hr, ny - hr * 0.05),
            (nx + hr * 0.6, ny + hr * 0.95), (nx - hr * 0.6, ny + hr * 0.95)]
    shape(d, head, neck_col, LINE - 2)

    # хвост: широкие перья веером, в цвет корпуса — узкие спицы читались как прутья
    fan = [(-1.35, -1.15), (-1.55, -0.55), (-1.45, 0.05)] if not goose else [(-1.1, -0.35), (-1.2, 0.2)]
    for i, (fx, fy) in enumerate(fan):
        tipx, tipy = cx + bw * fx, cy + bh * fy
        shape(d, [(cx - bw * 0.55, cy - bh * 0.1),
                  (tipx + bw * 0.12, tipy - bh * 0.3),
                  (tipx, tipy + bh * 0.15),
                  (cx - bw * 0.5, cy + bh * 0.55)],
              shade(body, 0.86 if i % 2 else 0.94), LINE - 3)

    # корпус
    body_pts = [(cx - bw * 0.95, cy - bh * 0.15), (cx - bw * 0.5, cy - bh * 1.0),
                (cx + bw * 0.45, cy - bh * 1.05), (cx + bw, cy - bh * 0.1),
                (cx + bw * 0.8, cy + bh * 0.85), (cx - bw * 0.4, cy + bh * 1.0)]
    shape(d, body_pts, body)
    if spot:
        spots(d, cx, cy, bw, bh, spot, seed, n=7, size=0.3)
        shape(d, body_pts, None)

    # крыло: капля с насечками на конце
    wx, wy = cx + bw * 0.12, cy + bh * 0.18
    wing = [(wx - bw * 0.55, wy - bh * 0.1), (wx - bw * 0.1, wy - bh * 0.55),
            (wx + bw * 0.6, wy - bh * 0.15), (wx + bw * 0.25, wy + bh * 0.6),
            (wx - bw * 0.35, wy + bh * 0.5)]
    shape(d, wing, shade(body, 0.90), LINE - 3)
    for i in range(3):
        x0 = wx - bw * 0.3 + i * bw * 0.3
        d.line([(x0, wy + bh * 0.25), (x0 + bw * 0.12, wy + bh * 0.55)], fill=INK, width=4)

    # ноги
    lh = foot - (cy + bh * 0.75)
    for dx, col in ((-bw * 0.25, shade(legs_col, 0.78)), (bw * 0.3, legs_col)):
        x = cx + dx
        d.line([(x, cy + bh * 0.6), (x, foot)], fill=INK, width=17)
        d.line([(x, cy + bh * 0.6), (x, foot)], fill=col, width=10)
        for tx in (-18, 4, 20):                     # пальцы
            d.line([(x, foot), (x + tx, foot + 10)], fill=INK, width=11)
            d.line([(x, foot), (x + tx, foot + 10)], fill=col, width=5)
    if legfeather:                                  # мохноногость брамы
        for dx in (-bw * 0.25, bw * 0.3):
            x = cx + dx
            shape(d, [(x - bw * 0.22, cy + bh * 0.65), (x + bw * 0.22, cy + bh * 0.65),
                      (x + bw * 0.16, foot - 34), (x - bw * 0.02, foot - 18),
                      (x - bw * 0.2, foot - 30)], light, LINE - 4)

    # гребень, серьги, клюв
    if goose:
        if comb:
            shape(d, [(nx + hr * 0.15, ny - hr * 0.75), (nx + hr * 0.55, ny - hr * 1.45),
                      (nx + hr * 0.95, ny - hr * 0.65)], comb, LINE - 4)
        poly(d, [(nx + hr * 0.75, ny - hr * 0.35), (nx + hr * 2.6, ny + hr * 0.2),
                 (nx + hr * 0.75, ny + hr * 0.75)], beak, LINE - 3)
    else:
        cpts = [(nx - hr * 0.75, ny - hr * 0.8)]
        for i in range(3):
            t = (i + 0.5) / 3.0
            cpts.append((nx - hr * 0.75 + hr * 1.5 * t, ny - hr * (1.35 + 0.35 * (i % 2))))
        cpts.append((nx + hr * 0.75, ny - hr * 0.75))
        poly(d, cpts, comb, LINE - 4)
        poly(d, [(nx + hr * 0.2, ny + hr * 0.7), (nx + hr * 0.7, ny + hr * 1.65),
                 (nx - hr * 0.1, ny + hr * 1.2)], comb, LINE - 4)
        poly(d, [(nx + hr * 0.8, ny - hr * 0.1), (nx + hr * 1.95, ny + hr * 0.3),
                 (nx + hr * 0.8, ny + hr * 0.7)], beak, LINE - 3)
    eye(d, nx + hr * 0.3, ny - hr * 0.25, 10)
    return ground(im)


# -------------------------------------------------------------------- свинья
def hog(body, ear=None, big=1.0, spot=None, seed=2, belly=False):
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    dark, light = shade(body, 0.78), shade(body, 1.10)
    ear = ear or dark
    cx, cy = W * 0.44, H * 0.54
    bw, bh = W * 0.28 * big, H * 0.17 * big * (1.2 if belly else 1.0)
    foot = H * 0.86

    for dx in (-bw * 0.5, bw * 0.5):                # дальние ноги
        x = cx + dx + 16
        d.line([(x, cy + bh * 0.4), (x, foot - 10)], fill=INK, width=26)
        d.line([(x, cy + bh * 0.4), (x, foot - 10)], fill=dark, width=18)
        d.line([(x, foot - 26), (x, foot - 10)], fill=INK, width=24)

    tp = [(cx - bw * 0.95, cy - bh * 0.5)]          # хвост крючком
    for i in range(1, 10):
        a = i * 0.85
        tp.append((cx - bw * 0.95 - 8 - math.sin(a) * 20, cy - bh * 0.5 - 7 * i + math.cos(a) * 20))
    d.line(tp, fill=INK, width=16, joint="curve")
    d.line(tp, fill=body, width=9, joint="curve")

    # корпус: спина с провисом, круп и грудь
    body_pts = [(cx - bw, cy - bh * 0.25), (cx - bw * 0.6, cy - bh * 1.05),
                (cx + bw * 0.25, cy - bh * 1.15), (cx + bw * 0.95, cy - bh * 0.55),
                (cx + bw, cy + bh * 0.5), (cx + bw * 0.4, cy + bh * 1.1),
                (cx - bw * 0.55, cy + bh * 1.05)]
    shape(d, body_pts, body)
    if spot:
        spots(d, cx, cy, bw, bh, spot, seed, n=5, size=0.42)
        shape(d, body_pts, None)

    for dx in (-bw * 0.45, bw * 0.45):              # ближние ноги
        x = cx + dx
        d.line([(x, cy + bh * 0.5), (x, foot)], fill=INK, width=30)
        d.line([(x, cy + bh * 0.5), (x, foot)], fill=body, width=22)
        d.line([(x, foot - 24), (x, foot)], fill=INK, width=28)
        d.line([(x - 3, foot - 8), (x - 3, foot)], fill=shade(body, 0.55), width=10)

    # голова с пятаком
    hx, hy = cx + bw * 1.0, cy - bh * 0.5
    hr = W * 0.115 * big
    head = [(hx - hr * 0.9, hy - hr * 0.9), (hx + hr * 0.2, hy - hr * 1.05),
            (hx + hr * 1.0, hy - hr * 0.25), (hx + hr * 0.95, hy + hr * 0.75),
            (hx - hr * 0.2, hy + hr * 1.0), (hx - hr * 1.0, hy + hr * 0.25)]
    shape(d, head, body, LINE - 1)
    poly(d, [(hx - hr * 0.55, hy - hr * 0.85), (hx - hr * 0.1, hy - hr * 1.75),
             (hx + hr * 0.45, hy - hr * 0.8)], ear, LINE - 3)          # ухо
    snout = [hx + hr * 0.6, hy + hr * 0.05, hx + hr * 1.7, hy + hr * 0.95]
    blob(d, snout, light, LINE - 3)
    for nx in (hr * 1.0, hr * 1.35):
        d.ellipse([hx + nx - 7, hy + hr * 0.35, hx + nx + 7, hy + hr * 0.68], fill=INK)
    eye(d, hx + hr * 0.3, hy - hr * 0.25, 10)
    return ground(im)


# ------------------------------------------------------------ корова и конь
def cattle(body, patch=None, horns=None, mane=None, udder=None, big=1.0, seed=3, heavy=False):
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    dark, light = shade(body, 0.76), shade(body, 1.10)
    cx, cy = W * 0.42, H * 0.46
    bw, bh = W * 0.27 * big, H * 0.15 * big
    foot = H * 0.87
    legw = 26 if not heavy else 34

    for dx in (-bw * 0.6, bw * 0.55):               # дальние ноги
        x = cx + dx + 18
        d.line([(x, cy + bh * 0.3), (x, foot - 12)], fill=INK, width=legw)
        d.line([(x, cy + bh * 0.3), (x, foot - 12)], fill=dark, width=legw - 9)
        d.line([(x, foot - 30), (x, foot - 12)], fill=INK, width=legw - 2)

    # хвост с кисточкой
    tail = [(cx - bw * 0.95, cy - bh * 0.7), (cx - bw * 1.15, cy + bh * 0.9),
            (cx - bw * 1.05, cy + bh * 2.4)]
    d.line(catmull(tail, closed=False), fill=INK, width=18, joint="curve")
    d.line(catmull(tail, closed=False), fill=dark, width=10, joint="curve")
    shape(d, [(cx - bw * 1.2, cy + bh * 2.2), (cx - bw * 0.95, cy + bh * 2.35),
              (cx - bw * 1.05, cy + bh * 3.1), (cx - bw * 1.25, cy + bh * 2.7)],
          mane or dark, LINE - 4)

    # корпус: холка, спина, круп
    body_pts = [(cx - bw, cy - bh * 0.6), (cx - bw * 0.45, cy - bh * 1.15),
                (cx + bw * 0.45, cy - bh * (1.3 if heavy else 1.1)),
                (cx + bw, cy - bh * 0.45), (cx + bw * 0.85, cy + bh * 0.7),
                (cx + bw * 0.1, cy + bh * (1.0 if not heavy else 1.15)),
                (cx - bw * 0.8, cy + bh * 0.8)]
    shape(d, body_pts, body)
    if patch:
        spots(d, cx, cy, bw, bh, patch, seed, n=4, size=0.55)
        shape(d, body_pts, None)
    if udder:
        blob(d, [cx - bw * 0.2, cy + bh * 0.55, cx + bw * 0.3, cy + bh * 1.5], udder, LINE - 3)

    for dx in (-bw * 0.5, bw * 0.6):                # ближние ноги
        x = cx + dx
        d.line([(x, cy + bh * 0.4), (x, foot)], fill=INK, width=legw + 6)
        d.line([(x, cy + bh * 0.4), (x, foot)], fill=body, width=legw - 3)
        d.line([(x, foot - 26), (x, foot)], fill=INK, width=legw + 4)
        d.line([(x, foot - 12), (x, foot)], fill=shade(body, 0.5), width=legw - 6)
        if heavy:                                    # щётки на бабках
            shape(d, [(x - 22, foot - 46), (x + 22, foot - 46), (x + 18, foot - 8),
                      (x - 18, foot - 8)], light, LINE - 4)

    # шея и голова
    hx, hy = cx + bw * (1.35 if heavy else 1.25), cy - bh * (2.0 if heavy else 1.55)
    d.line([(cx + bw * 0.55, cy - bh * 0.75), (hx, hy)], fill=INK, width=(72 if heavy else 60))
    d.line([(cx + bw * 0.55, cy - bh * 0.75), (hx, hy)], fill=body, width=(62 if heavy else 50))
    hr = W * (0.095 if heavy else 0.12) * big
    if heavy:                                        # вытянутая морда коня
        head = [(hx - hr * 0.85, hy - hr * 0.85), (hx + hr * 0.35, hy - hr * 1.0),
                (hx + hr * 0.95, hy - hr * 0.2), (hx + hr * 1.35, hy + hr * 1.15),
                (hx + hr * 0.75, hy + hr * 1.6), (hx - hr * 0.3, hy + hr * 0.7)]
    else:
        head = [(hx - hr * 0.95, hy - hr * 0.8), (hx + hr * 0.3, hy - hr * 1.05),
                (hx + hr * 1.05, hy - hr * 0.25), (hx + hr * 1.0, hy + hr * 0.85),
                (hx + hr * 0.1, hy + hr * 1.35), (hx - hr * 0.85, hy + hr * 0.45)]
    shape(d, head, body, LINE - 1)

    if mane:                                         # грива по гребню шеи
        mp = [(cx + bw * 0.5, cy - bh * 1.25)]
        for i in range(1, 6):
            t = i / 5.0
            mp.append((cx + bw * 0.5 + (hx - hr * 0.6 - cx - bw * 0.5) * t,
                       cy - bh * 1.25 + (hy - hr * 0.6 - cy + bh * 1.25) * t))
        d.line(catmull(mp, closed=False), fill=INK, width=34, joint="curve")
        d.line(catmull(mp, closed=False), fill=mane, width=24, joint="curve")
    if horns:
        for sx, ang in ((-1, 0.95), (1, 0.8)):
            poly(d, [(hx + sx * hr * 0.35, hy - hr * 0.8),
                     (hx + sx * hr * 1.25, hy - hr * (0.9 + ang)),
                     (hx + sx * hr * 1.1, hy - hr * 0.5),
                     (hx + sx * hr * 0.75, hy - hr * 0.55)], horns, LINE - 4)
        for sx in (-1, 1):                           # уши под рогами
            poly(d, [(hx + sx * hr * 0.55, hy - hr * 0.5), (hx + sx * hr * 1.5, hy - hr * 0.15),
                     (hx + sx * hr * 0.6, hy + hr * 0.15)], dark, LINE - 4)
    else:
        poly(d, [(hx - hr * 0.55, hy - hr * 0.75), (hx - hr * 0.25, hy - hr * 1.7),
                 (hx + hr * 0.2, hy - hr * 0.8)], dark, LINE - 4)
        poly(d, [(hx - hr * 0.1, hy - hr * 0.85), (hx + hr * 0.3, hy - hr * 1.6),
                 (hx + hr * 0.55, hy - hr * 0.7)], body, LINE - 4)
    mz = ([hx + hr * 0.6, hy + hr * 0.75, hx + hr * 1.5, hy + hr * 1.6] if heavy
          else [hx + hr * 0.35, hy + hr * 0.4, hx + hr * 1.25, hy + hr * 1.3])
    blob(d, mz, shade(body, 0.86) if heavy else light, LINE - 3)
    for nx in ((hr * 0.95, hr * 1.25) if heavy else (hr * 0.65, hr * 0.98)):
        d.ellipse([hx + nx - 7, mz[1] + hr * 0.25, hx + nx + 7, mz[1] + hr * 0.55], fill=INK)
    eye(d, hx + hr * (0.25 if not heavy else 0.2), hy - hr * 0.3, 11)
    return ground(im)


# ------------------------------------------------------------------- породы
WHITE = (238, 236, 228, 255)
RED   = (196, 74, 58, 255)
GOLD  = (222, 170, 72, 255)
BROWN = (150, 104, 62, 255)
DARK  = (86, 74, 68, 255)
PINK  = (226, 166, 162, 255)
GREY  = (176, 176, 170, 255)
BLACK = (72, 66, 70, 255)
ORANGE= (226, 150, 62, 255)
CREAM = (232, 214, 176, 255)

ANIMALS = {
    # куры
    "rusbel":  lambda: bird(WHITE, RED, ORANGE, GOLD),
    "leggorn": lambda: bird(WHITE, RED, GOLD, GOLD, big=1.06, neck_col=(246, 244, 238, 255)),
    "kuchin":  lambda: bird((178, 96, 54, 255), RED, GOLD, GOLD, big=1.05,
                            spot=(140, 66, 40, 255), seed=5, neck_col=GOLD),
    "brama":   lambda: bird(CREAM, RED, GOLD, CREAM, big=1.18,
                            spot=(96, 88, 92, 255), seed=7, legfeather=True),
    # гуси
    "tula":    lambda: bird((168, 166, 158, 255), None, ORANGE, ORANGE, goose=True, big=1.05,
                            spot=(122, 120, 114, 255), seed=9, neck_col=(196, 194, 186, 255)),
    "holmgus": lambda: bird(WHITE, (226, 150, 62, 255), ORANGE, ORANGE, goose=True, big=1.15,
                            neck_col=WHITE),
    # свиньи
    "vietnam": lambda: hog((96, 86, 92, 255), ear=(66, 58, 64, 255), big=0.92, belly=True,
                           spot=(70, 62, 68, 255), seed=23),
    "mirgorod":lambda: hog(PINK, big=1.0, spot=BLACK, seed=11),
    "landras": lambda: hog((236, 190, 186, 255), big=1.12),
    "krupbel": lambda: hog((242, 206, 200, 255), big=1.25),
    # коровы
    "holmkor": lambda: cattle(WHITE, patch=BLACK, horns=CREAM, udder=PINK, big=1.0, seed=13),
    "simment": lambda: cattle((214, 138, 92, 255), patch=WHITE, horns=CREAM, udder=PINK,
                              big=1.1, seed=17),
    # конь
    "vladimir":lambda: cattle(BROWN, mane=DARK, big=1.15, heavy=True, seed=19),
}


def breeds_from_content():
    src = open(os.path.join(ROOT, "public", "content.js"), encoding="utf-8").read()
    return set(re.findall(r'\{id:"(\w+)",\s*h:"(?:kury|gusi|svini|korovy|koni)"', src))


if __name__ == "__main__":
    want = breeds_from_content()
    have = set(ANIMALS)
    if want - have:
        raise SystemExit("нет рисунка для пород: " + ", ".join(sorted(want - have)))
    if have - want:
        print("лишние (нет в справочнике):", ", ".join(sorted(have - want)))
    for key, draw in ANIMALS.items():
        im = draw()
        box = im.getbbox()
        im = im.crop(box)
        im = im.resize((200, max(1, round(im.height * 200 / im.width))), Image.LANCZOS)
        im.save(os.path.join(OUT, "breed-" + key + ".png"), optimize=True)
    print("нарисовано пород:", len(ANIMALS))
