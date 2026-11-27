"""
Renders a short motion-graphics video from a scene plan (JSON). The run writes
the words and picks the scene types; this script owns the motion: kinetic
type, a living background, a slow camera push and real transitions, so every
video looks designed whatever the topic.

    python3 render_video.py plan.json out.mp4 [--poster poster.png] [--check]

--check validates the plan and lays out every scene without rendering.

The plan:

    {
      "title": "Why bees matter",
      "style": "midnight",                                   (optional, see STYLES)
      "palette": {"bg": "#0e1a1f", "fg": "#ffffff", "accent": "#3ec5d3"},   (optional overrides)
      "scenes": [
        {"type": "title",   "seconds": 2.2, "kicker": "Nature", "headline": "Why bees matter", "sub": "In ten seconds"},
        {"type": "word",    "seconds": 1.6, "word": "Pollination", "sub": "is how most plants make seeds"},
        {"type": "stat",    "seconds": 2.2, "value": 75, "suffix": "%", "label": "of leading food crops benefit from pollinators"},
        {"type": "steps",   "seconds": 2.2, "heading": "How it works", "steps": ["Visit flower", "Carry pollen", "Seeds form"]},
        {"type": "closing", "seconds": 1.8, "headline": "Protect them.", "sub": "Plant flowers"}
      ]
    }

Scene types:
  title    headline, optional kicker (a small label above) and sub
  word     one big word or very short phrase, optional sub
  bullets  heading, 1 to 4 items
  steps    heading, 2 to 4 steps in order (drawn on a timeline)
  stat     value, optional prefix/suffix/decimals, label (a % from 0 to 100 also gets a ring)
  bars     heading, 2 to 6 [label, value] pairs (the largest is highlighted)
  compare  optional heading, left and right, each {"label", "text"}
  quote    quote, optional by
  closing  headline, optional sub (drawn as a button)

Any scene may set "transition" (how it enters): wipe, push, zoom or cut;
otherwise they rotate. Scene seconds add up to 8 to 12 s. Text is wrapped and
shrunk to fit; overlong text is an error, not cut off.

Styles: midnight (default), sunrise, neon, paper. A palette's colours override
the style's; fg must contrast 4.5:1 with bg and accent 3:1.

Needs Pillow and numpy (both in the image) and ffmpeg: the ffmpeg binary on
PATH, else the one bundled with the imageio-ffmpeg wheel (install it with
`pip install --target /tmp/video/py imageio-ffmpeg` and set PYTHONPATH).
Uses the Geist fonts beside this script (fonts/, SIL OFL 1.1), falling back to
Noto or DejaVu for text Geist cannot draw.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H, FPS = 1280, 720, 30
MARGIN = 110
TRANSITION = 0.5  # seconds at the start of a scene while it replaces the previous one
LIMITS = {"headline": 60, "sub": 70, "kicker": 24, "heading": 50, "item": 48, "label": 80, "quote": 160,
          "by": 40, "bar_label": 14, "word": 18, "step": 28, "side_label": 24, "side_text": 70}
TRANSITIONS = ("wipe", "push", "zoom", "cut")

STYLES = {
    "midnight": {"bg": "#0b1620", "bg2": "#12324a", "fg": "#ffffff", "accent": "#3ec5d3", "accent2": "#7b6cf6"},
    "sunrise": {"bg": "#1c0f1e", "bg2": "#4a1a34", "fg": "#fff7ef", "accent": "#ffa74f", "accent2": "#ff4f78"},
    "neon": {"bg": "#08061c", "bg2": "#1e1150", "fg": "#ffffff", "accent": "#c6ff3d", "accent2": "#ff3dc8"},
    "paper": {"bg": "#f6f1e7", "bg2": "#e7dcc6", "fg": "#18181c", "accent": "#c4401b", "accent2": "#2e7fa8"},
}

HERE = os.path.dirname(os.path.abspath(__file__))
GEIST = {"black": "Geist-Black.ttf", "bold": "Geist-Bold.ttf", "medium": "Geist-Medium.ttf"}
FALLBACK = {
    "black": ["NotoSans-Black.ttf", "NotoSans-ExtraBold.ttf", "NotoSans-Bold.ttf", "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf"],
    "bold": ["NotoSans-Bold.ttf", "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf"],
    "medium": ["NotoSans-Medium.ttf", "NotoSans-Regular.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf"],
}
FONT_DIRS = [os.path.join(HERE, "..", "fonts"), "/usr/share/fonts", "/usr/local/share/fonts", os.path.expanduser("~/.fonts")]


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
    if not drawable(v):
        raise PlanError(f"'{key}' has characters no font on this machine can draw ({v[:40]}): "
                        "write it in English or another language these fonts cover")
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


def _side(scene: dict, key: str) -> None:
    side = scene.get(key)
    if not isinstance(side, dict):
        raise PlanError(f"compare scene needs '{key}': {{\"label\", \"text\"}}")
    _text({"type": "compare", "side_label": side.get("label")}, "side_label")
    _text({"type": "compare", "side_text": side.get("text")}, "side_text", required=False)


def load_plan(path: str) -> dict:
    with open(path) as f:
        plan = json.load(f)
    scenes = plan.get("scenes")
    if not isinstance(scenes, list) or not 3 <= len(scenes) <= 7:
        raise PlanError("the plan needs 3 to 7 scenes")
    total = 0.0
    for s in scenes:
        t = s.get("type")
        secs = s.get("seconds")
        if not isinstance(secs, (int, float)) or not 1.0 <= secs <= 4.0:
            raise PlanError(f"{t} scene: seconds must be 1 to 4")
        total += secs
        tr = s.get("transition")
        if tr is not None and tr not in TRANSITIONS:
            raise PlanError(f"{t} scene: transition must be one of {', '.join(TRANSITIONS)}")
        if t in ("title", "closing"):
            _text(s, "headline")
            _text(s, "sub", required=False)
            if t == "title":
                _text(s, "kicker", required=False)
        elif t == "word":
            _text(s, "word")
            _text(s, "sub", required=False)
        elif t == "bullets":
            _text(s, "heading")
            items = s.get("items")
            if not isinstance(items, list) or not 1 <= len(items) <= 4:
                raise PlanError("bullets scene needs 1 to 4 items")
            for it in items:
                _text({"type": t, "item": it}, "item")
        elif t == "steps":
            _text(s, "heading")
            steps = s.get("steps")
            if not isinstance(steps, list) or not 2 <= len(steps) <= 4:
                raise PlanError("steps scene needs 2 to 4 steps")
            for st in steps:
                _text({"type": t, "step": st}, "step")
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
        elif t == "compare":
            _text(s, "heading", required=False)
            _side(s, "left")
            _side(s, "right")
        elif t == "quote":
            _text(s, "quote")
            _text(s, "by", required=False)
        else:
            raise PlanError(f"unknown scene type {t!r}")
    if not 8.0 <= total <= 12.0:
        raise PlanError(f"scenes add up to {total:g} s; make it 8 to 12 s")
    style = plan.get("style") or "midnight"
    if style not in STYLES:
        raise PlanError(f"style must be one of {', '.join(STYLES)}")
    base = STYLES[style]
    pal = plan.get("palette") or {}
    p = {k: _color(pal.get(k), base[k]) for k in base}
    # A custom bg with the style's second background colour would clash: derive it from the bg instead.
    if "bg" in pal and "bg2" not in pal:
        p["bg2"] = mix(p["bg"], p["accent"], 0.18)
    if "accent" in pal and "accent2" not in pal:
        p["accent2"] = p["accent"]
    if _contrast(p["fg"], p["bg"]) < 4.5:
        raise PlanError("the palette's fg and bg need a contrast of at least 4.5:1")
    if _contrast(p["accent"], p["bg"]) < 3.0:
        raise PlanError("the palette's accent and bg need a contrast of at least 3:1")
    p["light"] = _lum(p["bg"]) > 0.5
    plan["_palette"] = p
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


# ---------------------------------------------------------------- fonts

_font_cache: dict = {}
_path_cache: dict = {}
_cmap_cache: dict = {}


def _find(name: str) -> str | None:
    if name not in _path_cache:
        _path_cache[name] = None
        for d in FONT_DIRS:
            if not os.path.isdir(d):
                continue
            for root, _dirs, files in os.walk(d):
                if name in files:
                    _path_cache[name] = os.path.join(root, name)
                    break
            if _path_cache[name]:
                break
    return _path_cache[name]


def _covers(path: str, text: str) -> bool:
    if path not in _cmap_cache:
        try:
            from fontTools.ttLib import TTFont

            _cmap_cache[path] = set(TTFont(path, lazy=True).getBestCmap() or {})
        except ImportError:
            _cmap_cache[path] = "pil"
        except Exception:
            _cmap_cache[path] = set()
    cmap = _cmap_cache[path]
    chars = {c for c in text if not c.isspace()}
    if cmap == "pil":
        # No fontTools: a missing glyph draws the same box as a code point no font has.
        try:
            f = ImageFont.truetype(path, 24)
        except OSError:
            return False
        def ink(c: str) -> bytes:
            im = Image.new("L", (48, 48))
            ImageDraw.Draw(im).text((8, 8), c, font=f, fill=255)
            return im.tobytes()

        missing = ink("\U0010fffd")
        return all(ink(c) != missing for c in chars)
    return all(ord(c) in cmap for c in chars)


_all_fonts: list | None = None
_script_cache: dict = {}
WEIGHT_WORDS = {"black": ("Black", "ExtraBold", "Bold"), "bold": ("Bold", "SemiBold"), "medium": ("Medium", "Regular")}


def _any_font_for(text: str, weight: str) -> str | None:
    """For text the usual fonts cannot draw (another script): any installed font that can,
    preferring one whose name matches the weight. None when nothing on the machine covers it."""
    global _all_fonts
    key = (frozenset(c for c in text if not c.isspace()), weight)
    if key in _script_cache:
        return _script_cache[key]
    if _all_fonts is None:
        _all_fonts = []
        for d in FONT_DIRS[1:]:
            if os.path.isdir(d):
                for root, _dirs, files in os.walk(d):
                    _all_fonts += [os.path.join(root, n) for n in sorted(files) if n.lower().endswith((".ttf", ".otf"))]
    found = [p for p in _all_fonts if _covers(p, text)]
    found.sort(key=lambda p: next((i for i, w in enumerate(WEIGHT_WORDS[weight]) if w in os.path.basename(p)), 9))
    _script_cache[key] = found[0] if found else None
    return _script_cache[key]


def drawable(text: str) -> bool:
    return _pick(text, "bold") is not None


def _pick(text: str, weight: str) -> str | None:
    for name in [GEIST[weight]] + FALLBACK[weight]:
        p = _find(name)
        if p and _covers(p, text):
            return p
    return _any_font_for(text, weight)


def font(size: int, weight: str = "bold", text: str = ""):
    """Geist at `weight` when it can draw `text`, else the first fallback that can."""
    size = max(8, int(size))
    choices = [GEIST[weight]] + FALLBACK[weight]
    path = _pick(text, weight)
    if path is None:
        path = next((p for p in (_find(n) for n in choices) if p), None)
    key = (path, size)
    if key not in _font_cache:
        _font_cache[key] = ImageFont.truetype(path, size) if path else ImageFont.load_default(size)
    return _font_cache[key]


_measure = ImageDraw.Draw(Image.new("L", (1, 1)))


def tw(text: str, f) -> float:
    return _measure.textlength(text, font=f)


def wrap(text: str, size: int, weight: str, width: float, max_lines: int, min_size: int = 18):
    """Wraps text to `width`, shrinking the size until it fits in `max_lines`."""
    while size >= min_size:
        f = font(size, weight, text)
        lines, cur = [], ""
        for w in text.split():
            trial = (cur + " " + w).strip()
            if tw(trial, f) <= width:
                cur = trial
            else:
                if cur:
                    lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        if len(lines) <= max_lines and all(tw(ln, f) <= width for ln in lines):
            return f, lines
        size -= 4
    raise PlanError(f"text does not fit: {text[:40]}")


# ---------------------------------------------------------------- motion helpers

def clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def ease_out(x: float) -> float:
    x = clamp(x)
    return 1 - (1 - x) ** 3


def ease_out_expo(x: float) -> float:
    x = clamp(x)
    return 1.0 if x >= 1 else 1 - 2 ** (-10 * x)


def ease_back(x: float, s: float = 1.6) -> float:
    x = clamp(x)
    x -= 1
    return x * x * ((s + 1) * x + s) + 1


def ease_in_out(x: float) -> float:
    x = clamp(x)
    return 4 * x ** 3 if x < 0.5 else 1 - (-2 * x + 2) ** 3 / 2


def prog(t: float, start: float, dur: float) -> float:
    return clamp((t - start) / dur)


def mix(a, b, t: float):
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def rgba(c, a: float) -> tuple:
    return (c[0], c[1], c[2], int(255 * clamp(a)))


def over(layer: Image.Image, img: Image.Image, x: float, y: float) -> None:
    """Alpha-composites img onto layer at (x, y), clipping at the edges."""
    x, y = int(round(x)), int(round(y))
    l, t = max(0, -x), max(0, -y)
    r, b = min(img.width, W - x), min(img.height, H - y)
    if r <= l or b <= t:
        return
    layer.alpha_composite(img.crop((l, t, r, b)) if (l, t, r, b) != (0, 0, img.width, img.height) else img, (x + l, y + t))


def kinetic(layer, x, y, text, f, color, t, start, stagger=0.07, dur=0.55, align="left", width=None):
    """One line of text whose words rise into place from behind a mask, one after another.
    Returns the line's width."""
    words = text.split()
    sp = tw(" ", f)
    widths = [tw(w, f) for w in words]
    total = sum(widths) + sp * (len(words) - 1)
    if align == "center":
        x = x + ((width or W) - total) / 2 - (0 if width else x)
    asc, desc = f.getmetrics()
    box_h = asc + desc + 6
    cx = x
    for i, w in enumerate(words):
        e = ease_out_expo(prog(t, start + i * stagger, dur))
        if e > 0:
            img = Image.new("RGBA", (int(widths[i]) + 12, box_h), (0, 0, 0, 0))
            ImageDraw.Draw(img).text((2, 3 + (1 - e) * box_h * 0.95), w, font=f, fill=rgba(color, min(1.0, e * 1.6)))
            over(layer, img, cx - 2, y - 3)
        cx += widths[i] + sp
    return total


