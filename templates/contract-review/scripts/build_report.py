"""Check a contract review and write issues.docx and output.json.

Usage: python3 build_report.py <review.json> <contract.txt> <out_dir>

review.json is the run's analysis (shape in SKILL.md step 3). The script:
  - checks every finding has a clause reference, a rating of RED, YELLOW or
    GREEN, and (for RED and YELLOW) a proposed redline;
  - checks every "contract_says" quote really appears in the contract text
    (ignoring case, spacing and punctuation), so nothing is misquoted;
  - writes <out_dir>/issues.docx (RED first, then YELLOW, then GREEN) and
    <out_dir>/output.json.
It prints one line per problem and exits 1 if there are any, after still
writing both files, so a fix and a rerun is all that is needed.
"""
import json
import os
import re
import sys

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor

ORDER = {"RED": 0, "YELLOW": 1, "GREEN": 2}
COLOUR = {"RED": "C0392B", "YELLOW": "B7791F", "GREEN": "2F7D4F"}
LABEL = {"RED": "RED: escalate", "YELLOW": "YELLOW: negotiate", "GREEN": "GREEN: acceptable"}


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def shade(cell, hex_colour: str) -> None:
    tc = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_colour)
    tc.append(shd)


def check(review: dict, contract_text: str) -> list[str]:
    problems = []
    text = norm(contract_text)
    findings = review.get("findings")
    if not isinstance(findings, list) or not findings:
        return ["review.json has no findings"]
    for i, f in enumerate(findings):
        name = f"finding {i + 1} ({f.get('topic', '?')})"
        rating = str(f.get("rating", "")).upper()
        if rating not in ORDER:
            problems.append(f"{name}: rating must be RED, YELLOW or GREEN, not {f.get('rating')!r}")
        if not str(f.get("clause_ref", "")).strip():
            problems.append(f"{name}: no clause_ref; cite the clause number as printed")
        if rating in ("RED", "YELLOW") and not str(f.get("redline", "")).strip():
            problems.append(f"{name}: a {rating} finding needs a proposed redline")
        quote = str(f.get("contract_says", "")).strip().strip('"')
        if quote and norm(quote) not in text:
            problems.append(f"{name}: the quote in contract_says is not in the contract; copy it exactly or shorten it")
    for key in ("our_side", "basis", "overall_risk"):
        if not str(review.get(key, "")).strip():
            problems.append(f"review.json is missing {key}")
    return problems


def para(doc, text: str, bold: bool = False, size: float | None = None, colour: str | None = None, italic: bool = False):
    p = doc.add_paragraph()
    r = p.add_run(text)
    r.bold, r.italic = bold, italic
    if size:
        r.font.size = Pt(size)
    if colour:
        r.font.color.rgb = RGBColor.from_string(colour)
    return p


def labelled(doc, label: str, value: str) -> None:
    if not str(value or "").strip():
        return
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(3)
    p.add_run(f"{label}: ").bold = True
    p.add_run(str(value))


