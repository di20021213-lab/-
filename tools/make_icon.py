"""Рисует значок программы (окно терминала с искрой) и сохраняет в .ico или .png.

Запуск: python tools/make_icon.py icon.ico
Нужен Pillow (pip install pillow).
"""

import sys

from PIL import Image, ImageDraw

BACKGROUND = (30, 34, 52, 255)
PROMPT = (94, 234, 212, 255)
SPARK = (250, 204, 21, 255)


def draw(size=1024):
    s = size
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([s * 0.04, s * 0.04, s * 0.96, s * 0.96], radius=s * 0.2, fill=BACKGROUND)

    w = int(s * 0.09)
    # «>»
    d.line([(s * 0.2, s * 0.36), (s * 0.4, s * 0.52), (s * 0.2, s * 0.68)],
           fill=PROMPT, width=w, joint="curve")
    for x, y in [(s * 0.2, s * 0.36), (s * 0.2, s * 0.68)]:
        d.ellipse([x - w / 2, y - w / 2, x + w / 2, y + w / 2], fill=PROMPT)
    # «_»
    d.rounded_rectangle([s * 0.46, s * 0.64, s * 0.74, s * 0.64 + w], radius=w / 2, fill=PROMPT)

    # четырёхлучевая искра
    cx, cy, big, small = s * 0.73, s * 0.3, s * 0.15, s * 0.04
    d.polygon([(cx, cy - big), (cx + small, cy - small), (cx + big, cy), (cx + small, cy + small),
               (cx, cy + big), (cx - small, cy + small), (cx - big, cy), (cx - small, cy - small)],
              fill=SPARK)
    return img.resize((256, 256), Image.LANCZOS)


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "icon.ico"
    icon = draw()
    if out.lower().endswith(".ico"):
        icon.save(out, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    else:
        icon.save(out)
    print("saved", out)
