"""Текстовый слой электронных PDF (сохранённых из Word, LaTeX и т. п.).

В таких файлах текст уже есть — с точными буквами, шрифтами и размерами,
и распознавать его не нужно: отсюда берутся слова с положением на странице,
шрифтом, жирностью, курсивом и индексами. Картинка страницы при этом нужна
только для таблиц, линий и рисунков. Если текстового слоя нет, он невидимый
(скан с распознаванием от сканера) или испорчен, страница распознаётся как
скан."""

from __future__ import annotations

import ctypes
import math
import re
import unicodedata
from statistics import median

import cv2
import numpy as np
import pypdfium2.raw as pdfium_c

from .layout import Line, Word

XH = 0.45
# знаки символьных шрифтов (Symbol, Wingdings) PDFium отдаёт кодами области
# частного использования Юникода (U+F020…U+F0FE): в Word это квадратики
_SYM_LO = (" !∀#∃%&∋()∗+,−./0123456789:;<=>?≅ΑΒΧΔΕΦΓΗΙϑΚΛΜΝΟΠΘΡΣΤΥςΩΞΨΖ[∴]⊥_‾"
           "αβχδεφγηιϕκλμνοπθρστυϖωξψζ{|}∼")
_SYM_HI = ("€ϒ′≤⁄∞ƒ♣♦♥♠↔←↑→↓°±″≥×∝∂•÷≠≡≈…⏐⎯↵ℵℑℜ℘⊗⊕∅∩∪⊃⊇⊄⊂⊆∈∉∠∇®©™∏√⋅¬∧∨⇔⇐⇑⇒⇓"
           "◊⟨®©™∑⎛⎜⎝⎡⎢⎣⎧⎨⎩⎪ ⟩∫⌠⎮⌡⎞⎟⎠⎤⎥⎦⎫⎬⎭")
SYMBOL_FONT = {**{0xF020 + i: ch for i, ch in enumerate(_SYM_LO)},
               **{0xF0A0 + i: ch for i, ch in enumerate(_SYM_HI)}}
WINGDINGS = {0xF06C: "●", 0xF06E: "■", 0xF06F: "□", 0xF071: "❑", 0xF076: "❖", 0xF09F: "•",
             0xF0A7: "▪", 0xF0D8: "➢", 0xF0E0: "→", 0xF0E8: "➔", 0xF0FB: "✗", 0xF0FC: "✓",
             0xF0FE: "☑"}
SYMBOLS = {0xF0B7: "•", 0xF0A7: "▪", 0xF06E: "■", 0xF0D8: "➢", 0xF0FC: "✓", 0xF0E0: "→",
           0xF02D: "–", 0xF076: "❖"}       # шрифт не назван: самые частые значки                  # высота строчных в долях кегля — для порогов раскладки
# отдельные знаки ударений и умлаутов (так их рисует TeX) → комбинируемые
ACCENTS = {"\u00a8": "\u0308", "\u00b4": "\u0301", "\u02c6": "\u0302", "\u02dc": "\u0303",
           "\u02c7": "\u030c", "\u02d8": "\u0306", "\u00b8": "\u0327", "\u02da": "\u030a",
           "\u02dd": "\u030b", "\u00af": "\u0304", "\u02d9": "\u0307"}
# буквы высотой со строчную «x» (без выносных элементов) и высотой с прописную
X_LOW = set("acemnorsuvwxzавгежзиклмнопстхчшъыьэюя")
CAPS = set("ABCDEFHIKLMNOPRSTUVWXZАБВГДЕЖЗИКЛМНОПРСТУФХЧШЭЮЯ0123456789")
INVISIBLE = 3              # режим «невидимый текст»: слой распознавания под сканом

# шрифты, которые есть в Windows, — их имя сохраняем в Word как есть
KNOWN_FONTS = {
    "timesnewroman": "Times New Roman", "times": "Times New Roman",
    "timesroman": "Times New Roman", "arial": "Arial", "helvetica": "Arial",
    "calibri": "Calibri", "cambria": "Cambria", "cambriamath": "Cambria Math",
    "georgia": "Georgia", "verdana": "Verdana", "tahoma": "Tahoma",
    "couriernew": "Courier New", "courier": "Courier New", "consolas": "Consolas",
    "lucidaconsole": "Lucida Console", "segoeui": "Segoe UI", "garamond": "Garamond",
    "bookantiqua": "Book Antiqua", "palatinolinotype": "Palatino Linotype",
    "palatino": "Palatino Linotype", "centurygothic": "Century Gothic",
    "trebuchetms": "Trebuchet MS", "arialnarrow": "Arial Narrow", "candara": "Candara",
    "constantia": "Constantia", "corbel": "Corbel", "franklingothicmedium":
    "Franklin Gothic Medium", "bookmanoldstyle": "Bookman Old Style",
    "century": "Century", "centuryschoolbook": "Century Schoolbook",
    "symbol": "Symbol", "wingdings": "Wingdings",
}
SANS = re.compile(r"sans|arial|helvet|gothic|grotesk|verdana|tahoma|segoe|roboto|"
                  r"ubuntu|myriad|futura|franklin|calibri|lato|montserrat|trebuchet")
MONO = re.compile(r"courier|mono|consol|typewriter|cmtt|lmtt")


def font_style(name: str, flags: int, weight: int) -> tuple[str, bool, bool]:
    """(шрифт для Word, жирный, курсив) по имени шрифта из PDF."""
    base = re.sub(r"^[A-Z]{6}\+", "", name)
    low = base.lower()
    bold = weight >= 600 or bool(re.search(r"bold|black|heavy|semibold|demi", low))
    italic = bool(flags & 64) or bool(re.search(r"italic|oblique|-it$|-ital", low))
    key = re.sub(r"[^a-z]", "", re.split(r"[,-]", base)[0].lower())
    key = re.sub(r"(psmt|ps|mt)$", "", key)
    if key in KNOWN_FONTS:
        return KNOWN_FONTS[key], bold, italic
    if flags & 1 or MONO.search(low):
        return "Courier New", bold, italic
    if SANS.search(low):
        return "Arial", bold, italic
    return "", bold, italic          # шрифт с засечками — основной шрифт документа