def pop_text(layer, cx, cy, text, f, color, s: float, alpha: float = 1.0):
    """Text centred on (cx, cy), scaled by s (an overshooting pop)."""
    if s <= 0.01 or alpha <= 0:
        return
    w = int(tw(text, f)) + 16
    asc, desc = f.getmetrics()
    img = Image.new("RGBA", (w, asc + desc + 12), (0, 0, 0, 0))
    ImageDraw.Draw(img).text((8, 6), text, font=f, fill=rgba(color, alpha))
    if abs(s - 1) > 0.01:
        img = img.resize((max(1, int(img.width * s)), max(1, int(img.height * s))), Image.BICUBIC)
    over(layer, img, cx - img.width / 2, cy - img.height / 2)


# ---------------------------------------------------------------- scenes
# Each draws onto a transparent RGBA layer at scene-local time t (it may be past the scene's end).

def scene_title(layer, s, t, p, dur):
    d = ImageDraw.Draw(layer)
    fg, ac, ac2 = p["fg"], p["accent"], p["accent2"]
    # A big ring drifting in on the right, behind the type.
    g = ease_out(prog(t, 0.0, 1.2))
    r = 300 + 40 * g + 12 * t
    cx, cy = W - 170 + 60 * (1 - g), H / 2 + 30
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=rgba(ac2, 0.35 * g), width=3)
    r2 = r * 0.62
    d.ellipse([cx - r2, cy - r2, cx + r2, cy + r2], outline=rgba(ac, 0.5 * g), width=2)

    f, lines = wrap(s["headline"], 112, "black", W - 2 * MARGIN - 80, 2, 40)
    lh = f.size * 1.04
    kicker = s.get("kicker")
    fk = font(26, "bold", kicker or "")
    block = lh * len(lines) + (78 if s.get("sub") else 0) + (56 if kicker else 0)
    y = (H - block) / 2
    if kicker:
        e = ease_out(prog(t, 0.05, 0.5))
        kw = tw(kicker.upper(), fk) + 36
        d.rounded_rectangle([MARGIN, y, MARGIN + kw * e, y + 40], radius=20, fill=rgba(ac, 0.18 * e), outline=rgba(ac, e), width=2)
        if e > 0.5:
            d.text((MARGIN + 18, y + 7), kicker.upper(), font=fk, fill=rgba(ac, (e - 0.5) * 2))
        y += 56
    for i, ln in enumerate(lines):
        kinetic(layer, MARGIN, y + i * lh, ln, f, fg, t, 0.12 + i * 0.16)
    yb = y + len(lines) * lh + f.size * 0.16
    bar = ease_out_expo(prog(t, 0.45, 0.7))
    d.rectangle([MARGIN, yb, MARGIN + 150 * bar, yb + 8], fill=ac)
    if s.get("sub"):
        fs, sl = wrap(s["sub"], 40, "medium", W - 2 * MARGIN, 1)
        kinetic(layer, MARGIN, yb + 28, sl[0], fs, mix(p["bg"], fg, 0.78), t, 0.6, stagger=0.05)


