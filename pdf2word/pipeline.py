"""Конвейер: страница PDF → распознанная структура → документ Word."""

from __future__ import annotations

import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from statistics import median
from typing import Callable

import cv2
import numpy as np

from . import imageops, layout, tables as tbl, textfix
from .engine import Cancelled, Engine, OcrError, TWord
from .layout import ColumnGroup, Line, Para, Word

XH_RATIO = 0.447         # высота строчных / кегль (Times New Roman)
LINE_H = 1.149           # высота строки при одинарном интервале / кегль (TNR)
COMMON_SIZES = [8, 9, 10, 11, 12, 14, 16, 18, 20, 22, 24, 26, 28, 36, 48, 72]


@dataclass
class Options:
    remove_stamps: bool = True       # стирать синие печати и подписи
    langs: str = "rus"
    workers: int = 0                 # 0 — по числу ядер (не больше 4)


@dataclass
class PageResult:
    index: int
    width_px: int
    height_px: int
    dpi: float
    elements: list = field(default_factory=list)   # Para | ColumnGroup | Table
    body: tuple = (0, 0, 0, 0)                     # x0, y0, x1, y1 содержимого
    body_size: float = 12.0
    rotated: int = 0


ProgressFn = Callable[[float, str], None]


# --------------------------------------------------------------------------

def _orient(engine: Engine, gray: np.ndarray, dpi: int) -> tuple[int, str]:
    """На сколько градусов (по часовой) повернуть страницу и какая письменность."""
    rot, conf, script, sconf = engine.osd(imageops.png_bytes(gray, dpi), dpi)
    script = script if sconf >= 1.0 else ""
    if conf >= 1.5:
        return rot, script
    ink = imageops.binarize(gray)
    vertical = imageops.text_is_vertical(ink)
    candidates = [90, 270] if vertical else [0, 180]
    if vertical is None:
        return 0, script
    # сравниваем уверенность распознавания центрального фрагмента
    h, w = gray.shape
    crop = gray[h // 4: 3 * h // 4, w // 4: 3 * w // 4]
    best, best_score = candidates[0], -1.0
    for c in candidates:
        img = imageops.rotate90(crop, c)
        words = engine.tsv(imageops.png_bytes(img, dpi), 6, dpi)
        good = [wd.conf for wd in words if len(wd.text) >= 3]
        score = float(np.mean(good)) * min(1.0, len(good) / 10) if good else 0.0
        if score > best_score:
            best, best_score = c, score
    return best, script


def _short_segments(ink: np.ndarray, xh: float, exclude: np.ndarray) -> list[tbl.Segment]:
    """Короткие горизонтальные линии: подчёркивания и поля «______»."""
    k = int(max(2.8 * xh, 40))
    opened = cv2.morphologyEx(ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (k, 1)))
    if exclude is not None:
        opened[exclude > 0] = 0
    n, _, stats, _ = cv2.connectedComponentsWithStats(opened, connectivity=8)
    segs = []
    max_t = max(8, int(0.6 * xh))
    for i in range(1, n):
        x, y, w, h, _ = stats[i]
        if w >= k and h <= max_t:
            segs.append(tbl.Segment(x, y, x + w, y + h, True))
    return segs


def _remove_specks(gray: np.ndarray, ink: np.ndarray, max_area: int) -> None:
    n, labels, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    small = np.where(stats[1:, cv2.CC_STAT_AREA] <= max_area)[0] + 1
    if len(small):
        mask = np.isin(labels, small)
        gray[mask] = 255
        ink[mask] = 0


def _lines_from_words(twords: list[TWord], offset=(0, 0), key_prefix=()) -> list[Line]:
    groups: dict[tuple, list[Word]] = {}
    ox, oy = offset
    for t in twords:
        key = key_prefix + (t.page, t.block, t.par, t.line)
        groups.setdefault(key, []).append(
            Word(t.text, t.x0 + ox, t.y0 + oy, t.x1 + ox, t.y1 + oy, t.conf))
    lines = []
    for key, ws in groups.items():
        ws.sort(key=lambda w: w.x0)
        lines.append(Line(ws, key=key))
    return lines