class _Fonts:
    """Сведения о шрифтах страницы с кэшем по указателю шрифта."""

    def __init__(self):
        self.cache: dict[int, tuple[str, bool, bool]] = {}
        self.buf = ctypes.create_string_buffer(512)

        self.names: dict[int, str] = {}

    def family(self, font) -> str:
        """Имя шрифта из PDF строчными буквами."""
        key = ctypes.cast(font, ctypes.c_void_p).value or 0
        if key not in self.names:
            n = pdfium_c.FPDFFont_GetBaseFontName(font, self.buf, len(self.buf))
            self.names[key] = self.buf.raw[:max(0, n - 1)].decode("utf-8", "replace").lower()
        return self.names[key]

    def get(self, font) -> tuple[str, bool, bool]:
        key = ctypes.cast(font, ctypes.c_void_p).value or 0
        if key not in self.cache:
            n = pdfium_c.FPDFFont_GetBaseFontName(font, self.buf, len(self.buf))
            name = self.buf.raw[:max(0, n - 1)].decode("utf-8", "replace")
            self.cache[key] = font_style(name, pdfium_c.FPDFFont_GetFlags(font),
                                         pdfium_c.FPDFFont_GetWeight(font))
        return self.cache[key]


class _Frame:
    """Перевод координат страницы PDF (точки, начало внизу слева, без
    поворота) в пиксели отрисованной картинки (начало вверху слева)."""

    def __init__(self, page, scale: float):
        cx0, cy0, cx1, cy1 = page.get_cropbox()
        self.x0, self.y0 = cx0, cy0
        self.w, self.h = cx1 - cx0, cy1 - cy0
        self.rot = page.get_rotation() % 360
        self.scale = scale

    def point(self, x: float, y: float) -> tuple[float, float]:
        u, v = x - self.x0, self.h - (y - self.y0)
        if self.rot == 90:
            u, v = self.h - v, u
        elif self.rot == 180:
            u, v = self.w - u, self.h - v
        elif self.rot == 270:
            u, v = v, self.w - u
        return u * self.scale, v * self.scale

    def box(self, l: float, b: float, r: float, t: float) -> tuple[float, float, float, float]:
        pts = [self.point(x, y) for x in (l, r) for y in (b, t)]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        return min(xs), min(ys), max(xs), max(ys)


def page_words(page, scale: float) -> list[Word] | None:
    """Слова текстового слоя в пикселях отрисованной страницы или None,
    если страницу надо распознавать как скан."""
    textpage = page.get_textpage()
    try:
        return _page_words(page, textpage.raw, scale)
    finally:
        textpage.close()


def _page_words(page, tp, scale: float) -> list[Word] | None:
    n = pdfium_c.FPDFText_CountChars(tp)
    if n < 20:
        return None
    frame = _Frame(page, scale)
    fonts = _Fonts()
    modes: dict[int, int] = {}
    l, r, b, t = ctypes.c_double(), ctypes.c_double(), ctypes.c_double(), ctypes.c_double()
    ox, oy = ctypes.c_double(), ctypes.c_double()
    chars: list = []                  # (символ, рамка, базовая линия, кегль px, стиль) | None
    counts = {"visible": 0, "invisible": 0, "tilted": 0, "unmapped": 0}
    for i in range(n):
        u = pdfium_c.FPDFText_GetUnicode(tp, i)
        if u in (0x0D, 0x0A) or pdfium_c.FPDFText_IsGenerated(tp, i) == 1:
            chars.append(None)        # пробел или конец строки, вставленные PDFium
            continue
        if 0xDC00 <= u <= 0xDFFF:
            # вторая половина суррогатной пары (знаки вне основной плоскости)
            prev = chars[-1] if chars else None
            if prev and 0xD800 <= ord(prev[0][-1]) <= 0xDBFF:
                full = 0x10000 + ((ord(prev[0][-1]) - 0xD800) << 10) + (u - 0xDC00)
                chars[-1] = (prev[0][:-1] + chr(full),) + prev[1:]
            continue
        hyphen = u == 0xFFFE or u == 0x02 or pdfium_c.FPDFText_IsHyphen(tp, i) == 1
        if not hyphen and (u < 0x20 or u in (0xFFFE, 0xFFFF) or u > 0x10FFFF or
                           chr(u).isspace()):
            chars.append(None)        # пробелы и управляющие знаки (их нельзя в .docx)
            continue
        if not pdfium_c.FPDFText_GetCharBox(tp, i, l, r, b, t):
            chars.append(None)
            continue
        obj = pdfium_c.FPDFText_GetTextObject(tp, i)
        okey = ctypes.cast(obj, ctypes.c_void_p).value or 0
        if okey not in modes:
            modes[okey] = pdfium_c.FPDFTextObj_GetTextRenderMode(obj) if obj else 0
        if modes[okey] == INVISIBLE:
            counts["invisible"] += 1
            chars.append(None)
            continue
        angle = pdfium_c.FPDFText_GetCharAngle(tp, i)
        shown = (math.degrees(angle) - frame.rot) % 360 if angle >= 0 else 0.0
        if min(shown, 360 - shown) > 3:
            counts["tilted"] += 1     # повёрнутый текст (подписи сбоку таблиц)
            chars.append(None)
            continue
        counts["visible"] += 1
        if pdfium_c.FPDFText_HasUnicodeMapError(tp, i) == 1:
            counts["unmapped"] += 1
        size = pdfium_c.FPDFText_GetFontSize(tp, i)
        font = pdfium_c.FPDFTextObj_GetFont(obj) if obj else None
        style = fonts.get(font) if font else ("", False, False)
        pdfium_c.FPDFText_GetCharOrigin(tp, i, ox, oy)
        box = frame.box(l.value, b.value, r.value, t.value)
        base = frame.point(ox.value, oy.value)[1]
        ch = "\u00ad" if hyphen else chr(u)
        if 0xF020 <= u <= 0xF0FE:
            family = fonts.family(font) if font else ""
            table = SYMBOL_FONT if "symbol" in family else \
                WINGDINGS if "wingding" in family else SYMBOLS
            ch = table.get(u, ch)
        if not 3.0 <= size <= 150.0:
            # у шрифтов Type 3 PDFium сообщает размер с масштабом шрифта
            # (0,12 пт): кегль тогда оцениваем по высоте букв, а точный
            # подберёт раскладка, как у скана
            size = 0.0
            em = max(1.0, (box[3] - box[1]) / 0.7)
        else:
            em = size * scale
        chars.append((ch, box, base, em, style, size))
    # непарные половинки суррогатных пар в документ записать нельзя
    chars = [None if c and 0xD800 <= ord(c[0][-1]) <= 0xDFFF else c for c in chars]
    chars = _attach_accents(chars)
    total = counts["visible"] + counts["invisible"] + counts["tilted"]
    if counts["visible"] < 20 or counts["visible"] < 0.5 * total or \
            counts["unmapped"] > 0.2 * counts["visible"]:
        return None                   # буквы шрифта без Юникода: часть их теряется
    # без размера из PDF кегль один на страницу — по высоте строчных букв без
    # выносных элементов и прописных, иначе буквы с выносными казались бы крупнее
    ems = [(c[1][3] - c[1][1]) / (0.46 if c[0] in X_LOW else 0.67)
           for c in chars if c and c[5] == 0 and (c[0] in X_LOW or c[0] in CAPS)]
    if not ems:
        ems = [(c[1][3] - c[1][1]) / 0.7 for c in chars if c and c[5] == 0]
    if ems:
        page_em = max(1.0, float(median(ems)))
        chars = [c if c is None or c[5] else c[:3] + (page_em,) + c[4:] for c in chars]
    words = _fix_encoding(_join_chars(chars))
    if words is None or not _looks_like_text(words):
        return None
    return words