def scene_closing(layer, s, t, p, dur):
    d = ImageDraw.Draw(layer)
    fg, ac = p["fg"], p["accent"]
    f, lines = wrap(s["headline"], 104, "black", W - 2 * MARGIN, 2, 40)
    lh = f.size * 1.05
    block = lh * len(lines) + (110 if s.get("sub") else 0)
    y = (H - block) / 2
    for i, ln in enumerate(lines):
        e = ease_back(prog(t, 0.08 + i * 0.14, 0.6), 1.3)
        a = clamp(prog(t, 0.08 + i * 0.14, 0.25))
        pop_text(layer, W / 2, y + i * lh + lh / 2, ln, f, fg, 0.6 + 0.4 * e, a)
    if s.get("sub"):
        fs = font(34, "bold", s["sub"])
        e = ease_back(prog(t, 0.45, 0.55), 1.8)
        if e > 0:
            bw, bh = tw(s["sub"], fs) + 70, 72
            bw2, bh2 = bw * e, bh * e
            cy = y + len(lines) * lh + 40 + bh / 2
            d.rounded_rectangle([W / 2 - bw2 / 2, cy - bh2 / 2, W / 2 + bw2 / 2, cy + bh2 / 2], radius=bh2 / 2, fill=ac)
            if e > 0.7:
                ink = p["bg"] if _contrast(p["bg"], ac) >= _contrast(fg, ac) else fg
                pop_text(layer, W / 2, cy, s["sub"], fs, ink, 1.0, clamp((e - 0.7) / 0.3))
    # Light rays: thin accent lines sweeping out from the centre.
    g = ease_out(prog(t, 0.2, 1.0))
    for k in range(12):
        ang = k / 12 * math.tau + t * 0.15
        r0, r1 = 420 + 40 * g, 420 + 140 * g
        d.line([W / 2 + math.cos(ang) * r0, H / 2 + math.sin(ang) * r0 * 0.6,
                W / 2 + math.cos(ang) * r1, H / 2 + math.sin(ang) * r1 * 0.6], fill=rgba(ac, 0.35 * g), width=3)


