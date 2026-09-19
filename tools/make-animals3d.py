# -*- coding: utf-8 -*-
"""Рендерит низкополигональные модели животных в плоские спрайты для двора.

Зачем: рисованных животных в наборе ODDBLOT нет, пиксельные спрайты Kenney
давали четырёх одинаковых кур, а нарисованные скриптом выходили угловатыми.
Модели Quaternius (CC0) дают нормальную анатомию, а здесь они снимаются под тем
же углом, что и постройки во дворе, с плоской заливкой и тёмным контуром —
чтобы не выбиваться из стиля.

Свой растеризатор, без OpenGL: моделей мало (сотни треугольников), хватает
сортировки по глубине и заливки многоугольников.

Модели: Quaternius, «LowPoly Animated Farm Animal Pack», CC0.
https://opengameart.org/content/lowpoly-animated-farm-animal-pack
Корова, свинья и конь лежат в assets-src/quaternius-farm-animals, остальное из
набора (овца, лама, мопс, зебра) колхозу не пригодилось.

Запуск из корня проекта:
    python3 tools/make-animals3d.py assets-src/quaternius-farm-animals
"""
from PIL import Image, ImageDraw, ImageFilter, ImageChops
import math, os, random, sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
OUT = os.path.join(ROOT, "public", "img", "iso")
SRC = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "assets-src", "quaternius-farm-animals")
os.makedirs(OUT, exist_ok=True)

INK = (48, 48, 56, 255)
SIZE = 520                     # рендерим крупно, ужимаем в конце
OUTLINE = 10                   # толщина контура в пикселях рендера


# ------------------------------------------------------------------ загрузка
def load_mtl(path):
    cols, cur = {}, None
    if not os.path.exists(path):
        return cols
    for line in open(path, encoding="utf-8", errors="ignore"):
        p = line.split()
        if not p:
            continue
        if p[0] == "newmtl":
            cur = p[1]
        elif p[0] == "Kd" and cur:
            cols[cur] = tuple(round(float(x) ** (1 / 2.2) * 255) for x in p[1:4])
    return cols


def load_obj(path):
    """Возвращает вершины и грани с именем материала."""
    verts, faces, mat = [], [], None
    for line in open(path, encoding="utf-8", errors="ignore"):
        p = line.split()
        if not p:
            continue
        if p[0] == "v":
            verts.append((float(p[1]), float(p[2]), float(p[3])))
        elif p[0] == "usemtl":
            mat = p[1]
        elif p[0] == "f":
            idx = [int(x.split("/")[0]) - 1 for x in p[1:]]
            for i in range(1, len(idx) - 1):          # веер из треугольников
                faces.append(((idx[0], idx[i], idx[i + 1]), mat))
    return verts, faces


# --------------------------------------------------------- свои низкополигоны
# Птиц в наборе Quaternius нет, поэтому курица и гусь собираются из примитивов
# тем же гранением: эллипсоиды, конусы и цилиндры с небольшим числом сегментов.
class Mesh:
    def __init__(self):
        self.v, self.f = [], []

    def add(self, verts, faces, color):
        base = len(self.v)
        self.v.extend(verts)
        for tri in faces:
            self.f.append((tuple(base + i for i in tri), color))

    def ellipsoid(self, c, r, color, su=10, sv=6, squash=None):
        cx, cy, cz = c
        rx, ry, rz = r
        verts, faces = [], []
        for j in range(sv + 1):
            phi = math.pi * j / sv
            for i in range(su):
                th = 2 * math.pi * i / su
                x = cx + rx * math.sin(phi) * math.cos(th)
                y = cy + ry * math.cos(phi)
                z = cz + rz * math.sin(phi) * math.sin(th)
                if squash:
                    x, y, z = squash(x - cx, y - cy, z - cz)
                    x, y, z = x + cx, y + cy, z + cz
                verts.append((x, y, z))
        for j in range(sv):
            for i in range(su):
                a = j * su + i
                b = j * su + (i + 1) % su
                c2 = (j + 1) * su + (i + 1) % su
                d2 = (j + 1) * su + i
                faces.append((a, b, c2))
                faces.append((a, c2, d2))
        self.add(verts, faces, color)

    def cone(self, base_c, tip, r, color, seg=8):
        cx, cy, cz = base_c
        verts = [tip]
        for i in range(seg):
            th = 2 * math.pi * i / seg
            verts.append((cx + r * math.cos(th), cy, cz + r * math.sin(th)))
        faces = [(0, 1 + i, 1 + (i + 1) % seg) for i in range(seg)]
        faces += [(1, 1 + i, 1 + (i + 1) % seg) for i in range(1, seg - 1)]
        self.add(verts, faces, color)

    def tube(self, a, b, r, color, seg=8):
        ax, ay, az = a
        bx, by, bz = b
        verts = []
        for c in (a, b):
            for i in range(seg):
                th = 2 * math.pi * i / seg
                verts.append((c[0] + r * math.cos(th), c[1], c[2] + r * math.sin(th)))
        faces = []
        for i in range(seg):
            j = (i + 1) % seg
            faces.append((i, j, seg + j))
            faces.append((i, seg + j, seg + i))
        for i in range(1, seg - 1):
            faces.append((0, i, i + 1))
            faces.append((seg, seg + i, seg + i + 1))
        self.add(verts, faces, color)


