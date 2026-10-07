"""Запись распознанной структуры в .docx (python-docx)."""

from __future__ import annotations

import math
from statistics import median

from docx import Document
from docx.enum.section import WD_ORIENT, WD_SECTION
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_ROW_HEIGHT_RULE, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Emu, Pt

from . import layout, metrics
from . import tables as tbl
from .layout import ColumnGroup, Para

FONT = "Times New Roman"
ALIGN = {
    "left": WD_ALIGN_PARAGRAPH.LEFT,
    "center": WD_ALIGN_PARAGRAPH.CENTER,
    "right": WD_ALIGN_PARAGRAPH.RIGHT,
    "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
}
TAB = {"left": WD_TAB_ALIGNMENT.LEFT, "right": WD_TAB_ALIGNMENT.RIGHT,
       "center": WD_TAB_ALIGNMENT.CENTER}
CELL_MARGIN_TW = 57           # поля ячеек 0,1 см (у Word по умолчанию 0,19 см) —
                              # меньше риск, что слово не влезет и перенесётся

PAPER = {  # дюймы
    "A4": (8.27, 11.69),
    "A3": (11.69, 16.54),
    "A5": (5.83, 8.27),
    "Letter": (8.5, 11.0),
    "Legal": (8.5, 14.0),
}


class Ctx:
    def __init__(self, dpi: float, body_size: float):
        self.dpi = dpi
        self.body_size = body_size

    def emu(self, px: float) -> Emu:
        return Emu(int(round(px / self.dpi * 914400)))

    def tw(self, px: float) -> int:
        return int(round(px / self.dpi * 1440))

    def pt(self, px: float) -> float:
        return px / self.dpi * 72.0


# --------------------------------------------------------------------------

def _set_fonts(rpr_parent, size: float | None = None):
    rpr = rpr_parent.get_or_add_rPr()
    fonts = rpr.find(qn("w:rFonts"))
    if fonts is None:
        fonts = OxmlElement("w:rFonts")
        rpr.insert(0, fonts)
    for attr in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        fonts.set(qn(attr), FONT)
    lang = rpr.find(qn("w:lang"))
    if lang is None:
        lang = OxmlElement("w:lang")
        rpr.append(lang)
    lang.set(qn("w:val"), "ru-RU")


def _setup_styles(doc, body_size: float):
    normal = doc.styles["Normal"]
    normal.font.name = FONT
    normal.font.size = Pt(body_size)
    _set_fonts(normal.element)
    pf = normal.paragraph_format
    pf.space_before = Pt(0)
    pf.space_after = Pt(0)
    pf.line_spacing = 1.0
    try:
        grid = doc.styles["Table Grid"]
        grid.font.name = FONT
    except KeyError:
        pass


def _paper(width_in: float, height_in: float) -> tuple[float, float]:
    """Подгоняет размер листа к стандартному, если он близок."""
    short, long_ = sorted((width_in, height_in))
    for w, h in PAPER.values():
        if abs(short - w) / w < 0.04 and abs(long_ - h) / h < 0.04:
            short, long_ = w, h
            break
    return (long_, short) if width_in > height_in else (short, long_)


