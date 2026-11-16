"""Extract a contract's text and list its numbered clauses.

Usage: python3 extract_text.py <contract.pdf|.docx|.txt|.md> <out.txt>

Writes the plain text to <out.txt> (reading order, not columns, so clause
wording can be quoted exactly) and prints one JSON line:
  {"pages": n, "chars": n, "method": "...", "scanned": bool, "clauses": [{"ref": "9.2", "line": "..."}],
   "numbers_rebuilt": n, "auto_numbered": bool}
"clauses" lists every line that starts with a clause number (1, 9.2, 10.3.1),
so findings can cite the right reference. Word's automatic list numbers are not
part of a paragraph's text, so for .docx they are rebuilt from the numbering
definitions and written in front of each paragraph ("numbers_rebuilt" counts
them); "auto_numbered" is true when some paragraphs are numbered in a way that
could not be rebuilt, so the clause numbers in the text are incomplete. On failure it prints
{"error": "unreadable" | "encrypted" | "unsupported", "detail": "..."} and exits 2.
"""
import json
import os
import re
import shutil
import subprocess
import sys

CLAUSE = re.compile(r"^\s*(?:(?:clause|section)\s+)?(\d{1,2}(?:\.\d{1,2}){0,3})\.?\s+(\S.{0,110})", re.I)


def fail(kind: str, detail: str) -> None:
    print(json.dumps({"error": kind, "detail": detail}))
    sys.exit(2)


def read_pdf(path: str, out: str) -> tuple[str, int, str]:
    try:
        from pypdf import PdfReader
    except ImportError:
        PdfReader = None
    pages = 0
    if PdfReader:
        try:
            reader = PdfReader(path)
        except Exception as e:
            fail("unreadable", f"The file could not be read as a PDF ({type(e).__name__}).")
        if reader.is_encrypted:
            try:
                opened = reader.decrypt("")
            except Exception:
                opened = 0
            if not opened:
                fail("encrypted", "The PDF is password protected.")
        pages = len(reader.pages)
    text, method, pdftotext_err = "", "", ""
    if shutil.which("pdftotext"):
        r = subprocess.run(["pdftotext", "-enc", "UTF-8", path, out], capture_output=True)
        if r.returncode == 0:
            with open(out, encoding="utf-8", errors="replace") as f:
                text, method = f.read(), "pdftotext"
            if not pages:
                pages = max(text.count("\f"), 1)
        else:
            pdftotext_err = r.stderr.decode("utf-8", "replace").lower()
    if len(text.strip()) < 40 and PdfReader:
        text = "\n\f".join((p.extract_text() or "") for p in reader.pages)
        method = "pypdf"
    if not method:
        if "password" in pdftotext_err or "encrypt" in pdftotext_err:
            fail("encrypted", "The PDF is password protected.")
        if pdftotext_err:
            fail("unreadable", "pdftotext could not read the PDF and pypdf is not installed to try again.")
        fail("unsupported", "Neither pdftotext nor pypdf is available to read the PDF.")
    return text, pages, method