def _smooth_xh(lines: list[Line], page_xh: float) -> None:
    if not lines:
        return
    ordered = sorted(lines, key=lambda l: l.base)
    for i, ln in enumerate(ordered):
        n = sum(len(w.text) for w in ln.words if not w.fill)
        if n >= 14:
            continue
        neigh = [o.xh for o in ordered[max(0, i - 3):i + 4] if o is not ln and
                 sum(len(w.text) for w in o.words) >= 14]
        ref = float(median(neigh)) if neigh else page_xh
        # занижение — почти всегда ошибка измерения; завышение может быть
        # настоящим заголовком крупным шрифтом, его не трогаем
        if ref and ln.xh < 0.75 * ref:
            ln.xh = ref


def _in_zone(zone, w: Word) -> float:
    if zone is None:
        return 0.0
    crop = zone[w.y0:w.y1, w.x0:w.x1]
    return cv2.countNonZero(crop) / max(1, crop.size)


def _clean_lines(lines: list[Line], ink: np.ndarray, page_xh: float = 0.0,
                 zone=None) -> list[Line]:
    out = []
    for ln in lines:
        if zone is not None:
            # следы печатей и подписей: одиночные знаки в зоне стёртого цвета
            ws = ln.words
            kept = []
            for i, w in enumerate(ws):
                if w.fill or _in_zone(zone, w) < 0.3:
                    kept.append(w)
                    continue
                n = sum(ch.isalnum() for ch in w.text)
                if n == 0 and w.conf < 90:
                    continue
                if w.conf < 50 and n <= 3:
                    continue
                kept.append(w)
            # одиночная буква в зоне — только если стоит между словами
            final = []
            for i, w in enumerate(kept):
                n = sum(ch.isalnum() for ch in w.text)
                if not w.fill and n == 1 and w.conf < 85 and _in_zone(zone, w) >= 0.3:
                    xh0 = ln.xh or 20
                    left = kept[i - 1] if i > 0 else None
                    right = kept[i + 1] if i + 1 < len(kept) else None
                    ok = left is not None and right is not None and \
                        w.x0 - left.x1 < 1.5 * xh0 and right.x0 - w.x1 < 1.5 * xh0 and \
                        sum(ch.isalpha() for ch in left.text) >= 2 and \
                        sum(ch.isalpha() for ch in right.text) >= 2
                    if not ok:
                        continue
                final.append(w)
            ln.words = final
            if not final:
                continue
        if page_xh and ln.xh < 0.45 * page_xh and \
                sum(len(w.text) for w in ln.words if not w.fill) < 5:
            continue        # крошечные «буквы» — точки и обрывки печати
        keep = []
        for w in ln.words:
            if w.fill:
                keep.append(w)
                continue
            if textfix.is_noise(w.text, w.conf):
                continue
            if w.conf < 50 and len(w.text) <= 3 and textfix.LAT.search(w.text) and \
                    not textfix.CYR.search(w.text):
                continue     # обрывки латиницы от подписей и печатей
            if textfix.is_dash_only(w.text):
                crop = ink[w.y0:w.y1, w.x0:w.x1]
                dens = cv2.countNonZero(crop) / max(1, crop.size)
                if dens < 0.12 or w.text in ("|", "||") or (w.text == "_" and dens < 0.3):
                    continue
                if w.text in ("-", "–", "—") and ln.xh:
                    rel = (w.x1 - w.x0) / ln.xh
                    w.text = "-" if rel < 0.85 else ("–" if rel < 1.6 else "—")
            keep.append(w)
        # одинокие знаки препинания вдали от слов — мусор
        xh = ln.xh or 20
        gaps = [b.x0 - a.x1 for a, b in zip(keep, keep[1:])]
        typical_gap = float(median(gaps)) if gaps else xh
        filtered = []
        for i, w in enumerate(keep):
            if not w.fill and not any(ch.isalnum() for ch in w.text) and \
                    not textfix.is_dash_only(w.text):
                left = keep[i - 1] if i > 0 else None
                right = keep[i + 1] if i + 1 < len(keep) else None
                gl = w.x0 - left.x1 if left else 1e9
                gr = right.x0 - w.x1 if right else 1e9
                isolated = min(gl, gr) > max(1.2 * xh, 2.5 * typical_gap)
                meaningful = w.text in textfix.SYMBOLS and w.conf >= 70
                if w.conf < 60 or (isolated and not meaningful):
                    continue
            filtered.append(w)
        keep = filtered
        if not keep:
            continue
        real = [w for w in keep if not w.fill]
        if real and not any(w.fill for w in keep):
            confs = [w.conf for w in real]
            letters = sum(sum(ch.isalnum() for ch in w.text) for w in real)
            if np.mean(confs) < 35 and letters < 6:
                continue
            if np.mean(confs) < 20:
                continue
        ln.words = keep
        out.append(ln)
    return out