def _apply_section(section, pages, ctx: Ctx):
    page = pages[0]
    w_in, h_in = _paper(page.width_px / page.dpi, page.height_px / page.dpi)
    landscape = w_in > h_in
    section.orientation = WD_ORIENT.LANDSCAPE if landscape else WD_ORIENT.PORTRAIT
    section.page_width = Emu(int(w_in * 914400))
    section.page_height = Emu(int(h_in * 914400))

    def med(vals, default):
        vals = [v for v in vals if v is not None]
        return median(vals) if vals else default

    # левое и правое поля — по заполненным страницам: на последней странице
    # с одной подписью текст обычно не доходит до правого края
    from .pipeline import _all_paras, _text_len
    chars = [sum(_text_len(q) for q in _all_paras(p.elements)) for p in pages]
    full = [p for p, n in zip(pages, chars) if n >= 0.5 * max(chars)] or pages
    lefts = [p.body[0] / p.dpi for p in full]
    rights = [(p.width_px - p.body[2]) / p.dpi for p in full]
    tops = [p.body[1] / p.dpi for p in pages]
    # нижнее поле: по самой заполненной странице
    bottoms = [(p.height_px - p.body[3]) / p.dpi for p in pages]

    def clamp(v, lo=0.3, hi=2.0):
        return max(lo, min(hi, v))

    left = clamp(med(lefts, 1.0) - 0.02)
    right = clamp(med(rights, 0.6) - 0.05)
    top = clamp(min(tops) - 0.05 if tops else 0.8, 0.3, 1.6)
    bottom = clamp(min(bottoms) - 0.05 if bottoms else 0.8, 0.3, 1.6)
    section.left_margin = Emu(int(left * 914400))
    section.right_margin = Emu(int(right * 914400))
    section.top_margin = Emu(int(top * 914400))
    section.bottom_margin = Emu(int(bottom * 914400))
    section.header_distance = Emu(int(min(0.5, top / 2) * 914400))
    section.footer_distance = Emu(int(min(0.5, bottom / 2) * 914400))


# --------------------------------------------------------------------------

def _fill_paragraph(par, p: Para, ctx: Ctx, max_indent_px: float | None = None):
    fmt = par.paragraph_format
    fmt.alignment = ALIGN.get(p.align, WD_ALIGN_PARAGRAPH.LEFT)
    left = p.left
    first = p.first
    if max_indent_px is not None:
        left = min(left, max_indent_px * 0.8)
        first = max(-left, min(first, max_indent_px * 0.6))
    if left > 0:
        fmt.left_indent = ctx.emu(left)
    if abs(first) > 0:
        fmt.first_line_indent = ctx.emu(first)
    if p.space_before > 0:
        fmt.space_before = Pt(round(min(ctx.pt(p.space_before), 200.0), 1))
    if p.spacing and abs(p.spacing - 1.0) > 0.01:
        fmt.line_spacing = p.spacing          # полуторный, двойной интервал
    for pos, kind in p.tabs:
        fmt.tab_stops.add_tab_stop(ctx.emu(pos), TAB[kind])
    size = None if abs(p.size - ctx.body_size) < 0.25 else p.size
    for text, bold, underline in layout.para_runs(p):
        parts = text.split("\u00ad")
        run = par.add_run(parts[0])
        for part in parts[1:]:
            # мягкий перенос: дефис появится только если слово разорвётся на краю
            run._r.append(OxmlElement("w:softHyphen"))
            t = OxmlElement("w:t")
            t.text = part
            t.set(qn("xml:space"), "preserve")
            run._r.append(t)
        if bold:
            run.bold = True
        if underline:
            run.underline = True
        if size:
            run.font.size = Pt(size)
    if size:
        _mark_size(par, size)


def _mark_size(par, size: float) -> None:
    """Кегль знака абзаца: от него зависит высота пустой строки и строки таблицы."""
    pPr = par._p.get_or_add_pPr()
    rPr = pPr.find(qn("w:rPr"))
    if rPr is None:
        rPr = OxmlElement("w:rPr")
        sect = pPr.find(qn("w:sectPr"))
        if sect is not None:
            sect.addprevious(rPr)
        else:
            pPr.append(rPr)
    for tag in ("w:sz", "w:szCs"):
        el = rPr.find(qn(tag))
        if el is None:
            el = OxmlElement(tag)
            rPr.append(el)
        el.set(qn("w:val"), str(int(round(size * 2))))


def _empty_cells_size(table, sizes: list[float], ctx: Ctx) -> None:
    """Пустые ячейки — тем же кеглем, что текст таблицы, иначе строки
    выйдут выше, чем на скане."""
    if not sizes:
        return
    size = median(sizes)
    if abs(size - ctx.body_size) < 0.25:
        return
    for row in table.rows:
        for cell in row.cells:
            pars = cell.paragraphs
            if len(pars) == 1 and not pars[0].text:
                _mark_size(pars[0], size)


