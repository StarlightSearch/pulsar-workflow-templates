"""Extract the text of a PDF, keeping its layout.

Usage: python3 extract_text.py <pdf> <out.txt>

Tries `pdftotext -layout` first (best at keeping table columns lined up), then
pypdf. Prints one JSON line: {"pages": n, "chars": n, "method": "...", "scanned": bool}.
"scanned" is true when the PDF has almost no text layer (an image scan): the
text cannot be read without OCR.
"""
import json
import shutil
import subprocess
import sys

from pypdf import PdfReader


def main(pdf: str, out: str) -> None:
    reader = PdfReader(pdf)
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception:
            print(json.dumps({"error": "encrypted", "detail": "The PDF is password protected."}))
            sys.exit(2)
    pages = len(reader.pages)
    text, method = "", ""
    if shutil.which("pdftotext"):
        r = subprocess.run(["pdftotext", "-layout", pdf, out], capture_output=True)
        if r.returncode == 0:
            with open(out, encoding="utf-8", errors="replace") as f:
                text, method = f.read(), "pdftotext"
    if len(text.strip()) < 40:
        text = "\n\f".join((p.extract_text() or "") for p in reader.pages)
        method = "pypdf"
        with open(out, "w", encoding="utf-8") as f:
            f.write(text)
    chars = len("".join(text.split()))
    print(json.dumps({"pages": pages, "chars": chars, "method": method, "scanned": chars < 40 * max(pages, 1)}))


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