def _attach_fills(lines: list[Line], fills: list[tbl.Segment], xh: float) -> list[Line]:
    em = xh / XH_RATIO
    for s in fills:
        n = max(3, int(round((s.x1 - s.x0) / (0.5 * em))))
        w = Word("_" * n, s.x0, int(s.y0 - 0.9 * xh), s.x1, s.y1, 100.0, fill=True)
        target = None
        best = 1e9
        for ln in lines:
            lxh = ln.xh or xh
            base = ln.base or ln.y1
            if ln.y0 - 0.3 * lxh <= s.y0 <= base + 0.8 * lxh:
                gap = max(0, ln.x0 - s.x1, s.x0 - ln.x1)
                if gap < best and not any(o.x0 < s.x1 and o.x1 > s.x0 for o in ln.words):
                    best, target = gap, ln
        if target is not None and best < 0.4 * (s.x1 - s.x0) + 6 * xh:
            target.words.append(w)
            target.words.sort(key=lambda q: q.x0)
        else:
            lines.append(Line([w], xh=xh, base=s.y1, key=("fill", s.x0, s.y0)))
    return lines


def _mark_underlines(lines: list[Line], unders: list[tbl.Segment]) -> None:
    if not unders:
        return
    for ln in lines:
        xh = ln.xh or 20
        for w in ln.words:
            if w.fill:
                continue
            for s in unders:
                y = (s.y0 + s.y1) / 2
                if not (ln.base - 0.35 * xh <= y <= ln.base + 0.75 * xh):
                    continue
                ov = min(w.x1, s.x1) - max(w.x0, s.x0)
                if ov >= 0.5 * (w.x1 - w.x0):
                    w.underline = True
                    break


def _merge_fills(fills: list[tbl.Segment], xh: float) -> list[tbl.Segment]:
    """Склеивает куски одной линии «______», разорванной печатью."""
    fills = sorted(fills, key=lambda s: (round((s.y0 + s.y1) / 2 / (0.5 * xh)), s.x0))
    out: list[tbl.Segment] = []
    for s in fills:
        if out:
            p = out[-1]
            if abs((p.y0 + p.y1) / 2 - (s.y0 + s.y1) / 2) < 0.4 * xh and 0 <= s.x0 - p.x1 < 3 * xh:
                out[-1] = tbl.Segment(p.x0, min(p.y0, s.y0), s.x1, max(p.y1, s.y1), True)
                continue
        out.append(s)
    return out


def _assign_sizes(paras: list[Para], dpi: float) -> None:
    """Кегль — по высоте строчных букв, интервал — по шагу строк."""
    for p in paras:
        p.size = p.xh / dpi * 72.0 / XH_RATIO
        p.spacing = 1.0
        if len(p.lines) >= 2:
            pitches = [b.base - a.base for a, b in zip(p.lines, p.lines[1:])]
            m = median(pitches) / (LINE_H * p.size * dpi / 72.0)
            if m < 1.07:
                p.spacing = 1.0
            elif m < 1.3:
                p.spacing = 1.15
            elif m < 1.75:
                p.spacing = 1.5
            elif m < 2.3:
                p.spacing = 2.0


def _all_paras(elements) -> list[Para]:
    out = []
    for el in elements:
        if isinstance(el, Para):
            out.append(el)
        elif isinstance(el, ColumnGroup):
            for cell in el.cells:
                out.extend(cell)
        elif isinstance(el, tbl.Table):
            for cell in el.cells:
                out.extend(cell.paragraphs)
    return out


