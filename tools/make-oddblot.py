# -*- coding: utf-8 -*-
"""Готовит изометрические спрайты двора из набора ODDBLOT «The Great Farm».

Набор рисованный, исходники крупные (сарай 1080×1150), поэтому здесь всё
обрезается по содержимому, ужимается до разумного размера и раскладывается
в public/img/iso. Часть построек перекрашена — в наборе нет отдельных
гусятника, свинарника и конюшни, а лицензия правки разрешает.

Нужен распакованный архив. Запуск из корня проекта:
    python3 tools/make-oddblot.py путь/к/Gr8FarmPack
"""
from PIL import Image, ImageDraw
import colorsys, os, random, re, sys

SRC = sys.argv[1] if len(sys.argv) > 1 else "Gr8FarmPack"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "public", "img", "iso")
os.makedirs(OUT, exist_ok=True)

def load(name):
    return Image.open(os.path.join(SRC, name + ".png")).convert("RGBA")

def plant(crop, stage):
    """Имена файлов в наборе живут своей жизнью: папка «Bell pepper» хранит
    BPepper3.png, «Brocollli» — Broccoli3.png, «Eggplant» — Egg3.png. Поэтому
    ищем не по имени папки, а по номеру стадии в конце имени файла."""
    folder = os.path.join(SRC, "Plants", crop)
    files = sorted(f for f in os.listdir(folder) if f.lower().endswith(".png"))
    if stage:
        hit = [f for f in files if re.sub(r"\.png$", "", f, flags=re.I).endswith(str(stage))]
    else:
        hit = [f for f in files if not re.sub(r"\.png$", "", f, flags=re.I)[-1].isdigit()]
    if not hit:
        raise FileNotFoundError("не нашёл стадию %s у культуры %s" % (stage, crop))
    return Image.open(os.path.join(folder, hit[0])).convert("RGBA")

def trim(im):
    box = im.getbbox()
    return im.crop(box) if box else im

def fit(im, w):
    """Ужать до ширины w, сохранив пропорции. Больше исходника не растягиваем."""
    im = trim(im)
    if im.width <= w:
        return im
    return im.resize((w, max(1, round(im.height * w / im.width))), Image.LANCZOS)

def hue_shift(im, deg, sat=1.0, light=1.0, only_reds=True):
    """Сдвиг тона. По умолчанию трогает только красноватые пиксели — стены и крыши,
    оставляя контур, тени и траву как были."""
    im = im.copy()
    px = im.load()
    d = deg / 360.0
    for y in range(im.height):
        for x in range(im.width):
            r, g, b, a = px[x, y]
            if a == 0:
                continue
            h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
            if only_reds and not (s > 0.18 and (h < 0.07 or h > 0.93)):
                continue
            if not only_reds and not (s > 0.10 and 0.05 < h < 0.48):
                continue   # листва и мякоть; контур и тени не трогаем
            h = (h + d) % 1.0
            l = min(1.0, l * light)
            s = min(1.0, s * sat)
            nr, ng, nb = colorsys.hls_to_rgb(h, l, s)
            px[x, y] = (round(nr * 255), round(ng * 255), round(nb * 255), a)
    return im

def save(im, name):
    im.save(os.path.join(OUT, name + ".png"), optimize=True)
    return name

# ---------------------------------------------------------------- постройки
W_BIG, W_MID = 420, 300
barn1, barn2, shed = load("Barn1"), load("Barn2"), load("Shed")

save(fit(barn1, W_BIG), "house-korovy")                       # большой сарай
save(fit(hue_shift(barn1, 32, sat=.45, light=.78), W_BIG), "house-koni")  # он же, но потемневший от времени
save(fit(barn2, W_BIG), "house-svini")
save(fit(shed, W_MID), "house-kury")
save(fit(hue_shift(shed, 190, sat=.6, light=1.05), W_MID), "house-gusi")
save(fit(load("Greenhouse1"), W_BIG), "house-teplica")

