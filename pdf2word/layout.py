"""Восстановление структуры текста: слова → строки → абзацы, колонки,
выравнивание, отступы, размер шрифта, жирный и подчёркнутый текст."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from statistics import median

import cv2
import numpy as np

from . import textfix

LOWER = re.compile(r"[a-zа-яё]")
UPPER_DIGIT = re.compile(r"[A-ZА-ЯЁ0-9]")
LIST_START = re.compile(r"^([-–—•·▪●]|\d{1,2}[.)]|\d{1,2}\.\d{1,2}\.?|[а-яa-z]\))$")


@dataclass
class Word:
    text: str
    x0: int
    y0: int
    x1: int
    y1: int
    conf: float = 100.0
    bold: bool = False
    underline: bool = False
    fill: bool = False      # линия для заполнения «______»
    stroke: float = 0.0     # относительная толщина штриха


@dataclass
class Line:
    words: list[Word]
    xh: float = 0.0          # высота строчных букв, px
    base: float = 0.0        # базовая линия, px
    key: tuple = ()

    @property
    def x0(self):
        return min(w.x0 for w in self.words)

    @property
    def x1(self):
        return max(w.x1 for w in self.words)

    @property
    def y0(self):
        return min(w.y0 for w in self.words)

    @property
    def y1(self):
        return max(w.y1 for w in self.words)

    @property
    def text(self):
        return " ".join(w.text for w in self.words)

    @property
    def center(self):
        return (self.x0 + self.x1) / 2


@dataclass
class Para:
    lines: list[Line]
    align: str = "left"           # left / center / right / justify
    left: float = 0.0             # отступ слева, px от левого края области
    first: float = 0.0            # отступ первой строки, px (может быть < 0)
    size: float = 12.0            # кегль, pt
    space_before: float = 0.0     # px
    tabs: list = field(default_factory=list)   # [(позиция px, 'left'|'right'|'center')]
    segments: list | None = None  # для строк с табуляцией: список списков слов
    spacing: float = 1.0          # межстрочный интервал (множитель)

    @property
    def y0(self):
        return min(ln.y0 for ln in self.lines)

    @property
    def y1(self):
        return max(ln.y1 for ln in self.lines)

    @property
    def xh(self):
        return median([ln.xh for ln in self.lines])


@dataclass
class ColumnGroup:
    """Несколько колонок текста рядом (например, блок подписей)."""
    bounds: list[tuple[int, int]]          # границы ячеек по x
    cells: list[list[Para]]                # абзацы в каждой ячейке
    y0: int = 0
    y1: int = 0
    space_before: float = 0.0


# --------------------------------------------------------------------------
# Измерения по изображению

def measure_line(line: Line, ink: np.ndarray) -> None:
    """Определяет высоту строчных букв и базовую линию по проекции.

    Верх строчных и базовая линия — места самого резкого роста и спада
    горизонтальной проекции строки."""
    if all(w.fill for w in line.words):
        return              # линия «______» без текста: высоту задали заранее
    x0, y0, x1, y1 = line.x0, line.y0, line.x1, line.y1
    h = max(1, y1 - y0)
    if x1 <= x0:
        line.xh, line.base = h * 0.5, y1
        return
    words = [w for w in line.words if not w.fill]

    def lowfrac(t: str) -> float:
        lo, up = len(LOWER.findall(t)), len(UPPER_DIGIT.findall(t))
        return lo / (lo + up) if lo + up else 0.0

    # по возможности меряем только слова из строчных букв
    lower_words = [w for w in words if lowfrac(w.text) >= 0.6]
    n_lower = sum(len(LOWER.findall(w.text)) for w in lower_words)
    use = lower_words if n_lower >= 5 else words
    text = "".join(w.text for w in use)
    caps = lowfrac(text) < 0.35
    mask = np.zeros((h, x1 - x0), np.uint8)
    for w in use:
        mask[max(0, w.y0 - y0):w.y1 - y0, max(0, w.x0 - x0):w.x1 - x0] = 1
    crop = (ink[y0:y1, x0:x1] > 0) & (mask > 0)
    prof = crop.sum(axis=1).astype(np.float64)
    k = 1.45 if caps else 1.0       # у заглавных/цифр меряем высоту заглавных
    band, base = 0.5 * h / k, float(y1)
    if prof.max() > 0 and len(prof) >= 6:
        sm = np.convolve(prof, [1, 2, 1], mode="same") / 4.0
        d = np.diff(sm)
        # верх строчных — самый нижний из сильных подъёмов проекции
        # (выше него может быть подъём от заглавных и цифр)
        dmax = d.max()
        peaks = [i for i in range(len(d))
                 if d[i] >= 0.3 * dmax and (i == 0 or d[i] >= d[i - 1]) and
                 (i + 1 >= len(d) or d[i] >= d[i + 1])]
        fall = int(np.argmin(d))
        peaks = [i for i in peaks if i < fall - 2] or [int(np.argmax(d))]
        # у заглавных берём верхний подъём, у строчных — нижний
        top = (min(peaks) if caps else max(peaks)) + 1
        below = d[top:]
        ok = False
        if len(below):
            bot = top + int(np.argmin(below)) + 1   # резкий спад — базовая линия
            height = bot - top
            if 0.3 * h <= height <= 1.05 * h and height >= 4 and \
                    prof[top:bot].mean() >= 0.45 * prof.max():
                band, base, ok = height / k, float(y0 + bot), True
        if not ok:
            rows = np.where(prof >= 0.45 * prof.max())[0]
            if len(rows):
                band = float(rows[-1] - rows[0] + 1) / k
                base = float(y0 + rows[-1] + 1)
    line.xh = max(4.0, band)
    line.base = base


def stroke_width(ink: np.ndarray, w: Word) -> tuple[float, float]:
    """Две оценки толщины штриха: 2·площадь/периметр и по карте расстояний."""
    crop = ink[w.y0:w.y1, w.x0:w.x1]
    if crop.size == 0:
        return 0.0, 0.0
    area = cv2.countNonZero(crop)
    if area < 25:
        return 0.0, 0.0
    er = cv2.erode(crop, np.ones((3, 3), np.uint8))
    boundary = area - cv2.countNonZero(er)
    if boundary <= 0:
        return 0.0, 0.0
    ap = 2.0 * area / boundary
    d = cv2.distanceTransform((crop > 0).astype(np.uint8), cv2.DIST_L2, 3)
    ridge = (d >= cv2.dilate(d, np.ones((3, 3), np.uint8))) & (d > 0.5)
    dt = 2.0 * float(np.median(d[ridge])) if ridge.sum() >= 5 else ap
    return ap, dt


def _alnum(text: str) -> int:
    return sum(ch.isalnum() for ch in text)


def mark_bold(lines: list[Line], ink: np.ndarray) -> None:
    """Жирный шрифт: штрих заметно толще, чем у основного текста страницы.

    Толщина штриха мерится как 2·площадь/периметр и делится на высоту
    строчных букв строки. Сначала решаем для строки целиком (заголовки),
    потом для отдельных слов — с запасом, чтобы не было ложных срабатываний."""
    samples_a, samples_d = [], []
    feats: dict[int, tuple[float, float]] = {}
    for ln in lines:
        for w in ln.words:
            w.bold = False
            w.stroke = 0.0
            if w.fill or _alnum(w.text) == 0 or not ln.xh:
                continue
            ap, dt = stroke_width(ink, w)
            if ap <= 0:
                continue
            feats[id(w)] = (ap / ln.xh, dt / ln.xh)
            if _alnum(w.text) >= 4 and w.conf >= 50:
                samples_a.append(ap / ln.xh)
                samples_d.append(dt / ln.xh)
    if len(samples_a) < 8:
        return
    ref_a = float(np.percentile(samples_a, 40))
    ref_d = float(np.percentile(samples_d, 40))
    if ref_a <= 0 or ref_d <= 0:
        return
    for ln in lines:
        for w in ln.words:
            f = feats.get(id(w))
            if f:
                # среднее двух независимых оценок — меньше ложных срабатываний
                w.stroke = (f[0] / ref_a + f[1] / ref_d) / 2.0

    # Местная поправка: скан бывает темнее в одной части страницы, поэтому
    # опорную толщину берём по соседним строкам той же области (но не
    # больше чем на 12% выше общей — иначе спрячется жирный абзац).
    local_ref: dict[int, float] = {}
    groups: dict[tuple, list[Line]] = {}
    for ln in lines:
        key = ln.key[:2] if ln.key and ln.key[0] == "cell" else ("text",)
        groups.setdefault(key, []).append(ln)
    for grp in groups.values():
        grp.sort(key=lambda l: l.base)
        for i, ln in enumerate(grp):
            vals = [w.stroke for j in range(max(0, i - 4), min(len(grp), i + 5)) if j != i
                    for w in grp[j].words if w.stroke > 0 and _alnum(w.text) >= 4]
            if len(vals) >= 6:
                local_ref[id(ln)] = min(1.12, max(1.0, float(np.percentile(vals, 40))))

    def score(w: Word, ref_line: float) -> float | None:
        if w.stroke <= 0:
            return None
        n = _alnum(w.text)
        k = 1.15 if n >= 4 else (1.28 if n == 3 else 1.42)
        return w.stroke / ref_line / k

    for ln in lines:
        ws = [w for w in ln.words if not w.fill]
        ref_line = local_ref.get(id(ln), 1.0)
        sc = [score(w, ref_line) for w in ws]
        long_sc = [v for w, v in zip(ws, sc) if v is not None and _alnum(w.text) >= 3]
        uniform = long_sc and sum(v >= 0.93 for v in long_sc) >= 0.8 * len(long_sc) and \
            median(long_sc) >= 1.0
        if uniform:
            for w, v in zip(ws, sc):            # строка целиком жирная
                w.bold = v is None or v >= 0.85 or _alnum(w.text) < 3
        else:
            for w, v in zip(ws, sc):
                w.bold = v is not None and _alnum(w.text) >= 3 and v >= 1.08
            changed = True
            while changed:                      # продлеваем жирные фрагменты
                changed = False
                for i, w in enumerate(ws):
                    if w.bold or sc[i] is None:
                        continue
                    nb = (i > 0 and ws[i - 1].bold) or (i + 1 < len(ws) and ws[i + 1].bold)
                    if nb and _alnum(w.text) >= 3 and sc[i] >= 1.0:
                        w.bold = True
                        changed = True
            for i, w in enumerate(ws):          # короткие слова рядом с жирными
                if w.bold or _alnum(w.text) > 2:
                    continue
                lb = i > 0 and ws[i - 1].bold
                rb = i + 1 < len(ws) and ws[i + 1].bold
                edge = (i == 0 and rb) or (i == len(ws) - 1 and lb)
                if (lb and rb) or (edge and sc[i] is not None and sc[i] >= 0.9):
                    w.bold = True
        for i, w in enumerate(ws):              # знаки препинания между жирными
            if _alnum(w.text) == 0:
                l_b = ws[i - 1].bold if i > 0 else False
                r_b = ws[i + 1].bold if i + 1 < len(ws) else l_b
                w.bold = l_b and r_b


# --------------------------------------------------------------------------
# Строки и сегменты

def split_line(line: Line) -> list[Line]:
    """Разрезает строку по очень большим пробелам (табуляция, колонки)."""
    ws = sorted(line.words, key=lambda w: w.x0)
    if len(ws) < 2:
        return [line]
    gaps = [ws[i + 1].x0 - ws[i].x1 for i in range(len(ws) - 1)]
    xh = line.xh or 0.6 * median([w.y1 - w.y0 for w in ws]) or 20
    cuts = []
    for i, g in enumerate(gaps):
        others = gaps[:i] + gaps[i + 1:]
        typical = median(others) if others else xh * 0.6
        if len(gaps) == 1:
            big = g > 6.0 * xh
        else:
            big = g > 3.5 * xh and g > 3.0 * max(typical, xh * 0.4)
        if big:
            cuts.append(i + 1)
    if not cuts:
        line.words = ws
        return [line]
    parts, prev = [], 0
    for c in cuts + [len(ws)]:
        parts.append(Line(ws[prev:c], line.xh, line.base, line.key))
        prev = c
    return parts


def _voverlap(a: Line, b: Line) -> float:
    lo = max(a.y0, b.y0)
    hi = min(a.y1, b.y1)
    return max(0, hi - lo) / max(1, min(a.y1 - a.y0, b.y1 - b.y0))


def group_rows(segs: list[Line]) -> list[list[Line]]:
    segs = sorted(segs, key=lambda s: (s.base, s.x0))
    rows: list[list[Line]] = []
    for s in segs:
        placed = False
        for row in rows[-4:]:
            ref = row[0]
            xh = max(ref.xh, s.xh)
            if abs(ref.base - s.base) < 0.75 * xh and _voverlap(ref, s) > 0.4 and \
                    all(s.x1 <= o.x0 or s.x0 >= o.x1 for o in row):
                row.append(s)
                placed = True
                break
        if not placed:
            rows.append([s])
    for row in rows:
        row.sort(key=lambda s: s.x0)
    rows.sort(key=lambda r: min(s.base for s in r))
    return rows


# --------------------------------------------------------------------------
# Абзацы

def _pitch(lines: list[Line]) -> float:
    pitches = []
    for a, b in zip(lines, lines[1:]):
        d = b.base - a.base
        xh = max(a.xh, b.xh)
        if 1.5 * xh < d < 4.0 * xh and abs(a.xh - b.xh) < 0.3 * xh:
            pitches.append(d)
    if pitches:
        return float(median(pitches))
    xs = [ln.xh for ln in lines] or [20]
    return float(median(xs)) * 2.55


def _first_word_width(line: Line) -> float:
    for w in line.words:
        return w.x1 - w.x0
    return 0.0


def _is_list_start(line: Line) -> bool:
    if not line.words:
        return False
    first = line.words[0].text
    return bool(LIST_START.match(first))


def _is_centered(ln: Line, L: float, R: float, centered_mode: bool,
                 cell: bool = False) -> bool:
    xh = ln.xh or 20
    width = R - L
    lg, rg = ln.x0 - L, R - ln.x1
    tol = max(1.5 * xh, 0.025 * width)
    if cell:
        tol = max(0.8 * xh, 0.08 * width)
    if abs(lg - rg) >= tol:
        return False
    if centered_mode:
        return True
    need = 0.5 * xh if cell else 2.5 * xh
    return lg > need and rg > need


def _expected_x0(cur: list[Line], L: float, width: float) -> float | None:
    """Где должна начинаться следующая строка, если абзац продолжается."""
    if len(cur) >= 2:
        return cur[1].x0
    first = cur[0]
    if _is_list_start(first):
        return None                 # висячий отступ у пунктов списка
    xh = first.xh or 20
    indent = first.x0 - L
    if 1.0 * xh < indent < 0.15 * width:
        return L                    # была красная строка
    return first.x0


def segment_paragraphs(lines: list[Line], L: float, R: float,
                       centered_mode: bool = False, cell: bool = False) -> list[Para]:
    """Делит строки одной области (страница, ячейка, колонка) на абзацы."""
    if not lines:
        return []
    lines = sorted(lines, key=lambda ln: ln.base)
    width = max(1.0, R - L)
    pitch = _pitch(lines)

    paras: list[list[Line]] = [[lines[0]]]
    for prev, ln in zip(lines, lines[1:]):
        cur = paras[-1]
        xh = max(prev.xh, ln.xh) or 20
        cen_p = _is_centered(prev, L, R, centered_mode, cell)
        cen_c = _is_centered(ln, L, R, centered_mode, cell)
        new = False
        if ln.base - prev.base > 1.55 * pitch:
            new = True
        elif abs(ln.xh - prev.xh) > 0.35 * xh:
            new = True
        elif _is_list_start(ln):
            new = True
        else:
            # Если первое слово следующей строки поместилось бы в предыдущую,
            # значит, предыдущая строка была последней в абзаце.
            if cen_p or centered_mode:
                avail = width - (prev.x1 - prev.x0)
            else:
                avail = R - prev.x1
            if avail > _first_word_width(ln) + 1.1 * xh:
                new = True
            elif cen_p != cen_c:
                new = True
            elif not cen_c:
                exp = _expected_x0(cur, L, width)
                if exp is not None and abs(ln.x0 - exp) > 1.4 * xh:
                    new = True
        if new:
            paras.append([ln])
        else:
            cur.append(ln)
    return [_make_para(group, L, R, width, centered_mode, cell) for group in paras]


def _make_para(group: list[Line], L: float, R: float, width: float,
               centered_mode: bool, cell: bool = False) -> Para:
    p = Para(group)
    xh = median([ln.xh for ln in group]) or 20
    lefts = [ln.x0 - L for ln in group]
    rights = [R - ln.x1 for ln in group]
    edge = max(1.5 * xh, 0.03 * width)
    if all(_is_centered(ln, L, R, centered_mode, cell) for ln in group) and \
            (centered_mode or max(lefts) > (0.5 if cell else 2.5) * xh):
        p.align = "center"
        return p
    if len(group) == 1:
        lg, rg = lefts[0], rights[0]
        if rg < edge and lg > 0.3 * width:
            p.align = "right"
        else:
            p.align = "left"
            if lg > 0.15 * width:
                p.left = lg              # блок справа («УТВЕРЖДАЮ» и т.п.)
            elif lg > 1.0 * xh:
                p.first = lg             # красная строка
        return p
    body_left = median(lefts[1:])
    if max(rights[:-1]) < edge:
        p.align = "justify"
    elif min(rights) < edge and max(lefts) - min(lefts) > 3 * xh and \
            max(rights) - min(rights) < 1.5 * xh:
        p.align = "right"
        return p
    else:
        p.align = "left"
    p.left = max(0.0, body_left) if body_left > 0.8 * xh else 0.0
    p.first = lefts[0] - p.left
    if abs(p.first) < 0.8 * xh:
        p.first = 0.0
    return p


# --------------------------------------------------------------------------
# Раскладка страницы: колонки, строки с табуляцией, обычные абзацы

def _fits(seg: Line, iv: tuple[float, float], slack: float) -> bool:
    return seg.x1 > iv[0] - slack and seg.x0 < iv[1] + slack


def _assign(row: list[Line], cols: list[list[float]], slack: float) -> list[int] | None:
    """Номер колонки для каждого сегмента строки (или None, если не ложится)."""
    idx = []
    for s in row:
        hits = [k for k, iv in enumerate(cols) if _fits(s, iv, slack)]
        if len(hits) != 1:
            return None
        idx.append(hits[0])
    return idx


def layout_region(lines: list[Line], L: float, R: float) -> list:
    """Раскладывает строки страницы (вне таблиц) на элементы в порядке чтения."""
    segs: list[Line] = []
    for ln in lines:
        for seg in split_line(ln):
            if any(w.fill for w in seg.words) or \
                    any(ch.isalnum() for w in seg.words for ch in w.text):
                segs.append(seg)
    if not segs:
        return []
    rows = group_rows(segs)
    width = max(1.0, R - L)
    pitch = _pitch([r[0] for r in rows]) if rows else 40.0
    # строка «по ширине» с широкими пробелами — не табуляция: склеиваем обратно
    for k, row in enumerate(rows):
        if len(row) < 2:
            continue
        xh = median([sg.xh for sg in row]) or 20
        gaps = [b.x0 - a.x1 for a, b in zip(row, row[1:])]
        spans = row[0].x0 - L < 2.5 * xh and R - row[-1].x1 < 2.5 * xh
        if spans and max(gaps) < 0.15 * width:
            words = [w for sg in row for w in sg.words]
            rows[k] = [Line(words, xh, median([sg.base for sg in row]), row[0].key)]

    items = []   # (y, kind, payload)
    i = 0
    used = [False] * len(rows)
    while i < len(rows):
        row = rows[i]
        if len(row) >= 2 and not used[i]:
            xh = median([s.xh for s in row]) or 20
            slack = 1.0 * xh
            cols = [[s.x0, s.x1] for s in row]
            members = [i]
            multi = 1
            k = i + 1
            last_y = max(s.base for s in row)
            while k < len(rows):
                r = rows[k]
                gap = min(s.base for s in r) - last_y
                if gap > 4.5 * pitch:
                    break
                idx = _assign(r, cols, slack)
                if len(r) >= 2 and idx is not None and len(set(idx)) >= 2:
                    for s, c in zip(r, idx):
                        cols[c][0] = min(cols[c][0], s.x0)
                        cols[c][1] = max(cols[c][1], s.x1)
                    members.append(k)
                    multi += 1
                elif len(r) == 1 and idx is not None and \
                        (r[0].x1 - r[0].x0) < 0.55 * width and gap < 2.6 * pitch:
                    members.append(k)
                else:
                    break
                last_y = max(s.base for s in r)
                k += 1
            # хвостовые одиночные строки берём, только если они близко
            while members and len(rows[members[-1]]) == 1 and multi >= 2 and \
                    members[-1] != members[0]:
                prev_y = max(s.base for s in rows[members[-2]])
                if min(s.base for s in rows[members[-1]]) - prev_y < 2.6 * pitch:
                    break
                members.pop()
            if multi >= 2 and len(cols) >= 2:
                cols.sort(key=lambda c: c[0])
                group = _make_columns([rows[m] for m in members], cols, L, R, slack)
                if group is not None:
                    for m in members:
                        used[m] = True
                    items.append((group.y0, "cols", group))
                    i = members[-1] + 1
                    continue
            # одиночная строка из нескольких частей — абзац с табуляцией
            items.append((min(s.y0 for s in row), "tabrow", row))
            used[i] = True
            i += 1
            continue
        if not used[i]:
            items.append((row[0].y0, "line", row[0]))
            used[i] = True
        i += 1

    items.sort(key=lambda t: t[0])
    elements = []
    run: list[Line] = []

    def flush():
        if run:
            elements.extend(segment_paragraphs(run, L, R))
            run.clear()

    for _, kind, payload in items:
        if kind == "line":
            run.append(payload)
            continue
        flush()
        if kind == "cols":
            elements.append(payload)
        else:
            elements.append(_make_tab_para(payload, L, R))
    flush()
    return elements


def _make_tab_para(row: list[Line], L: float, R: float) -> Para:
    words = []
    for s in row:
        words.extend(s.words)
    line = Line(words, median([s.xh for s in row]), median([s.base for s in row]))
    p = Para([line])
    width = R - L
    p.segments = [s.words for s in row]
    first = row[0]
    xh = line.xh or 20
    if first.x0 - L > 1.0 * xh:
        p.left = first.x0 - L
    tabs = []
    for k, s in enumerate(row[1:], start=1):
        last = k == len(row) - 1
        if last and R - s.x1 < max(2.0 * xh, 0.03 * width):
            tabs.append((R - L, "right"))
        elif abs((s.x0 + s.x1) / 2 - (L + R) / 2) < 1.5 * xh:
            tabs.append(((s.x0 + s.x1) / 2 - L, "center"))
        else:
            tabs.append((s.x0 - L, "left"))
    p.tabs = tabs
    p.align = "left"
    return p


def _make_columns(rows: list[list[Line]], cols: list[list[float]], L: float, R: float,
                  slack: float) -> ColumnGroup | None:
    per_col: list[list[Line]] = [[] for _ in cols]
    for row in rows:
        parts: dict[int, list[Line]] = {}
        for s in row:
            hits = [k for k, iv in enumerate(cols) if _fits(s, iv, slack)]
            if len(hits) != 1:
                return None
            parts.setdefault(hits[0], []).append(s)
        for k, segs in parts.items():
            if len(segs) == 1:
                per_col[k].append(segs[0])
            else:   # несколько кусков одной строки в колонке — склеиваем
                words = sorted((w for sg in segs for w in sg.words), key=lambda w: w.x0)
                per_col[k].append(Line(words, max(sg.xh for sg in segs),
                                       median([sg.base for sg in segs])))
    n = len(cols)
    # границы между колонками — посередине промежутков
    edges = [L] + [(cols[k][1] + cols[k + 1][0]) / 2 for k in range(n - 1)] + [R]
    bounds: list[tuple[int, int]] = []
    cells: list[list[Para]] = []
    for k in range(n):
        lines = sorted(per_col[k], key=lambda ln: ln.base)
        lo, hi = edges[k], edges[k + 1]
        if not lines:
            bounds.append((int(lo), int(hi)))
            cells.append([])
            continue
        centers = [ln.center for ln in lines]
        lefts = [ln.x0 for ln in lines]
        xh = median([ln.xh for ln in lines]) or 20
        cmed = float(median(centers))
        close = [c for c in centers if abs(c - cmed) < 2.0 * xh]
        mutually_centered = len(lines) >= 2 and len(close) >= max(2, 0.7 * len(lines)) and \
            (max(lefts) - min(lefts)) > 2.0 * xh
        if mutually_centered:
            c = float(median(centers))
            half = min(c - lo, hi - c)
            a, b = c - half, c + half
            if a - lo > 2 * xh:
                bounds.append((int(lo), int(a)))
                cells.append([])
            bounds.append((int(a), int(b)))
            cells.append(segment_paragraphs(lines, a, b, centered_mode=True))
            if hi - b > 2 * xh:
                bounds.append((int(b), int(hi)))
                cells.append([])
        else:
            bounds.append((int(lo), int(hi)))
            cells.append(segment_paragraphs(lines, lo, max(ln.x1 for ln in lines)))
    # убираем пустые соседние колонки, сливая их
    merged_b, merged_c = [], []
    for b, c in zip(bounds, cells):
        if merged_b and not c and not merged_c[-1]:
            merged_b[-1] = (merged_b[-1][0], b[1])
        else:
            merged_b.append(b)
            merged_c.append(c)
    y0 = min(s.y0 for r in rows for s in r)
    y1 = max(s.y1 for r in rows for s in r)
    return ColumnGroup(merged_b, merged_c, y0, y1)


# --------------------------------------------------------------------------
# Текст абзаца с учётом форматирования

def para_runs(p: Para) -> list[tuple[str, bool, bool]]:
    """Собирает текст абзаца в фрагменты (текст, жирный, подчёркнутый)."""
    runs: list[list] = []

    def add(text, bold, underline):
        if runs and runs[-1][1] == bold and runs[-1][2] == underline:
            runs[-1][0] += text
        else:
            runs.append([text, bold, underline])

    if p.segments is not None:
        for k, seg in enumerate(p.segments):
            if k:
                add("\t", False, False)
            _add_words(seg, add)
        return [tuple(r) for r in runs]

    for li, ln in enumerate(p.lines):
        ws = ln.words
        if li > 0 and ws and runs:
            prev_text = runs[-1][0]
            joined_hyphen = prev_text.endswith(("-", "­")) and \
                bool(re.match(r"[a-zа-яё]", ws[0].text))
            if not joined_hyphen:
                prev_w = p.lines[li - 1].words[-1] if p.lines[li - 1].words else None
                ul = bool(prev_w and prev_w.underline and ws[0].underline)
                bold = bool(prev_w and prev_w.bold and ws[0].bold)
                add(" ", bold, ul)
        _add_words(ws, add)
    return [tuple(r) for r in runs]


def _add_words(ws: list[Word], add) -> None:
    for i, w in enumerate(ws):
        if i:
            prev = ws[i - 1]
            ul = prev.underline and w.underline
            bold = prev.bold and w.bold
            add(" ", bold, ul)
        add(w.text, w.bold, w.underline)


def para_text(p: Para) -> str:
    return "".join(r[0] for r in para_runs(p))


def fix_words(lines: list[Line]) -> None:
    for ln in lines:
        for w in ln.words:
            if not w.fill:
                w.text = textfix.fix_word(w.text)
                w.text = textfix.fix_case(w.text, w.y1 - w.y0, ln.xh)