def _text_len(p: Para) -> int:
    return sum(len(w.text) for ln in p.lines for w in ln.words if not w.fill)


def _snap(size: float) -> float:
    return float(min(COMMON_SIZES, key=lambda c: abs(size - c) / c))


def _dominant(paras: list[Para]) -> float | None:
    weights: dict[float, int] = {}
    for p in paras:
        if _text_len(p) <= 4:
            continue
        s = _snap(p.size)
        weights[s] = weights.get(s, 0) + _text_len(p)
    return max(weights, key=weights.get) if weights else None


def finalize_sizes(pages: list["PageResult"]) -> float:
    """Приводит кегли к стандартным значениям по всему документу."""
    flow_paras, table_groups = [], []
    for page in pages:
        for el in page.elements:
            if isinstance(el, Para):
                flow_paras.append(el)
            elif isinstance(el, ColumnGroup):
                for cell in el.cells:
                    flow_paras.extend(cell)
            elif isinstance(el, tbl.Table):
                table_groups.append([p for c in el.cells for p in c.paragraphs])
    all_paras = flow_paras + [p for g in table_groups for p in g]
    body = _dominant(flow_paras) or _dominant(all_paras) or 12.0

    def apply(paras: list[Para], ref: float):
        for p in paras:
            if _text_len(p) <= 4:
                p.size = ref
                continue
            raw = p.size
            p.size = ref if abs(raw - ref) <= 0.08 * ref else _snap(raw)

    apply(flow_paras, body)
    for g in table_groups:
        apply(g, _dominant(g) or body)
    for page in pages:
        page.body_size = body
    return body


def _space_before(seq: list, dpi: float, start_y: float | None) -> None:
    """Вертикальные промежутки между элементами → интервал перед абзацем."""
    prev_bottom = start_y
    prev_base = None
    for el in seq:
        top = el.y0
        if isinstance(el, Para):
            first = el.lines[0]
            pitch = 1.15 * el.size * dpi / 72.0
            if prev_base is not None:
                extra = (first.base - prev_base) - pitch
            elif prev_bottom is not None:
                extra = top - prev_bottom - 0.25 * pitch
            else:
                extra = 0.0
            el.space_before = max(0.0, extra) if extra > 0.35 * pitch else 0.0
            prev_base = el.lines[-1].base
            prev_bottom = el.y1
        else:
            if prev_bottom is not None:
                gap = top - prev_bottom
                el.space_before = max(0.0, gap) if not isinstance(el, tbl.Table) else gap
            prev_base = None
            prev_bottom = el.y1


# --------------------------------------------------------------------------

