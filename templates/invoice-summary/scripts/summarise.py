"""Check an invoice's arithmetic and write the summary PDF and output.json.

Usage: python3 summarise.py <fields.json> <out_dir>

fields.json is written by the run from the invoice text (see SKILL.md, step 2).
Writes <out_dir>/summary.pdf and <out_dir>/output.json and prints the checks.
Amounts are compared to the cent; nothing printed on the invoice is changed.
"""
import json
import os
import sys
from datetime import date

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

TOL = 0.011  # a cent, plus float noise


def num(v):
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace(",", "").replace(" ", "")
    try:
        return float(s)
    except ValueError:
        return None


def iso(v):
    if not v:
        return None
    try:
        return date.fromisoformat(str(v)).isoformat()
    except ValueError:
        return None


def money(v, cur):
    return "not printed" if v is None else f"{cur} {v:,.2f}"


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def checks(f):
    """Each check is (name, ok, detail). ok is None when the invoice does not print what the check needs."""
    out = []
    items = f.get("line_items") or []
    bad_lines = []
    for i, it in enumerate(items, 1):
        q, u, a = num(it.get("quantity")), num(it.get("unit_price")), num(it.get("amount"))
        if None not in (q, u, a) and abs(round(q * u, 2) - a) > TOL:
            bad_lines.append(f"line {i}: {q:g} x {u:g} = {q * u:,.2f}, printed {a:,.2f}")
    if items:
        out.append(("Line amounts = quantity x unit price", not bad_lines, "; ".join(bad_lines) or f"{len(items)} lines agree"))
    amounts = [num(it.get("amount")) for it in items]
    sub, tax, total = num(f.get("subtotal")), num(f.get("tax")), num(f.get("total"))
    if items and None not in amounts and sub is not None:
        s = round(sum(amounts), 2)
        out.append(("Lines add up to the subtotal", abs(s - sub) <= TOL, f"lines {s:,.2f}, subtotal {sub:,.2f}"))
    else:
        out.append(("Lines add up to the subtotal", None, "subtotal or a line amount is not printed"))
    if sub is not None and total is not None:
        t = round(sub + (tax or 0) - (num(f.get("discount")) or 0), 2)
        out.append(("Subtotal + tax = total", abs(t - total) <= TOL, f"{t:,.2f} computed, total {total:,.2f}"))
    else:
        out.append(("Subtotal + tax = total", None, "subtotal or total is not printed"))
    due, inv = iso(f.get("due_date")), iso(f.get("invoice_date"))
    if due and inv:
        out.append(("Due date is on or after the invoice date", due >= inv, f"invoice {inv}, due {due}"))
    return out


