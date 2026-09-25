# -*- coding: utf-8 -*-
"""Рисует фон двора и перекрашивает постройки под деревенский вид.

Причина: в наборе ODDBLOT все строения — американские красные амбары с
гофрированной крышей, а фон двора был CSS-градиентом. На скринах оригинала
двор другой: соломенные и черепичные крыши, мазанка, брёвна, плетень по
периметру, вытоптанная земля посередине и зелёный луг с прудом за забором.

Палитра набора плоская (стена — ровно два цвета, крыша — ровно два), поэтому
перекраска идёт точной заменой цветов, а фактура (солома, черепица, брёвна)
дорисовывается штрихами по маске каждой плоскости. Так сохраняется рисованный
свет оригинальных спрайтов.

Запуск из корня проекта:
    python3 tools/make-scene.py путь/к/Gr8FarmPack
"""
from PIL import Image, ImageDraw, ImageFilter, ImageChops
import math, os, random, sys

SRC = sys.argv[1] if len(sys.argv) > 1 else "Gr8FarmPack"
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
OUT = os.path.join(ROOT, "public", "img", "iso")
os.makedirs(OUT, exist_ok=True)

INK = (48, 48, 56)


def load(name):
    return Image.open(os.path.join(SRC, name + ".png")).convert("RGBA")


def trim(im):
    box = im.getbbox()
    return im.crop(box) if box else im


def fit(im, w):
    im = trim(im)
    if im.width <= w:
        return im
    return im.resize((w, max(1, round(im.height * w / im.width))), Image.LANCZOS)


def save(im, name):
    im.save(os.path.join(OUT, name + ".png"), optimize=True)
    return name


# ----------------------------------------------------------------- перекраска
# Плоские цвета набора: крыша светлая/тёмная, стена светлая/тёмная.
ROOF_HI, ROOF_LO = (232, 224, 216), (184, 184, 176)
WALL_HI, WALL_LO = (200, 88, 80), (160, 72, 72)

# Наборы «крыша» и «стена»: (светлая плоскость, тёмная плоскость).
ROOFS = {
    "soloma":   ((214, 178, 92),  (162, 130, 62)),   # солома
    "cherepica":((192, 88, 62),   (140, 58, 44)),    # красная черепица
    "dranka":   ((150, 126, 96),  (108, 90, 70)),    # серая дранка
}
WALLS = {
    "mazanka":  ((238, 230, 210), (200, 188, 166)),  # белёная мазанка
    "brevna":   ((186, 140, 92),  (140, 102, 66)),   # сруб
    "doski":    ((158, 130, 100), (118, 96, 74)),    # тёсаные доски
    "temdoski": ((124, 100, 78),  (92, 74, 58)),     # потемневшие доски
}


def near(px, ref, tol=26):
    return abs(px[0] - ref[0]) <= tol and abs(px[1] - ref[1]) <= tol and abs(px[2] - ref[2]) <= tol


def repaint(im, roof, wall):
    """Меняет цвета крыши и стен и отдаёт маски обеих плоскостей крыши и стены,
    чтобы поверх можно было положить фактуру."""
    im = im.copy()
    px = im.load()
    masks = {"roof_hi": [], "roof_lo": [], "wall_hi": [], "wall_lo": []}
    rh, rl = ROOFS[roof]
    wh, wl = WALLS[wall]
    for y in range(im.height):
        for x in range(im.width):
            r, g, b, a = px[x, y]
            if a < 40:
                continue
            c = (r, g, b)
            if near(c, ROOF_HI, 18):
                px[x, y] = rh + (a,); masks["roof_hi"].append((x, y))
            elif near(c, ROOF_LO, 18):
                px[x, y] = rl + (a,); masks["roof_lo"].append((x, y))
            elif near(c, WALL_HI, 22):
                px[x, y] = wh + (a,); masks["wall_hi"].append((x, y))
            elif near(c, WALL_LO, 22):
                px[x, y] = wl + (a,); masks["wall_lo"].append((x, y))
    return im, masks


def mask_image(size, pts):
    m = Image.new("L", size, 0)
    if not pts:
        return m
    mp = m.load()
    for x, y in pts:
        mp[x, y] = 255
    return m


def shade(c, k):
    return tuple(max(0, min(255, round(v * k))) for v in c)