def bird_mesh(body, comb_col, beak_col, leg_col, goose=False, wattle=True, knob=False):
    m = Mesh()
    if goose:
        m.ellipsoid((0, 1.0, 0), (1.55, 1.0, 1.0), body, su=12, sv=7)          # корпус
        for k in range(5):                                                      # шея дугой
            t = k / 4.0
            x = 1.0 + 0.85 * t
            y = 1.7 + 1.85 * t
            m.ellipsoid((x, y, 0), (0.42 - 0.06 * t, 0.46, 0.42 - 0.06 * t), body, su=8, sv=5)
        hx, hy = 1.95, 3.75
        m.ellipsoid((hx, hy, 0), (0.55, 0.5, 0.5), body, su=9, sv=6)            # голова
        m.cone((hx + 0.35, hy - 0.05, 0), (hx + 1.35, hy - 0.15, 0), 0.3, beak_col, seg=7)
        if knob:
            m.ellipsoid((hx + 0.2, hy + 0.42, 0), (0.24, 0.24, 0.22), comb_col, su=7, sv=5)
        tail = [(-1.5, 1.35, 0.0), (-2.5, 1.85, 0.0), (-1.45, 0.95, 0.35), (-1.45, 0.95, -0.35)]
        m.add(tail, [(0, 1, 2), (0, 3, 1), (0, 2, 3), (1, 3, 2)], body)
        legs = [(0.3, -0.42), (-0.28, 0.42)]
    else:
        m.ellipsoid((0, 1.15, 0), (1.25, 1.05, 0.95), body, su=12, sv=7)
        m.ellipsoid((0.85, 1.95, 0), (0.6, 0.62, 0.55), body, su=9, sv=5)       # грудь-шея
        hx, hy = 1.35, 2.55
        m.ellipsoid((hx, hy, 0), (0.52, 0.5, 0.48), body, su=9, sv=6)
        m.cone((hx + 0.3, hy - 0.05, 0), (hx + 0.95, hy - 0.12, 0), 0.24, beak_col, seg=7)
        for i, (dx, dy, r) in enumerate([(-0.18, 0.42, 0.2), (0.05, 0.5, 0.22), (0.28, 0.42, 0.18)]):
            m.ellipsoid((hx + dx, hy + dy, 0), (r, r * 1.2, r * 0.55), comb_col, su=6, sv=4)
        if wattle:
            m.ellipsoid((hx + 0.3, hy - 0.45, 0), (0.16, 0.24, 0.12), comb_col, su=6, sv=4)
        tail = [(-1.1, 1.65, 0.0), (-2.05, 2.55, 0.0), (-1.05, 1.15, 0.4), (-1.05, 1.15, -0.4)]
        m.add(tail, [(0, 1, 2), (0, 3, 1), (0, 2, 3), (1, 3, 2)], body)
        legs = [(0.32, -0.38), (-0.22, 0.4)]
    # крылья
    for sz in (0.78, -0.78):
        m.ellipsoid((-0.1, 1.15 if not goose else 1.05, sz), (0.85, 0.55, 0.22),
                    shade3(body, 0.88), su=9, sv=5)
    # ноги и лапы
    for (lx, lz) in legs:
        top = 0.35 if not goose else 0.3
        m.tube((lx, top, lz), (lx, -0.75, lz), 0.12, leg_col, seg=6)
        m.ellipsoid((lx + 0.2, -0.78, lz), (0.42, 0.1, 0.3), leg_col, su=7, sv=4)
    return m


def shade3(c, k):
    return tuple(max(0, min(255, round(v * k))) for v in c)


