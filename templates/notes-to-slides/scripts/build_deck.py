"""Build a designed 16:9 PowerPoint deck from a slide plan (deck.json).

Usage:
  python3 build_deck.py <deck.json> <out.pptx>      build the deck, print fit warnings
  python3 build_deck.py --text <deck.pptx>          print every slide's text and notes (for checking)

Needs python-pptx (pip install python-pptx). The design lives here so every
deck is consistent: one palette, dark title and closing slides, light content
slides, a serif heading font with a sans body font, real titles (they show in
PowerPoint's outline and to screen readers), speaker notes in the notes pane,
native charts. See SKILL.md step 3 for the deck.json format.
"""
import json
import math
import sys

from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION, XL_LEGEND_POSITION
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Emu, Inches, Pt

PALETTES = {  # dark, light background, accent, muted text
    "midnight": ("1E2761", "F4F6FB", "D9822B", "5A6275"),
    "forest": ("23402A", "F3F6F1", "C8963E", "5B6858"),
    "terracotta": ("7A2E22", "FAF6F3", "2F6F73", "6E5F59"),
    "ocean": ("0B3C5D", "F2F7FA", "E07A5F", "52646F"),
    "charcoal": ("2B3035", "F5F5F4", "C0392B", "5F6468"),
    "berry": ("5A1F3A", "FAF5F7", "2E7D6B", "6B5862"),
}
HEAD_FONT, BODY_FONT = "Cambria", "Calibri"
W, H = Inches(13.333), Inches(7.5)
M = Inches(0.6)  # outer margin
TITLE_TOP, TITLE_H = Inches(0.35), Inches(1.1)
BODY_TOP = Inches(1.65)
WARN = []


def E(v):
    """Whole EMUs: a fractional coordinate makes a file PowerPoint refuses."""
    return Emu(int(round(v)))


def rgb(h):
    return RGBColor.from_string(h)


def fits(text, width, height, size, line=1.18, em=0.5):
    """Rough check that `text` at `size` pt fits a box (average glyph ~0.5 em)."""
    cpl = max(1, int(Emu(width).pt / (size * em)))
    lines = sum(max(1, math.ceil(len(p) / cpl)) for p in str(text).split("\n"))
    return lines * size * line <= Emu(height).pt