def _set_col_widths(table, widths_tw: list[int]):
    tbl_el = table._tbl
    grid = tbl_el.tblGrid
    cols = grid.findall(qn("w:gridCol"))
    for col, w in zip(cols, widths_tw):
        col.set(qn("w:w"), str(max(60, w)))
    for row in table.rows:
        for idx, cell in enumerate(row.cells):
            if idx < len(widths_tw):
                cell.width = Emu(int(widths_tw[idx] * 635))
    tblPr = tbl_el.tblPr
    tblW = tblPr.find(qn("w:tblW"))
    if tblW is None:
        tblW = _put_tblpr(tblPr, OxmlElement("w:tblW"))
    tblW.set(qn("w:w"), str(sum(widths_tw)))
    tblW.set(qn("w:type"), "dxa")


TBLPR_ORDER = ["tblStyle", "tblpPr", "tblOverlap", "bidiVisual", "tblStyleRowBandSize",
               "tblStyleColBandSize", "tblW", "jc", "tblCellSpacing", "tblInd", "tblBorders",
               "shd", "tblLayout", "tblCellMar", "tblLook", "tblCaption", "tblDescription"]


def _put_tblpr(tblPr, el):
    """Вставляет элемент в w:tblPr в порядке, которого требует схема Word."""
    name = el.tag.split("}")[1]
    old = tblPr.find(qn(f"w:{name}"))
    if old is not None:
        tblPr.remove(old)
    later = TBLPR_ORDER[TBLPR_ORDER.index(name) + 1:]
    for child in tblPr:
        if child.tag.split("}")[1] in later:
            child.addprevious(el)
            return el
    tblPr.append(el)
    return el


def _cell_margins(table, tw: int = CELL_MARGIN_TW):
    tblPr = table._tbl.tblPr
    mar = tblPr.find(qn("w:tblCellMar"))
    if mar is None:
        mar = _put_tblpr(tblPr, OxmlElement("w:tblCellMar"))
    for side in ("left", "right"):
        el = mar.find(qn(f"w:{side}"))
        if el is None:
            el = OxmlElement(f"w:{side}")
            mar.append(el)
        el.set(qn("w:w"), str(tw))
        el.set(qn("w:type"), "dxa")


def _cell_borders(cell_obj, right: bool = False):
    """Ячейка без рамки (правая граница — это левая граница самой таблицы)."""
    tcPr = cell_obj._tc.get_or_add_tcPr()
    borders = tcPr.find(qn("w:tcBorders"))
    if borders is None:
        borders = OxmlElement("w:tcBorders")
        # порядок в tcPr: tcW, gridSpan, vMerge, tcBorders, shd, ..., vAlign
        after = [qn("w:tcW"), qn("w:gridSpan"), qn("w:hMerge"), qn("w:vMerge")]
        anchor = None
        for child in tcPr:
            if child.tag in after:
                anchor = child
        if anchor is not None:
            anchor.addnext(borders)
        else:
            tcPr.insert(0, borders)
    for edge in ("top", "left", "bottom", "right"):
        el = OxmlElement(f"w:{edge}")
        if edge == "right" and right:
            el.set(qn("w:val"), "single")
            el.set(qn("w:sz"), "4")
            el.set(qn("w:color"), "000000")
        else:
            el.set(qn("w:val"), "nil")
        borders.append(el)


def _no_borders(table):
    tblPr = table._tbl.tblPr
    borders = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        el = OxmlElement(f"w:{edge}")
        el.set(qn("w:val"), "nil")
        borders.append(el)
    _put_tblpr(tblPr, borders)


def _cell_widths_merged(cell_obj, width_tw: int):
    cell_obj.width = Emu(int(width_tw * 635))


