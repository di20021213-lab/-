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
    python3 tools/import-art.py картинка.png bone --item        # иконка предмета
    python3 tools/import-art.py картинка.png farmer --prop      # портрет, реквизит
    python3 tools/import-art.py картинка.png kury --house --w 300   # постройка
"""
from PIL import Image, ImageChops, ImageDraw, ImageFilter
from collections import deque
import os, sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
FLIP_LIST = os.path.join(ROOT, "assets-src", "art", "flip.txt")
RECOLOR_LIST = os.path.join(ROOT, "assets-src", "art", "recolor.txt")
OUT = os.path.join(ROOT, "public", "img", "iso")
WIDTH = 200                       # столько же, сколько у остальных пород
HEIGHT = 330                      # и не выше самой рослой: во дворе размер задаётся
                                  # шириной, и долговязая птица переросла бы постройку
ITEM = 150                        # иконки кормов и ресурсов: вписываем в квадрат
HOUSE = 420                       # постройки: по ширине, как самые крупные из нынешних
INK = (48, 48, 56)                # контур как у набора: им обведены кусты, забор, реквизит


def needs_flip(key):
    """Породы, у которых исходник смотрит влево, перечислены в flip.txt.

    Список лежит рядом с картинками, а не держится в голове: при разовом
    переимпорте всех пород его легко переврать по памяти, и часть двора
    разворачивается спиной к остальным.
    """
    try:
        with open(FLIP_LIST, encoding="utf-8") as f:
            names = [l.strip() for l in f if l.strip() and not l.startswith("#")]
    except OSError:
        return False
    return key in names


def wanted_palette(key):
    """Масть из recolor.txt, если для этой породы она задана."""
    try:
        with open(RECOLOR_LIST, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                name, _, pal = line.partition(" ")
                if name == key:
                    return pal.strip()
    except OSError:
        pass
    return None


def is_backdrop(px, bright=168, spread=14):
    """Нейтральный и светлый — значит фон или тень, а не животное."""
    r, g, b = px[:3]
    return max(r, g, b) >= bright and max(r, g, b) - min(r, g, b) <= spread


def cut_background(im):
    """Заливка от краёв: всё связное с рамкой и похожее на фон становится дырой.

    Фон бывает не белым, а кремовым — (252,243,234). По признаку «нейтральное»
    он не проходит, поэтому дополнительно берём цвет угла как образец и считаем
    фоном всё, что от него почти не отличается.

    Допуск не постоянный, а по шуму самого фона: замеряем разброс в рамке
    кадра и берём его с небольшим запасом. Глухой допуск не годится — у
    итальянского гуся перо (253,248,242) отстоит от кремового фона
    (254,244,235) всего на семь единиц, и допуск в десять съедал птицу
    целиком, оставляя один контур. Краем силуэта тут тоже не спастись:
    перепад тоньше шума JPEG, его не видит ни один детектор.
    """
    im = im.convert("RGBA")
    w, h = im.size
    px = im.load()
    corners = [px[1, 1], px[w - 2, 1], px[1, h - 2], px[w - 2, h - 2]]
    ref = tuple(sorted(c[i] for c in corners)[1] for i in range(3))

    devs = []
    for y in list(range(0, 8)) + list(range(h - 8, h)):
        for x in range(0, w, 3):
            devs.append(max(abs(px[x, y][i] - ref[i]) for i in range(3)))
    for x in list(range(0, 8)) + list(range(w - 8, w)):
        for y in range(0, h, 3):
            devs.append(max(abs(px[x, y][i] - ref[i]) for i in range(3)))
    devs.sort()
    tol = max(4, min(10, devs[int(len(devs) * 0.98)] + 3))

    def near_ref(p):
        return all(abs(p[i] - ref[i]) <= tol for i in range(3))
    alpha = Image.new("L", (w, h), 255)
    ap = alpha.load()

    seen = bytearray(w * h)
    q = deque()

    def push(x, y):
        i = y * w + x
        if seen[i]:
            return
        seen[i] = 1
        p = px[x, y]
        if p[3] == 0 or is_backdrop(p) or near_ref(p):
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
    # Доля высоты задаёт лишь потолок полосы, а начинается она от верхней
    # тёмной строки внутри этой доли — от копыт или лап. Тень стелется вокруг
    # них и выше не поднимается, а нога бывает того же кремового цвета, что и
    # тень: у чёрно-пёстрой коровы полоса в 12% высоты выгрызала из бабок
    # куски. Ищем именно верхнюю тёмную строку, а не сплошную их цепочку:
    # цепочку обрывает сглаживание, и полоса схлопывается в четыре пикселя.
    y0 = max(0, feet - int(h * band))
    for y in range(y0, feet + 1):
        if any(px[x, y][3] > 40 and min(px[x, y][:3]) < 120 for x in range(w)):
            y0 = y
            break
    for y in range(y0, h):
        for x in range(w):
            p = px[x, y]
            if pale(p) or (p[3] and is_backdrop(p[:3], bright=150, spread=18)):
                px[x, y] = (p[0], p[1], p[2], 0)
    return im


def drop_base(im):
    """Срезает у постройки подставку — кусок газона, на котором она стоит.

    Генератор почти всегда рисует постройку на плите с травой, а во дворе
    своя земля, и такая плита торчит. Заливаем землю от нижней кромки:
    траву по цвету, песчаную дорожку тоже.

    Дальше оставляем только самый большой связный кусок. Без этого на
    картинке зависает всё, что стояло на газоне, а не на постройке: у
    свинарника это плетень, который без земли рассыпается на столбики,
    плюс светлый кант самой плиты.
    """
    im = im.convert("RGBA")
    px = im.load()
    w, h = im.size
    box = im.getbbox()
    if not box:
        return im
    hsv = im.convert("RGB").convert("HSV")
    hp, sp, vp = [c.load() for c in hsv.split()]

    # Зелень — признак однозначный: ни дерева, ни соломы такого тона нет.
    # Песчаную дорожку берём тесным допуском: расширишь — заливка пойдёт по
    # соломе на крыше и по светлым венцам, это уже проверено.
    def ground(x, y):
        H, S, V = hp[x, y], sp[x, y], vp[x, y]
        if 40 <= H <= 120 and S > 35:
            return True                                  # трава
        return 15 <= H <= 35 and S < 90 and V > 190      # песчаная дорожка

    # Пускаем заливку отовсюду, где земля касается вырезанного фона. Сначала
    # стартовали только от нижней кромки — и дорожка перед второй дверью
    # уцелела: она выше кромки, заливка до неё не дошла.
    seen = bytearray(w * h)
    q = deque()
    for y in range(h):
        for x in range(w):
            if px[x, y][3] > 40 or seen[y * w + x]:
                continue
            for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if 0 <= nx < w and 0 <= ny < h and px[nx, ny][3] > 40 \
                   and ground(nx, ny) and not seen[ny * w + nx]:
                    seen[ny * w + nx] = 1
                    q.append((nx, ny))
    while q:
        x, y = q.popleft()
        px[x, y] = (px[x, y][0], px[x, y][1], px[x, y][2], 0)
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= nx < w and 0 <= ny < h and not seen[ny * w + nx]:
                seen[ny * w + nx] = 1
                if px[nx, ny][3] > 40 and ground(nx, ny):
                    q.append((nx, ny))

    # самый большой связный кусок — сама постройка, остальное обрезки
    seen = bytearray(w * h)
    best, best_n = None, 0
    for sy in range(h):
        for sx in range(w):
            if seen[sy * w + sx] or px[sx, sy][3] <= 40:
                continue
            comp, qq = [], deque([(sx, sy)])
            seen[sy * w + sx] = 1
            while qq:
                x, y = qq.popleft()
                comp.append((x, y))
                for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                    if 0 <= nx < w and 0 <= ny < h and not seen[ny * w + nx] and px[nx, ny][3] > 40:
                        seen[ny * w + nx] = 1
                        qq.append((nx, ny))
            if len(comp) > best_n:
                best, best_n = comp, len(comp)
    if best:
        keep = set(best)
        for y in range(h):
            for x in range(w):
                if px[x, y][3] and (x, y) not in keep:
                    px[x, y] = (px[x, y][0], px[x, y][1], px[x, y][2], 0)
    return im


def ink_outline(im, width=3):
    """Обводит силуэт тёмным контуром — тем же, каким обведён весь набор.

    Без неё присланная постройка читается наклейкой: у кустов, забора и
    реквизита контур плотный и холодный, а у неё свой, тонкий и тёплый.
    Контур наращиваем наружу расширением маски, чтобы не съесть рисунок.
    """
    a = im.split()[3]
    grown = a.filter(ImageFilter.MaxFilter(width * 2 + 1))
    ring = ImageChops.subtract(grown, a)
    out = Image.new("RGBA", im.size, (0, 0, 0, 0))
    out.paste(Image.new("RGBA", im.size, INK + (255,)), (0, 0), ring)
    out.alpha_composite(im)
    return out


def house_shadow(im):
    """Тень под постройкой — по её размеру, а не по животному.

    Общая тень рассчитана на спрайт в 200 пикселей: под постройкой в 420
    она превращается в невидимое пятнышко, и та стоит на земле наклейкой.
    Здесь тень идёт по всей подошве и уходит вправо-вниз, за светом сцены.
    """
    box = im.getbbox()
    if not box:
        return im
    x0, y0, x1, y1 = box
    w = x1 - x0
    pad = Image.new("RGBA", (im.width, im.height + int(w * 0.10)), (0, 0, 0, 0))
    sh = Image.new("RGBA", pad.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(sh)
    cx = (x0 + x1) / 2 + w * 0.04
    half, thick = w * 0.46, w * 0.055
    d.ellipse([cx - half, y1 - thick, cx + half, y1 + thick * 1.6], fill=(38, 32, 22, 110))
    sh = sh.filter(ImageFilter.GaussianBlur(max(4, w * 0.035)))
    sh.alpha_composite(im)
    return sh


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


def prepare(path, keep_shadow=False, flip=False, item=False, palette=None, prop=False,
            house=False, width=HOUSE):
    im = Image.open(path)
    if palette:
        import recolor
        im = recolor.recolor(im, recolor.PALETTES[palette])
    im = cut_background(im)
    if flip:
        im = im.transpose(Image.FLIP_LEFT_RIGHT)   # во дворе все смотрят вправо
    if not keep_shadow:
        im = drop_ground(im)
    box = im.getbbox()
    if not box:
        raise SystemExit("после обрезки ничего не осталось — проверь картинку")
    im = im.crop(box)
    if house:
        im = drop_base(im)
        im = im.crop(im.getbbox())
        # Постройке важна ширина: во дворе она задаёт масштаб, а высота идёт
        # за пропорцией. Курятник и гусятник мельче хлевов — их ширину
        # задаём отдельно, иначе двор выровняется и потеряет иерархию.
        k = width / im.width
        im = im.resize((max(1, round(im.width * k)), max(1, round(im.height * k))), Image.LANCZOS)
        return house_shadow(ink_outline(im))
    if item:
        # Иконку предмета не надо равнять по ширине с остальными: она лежит в
        # плитке магазина, а не стоит во дворе рядом с постройкой. Просто
        # вписываем в квадрат, как лежат иконки из набора.
        k = min(ITEM / im.width, ITEM / im.height)
        im = im.resize((max(1, round(im.width * k)), max(1, round(im.height * k))), Image.LANCZOS)
        # Реквизит вроде портрета ни на чём не стоит: тень под парящей
        # головой выглядит пятном, поэтому её ставим только предметам.
        return im if prop else shadow(im)
    k = min(WIDTH / im.width, HEIGHT / im.height)
    im = im.resize((max(1, round(im.width * k)), max(1, round(im.height * k))), Image.LANCZOS)
    # Во дворе размер задаётся шириной, а высота идёт за пропорцией картинки.
    # Поэтому холст у всех один: долговязая птица получает воздух по бокам и
    # встаёт вровень с остальными, а не перерастает постройку.
    canvas = Image.new("RGBA", (WIDTH, im.height), (0, 0, 0, 0))
    canvas.alpha_composite(im, ((WIDTH - im.width) // 2, 0))
    return shadow(canvas)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) < 2:
        raise SystemExit(__doc__)
    src, key = args[0], args[1]
    prop = "--prop" in sys.argv
    house = "--house" in sys.argv
    width = int(sys.argv[sys.argv.index("--w") + 1]) if "--w" in sys.argv else HOUSE
    item = "--item" in sys.argv or prop
    flip = "--flip" in sys.argv or needs_flip(key)
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    im = prepare(src, keep_shadow="--keep-shadow" in sys.argv, flip=flip, item=item,
                 palette=wanted_palette(key), prop=prop, house=house, width=width)
    os.makedirs(OUT, exist_ok=True)
    dst = os.path.join(OUT, ("house-" if house else "prop-" if prop else
                            "feed-" if item else "breed-") + key + ".png")
    im.save(dst, optimize=True)
    print("готово:", dst, im.size)
