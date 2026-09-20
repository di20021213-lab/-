# -*- coding: utf-8 -*-
"""Делает иконки сортов корма из одного пакета.

В оригинале сорт — бумажный пакет с картинкой животного, и сорта разведены
цветом; у нас это заложено эмодзи 🟥 🟩 🟦 🟪 в content.js. Четыре отдельные
генерации дали бы четыре разные формы пакета, и цветовой код развалился бы,
поэтому нарисован один красный, а остальные три получаются сменой тона.

Перекрашивается только сам мешок: окно по тону оставляет картинку на
этикетке в покое, иначе вышла бы синяя корова на синей траве.

Набор корма — та же пачка в трёх экземплярах: складываем без теней и ставим
общую тень уже на стопку, иначе под каждым пакетом остаётся своя клякса.

Запуск из корня проекта:
    python3 tools/make-feed-grades.py
"""
from PIL import Image
import importlib.util
import os

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
SRC = os.path.join(ROOT, "assets-src", "art", "items", "low.jpg")
OUT = os.path.join(ROOT, "public", "img", "iso")
GRADES = {"mid": "green", "high": "blue", "elite": "purple"}
BAG_HUE = 0                       # тон самого мешка: красный, замкнут через 255


def load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, "tools", name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    ia, rc = load("import-art"), load("recolor")
    tmp = os.path.join(ROOT, "var", "feed-grades")
    os.makedirs(tmp, exist_ok=True)
    os.makedirs(OUT, exist_ok=True)

    ia.prepare(SRC, item=True).save(os.path.join(OUT, "feed-low.png"), optimize=True)
    for key, hue in GRADES.items():
        p = os.path.join(tmp, key + ".png")
        rc.rehue(Image.open(SRC), rc.HUES[hue], BAG_HUE).save(p)
        ia.prepare(p, item=True).save(os.path.join(OUT, "feed-" + key + ".png"), optimize=True)

    # Стопка: берём пачку без тени, иначе тени сложатся кляксами.
    bag = ia.drop_ground(ia.cut_background(Image.open(SRC)))
    bag = bag.crop(bag.getbbox())
    k = 150 / max(bag.size)
    bag = bag.resize((round(bag.width * k), round(bag.height * k)), Image.LANCZOS)
    w, h = bag.size
    stack = Image.new("RGBA", (int(w * 1.8), int(h * 1.22)), (0, 0, 0, 0))
    for x, y, s in ((0, h * 0.18, 0.78), (w * 0.80, h * 0.14, 0.82), (w * 0.38, h * 0.28, 0.92)):
        im = bag.resize((max(1, round(w * s)), max(1, round(h * s))), Image.LANCZOS)
        stack.alpha_composite(im, (int(x), int(y)))
    ia.shadow(stack.crop(stack.getbbox())).save(os.path.join(OUT, "feed-lowset.png"), optimize=True)
    print("сорта корма готовы:", ", ".join(["low"] + list(GRADES) + ["lowset"]))


if __name__ == "__main__":
    main()
