"""Build meeting notes as a Word document from notes.json.

Usage: python3 build_notes.py <notes.json> <out.docx>

notes.json is written by the run (see SKILL.md, step 3). The layout is fixed
here so every set of notes looks the same: title, meeting line, summary,
decisions, an action table (action, owner, due), open questions, and parked
topics. Also writes output.json (decisions, actions, open questions) beside
the document. Prints the counts it wrote.
"""
import json
import os
import sys
from datetime import date

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

INK = RGBColor(0x1F, 0x2A, 0x36)
MUTED = RGBColor(0x5B, 0x65, 0x70)
ALERT = RGBColor(0xB4, 0x23, 0x18)
FONT = "Calibri"


def nice_date(v):
    """ISO date -> 'Monday 9/11/2026' style dd/mm/yyyy; anything else is returned as written."""
    if not v:
        return None
    try:
        d = date.fromisoformat(str(v))
        return f"{d.strftime('%A')} {d.strftime('%d/%m/%Y')}"
    except ValueError:
        return str(v)


def shade(cell, hex_fill):
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")  # never "solid": that renders black
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_fill)
    tc_pr.append(shd)


def set_styles(doc):
    normal = doc.styles["Normal"]
    normal.font.name = FONT
    normal.font.size = Pt(11)
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), FONT)
    normal.paragraph_format.space_after = Pt(4)
    for name, size, before in (("Title", 22, 0), ("Heading 1", 14, 14), ("Heading 2", 12, 10)):
        st = doc.styles[name]
        st.font.name = FONT
        st.font.size = Pt(size)
        st.font.bold = True
        st.font.color.rgb = INK
        # The built-in headings name theme fonts, which win over font.name; drop them.
        rfonts = st.element.rPr.rFonts
        for attr in ("w:asciiTheme", "w:hAnsiTheme", "w:eastAsiaTheme", "w:cstheme"):
            if rfonts is not None and rfonts.get(qn(attr)) is not None:
                del rfonts.attrib[qn(attr)]
        st.paragraph_format.space_before = Pt(before)
        st.paragraph_format.space_after = Pt(4)
        st.paragraph_format.keep_with_next = True
    # Title style ships with a bottom border in the default template; keep it plain.
    ppr = doc.styles["Title"].element.get_or_add_pPr()
    for b in ppr.findall(qn("w:pBdr")):
        ppr.remove(b)


def para(doc, text, style=None, color=None, italic=False, bold_prefix=None):
    p = doc.add_paragraph(style=style)
    if bold_prefix:
        r = p.add_run(bold_prefix)
        r.bold = True
    r = p.add_run(text)
    r.italic = italic
    if color is not None:
        r.font.color.rgb = color
    return p


def main(src, out):
    with open(src, encoding="utf-8") as f:
        n = json.load(f)
    doc = Document()
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Cm(21.0), Cm(29.7)  # A4
    for side in ("left_margin", "right_margin"):
        setattr(sec, side, Cm(2.2))
    sec.top_margin = sec.bottom_margin = Cm(2.0)
    set_styles(doc)

    doc.add_paragraph(n.get("title") or "Meeting notes", style="Title")
    meta = []
    if n.get("date"):
        meta.append(nice_date(n["date"]))
    if n.get("attendees"):
        meta.append("Attendees: " + ", ".join(n["attendees"]))
    if meta:
        para(doc, "   |   ".join(meta), color=MUTED)

    if n.get("summary"):
        doc.add_paragraph("Summary", style="Heading 1")
        para(doc, n["summary"])

    decisions = n.get("decisions") or []
    doc.add_paragraph("Decisions", style="Heading 1")
    if decisions:
        for d in decisions:
            p = doc.add_paragraph(style="List Number")
            p.add_run(d.get("decision", "")).bold = True
            if d.get("detail"):
                p.add_run(f" {d['detail']}")
    else:
        para(doc, "No decisions were made.", italic=True, color=MUTED)

    actions = n.get("actions") or []
    doc.add_paragraph("Action items", style="Heading 1")
    unassigned = 0
    if actions:
        widths = [Cm(9.6), Cm(3.4), Cm(3.6)]
        t = doc.add_table(rows=1, cols=3)
        t.alignment = WD_TABLE_ALIGNMENT.LEFT
        t.autofit = False
        t.style = doc.styles["Table Grid"]
        for i, w in enumerate(widths):  # grid widths as well as cell widths, or some readers ignore them
            t.columns[i].width = w
        for i, h in enumerate(("Action", "Owner", "Due")):
            c = t.rows[0].cells[i]
            c.width = widths[i]
            c.text = ""
            r = c.paragraphs[0].add_run(h)
            r.bold = True
            r.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
            shade(c, "1F2A36")
        for a in actions:
            row = t.add_row().cells
            for i in range(3):
                row[i].width = widths[i]
            row[0].text = a.get("action", "")
            owner = a.get("owner")
            if owner:
                row[1].text = owner
            else:
                unassigned += 1
                rr = row[1].paragraphs[0].add_run("Unassigned")
                rr.bold = True
                rr.font.color.rgb = ALERT
            due = nice_date(a.get("due")) or "Not set"
            row[2].text = due
            if a.get("due_note"):
                rr = row[2].add_paragraph().add_run(a["due_note"])
                rr.italic = True
                rr.font.size = Pt(9)
                rr.font.color.rgb = MUTED
    else:
        para(doc, "No action items.", italic=True, color=MUTED)

    questions = n.get("open_questions") or []
    doc.add_paragraph("Open questions", style="Heading 1")
    if questions:
        for q in questions:
            p = doc.add_paragraph(style="List Bullet")
            p.add_run(q.get("question", ""))
            if q.get("owner"):
                r = p.add_run(f" (follow-up: {q['owner']})")
                r.font.color.rgb = MUTED
    else:
        para(doc, "None left open.", italic=True, color=MUTED)

    parked = n.get("parked") or []
    if parked:
        doc.add_paragraph("Discussed, not agreed", style="Heading 1")
        for item in parked:
            doc.add_paragraph(item, style="List Bullet")

    if n.get("source"):
        doc.add_paragraph()
        para(doc, f"Written from {n['source']}. Owners and dates are as said in the meeting; relative dates were resolved against the meeting date.",
             color=MUTED, italic=True).runs[0].font.size = Pt(9)

    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    doc.save(out)
    result = {
        "title": n.get("title"),
        "date": n.get("date"),
        "decisions": [d.get("decision", "") for d in decisions],
        "actions": [{"action": a.get("action", ""), "owner": a.get("owner"), "due": a.get("due")} for a in actions],
        "open_questions": [q.get("question", "") for q in questions],
    }
    with open(os.path.join(os.path.dirname(os.path.abspath(out)), "output.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    print(json.dumps({"decisions": len(decisions), "actions": len(actions), "unassigned_actions": unassigned,
                      "open_questions": len(questions), "parked": len(parked)}))


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