def _fit_size(p: Para, ctx: Ctx, width_px: float) -> None:
    """Надпись, которая на скане умещалась в ячейке одной строкой, не должна
    переноситься в Word: при нехватке места чуть уменьшаем кегль (до 12 %)."""
    if len(p.lines) != 1 or p.segments is not None or not p.lines[0].words:
        return
    ws = p.lines[0].words
    em = sum(metrics.advance_width(w.text, w.bold) for w in ws) + metrics.SPACE * (len(ws) - 1)
    avail = width_px - 2 * CELL_MARGIN_TW / 1440 * ctx.dpi - p.left - max(0.0, p.first)
    need = em * p.size * ctx.dpi / 72.0
    if need > avail > 0:
        size = math.floor(2 * p.size * avail / need) / 2      # шаг 0,5 пт
        if size >= 0.88 * p.size:
            p.size = size


def _write_cell(cell_obj, paras: list[Para], ctx: Ctx, width_px: float):
    first = True
    for p in paras:
        _fit_size(p, ctx, width_px)
        if first:
            par = cell_obj.paragraphs[0]
            first = False
        else:
            par = cell_obj.add_paragraph()
        _fill_paragraph(par, p, ctx, max_indent_px=width_px)


def _add_table(doc, t: tbl.Table, ctx: Ctx, max_width_px: float):
    widths_px = [t.xs[i + 1] - t.xs[i] for i in range(t.ncols)]
    total = sum(widths_px)
    scale = min(1.0, max_width_px / total) if total > 0 else 1.0
    widths_tw = [ctx.tw(w * scale) for w in widths_px]
    table = doc.add_table(rows=t.nrows, cols=t.ncols)
    try:
        table.style = doc.styles["Table Grid"]
    except KeyError:
        pass
    table.autofit = False
    where, indent = getattr(t, "place", ("center", 0))
    table.alignment = {"left": WD_TABLE_ALIGNMENT.LEFT, "right": WD_TABLE_ALIGNMENT.RIGHT}.get(
        where, WD_TABLE_ALIGNMENT.CENTER)
    if where == "left" and indent > 0:
        ind = OxmlElement("w:tblInd")
        ind.set(qn("w:w"), str(ctx.tw(min(indent, max(0.0, max_width_px - total)))))
        ind.set(qn("w:type"), "dxa")
        _put_tblpr(table._tbl.tblPr, ind)
    _cell_margins(table)
    _set_col_widths(table, widths_tw)
    if not t.beside_text:
        # строки не ниже, чем на скане: пустые строки бланка остаются
        # местом для записи, высокая шапка — высокой
        for r, row in enumerate(table.rows):
            h = t.ys[r + 1] - t.ys[r]
            if h > 0:
                row.height = ctx.emu(0.97 * h)
                row.height_rule = WD_ROW_HEIGHT_RULE.AT_LEAST
    for c in t.cells:
        a = table.cell(c.r0, c.c0)
        if c.r1 - c.r0 > 1 or c.c1 - c.c0 > 1:
            a = a.merge(table.cell(c.r1 - 1, c.c1 - 1))
            _cell_widths_merged(a, sum(widths_tw[c.c0:c.c1]))
    _empty_cells_size(table, [p.size for c in t.cells for p in c.paragraphs], ctx)
    for c in t.cells:
        cell_obj = table.cell(c.r0, c.c0)
        _write_cell(cell_obj, c.paragraphs, ctx, (c.x1 - c.x0) * scale)
        if c.borderless:
            _cell_borders(cell_obj, right=True)
        if c.valign:
            cell_obj.vertical_alignment = {
                "top": WD_CELL_VERTICAL_ALIGNMENT.TOP, "bottom": WD_CELL_VERTICAL_ALIGNMENT.BOTTOM,
                "center": WD_CELL_VERTICAL_ALIGNMENT.CENTER}[c.valign]
            continue
        if c.paragraphs:
            top_gap = c.paragraphs[0].y0 - c.y0
            bottom_gap = c.y1 - c.paragraphs[-1].y1
            h = c.y1 - c.y0
            if h > 0 and top_gap > 0.2 * h and abs(top_gap - bottom_gap) < 0.25 * h:
                cell_obj.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            elif h > 0 and top_gap > 0.4 * h and bottom_gap < 0.2 * h:
                cell_obj.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.BOTTOM
    return table