def _attach_accents(chars: list) -> list:
    """Знак над буквой, нарисованный отдельно («u» и «¨»), соединяем с буквой
    под ним: «ü». Иначе он попадёт в текст отдельным словом."""
    out = list(chars)
    drop = set()
    for i, c in enumerate(out):
        if c is None or c[0] not in ACCENTS:
            continue
        cx = (c[1][0] + c[1][2]) / 2
        cy = (c[1][1] + c[1][3]) / 2
        # знак может стоять в потоке далеко от своей буквы (в конце строки),
        # поэтому ищем по положению на странице
        near = [j for j, d in enumerate(out)
                if d is not None and j != i and j not in drop and d[0][-1].isalpha()
                and d[1][0] - 1 <= cx <= d[1][2] + 1
                and abs((d[1][1] + d[1][3]) / 2 - cy) < 1.2 * d[3]]
        if not near:
            continue
        j = min(near, key=lambda k: abs((out[k][1][1] + out[k][1][3]) / 2 - cy))
        base = out[j]
        out[j] = (unicodedata.normalize("NFC", base[0] + ACCENTS[c[0]]),) + base[1:]
        drop.add(i)
    return [c for k, c in enumerate(out) if k not in drop]


def _join_chars(chars: list) -> list[Word]:
    """Буквы → слова: по пробелам, по скачку на другую строку, по разрыву
    между буквами и по смене размера (индексы)."""
    words: list[Word] = []
    cur: list = []
    glue_next = False

    def flush(glue_after: bool):
        nonlocal cur, glue_next
        if cur:
            words.append(_make_word(cur, glue_next))
        glue_next = glue_after
        cur = []

    for ch in chars:
        if ch is None:
            flush(False)
            continue
        if cur and all(abs(a - b) < 0.5 for a, b in zip(ch[1], cur[-1][1])):
            cur.append(ch)                    # лигатура: несколько букв в одном знаке
            continue
        if cur:
            prev = cur[-1]
            em = max(prev[3], ch[3], 1.0)
            gap = ch[1][0] - prev[1][2]
            jump = abs(ch[2] - prev[2])
            if prev[0] == "­" or gap < -0.6 * em or jump > 0.5 * em:
                flush(False)                  # перенос или новая строка
            elif gap > 0.3 * em:
                flush(False)                  # пробел без символа пробела
            elif ch[5] and prev[5] and (jump > 0.1 * em or abs(ch[3] - prev[3]) > 0.15 * em):
                flush(True)                   # индекс: вплотную, без пробела
        cur.append(ch)
    flush(False)
    return words


def _make_word(cs: list, glue: bool) -> Word:
    text = "".join(c[0] for c in cs)
    if text == "ffi" and len({c[1] for c in cs}) == 1:
        text = "\u00a9"     # знак © в шрифтах TeX подписан как лигатура «ffi»
    x0 = min(c[1][0] for c in cs)
    y0 = min(c[1][1] for c in cs)
    x1 = max(c[1][2] for c in cs)
    y1 = max(c[1][3] for c in cs)
    # оформление слова — по буквам: точки отточия и знаки препинания вплотную
    # к слову часто набраны другим шрифтом
    styles: dict = {}
    letters = [c for c in cs if c[0].isalnum()] or cs
    for c in letters:
        styles[c[4]] = styles.get(c[4], 0) + 1
    font, bold, italic = max(styles, key=styles.get)
    sizes = [c[5] for c in cs if c[5] > 0]
    size_pt = float(median(sizes)) if sizes else 0.0
    return Word(text, int(round(x0)), int(round(y0)), max(int(round(x1)), int(round(x0)) + 1),
                max(int(round(y1)), int(round(y0)) + 1), 100.0, bold=bold, italic=italic,
                font=font, size=size_pt, glue=glue, base=float(median([c[2] for c in cs])),
                em=float(median([c[3] for c in cs])))