def scene_word(layer, s, t, p, dur):
    word = s["word"]
    size = 300
    f = font(size, "black", word)
    while tw(word, f) > W - 2 * MARGIN and size > 60:
        size -= 10
        f = font(size, "black", word)
    asc, desc = f.getmetrics()
    sub = s.get("sub")
    cy = H / 2 - (40 if sub else 0)
    # Letters drop in one by one, with a little overshoot.
    total = tw(word, f)
    x = (W - total) / 2
    n = max(1, len(word))
    stagger = min(0.05, 0.5 / n)
    for i, ch in enumerate(word):
        cw = tw(ch, f)
        e = ease_back(prog(t, 0.05 + i * stagger, 0.5), 1.4)
        a = clamp(prog(t, 0.05 + i * stagger, 0.2))
        if a > 0 and not ch.isspace():
            img = Image.new("RGBA", (int(cw) + 20, asc + desc + 20), (0, 0, 0, 0))
            ImageDraw.Draw(img).text((10, 10), ch, font=f, fill=rgba(p["fg"], a))
            over(layer, img, x - 10, cy - (asc + desc) / 2 - 10 - (1 - e) * 90)
        x += cw
    d = ImageDraw.Draw(layer)
    line = ease_out_expo(prog(t, 0.35, 0.7))
    yl = cy + (asc + desc) / 2 + 6
    d.rectangle([W / 2 - total / 2 * line, yl, W / 2 + total / 2 * line, yl + 10], fill=p["accent"])
    if sub:
        fs, sl = wrap(sub, 40, "medium", W - 2 * MARGIN, 1)
        kinetic(layer, 0, yl + 40, sl[0], fs, mix(p["bg"], p["fg"], 0.78), t, 0.55, stagger=0.05, align="center")