# ------------------------------------------------------------------- камера
def rotate(v, yaw, pitch):
    x, y, z = v
    cy, sy = math.cos(yaw), math.sin(yaw)
    x, z = x * cy - z * sy, x * sy + z * cy
    cp, sp = math.cos(pitch), math.sin(pitch)
    y, z = y * cp - z * sp, y * sp + z * cp
    return (x, y, z)


def quantize(col, k):
    """Плоская заливка в три тона: набор ODDBLOT так же не знает градиентов."""
    if k > 0.84:
        f = 1.30
    elif k > 0.60:
        f = 1.12
    else:
        f = 0.86
    return tuple(max(0, min(255, round(c * f))) for c in col)


def render(src, yaw=-34, pitch=26, tint=None, scale=1.0):
    """src — путь к .obj или готовый Mesh с цветом прямо в гранях."""
    if isinstance(src, Mesh):
        verts, faces, cols = src.v, src.f, None
    else:
        verts, faces = load_obj(src)
        cols = load_mtl(src[:-4] + ".mtl")
    ry, rp = math.radians(yaw), math.radians(pitch)
    pts = [rotate(v, ry, rp) for v in verts]

    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
    w, h = max(xs) - min(xs), max(ys) - min(ys)
    k = SIZE * 0.78 / max(w, h) * scale
    ox = SIZE / 2 - (min(xs) + max(xs)) / 2 * k
    ground_y = SIZE * 0.93                            # линия земли
    lo = min(ys)

    def to2d(p):
        return (ox + p[0] * k, ground_y - (p[1] - lo) * k)

    light = (-0.45, 0.78, -0.44)
    # художник рисует от дальних к ближним: сортируем по центру грани
    order = sorted(faces, key=lambda f: sum(pts[i][2] for i in f[0]) / 3.0)

    im = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    for idx, mat in order:
        a, b, c = (pts[i] for i in idx)
        nx = (b[1] - a[1]) * (c[2] - a[2]) - (b[2] - a[2]) * (c[1] - a[1])
        ny = (b[2] - a[2]) * (c[0] - a[0]) - (b[0] - a[0]) * (c[2] - a[2])
        nz = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
        ln = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
        if nz / ln <= 0:                              # задние грани не рисуем
            continue
        lam = max(0.0, min(1.0, (nx * light[0] + ny * light[1] + nz * light[2]) / ln * 0.5 + 0.55))
        base = mat if cols is None else cols.get(mat, (200, 200, 200))
        if tint and cols is not None and mat in tint:
            base = tint[mat]
        d.polygon([to2d(a), to2d(b), to2d(c)], fill=quantize(base, lam))
    return im


def outline(im, w=OUTLINE):
    """Контур по силуэту: обводим альфу, как в рисованном наборе."""
    a = im.split()[3]
    grown = a.filter(ImageFilter.MaxFilter(w if w % 2 else w + 1))
    edge = Image.new("RGBA", im.size, INK)
    edge.putalpha(grown)
    out = Image.alpha_composite(edge, im)
    return out


