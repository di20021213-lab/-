"""Генерирует тестовый «скан» (PDF из картинок) с известным текстом.

Страница 1 — книжная: заголовок, абзацы по ширине, таблица 3×4, подпись.
Страница 2 — альбомная, но отсканирована боком (повёрнута на 90°).

    python tests/make_scan.py out.pdf  → создаёт out.pdf и out.txt (эталонные слова)
"""

from __future__ import annotations

import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

DPI = 200

TITLE = "АКТ СВЕРКИ ВЗАИМНЫХ РАСЧЕТОВ № 7"
PARAS = [
    "Общество с ограниченной ответственностью «Северный ветер», именуемое в дальнейшем "
    "Заказчик, в лице директора Смирнова Алексея Викторовича, и индивидуальный "
    "предприниматель Кузнецова Мария Петровна, именуемая в дальнейшем Исполнитель, "
    "составили настоящий акт о том, что работы выполнены полностью и в срок.",
    "Стороны претензий по объему, качеству и срокам оказания услуг друг к другу не имеют. "
    "Настоящий акт составлен в двух экземплярах, по одному для каждой из сторон.",
]
TABLE = [
    ["Наименование работ", "Количество", "Сумма, руб."],
    ["Монтаж освещения", "12", "48 000,00"],
    ["Прокладка кабеля", "150", "27 750,00"],
    ["Пусконаладочные работы", "1", "15 000,00"],
]
SIGN = "Директор"
SIGN_NAME = "А.В. Смирнов"
PAGE2 = [
    "Приложение № 1 к акту сверки",
    "Перечень оборудования, переданного Заказчику для эксплуатации в рамках договора "
    "подряда, приведен в настоящем приложении. Оборудование проверено и принято без "
    "замечаний, гарантийный срок составляет двенадцать месяцев.",
]


def find_font(bold: bool = False) -> str:
    names = (["timesbd.ttf", "LiberationSerif-Bold.ttf", "DejaVuSerif-Bold.ttf"] if bold
             else ["times.ttf", "LiberationSerif-Regular.ttf", "DejaVuSerif.ttf"])
    dirs = [os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"),
            "/usr/share/fonts/truetype/liberation", "/usr/share/fonts/truetype/dejavu",
            "/usr/share/fonts/liberation", "/Library/Fonts"]
    for n in names:
        for d in dirs:
            p = os.path.join(d, n)
            if os.path.isfile(p):
                return p
    raise SystemExit("Не найден шрифт с кириллицей")


def pt(size: float) -> int:
    return int(round(size * DPI / 72))


def wrap(draw, text, font, width):
    lines, cur = [], []
    for word in text.split():
        trial = " ".join(cur + [word])
        if cur and draw.textlength(trial, font=font) > width:
            lines.append(cur)
            cur = [word]
        else:
            cur.append(word)
    if cur:
        lines.append(cur)
    return lines


def draw_paragraph(draw, text, font, x, y, width, indent, pitch):
    lines = wrap(draw, text, font, width - indent)
    for i, words in enumerate(lines):
        x0 = x + (indent if i == 0 else 0)
        avail = width - (indent if i == 0 else 0)
        if i < len(lines) - 1 and len(words) > 1:   # по ширине
            total = sum(draw.textlength(w, font=font) for w in words)
            gap = (avail - total) / (len(words) - 1)
            cx = x0
            for w in words:
                draw.text((cx, y), w, font=font, fill=0)
                cx += draw.textlength(w, font=font) + gap
        else:
            draw.text((x0, y), " ".join(words), font=font, fill=0)
        y += pitch
    return y


def page1() -> Image.Image:
    W, H = int(8.27 * DPI), int(11.69 * DPI)
    img = Image.new("L", (W, H), 255)
    d = ImageDraw.Draw(img)
    reg, bold = ImageFont.truetype(find_font(), pt(12)), ImageFont.truetype(find_font(True), pt(12))
    title = ImageFont.truetype(find_font(True), pt(14))
    left, right = int(1.2 * DPI), W - int(0.6 * DPI)
    width = right - left
    pitch = int(pt(12) * 1.15)
    y = int(0.8 * DPI)
    tw = d.textlength(TITLE, font=title)
    d.text(((W - tw) / 2, y), TITLE, font=title, fill=0)
    y += int(pitch * 2)
    for p in PARAS:
        y = draw_paragraph(d, p, reg, left, y, width, int(0.49 * DPI), pitch)
    y += pitch
    cols = [left, left + int(width * 0.55), left + int(width * 0.75), right]
    row_h = int(pitch * 1.6)
    top = y
    for r, row in enumerate(TABLE):
        for c, txt in enumerate(row):
            f = bold if r == 0 else reg
            tw = d.textlength(txt, font=f)
            cx = cols[c] + 10 if c == 0 else (cols[c] + cols[c + 1] - tw) / 2
            d.text((cx, y + (row_h - pt(12)) / 2 - 2), txt, font=f, fill=0)
        y += row_h
    for yy in range(top, y + 1, row_h):
        d.line((cols[0], yy, cols[-1], yy), fill=0, width=3)
    for xx in cols:
        d.line((xx, top, xx, y), fill=0, width=3)
    y += pitch * 2
    d.text((left, y), SIGN, font=reg, fill=0)
    lx = left + int(width * 0.45)
    d.line((lx, y + pt(12) - 2, lx + int(1.6 * DPI), y + pt(12) - 2), fill=0, width=2)
    d.text((lx + int(1.7 * DPI), y), SIGN_NAME, font=reg, fill=0)
    return img


def page2() -> Image.Image:
    W, H = int(11.69 * DPI), int(8.27 * DPI)       # альбомная
    img = Image.new("L", (W, H), 255)
    d = ImageDraw.Draw(img)
    reg = ImageFont.truetype(find_font(), pt(12))
    bold = ImageFont.truetype(find_font(True), pt(12))
    left, right = int(0.8 * DPI), W - int(0.8 * DPI)
    pitch = int(pt(12) * 1.15)
    y = int(0.8 * DPI)
    tw = d.textlength(PAGE2[0], font=bold)
    d.text(((W - tw) / 2, y), PAGE2[0], font=bold, fill=0)
    y += pitch * 2
    draw_paragraph(d, PAGE2[1], reg, left, y, right - left, int(0.49 * DPI), pitch)
    return img.rotate(90, expand=True, fillcolor=255)   # отсканировано боком


def scanify(img: Image.Image, angle: float, seed: int) -> Image.Image:
    img = img.rotate(angle, resample=Image.BICUBIC, fillcolor=255)
    img = img.filter(ImageFilter.GaussianBlur(0.6))
    arr = np.asarray(img).astype(np.float32)
    rng = np.random.default_rng(seed)
    arr = np.clip(arr * 0.92 + 14 + rng.normal(0, 7, arr.shape), 0, 255).astype(np.uint8)
    return Image.fromarray(arr).convert("RGB")


def expected_words() -> list[str]:
    words = TITLE.split()
    for p in PARAS:
        words += p.split()
    for row in TABLE:
        for cell in row:
            words += cell.split()
    words += [SIGN, *SIGN_NAME.split()]
    for p in PAGE2:
        words += p.split()
    return words


def main(out: str) -> None:
    pages = [scanify(page1(), 0.6, 1), scanify(page2(), -0.4, 2)]
    pages[0].save(out, save_all=True, append_images=pages[1:], resolution=DPI)
    with open(os.path.splitext(out)[0] + ".txt", "w", encoding="utf-8") as fh:
        fh.write(" ".join(expected_words()))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "test_scan.pdf")