def _fix_encoding(words: list[Word]) -> list[Word] | None:
    """Русский текст, записанный в PDF в кодировке KOI8-R под видом латиницы
    («õÞÉÍ» вместо «Учим»), перекодируем; другой «мусор» — распознаём."""
    text = "".join(w.text for w in words)
    letters = sum(ch.isalpha() for ch in text)
    if not letters:
        return words
    cyr = sum("\u0400" <= ch <= "\u04ff" for ch in text)
    latin_ext = sum("\u00c0" <= ch <= "\u00ff" for ch in text)
    if latin_ext < 0.3 * letters or cyr > 0.1 * letters:
        return words

    def koi(s: str) -> str:
        return "".join(bytes([ord(ch)]).decode("koi8-r")
                       if 0x80 <= ord(ch) < 0x100 and ch != "\u00ad" else ch for ch in s)

    fixed = [koi(w.text) for w in words]
    joined = "".join(fixed)
    if sum("\u0400" <= ch <= "\u04ff" for ch in joined) < 0.6 * letters:
        return None
    for w, t in zip(words, fixed):
        w.text = t
    return words


def _looks_like_text(words: list[Word]) -> bool:
    """Буквы — обычные (а не символы из частной области шрифта)."""
    text = "".join(w.text for w in words)
    odd = sum(0xE000 <= ord(ch) <= 0xF8FF or ord(ch) < 0x20 for ch in text if ch != "­")
    return odd < 0.1 * max(1, len(text))


def build_lines(words: list[Word], scale: float) -> list[Line]:
    """Слова → строки по положению на странице (порядок в файле бывает любым:
    номер страницы нередко записан первым). Мелкие слова над и под базовой
    линией — верхние и нижние индексы своей строки. scale — пикселей в пункте."""
    rows: list[list[Word]] = []
    for w in sorted(words, key=lambda q: (q.base, q.x0)):
        best, best_ov = None, 0.0
        for row in rows[-6:]:
            ry0 = min(q.y0 for q in row)
            ry1 = max(q.y1 for q in row)
            ov = min(ry1, w.y1) - max(ry0, w.y0)
            h = min(ry1 - ry0, w.y1 - w.y0)
            if h > 0 and ov / h > best_ov:
                best, best_ov = row, ov / h
        if best is not None and best_ov >= 0.5:
            best.append(w)
        else:
            rows.append([w])
    def em_of(q: Word) -> float:
        # кегль слова в пикселях; без размера из PDF — оценка по высоте букв
        # (одна на страницу: иначе строки с «у», «д», «б» казались бы крупнее)
        return q.size * scale if q.size else (q.em or (q.y1 - q.y0) / 0.75)

    rows = _attach_scripts(rows, em_of)
    lines = []
    for row in rows:
        row.sort(key=lambda q: q.x0)
        ems = {id(q): em_of(q) for q in row}
        # основной кегль строки — тот, которым набрано больше всего букв
        # (в строке с формулой её знаки бывают крупнее текста)
        weight: dict[int, int] = {}
        for q in row:
            k = int(round(ems[id(q)]))
            weight[k] = weight.get(k, 0) + len(q.text)
        main_em = float(max(weight, key=weight.get))
        main = [q for q in row if abs(ems[id(q)] - main_em) <= 0.1 * main_em] or row
        em = float(median([ems[id(q)] for q in main]))
        base = float(median([q.base for q in main]))
        for q in row:
            # индекс — короткий и мельче основного текста, выше или ниже строки
            if q.size and len(q.text) <= 5 and ems[id(q)] < 0.85 * em and \
                    abs(q.base - base) > 0.2 * em:
                q.script = "super" if q.base < base else "sub"
        row[0].glue = False
        ln = Line(row, xh=XH * em, base=base)
        ln.sure = True
        lines.append(ln)
    return lines


def _attach_scripts(rows: list[list[Word]], em_of) -> list[list[Word]]:
    """Строка из одних мелких коротких слов (показатель степени, индекс),
    стоящая над или под строкой и в её пределах, — часть этой строки."""
    def small(row):
        return sum(len(q.text) for q in row) <= 6 and all(q.size for q in row)

    out: list[list[Word]] = []
    for row in rows:
        out.append(row)
    merged = True
    while merged:
        merged = False
        for i, row in enumerate(out):
            if not small(row):
                continue
            r_em = max(em_of(q) for q in row)
            x0, x1 = min(q.x0 for q in row), max(q.x1 for q in row)
            base = median([q.base for q in row])
            best = None
            for j, other in enumerate(out):
                if j == i or small(other):
                    continue
                o_em = float(median([em_of(q) for q in other]))
                if r_em >= 0.85 * o_em:
                    continue
                if not (min(q.x0 for q in other) - o_em <= x0 and x1 <= max(q.x1 for q in other) + o_em):
                    continue
                d = abs(median([q.base for q in other]) - base)
                if d < 0.75 * o_em and (best is None or d < best[0]):
                    best = (d, j)
            if best is not None:
                out[best[1]].extend(row)
                del out[i]
                merged = True
                break
    return out


def _content(obj, depth: int = 0) -> dict[int, int]:
    """Сколько объектов каждого типа внутри объекта PDF (с вложенными формами)."""
    kind = pdfium_c.FPDFPageObj_GetType(obj)
    counts = {kind: 1}
    if kind == pdfium_c.FPDF_PAGEOBJ_FORM and depth < 6:
        for i in range(pdfium_c.FPDFFormObj_CountObjects(obj)):
            for k, v in _content(pdfium_c.FPDFFormObj_GetObject(obj, i), depth + 1).items():
                counts[k] = counts.get(k, 0) + v
    return counts