def scene_bullets(layer, s, t, p, dur):
    d = ImageDraw.Draw(layer)
    fg, ac = p["fg"], p["accent"]
    fh, hl = wrap(s["heading"], 70, "black", W - 2 * MARGIN, 1)
    items = s["items"]
    fi = min((wrap(it, 46, "bold", W - 2 * MARGIN - 130, 1)[0] for it in items), key=lambda f: f.size)
    row = fi.size * 2.1
    top = (H - (fh.size * 1.7 + row * len(items))) / 2
    kinetic(layer, MARGIN, top, hl[0], fh, fg, t, 0.05)
    fn = font(26, "bold", "0123456789")
    for i, it in enumerate(items):
        st = 0.35 + i * 0.22
        y = top + fh.size * 1.7 + i * row
        e = ease_back(prog(t, st, 0.45), 1.8)
        if e > 0:
            r = 30 * e
            cx, cy = MARGIN + 30, y + fi.size * 0.62
            d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=ac)
            if e > 0.6:
                ink = p["bg"] if _contrast(p["bg"], ac) >= _contrast(fg, ac) else fg
                pop_text(layer, cx, cy, f"{i + 1:02d}", fn, ink, 1.0, clamp((e - 0.6) / 0.4))
        kinetic(layer, MARGIN + 90, y, items[i], fi, fg, t, st + 0.08, stagger=0.05)
        ln = ease_out_expo(prog(t, st + 0.1, 0.7))
        if ln > 0 and i < len(items) - 1:
            yy = y + row - fi.size * 0.55
            d.line([MARGIN + 90, yy, MARGIN + 90 + (W - 2 * MARGIN - 90) * ln, yy], fill=rgba(fg, 0.12), width=2)


def scene_steps(layer, s, t, p, dur):
    d = ImageDraw.Draw(layer)
    fg, ac = p["fg"], p["accent"]
    fh, hl = wrap(s["heading"], 66, "black", W - 2 * MARGIN, 1)
    kinetic(layer, MARGIN, 120, hl[0], fh, fg, t, 0.05)
    steps = s["steps"]
    n = len(steps)
    slot = (W - 2 * MARGIN) / n
    ly = 360
    line = ease_in_out(prog(t, 0.25, 0.4 + 0.25 * n))
    x0, x1 = MARGIN + slot / 2, W - MARGIN - slot / 2
    d.line([x0, ly, x1, ly], fill=rgba(fg, 0.18), width=4)
    d.line([x0, ly, x0 + (x1 - x0) * line, ly], fill=ac, width=6)
    fl = min((wrap(st, 34, "bold", slot - 30, 2)[0] for st in steps), key=lambda f: f.size)
    fn = font(30, "black", "0123456789")
    for i, st in enumerate(steps):
        cx = MARGIN + slot * (i + 0.5)
        reach = 0 if n == 1 else i / (n - 1)
        when = 0.25 + (0.4 + 0.25 * n) * reach
        e = ease_back(prog(t, when - 0.05, 0.45), 2.0)
        if e > 0:
            r = 34 * e
            d.ellipse([cx - r - 8, ly - r - 8, cx + r + 8, ly + r + 8], fill=rgba(ac, 0.2))
            d.ellipse([cx - r, ly - r, cx + r, ly + r], fill=ac)
            if e > 0.6:
                ink = p["bg"] if _contrast(p["bg"], ac) >= _contrast(fg, ac) else fg
                pop_text(layer, cx, ly, str(i + 1), fn, ink, 1.0, clamp((e - 0.6) / 0.4))
        _f, lines = wrap(st, fl.size, "bold", slot - 30, 2, fl.size)
        for j, ln in enumerate(lines):
            lw = tw(ln, fl)
            kinetic(layer, cx - lw / 2, ly + 70 + j * fl.size * 1.2, ln, fl, fg, t, when + 0.08 + j * 0.06, stagger=0.04)


def scene_stat(layer, s, t, p, dur):
    d = ImageDraw.Draw(layer)
    fg, ac = p["fg"], p["accent"]
    v = float(s["value"])
    dec = int(s.get("decimals", 0 if v == int(v) else 1))
    pre, suf = str(s.get("prefix", "")), str(s.get("suffix", ""))
    ring = suf.strip() == "%" and 0 <= v <= 100
    c = ease_out_expo(prog(t, 0.1, 1.2))
    final = f"{pre}{v:,.{dec}f}{suf}"
    txt = f"{pre}{v * c:,.{dec}f}{suf}"
    area = (W - 2 * MARGIN - (380 if ring else 0))
    size = 210
    f = font(size, "black", final)
    while tw(final, f) > area and size > 60:
        size -= 10
        f = font(size, "black", final)
    fl, ll = wrap(s["label"], 40, "medium", area, 2)
    asc, desc = f.getmetrics()
    block = asc + desc + 24 + fl.size * 1.3 * len(ll)
    y = (H - block) / 2
    e = ease_back(prog(t, 0.0, 0.5), 1.2)
    a = clamp(prog(t, 0.0, 0.2))
    img = Image.new("RGBA", (int(tw(final, f)) + 40, asc + desc + 20), (0, 0, 0, 0))
    ImageDraw.Draw(img).text((10, 10), txt, font=f, fill=rgba(ac, a))
    if abs(e - 1) > 0.01:
        sc = 0.7 + 0.3 * e
        img = img.resize((max(1, int(img.width * sc)), max(1, int(img.height * sc))), Image.BICUBIC)
    over(layer, img, MARGIN - 10, y - 10 + (asc + desc) * (1 - (0.7 + 0.3 * e)) / 2)
    for i, ln in enumerate(ll):
        kinetic(layer, MARGIN, y + asc + desc + 24 + i * fl.size * 1.3, ln, fl, fg, t, 0.5 + i * 0.12, stagger=0.04)
    if ring:
        cx, cy, r = W - MARGIN - 160, H / 2, 150
        g = ease_out(prog(t, 0.0, 0.5))
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=rgba(fg, 0.12 * g), width=22)
        frac = v / 100 * c
        if frac > 0:
            d.arc([cx - r, cy - r, cx + r, cy + r], -90, -90 + 360 * frac, fill=ac, width=22)
        # The rest of the ring, as a soft second colour.
        fi = font(40, "black", "0123456789%")
        pop_text(layer, cx, cy, f"{v * c:,.{dec}f}%", fi, fg, 1.0, g)


