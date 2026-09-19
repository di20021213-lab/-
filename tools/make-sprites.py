# -*- coding: utf-8 -*-
"""Готовит спрайты игры из CC0-наборов Kenney: копирует нужные тайлы,
перекрашивает недостающую живность и склеивает постройки из стен и крыш.

Запускать нужно только если меняете палитру или набор: готовые спрайты уже лежат
в public/img. Скрипту нужны распакованные наборы рядом с рабочим каталогом:

    kenney.nl/assets/tiny-farm                        -> tiny-farm/
    kenney.nl/assets/tiny-town                        -> tiny-town/
    kenney.nl/assets/pixel-platformer-farm-expansion  -> pp/

Все три под CC0, подробности в CREDITS.md. Нужен Pillow: pip install Pillow
Запуск:  python3 tools/make-sprites.py  (из корня проекта)
"""
from PIL import Image
import os

OUT = os.environ.get('SPRITE_OUT', os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'public', 'img'))
SRC = os.environ.get('SPRITE_SRC', '.')
FARM = os.path.join(SRC, 'tiny-farm', 'Tiles')
TOWN = os.path.join(SRC, 'tiny-town', 'Tiles')
PP   = os.path.join(SRC, 'pp', 'Tiles')
os.makedirs(OUT, exist_ok=True)

def tile(src, n):
    return Image.open(os.path.join(src, 'tile_%04d.png' % n)).convert('RGBA')

def recolor(img, mapping):
    img = img.copy()
    px = img.load()
    for y in range(img.height):
        for x in range(img.width):
            c = px[x, y]
            if c[3] == 0:
                continue
            key = c[:3]
            if key in mapping:
                px[x, y] = mapping[key] + (c[3],)
    return img

def save(img, name, scale=6):
    img = img.resize((img.width * scale, img.height * scale), Image.NEAREST)
    img.save(os.path.join(OUT, name + '.png'))
    return name

# ----- палитры -----
WHITE, OUT_LINE = (255, 255, 255), (63, 38, 49)
GREY1, GREY2, GREY3 = (192, 203, 220), (139, 155, 180), (90, 105, 136)
COMB = (195, 75, 53)
BEAK = (227, 134, 40)

PINK  = {WHITE:(244,164,186), GREY1:(226,130,158), GREY2:(198,102,132), GREY3:(170,80,110)}
BROWN = {WHITE:(178,120,72),  GREY1:(140,92,54),   GREY2:(112,72,42),   GREY3:(92,58,34)}
GOOSE = {COMB:BEAK, GREY1:(226,232,240)}
GREYG = {WHITE:(206,212,222), COMB:BEAK, GREY1:(166,176,192)}
RUSTY = {WHITE:(196,124,74),  GREY1:(160,96,56)}
CHICK = {WHITE:(247,206,86),  GREY1:(226,176,58), COMB:BEAK}
SIMM  = {GREY1:(214,140,96),  GREY2:(186,112,70), GREY3:(150,86,50)}
SPOT  = {GREY1:(120,84,74),   GREY2:(96,64,58)}

# ----- живность: породы -----
chicken, cow, sheep = tile(FARM,122), tile(FARM,121), tile(FARM,120)
breeds = {
  'rusbel':   chicken,
  'leggorn':  recolor(chicken, {GREY1:(250,250,250)}),
  'kuchin':   recolor(chicken, RUSTY),
  'tula':     recolor(chicken, GOOSE),
  'holmgus':  recolor(chicken, GREYG),
  'vietnam':  recolor(sheep, PINK),
  'mirgorod': recolor(recolor(sheep, PINK), SPOT),
  'landras':  recolor(sheep, {WHITE:(250,206,214), GREY1:(232,168,184), GREY2:(206,136,156), GREY3:(178,108,130)}),
  'krupbel':  recolor(sheep, {WHITE:(252,236,232), GREY1:(232,198,196), GREY2:(206,166,166), GREY3:(176,136,138)}),
  'holmkor':  cow,
  'simment':  recolor(cow, SIMM),
  'vladimir': recolor(cow, BROWN),
}
# ----- растения -----
plants = {
  'kartoha':  tile(FARM,55), 'kukuruza': tile(FARM,32), 'podsol': tile(FARM,83),
  'ogurcy':   tile(FARM,56), 'trufel':   tile(TOWN,29), 'yablon': tile(FARM,78),
  'grusha':   tile(TOWN,27),
}
for k, v in list(breeds.items()) + list(plants.items()):
    save(v, 'breed-' + k)

# ----- постройки: крыша + стены -----
ROOF = {'main':(195,75,53), 'lit':(242,132,98), 'top':(252,188,143)}
def roof_map(main, lit, top):
    return {ROOF['main']:main, ROOF['lit']:lit, ROOF['top']:top}
ROOFS = {
  'kury':   roof_map((201,149,47),(232,190,88),(248,225,160)),    # солома
  'gusi':   roof_map((62,110,160),(104,160,205),(170,210,240)),   # синяя
  'svini':  roof_map((195,75,53),(242,132,98),(252,188,143)),     # красная, как есть
  'korovy': roof_map((140,92,52),(186,134,84),(226,190,150)),     # коричневая
  'koni':   roof_map((110,118,132),(150,160,175),(200,208,220)),  # шифер
}
def house(roof_cols):
    im = Image.new('RGBA', (48, 32), (0,0,0,0))
    for i, n in enumerate((52,53,54)):
        im.paste(recolor(tile(TOWN,n), roof_cols), (i*16, 0))
    im.paste(tile(TOWN,72), (0,16)); im.paste(tile(TOWN,86), (16,16)); im.paste(tile(TOWN,72), (32,16))
    return im
for k, cols in ROOFS.items():
    save(house(cols), 'house-' + k, scale=4)

# огород: грядки с всходами
plot = Image.new('RGBA',(48,32),(0,0,0,0))
for i,n in enumerate((49,50,49)): plot.paste(tile(FARM,n),(i*16,0))
for i,n in enumerate((61,62,61)): plot.paste(tile(FARM,n),(i*16,16))
save(plot,'house-ogorod',scale=4)

# теплица: рамы из фермерского расширения
gh = Image.new('RGBA',(54,36),(0,0,0,0))
for i,n in enumerate((68,69,71)): gh.paste(tile(PP,n),(i*18,0))
for i,n in enumerate((84,85,87)): gh.paste(tile(PP,n),(i*18,18))
save(gh.resize((48,32),Image.NEAREST),'house-teplica',scale=4)

# сад: деревья на траве
sad = Image.new('RGBA',(48,32),(0,0,0,0))
for i,n in enumerate((27,4,27)):
    t=tile(TOWN,n); sad.paste(t,(i*16,6),t)
save(sad,'house-sad',scale=4)

# ----- мелочи двора и продукция -----
props = {'egg':(FARM,125),'milk':(FARM,123),'hay':(FARM,96),'well':(FARM,73),
         'sign':(TOWN,83),'farmer':(FARM,109),'tree':(TOWN,4),'fence':(FARM,98),
         'crate':(FARM,90),'barrel':(FARM,85),'vily':(TOWN,116),'stone':(FARM,89)}
for name,(src,n) in props.items():
    save(tile(src,n), 'prop-' + name)

files = sorted(os.listdir(OUT))
print('готово, файлов:', len(files))
