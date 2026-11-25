"""
Turns a drawing (PDF page or image) into PNGs a model can read: the whole
sheet, plus zoomed tiles so small dimensions and tolerances are legible, and
for a PDF with a text layer, the sheet's text with positions.

    python3 render_drawing.py <drawing> <out_dir> [--page 1] [--grid 2x2]
    python3 render_drawing.py <drawing> <out_dir> --crop x0,y0,x1,y1   (fractions 0-1 of the sheet, e.g. 0.4,0.2,0.7,0.5)

Writes <out_dir>/sheet.png (about 1800 px wide), tile-r<row>c<col>.png
(about 2x zoom, overlapping 10%), crop-<n>.png for --crop, and text.txt
(pdftotext -layout) when the PDF has text. Prints what it wrote.
"""
import argparse
import os
import shutil
import subprocess
import sys

from PIL import Image

Image.MAX_IMAGE_PIXELS = 400_000_000


def sheet_image(src: str, page: int, dpi: int, out_png: str) -> Image.Image:
    if src.lower().endswith(".pdf"):
        if not shutil.which("pdftoppm"):
            sys.exit("pdftoppm is not installed")
        base = out_png[:-4]
        # pdftoppm prints font warnings ("Syntax Error: ...") for many CAD PDFs; show them only if it fails.
        r = subprocess.run(["pdftoppm", "-png", "-r", str(dpi), "-f", str(page), "-l", str(page), "-singlefile", src, base], capture_output=True, text=True)
        if r.returncode != 0 or not os.path.exists(out_png):
            sys.exit(f"pdftoppm failed: {r.stderr.strip()[-2000:]}")
        return Image.open(out_png).convert("RGB")
    img = Image.open(src)
    img.seek(min(page - 1, getattr(img, "n_frames", 1) - 1))
    return img.convert("RGB")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("drawing")
    ap.add_argument("out_dir")
    ap.add_argument("--page", type=int, default=1)
    ap.add_argument("--grid", default="2x2", help="rows x cols of zoomed tiles")
    ap.add_argument("--crop", action="append", default=[], help="x0,y0,x1,y1 as fractions of the sheet")
    a = ap.parse_args()
    os.makedirs(a.out_dir, exist_ok=True)
    big_png = os.path.join(a.out_dir, "_full.png")
    big = sheet_image(a.drawing, a.page, 400, big_png)
    W, H = big.size
    written = []

    sheet = big.copy()
    sheet.thumbnail((1800, 1800))
    p = os.path.join(a.out_dir, "sheet.png")
    sheet.save(p)
    written.append(f"sheet.png {sheet.size[0]}x{sheet.size[1]}")

    def save_region(name: str, x0: float, y0: float, x1: float, y1: float) -> None:
        box = (int(x0 * W), int(y0 * H), int(x1 * W), int(y1 * H))
        tile = big.crop(box)
        tile.thumbnail((1800, 1800))
        tile.save(os.path.join(a.out_dir, name))
        written.append(f"{name} {tile.size[0]}x{tile.size[1]} (x {x0:.2f}-{x1:.2f}, y {y0:.2f}-{y1:.2f} of the sheet)")

    if a.crop:
        for n, c in enumerate(a.crop, 1):
            x0, y0, x1, y1 = (float(v) for v in c.split(","))
            save_region(f"crop-{n}.png", x0, y0, x1, y1)
    else:
        rows, cols = (int(v) for v in a.grid.lower().split("x"))
        ov = 0.05
        for r in range(rows):
            for c in range(cols):
                save_region(
                    f"tile-r{r + 1}c{c + 1}.png",
                    max(0, c / cols - ov), max(0, r / rows - ov),
                    min(1, (c + 1) / cols + ov), min(1, (r + 1) / rows + ov),
                )
        if a.drawing.lower().endswith(".pdf") and shutil.which("pdftotext"):
            t = os.path.join(a.out_dir, "text.txt")
            subprocess.run(["pdftotext", "-layout", "-f", str(a.page), "-l", str(a.page), a.drawing, t], check=False, capture_output=True)
            if os.path.exists(t) and len(open(t, errors="ignore").read().split()) >= 10:
                written.append("text.txt (the PDF's text layer: dimensions as printed, positions approximate)")
            else:
                if os.path.exists(t):
                    os.remove(t)
                written.append("no text layer: read every number from the sheet, tiles and crops")
    os.remove(big_png) if os.path.exists(big_png) else None
    print("\n".join(written))


if __name__ == "__main__":
    main()