Rect = tuple[float, float, float, float]          # l, b, r, t в точках PDF
IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def _intersect(a: Rect | None, b: Rect | None) -> Rect | None:
    if a is None or b is None:
        return a if b is None else b
    r = (max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3]))
    return r if r[0] < r[2] and r[1] < r[3] else (r[0], r[1], r[0], r[1])


def _transform(rect: Rect, m) -> Rect:
    pts = [_apply(m, x, y) for x in (rect[0], rect[2]) for y in (rect[1], rect[3])]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def _clip_rect(obj) -> Rect | None:
    """Рамка области обрезки объекта (в координатах, где лежит сам объект)."""
    clip = pdfium_c.FPDFPageObj_GetClipPath(obj)
    if not clip:
        return None
    x, y = ctypes.c_float(), ctypes.c_float()
    rect = None
    for k in range(max(0, pdfium_c.FPDFClipPath_CountPaths(clip))):
        xs, ys = [], []
        for j in range(max(0, pdfium_c.FPDFClipPath_CountPathSegments(clip, k))):
            seg = pdfium_c.FPDFClipPath_GetPathSegment(clip, k, j)
            if seg and pdfium_c.FPDFPathSegment_GetPoint(seg, x, y):
                xs.append(x.value)
                ys.append(y.value)
        if xs:
            rect = _intersect(rect, (min(xs), min(ys), max(xs), max(ys)))
    return rect


def _content_box(obj, m=IDENTITY, clip: Rect | None = None, depth: int = 0) -> Rect | None:
    """Видимая часть рисунка в координатах страницы: с учётом обрезки и без
    пустых вложенных форм, которые раздувают рамку, сообщаемую PDFium."""
    kind = pdfium_c.FPDFPageObj_GetType(obj)
    own = _clip_rect(obj)
    if own is not None:
        clip = _intersect(clip, _transform(own, m))
    if kind == pdfium_c.FPDF_PAGEOBJ_FORM:
        if depth >= 6:
            return None
        matrix = pdfium_c.FS_MATRIX()
        if pdfium_c.FPDFPageObj_GetMatrix(obj, ctypes.byref(matrix)):
            m = _mul((matrix.a, matrix.b, matrix.c, matrix.d, matrix.e, matrix.f), m)
        boxes = [_content_box(pdfium_c.FPDFFormObj_GetObject(obj, i), m, clip, depth + 1)
                 for i in range(pdfium_c.FPDFFormObj_CountObjects(obj))]
        boxes = [b for b in boxes if b is not None]
        if not boxes:
            return None
        return (min(b[0] for b in boxes), min(b[1] for b in boxes),
                max(b[2] for b in boxes), max(b[3] for b in boxes))
    if kind == pdfium_c.FPDF_PAGEOBJ_TEXT:
        return None
    l, b, r, t = ctypes.c_float(), ctypes.c_float(), ctypes.c_float(), ctypes.c_float()
    if not pdfium_c.FPDFPageObj_GetBounds(obj, l, b, r, t):
        return None
    rect = _intersect(_transform((l.value, b.value, r.value, t.value), m), clip)
    if rect[2] - rect[0] < 0.5 and rect[3] - rect[1] < 0.5:
        return None                    # пустой объект или целиком обрезан
    return rect


def picture_boxes(page, scale: float) -> list[tuple[int, int, int, int]]:
    """Рамки рисунков в пикселях страницы: встроенные картинки и фото, а также
    вложенные формы с картинками или чертежами без текста."""
    frame = _Frame(page, scale)
    pw, ph = frame.w * scale, frame.h * scale
    if frame.rot in (90, 270):
        pw, ph = ph, pw
    out = []
    for i in range(pdfium_c.FPDFPage_CountObjects(page.raw)):
        obj = pdfium_c.FPDFPage_GetObject(page.raw, i)
        kind = pdfium_c.FPDFPageObj_GetType(obj)
        if kind == pdfium_c.FPDF_PAGEOBJ_FORM:
            inside = _content(obj)
            if inside.get(pdfium_c.FPDF_PAGEOBJ_TEXT) or not (
                    inside.get(pdfium_c.FPDF_PAGEOBJ_IMAGE) or
                    inside.get(pdfium_c.FPDF_PAGEOBJ_PATH, 0) >= 3):
                continue              # форма с текстом — это не рисунок
        elif kind != pdfium_c.FPDF_PAGEOBJ_IMAGE:
            continue
        box = _content_box(obj)
        if box is None:
            continue
        x0, y0, x1, y1 = frame.box(*box)
        x0, y0 = max(0.0, x0), max(0.0, y0)
        x1, y1 = min(pw, x1), min(ph, y1)
        if x1 - x0 < 0.03 * pw or y1 - y0 < 0.02 * ph:
            continue                  # значки, линии-картинки
        if (x1 - x0) * (y1 - y0) > 0.8 * pw * ph:
            continue                  # фон всей страницы (обложка, подложка)
        out.append((math.floor(x0), math.floor(y0), math.ceil(x1), math.ceil(y1)))
    return out


# --------------------------------------------------------------------------
# Векторные линии

MAX_SEGMENTS = 20000          # сложные чертежи и графики целиком не разбираем


def _mul(a, m):
    """Матрица «сначала a, потом m» (как в PDF: x' = a·x + c·y + e)."""
    return (m[0] * a[0] + m[2] * a[1], m[1] * a[0] + m[3] * a[1],
            m[0] * a[2] + m[2] * a[3], m[1] * a[2] + m[3] * a[3],
            m[0] * a[4] + m[2] * a[5] + m[4], m[1] * a[4] + m[3] * a[5] + m[5])


def _apply(m, x: float, y: float) -> tuple[float, float]:
    return m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5]


