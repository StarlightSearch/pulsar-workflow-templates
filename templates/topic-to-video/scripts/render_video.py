"""
Renders a short motion-graphics video from a scene plan (JSON), so every video
looks finished whatever the topic: the run writes the words, this script owns
the layout, type, easing and timing.

    python3 render_video.py plan.json out.mp4 [--poster poster.png] [--check]

--check validates the plan and prints its timing without rendering.

The plan:

    {
      "title": "Why bees matter",
      "palette": {"bg": "#0e1a1f", "fg": "#ffffff", "accent": "#3ec5d3"},   (optional)
      "scenes": [
        {"type": "title",   "seconds": 2.5, "headline": "Why bees matter", "sub": "In ten seconds"},
        {"type": "bullets", "seconds": 2.5, "heading": "They pollinate", "items": ["Fruit", "Nuts", "Coffee"]},
        {"type": "stat",    "seconds": 2.0, "value": 75, "suffix": "%", "label": "of food crops benefit from pollinators"},
        {"type": "bars",    "seconds": 2.0, "heading": "Honey per hive (kg)", "bars": [["Spring", 8], ["Summer", 20], ["Autumn", 6]]},
        {"type": "closing", "seconds": 1.0, "headline": "Protect them.", "sub": "Plant flowers"}
      ]
    }

Scene types: title (headline, sub), bullets (heading, 1 to 4 items), stat
(value, optional prefix/suffix/decimals, label), bars (heading, 2 to 6
[label, value] pairs), quote (text, by), closing (headline, sub). Scene
seconds add up to the video's length (8 to 12 s). Text is wrapped and shrunk
to fit; overlong text is an error, not cut off.

Needs Pillow (in the image) and ffmpeg: the ffmpeg binary on PATH, else the
one bundled with the imageio-ffmpeg wheel (install it with
`pip install --target /tmp/video/py imageio-ffmpeg` and set PYTHONPATH).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H, FPS = 1280, 720, 30
MARGIN = 110
LIMITS = {"headline": 60, "sub": 70, "heading": 50, "item": 48, "label": 80, "quote": 160, "by": 40, "bar_label": 14}
FONT_DIRS = ["/usr/share/fonts", "/usr/local/share/fonts", os.path.expanduser("~/.fonts")]
BOLD = ["DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf", "NotoSans-Bold.ttf"]
REGULAR = ["DejaVuSans.ttf", "LiberationSans-Regular.ttf", "NotoSans-Regular.ttf"]
DEFAULT_PALETTE = {"bg": "#0e1a1f", "fg": "#ffffff", "accent": "#3ec5d3"}


class PlanError(ValueError):
    pass


# ---------------------------------------------------------------- plan

def _text(scene: dict, key: str, limit_key: str | None = None, required: bool = True) -> str:
    v = scene.get(key)
    if v is None or v == "":
        if required:
            raise PlanError(f"{scene.get('type')} scene needs '{key}'")
        return ""
    if not isinstance(v, str):
        raise PlanError(f"'{key}' must be text")
    limit = LIMITS[limit_key or key]
    if len(v) > limit:
        raise PlanError(f"'{key}' is {len(v)} characters, at most {limit}: shorten it ({v[:40]}...)")
    return v.strip()


def _color(v, fallback: str) -> tuple:
    s = v if isinstance(v, str) else fallback
    s = s.lstrip("#")
    if len(s) != 6:
        raise PlanError(f"colour {v!r} must be #rrggbb")
    try:
        return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        raise PlanError(f"colour {v!r} must be #rrggbb") from None


def load_plan(path: str) -> dict:
    with open(path) as f:
        plan = json.load(f)
    scenes = plan.get("scenes")
    if not isinstance(scenes, list) or not 3 <= len(scenes) <= 6:
        raise PlanError("the plan needs 3 to 6 scenes")
    total = 0.0
    for s in scenes:
        t = s.get("type")
        secs = s.get("seconds")
        if not isinstance(secs, (int, float)) or not 1.0 <= secs <= 4.0:
            raise PlanError(f"{t} scene: seconds must be 1 to 4")
        total += secs
        if t in ("title", "closing"):
            _text(s, "headline")
            _text(s, "sub", required=False)
        elif t == "bullets":
            _text(s, "heading")
            items = s.get("items")
            if not isinstance(items, list) or not 1 <= len(items) <= 4:
                raise PlanError("bullets scene needs 1 to 4 items")
            for it in items:
                _text({"type": t, "item": it}, "item")
        elif t == "stat":
            if not isinstance(s.get("value"), (int, float)):
                raise PlanError("stat scene needs a number 'value'")
            _text(s, "label")
            for k in ("prefix", "suffix"):
                if len(str(s.get(k, ""))) > 6:
                    raise PlanError(f"stat {k} is at most 6 characters")
        elif t == "bars":
            _text(s, "heading")
            bars = s.get("bars")
            if not isinstance(bars, list) or not 2 <= len(bars) <= 6:
                raise PlanError("bars scene needs 2 to 6 bars")
            for b in bars:
                if not (isinstance(b, list) and len(b) == 2 and isinstance(b[1], (int, float)) and b[1] >= 0):
                    raise PlanError("each bar is [label, non-negative number]")
                _text({"type": t, "bar_label": b[0]}, "bar_label")
        elif t == "quote":
            _text(s, "quote")
            _text(s, "by", required=False)
        else:
            raise PlanError(f"unknown scene type {t!r}")
    if not 8.0 <= total <= 12.0:
        raise PlanError(f"scenes add up to {total:g} s; make it 8 to 12 s")
    pal = plan.get("palette") or {}
    plan["_palette"] = {k: _color(pal.get(k), DEFAULT_PALETTE[k]) for k in DEFAULT_PALETTE}
    if _contrast(plan["_palette"]["fg"], plan["_palette"]["bg"]) < 4.5:
        raise PlanError("the palette's fg and bg need a contrast of at least 4.5:1")
    plan["_total"] = total
    return plan


def _lum(c) -> float:
    def ch(v):
        v = v / 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(v) for v in c)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a, b) -> float:
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


# ---------------------------------------------------------------- drawing

_font_cache: dict = {}


def _find_font(names: list[str]) -> str | None:
    for d in FONT_DIRS:
        for root, _dirs, files in os.walk(d):
            for n in names:
                if n in files:
                    return os.path.join(root, n)
    return None


def font(size: int, bold: bool = True):
    key = (size, bold)
    if key not in _font_cache:
        path = _find_font(BOLD if bold else REGULAR)
        _font_cache[key] = ImageFont.truetype(path, size) if path else ImageFont.load_default(size)
    return _font_cache[key]


def wrap(draw, text: str, size: int, bold: bool, width: int, max_lines: int):
    """Wraps text to `width`, shrinking the size until it fits in `max_lines`."""
    while size >= 18:
        f = font(size, bold)
        words, lines, cur = text.split(), [], ""
        for w in words:
            trial = (cur + " " + w).strip()
            if draw.textlength(trial, font=f) <= width:
                cur = trial
            else:
                if cur:
                    lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        if len(lines) <= max_lines and all(draw.textlength(ln, font=f) <= width for ln in lines):
            return f, lines
        size -= 4
    raise PlanError(f"text does not fit: {text[:40]}")


def ease_out(x: float) -> float:
    x = max(0.0, min(1.0, x))
    return 1 - (1 - x) ** 3


def mix(a, b, t: float):
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def reveal(t: float, start: float, dur: float = 0.45) -> float:
    return ease_out((t - start) / dur)


def text_line(img, xy, text, f, color, bg, alpha: float, rise: float = 18):
    """Draws a line of text faded and lifted by `alpha` (0 hidden, 1 in place)."""
    if alpha <= 0:
        return
    x, y = xy
    d = ImageDraw.Draw(img)
    d.text((x, y + (1 - alpha) * rise), text, font=f, fill=mix(bg, color, alpha))


def scene_title(img, s, t, pal, closing=False):
    d = ImageDraw.Draw(img)
    bg, fg, ac = pal["bg"], pal["fg"], pal["accent"]
    f, lines = wrap(d, s["headline"], 92 if not closing else 84, True, W - 2 * MARGIN, 2)
    lh = f.size * 1.12
    block = lh * len(lines) + (70 if s.get("sub") else 0)
    y = (H - block) / 2
    bar = ease_out(t / 0.6)
    d.rectangle([MARGIN, y - 34, MARGIN + int(120 * bar), y - 26], fill=ac)
    for i, ln in enumerate(lines):
        text_line(img, (MARGIN, y + i * lh), ln, f, fg, bg, reveal(t, 0.1 + i * 0.12))
    if s.get("sub"):
        fs, sl = wrap(d, s["sub"], 40, False, W - 2 * MARGIN, 1)
        text_line(img, (MARGIN, y + len(lines) * lh + 22), sl[0], fs, ac, bg, reveal(t, 0.35 + 0.12 * len(lines)))


def scene_bullets(img, s, t, pal):
    d = ImageDraw.Draw(img)
    bg, fg, ac = pal["bg"], pal["fg"], pal["accent"]
    fh, hl = wrap(d, s["heading"], 64, True, W - 2 * MARGIN, 1)
    items = s["items"]
    fi = min((wrap(d, it, 44, False, W - 2 * MARGIN - 60, 1)[0] for it in items), key=lambda f: f.size)
    gap = fi.size * 1.9
    top = (H - (fh.size * 1.6 + gap * len(items))) / 2
    text_line(img, (MARGIN, top), hl[0], fh, fg, bg, reveal(t, 0.05))
    for i, it in enumerate(items):
        a = reveal(t, 0.35 + i * 0.28)
        y = top + fh.size * 1.6 + i * gap
        if a > 0:
            r = 9 * a
            cy = y + fi.size * 0.62
            d.ellipse([MARGIN + 10 - r, cy - r, MARGIN + 10 + r, cy + r], fill=mix(bg, ac, a))
        text_line(img, (MARGIN + 46, y), it, fi, fg, bg, a)


def scene_stat(img, s, t, pal):
    d = ImageDraw.Draw(img)
    bg, fg, ac = pal["bg"], pal["fg"], pal["accent"]
    v = float(s["value"])
    dec = int(s.get("decimals", 0 if v == int(v) else 1))
    shown = v * ease_out(t / 1.1)
    txt = f"{s.get('prefix', '')}{shown:,.{dec}f}{s.get('suffix', '')}"
    final = f"{s.get('prefix', '')}{v:,.{dec}f}{s.get('suffix', '')}"
    f = font(170, True)
    while d.textlength(final, font=f) > W - 2 * MARGIN and f.size > 60:
        f = font(f.size - 10, True)
    fl, ll = wrap(d, s["label"], 40, False, W - 2 * MARGIN, 2)
    total_h = f.size * 1.05 + 20 + fl.size * 1.3 * len(ll)
    y = (H - total_h) / 2
    text_line(img, (MARGIN, y), txt, f, ac, bg, reveal(t, 0.0, 0.3), rise=10)
    for i, ln in enumerate(ll):
        text_line(img, (MARGIN, y + f.size * 1.05 + 20 + i * fl.size * 1.3), ln, fl, fg, bg, reveal(t, 0.45 + i * 0.1))


def scene_bars(img, s, t, pal):
    d = ImageDraw.Draw(img)
    bg, fg, ac = pal["bg"], pal["fg"], pal["accent"]
    fh, hl = wrap(d, s["heading"], 54, True, W - 2 * MARGIN, 1)
    text_line(img, (MARGIN, 90), hl[0], fh, fg, bg, reveal(t, 0.05))
    bars = s["bars"]
    top, bottom = 90 + fh.size * 1.8, H - 110
    n = len(bars)
    slot = (W - 2 * MARGIN) / n
    bw = slot * 0.56
    vmax = max(b[1] for b in bars) or 1
    fl = font(26, False)
    fv = font(28, True)
    d.line([MARGIN, bottom, W - MARGIN, bottom], fill=mix(bg, fg, 0.35), width=2)
    for i, (label, value) in enumerate(bars):
        g = ease_out((t - 0.3 - i * 0.12) / 0.7)
        x0 = MARGIN + i * slot + (slot - bw) / 2
        h = (bottom - top - 40) * (value / vmax) * g
        if h > 0:
            d.rounded_rectangle([x0, bottom - h, x0 + bw, bottom], radius=8, fill=ac)
        val = f"{value * g:,.0f}" if value == int(value) else f"{value * g:,.1f}"
        if g > 0:
            tw = d.textlength(val, font=fv)
            d.text((x0 + (bw - tw) / 2, bottom - h - 40), val, font=fv, fill=mix(bg, fg, g))
        lw = d.textlength(label, font=fl)
        text_line(img, (x0 + (bw - lw) / 2, bottom + 16), label, fl, fg, bg, reveal(t, 0.2 + i * 0.08), rise=6)


def scene_quote(img, s, t, pal):
    d = ImageDraw.Draw(img)
    bg, fg, ac = pal["bg"], pal["fg"], pal["accent"]
    fq, ql = wrap(d, s["quote"], 54, True, W - 2 * MARGIN - 40, 4)
    lh = fq.size * 1.25
    block = lh * len(ql) + (60 if s.get("by") else 0)
    y = (H - block) / 2
    text_line(img, (MARGIN - 6, y - 110), "“", font(140, True), ac, bg, reveal(t, 0.0))
    for i, ln in enumerate(ql):
        text_line(img, (MARGIN + 40, y + i * lh), ln, fq, fg, bg, reveal(t, 0.15 + i * 0.1))
    if s.get("by"):
        text_line(img, (MARGIN + 40, y + len(ql) * lh + 18), "– " + s["by"], font(32, False), ac, bg, reveal(t, 0.5 + 0.1 * len(ql)))


DRAW = {
    "title": scene_title,
    "closing": lambda img, s, t, pal: scene_title(img, s, t, pal, closing=True),
    "bullets": scene_bullets,
    "stat": scene_stat,
    "bars": scene_bars,
    "quote": scene_quote,
}
FADE = 0.25  # crossfade between scenes, seconds
_bg_cache: dict = {}


def background(pal: dict, tsec: float) -> Image.Image:
    """The backdrop: a vertical gradient from the bg colour, lifted a little at the top, with a soft
    accent glow that drifts slowly across the frame. Built once, shifted per frame."""
    key = (pal["bg"], pal["accent"])
    if key not in _bg_cache:
        top = mix(pal["bg"], (255, 255, 255), 0.06 if _lum(pal["bg"]) < 0.5 else -0.0)
        grad = Image.new("RGB", (1, H))
        for y in range(H):
            grad.putpixel((0, y), mix(top, pal["bg"], y / H))
        base = grad.resize((W, H))
        glow = Image.new("L", (W, H), 0)
        ImageDraw.Draw(glow).ellipse([W * 0.55, -H * 0.35, W * 1.25, H * 0.75], fill=70)
        glow = glow.filter(ImageFilter.GaussianBlur(120))
        _bg_cache[key] = (base, glow)
    base, glow = _bg_cache[key]
    img = base.copy()
    shift = int(-60 * math.sin(tsec / 10 * math.pi))
    tint = Image.new("RGB", (W, H), pal["accent"])
    img.paste(tint, (0, 0), glow.transform((W, H), Image.AFFINE, (1, 0, shift, 0, 1, 0)))
    return img


def frame(plan: dict, i: int) -> Image.Image:
    pal = plan["_palette"]
    tsec = i / FPS
    starts, acc = [], 0.0
    for s in plan["scenes"]:
        starts.append(acc)
        acc += s["seconds"]
    k = max(j for j, st in enumerate(starts) if st <= tsec + 1e-9)
    s = plan["scenes"][k]
    img = background(pal, tsec)
    DRAW[s["type"]](img, s, tsec - starts[k], pal)
    end = starts[k] + s["seconds"]
    if k + 1 < len(plan["scenes"]) and end - tsec < FADE:
        nxt = background(pal, tsec)
        DRAW[plan["scenes"][k + 1]["type"]](nxt, plan["scenes"][k + 1], 0.0, pal)
        img = Image.blend(img, nxt, 1 - (end - tsec) / FADE)
    # A thin progress line along the bottom edge.
    dr = ImageDraw.Draw(img)
    dr.rectangle([0, H - 6, int(W * tsec / plan["_total"]), H], fill=pal["accent"])
    return img


def ffmpeg_path() -> str:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        sys.exit("no ffmpeg: install it with `python3 -m pip install --target /tmp/video/py imageio-ffmpeg` "
                 "and run with PYTHONPATH=/tmp/video/py")


def render(plan: dict, out: str, poster: str | None) -> None:
    n = int(round(plan["_total"] * FPS))
    cmd = [ffmpeg_path(), "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
           "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
           "-pix_fmt", "yuv420p", "-movflags", "+faststart", out]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    try:
        for i in range(n):
            p.stdin.write(frame(plan, i).tobytes())
    finally:
        p.stdin.close()
    if p.wait() != 0:
        sys.exit("ffmpeg failed")
    if poster:
        # The first scene, fully in.
        frame(plan, min(n - 1, int(plan["scenes"][0]["seconds"] * FPS * 0.8))).save(poster)
    print(json.dumps({"video": out, "poster": poster, "seconds": plan["_total"], "frames": n, "size": [W, H]}))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("plan")
    ap.add_argument("out", nargs="?")
    ap.add_argument("--poster")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    try:
        plan = load_plan(a.plan)
        if a.check or not a.out:
            # Lay out every scene once, so text that does not fit fails here.
            for j, s in enumerate(plan["scenes"]):
                DRAW[s["type"]](Image.new("RGB", (W, H)), s, s["seconds"], plan["_palette"])
            print(json.dumps({"ok": True, "seconds": plan["_total"], "scenes": [s["type"] for s in plan["scenes"]]}))
            return
        render(plan, a.out, a.poster)
    except PlanError as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        sys.exit(2)


if __name__ == "__main__":
    main()