def process_page(engine: Engine, src: imageops.PageSource, index: int,
                 opts: Options, step: Callable[[float], None] | None = None) -> PageResult:
    step = step or (lambda f: None)
    bgr, info = src.render(index)
    dpi = int(round(info.dpi))
    engine.check()
    step(0.05)

    gray0 = imageops.to_gray(bgr)
    rot, script = _orient(engine, gray0, dpi)
    langs = opts.langs
    if script == "Latin" and "eng" not in langs and engine.has_lang("eng"):
        langs = "eng+" + langs          # английский документ
    step(0.15)
    if rot:
        bgr = imageops.rotate90(bgr, rot)
    color_mask = None
    if opts.remove_stamps and bgr.ndim == 3:
        bgr, color_mask = imageops.remove_color_ink(bgr)
    gray = imageops.flatten_background(imageops.to_gray(bgr))
    del bgr, gray0
    ink = imageops.binarize(gray)
    angle = imageops.estimate_skew(ink)
    if abs(angle) >= 0.08:
        gray = imageops.rotate_small(gray, angle)
        ink = imageops.binarize(gray)
        if color_mask is not None:
            color_mask = imageops.rotate_small(color_mask, angle, 0)
    engine.check()

    step(0.25)
    H, W = gray.shape
    xh = imageops.estimate_xheight(ink)
    zone = None
    if color_mask is not None:
        color_mask[color_mask < 128] = 0
        k = max(3, int(0.8 * xh))
        zone = cv2.dilate(color_mask, np.ones((k, k), np.uint8))
    _remove_specks(gray, ink, max(3, int((dpi / 300.0) ** 2 * 6)))

    tables = tbl.detect_tables(ink, xh)
    grid_mask = np.zeros_like(ink)
    for t in tables:
        grid_mask |= t.line_mask

    segs = _short_segments(ink, xh, grid_mask)
    # обрывки линий таблицы (продолжение границы) — не подчёркивания:
    # они лежат на линии сетки и упираются в вертикальную линию или край
    tol = max(6, int(0.35 * xh))

    def grid_fragment(sg) -> bool:
        cy = (sg.y0 + sg.y1) / 2
        for t in tables:
            if not (t.x0 - tol <= sg.x1 and sg.x0 <= t.x1 + tol):
                continue
            if not any(abs(cy - y) <= tol for y in t.ys):
                continue
            if any(abs(sg.x0 - x) <= tol or abs(sg.x1 - x) <= tol for x in t.xs) or \
                    sg.x0 < t.x0 or sg.x1 > t.x1:
                return True
        return False

    segs = [sg for sg in segs if not grid_fragment(sg)]
    seg_mask = np.zeros_like(ink)
    for s in segs:
        cv2.rectangle(seg_mask, (s.x0 - 1, s.y0 - 2), (s.x1 + 1, s.y1 + 2), 255, -1)
    lines_removed = cv2.bitwise_or(grid_mask, seg_mask)
    clean = gray.copy()
    clean[lines_removed > 0] = 255
    clean_ink = ink.copy()
    clean_ink[lines_removed > 0] = 0

    # подчёркивание (над линией есть текст) или поле для заполнения (пусто)
    unders, fills = [], []
    for s in segs:
        y_top = max(0, int(s.y0 - 1.1 * xh))
        band = clean_ink[y_top:max(y_top + 1, s.y0 - 1), s.x0:s.x1]
        dens = cv2.countNonZero(band) / max(1, band.size)
        (unders if dens > 0.035 else fills).append(s)

    # --- распознавание текста вне таблиц
    text_img = clean.copy()
    for t in tables:
        cv2.rectangle(text_img, (t.x0 - 4, t.y0 - 4), (t.x1 + 4, t.y1 + 4), 255, -1)

    cell_jobs = []   # (table_idx, cell, crop_offset)
    crops = []
    pad = 20
    for ti, t in enumerate(tables):
        for cell in t.cells:
            inset = max(5, int(0.25 * xh))
            x0, y0 = cell.x0 + inset, cell.y0 + inset
            x1, y1 = cell.x1 - inset, cell.y1 - inset
            if x1 - x0 < 8 or y1 - y0 < 8:
                continue
            region_ink = clean_ink[y0:y1, x0:x1]
            if cv2.countNonZero(region_ink) < 15:
                continue
            crop = np.full((y1 - y0 + 2 * pad, x1 - x0 + 2 * pad), 255, np.uint8)
            crop[pad:-pad, pad:-pad] = clean[y0:y1, x0:x1]
            cell_jobs.append((ti, cell, (x0 - pad, y0 - pad)))
            crops.append(crop)

    step(0.3)

    def ocr_text():
        if cv2.countNonZero(cv2.threshold(text_img, 200, 255, cv2.THRESH_BINARY_INV)[1]) < 30:
            return []
        return engine.tsv(imageops.png_bytes(text_img, dpi), 3, dpi, langs)

    def ocr_cells():
        if not crops:
            return []
        return engine.tsv(imageops.tiff_stack(crops, dpi), 6, dpi, langs)

    with ThreadPoolExecutor(max_workers=2) as pool:
        f_text = pool.submit(ocr_text)
        f_cells = pool.submit(ocr_cells)
        text_words = f_text.result()
        cell_words = f_cells.result()
    step(0.85)

    # --- строки
    text_lines = _lines_from_words(text_words, key_prefix=("text",))
    cell_lines: dict[int, list[Line]] = {}
    by_page: dict[int, list[TWord]] = {}
    for t in cell_words:
        by_page.setdefault(t.page, []).append(t)
    for job_i, (ti, cell, off) in enumerate(cell_jobs):
        ws = by_page.get(job_i + 1, [])
        if ws:
            cell_lines[id(cell)] = _lines_from_words(ws, offset=off, key_prefix=("cell", job_i))

    def in_any_table(s: tbl.Segment):
        for t in tables:
            if t.x0 <= s.x0 and s.x1 <= t.x1 and t.y0 <= s.y0 <= t.y1:
                return t
        return None

    # строки, слитые Tesseract из разных колонок, режем сразу и меряем
    text_lines = [seg for ln in text_lines for seg in layout.split_line(ln)]
    for k in list(cell_lines):
        cell_lines[k] = [seg for ln in cell_lines[k] for seg in layout.split_line(ln)]
    for ln in text_lines:
        layout.measure_line(ln, clean_ink)
    for v in cell_lines.values():
        for ln in v:
            layout.measure_line(ln, clean_ink)
    xhs = [ln.xh for ln in text_lines + [l for v in cell_lines.values() for l in v]
           if len(ln.words) >= 3]
    page_xh = float(median(xhs)) if xhs else xh
    # у коротких строк высота меряется ненадёжно: сверяем с соседями
    for group in [text_lines] + list(cell_lines.values()):
        _smooth_xh(group, page_xh)
    text_lines = _clean_lines(text_lines, clean_ink, page_xh, zone)
    for k in list(cell_lines):
        cell_lines[k] = _clean_lines(cell_lines[k], clean_ink, page_xh, zone)

    fills = _merge_fills(fills, page_xh)
    text_fills = [s for s in fills if in_any_table(s) is None]
    text_lines = _attach_fills(text_lines, text_fills, page_xh)
    for t in tables:
        for cell in t.cells:
            cf = [s for s in fills if cell.x0 < s.x0 and s.x1 < cell.x1 and cell.y0 < s.y0 < cell.y1]
            if cf:
                cell_lines[id(cell)] = _attach_fills(cell_lines.get(id(cell), []), cf, page_xh)

    all_lines = list(text_lines)
    for v in cell_lines.values():
        all_lines.extend(v)
    _mark_underlines(all_lines, unders)
    layout.mark_bold(all_lines, clean_ink)
    layout.fix_words(all_lines)

    # --- границы содержимого
    xs0 = [ln.x0 for ln in text_lines] + [t.x0 for t in tables]
    xs1 = [ln.x1 for ln in text_lines] + [t.x1 for t in tables]
    ys0 = [ln.y0 for ln in text_lines] + [t.y0 for t in tables]
    ys1 = [ln.y1 for ln in text_lines] + [t.y1 for t in tables]
    if xs0:
        L = float(np.percentile(xs0, 3)) if len(xs0) > 10 else float(min(xs0))
        R = float(np.percentile(xs1, 97)) if len(xs1) > 10 else float(max(xs1))
        if tables:
            L = min(L, min(t.x0 for t in tables))
            R = max(R, max(t.x1 for t in tables))
        body = (int(L), int(min(ys0)), int(R), int(max(ys1)))
    else:
        L, R = W * 0.1, W * 0.9
        body = (int(L), int(H * 0.1), int(R), int(H * 0.9))

    # --- раскладка
    elements: list = []
    elements.extend(layout.layout_region(text_lines, L, R))
    cell_pad = 0.19 / 2.54 * dpi          # поле ячейки Word по умолчанию
    for t in tables:
        for cell in t.cells:
            lines = cell_lines.get(id(cell), [])
            cl, cr = cell.x0 + cell_pad, cell.x1 - cell_pad
            if lines:
                # текст может немного заходить за стандартные поля
                cl = min(cl, min(ln.x0 for ln in lines))
                long_r = max(ln.x1 for ln in lines)
                if long_r > cr or (len(lines) >= 3 and cr - long_r < 1.5 * xh):
                    cr = long_r
            cell.paragraphs = layout.segment_paragraphs(lines, cl, cr, cell=True)
            _assign_sizes(cell.paragraphs, dpi)
        elements.append(t)
    _drop_page_numbers(elements, H)
    _harmonize_alignment([e for e in elements if isinstance(e, Para)], L)
    for t in tables:
        for cell in t.cells:
            _harmonize_alignment(cell.paragraphs, None)
    paras = _all_paras(elements)
    _assign_sizes(paras, dpi)
    body_size = 12.0
    elements.sort(key=lambda e: e.y0)

    # интервалы между элементами (в основном потоке и внутри ячеек/колонок)
    _space_before(elements, dpi, None)
    for el in elements:
        if isinstance(el, tbl.Table):
            for cell in el.cells:
                _space_before(cell.paragraphs, dpi, None)
                if cell.paragraphs:
                    cell.paragraphs[0].space_before = 0.0
        elif isinstance(el, ColumnGroup):
            for cell in el.cells:
                _space_before(cell, dpi, el.y0)
    return PageResult(index, W, H, dpi, elements, body, body_size, rot)