def _add_columns(doc, g: ColumnGroup, ctx: Ctx, max_width_px: float):
    widths_px = [b - a for a, b in g.bounds]
    total = sum(widths_px)
    if 0 < total < max_width_px:
        # колонки растягиваем до полной ширины текста (запас справа)
        widths_px[-1] += max_width_px - total
        total = max_width_px
    scale = min(1.0, max_width_px / total) if total > 0 else 1.0
    widths_tw = [ctx.tw(w * scale) for w in widths_px]
    table = doc.add_table(rows=1, cols=len(widths_tw))
    table.autofit = False
    _no_borders(table)
    _cell_margins(table)
    _set_col_widths(table, widths_tw)
    _empty_cells_size(table, [p.size for paras in g.cells for p in paras], ctx)
    for k, paras in enumerate(g.cells):
        _write_cell(table.cell(0, k), paras, ctx, widths_px[k] * scale)
    return table


def _spacer(doc, ctx: Ctx, gap_px: float):
    par = doc.add_paragraph()
    fmt = par.paragraph_format
    h = ctx.pt(gap_px)
    if h >= 4:
        fmt.line_spacing = Pt(min(h, 400))
        from docx.enum.text import WD_LINE_SPACING
        fmt.line_spacing_rule = WD_LINE_SPACING.EXACTLY
    else:
        fmt.line_spacing = Pt(1)
        from docx.enum.text import WD_LINE_SPACING
        fmt.line_spacing_rule = WD_LINE_SPACING.EXACTLY
    return par


# --------------------------------------------------------------------------

def write(pages, flow, out_path: str, title: str = ""):
    from .pipeline import SectionBreak

    doc = Document()
    if not pages:
        doc.save(out_path)
        return
    sizes = [p.body_size for p in pages]
    body_size = median(sizes)
    dpi = median([p.dpi for p in pages])
    ctx = Ctx(dpi, body_size)
    _setup_styles(doc, body_size)
    zoom = doc.settings.element.find(qn("w:zoom"))
    if zoom is not None and zoom.get(qn("w:percent")) is None:
        zoom.set(qn("w:percent"), "100")
    doc.core_properties.title = title
    doc.core_properties.author = "PDF в Word"

    # группы страниц с одинаковой ориентацией → разделы
    groups = [[pages[0]]]
    for p in pages[1:]:
        if (p.width_px > p.height_px) == (groups[-1][-1].width_px > groups[-1][-1].height_px):
            groups[-1].append(p)
        else:
            groups.append([p])
    section = doc.sections[0]
    _apply_section(section, groups[0], ctx)
    group_iter = iter(groups[1:])

    def text_width_px(sec):
        w = sec.page_width - sec.left_margin - sec.right_margin
        return w / 914400 * dpi

    max_w = text_width_px(section)
    body = doc.element.body
    # убираем пустой абзац шаблона, если он есть
    for par in list(doc.paragraphs):
        if not par.text.strip():
            body.remove(par._p)

    prev_kind = None
    for el in flow:
        if isinstance(el, SectionBreak):
            grp = next(group_iter, None)
            section = doc.add_section(WD_SECTION.NEW_PAGE)
            if grp:
                _apply_section(section, grp, ctx)
            max_w = text_width_px(section)
            prev_kind = None
            continue
        if isinstance(el, Para):
            par = doc.add_paragraph()
            _fill_paragraph(par, el, ctx, max_indent_px=max_w)
            prev_kind = "para"
        elif isinstance(el, (tbl.Table, ColumnGroup)):
            gap = getattr(el, "space_before", 0.0) or 0.0
            if prev_kind in ("table", "cols"):
                _spacer(doc, ctx, max(gap, 2.0))
            elif gap > 0.6 * ctx.body_size * dpi / 72:
                _spacer(doc, ctx, gap)
            if isinstance(el, tbl.Table):
                _add_table(doc, el, ctx, max_w)
                prev_kind = "table"
            else:
                _add_columns(doc, el, ctx, max_w)
                prev_kind = "cols"
    # Word требует абзац после таблицы в конце документа
    if prev_kind in ("table", "cols"):
        _spacer(doc, ctx, 2.0)
    doc.save(out_path)
