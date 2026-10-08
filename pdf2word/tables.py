"""Поиск таблиц с линиями (разлиновка) и построение сетки ячеек."""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np


@dataclass
class Segment:
    x0: int
    y0: int
    x1: int
    y1: int
    horizontal: bool

    @property
    def pos(self) -> float:
        return (self.y0 + self.y1) / 2 if self.horizontal else (self.x0 + self.x1) / 2

    @property
    def thick(self) -> int:
        return (self.y1 - self.y0) if self.horizontal else (self.x1 - self.x0)


@dataclass
class GridCell:
    r0: int
    c0: int
    r1: int  # не включительно
    c1: int
    x0: int = 0
    y0: int = 0
    x1: int = 0
    y1: int = 0
    paragraphs: list = field(default_factory=list)
    borderless: bool = False      # столбец подписей слева от таблицы бланка
    valign: str = ""              # "", "top", "center", "bottom"
    pictures: list = field(default_factory=list)   # рисунки в ячейке (layout.Picture)


@dataclass
class Table:
    xs: list[int]
    ys: list[int]
    cells: list[GridCell]
    line_mask: np.ndarray | None = None  # маска линий (в координатах страницы)
    bordered: bool = True
    segments: list = field(default_factory=list)   # отрезки линий сетки
    frame: bool = False                            # рамка листа, а не таблица
    place: tuple = ("center", 0)                   # выравнивание на листе и отступ, px
    beside_text: bool = False                      # рядом с таблицей стоит текст

    @property
    def x0(self):
        return self.xs[0]

    @property
    def x1(self):
        return self.xs[-1]

    @property
    def y0(self):
        return self.ys[0]

    @property
    def y1(self):
        return self.ys[-1]

    @property
    def nrows(self):
        return len(self.ys) - 1

    @property
    def ncols(self):
        return len(self.xs) - 1


def _segments(mask: np.ndarray, horizontal: bool, min_len: int) -> list[Segment]:
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    segs = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if horizontal and w >= min_len and h <= max(16, w // 6):
            if h > 6:
                # к линии может прилипнуть подчёркивание соседнего текста:
                # оставляем только ряды, прорисованные почти по всей длине
                comp = labels[y:y + h, x:x + w] == i
                cov = comp.sum(axis=1)
                rows = np.where(cov >= 0.5 * w)[0]
                if len(rows):
                    y, h = y + int(rows[0]), int(rows[-1] - rows[0] + 1)
            segs.append(Segment(x, y, x + w, y + h, True))
        elif not horizontal and h >= min_len and w <= max(16, h // 6):
            if w > 6:
                comp = labels[y:y + h, x:x + w] == i
                cov = comp.sum(axis=0)
                cols = np.where(cov >= 0.5 * h)[0]
                if len(cols):
                    x, w = x + int(cols[0]), int(cols[-1] - cols[0] + 1)
            segs.append(Segment(x, y, x + w, y + h, False))
    return segs


def _touch(h: Segment, v: Segment, tol: int) -> bool:
    return (v.x0 - tol <= h.x1 and v.x1 + tol >= h.x0 and
            h.y0 - tol <= v.y1 and h.y1 + tol >= v.y0)


def line_masks(ink: np.ndarray, xh: float) -> tuple[np.ndarray, np.ndarray]:
    """Длинные горизонтальные и вертикальные линии."""
    h, w = ink.shape
    hlen = int(max(4.5 * xh, 60))
    vlen = int(max(2.2 * xh, 40))
    # слегка «склеиваем» разрывы в линиях от плохого скана
    closed_h = cv2.morphologyEx(ink, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (5, 1)))
    closed_v = cv2.morphologyEx(ink, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (1, 5)))
    horiz = cv2.morphologyEx(closed_h, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (hlen, 1)))
    vert = cv2.morphologyEx(closed_v, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, vlen)))
    return horiz, vert


def _cluster(values: list[tuple[float, Segment]], tol: float) -> list[list[Segment]]:
    values = sorted(values, key=lambda t: t[0])
    groups: list[list[Segment]] = []
    last = None
    for pos, seg in values:
        if groups and pos - last <= tol:
            groups[-1].append(seg)
        else:
            groups.append([seg])
        last = pos
    return groups