def texture_roof(im, masks, kind, seed=1):
    """Штриховка по крыше: солома — частые вертикальные мазки,
    черепица — ряды дуг, дранка — длинные доски."""
    rnd = random.Random(seed)
    layer = Image.new("RGBA", im.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for key in ("roof_hi", "roof_lo"):
        pts = masks[key]
        if not pts:
            continue
        xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        base = ROOFS[kind][0 if key == "roof_hi" else 1]
        dark = shade(base, 0.80)
        light = shade(base, 1.10)
        if kind == "soloma":
            step = max(3, (x1 - x0) // 90)
            for x in range(x0, x1, step):
                for _ in range(3):
                    y = rnd.randint(y0, y1)
                    ln = rnd.randint((y1 - y0) // 14 + 3, (y1 - y0) // 6 + 6)
                    col = dark if rnd.random() < 0.6 else light
                    d.line([(x + rnd.randint(-1, 1), y), (x + rnd.randint(-2, 2), y + ln)],
                           fill=col + (150,), width=max(1, step // 2))
        elif kind == "cherepica":
            step = max(5, (y1 - y0) // 16)
            for y in range(y0, y1, step):
                d.line([(x0, y), (x1, y)], fill=dark + (120,), width=max(1, step // 5))
            stepx = max(6, (x1 - x0) // 26)
            for x in range(x0, x1, stepx):
                d.line([(x, y0), (x, y1)], fill=dark + (60,), width=1)
        else:  # дранка
            step = max(4, (x1 - x0) // 40)
            for x in range(x0, x1, step):
                d.line([(x, y0), (x, y1)], fill=dark + (110,), width=1)
    layer.putalpha(ImageChops.multiply(layer.split()[3],
                                       mask_image(im.size, masks["roof_hi"] + masks["roof_lo"])))
    out = im.copy()
    out.alpha_composite(layer)
    return out


def texture_wall(im, masks, kind, seed=2):
    """Брёвна — горизонтальные валики, мазанка — редкие пятна побелки,
    доски — вертикальные швы."""
    rnd = random.Random(seed)
    layer = Image.new("RGBA", im.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for key in ("wall_hi", "wall_lo"):
        pts = masks[key]
        if not pts:
            continue
        xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        base = WALLS[kind][0 if key == "wall_hi" else 1]
        dark = shade(base, 0.76)
        light = shade(base, 1.10)
        if kind == "brevna":
            step = max(5, (y1 - y0) // 13)
            for y in range(y0, y1, step):
                d.line([(x0, y), (x1, y)], fill=dark + (140,), width=max(1, step // 4))
                d.line([(x0, y + step // 3), (x1, y + step // 3)], fill=light + (70,), width=1)
        elif kind == "mazanka":
            for _ in range(240):
                x = rnd.randint(x0, x1); y = rnd.randint(y0, y1)
                r = rnd.randint(2, max(3, (x1 - x0) // 40))
                col = dark if rnd.random() < 0.5 else light
                d.ellipse([x - r, y - r, x + r, y + r], fill=col + (48,))
        else:
            step = max(4, (x1 - x0) // 34)
            for x in range(x0, x1, step):
                d.line([(x, y0), (x, y1)], fill=dark + (110,), width=1)
    layer.putalpha(ImageChops.multiply(layer.split()[3],
                                       mask_image(im.size, masks["wall_hi"] + masks["wall_lo"])))
    out = im.copy()
    out.alpha_composite(layer)
    return out


def village(name, roof, wall, seed=1):
    im, masks = repaint(load(name), roof, wall)
    im = texture_roof(im, masks, roof, seed)
    im = texture_wall(im, masks, wall, seed + 7)
    return im


# ----------------------------------------------------------------- фон двора
W, H = 1600, 1000
GRASS_HI, GRASS_LO = (124, 162, 84), (92, 132, 68)
FAR_GRASS = (104, 146, 82)
DIRT_HI, DIRT_LO = (176, 142, 96), (140, 110, 72)


def noise(w, h, scale, seed):
    rnd = random.Random(seed)
    sw, sh = max(2, w // scale), max(2, h // scale)
    small = Image.new("L", (sw, sh))
    small.putdata([rnd.randint(0, 255) for _ in range(sw * sh)])
    return small.resize((w, h), Image.BICUBIC)


def blotchy(size, c_lo, c_hi, seed, scale=48, soft=6):
    """Живой «крашеный» слой: два цвета, смешанные мягким шумом."""
    n = noise(size[0], size[1], scale, seed).filter(ImageFilter.GaussianBlur(soft))
    n2 = noise(size[0], size[1], max(4, scale // 4), seed + 1).filter(ImageFilter.GaussianBlur(2))
    n = ImageChops.blend(n, n2, 0.35)
    lo = Image.new("RGB", size, c_lo)
    hi = Image.new("RGB", size, c_hi)
    return Image.composite(hi, lo, n)


def blob(d, cx, cy, rx, ry, seed, wob=0.16, steps=160):
    """Кривой круг: радиус гуляет по нескольким синусоидам, поэтому край
    получается органическим, а не кружочками-конфетти."""
    rnd = random.Random(seed)
    waves = [(rnd.uniform(0.5, 1.0), rnd.randint(2, 3), rnd.random() * math.tau),
             (rnd.uniform(0.3, 0.6), rnd.randint(4, 6), rnd.random() * math.tau),
             (rnd.uniform(0.15, 0.3), rnd.randint(7, 11), rnd.random() * math.tau)]
    pts = []
    for i in range(steps):
        a = i / steps * math.tau
        k = 1.0 + wob * sum(amp * math.sin(f * a + ph) for amp, f, ph in waves)
        pts.append((cx + math.cos(a) * rx * k, cy + math.sin(a) * ry * k))
    d.polygon(pts, fill=255)


def dirt_mask(size, seed=5):
    """Вытоптанный двор одним куском: два наложенных кривых пятна."""
    w, h = size
    m = Image.new("L", size, 0)
    d = ImageDraw.Draw(m)
    # Верхняя кромка держится выше подошв заднего ряда: конюшня, коровник и
    # гусятник стоят на 34–39% высоты двора, и если земля не доходит, они
    # оказываются половиной на траве — видно как «дома странно стоят».
    blob(d, w * 0.50, h * 0.65, w * 0.47, h * 0.37, seed, 0.11)
    blob(d, w * 0.50, h * 0.93, w * 0.46, h * 0.19, seed + 1, 0.13)
    blob(d, w * 0.27, h * 0.40, w * 0.23, h * 0.13, seed + 2, 0.18)
    blob(d, w * 0.75, h * 0.41, w * 0.23, h * 0.13, seed + 3, 0.18)
    m = m.filter(ImageFilter.GaussianBlur(5))
    # рваная кромка: шум подмешивается только у границы пятна
    edge = m.point(lambda v: 255 - abs(v - 128) * 2)
    n = noise(w, h, 22, seed + 9).filter(ImageFilter.GaussianBlur(2))
    m = ImageChops.add(m, ImageChops.multiply(edge, n.point(lambda v: max(0, v - 128))), scale=1.6)
    return m.point(lambda v: 255 if v > 150 else (0 if v < 110 else (v - 110) * 6))


def grass_strokes(img, mask, seed=9, n=14000):
    """Мазки травы — без них заливка выглядит пластиковой."""
    rnd = random.Random(seed)
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    mp = mask.load()
    w, h = img.size
    for _ in range(n):
        x = rnd.randrange(w); y = rnd.randrange(h)
        if mp[x, y] > 60:
            continue
        ln = rnd.randint(4, 11)
        k = rnd.random()
        col = (72, 108, 60) if k < 0.45 else ((148, 180, 96) if k < 0.8 else (96, 140, 76))
        d.line([(x, y), (x + rnd.randint(-3, 3), y - ln)], fill=col + (rnd.randint(70, 150),),
               width=1 if rnd.random() < 0.7 else 2)
    img.alpha_composite(layer)


def dirt_specks(img, mask, seed=11, n=3500):
    rnd = random.Random(seed)
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    mp = mask.load()
    w, h = img.size
    for _ in range(n):
        x = rnd.randrange(w); y = rnd.randrange(h)
        if mp[x, y] < 180:
            continue
        r = rnd.randint(1, 3)
        k = rnd.random()
        col = (120, 94, 62) if k < 0.5 else ((196, 166, 118) if k < 0.85 else (88, 68, 46))
        d.ellipse([x - r, y - r, x + r, y + r], fill=col + (rnd.randint(60, 130),))
    for _ in range(26):                        # колеи от телеги
        x = rnd.randrange(w); y = rnd.randint(int(h * 0.45), h)
        ln = rnd.randint(w // 12, w // 4)
        d.line([(x, y), (x + ln, y + rnd.randint(-14, 14))], fill=(120, 94, 62, 70),
               width=rnd.randint(2, 5))
    layer.putalpha(ImageChops.multiply(layer.split()[3], mask))
    img.alpha_composite(layer)


def board_fence(d, pts, post_h, seed=3):
    """Жердевой забор по ломаной: столбы + две жерди, с обводкой как в наборе."""
    rnd = random.Random(seed)
    for i in range(len(pts) - 1):
        (x0, y0), (x1, y1) = pts[i], pts[i + 1]
        seg = math.hypot(x1 - x0, y1 - y0)
        n = max(2, int(seg / (post_h * 0.85)))
        for f in (0.34, 0.66):                 # жерди
            for j in range(n):
                t0 = j / n; t1 = (j + 1) / n
                ax, ay = x0 + (x1 - x0) * t0, y0 + (y1 - y0) * t0 - post_h * f
                bx, by = x0 + (x1 - x0) * t1, y0 + (y1 - y0) * t1 - post_h * f
                sag = post_h * 0.05
                d.line([(ax, ay), (bx, by + sag)], fill=INK, width=max(3, int(post_h * 0.17)))
                d.line([(ax, ay), (bx, by + sag)], fill=(150, 116, 78), width=max(1, int(post_h * 0.10)))
        for j in range(n + 1):
            t = j / n
            px = x0 + (x1 - x0) * t
            py = y0 + (y1 - y0) * t
            wdt = max(3, int(post_h * 0.16))
            jit = rnd.randint(-2, 2)
            d.line([(px, py), (px + jit, py - post_h)], fill=INK, width=wdt + 3)
            d.line([(px, py), (px + jit, py - post_h)], fill=(168, 132, 88), width=wdt)
            d.line([(px + 1, py - 2), (px + jit + 1, py - post_h + 2)], fill=(120, 92, 60), width=1)


def pond(img, cx, cy, rx, ry, seed=7):
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.ellipse([cx - rx - 6, cy - ry - 6, cx + rx + 6, cy + ry + 6], fill=(96, 122, 72, 255))
    d.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=(94, 146, 156, 255), outline=INK, width=4)
    rnd = random.Random(seed)
    for _ in range(26):
        y = rnd.randint(int(cy - ry * 0.7), int(cy + ry * 0.7))
        w2 = int(rx * 0.7 * math.sqrt(max(0.0, 1 - ((y - cy) / ry) ** 2)))
        x = rnd.randint(int(cx - w2), int(cx + w2 - 10)) if w2 > 12 else cx
        d.line([(x, y), (x + rnd.randint(8, 28), y)], fill=(182, 216, 220, 150), width=2)
    img.alpha_composite(layer)


def build_background():
    size = (W, H)
    img = blotchy(size, GRASS_LO, GRASS_HI, seed=21, scale=52).convert("RGBA")
    d = ImageDraw.Draw(img)

    # дальний план: поле за деревьями — светлее и холоднее, глубина сцены
    d.rectangle([0, 0, W, int(H * 0.16)], fill=FAR_GRASS + (255,))
    band = Image.new("RGBA", (W, int(H * 0.06)), (0, 0, 0, 0))
    img.alpha_composite(band, (0, int(H * 0.16)))
    pond(img, int(W * 0.13), int(H * 0.062), int(W * 0.085), int(H * 0.030))

    # лесополоса вдоль верхнего края: разный рост и шаг, иначе выходит частокол
    rnd = random.Random(4)
    trees = [trim(load("Smtree1")), trim(load("Smtree2"))]

    def treeline(base_y, lo, hi, step_lo, step_hi, dim, squash):
        x = -60
        while x < W + 60:
            t = rnd.choice(trees)
            hh = rnd.randint(int(H * lo), int(H * hi))
            ww = max(1, round(t.width * hh / t.height * rnd.uniform(0.85, 1.25)))
            t2 = t.resize((ww, hh), Image.LANCZOS)
            if squash:                      # крона пониже — деревья перестают быть одинаковыми
                t2 = t2.resize((ww, int(hh * 0.92)), Image.LANCZOS)
            if dim < 1:
                dk = Image.new("RGBA", t2.size, (34, 52, 44, int(255 * (1 - dim))))
                dk.putalpha(ImageChops.multiply(dk.split()[3], t2.split()[3]))
                t2.alpha_composite(dk)
            ty = int(H * base_y) - t2.height + rnd.randint(-6, 6)
            near_pond = W * 0.02 < x < W * 0.26 and ty < H * 0.085
            if not near_pond:
                img.alpha_composite(t2, (x, max(0, ty)))
            x += rnd.randint(int(W * step_lo), int(W * step_hi))

    treeline(0.085, 0.07, 0.10, 0.028, 0.055, 0.78, True)    # дальний план
    treeline(0.125, 0.10, 0.155, 0.045, 0.085, 1.0, False)   # ближний

    # двор
    dm = dirt_mask(size)
    dirt = blotchy(size, DIRT_LO, DIRT_HI, seed=33, scale=40).convert("RGBA")
    dirt.putalpha(dm)
    grass_strokes(img, dm, n=14000)
    img.alpha_composite(dirt)
    dirt_specks(img, dm)

    # кусты вдоль забора, уже поверх травы
    bushes = [trim(load("Smbush1")), trim(load("Flwrbush")), trim(load("Smbush2"))]
    dmp = dm.load()
    for _ in range(22):
        b = rnd.choice(bushes)
        ww = rnd.randint(60, 115)
        b2 = b.resize((ww, max(1, round(b.height * ww / b.width))), Image.LANCZOS)
        bx = rnd.randrange(0, W - ww)
        by = rnd.randint(int(H * 0.13), int(H * 0.19))
        if dmp[min(W - 1, bx + ww // 2), min(H - 1, by + b2.height)] > 60:
            continue                      # на вытоптанной земле кусты не растут
        img.alpha_composite(b2, (bx, by))

    # Забор: поперёк за постройками и по бокам с уходом в перспективу.
    # Высота выбрана не на глаз: самая высокая постройка (конюшня) занимает
    # во дворе полосу 15–34% высоты, поэтому низ забора держим выше 15%,
    # иначе рейки режут крыши заднего ряда.
    d = ImageDraw.Draw(img)
    board_fence(d, [(-20, H * 0.148), (W + 20, H * 0.148)], H * 0.062)
    board_fence(d, [(-6, H * 0.158), (-30, H * 1.05)], H * 0.075)
    board_fence(d, [(W + 6, H * 0.158), (W + 30, H * 1.05)], H * 0.075)

    # мягкая виньетка, чтобы края не спорили с постройками
    vg = Image.new("L", size, 0)
    ImageDraw.Draw(vg).ellipse([-W * 0.22, -H * 0.35, W * 1.22, H * 1.3], fill=255)
    vg = vg.filter(ImageFilter.GaussianBlur(100))
    dark = Image.new("RGBA", size, (38, 42, 28, 120))
    img = Image.composite(img, Image.alpha_composite(img, dark), vg)
    return img.convert("RGB")


def wattle(w=520, h=230, seed=6):
    """Плетень: в наборе его нет, а колючая проволока во дворе колхоза
    смотрится чужеродно. Колья + прутья, сплетённые через кол."""
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    rnd = random.Random(seed)
    posts = list(range(24, w - 10, 62))
    top, bot = int(h * 0.30), int(h * 0.92)
    for i in range(7):                       # прутья
        y = top + (bot - top) * i / 6.5
        pts = []
        for x in range(10, w - 8, 10):
            k = math.sin((x / 62.0 + i * 0.5) * math.pi) * 4
            pts.append((x, y + k + i * 0.6))
        d.line(pts, fill=INK, width=9)
        d.line(pts, fill=(172, 138, 92) if i % 2 else (146, 114, 74), width=5)
    for px in posts:                         # колья поверх — видно плетение
        jit = rnd.randint(-2, 2)
        d.line([(px, bot + 12), (px + jit, top - 22)], fill=INK, width=13)
        d.line([(px, bot + 12), (px + jit, top - 22)], fill=(120, 92, 60), width=8)
        d.line([(px + 2, bot + 8), (px + jit + 2, top - 18)], fill=(156, 124, 84), width=2)
    return im


def well(w=460, h=520):
    """Колодец: в наборе вместо него ручная колонка, а в колхозе ожидается
    сруб с воротом и двускатной крышей."""
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    cx = w // 2
    top, bot = int(h * 0.58), int(h * 0.92)
    half = int(w * 0.30)
    # сруб: передняя стенка брёвнами, верх — овал воды
    d.polygon([(cx - half, top), (cx + half, top), (cx + half, bot - 24), (cx - half, bot - 24)],
              fill=(150, 112, 70), outline=INK, width=7)
    for i in range(1, 5):
        y = top + (bot - 24 - top) * i / 5
        d.line([(cx - half + 5, y), (cx + half - 5, y)], fill=(112, 84, 52), width=5)
    d.ellipse([cx - half, top - 26, cx + half, top + 26], fill=(122, 92, 58), outline=INK, width=7)
    d.ellipse([cx - half + 16, top - 15, cx + half - 16, top + 15], fill=(86, 128, 140))
    # столбы, ворот и крыша
    for sx in (cx - half + 12, cx + half - 12):
        d.line([(sx, top - 6), (sx, int(h * 0.20))], fill=INK, width=16)
        d.line([(sx, top - 6), (sx, int(h * 0.20))], fill=(132, 100, 64), width=10)
    d.line([(cx - half + 12, int(h * 0.30)), (cx + half - 12, int(h * 0.30))], fill=INK, width=17)
    d.line([(cx - half + 12, int(h * 0.30)), (cx + half - 12, int(h * 0.30))], fill=(168, 132, 86), width=11)
    d.line([(cx + half - 4, int(h * 0.30)), (cx + half + 22, int(h * 0.36))], fill=INK, width=9)  # ручка
    roof = [(cx - half - 26, int(h * 0.22)), (cx, int(h * 0.05)), (cx + half + 26, int(h * 0.22))]
    d.polygon(roof + [(cx + half + 26, int(h * 0.27)), (cx, int(h * 0.10)), (cx - half - 26, int(h * 0.27))],
              fill=(176, 84, 60), outline=INK, width=7)
    for i in range(1, 6):                       # черепица
        y = int(h * 0.07) + i * int(h * 0.028)
        dx = int(half * 0.55 * i / 5) + 10
        d.line([(cx - dx, y + 6), (cx + dx, y + 6)], fill=(132, 56, 42), width=3)
    return im


def rooster_vane(w=340, h=580):
    """Флюгер-петух: мачта, стрелка и петух. В наборе на этом месте стояла
    водокачка — название и картинка расходились."""
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    cx, W, Hh = w // 2, w, h

    def P(fx, fy):
        return (cx + W * fx, Hh * fy)

    # мачта и раскосы
    d.line([P(0, 0.99), P(0, 0.42)], fill=INK, width=20)
    d.line([P(0, 0.99), P(0, 0.42)], fill=(120, 92, 60), width=12)
    for y in (0.62, 0.78):
        d.line([P(-0.18, y + 0.06), P(0.18, y)], fill=INK, width=8)
        d.line([P(-0.18, y), P(0.18, y + 0.06)], fill=INK, width=8)
    # стрелка направления
    d.line([P(-0.36, 0.40), P(0.36, 0.40)], fill=INK, width=9)
    d.polygon([P(0.36, 0.40), P(0.26, 0.365), P(0.26, 0.435)], fill=INK)
    d.polygon([P(-0.36, 0.40), P(-0.24, 0.372), P(-0.24, 0.428)], fill=INK)

    red, dark = (176, 62, 46), (132, 40, 30)
    # хвост — три пера назад и вверх
    for k, (tx, ty) in enumerate([(-0.40, 0.03), (-0.44, 0.11), (-0.40, 0.19)]):
        d.polygon([P(-0.10, 0.22), P(tx, ty), P(tx + 0.10, ty + 0.05), P(-0.06, 0.28)],
                  fill=dark if k % 2 else red, outline=INK, width=6)
    # туловище и грудь
    d.polygon([P(-0.12, 0.20), P(0.02, 0.15), P(0.16, 0.20), P(0.20, 0.29),
               P(0.10, 0.35), P(-0.06, 0.33), P(-0.14, 0.27)], fill=red, outline=INK, width=7)
    # шея и голова
    d.polygon([P(0.06, 0.18), P(0.16, 0.08), P(0.24, 0.10), P(0.20, 0.22)],
              fill=red, outline=INK, width=7)
    d.ellipse([P(0.10, 0.03)[0], P(0.10, 0.03)[1], P(0.30, 0.13)[0], P(0.30, 0.13)[1]],
              fill=red, outline=INK, width=7)
    # гребень, клюв, бородка
    d.polygon([P(0.12, 0.035), P(0.16, -0.01), P(0.20, 0.03), P(0.24, -0.01), P(0.27, 0.04)],
              fill=(216, 86, 66), outline=INK, width=5)
    d.polygon([P(0.29, 0.07), P(0.40, 0.085), P(0.29, 0.11)], fill=(226, 176, 72), outline=INK, width=5)
    d.polygon([P(0.24, 0.12), P(0.29, 0.17), P(0.22, 0.16)], fill=(216, 86, 66), outline=INK, width=4)
    d.ellipse([P(0.20, 0.055)[0], P(0.20, 0.055)[1], P(0.235, 0.075)[0], P(0.235, 0.075)[1]], fill=INK)
    # лапы на ось
    for fx in (-0.02, 0.08):
        d.line([P(fx, 0.33), P(fx, 0.40)], fill=INK, width=7)
    return im


def planks(w=460, h=300):
    """Стопка досок для раздела «Ресурсы»: там висели эмодзи."""
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    for i, (dx, dy) in enumerate([(0, 0), (18, -46), (-12, -92), (10, -136)]):
        x0, y0 = 40 + dx, h - 70 + dy
        pts = [(x0, y0), (x0 + 330, y0 - 34), (x0 + 330, y0 + 10), (x0, y0 + 44)]
        base = (176, 134, 86) if i % 2 else (156, 116, 74)
        d.polygon(pts, fill=base, outline=INK, width=7)
        d.line([(x0 + 8, y0 + 14), (x0 + 322, y0 - 20)], fill=(126, 94, 58), width=3)
        d.line([(x0 + 8, y0 + 28), (x0 + 322, y0 - 6)], fill=(200, 160, 110), width=2)
    return im


def nails(w=420, h=320):
    """Горсть гвоздей."""
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    rnd = random.Random(12)
    for ax, ay, bx, by in [(60, 250, 330, 150), (90, 190, 350, 240), (70, 120, 300, 90)]:
        ax += rnd.randint(-6, 6); ay += rnd.randint(-6, 6)
        d.line([(ax, ay), (bx, by)], fill=INK, width=20)
        d.line([(ax, ay), (bx, by)], fill=(168, 172, 180), width=12)
        d.line([(ax + 6, ay - 2), (bx - 20, by - 2)], fill=(214, 218, 224), width=3)
        dxn, dyn = bx - ax, by - ay
        ln = max(1.0, math.hypot(dxn, dyn))
        px, py = -dyn / ln * 26, dxn / ln * 26
        d.line([(ax - px, ay - py), (ax + px, ay + py)], fill=INK, width=20)
        d.line([(ax - px, ay - py), (ax + px, ay + py)], fill=(186, 190, 198), width=13)
    return im


def room(kind, w=1200, h=760, seed=41):
    """Интерьер постройки: бревенчатая стена и пол, на котором стоит живность.

    Пока процедурный — чтобы механика работала сразу. Заменяется присланной
    картинкой ровно так же, как заменились сами постройки: см. ART-TODO.

    Пол у всех разный: в курятнике солома, в свинарнике земля, в конюшне
    опилки. По нему сразу видно, куда зашёл, даже без подписи.
    """
    FLOORS = {"kury":   ((214, 178, 96),  (176, 142, 70)),    # солома
              "gusi":   ((206, 186, 130), (168, 148, 96)),    # подстилка
              "svini":  ((150, 120, 88),  (112, 88, 64)),     # земля
              "korovy": ((176, 150, 104), (136, 112, 76)),    # сенная труха
              "koni":   ((198, 172, 128), (158, 134, 96))}    # опилки
    f_lo, f_hi = FLOORS.get(kind, FLOORS["kury"])
    rnd = random.Random(seed)

    img = blotchy((w, h), f_lo, f_hi, seed=seed, scale=26).convert("RGBA")
    d = ImageDraw.Draw(img)

    # стена из брёвен занимает верх, пол — низ; граница чуть выше середины,
    # чтобы живности хватило места встать в два ряда
    wall_h = int(h * 0.46)
    LOG_LO, LOG_HI = (150, 108, 70), (186, 140, 92)
    logs = blotchy((w, wall_h), LOG_LO, LOG_HI, seed=seed + 1, scale=34)
    img.alpha_composite(logs.convert("RGBA"), (0, 0))
    dd = ImageDraw.Draw(img)
    rows = 7
    for i in range(rows + 1):
        y = wall_h * i / rows
        dd.line([(0, y), (w, y)], fill=(104, 74, 46, 180), width=4)
        dd.line([(0, y + 4), (w, y + 4)], fill=(206, 166, 118, 90), width=3)
    # окно: единственный источник света, иначе комната читается как стена
    wx, wy, ww, wh = int(w * 0.70), int(wall_h * 0.22), int(w * 0.17), int(wall_h * 0.44)
    dd.rectangle([wx, wy, wx + ww, wy + wh], fill=(150, 196, 214, 255), outline=INK + (255,), width=6)
    dd.line([(wx + ww / 2, wy), (wx + ww / 2, wy + wh)], fill=INK + (255,), width=5)
    dd.line([(wx, wy + wh / 2), (wx + ww, wy + wh / 2)], fill=INK + (255,), width=5)

    # пол: соломинки или крошка, тем же приёмом, что трава во дворе
    for _ in range(9000):
        x = rnd.randrange(0, w); y = rnd.randint(wall_h, h - 1)
        ln = rnd.randint(5, 16)
        c = shade(f_hi if rnd.random() < 0.5 else f_lo, rnd.uniform(0.86, 1.14))
        dd.line([(x, y), (x + rnd.randint(-ln, ln), y - rnd.randint(0, 3))], fill=c + (150,), width=1)

    dd.line([(0, wall_h), (w, wall_h)], fill=(88, 62, 40, 220), width=6)

    # виньетка, чтобы края не спорили с живностью
    vig = Image.new("L", (w, h), 0)
    ImageDraw.Draw(vig).ellipse([-w * 0.2, -h * 0.35, w * 1.2, h * 1.5], fill=255)
    vig = vig.filter(ImageFilter.GaussianBlur(w * 0.08))
    dark = Image.new("RGBA", (w, h), (40, 26, 14, 255))
    dark.putalpha(ImageChops.invert(vig).point(lambda v: int(v * 0.42)))
    img.alpha_composite(dark)
    return img.convert("RGB")


def supplied(key):
    """Постройку уже заменили присланной картинкой — рисовать её не надо.

    Без этой проверки скрипт затирает присланные постройки своими: фон и
    хлева он собирает одним прогоном, и правка фона уносит с собой двор.
    """
    d = os.path.join(ROOT, "assets-src", "art", "houses")
    return any(os.path.exists(os.path.join(d, key + ext))
               for ext in (".png", ".jpg", ".jpeg", ".webp"))


# ----------------------------------------------------------------- сборка
if __name__ == "__main__":
    W_BIG, W_MID = 420, 300
    HOUSES_OWN = [("korovy", "Barn1", "cherepica", "brevna",  1, W_BIG),
                  ("koni",   "Barn1", "dranka",    "temdoski", 2, W_BIG),
                  ("svini",  "Barn2", "cherepica", "mazanka",  3, W_BIG),
                  ("kury",   "Shed",  "soloma",    "mazanka",  4, W_MID),
                  ("gusi",   "Shed",  "soloma",    "doski",    5, W_MID)]
    drawn = []
    for key, shape, roof, wall, seed, w in HOUSES_OWN:
        if supplied(key):
            continue
        save(fit(village(shape, roof, wall, seed), w), "house-" + key)
        drawn.append(key)
    print("построек отрисовано: " + (", ".join(drawn) if drawn else "ни одной, все присланные"))

    made = []
    for key in ("kury", "gusi", "svini", "korovy", "koni"):
        # Присланный интерьер не трогаем — та же защита, что у построек.
        if any(os.path.exists(os.path.join(ROOT, "assets-src", "art", "rooms", key + e))
               for e in (".jpg", ".jpeg", ".png", ".webp")):
            continue
        room(key).save(os.path.join(OUT, "room-" + key + ".jpg"), quality=86, optimize=True)
        made.append(key)
    print("интерьеров отрисовано: " + (", ".join(made) if made else "ни одного, все присланные"))

    save(fit(wattle(), 220), "prop-pleten")
    save(fit(well(), 150), "prop-kolodec")
    save(fit(rooster_vane(), 130), "prop-fluger")
    save(fit(planks(), 190), "res-doska")
    save(fit(nails(), 180), "res-gvozdi")
    save(fit(load("Bale1"), 180), "res-soloma")
    print("плетень нарисован")

    bg = build_background()
    bg.save(os.path.join(OUT, "bg-yard.jpg"), quality=82, optimize=True)
    print("фон:", bg.size)