def scene_bars(layer, s, t, p, dur):
    d = ImageDraw.Draw(layer)
    fg, ac = p["fg"], p["accent"]
    fh, hl = wrap(s["heading"], 58, "black", W - 2 * MARGIN, 1)
    kinetic(layer, MARGIN, 80, hl[0], fh, fg, t, 0.05)
    bars = s["bars"]
    top, bottom = 80 + fh.size * 1.9, H - 110
    n = len(bars)
    slot = (W - 2 * MARGIN) / n
    bw = slot * 0.6
    vmax = max(b[1] for b in bars) or 1
    imax = max(range(n), key=lambda i: bars[i][1])
    fl = font(26, "bold", "".join(str(b[0]) for b in bars))
    fv = font(32, "black", "0123456789.,")
    for k in range(4):
        gy = bottom - (bottom - top - 40) * (k + 1) / 4
        gl = ease_out(prog(t, 0.1 + k * 0.05, 0.6))
        d.line([MARGIN, gy, MARGIN + (W - 2 * MARGIN) * gl, gy], fill=rgba(fg, 0.07), width=1)
    d.line([MARGIN, bottom, W - MARGIN, bottom], fill=rgba(fg, 0.35), width=2)
    for i, (label, value) in enumerate(bars):
        g = ease_back(prog(t, 0.3 + i * 0.1, 0.7), 1.3)
        x0 = MARGIN + i * slot + (slot - bw) / 2
        h = max(0.0, (bottom - top - 40) * (value / vmax) * g)
        col = ac if i == imax else mix(p["bg"], ac, 0.45)
        if h > 2:
            d.rounded_rectangle([x0, bottom - h, x0 + bw, bottom], radius=min(12, h / 2), fill=col)
        shown = value * clamp(g)
        val = f"{shown:,.0f}" if value == int(value) else f"{shown:,.1f}"
        if g > 0.05:
            pop_text(layer, x0 + bw / 2, bottom - h - 26, val, fv, fg, 1.0, clamp(g))
        lw = tw(str(label), fl)
        kinetic(layer, x0 + (bw - lw) / 2, bottom + 16, str(label), fl, mix(p["bg"], fg, 0.8), t, 0.2 + i * 0.08)


def scene_compare(layer, s, t, p, dur):
    d = ImageDraw.Draw(layer)
    fg, ac, ac2 = p["fg"], p["accent"], p["accent2"]
    top = 110
    if s.get("heading"):
        fh, hl = wrap(s["heading"], 58, "black", W - 2 * MARGIN, 1)
        kinetic(layer, 0, 90, hl[0], fh, fg, t, 0.05, align="center")
        top = 200
    bottom = H - 90
    mid, gap = W / 2, 80
    half = W / 2 - MARGIN - gap
    # Lay both sides out first, so the pair can sit in the middle of the space.
    sides = []
    for side in (s["left"], s["right"]):
        fl, ll = wrap(side["label"], 70, "black", half, 2, 30)
        ft, tl = wrap(side["text"], 36, "medium", half, 3) if side.get("text") else (None, [])
        hgt = len(ll) * fl.size * 1.1 + (24 + len(tl) * ft.size * 1.3 if tl else 0)
        sides.append((fl, ll, ft, tl, hgt))
    block = max(x[4] for x in sides)
    y0 = top + (bottom - top - block) / 2
    ln = ease_in_out(prog(t, 0.15, 0.6))
    d.line([mid, top, mid, top + (bottom - top) * ln], fill=rgba(fg, 0.2), width=3)
    for k, (fl, ll, ft, tl, _h) in enumerate(sides):
        col = ac if k == 0 else (ac2 if _contrast(ac2, p["bg"]) >= 3 else fg)
        e = ease_out_expo(prog(t, 0.25 + k * 0.15, 0.7))
        off = (1 - e) * (-120 if k == 0 else 120)
        x = MARGIN if k == 0 else mid + gap
        a = clamp(e * 1.4)
        y = y0
        for j, l in enumerate(ll):
            img = Image.new("RGBA", (int(half) + 20, int(fl.size * 1.3)), (0, 0, 0, 0))
            ImageDraw.Draw(img).text((0, 0), l, font=fl, fill=rgba(col, a))
            over(layer, img, x + off, y + j * fl.size * 1.1)
        y += len(ll) * fl.size * 1.1 + 24
        for j, l in enumerate(tl):
            kinetic(layer, x, y + j * ft.size * 1.3, l, ft, mix(p["bg"], fg, 0.85), t, 0.5 + k * 0.15 + j * 0.08, stagger=0.04)
    e = ease_back(prog(t, 0.45, 0.45), 2.2)
    if e > 0:
        cy = top + (bottom - top) / 2
        r = 40 * e
        d.ellipse([mid - r, cy - r, mid + r, cy + r], fill=p["bg"], outline=ac, width=3)
        pop_text(layer, mid, cy, "vs", font(30, "black", "vs"), fg, 1.0, clamp((e - 0.5) * 2))