def _visible(getter, obj) -> bool:
    """Цвет заметен на белой бумаге (не белый и не прозрачный)."""
    r, g, b, a = (ctypes.c_uint() for _ in range(4))
    if not getter(obj, r, g, b, a):
        return True
    return a.value > 40 and min(r.value, g.value, b.value) < 250


def rule_lines(page, scale: float) -> list[tuple[int, int, int, int]]:
    """Прямые линии, нарисованные векторами (рамки таблиц, подчёркивания,
    линии для подписи), в пикселях отрисовки. На картинке страницы тонкие
    и бледные линии теряются, а здесь они видны всегда."""
    frame = _Frame(page, scale)
    rects: list[tuple[float, float, float, float]] = []
    budget = [MAX_SEGMENTS]
    matrix = pdfium_c.FS_MATRIX()

    def walk(obj, m, depth):
        kind = pdfium_c.FPDFPageObj_GetType(obj)
        if kind not in (pdfium_c.FPDF_PAGEOBJ_PATH, pdfium_c.FPDF_PAGEOBJ_FORM):
            return
        if pdfium_c.FPDFPageObj_GetMatrix(obj, ctypes.byref(matrix)):
            m = _mul((matrix.a, matrix.b, matrix.c, matrix.d, matrix.e, matrix.f), m)
        if kind == pdfium_c.FPDF_PAGEOBJ_FORM:
            if depth < 6:
                for i in range(pdfium_c.FPDFFormObj_CountObjects(obj)):
                    walk(pdfium_c.FPDFFormObj_GetObject(obj, i), m, depth + 1)
        else:
            _path_lines(obj, m, rects, budget)

    for i in range(pdfium_c.FPDFPage_CountObjects(page.raw)):
        walk(pdfium_c.FPDFPage_GetObject(page.raw, i), IDENTITY, 0)
    out = []
    for l, b, r, t in rects:
        x0, y0, x1, y1 = frame.box(l, b, r, t)
        x0, y0, x1, y1 = math.floor(x0), math.floor(y0), math.ceil(x1), math.ceil(y1)
        if x1 - x0 < 2:
            x1 = x0 + 2
        if y1 - y0 < 2:
            y1 = y0 + 2
        out.append((max(0, x0), max(0, y0), x1, y1))
    return out


def _path_lines(obj, m, rects: list, budget: list) -> None:
    """Горизонтальные и вертикальные отрезки контура и тонкие залитые
    прямоугольники одного векторного объекта (координаты страницы)."""
    fill, stroke = ctypes.c_int(), ctypes.c_int()
    if not pdfium_c.FPDFPath_GetDrawMode(obj, fill, stroke):
        return
    n = pdfium_c.FPDFPath_CountSegments(obj)
    if n <= 1 or n > budget[0]:
        return
    budget[0] -= n
    filled = fill.value != 0 and _visible(pdfium_c.FPDFPageObj_GetFillColor, obj)
    stroked = bool(stroke.value) and _visible(pdfium_c.FPDFPageObj_GetStrokeColor, obj)
    if not (filled or stroked):
        return
    width = ctypes.c_float(0.0)
    pdfium_c.FPDFPageObj_GetStrokeWidth(obj, width)
    half = max(0.25, width.value * math.sqrt(abs(m[0] * m[3] - m[1] * m[2])) / 2)

    subpaths: list[list[tuple[float, float, bool]]] = []
    x, y = ctypes.c_float(), ctypes.c_float()
    for i in range(n):
        seg = pdfium_c.FPDFPath_GetPathSegment(obj, i)
        if not seg or not pdfium_c.FPDFPathSegment_GetPoint(seg, x, y):
            continue
        kind = pdfium_c.FPDFPathSegment_GetType(seg)
        px, py = _apply(m, x.value, y.value)
        if kind == pdfium_c.FPDF_SEGMENT_MOVETO or not subpaths:
            subpaths.append([(px, py, False)])
        else:
            subpaths[-1].append((px, py, kind == pdfium_c.FPDF_SEGMENT_BEZIERTO))
        if pdfium_c.FPDFPathSegment_GetClose(seg) and subpaths[-1]:
            sx, sy, _ = subpaths[-1][0]
            subpaths[-1].append((sx, sy, False))

    for sub in subpaths:
        if filled and not any(c for _, _, c in sub):
            xs = sorted({round(p[0], 1) for p in sub})
            ys = sorted({round(p[1], 1) for p in sub})
            if 4 <= len(sub) <= 6 and len(xs) <= 2 and len(ys) <= 2:
                w, h = xs[-1] - xs[0], ys[-1] - ys[0]
                thin, long = min(w, h), max(w, h)
                if thin <= 3.0 and long >= 4.0 and long >= 3 * thin:
                    rects.append((xs[0], ys[0], xs[-1], ys[-1]))
                    continue
        if not stroked:
            continue
        for (ax, ay, _), (bx, by, curve) in zip(sub, sub[1:]):
            if curve:
                continue
            if abs(ay - by) <= 0.3 and abs(ax - bx) >= 4.0:
                rects.append((min(ax, bx), ay - half, max(ax, bx), ay + half))
            elif abs(ax - bx) <= 0.3 and abs(ay - by) >= 4.0:
                rects.append((ax - half, min(ay, by), ax + half, max(ay, by)))


# --------------------------------------------------------------------------
# Чертежи из векторных линий