def text_box(slide, x, y, w, h, paras, size, color, font=BODY_FONT, bold=False, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP,
             min_size=None, where="", space_after=6, bullets=False):
    """paras: list of str or (str, {"bold":..., "color":..., "size":...})."""
    flat = "\n".join(p if isinstance(p, str) else p[0] for p in paras)
    if min_size:
        while size > min_size and not fits(flat, w - Inches(0.1), h, size):
            size -= 1
        if not fits(flat, w - Inches(0.1), h, size):
            WARN.append(f"{where}: text may overflow at {size}pt; shorten it")
    tb = slide.shapes.add_textbox(E(x), E(y), E(w), E(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = 0
    tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = anchor
    for i, p in enumerate(paras):
        t, o = (p, {}) if isinstance(p, str) else p
        para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        para.alignment = align
        para.space_after = Pt(space_after)
        if bullets:
            bullet(para, color if not o.get("bullet_color") else o["bullet_color"])
        r = para.add_run()
        r.text = t
        f = r.font
        f.name, f.size, f.bold = o.get("font", font), Pt(o.get("size", size)), o.get("bold", bold)
        f.italic = o.get("italic", False)
        f.color.rgb = rgb(o.get("color", color))
    return tb


def bullet(para, color):
    """A real bullet (not a typed character), with a hanging indent."""
    from pptx.oxml.ns import qn
    from lxml import etree

    pPr = para._p.get_or_add_pPr()
    pPr.set("marL", str(Inches(0.3)))
    pPr.set("indent", str(-Inches(0.3)))
    for tag in ("a:buClr", "a:buFont", "a:buChar", "a:buNone"):
        for el in pPr.findall(qn(tag)):
            pPr.remove(el)
    clr = etree.SubElement(pPr, qn("a:buClr"))
    etree.SubElement(clr, qn("a:srgbClr")).set("val", color)
    etree.SubElement(pPr, qn("a:buFont")).set("typeface", "Arial")
    etree.SubElement(pPr, qn("a:buChar")).set("char", "•")


def shape(slide, kind, x, y, w, h, fill, line=None):
    s = slide.shapes.add_shape(kind, E(x), E(y), E(w), E(h))
    s.fill.solid()
    s.fill.fore_color.rgb = rgb(fill)
    if line:
        s.line.color.rgb = rgb(line)
        s.line.width = Pt(1)
    else:
        s.line.fill.background()
    s.shadow.inherit = False
    return s


def new_slide(prs, pal, dark, title, where, title_size=34):
    slide = prs.slides.add_slide(prs.slide_layouts[5])  # Title Only: keeps a real title placeholder
    bg = slide.background.fill
    bg.solid()
    bg.fore_color.rgb = rgb(pal[0] if dark else pal[1])
    t = slide.shapes.title
    t.left, t.top, t.width, t.height = E(M), E(TITLE_TOP), E(W - 2 * M), E(TITLE_H)
    tf = t.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = 0
    tf.vertical_anchor = MSO_ANCHOR.BOTTOM
    tf.text = title or ""
    size = title_size
    while size > 26 and not fits(title or "", t.width, t.height, size, em=0.56):
        size -= 2
    if not fits(title or "", t.width, t.height, size, em=0.56):
        WARN.append(f"{where}: title is too long for one or two lines; shorten it")
    for p in tf.paragraphs:
        p.alignment = PP_ALIGN.LEFT
        for r in p.runs:
            r.font.name, r.font.size, r.font.bold = HEAD_FONT, Pt(size), True
            r.font.color.rgb = rgb("FFFFFF" if dark else pal[0])
    return slide


def add_notes(slide, notes):
    if notes:
        slide.notes_slide.notes_text_frame.text = notes


def footer(slide, pal, deck, n):
    if deck.get("footer"):
        text_box(slide, M, H - Inches(0.5), Inches(8), Inches(0.3), [deck["footer"]], 10, pal[3])
    text_box(slide, W - M - Inches(1), H - Inches(0.5), Inches(1), Inches(0.3), [str(n)], 10, pal[3], align=PP_ALIGN.RIGHT)


def s_title(prs, pal, s, deck, n):
    slide = new_slide(prs, pal, True, s.get("title"), f"slide {n}", title_size=44)
    t = slide.shapes.title
    t.top, t.height, t.width = Inches(2.2), Inches(1.9), Inches(8.6)
    if s.get("subtitle"):
        text_box(slide, M, Inches(4.3), W - 2 * M, Inches(0.9), [s["subtitle"]], 22, "D9DEE8", min_size=16, where=f"slide {n} subtitle")
    if s.get("byline"):
        text_box(slide, M, Inches(6.2), W - 2 * M, Inches(0.5), [s["byline"]], 14, pal[2], bold=True)
    disc = shape(slide, MSO_SHAPE.OVAL, W - Inches(3.4), Inches(-1.2), Inches(4.6), Inches(4.6), pal[2])
    tree = slide.shapes._spTree  # send the disc behind the text
    tree.remove(disc._element)
    tree.insert(2, disc._element)
    return slide


def s_bullets(prs, pal, s, deck, n):
    slide = new_slide(prs, pal, False, s.get("title"), f"slide {n}")
    items = s.get("bullets") or []
    if len(items) > 5:
        WARN.append(f"slide {n}: {len(items)} bullets; keep to 5 or split the slide")
    has_side = bool(s.get("takeaway"))
    bw = Inches(7.6) if has_side else W - 2 * M
    text_box(slide, M, BODY_TOP + Inches(0.2), bw, Inches(4.8), items, 20, "222222", min_size=16, where=f"slide {n} bullets",
             space_after=14, bullets=True)
    if has_side:
        x = M + bw + Inches(0.5)
        card = shape(slide, MSO_SHAPE.ROUNDED_RECTANGLE, x, BODY_TOP + Inches(0.2), W - M - x, Inches(4.4), pal[0])
        card.adjustments[0] = 0.06
        text_box(slide, x + Inches(0.4), BODY_TOP + Inches(0.6), W - M - x - Inches(0.8), Inches(3.6), [s["takeaway"]], 24, "FFFFFF",
                 font=HEAD_FONT, min_size=18, where=f"slide {n} takeaway", anchor=MSO_ANCHOR.MIDDLE)
    return slide


def s_stats(prs, pal, s, deck, n):
    slide = new_slide(prs, pal, False, s.get("title"), f"slide {n}")
    stats = (s.get("stats") or [])[:4]
    k = max(1, len(stats))
    gap = Inches(0.35)
    cw = (W - 2 * M - gap * (k - 1)) / k
    for i, st in enumerate(stats):
        x = M + i * (cw + gap)
        card = shape(slide, MSO_SHAPE.ROUNDED_RECTANGLE, x, BODY_TOP + Inches(0.3), cw, Inches(3.6), "FFFFFF", line="E1E4EA")
        card.adjustments[0] = 0.05
        text_box(slide, x + Inches(0.3), BODY_TOP + Inches(0.6), cw - Inches(0.6), Inches(1.4), [st.get("value", "")], 54 if k <= 3 else 44,
                 pal[2], font=HEAD_FONT, bold=True, min_size=30, where=f"slide {n} stat {i + 1}", anchor=MSO_ANCHOR.MIDDLE)
        paras = [(st.get("label", ""), {"bold": True, "color": pal[0]})]
        if st.get("detail"):
            paras.append((st["detail"], {"size": 14, "color": pal[3]}))
        text_box(slide, x + Inches(0.3), BODY_TOP + Inches(2.1), cw - Inches(0.6), Inches(1.6), paras, 17, pal[0], min_size=13,
                 where=f"slide {n} stat {i + 1} label")
    if s.get("note"):
        text_box(slide, M, BODY_TOP + Inches(4.25), W - 2 * M, Inches(0.6), [s["note"]], 14, pal[3], min_size=12, where=f"slide {n} note")
    return slide


def s_chart(prs, pal, s, deck, n):
    slide = new_slide(prs, pal, False, s.get("title"), f"slide {n}")
    c = s.get("chart") or {}
    data = CategoryChartData()
    data.categories = c.get("categories", [])
    series = c.get("series", [])
    for se in series:
        data.add_series(se.get("name", ""), se.get("values", []))
    kind = {"line": XL_CHART_TYPE.LINE_MARKERS, "bar": XL_CHART_TYPE.BAR_CLUSTERED}.get(c.get("type"), XL_CHART_TYPE.COLUMN_CLUSTERED)
    cap = s.get("caption")
    cw = Inches(8.4) if cap else W - 2 * M
    gf = slide.shapes.add_chart(kind, E(M), E(BODY_TOP + Inches(0.1)), E(cw), E(Inches(4.9)), data)
    ch = gf.chart
    ch.font.name, ch.font.size = BODY_FONT, Pt(12)
    ch.font.color.rgb = rgb(pal[3])
    ch.has_legend = len(series) > 1
    if ch.has_legend:
        ch.legend.position, ch.legend.include_in_layout = XL_LEGEND_POSITION.TOP, False
    colors = [pal[3] if len(series) > 1 else pal[2], pal[2], pal[0]]
    for i, plot_series in enumerate(ch.plots[0].series):
        col = rgb(colors[i % len(colors)] if len(series) > 1 else pal[2])
        if kind == XL_CHART_TYPE.LINE_MARKERS:
            plot_series.format.line.color.rgb = col
            plot_series.format.line.width = Pt(2.5)
            plot_series.marker.format.fill.solid()
            plot_series.marker.format.fill.fore_color.rgb = col
            plot_series.smooth = False
        else:
            plot_series.format.fill.solid()
            plot_series.format.fill.fore_color.rgb = col
    va = ch.value_axis
    va.has_major_gridlines = True
    va.major_gridlines.format.line.color.rgb = rgb("E1E4EA")
    va.format.line.fill.background()
    if c.get("value_title"):
        va.has_title = True
        va.axis_title.text_frame.text = c["value_title"]
        va.axis_title.text_frame.paragraphs[0].runs[0].font.size = Pt(12)
    ca = ch.category_axis
    ca.format.line.color.rgb = rgb("C9CED6")
    ca.tick_labels.font.size = Pt(11)
    if c.get("data_labels", len(c.get("categories", [])) <= 8 and len(series) == 1):
        pl = ch.plots[0]
        pl.has_data_labels = True
        pl.data_labels.font.size = Pt(11)
        pl.data_labels.number_format_is_linked = False
        pl.data_labels.number_format = c.get("number_format", "General")
        if kind != XL_CHART_TYPE.LINE_MARKERS:
            pl.data_labels.position = XL_LABEL_POSITION.OUTSIDE_END
    if cap:
        x = M + cw + Inches(0.4)
        text_box(slide, x, BODY_TOP + Inches(0.6), W - M - x, Inches(4.2), [cap], 20, pal[0], font=HEAD_FONT, min_size=15,
                 where=f"slide {n} caption", anchor=MSO_ANCHOR.MIDDLE)
    return slide


def s_compare(prs, pal, s, deck, n):
    slide = new_slide(prs, pal, False, s.get("title"), f"slide {n}")
    gap = Inches(0.4)
    cw = (W - 2 * M - gap) / 2
    for i, side in enumerate((s.get("left") or {}, s.get("right") or {})):
        x = M + i * (cw + gap)
        hl = i == 1
        card = shape(slide, MSO_SHAPE.ROUNDED_RECTANGLE, x, BODY_TOP + Inches(0.2), cw, Inches(4.7), pal[0] if hl else "FFFFFF",
                     line=None if hl else "E1E4EA")
        card.adjustments[0] = 0.04
        fg = "FFFFFF" if hl else "222222"
        text_box(slide, x + Inches(0.4), BODY_TOP + Inches(0.5), cw - Inches(0.8), Inches(0.6), [side.get("heading", "")], 24,
                 pal[2] if hl else pal[0], font=HEAD_FONT, bold=True, min_size=18, where=f"slide {n} heading {i + 1}")
        text_box(slide, x + Inches(0.4), BODY_TOP + Inches(1.3), cw - Inches(0.8), Inches(3.4), side.get("bullets") or [], 18, fg,
                 min_size=14, where=f"slide {n} column {i + 1}", space_after=10, bullets=True)
    return slide


def s_timeline(prs, pal, s, deck, n):
    slide = new_slide(prs, pal, False, s.get("title"), f"slide {n}")
    steps = (s.get("steps") or [])[:5]
    k = max(1, len(steps))
    gap = Inches(0.3)
    cw = (W - 2 * M - gap * (k - 1)) / k
    y = BODY_TOP + Inches(0.5)
    line_y = y + Inches(0.35)
    ln = slide.shapes.add_connector(1, E(M + Inches(0.35)), E(line_y), E(M + (k - 1) * (cw + gap) + Inches(0.35)), E(line_y))
    ln.line.color.rgb = rgb("C9CED6")
    ln.line.width = Pt(2)
    for i, st in enumerate(steps):
        x = M + i * (cw + gap)
        dot = shape(slide, MSO_SHAPE.OVAL, x, y, Inches(0.7), Inches(0.7), pal[2] if i == 0 else pal[0])
        tf = dot.text_frame
        tf.text = str(i + 1)
        p = tf.paragraphs[0]
        p.alignment = PP_ALIGN.CENTER
        p.runs[0].font.size, p.runs[0].font.bold, p.runs[0].font.name = Pt(18), True, BODY_FONT
        p.runs[0].font.color.rgb = rgb("FFFFFF")
        text_box(slide, x, y + Inches(1.0), cw, Inches(0.6), [st.get("label", "")], 20, pal[0], font=HEAD_FONT, bold=True, min_size=15,
                 where=f"slide {n} step {i + 1} label")
        text_box(slide, x, y + Inches(1.65), cw, Inches(2.6), [st.get("text", "")], 16, "333333", min_size=12, where=f"slide {n} step {i + 1}")
    return slide


def s_statement(prs, pal, s, deck, n):
    slide = new_slide(prs, pal, False, s.get("title", ""), f"slide {n}", title_size=24)
    for r in slide.shapes.title.text_frame.paragraphs[0].runs:
        r.font.color.rgb = rgb(pal[3])
    mark = text_box(slide, M, BODY_TOP - Inches(0.1), Inches(1.2), Inches(1.4), ["“"], 120, pal[2], font=HEAD_FONT, bold=True)
    mark.name = "Quote mark"
    paras = [(s.get("text", ""), {"font": HEAD_FONT, "italic": True})]
    if s.get("attribution"):
        paras.append((s["attribution"], {"size": 16, "color": pal[3], "bold": True}))
    text_box(slide, M + Inches(1.3), BODY_TOP + Inches(0.3), W - 2 * M - Inches(1.3), Inches(4.4), paras, 32, pal[0], min_size=22,
             where=f"slide {n} statement", anchor=MSO_ANCHOR.MIDDLE, space_after=18)
    return slide


def s_closing(prs, pal, s, deck, n):
    slide = new_slide(prs, pal, True, s.get("title"), f"slide {n}", title_size=40)
    items = s.get("bullets") or []
    y = BODY_TOP + Inches(0.4)
    for i, it in enumerate(items[:4]):
        dot = shape(slide, MSO_SHAPE.OVAL, M, y + i * Inches(1.15), Inches(0.55), Inches(0.55), pal[2])
        tf = dot.text_frame
        tf.text = str(i + 1)
        tf.paragraphs[0].alignment = PP_ALIGN.CENTER
        r = tf.paragraphs[0].runs[0]
        r.font.size, r.font.bold, r.font.name = Pt(16), True, BODY_FONT
        r.font.color.rgb = rgb("FFFFFF")
        text_box(slide, M + Inches(0.85), y + i * Inches(1.15) - Inches(0.05), W - 2 * M - Inches(0.85), Inches(0.9), [it], 22, "FFFFFF",
                 min_size=16, where=f"slide {n} item {i + 1}", anchor=MSO_ANCHOR.MIDDLE)
    if len(items) > 4:
        WARN.append(f"slide {n}: closing slide shows 4 items; {len(items) - 4} dropped")
    return slide


KINDS = {"title": s_title, "bullets": s_bullets, "stats": s_stats, "chart": s_chart, "compare": s_compare,
         "timeline": s_timeline, "statement": s_statement, "closing": s_closing}


def build(spec_path, out):
    with open(spec_path, encoding="utf-8") as f:
        deck = json.load(f)
    pal = PALETTES.get(deck.get("palette", "midnight"), PALETTES["midnight"])
    prs = Presentation()
    prs.slide_width, prs.slide_height = W, H
    prs.core_properties.title = deck.get("title", "")
    prs.core_properties.author = deck.get("author", "")
    for n, s in enumerate(deck.get("slides", []), 1):
        fn = KINDS.get(s.get("kind"))
        if not fn:
            WARN.append(f"slide {n}: unknown kind {s.get('kind')!r}, used bullets")
            fn = s_bullets
        slide = fn(prs, pal, s, deck, n)
        if s.get("kind") not in ("title", "closing"):
            footer(slide, pal, deck, n)
        add_notes(slide, s.get("notes"))
        if not s.get("notes"):
            WARN.append(f"slide {n}: no speaker notes")
    prs.save(out)
    for slide in Presentation(out).slides:  # reopen and read every position: fails loudly if the file is broken
        for sh in slide.shapes:
            _ = (sh.left, sh.top, sh.width, sh.height)
    print(json.dumps({"slides": len(deck.get("slides", [])), "warnings": WARN}, indent=2))


def dump(path):
    prs = Presentation(path)
    for n, slide in enumerate(prs.slides, 1):
        print(f"--- slide {n}")
        for sh in slide.shapes:
            if sh.has_text_frame and sh.text_frame.text.strip():
                print(sh.text_frame.text.replace("\n", " | "))
            if getattr(sh, "has_chart", False) and sh.has_chart:
                ch = sh.chart
                print("[chart] " + "; ".join(f"{s.name}: {list(s.values)}" for s in ch.plots[0].series))
        if slide.has_notes_slide:
            print("notes: " + slide.notes_slide.notes_text_frame.text)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--text":
        dump(sys.argv[2])
    elif len(sys.argv) == 3:
        build(sys.argv[1], sys.argv[2])
    else:
        sys.exit(__doc__)