ROMAN = [(1000, "m"), (900, "cm"), (500, "d"), (400, "cd"), (100, "c"), (90, "xc"), (50, "l"), (40, "xl"), (10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i")]


def fmt_number(n: int, fmt: str) -> str:
    if fmt in ("lowerLetter", "upperLetter"):
        s = ""
        while n > 0:
            n, r = divmod(n - 1, 26)
            s = chr(97 + r) + s
        return s.upper() if fmt == "upperLetter" else s
    if fmt in ("lowerRoman", "upperRoman"):
        s, x = "", n
        for v, sym in ROMAN:
            while x >= v:
                s, x = s + sym, x - v
        return s.upper() if fmt == "upperRoman" else s
    return str(n)  # decimal and anything else


class Numbering:
    """Rebuild Word's automatic list numbers ("1.", "1.1", "(a)"), which paragraph.text leaves out."""

    def __init__(self, doc):
        from docx.oxml.ns import qn

        self.qn = qn
        self.levels, self.num_abs, self.counters = {}, {}, {}
        self.unresolved = 0
        try:
            root = doc.part.numbering_part.element
        except Exception:
            root = None
        if root is None:
            return
        for an in root.findall(qn("w:abstractNum")):
            aid = an.get(qn("w:abstractNumId"))
            for lvl in an.findall(qn("w:lvl")):
                il = int(lvl.get(qn("w:ilvl")))
                val = lambda tag: (lvl.find(qn(tag)).get(qn("w:val")) if lvl.find(qn(tag)) is not None else None)
                self.levels[(aid, il)] = {"start": int(val("w:start") or 1), "fmt": val("w:numFmt") or "decimal", "text": val("w:lvlText") or ""}
        for num in root.findall(qn("w:num")):
            ref = num.find(qn("w:abstractNumId"))
            if ref is not None:
                self.num_abs[num.get(qn("w:numId"))] = ref.get(qn("w:val"))

    def _numpr(self, para):
        qn = self.qn
        ppr = para._p.pPr
        npr = ppr.find(qn("w:numPr")) if ppr is not None else None
        style = para.style
        while npr is None and style is not None:  # numbering set on the style (common for headings)
            sp = style.element.pPr
            npr = sp.find(qn("w:numPr")) if sp is not None else None
            style = style.base_style
        if npr is None:
            return None
        nid = npr.find(qn("w:numId"))
        il = npr.find(qn("w:ilvl"))
        return (nid.get(qn("w:val")) if nid is not None else None, int(il.get(qn("w:val"))) if il is not None else 0)

    def label(self, para) -> str:
        np_ = self._numpr(para)
        if not np_ or np_[0] in (None, "0"):
            return ""
        nid, il = np_
        aid = self.num_abs.get(nid)
        if aid is None or (aid, il) not in self.levels:
            self.unresolved += 1
            return ""
        lv = self.levels[(aid, il)]
        if lv["fmt"] in ("bullet", "none"):
            return ""
        c = self.counters.setdefault(aid, {})
        c[il] = c.get(il, lv["start"] - 1) + 1
        for deeper in [k for k in c if k > il]:
            del c[deeper]
        text = lv["text"]
        for k in range(il + 1):
            lk = self.levels.get((aid, k), {"start": 1, "fmt": "decimal"})
            text = text.replace(f"%{k + 1}", fmt_number(c.get(k, lk["start"]), lk["fmt"]))
        return text.strip()


def read_docx(path: str) -> tuple[str, int, int]:
    import docx  # python-docx

    d = docx.Document(path)
    nums = Numbering(d)
    parts, rebuilt = [], 0
    for p in d.paragraphs:
        lab = nums.label(p)
        if lab:
            rebuilt += 1
            parts.append(f"{lab} {p.text}")
        else:
            parts.append(p.text)
    for t in d.tables:
        for row in t.rows:
            parts.append(" | ".join(c.text.strip() for c in row.cells))
    return "\n".join(parts), rebuilt, nums.unresolved


def main(path: str, out: str) -> None:
    ext = os.path.splitext(path)[1].lower()
    rebuilt, unresolved = 0, 0
    if ext == ".pdf":
        text, pages, method = read_pdf(path, out)
    elif ext == ".docx":
        try:
            text, rebuilt, unresolved = read_docx(path)
            pages, method = 0, "python-docx"
        except Exception as e:
            fail("unreadable", f"The file could not be read as a Word document ({type(e).__name__}).")
    elif ext in (".txt", ".md", ".text"):
        with open(path, encoding="utf-8", errors="replace") as f:
            text, pages, method = f.read(), 0, "text"
    else:
        fail("unsupported", f"{ext or 'This file type'} is not supported; use PDF, DOCX or plain text.")
    # Re-join words hyphenated across line breaks, keep everything else as printed.
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    with open(out, "w", encoding="utf-8") as f:
        f.write(text)
    clauses, seen = [], set()
    for line in text.splitlines():
        m = CLAUSE.match(line)
        if m and m.group(1) not in seen and not re.match(r"^\d+(\.\d+)?\s*(%|per|months?|days?|years?)\b", line.strip(), re.I):
            seen.add(m.group(1))
            clauses.append({"ref": m.group(1), "line": line.strip()[:120]})
    chars = len("".join(text.split()))
    print(json.dumps({
        "pages": pages,
        "chars": chars,
        "method": method,
        "scanned": ext == ".pdf" and chars < 40 * max(pages, 1),
        "clauses": clauses[:150],
        "numbers_rebuilt": rebuilt,
        "auto_numbered": unresolved > 0,
    }))


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("usage: extract_text.py <contract> <out.txt>")
    main(sys.argv[1], sys.argv[2])
