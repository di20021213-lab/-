"""Рисует значок программы (app.ico): лист с текстом и плашкой «OCR»."""

import sys

from PIL import Image, ImageDraw, ImageFont


def font(size):
    for name in ("segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf"):
        for base in ("C:/Windows/Fonts/", "/usr/share/fonts/truetype/dejavu/",
                     "/usr/share/fonts/truetype/liberation/", ""):
            try:
                return ImageFont.truetype(base + name, size)
            except OSError:
                continue
    return ImageFont.load_default()


def draw(size=256):
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    s = size / 256
    fold = 60 * s
    page = [(40 * s, 16 * s), (216 * s - fold, 16 * s), (216 * s, 16 * s + fold),
            (216 * s, 240 * s), (40 * s, 240 * s)]
    d.polygon(page, fill=(255, 255, 255, 255), outline=(60, 80, 110, 255))
    d.polygon([(216 * s - fold, 16 * s), (216 * s - fold, 16 * s + fold), (216 * s, 16 * s + fold)],
              fill=(200, 210, 225, 255), outline=(60, 80, 110, 255))
    d.rounded_rectangle((28 * s, 136 * s, 228 * s, 222 * s), radius=16 * s, fill=(0, 128, 118, 255))
    f = font(int(64 * s))
    w = d.textlength("OCR", font=f)
    d.text(((256 * s - w) / 2, 140 * s), "OCR", font=f, fill=(255, 255, 255, 255))
    for i in range(3):
        y = (44 + i * 22) * s
        d.line((62 * s, y, 150 * s, y), fill=(150, 160, 175, 255), width=max(1, int(8 * s)))
    return im


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "app.ico"
    draw().save(out, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