def _path_shape(obj, m, budget: list) -> tuple[Rect, bool, bool] | None:
    """Рамка видимого векторного объекта (координаты страницы), есть ли в нём
    кривые или наклонные отрезки и не тонкая ли это прямая линия."""
    fill, stroke = ctypes.c_int(), ctypes.c_int()
    if not pdfium_c.FPDFPath_GetDrawMode(obj, fill, stroke):
        return None
    filled = fill.value != 0 and _visible(pdfium_c.FPDFPageObj_GetFillColor, obj)
    stroked = bool(stroke.value) and _visible(pdfium_c.FPDFPageObj_GetStrokeColor, obj)
    if not (filled or stroked):
        return None
    n = pdfium_c.FPDFPath_CountSegments(obj)
    if n <= 1:
        return None
    if n > budget[0]:
        # очень сложный контур (карта, график) разбирать не будем: это рисунок
        l, b, r, t = ctypes.c_float(), ctypes.c_float(), ctypes.c_float(), ctypes.c_float()
        if not pdfium_c.FPDFPageObj_GetBounds(obj, l, b, r, t):
            return None
        return _transform((l.value, b.value, r.value, t.value), m), True, False
    budget[0] -= n
    x, y = ctypes.c_float(), ctypes.c_float()
    xs, ys = [], []
    curved = False
    px = py = None
    for i in range(n):
        seg = pdfium_c.FPDFPath_GetPathSegment(obj, i)
        if not seg or not pdfium_c.FPDFPathSegment_GetPoint(seg, x, y):
            continue
        kind = pdfium_c.FPDFPathSegment_GetType(seg)
        qx, qy = _apply(m, x.value, y.value)
        if kind == pdfium_c.FPDF_SEGMENT_BEZIERTO:
            curved = True
        elif kind == pdfium_c.FPDF_SEGMENT_LINETO and px is not None:
            dx, dy = abs(qx - px), abs(qy - py)
            if dx > 0.5 and dy > 0.5 and dx + dy > 2.0:
                curved = True             # наклонный отрезок
        xs.append(qx)
        ys.append(qy)
        px, py = qx, qy
    if not xs:
        return None
    width = ctypes.c_float(0.0)
    pdfium_c.FPDFPageObj_GetStrokeWidth(obj, width)
    half = width.value * math.sqrt(abs(m[0] * m[3] - m[1] * m[2])) / 2 if stroked else 0.0
    rect = (min(xs) - half, min(ys) - half, max(xs) + half, max(ys) + half)
    thin = not curved and min(rect[2] - rect[0], rect[3] - rect[1]) <= 3.0
    return rect, curved, thin


def figure_boxes(page, scale: float, words: list[Word]) -> list[tuple[int, int, int, int]]:
    """Рамки чертежей, нарисованных векторными линиями и кривыми (геометрические
    построения, графики, схемы), в пикселях отрисовки. Подписи точек на чертеже
    («A», «B₁») входят в рамку. Рамки таблиц и подчёркивания (прямые линии) и
    рамки вокруг текста чертежами не считаются."""
    frame = _Frame(page, scale)
    pw, ph = frame.w * scale, frame.h * scale
    if frame.rot in (90, 270):
        pw, ph = ph, pw
    items: list[tuple[float, float, float, float, bool, bool]] = []
    budget = [MAX_SEGMENTS]
    matrix = pdfium_c.FS_MATRIX()

    def walk(obj, m, depth):
        kind = pdfium_c.FPDFPageObj_GetType(obj)
        if kind == pdfium_c.FPDF_PAGEOBJ_FORM:
            if depth >= 6:
                return
            if pdfium_c.FPDFPageObj_GetMatrix(obj, ctypes.byref(matrix)):
                m = _mul((matrix.a, matrix.b, matrix.c, matrix.d, matrix.e, matrix.f), m)
            for i in range(pdfium_c.FPDFFormObj_CountObjects(obj)):
                walk(pdfium_c.FPDFFormObj_GetObject(obj, i), m, depth + 1)
            return
        if kind != pdfium_c.FPDF_PAGEOBJ_PATH:
            return
        if pdfium_c.FPDFPageObj_GetMatrix(obj, ctypes.byref(matrix)):
            m = _mul((matrix.a, matrix.b, matrix.c, matrix.d, matrix.e, matrix.f), m)
        shape = _path_shape(obj, m, budget)
        if shape is None:
            return
        rect, curved, thin = shape
        x0, y0, x1, y1 = frame.box(*rect)
        if (x1 - x0) * (y1 - y0) > 0.8 * pw * ph:
            return                         # фон страницы
        items.append((x0, y0, x1, y1, curved, thin))

    for i in range(pdfium_c.FPDFPage_CountObjects(page.raw)):
        walk(pdfium_c.FPDFPage_GetObject(page.raw, i), IDENTITY, 0)
    if not any(it[4] for it in items):
        return []

    # объекты, стоящие рядом, — один чертёж: группируем по уменьшенной маске
    k = 0.25
    pad = 0.12 * 72 * scale * k
    mask = np.zeros((int(ph * k) + 2, int(pw * k) + 2), np.uint8)
    for x0, y0, x1, y1, curved, thin in items:
        if not thin:                       # линии таблиц чертежи не склеивают
            cv2.rectangle(mask, (int(x0 * k - pad), int(y0 * k - pad)),
                          (int(x1 * k + pad), int(y1 * k + pad)), 255, -1)
    _, labels = cv2.connectedComponents(mask)
    groups: dict[int, list] = {}
    for it in items:
        if it[5]:
            continue
        cy = min(labels.shape[0] - 1, max(0, int((it[1] + it[3]) / 2 * k)))
        cx = min(labels.shape[1] - 1, max(0, int((it[0] + it[2]) / 2 * k)))
        groups.setdefault(int(labels[cy, cx]), []).append(it)

    inch = 72 * scale
    segments = row_segments(words)
    out = []
    for members in groups.values():
        if not any(it[4] for it in members):
            continue                       # одни прямоугольники: рамки, заливки
        x0 = min(it[0] for it in members)
        y0 = min(it[1] for it in members)
        x1 = max(it[2] for it in members)
        y1 = max(it[3] for it in members)
        # прямые линии чертежа (оси, основания), не длиннее самого чертежа
        for it in items:
            if it[5] and it[0] < x1 + pad / k and it[2] > x0 - pad / k and \
                    it[1] < y1 + pad / k and it[3] > y0 - pad / k and \
                    it[2] - it[0] < 1.5 * (x1 - x0) and it[3] - it[1] < 1.5 * (y1 - y0):
                x0, y0 = min(x0, it[0]), min(y0, it[1])
                x1, y1 = max(x1, it[2]), max(y1, it[3])
        if x1 - x0 < 0.4 * inch or y1 - y0 < 0.4 * inch:
            continue                       # значок, знак корня в формуле
        box = _grow_with_labels((x0, y0, x1, y1), segments, 0.15 * inch)
        if _text_heavy(box, words):
            continue                       # формула или рамка вокруг текста
        out.append((max(0, math.floor(box[0])), max(0, math.floor(box[1])),
                    min(math.ceil(pw), math.ceil(box[2])), min(math.ceil(ph), math.ceil(box[3]))))
    return out