def detect_tables(ink: np.ndarray, xh: float) -> list[Table]:
    horiz, vert = line_masks(ink, xh)
    hsegs = _segments(horiz, True, int(max(4.5 * xh, 60)))
    vsegs = _segments(vert, False, int(max(2.2 * xh, 40)))
    if len(hsegs) < 2 or len(vsegs) < 2:
        return []
    tol = int(max(6, xh * 0.35))

    # Линия сетки должна касаться минимум двух перпендикулярных линий.
    # Так подчёркивания внутри ячеек (они не доходят до границ) отсеиваются.
    for _ in range(4):
        h_keep = [hs for hs in hsegs if sum(_touch(hs, vs, tol) for vs in vsegs) >= 2]
        v_keep = [vs for vs in vsegs if sum(_touch(hs, vs, tol) for hs in h_keep) >= 2]
        if len(h_keep) == len(hsegs) and len(v_keep) == len(vsegs):
            break
        hsegs, vsegs = h_keep, v_keep
    if len(hsegs) < 2 or len(vsegs) < 2:
        return []

    # Группируем в отдельные таблицы по касаниям
    allsegs = hsegs + vsegs
    parent = list(range(len(allsegs)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for i, hs in enumerate(hsegs):
        for j, vs in enumerate(vsegs):
            if _touch(hs, vs, tol):
                parent[find(i)] = find(len(hsegs) + j)
    groups: dict[int, list[Segment]] = {}
    for i, s in enumerate(allsegs):
        groups.setdefault(find(i), []).append(s)

    tables = []
    H, W = ink.shape
    for segs in groups.values():
        hs = [s for s in segs if s.horizontal]
        vs = [s for s in segs if not s.horizontal]
        if len(hs) < 2 or len(vs) < 2:
            continue
        table = _build_table(hs, vs, tol, xh, (H, W))
        if table is None:
            continue
        # рамка вокруг всего листа (тень копира, рамка бланка) — не таблица
        area = (table.x1 - table.x0) * (table.y1 - table.y0)
        if len(table.cells) == 1 and area > 0.45 * H * W:
            table.bordered = False
            table.frame = True
        tables.append(table)
    tables.sort(key=lambda t: t.y0)
    return tables


def _build_table(hs: list[Segment], vs: list[Segment], tol: int, xh: float,
                 shape: tuple[int, int]) -> Table | None:
    hgroups = _cluster([(s.pos, s) for s in hs], tol)
    vgroups = _cluster([(s.pos, s) for s in vs], tol)
    ys = [int(round(np.mean([s.pos for s in g]))) for g in hgroups]
    xs = [int(round(np.mean([s.pos for s in g]))) for g in vgroups]
    # слишком узкие строки/столбцы (двойные линии) сливаем
    min_gap = max(8, int(0.6 * xh))
    ys, hgroups = _dedupe(ys, hgroups, min_gap)
    xs, vgroups = _dedupe(xs, vgroups, min_gap)
    if len(xs) < 2 or len(ys) < 2:
        return None
    if xs[-1] - xs[0] < 3 * xh or ys[-1] - ys[0] < 1.2 * xh:
        return None

    nr, nc = len(ys) - 1, len(xs) - 1

    def coverage_h(gi: int, xa: int, xb: int) -> float:
        """Какая доля отрезка [xa, xb] на горизонтальной линии gi прорисована."""
        if xb - xa <= 2 * tol:
            return 1.0
        lo, hi = xa + tol, xb - tol
        covered = np.zeros(hi - lo, dtype=bool)
        for s in hgroups[gi]:
            a, b = max(lo, s.x0 - tol), min(hi, s.x1 + tol)
            if b > a:
                covered[a - lo:b - lo] = True
        return covered.mean()

    def coverage_v(gi: int, ya: int, yb: int) -> float:
        if yb - ya <= 2 * tol:
            return 1.0
        lo, hi = ya + tol, yb - tol
        covered = np.zeros(hi - lo, dtype=bool)
        for s in vgroups[gi]:
            a, b = max(lo, s.y0 - tol), min(hi, s.y1 + tol)
            if b > a:
                covered[a - lo:b - lo] = True
        return covered.mean()

    # Объединение ячеек, между которыми нет линии
    parent = list(range(nr * nc))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    for r in range(nr):
        for c in range(nc):
            if c + 1 < nc and coverage_v(c + 1, ys[r], ys[r + 1]) < 0.5:
                union(r * nc + c, r * nc + c + 1)
            if r + 1 < nr and coverage_h(r + 1, xs[c], xs[c + 1]) < 0.5:
                union(r * nc + c, (r + 1) * nc + c)

    groups: dict[int, list[tuple[int, int]]] = {}
    for r in range(nr):
        for c in range(nc):
            groups.setdefault(find(r * nc + c), []).append((r, c))

    cells: list[GridCell] = []
    for members in groups.values():
        rs = [m[0] for m in members]
        cs = [m[1] for m in members]
        r0, r1, c0, c1 = min(rs), max(rs) + 1, min(cs), max(cs) + 1
        if len(members) != (r1 - r0) * (c1 - c0):
            # не прямоугольник — разбиваем обратно на простые ячейки
            for r, c in members:
                cells.append(GridCell(r, c, r + 1, c + 1))
            continue
        cells.append(GridCell(r0, c0, r1, c1))
    for cell in cells:
        cell.x0, cell.x1 = xs[cell.c0], xs[cell.c1]
        cell.y0, cell.y1 = ys[cell.r0], ys[cell.r1]
    cells.sort(key=lambda c: (c.r0, c.c0))

    H, W = shape
    mask = np.zeros((H, W), np.uint8)
    # линию, продолжающуюся за пределы таблицы (поле бланка на одном уровне
    # с границей строки), к таблице относим только в её пределах
    gx0, gx1, gy0, gy1 = xs[0] - tol, xs[-1] + tol, ys[0] - tol, ys[-1] + tol
    for s in hs:
        cv2.rectangle(mask, (max(s.x0, gx0) - 2, s.y0 - 2), (min(s.x1, gx1) + 2, s.y1 + 2), 255, -1)
    for s in vs:
        cv2.rectangle(mask, (s.x0 - 2, max(s.y0, gy0) - 2), (s.x1 + 2, min(s.y1, gy1) + 2), 255, -1)
    return Table(xs, ys, cells, mask, segments=list(hs) + list(vs))


def _dedupe(pos: list[int], groups: list[list[Segment]], min_gap: int):
    out_p, out_g = [], []
    for p, g in zip(pos, groups):
        if out_p and p - out_p[-1] < min_gap:
            out_g[-1] = out_g[-1] + g
            out_p[-1] = (out_p[-1] + p) // 2
        else:
            out_p.append(p)
            out_g.append(list(g))
    return out_p, out_g