# огород — грядка с ботвой, сад — два дерева
plot = trim(load("Dirt4"))
row = Image.new("RGBA", plot.size, (0, 0, 0, 0))
row.alpha_composite(plot)
for i, (cx, cy) in enumerate([(.25, .45), (.5, .55), (.75, .45)]):
    s = trim(plant("Cabbage", 4))
    s = s.resize((plot.width // 4, round(s.height * (plot.width // 4) / s.width)), Image.LANCZOS)
    row.alpha_composite(s, (int(plot.width * cx) - s.width // 2, int(plot.height * cy) - s.height))
save(fit(row, W_BIG), "house-ogorod")

sad = Image.new("RGBA", (900, 700), (0, 0, 0, 0))
for i, (nm, x) in enumerate([("Smtree1", 40), ("Smtree2", 330), ("Smtree1", 620)]):
    t = trim(load(nm))
    t = t.resize((260, round(t.height * 260 / t.width)), Image.LANCZOS)
    sad.alpha_composite(t, (x, 700 - t.height))
save(fit(sad, W_BIG), "house-sad")

# ---------------------------------------------------------------- спелые овощи
# В наборе есть лист со зрелыми плодами — он куда понятнее в магазине,
# чем тёмный куст ботвы. Координаты найдены разбором листа на связные области.
VEGGIE_SHEET = os.path.join(SRC, "Plants", "SimpleSpriteSheet_Veggies.png")
VEGGIE = {
    "perec":   (39, 10, 217, 246),     "brokkoli": (788, 17, 1020, 239),
    "kapusta": (1557, 13, 1783, 243),  "morkov":   (319, 269, 537, 499),
    "selderey":(1081, 270, 1287, 498), "kukuruza": (15, 522, 241, 758),
    "baklazh": (1358, 524, 1510, 756), "ogurcy":   (1578, 530, 1802, 750),
    "salat":   (396, 786, 620, 1006),  "luk":      (1157, 775, 1371, 1009),
    "chili":   (449, 1034, 667, 1270), "kartoha":  (697, 1074, 931, 1230),
    "redis":   (1490, 1063, 1650, 1241),"shpinat": (239, 1305, 417, 1511),
    "pomidor": (975, 1296, 1193, 1520),"podsol":   (1762, 1291, 1978, 1525),
}
def veggie(key):
    return Image.open(VEGGIE_SHEET).convert("RGBA").crop(VEGGIE[key])

for key, box in VEGGIE.items():
    save(fit(veggie(key), 200), "breed-" + key)
# трюфель — та же картофелина, только тёмная: отдельного гриба в наборе нет
save(fit(hue_shift(veggie("kartoha"), -18, sat=.55, light=.45, only_reds=False), 200), "breed-trufel")

# ---------------------------------------------------------------- культуры
CROPS = {
    "kartoha": "Potato",   "kukuruza": "Corn",       "podsol": "Wheat",
    "ogurcy": "Green bean","morkov": "Carrot",
    "kapusta": "Cabbage",  "redis": "Radish",        "luk": "Onion",
    "shpinat": "Spinach",  "salat": "Lettuce",       "pomidor": "Tomato",
    "perec": "Bell pepper","baklazh": "Eggplant",    "brokkoli": "Brocollli",
    "selderey": "Celery",  "yablon": None,           "grusha": None,
}
for key, crop in CROPS.items():
    if crop and key not in VEGGIE:
        save(fit(plant(crop, 5), 180), "breed-" + key)
tree1 = trim(load("Smtree1")); tree2 = trim(load("Smtree2"))

def fruit_tree(base, color, n=10, seed=1, leaf=None, rad_k=13):
    """В наборе всего два дерева, и оба без плодов — яблоня от груши не отличалась.
    Развешиваем по кроне плоды нужного цвета, крону при желании подкрашиваем."""
    im = trim(base).copy()
    if leaf:
        im = hue_shift(im, leaf[0], sat=leaf[1], light=leaf[2], only_reds=False)
    w, h = im.size
    px = im.load()
    crown = []
    for x in range(2, w - 2):
        for y in range(2, int(h * 0.66)):
            r, g, b, a = px[x, y]
            if a > 220 and g > r + 10 and g > b + 10:
                crown.append((x, y))
    if not crown:
        return im
    rnd = random.Random(seed)
    spots = []
    rad = max(3, w // rad_k)
    for _ in range(400):
        if len(spots) >= n:
            break
        x, y = rnd.choice(crown)
        if all((x - sx) ** 2 + (y - sy) ** 2 > (rad * 2.4) ** 2 for sx, sy in spots):
            spots.append((x, y))
    d = ImageDraw.Draw(im)
    dark = (60, 40, 45, 255)
    for x, y in spots:
        d.ellipse([x - rad, y - rad, x + rad, y + rad], fill=color + (255,), outline=dark, width=max(1, rad // 3))
        d.ellipse([x - rad // 2, y - rad // 2, x - rad // 6, y - rad // 6],
                  fill=(255, 255, 255, 90))     # блик, чтобы плод не был плоским пятном
    return im

save(fit(fruit_tree(tree1, (196, 60, 52), n=11, seed=3), 200), "breed-yablon")
save(fit(fruit_tree(tree2, (222, 196, 84), n=9, seed=5, leaf=(8, .8, 1.12), rad_k=11), 200), "breed-grusha")
save(fit(fruit_tree(tree1, (168, 24, 44), n=18, seed=7, leaf=(-8, 1.15, .72), rad_k=20), 200), "breed-vishnya")
save(fit(fruit_tree(tree2, (104, 72, 150), n=12, seed=11, leaf=(15, .9, .95)), 200), "breed-sliva")
save(fit(fruit_tree(tree1, (232, 140, 38), n=16, seed=13, leaf=(-35, .7, 1.05)), 200), "breed-oblepiha")

# ---------------------------------------------------------------- корма
# Цветные квадратики-эмодзи выглядели дёшево, поэтому кормам — мешки, ящики и вёдра.
FEED_ART = {
    "low": "Bale2", "mid": "Smcrate1", "high": "Smcrate2", "elite": "Smcrate3",
    "instant": "Bucket", "lowset": "Bale1", "krapiva": "Smbush1", "otrubi": "Bucket",
    "zhmyh": "Smcrate1", "univer": "Table", "navoz": "Dirt2", "torf": "Dirt5",
}
for key, nm in FEED_ART.items():
    im = load(nm)
    if key == "zhmyh":  im = hue_shift(im, 20, sat=.6, light=.75, only_reds=False)
    if key == "otrubi": im = hue_shift(im, 40, sat=.5, light=.9,  only_reds=False)
    if key == "high":   im = hue_shift(im, 150, sat=.5, light=1.0, only_reds=False)
    if key == "elite":  im = hue_shift(im, 250, sat=.6, light=.95, only_reds=False)
    save(fit(im, 170), "feed-" + key)

# ---------------------------------------------------------------- двор и декор
DECOR = {
    "pleten": "Barb3", "skirda": "Bale1", "telega": "Smcrate2", "kolodec": "Pump",
    "fluger": "Windmill", "klumba": "Flwrbush", "doska": "Stall_v1", "traktor": "Silo",
}
for key, nm in DECOR.items():
    save(fit(load(nm), 200), "prop-" + key)
for nm, key in [("Scare", "scare"), ("Table", "table"), ("Smtree1", "tree"),
                ("Grass1", "grass"), ("Smbush2", "bush"), ("Dirt3", "path"),
                ("Bale2", "hay"), ("Barb4", "fence")]:
    save(fit(load(nm), 220), "prop-" + key)

files = sorted(os.listdir(OUT))
total = sum(os.path.getsize(os.path.join(OUT, f)) for f in files)
print("готово:", len(files), "файлов,", round(total / 1024), "КБ")