def scene_quote(layer, s, t, p, dur):
    fg, ac = p["fg"], p["accent"]
    fq, ql = wrap(s["quote"], 58, "bold", W - 2 * MARGIN - 60, 4)
    lh = fq.size * 1.25
    block = lh * len(ql) + (64 if s.get("by") else 0)
    y = (H - block) / 2
    e = ease_back(prog(t, 0.0, 0.6), 1.6)
    pop_text(layer, MARGIN + 30, y - 40, "“", font(220, "black", "“"), ac, 0.4 + 0.6 * e, clamp(e))
    n_words = 0
    for i, ln in enumerate(ql):
        kinetic(layer, MARGIN + 60, y + i * lh, ln, fq, fg, t, 0.15 + n_words * 0.045, stagger=0.045)
        n_words += len(ln.split())
    if s.get("by"):
        fb = font(32, "medium", s["by"])
        yb = y + len(ql) * lh + 22
        g = ease_out_expo(prog(t, 0.3 + n_words * 0.045, 0.6))
        ImageDraw.Draw(layer).rectangle([MARGIN + 60, yb + 18, MARGIN + 60 + 40 * g, yb + 21], fill=ac)
        kinetic(layer, MARGIN + 116, yb, s["by"], fb, ac, t, 0.35 + n_words * 0.045, stagger=0.04)


DRAW = {
    "title": scene_title,
    "closing": scene_closing,
    "word": scene_word,
    "bullets": scene_bullets,
    "steps": scene_steps,
    "stat": scene_stat,
    "bars": scene_bars,
    "compare": scene_compare,
    "quote": scene_quote,
}


# ---------------------------------------------------------------- background

class Backdrop:
    """A living background: a gradient with three soft colour fields drifting on slow orbits, two
    faint rings, a vignette and film grain. Computed at low resolution and scaled up, so it is cheap."""

    LW, LH = 160, 90

    def __init__(self, p: dict, seconds: float):
        self.p = p
        self.seconds = seconds
        yy, xx = np.mgrid[0:self.LH, 0:self.LW].astype(np.float32)
        self.xx, self.yy = xx / self.LH, yy / self.LH  # square units, height = 1
        bg, bg2 = np.array(p["bg"], np.float32), np.array(p["bg2"], np.float32)
        grad = (yy / (self.LH - 1))[..., None]
        self.base = bg2 * (1 - grad) + bg * grad
        strength = 0.28 if p["light"] else 0.5
        self.blobs = [
            (np.array(p["accent"], np.float32), strength, 0.55, (1.35, 0.25, 0.30, 0.18, 0.21, 0.17)),
            (np.array(p["accent2"], np.float32), strength * 0.9, 0.62, (0.35, 0.80, 0.26, 0.16, 0.13, 0.23)),
            (np.array(p["bg2"], np.float32), 0.7, 0.75, (0.95, 0.55, 0.40, 0.25, 0.09, 0.11)),
        ]
        ys, xs = np.mgrid[0:H, 0:W].astype(np.float32)
        dist = np.sqrt(((xs - W / 2) / (W * 0.75)) ** 2 + ((ys - H / 2) / (H * 0.75)) ** 2)
        self.vignette = (1 - 0.32 * np.clip(dist, 0, 1) ** 2.2)[..., None] if not p["light"] else \
            (1 - 0.08 * np.clip(dist, 0, 1) ** 2)[..., None]
        rng = np.random.default_rng(7)
        amp = 3.5 if p["light"] else 4.5
        # Fixed grain: noise that changes every frame would cost the encoder ~6x the file size.
        self.grain = rng.normal(0, amp, (H, W, 1)).astype(np.float32)

    def field(self, tsec: float) -> Image.Image:
        img = self.base.copy()
        for color, s, r, (cx, cy, ax, ay, fx, fy) in self.blobs:
            x = cx + ax * math.sin(tsec * fx * math.tau / 4 + cx * 3)
            y = cy + ay * math.cos(tsec * fy * math.tau / 4 + cy * 5)
            w = (s * np.exp(-((self.xx - x) ** 2 + (self.yy - y) ** 2) / (r * r)))[..., None]
            img = img * (1 - w) + color * w
        out = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)).resize((W, H), Image.BICUBIC)
        # Two faint rings, slowly drifting.
        d = ImageDraw.Draw(out, "RGBA")
        for k, (bx, by, br) in enumerate(((0.12, 0.85, 260), (0.92, 0.12, 190))):
            cx = W * bx + 40 * math.sin(tsec * 0.4 + k)
            cy = H * by + 30 * math.cos(tsec * 0.35 + k * 2)
            d.ellipse([cx - br, cy - br, cx + br, cy + br], outline=rgba(self.p["fg"], 0.06), width=2)
        return out

    def finish(self, frame: Image.Image, i: int) -> Image.Image:
        arr = np.asarray(frame, np.float32) * self.vignette + self.grain
        return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