def write_docx(review: dict, path: str) -> None:
    doc = Document()
    st = doc.styles["Normal"]
    st.font.name, st.font.size = "Calibri", Pt(10.5)
    doc.add_heading(review.get("title") or "Contract review", level=0)
    para(doc, "Prepared to help a review, not legal advice. Have a qualified lawyer check it before relying on it.", italic=True, size=9, colour="666666")

    t = doc.add_table(rows=0, cols=2)
    t.style = "Light Grid Accent 1"
    t.alignment = WD_TABLE_ALIGNMENT.LEFT
    parties = "; ".join(f"{p.get('name')} ({p.get('role')})" for p in review.get("parties", []) if p.get("name"))
    counts = {k: sum(1 for f in review["findings"] if str(f.get("rating", "")).upper() == k) for k in ORDER}
    rows = [
        ("Document", review.get("document", "")),
        ("Contract type", review.get("contract_type", "")),
        ("Parties", parties),
        ("Reviewed for", review.get("our_side", "")),
        ("Basis", review.get("basis", "")),
        ("Overall risk", str(review.get("overall_risk", "")).capitalize()),
        ("Findings", f"{counts['RED']} red, {counts['YELLOW']} yellow, {counts['GREEN']} green"),
    ]
    for k, v in rows:
        c = t.add_row().cells
        c[0].text, c[1].text = k, str(v)
        c[0].paragraphs[0].runs[0].bold = True

    if review.get("summary"):
        doc.add_heading("Summary", level=1)
        para(doc, review["summary"])
    if review.get("top_issues"):
        doc.add_heading("Top issues", level=1)
        for s in review["top_issues"]:
            doc.add_paragraph(s, style="List Number")

    doc.add_heading("Clause by clause", level=1)
    for f in sorted(review["findings"], key=lambda f: (ORDER.get(str(f.get("rating", "")).upper(), 3))):
        rating = str(f.get("rating", "")).upper()
        h = doc.add_heading(level=2)
        h.add_run(f"Clause {f.get('clause_ref', '?')}: {f.get('topic', '')}  ")
        tag = h.add_run(f"[{LABEL.get(rating, rating)}]")
        tag.font.color.rgb = RGBColor.from_string(COLOUR.get(rating, "333333"))
        if f.get("contract_says"):
            labelled(doc, "Contract says", f'"{str(f["contract_says"]).strip().strip(chr(34))}"')
        labelled(doc, "Position", f.get("position"))
        labelled(doc, "Issue", f.get("issue"))
        labelled(doc, "Impact", f.get("impact"))
        labelled(doc, "Proposed redline", f.get("redline"))
        labelled(doc, "Fallback", f.get("fallback"))
        labelled(doc, "Priority", f.get("priority"))

    if review.get("missing"):
        doc.add_heading("Missing or unusual", level=1)
        for m in review["missing"]:
            p = doc.add_paragraph(style="List Bullet")
            p.add_run(f"{m.get('topic', '')}: ").bold = True
            p.add_run(m.get("note", ""))
    if review.get("negotiation"):
        doc.add_heading("Negotiation strategy", level=1)
        for s in review["negotiation"]:
            doc.add_paragraph(s, style="List Bullet")
    if review.get("next_steps"):
        doc.add_heading("Next steps", level=1)
        for s in review["next_steps"]:
            doc.add_paragraph(s, style="List Bullet")

    # Colour the rating cells in the summary table's findings row for a quick read.
    shade(t.rows[-1].cells[1], "FBEAEA" if counts["RED"] else ("FFF5DB" if counts["YELLOW"] else "E8F4EC"))
    doc.save(path)


def main(review_path: str, text_path: str, out_dir: str) -> None:
    with open(review_path, encoding="utf-8") as f:
        review = json.load(f)
    with open(text_path, encoding="utf-8", errors="replace") as f:
        contract_text = f.read()
    problems = check(review, contract_text)
    os.makedirs(out_dir, exist_ok=True)
    if review.get("findings"):
        write_docx(review, os.path.join(out_dir, "issues.docx"))
    findings = review.get("findings") or []
    out = {
        "contract_type": review.get("contract_type"),
        "parties": [{"name": p.get("name"), "role": p.get("role")} for p in review.get("parties", [])],
        "our_side": review.get("our_side"),
        "basis": review.get("basis"),
        "overall_risk": str(review.get("overall_risk", "")).lower() or None,
        "red_count": sum(1 for x in findings if str(x.get("rating", "")).upper() == "RED"),
        "yellow_count": sum(1 for x in findings if str(x.get("rating", "")).upper() == "YELLOW"),
        "green_count": sum(1 for x in findings if str(x.get("rating", "")).upper() == "GREEN"),
        "findings": [
            {"clause_ref": str(x.get("clause_ref", "")), "topic": x.get("topic", ""), "rating": str(x.get("rating", "")).upper(), "issue": x.get("issue", "")}
            for x in sorted(findings, key=lambda x: ORDER.get(str(x.get("rating", "")).upper(), 3))
        ],
        "top_issues": review.get("top_issues", []),
    }
    with open(os.path.join(out_dir, "output.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    print(f"findings: {out['red_count']} red, {out['yellow_count']} yellow, {out['green_count']} green")
    for p in problems:
        print(f"PROBLEM: {p}")
    print("ok" if not problems else f"{len(problems)} problem(s): fix review.json and rerun")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit("usage: build_report.py <review.json> <contract.txt> <out_dir>")
    main(sys.argv[1], sys.argv[2], sys.argv[3])