def row_segments(words: list[Word]) -> list[list[Word]]:
    """Слова → куски строк: слова одной строки, стоящие рядом (подпись на
    чертеже и строка текста рядом с ним — разные куски)."""
    rows: list[list[Word]] = []
    for w in sorted(words, key=lambda q: (q.base, q.x0)):
        best, best_ov = None, 0.0
        for row in rows[-6:]:
            ry0 = min(q.y0 for q in row)
            ry1 = max(q.y1 for q in row)
            h = min(ry1 - ry0, w.y1 - w.y0)
            ov = min(ry1, w.y1) - max(ry0, w.y0)
            if h > 0 and ov / h > best_ov:
                best, best_ov = row, ov / h
        if best is not None and best_ov >= 0.5:
            best.append(w)
        else:
            rows.append([w])
    out = []
    for row in rows:
        row.sort(key=lambda q: q.x0)
        em = float(median([q.em or (q.y1 - q.y0) for q in row]))
        cur = [row[0]]
        for a, b in zip(row, row[1:]):
            if b.x0 - a.x1 > 2.0 * em:
                out.append(cur)
                cur = [b]
            else:
                cur.append(b)
        out.append(cur)
    return out


def _inside(w: Word, box) -> bool:
    cx, cy = (w.x0 + w.x1) / 2, (w.y0 + w.y1) / 2
    return box[0] <= cx <= box[2] and box[1] <= cy <= box[3]


def inside_share(seg: list[Word], box) -> float:
    """Какая доля букв куска строки стоит внутри рамки."""
    total = sum(len(w.text) for w in seg) or 1
    return sum(len(w.text) for w in seg if _inside(w, box)) / total


def _grow_with_labels(box, segments: list[list[Word]], margin: float):
    """Подписи точек и отрезков у края чертежа («A», «B1») — часть чертежа.
    Кусок строки, где есть хоть одно длинное слово, — это текст, а не подпись."""
    x0, y0, x1, y1 = box
    for seg in segments:
        if any(len(w.text) > 3 or w.fill for w in seg):
            continue
        sx0, sy0 = min(w.x0 for w in seg), min(w.y0 for w in seg)
        sx1, sy1 = max(w.x1 for w in seg), max(w.y1 for w in seg)
        if sx1 > x0 - margin and sx0 < x1 + margin and sy1 > y0 - margin and sy0 < y1 + margin:
            x0, y0, x1, y1 = min(x0, sx0), min(y0, sy0), max(x1, sx1), max(y1, sy1)
    return x0, y0, x1, y1


def _text_heavy(box, words: list[Word]) -> bool:
    """В рамке много текста: формула (знак корня нарисован линиями) или рамка
    вокруг абзаца. У чертежа надписи занимают мало места."""
    x0, y0, x1, y1 = box
    area = max(1.0, (x1 - x0) * (y1 - y0))
    covered = sum((w.x1 - w.x0) * (w.y1 - w.y0) for w in words if _inside(w, box))
    return covered > 0.08 * area


def fit_boxes(boxes: list, words: list[Word]) -> list:
    """Строка обычного текста, задетая рамкой рисунка (текст обтекает рисунок,
    рамка зацепила строку над ним), остаётся текстом: рамку сужаем."""
    segments = row_segments(words)
    out = []
    for box in boxes:
        x0, y0, x1, y1 = box
        for seg in segments:
            if not any(_inside(w, (x0, y0, x1, y1)) for w in seg):
                continue
            if inside_share(seg, (x0, y0, x1, y1)) >= 0.6:
                continue                   # надпись на самом рисунке
            hit = [w for w in seg if _inside(w, (x0, y0, x1, y1))]
            sx0, sx1 = min(w.x0 for w in seg), max(w.x1 for w in seg)
            hy0, hy1 = min(w.y0 for w in hit), max(w.y1 for w in hit)
            if sx0 < x0 and sx1 > x1:      # строка пересекает рисунок целиком
                if (hy0 + hy1) / 2 < (y0 + y1) / 2:
                    y0 = max(y0, hy1 + 2)
                else:
                    y1 = min(y1, hy0 - 2)
            elif sx0 < x0:                 # текст слева заходит на рисунок
                x0 = max(x0, max(w.x1 for w in hit) + 2)
            else:
                x1 = min(x1, min(w.x0 for w in hit) - 2)
        if x1 - x0 >= 0.5 * (box[2] - box[0]) and y1 - y0 >= 0.5 * (box[3] - box[1]):
            box = (int(x0), int(y0), int(x1), int(y1))
        out.append(box)
    return out


def merge_boxes(boxes: list) -> list:
    """Пересекающиеся рамки рисунков объединяем (картинка с надписями поверх)."""
    boxes = [list(b) for b in boxes]
    merged = True
    while merged:
        merged = False
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                a, b = boxes[i], boxes[j]
                if a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]:
                    boxes[i] = [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]
                    del boxes[j]
                    merged = True
                    break
            if merged:
                break
    return [tuple(b) for b in boxes]
