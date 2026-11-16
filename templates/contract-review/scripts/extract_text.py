"""Extract a contract's text and list its numbered clauses.

Usage: python3 extract_text.py <contract.pdf|.docx|.txt|.md> <out.txt>

Writes the plain text to <out.txt> (reading order, not columns, so clause
wording can be quoted exactly) and prints one JSON line:
  {"pages": n, "chars": n, "method": "...", "scanned": bool, "clauses": [{"ref": "9.2", "line": "..."}]}
"clauses" lists every line that starts with a clause number (1, 9.2, 10.3.1),
so findings can cite the right reference. On failure it prints
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
    text, method = "", ""
    if shutil.which("pdftotext"):
        r = subprocess.run(["pdftotext", "-enc", "UTF-8", path, out], capture_output=True)
        if r.returncode == 0:
            with open(out, encoding="utf-8", errors="replace") as f:
                text, method = f.read(), "pdftotext"
            if not pages:
                pages = max(text.count("\f"), 1)
    if len(text.strip()) < 40 and PdfReader:
        text = "\n\f".join((p.extract_text() or "") for p in reader.pages)
        method = "pypdf"
    if not method:
        fail("unsupported", "Neither pdftotext nor pypdf is available to read the PDF.")
    return text, pages, method


def read_docx(path: str) -> str:
    import docx  # python-docx

    d = docx.Document(path)
    parts = [p.text for p in d.paragraphs]
    for t in d.tables:
        for row in t.rows:
            parts.append(" | ".join(c.text.strip() for c in row.cells))
    return "\n".join(parts)


def main(path: str, out: str) -> None:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        text, pages, method = read_pdf(path, out)
    elif ext == ".docx":
        try:
            text, pages, method = read_docx(path), 0, "python-docx"
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
    }))


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("usage: extract_text.py <contract> <out.txt>")
    main(sys.argv[1], sys.argv[2])