def shadow(im):
    box = im.getbbox()
    if not box:
        return im
    x0, y0, x1, y1 = box
    sh = Image.new("RGBA", im.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(sh)
    cx, half = (x0 + x1) / 2, (x1 - x0) * 0.38
    d.ellipse([cx - half, y1 - 26, cx + half, y1 + 10], fill=(40, 34, 20, 95))
    sh = sh.filter(ImageFilter.GaussianBlur(9))
    sh.alpha_composite(im)
    return sh


def specks(im, col, seed, n=7, size=0.075):
    """Пятна по силуэту: порода узнаётся по масти, а модель у всех одна."""
    box = im.getbbox()
    x0, y0, x1, y1 = box
    layer = Image.new("RGBA", im.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    rnd = random.Random(seed)
    for _ in range(n):
        r = rnd.uniform(0.6, 1.2) * (x1 - x0) * size
        x = rnd.uniform(x0 + r, x1 - r)
        y = rnd.uniform(y0 + (y1 - y0) * 0.15, y0 + (y1 - y0) * 0.62)
        d.ellipse([x - r, y - r * 0.8, x + r, y + r * 0.8], fill=col)
    layer.putalpha(ImageChops.multiply(layer.split()[3], im.split()[3]))
    out = im.copy()
    out.alpha_composite(layer)
    return out


def save(im, name, width=200):
    im = im.crop(im.getbbox())
    im = im.resize((width, max(1, round(im.height * width / im.width))), Image.LANCZOS)
    im.save(os.path.join(OUT, "breed-" + name + ".png"), optimize=True)


# ------------------------------------------------------------------- породы
WHITE  = (242, 240, 232)
CREAM  = (232, 214, 172)
RED    = (192, 66, 52)
GOLD   = (226, 172, 68)
ORANGE = (228, 146, 54)
BROWN  = (156, 96, 52)
GREY   = (176, 176, 170)
DARK   = (92, 84, 88)
PINK   = (228, 168, 164)
PALE   = (238, 198, 194)
CHERRY = (176, 92, 70)

def chicken(body, comb=RED, beak=GOLD, legs=GOLD, scale=1.0, spots=None):
    return dict(mesh=bird_mesh(body, comb, beak, legs), scale=scale, spots=spots)

def goose(body, knobc=ORANGE, knob=False, scale=1.0):
    return dict(mesh=bird_mesh(body, knobc, ORANGE, ORANGE, goose=True, knob=knob), scale=scale)

def model(name, tint=None, scale=1.0, spots=None, yaw=-34, flip=False):
    return dict(obj=name, tint=tint, scale=scale, spots=spots, yaw=yaw, flip=flip)

BREEDS = {
    # куры и гуси — свои низкополигоны
    "rusbel":  chicken(WHITE),
    "leggorn": chicken(WHITE, comb=(212, 74, 58), scale=1.06),
    "kuchin":  chicken(CHERRY, comb=RED, scale=1.04),
    # шесть пород добавлены, чтобы курятник не был рядом одинаково белых птиц
    "moskchern": chicken((64, 58, 66), comb=RED, legs=(96, 92, 98), scale=1.02),
    "orlov":     chicken((196, 148, 92), comb=(168, 58, 46), scale=1.06,
                         spots=((242, 238, 230), 9)),
    "pavlov":    chicken((206, 204, 198), comb=RED, scale=1.04,
                         spots=((86, 80, 86), 10)),
    "tula":    goose(GREY, scale=1.04),
    "holmgus": goose(WHITE, knob=True, scale=1.14),
    "kitay":   goose((162, 122, 82), knobc=(96, 74, 56), knob=True, scale=1.0),
    "kuban":   goose((150, 138, 118), knobc=(92, 82, 70), knob=True, scale=1.08),
    "tuluz":   goose((154, 152, 146), knobc=ORANGE, scale=1.26),
    "ital":    goose((246, 244, 238), scale=1.12),
    # свиньи, коровы и конь — модели Quaternius
    "vietnam":  model("Pig", {"Material.003": DARK, "Material": (60, 54, 58)}, 0.92, flip=True),
    "mirgorod": model("Pig", {"Material.003": PINK}, 1.0, spots=((78, 70, 74), 7), flip=True),
    "landras":  model("Pig", {"Material.003": PALE}, 1.1, flip=True),
    "krupbel":  model("Pig", {"Material.003": (244, 206, 200)}, 1.22, flip=True),
    "holmkor":  model("Cow", {"White": WHITE}, 1.0),
    "simment":  model("Cow", {"White": CREAM, "Black": (186, 104, 62)}, 1.08),
    "vladimir": model("Horse", None, 1.15),
}

def imported(key):
    """Порода уже заменена присланной картинкой — рендер её не трогает."""
    art = os.path.join(ROOT, "assets-src", "art")
    return any(os.path.exists(os.path.join(art, key + ext))
               for ext in (".png", ".jpg", ".jpeg", ".webp"))


if __name__ == "__main__":
    skipped = []
    for key, spec in BREEDS.items():
        if imported(key):
            skipped.append(key)
            continue
        if "mesh" in spec:
            im = render(spec["mesh"], yaw=-38, pitch=24, scale=spec["scale"])
        else:
            path = os.path.join(SRC, spec["obj"] + ".obj")
            if not os.path.exists(path):
                raise SystemExit("нет модели: " + path)
            im = render(path, yaw=spec.get("yaw", -34), tint=spec["tint"], scale=spec["scale"])
        if spec.get("flip"):
            im = im.transpose(Image.FLIP_LEFT_RIGHT)
        im = outline(im)
        if spec.get("spots"):
            im = specks(im, spec["spots"][0] + (255,), seed=hash(key) % 1000, n=spec["spots"][1])
        save(shadow(im), key)
    print("отрисовано пород:", len(BREEDS) - len(skipped))
    if skipped:
        print("взяты присланные картинки:", ", ".join(skipped))
