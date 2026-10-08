"""Создаёт «электронный» PDF (с текстовым слоем, как из Word или вёрстки)
для проверки программы и рядом файл с эталонными словами.

    python tests/make_digital.py digital.pdf

Нужен reportlab (pip install reportlab) и шрифты Liberation.
"""

from __future__ import annotations

import io
import os
import sys

import numpy as np
from PIL import Image
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

FONT_DIRS = ["/usr/share/fonts/truetype/liberation", "/usr/share/fonts/truetype/liberation2",
             "/usr/share/fonts/liberation", r"C:\Windows\Fonts"]
FACES = {"Serif": "LiberationSerif-Regular.ttf", "Serif-Bold": "LiberationSerif-Bold.ttf",
         "Serif-Italic": "LiberationSerif-Italic.ttf"}

LEFT, RIGHT = 25 * mm, A4[0] - 15 * mm
HEAD = "Учебное пособие по информатике"

# абзацы уже разбиты на строки, как в вёрстке; «-» в конце строки — перенос
PAGE1 = [
    ("Serif", 12, ["Компьютерная программа — это последовательность инструкций,",
                   "предназначенная для исполнения устройством управления вычисли-",
                   "тельной машины. Программы пишут на языках программирования."]),
    ("Serif", 12, ["Алгоритм описывает порядок действий, а программа — его запись",
                   "на понятном компьютеру языке. Перед написанием кода полезно",
                   "составить блок-схему и проверить её на простых примерах."]),
]
TABLE = [["Тип", "Размер, байт", "Диапазон"],
         ["byte", "1", "0…255"],
         ["short", "2", "−32768…32767"],
         ["int", "4", "около ±2 млрд"]]
PAGE3 = [
    ("Serif", 12, ["Рисунки и схемы помогают понять устройство программы. Ниже",
                   "показан пример рисунка, встроенного в документ."]),
]


def find_font(name: str) -> str:
    for d in FONT_DIRS:
        path = os.path.join(d, name)
        if os.path.exists(path):
            return path
    raise SystemExit(f"Не найден шрифт {name}: установите fonts-liberation")


def paragraph(c, lines, font, size, y, words, indent=12.5 * mm):
    lead = size * 1.25
    for k, line in enumerate(lines):
        x = LEFT + (indent if k == 0 else 0)
        last = k == len(lines) - 1
        parts = line.split(" ")
        if last or len(parts) == 1:
            c.setFont(font, size)
            c.drawString(x, y, line)
        else:
            # выключка по ширине: пробелы растягиваются
            width = sum(pdfmetrics.stringWidth(p, font, size) for p in parts)
            gap = (RIGHT - x - width) / (len(parts) - 1)
            for p in parts:
                c.setFont(font, size)
                c.drawString(x, y, p)
                x += pdfmetrics.stringWidth(p, font, size) + gap
        y -= lead
    text = ""
    for line in lines:
        if text.endswith("-") and line[:1].islower():
            text = text[:-1] + line          # перенос: слово целиком
        else:
            text = (text + " " + line).strip()
    words += text.split()
    return y - 0.4 * lead


def head_and_number(c, number: int):
    c.setFont("Serif-Italic", 10)
    c.drawString(LEFT, A4[1] - 15 * mm, HEAD)
    c.setLineWidth(0.5)
    c.line(LEFT, A4[1] - 17 * mm, RIGHT, A4[1] - 17 * mm)
    c.setFont("Serif", 10)
    c.drawCentredString((LEFT + RIGHT) / 2, 12 * mm, str(number))


def photo() -> ImageReader:
    yy, xx = np.mgrid[0:300, 0:400]
    rgb = np.stack([(xx * 255 // 400), (yy * 255 // 300), ((xx + yy) * 255 // 700)], axis=2)
    rgb = (rgb + np.random.default_rng(1).integers(0, 40, rgb.shape)).clip(0, 255)
    buf = io.BytesIO()
    Image.fromarray(rgb.astype(np.uint8)).save(buf, format="PNG")
    buf.seek(0)
    return ImageReader(buf)


def main(out: str) -> None:
    for face, file in FACES.items():
        pdfmetrics.registerFont(TTFont(face, find_font(file)))
    c = canvas.Canvas(out, pagesize=A4)
    words: list[str] = []

    # стр. 1: заголовок, абзацы с переносом, жирное и курсив
    head_and_number(c, 1)
    y = A4[1] - 35 * mm
    c.setFont("Serif-Bold", 16)
    c.drawCentredString((LEFT + RIGHT) / 2, y, "Глава 1. Программы")
    words += "Глава 1. Программы".split()
    y -= 14 * mm
    for font, size, lines in PAGE1:
        y = paragraph(c, lines, font, size, y, words)
    c.setFont("Serif-Bold", 12)
    c.drawString(LEFT + 12.5 * mm, y, "Переменная")
    w = pdfmetrics.stringWidth("Переменная ", "Serif-Bold", 12)
    c.setFont("Serif", 12)
    c.drawString(LEFT + 12.5 * mm + w, y, "— это именованная область")
    w2 = w + pdfmetrics.stringWidth("— это именованная область ", "Serif", 12)
    c.setFont("Serif-Italic", 12)
    c.drawString(LEFT + 12.5 * mm + w2, y, "оперативной памяти.")
    words += "Переменная — это именованная область оперативной памяти.".split()
    c.showPage()

    # стр. 2: таблица из линий
    head_and_number(c, 2)
    y = A4[1] - 35 * mm
    c.setFont("Serif", 12)
    c.drawString(LEFT, y, "Таблица 1. Целые типы языка C#")
    words += "Таблица 1. Целые типы языка C#".split()
    y -= 8 * mm
    xs = [LEFT, LEFT + 45 * mm, LEFT + 95 * mm, RIGHT]
    row_h = 9 * mm
    c.setLineWidth(0.6)
    for r in range(len(TABLE) + 1):
        c.line(xs[0], y - r * row_h, xs[-1], y - r * row_h)
    for x in xs:
        c.line(x, y, x, y - len(TABLE) * row_h)
    for r, row in enumerate(TABLE):
        for k, cell in enumerate(row):
            c.setFont("Serif-Bold" if r == 0 else "Serif", 12)
            c.drawString(xs[k] + 2 * mm, y - r * row_h - 6 * mm, cell)
            words += cell.split()
    c.showPage()

    # стр. 3: текст и рисунок с подписью
    head_and_number(c, 3)
    y = A4[1] - 35 * mm
    for font, size, lines in PAGE3:
        y = paragraph(c, lines, font, size, y, words)
    c.drawImage(photo(), LEFT + 30 * mm, y - 75 * mm, width=100 * mm, height=75 * mm)
    y -= 83 * mm
    c.setFont("Serif", 11)
    c.drawCentredString((LEFT + RIGHT) / 2, y, "Рис. 1. Пример рисунка")
    words += "Рис. 1. Пример рисунка".split()
    c.showPage()
    c.save()

    truth = os.path.splitext(out)[0] + ".txt"
    with open(truth, "w", encoding="utf-8") as f:
        f.write(" ".join(w for w in words) + "\n")
    print(out, truth)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "digital.pdf")
