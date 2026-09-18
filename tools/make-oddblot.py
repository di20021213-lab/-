# -*- coding: utf-8 -*-
"""Готовит изометрические спрайты двора из набора ODDBLOT «The Great Farm».

Набор рисованный, исходники крупные (сарай 1080×1150), поэтому здесь всё
обрезается по содержимому, ужимается до разумного размера и раскладывается
в public/img/iso. Часть построек перекрашена — в наборе нет отдельных
гусятника, свинарника и конюшни, а лицензия правки разрешает.

Нужен распакованный архив. Запуск из корня проекта:
    python3 tools/make-oddblot.py путь/к/Gr8FarmPack
"""
from PIL import Image
import colorsys, os, sys

SRC = sys.argv[1] if len(sys.argv) > 1 else "Gr8FarmPack"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "public", "img", "iso")
os.makedirs(OUT, exist_ok=True)

def load(name):
    return Image.open(os.path.join(SRC, name + ".png")).convert("RGBA")

def plant(crop, stage):
    """В наборе имена файлов не всегда совпадают с именем папки: «Green bean»
    лежит как «Greenbean1.png». Поэтому пробуем оба написания."""
    names = [crop if stage == 0 else "%s%d" % (crop, stage),
             crop.replace(" ", "") if stage == 0 else "%s%d" % (crop.replace(" ", ""), stage)]
    for n in names:
        f = os.path.join(SRC, "Plants", crop, n + ".png")
        if os.path.exists(f):
            return Image.open(f).convert("RGBA")
    raise FileNotFoundError("не нашёл стадию %d у культуры %s" % (stage, crop))

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

# ---------------------------------------------------------------- культуры
CROPS = {
    "kartoha": "Potato", "kukuruza": "Corn", "podsol": "Wheat",
    "ogurcy": "Green bean", "trufel": "Onion", "yablon": None, "grusha": None,
}
for key, crop in CROPS.items():
    if crop:
        save(fit(plant(crop, 5), 180), "breed-" + key)
tree1 = trim(load("Smtree1")); tree2 = trim(load("Smtree2"))
save(fit(tree1, 180), "breed-yablon")
save(fit(tree2, 180), "breed-grusha")

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