def _harmonize_alignment(paras: list[Para], L: float | None) -> None:
    """Однострочные абзацы подстраиваем под соседей.

    Строка с обычной «красной строкой», случайно оказавшаяся по центру,
    становится обычным абзацем; в документе «по ширине» однострочные
    абзацы тоже делаются по ширине."""
    multi = [p for p in paras if len(p.lines) >= 2 and p.segments is None]
    firsts = [p.first for p in multi if p.first > 0]
    if L is not None and firsts:
        ind = median(firsts)
        for p in paras:
            if len(p.lines) == 1 and p.align == "center" and p.segments is None:
                xh = p.lines[0].xh or 20
                if abs((p.lines[0].x0 - L) - ind) < 1.0 * xh:
                    p.align = "left"
                    p.first = ind
                    p.left = 0.0
    if not multi:
        return
    just = sum(p.align == "justify" for p in multi)
    if just < 0.6 * len(multi):
        return
    for p in paras:
        if len(p.lines) == 1 and p.align == "left" and p.segments is None and p.left == 0:
            p.align = "justify"


def _drop_page_numbers(elements: list, H: int) -> None:
    """Убирает номера страниц и колонтитулы вида «- 2 -», «Страница 2 из 5»."""
    pat = re.compile(r"^(стр\.?|страница|лист|page)?\s*[-–—]?\s*\d{1,4}\s*[-–—]?\s*(из\s*\d+)?$", re.I)
    for el in list(elements):
        if not isinstance(el, Para) or len(el.lines) != 1:
            continue
        txt = el.lines[0].text.strip()
        if el.y1 < 0.08 * H or el.y0 > 0.92 * H:
            if pat.match(txt):
                elements.remove(el)


