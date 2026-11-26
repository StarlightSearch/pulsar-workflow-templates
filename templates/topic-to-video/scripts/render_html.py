"""
Renders a video page (HTML with one paused GSAP timeline, see assets/stage.js)
to an MP4 by seeking the timeline frame by frame in headless Chromium.

    python3 render_html.py page.html --check            lint the page, write stills.png beside it
    python3 render_html.py page.html out.mp4 [--poster poster.png]

--check seeks through the whole video and reports, with the time each starts:
script errors, text that leaves the frame or overflows its box, text that
overlaps other text, icons whose name does not exist, and a length outside
8 to 12.5 s. It also writes stills.png (a contact sheet of 8 frames) next to
the page. Fix everything it reports, then render.

Needs Playwright for Python and its Chromium (scripts/setup_browser.sh sets
both up and writes /tmp/video-browser-env.sh to source first), Pillow, and
ffmpeg on PATH or from the imageio-ffmpeg wheel.
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import os
import shutil
import subprocess
import sys

W, H, FPS = 1280, 720, 30

LINT_JS = r"""
() => {
  const stage = document.getElementById('stage');
  if (!stage) return [{kind: 'no_stage', text: 'the page has no #stage element'}];
  const sb = stage.getBoundingClientRect();
  const out = [];
  const shown = (el) => {
    let a = 1;
    for (let e = el; e && e.nodeType === 1; e = e.parentElement) {
      const cs = getComputedStyle(e);
      if (cs.display === 'none' || cs.visibility === 'hidden') return 0;
      a *= parseFloat(cs.opacity);
      if (a < 0.35) return 0;
    }
    return a;
  };
  const texts = [];
  for (const el of stage.querySelectorAll('*')) {
    if (el.closest('svg') && el.tagName.toLowerCase() !== 'text') continue;
    const own = [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim());
    if (el.classList.contains('ph') && !own) {
      const c = getComputedStyle(el, '::before').content;
      if (!c || c === 'none' || c === 'normal' || c === '""')
        out.push({kind: 'unknown_icon', text: [...el.classList].join(' ')});
      continue;
    }
    if (!own || !shown(el)) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) continue;
    const label = el.textContent.trim().slice(0, 40);
    const m = 12;
    if (r.left < sb.left + m || r.top < sb.top + m || r.right > sb.right - m || r.bottom > sb.bottom - m)
      out.push({kind: 'off_frame', text: label});
    if (el.scrollWidth > el.clientWidth + 2 && getComputedStyle(el).overflow !== 'visible')
      out.push({kind: 'overflows_box', text: label});
    texts.push({el, r, label});
  }
  for (let i = 0; i < texts.length; i++) for (let j = i + 1; j < texts.length; j++) {
    const a = texts[i], b = texts[j];
    if (a.el.contains(b.el) || b.el.contains(a.el)) continue;
    if (a.el.closest('.scene') !== b.el.closest('.scene')) continue;  // a scene change crossing over is fine
    const ix = Math.min(a.r.right, b.r.right) - Math.max(a.r.left, b.r.left);
    const iy = Math.min(a.r.bottom, b.r.bottom) - Math.max(a.r.top, b.r.top);
    if (ix <= 0 || iy <= 0) continue;
    const small = Math.min(a.r.width * a.r.height, b.r.width * b.r.height);
    if (ix * iy > 0.15 * small) out.push({kind: 'text_overlap', text: a.label + ' / ' + b.label});
  }
  return out;
}
"""


class PageError(RuntimeError):
    pass


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


def open_page(p, page_path: str):
    exe = os.environ.get("VIDEO_CHROME") or None
    browser = p.chromium.launch(executable_path=exe, args=["--no-sandbox", "--font-render-hinting=none",
                                                            "--disable-gpu", "--hide-scrollbars"])
    page = browser.new_page(viewport={"width": W, "height": H}, device_scale_factor=1)
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e).splitlines()[0][:200]))
    page.on("console", lambda m: errors.append(m.text[:200]) if m.type == "error" else None)
    page.on("requestfailed", lambda r: errors.append(f"could not load {os.path.basename(r.url)}"))
    page.goto("file://" + os.path.abspath(page_path) + "?render")
    try:
        page.wait_for_function("window.__ready === true", timeout=20000, polling=100)
    except Exception:
        raise PageError("the page never called Stage.ready(tl): " + ("; ".join(errors[:3]) or "no script errors seen"))
    duration = float(page.evaluate("window.__duration"))
    return browser, page, duration, errors


def seek(page, t: float) -> None:
    page.evaluate("(t) => { window.__seek(t); }", t)


def check(page_path: str) -> dict:
    from playwright.sync_api import sync_playwright
    from PIL import Image

    problems: dict[tuple, float] = {}
    with sync_playwright() as p:
        browser, page, duration, errors = open_page(p, page_path)
        if not 8.0 <= duration <= 12.5:
            problems[("length", f"the timeline is {duration:.2f} s; make it 8 to 12.5 s")] = 0.0
        # A problem counts once it lasts two samples in a row (0.25 s apart): text still moving
        # into place may cross something for a moment. An unknown icon counts at once.
        t, last = 0.0, set()
        while t <= duration + 1e-6:
            seek(page, t)
            now = {(pr["kind"], pr["text"]) for pr in page.evaluate(LINT_JS)}
            for key in now:
                if key in last or key[0] == "unknown_icon":
                    problems.setdefault(key, round(t - (0.25 if key in last else 0), 2))
            last = now
            t += 0.25
        # Stills: 8 frames across the video, two rows of four.
        shots = []
        for k in range(8):
            seek(page, duration * (k + 0.5) / 8)
            shots.append(Image.open(io.BytesIO(page.screenshot(type="png"))).convert("RGB").resize((640, 360)))
        browser.close()
    sheet = Image.new("RGB", (640 * 4, 360 * 2), "white")
    for k, im in enumerate(shots):
        sheet.paste(im, ((k % 4) * 640, (k // 4) * 360))
    stills = os.path.join(os.path.dirname(os.path.abspath(page_path)), "stills.png")
    sheet.save(stills)
    for e in dict.fromkeys(errors):
        problems.setdefault(("script_error", e), 0.0)
    listed = [{"at": at, "kind": k, "text": txt} for (k, txt), at in sorted(problems.items(), key=lambda x: x[1])]
    return {"ok": not listed, "seconds": round(duration, 2), "stills": stills, "problems": listed[:30]}


def render(page_path: str, out: str, poster: str | None) -> dict:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser, page, duration, errors = open_page(p, page_path)
        if not 8.0 <= duration <= 12.5:
            raise PageError(f"the timeline is {duration:.2f} s; make it 8 to 12.5 s")
        n = int(round(duration * FPS))
        cmd = [ffmpeg_path(), "-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", str(FPS), "-c:v", "mjpeg",
               "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "21", "-pix_fmt", "yuv420p",
               "-movflags", "+faststart", out]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        # Straight through DevTools at JPEG quality 95: about 4x faster than Playwright's PNG
        # screenshots, and the H.264 pass that follows loses more than this does.
        cdp = page.context.new_cdp_session(page)
        try:
            for i in range(n):
                seek(page, i / FPS)
                shot = cdp.send("Page.captureScreenshot", {"format": "jpeg", "quality": 95, "optimizeForSpeed": True})
                proc.stdin.write(base64.b64decode(shot["data"]))
        finally:
            proc.stdin.close()
        if proc.wait() != 0:
            raise PageError("ffmpeg failed")
        if poster:
            seek(page, min(duration, 1.8))
            page.screenshot(path=poster, type="png")
        browser.close()
    return {"video": out, "poster": poster, "seconds": round(n / FPS, 2), "frames": n, "size": [W, H]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("page")
    ap.add_argument("out", nargs="?")
    ap.add_argument("--poster")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    try:
        if a.check or not a.out:
            res = check(a.page)
            print(json.dumps(res, indent=1))
            sys.exit(0 if res["ok"] else 2)
        print(json.dumps(render(a.page, a.out, a.poster)))
    except PageError as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        sys.exit(2)


if __name__ == "__main__":
    main()