def write_pdf(path, f, cks):
    cur = f.get("currency") or ""
    ss = getSampleStyleSheet()
    body = ParagraphStyle("b", parent=ss["Normal"], fontName="Helvetica", fontSize=10, leading=13)
    small = ParagraphStyle("s", parent=body, fontSize=8.5, leading=11, textColor=colors.HexColor("#555555"))
    h1 = ParagraphStyle("h1", parent=body, fontName="Helvetica-Bold", fontSize=18, leading=22, spaceAfter=2)
    h2 = ParagraphStyle("h2", parent=body, fontName="Helvetica-Bold", fontSize=11.5, leading=15, spaceBefore=10, spaceAfter=4)
    ink = colors.HexColor("#1F2A36")
    grid = colors.HexColor("#D5DAE0")
    doc = SimpleDocTemplate(path, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=14 * mm,
                            title=f"Invoice summary {f.get('invoice_number') or ''}".strip())
    st = [Paragraph("Invoice summary", h1),
          Paragraph(esc(f"{f.get('supplier') or 'Unknown supplier'}, invoice {f.get('invoice_number') or 'without a number'}"), small),
          Spacer(1, 6 * mm)]

    due = iso(f.get("due_date"))
    src = f.get("due_date_source")
    due_txt = due or "not found"
    if due and src == "terms":
        due_txt += f" (worked out from the terms: {f.get('payment_terms') or 'see invoice'})"
    facts = [["Supplier", f.get("supplier") or "not found"], ["Bill to", f.get("customer") or "not printed"],
             ["Invoice number", f.get("invoice_number") or "not found"], ["Invoice date", iso(f.get("invoice_date")) or "not found"],
             ["Due date", due_txt], ["Payment terms", f.get("payment_terms") or "not printed"],
             ["Total", money(num(f.get("total")), cur)]]
    if num(f.get("amount_due")) is not None and abs(num(f.get("amount_due")) - (num(f.get("total")) or 0)) > TOL:
        facts.append(["Amount due", money(num(f.get("amount_due")), cur)])
    t = Table([[Paragraph(f"<b>{esc(k)}</b>", body), Paragraph(esc(v), body)] for k, v in facts], colWidths=[38 * mm, 136 * mm])
    t.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.4, grid), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                           ("BACKGROUND", (0, 6), (-1, 6), colors.HexColor("#EEF2F6"))]))
    st.append(t)

    items = f.get("line_items") or []
    if items:
        st.append(Paragraph("Line items", h2))
        rows = [["Description", "Qty", "Unit price", "Amount"]]
        for it in items:
            q, u, a = num(it.get("quantity")), num(it.get("unit_price")), num(it.get("amount"))
            rows.append([Paragraph(esc(it.get("description") or ""), body), "" if q is None else f"{q:g}",
                         "" if u is None else f"{u:,.{3 if u and round(u, 2) != u else 2}f}", "" if a is None else f"{a:,.2f}"])
        rows.append(["", "", "Subtotal", "" if num(f.get("subtotal")) is None else f"{num(f.get('subtotal')):,.2f}"])
        if num(f.get("discount")):
            rows.append(["", "", "Discount", f"-{num(f.get('discount')):,.2f}"])
        rows.append(["", "", f.get("tax_label") or "Tax", "" if num(f.get("tax")) is None else f"{num(f.get('tax')):,.2f}"])
        rows.append(["", "", f"Total ({cur})" if cur else "Total", "" if num(f.get("total")) is None else f"{num(f.get('total')):,.2f}"])
        n = len(items)
        lt = Table(rows, colWidths=[96 * mm, 18 * mm, 30 * mm, 30 * mm], repeatRows=1)
        lt.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), ink), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 9.5),
                                ("ALIGN", (1, 0), (-1, -1), "RIGHT"), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                                ("LINEBELOW", (0, 1), (-1, n), 0.4, grid), ("LINEABOVE", (2, -1), (-1, -1), 0.8, ink),
                                ("FONTNAME", (2, -1), (-1, -1), "Helvetica-Bold")]))
        st.append(lt)

    st.append(Paragraph("Checks", h2))
    crow = [[{True: "OK", False: "CHECK", None: "n/a"}[ok], Paragraph(f"<b>{esc(name)}</b><br/>{esc(detail)}", body)] for name, ok, detail in cks]
    ct = Table(crow, colWidths=[18 * mm, 156 * mm])
    style = [("VALIGN", (0, 0), (-1, -1), "TOP"), ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"), ("LINEBELOW", (0, 0), (-1, -1), 0.4, grid)]
    for i, (_, ok, _) in enumerate(cks):
        style.append(("TEXTCOLOR", (0, i), (0, i), {True: colors.HexColor("#1E7B45"), False: colors.HexColor("#B42318"), None: colors.grey}[ok]))
    ct.setStyle(TableStyle(style))
    st.append(ct)

    notes = [n for n in (f.get("notes") or []) if n]
    if notes:
        st.append(Paragraph("Notes", h2))
        for n in notes:
            st.append(Paragraph(f"- {esc(n)}", body))
    st += [Spacer(1, 6 * mm), Paragraph("Read from the invoice PDF. Amounts are as printed; the checks recompute them to the cent.", small)]
    doc.build(st)


def main(fields_path, out_dir):
    with open(fields_path, encoding="utf-8") as fh:
        f = json.load(fh)
    os.makedirs(out_dir, exist_ok=True)
    cks = checks(f)
    write_pdf(os.path.join(out_dir, "summary.pdf"), f, cks)
    failed = [f"{name}: {detail}" for name, ok, detail in cks if ok is False]
    out = {
        "supplier": f.get("supplier"),
        "invoice_number": f.get("invoice_number"),
        "invoice_date": iso(f.get("invoice_date")),
        "total": num(f.get("total")),
        "currency": f.get("currency"),
        "due_date": iso(f.get("due_date")),
        "subtotal": num(f.get("subtotal")),
        "tax": num(f.get("tax")),
        "checks_passed": not failed,
        "issues": failed,
    }
    with open(os.path.join(out_dir, "output.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2)
    for name, ok, detail in cks:
        print(f"{ {True: 'OK', False: 'CHECK', None: 'n/a'}[ok]:5}  {name}: {detail}")
    print(json.dumps(out))


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