# --------------------------------------------------------------------------

@dataclass
class SectionBreak:
    page: PageResult


def merge_pages(pages: list[PageResult]) -> list:
    """Склеивает страницы в один поток: переносы таблиц и абзацев.

    Если ориентация листа меняется, вставляется SectionBreak."""
    flow: list = []
    prev_landscape = None
    for page in pages:
        landscape = page.width_px > page.height_px
        els = list(page.elements)
        if prev_landscape is not None and landscape != prev_landscape:
            flow.append(SectionBreak(page))
        elif flow and els:
            last, first = flow[-1], els[0]
            if isinstance(last, tbl.Table) and isinstance(first, tbl.Table) and \
                    _same_columns(last, first):
                _append_table(last, first)
                els = els[1:]
            elif isinstance(last, Para) and isinstance(first, Para) and _continues(last, first):
                last.lines.extend(first.lines)
                if first.align == "justify":
                    last.align = "justify"
                els = els[1:]
            else:
                # промежуток до первого элемента новой страницы — это поле листа
                first.space_before = 0.0
        flow.extend(els)
        prev_landscape = landscape
    return flow


def _same_columns(a: tbl.Table, b: tbl.Table) -> bool:
    if a.ncols != b.ncols:
        return False
    wa = a.x1 - a.x0
    wb = b.x1 - b.x0
    if abs(wa - wb) > 0.05 * max(wa, wb):
        return False
    for xa, xb in zip(a.xs, b.xs):
        if abs((xa - a.x0) / wa - (xb - b.x0) / wb) > 0.03:
            return False
    return True


