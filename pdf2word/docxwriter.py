"""Запись распознанной структуры в .docx (python-docx)."""

from __future__ import annotations

from statistics import median

from docx import Document
from docx.enum.section import WD_ORIENT, WD_SECTION
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Emu, Pt

from . import layout
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

    lefts = [p.body[0] / p.dpi for p in pages]
    rights = [(p.width_px - p.body[2]) / p.dpi for p in pages]
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
    for pos, kind in p.tabs:
        fmt.tab_stops.add_tab_stop(ctx.emu(pos), TAB[kind])
    size = None if abs(p.size - ctx.body_size) < 0.25 else p.size
    for text, bold, underline in layout.para_runs(p):
        run = par.add_run(text)
        if bold:
            run.bold = True
        if underline:
            run.underline = True
        if size:
            run.font.size = Pt(size)


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
        tblW = OxmlElement("w:tblW")
        tblPr.append(tblW)
    tblW.set(qn("w:w"), str(sum(widths_tw)))
    tblW.set(qn("w:type"), "dxa")


def _cell_margins(table, tw: int = CELL_MARGIN_TW):
    tblPr = table._tbl.tblPr
    mar = tblPr.find(qn("w:tblCellMar"))
    if mar is None:
        mar = OxmlElement("w:tblCellMar")
        tblPr.append(mar)
    for side in ("left", "right"):
        el = mar.find(qn(f"w:{side}"))
        if el is None:
            el = OxmlElement(f"w:{side}")
            mar.append(el)
        el.set(qn("w:w"), str(tw))
        el.set(qn("w:type"), "dxa")


def _no_borders(table):
    tblPr = table._tbl.tblPr
    borders = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        el = OxmlElement(f"w:{edge}")
        el.set(qn("w:val"), "nil")
        borders.append(el)
    old = tblPr.find(qn("w:tblBorders"))
    if old is not None:
        tblPr.remove(old)
    tblPr.append(borders)


def _cell_widths_merged(cell_obj, width_tw: int):
    cell_obj.width = Emu(int(width_tw * 635))


def _write_cell(cell_obj, paras: list[Para], ctx: Ctx, width_px: float):
    first = True
    for p in paras:
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
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    _cell_margins(table)
    _set_col_widths(table, widths_tw)
    for c in t.cells:
        a = table.cell(c.r0, c.c0)
        if c.r1 - c.r0 > 1 or c.c1 - c.c0 > 1:
            a = a.merge(table.cell(c.r1 - 1, c.c1 - 1))
            _cell_widths_merged(a, sum(widths_tw[c.c0:c.c1]))
    for c in t.cells:
        cell_obj = table.cell(c.r0, c.c0)
        _write_cell(cell_obj, c.paragraphs, ctx, (c.x1 - c.x0) * scale)
        if c.paragraphs:
            top_gap = c.paragraphs[0].y0 - c.y0
            bottom_gap = c.y1 - c.paragraphs[-1].y1
            h = c.y1 - c.y0
            if h > 0 and top_gap > 0.2 * h and abs(top_gap - bottom_gap) < 0.25 * h:
                cell_obj.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
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