# ---------------------------------------------------------------- compositing

def content(plan: dict, k: int, t: float) -> Image.Image:
    """Scene k's layer at local time t, with the camera's slow push-in."""
    s = plan["scenes"][k]
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    DRAW[s["type"]](layer, s, t, plan["_palette"], s["seconds"])
    zoom = 1 + 0.04 * ease_in_out(t / (s["seconds"] + TRANSITION))
    return scale(layer, zoom)


def scale(layer: Image.Image, z: float, alpha: float = 1.0) -> Image.Image:
    if abs(z - 1) > 0.002:
        sw, sh = int(W * z), int(H * z)
        big = layer.resize((sw, sh), Image.BILINEAR)
        if z > 1:
            l, t = (sw - W) // 2, (sh - H) // 2
            layer = big.crop((l, t, l + W, t + H))
        else:
            layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            layer.alpha_composite(big, ((W - sw) // 2, (H - sh) // 2))
    if alpha < 1:
        a = layer.getchannel("A").point(lambda v: int(v * alpha))
        layer.putalpha(a)
    return layer


def transition_of(plan: dict, k: int) -> str:
    s = plan["scenes"][k]
    return s.get("transition") or ("wipe", "push", "zoom")[(k - 1) % 3]


def frame(plan: dict, backdrop: Backdrop, i: int) -> Image.Image:
    p = plan["_palette"]
    tsec = i / FPS
    starts, acc = [], 0.0
    for s in plan["scenes"]:
        starts.append(acc)
        acc += s["seconds"]
    k = max(j for j, st in enumerate(starts) if st <= tsec + 1e-9)
    t = tsec - starts[k]
    bg = backdrop.field(tsec).convert("RGBA")
    cur = content(plan, k, t)
    kind = transition_of(plan, k) if k > 0 else "cut"
    if k > 0 and t < TRANSITION and kind != "cut":
        e = ease_in_out(t / TRANSITION)
        prev = content(plan, k - 1, plan["scenes"][k - 1]["seconds"] + t)
        if kind == "push":
            out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            over(out, prev, -W * e, 0)
            over(out, cur, W * (1 - e), 0)
            bg.alpha_composite(out)
        elif kind == "zoom":
            bg.alpha_composite(scale(prev, 1 + 0.35 * e, 1 - e))
            bg.alpha_composite(scale(cur, 0.86 + 0.14 * e, e))
        else:  # wipe: a slanted accent band sweeps across, revealing the new scene behind it
            edge = -260 + (W + 520) * e
            slant = 180
            mask = Image.new("L", (W, H), 0)
            ImageDraw.Draw(mask).polygon([(edge - slant, 0), (W + 400, 0), (W + 400, H), (edge, H)], fill=255)
            bg.alpha_composite(cur)
            prev.putalpha(Image.composite(prev.getchannel("A"), Image.new("L", (W, H), 0), mask))
            # Behind the old scene, the backdrop shows where the new one has not been revealed: cover
            # the new scene there by re-drawing the backdrop under the old one.
            hide = Image.composite(backdrop.field(tsec).convert("RGBA"), Image.new("RGBA", (W, H), (0, 0, 0, 0)), mask)
            bg.alpha_composite(hide)
            bg.alpha_composite(prev)
            band = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            bd = ImageDraw.Draw(band)
            bw = 70 * math.sin(math.pi * e)
            bd.polygon([(edge - slant - bw, 0), (edge - slant, 0), (edge, H), (edge - bw, H)], fill=rgba(p["accent"], 1))
            bd.polygon([(edge - slant - bw * 1.9, 0), (edge - slant - bw * 1.2, 0), (edge - bw * 1.2, H), (edge - bw * 1.9, H)],
                       fill=rgba(p["accent2"], 0.85))
            bg.alpha_composite(band)
    else:
        bg.alpha_composite(cur)
    # A thin progress line along the bottom edge.
    d = ImageDraw.Draw(bg)
    d.rectangle([0, H - 5, int(W * tsec / plan["_total"]), H], fill=rgba(p["accent"], 0.9))
    return backdrop.finish(bg.convert("RGB"), i)


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
    backdrop = Backdrop(plan["_palette"], plan["_total"])
    cmd = [ffmpeg_path(), "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
           "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "21",
           "-pix_fmt", "yuv420p", "-movflags", "+faststart", out]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    try:
        for i in range(n):
            p.stdin.write(frame(plan, backdrop, i).tobytes())
    finally:
        p.stdin.close()
    if p.wait() != 0:
        sys.exit("ffmpeg failed")
    if poster:
        # The first scene, fully in.
        frame(plan, backdrop, min(n - 1, int(plan["scenes"][0]["seconds"] * FPS * 0.85))).save(poster)
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
            # Lay out every scene once, fully in, so text that does not fit fails here.
            for s in plan["scenes"]:
                DRAW[s["type"]](Image.new("RGBA", (W, H)), s, s["seconds"], plan["_palette"], s["seconds"])
            print(json.dumps({"ok": True, "seconds": plan["_total"], "scenes": [s["type"] for s in plan["scenes"]]}))
            return
        render(plan, a.out, a.poster)
    except PlanError as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        sys.exit(2)


if __name__ == "__main__":
    main()