def _append_table(a: tbl.Table, b: tbl.Table) -> None:
    # повтор шапки на новой странице не нужен
    def row_text(t, r):
        cells = [c for c in t.cells if c.r0 == r]
        return [" ".join(layout.para_text(p) for p in c.paragraphs) for c in cells]

    skip_first = b.nrows > 1 and row_text(a, 0) == row_text(b, 0)
    shift = a.nrows - (1 if skip_first else 0)
    offset_y = a.ys[-1] - b.ys[1 if skip_first else 0]
    for c in b.cells:
        if skip_first and c.r0 == 0:
            continue
        c.r0 += shift
        c.r1 += shift
        a.cells.append(c)
    new_ys = b.ys[(2 if skip_first else 1):]
    a.ys = a.ys + [y + offset_y for y in new_ys]
    # колонки — по первой таблице
    a.cells.sort(key=lambda c: (c.r0, c.c0))


def _continues(a: Para, b: Para) -> bool:
    if a.segments is not None or b.segments is not None:
        return False
    text_a = a.lines[-1].text.rstrip()
    text_b = b.lines[0].text.lstrip()
    if not text_a or not text_b:
        return False
    if text_a[-1] in ".!?:;»\"":
        return False
    if b.first > 0 or b.align in ("center", "right"):
        return False
    return bool(re.match(r"[a-zа-яё(«\d]", text_b)) and abs(a.size - b.size) < 1


# --------------------------------------------------------------------------

def convert(path: str, out_path: str, opts: Options | None = None,
            progress: ProgressFn | None = None, engine: Engine | None = None) -> str:
    from . import docxwriter

    opts = opts or Options()
    engine = engine or Engine(opts.langs)
    report = progress or (lambda f, m: None)
    report(0.0, "Открываю файл…")
    src = imageops.PageSource(path)
    try:
        n = src.count
        if n == 0:
            raise ValueError("В файле нет страниц")
        workers = opts.workers or max(1, min(4, (os.cpu_count() or 2)))
        workers = min(workers, n)
        done = 0
        results: list[PageResult | None] = [None] * n
        fractions = [0.0] * n
        lock = threading.Lock()

        def stepper(i):
            def step(f):
                with lock:
                    fractions[i] = f
                    total = sum(fractions) / n
                report(0.02 + 0.93 * total, f"Распознаю страницы: {done} из {n} готово")
            return step

        report(0.02, f"Распознаю страницы: 0 из {n} готово")
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(process_page, engine, src, i, opts, stepper(i)): i
                       for i in range(n)}
            try:
                for fut in _as_completed(futures):
                    i = futures[fut]
                    try:
                        results[i] = fut.result()
                    except (OcrError, ValueError, cv2.error, MemoryError) as exc:
                        # одна плохая страница не должна губить весь документ
                        results[i] = _failed_page(i, exc)
                    done += 1
                    with lock:
                        fractions[i] = 1.0
                        total = sum(fractions) / n
                    report(0.02 + 0.93 * total, f"Распознаю страницы: {done} из {n} готово")
            except BaseException:
                engine.cancel()
                for f in futures:
                    f.cancel()
                raise
        report(0.96, "Собираю документ Word…")
        pages = [r for r in results if r is not None]
        finalize_sizes(pages)
        docxwriter.write(pages, merge_pages(pages), out_path,
                         title=os.path.splitext(os.path.basename(path))[0])
        report(1.0, "Готово")
        return out_path
    finally:
        src.close()


def _failed_page(index: int, exc: Exception) -> PageResult:
    text = f"[Страница {index + 1} не распознана: {exc}]"
    line = Line([Word(text, 0, 0, 100, 30)], xh=14.0, base=30.0)
    para = Para([line], align="left", size=12.0)
    return PageResult(index, 2480, 3508, 300.0, [para], (295, 236, 2303, 3272))


def _as_completed(futures):
    from concurrent.futures import as_completed
    return as_completed(futures)


__all__ = ["convert", "Options", "Cancelled", "process_page", "merge_pages", "SectionBreak"]
