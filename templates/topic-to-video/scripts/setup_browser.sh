#!/usr/bin/env bash
# Sets up what render_html.py needs, without root, in /tmp: Playwright for Python and its
# headless Chromium, the shared libraries Chromium lacks on this machine (downloaded as .deb
# files and unpacked, found through LD_LIBRARY_PATH), GSAP, and ffmpeg. Safe to re-run.
#
#   bash setup_browser.sh <page folder>
#
# Copies the page helpers (assets/stage.js, assets/icons.css), the fonts and GSAP into the page folder and writes /tmp/video-browser-env.sh, which must be
# sourced before render_html.py. The last line printed is BROWSER_OK or BROWSER_FAILED <reason>.
set -u

DIR="${1:-/tmp/video}"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$DIR/fonts"
cp "$HERE/assets/stage.js" "$HERE/assets/icons.css" "$DIR/"
cp "$HERE"/fonts/*.ttf "$DIR/fonts/"
ENV_FILE=/tmp/video-browser-env.sh
PY=/tmp/video/py
LIBS=/tmp/video/libs
APT=/tmp/video/apt
LIB_PATH="$LIBS/usr/lib/x86_64-linux-gnu:$LIBS/lib/x86_64-linux-gnu"
export PLAYWRIGHT_BROWSERS_PATH=/tmp/video/browsers
export PYTHONPATH="$PY${PYTHONPATH:+:$PYTHONPATH}"
NODE_BIN="$(command -v node || true)"
# Playwright's bundled Node needs libatomic; the machine's own Node does not.
[ -n "$NODE_BIN" ] && export PLAYWRIGHT_NODEJS_PATH="$NODE_BIN"

if ! python3 -c "import playwright, imageio_ffmpeg" 2>/dev/null; then
  python3 -m pip install --quiet --target "$PY" playwright==1.49.1 imageio-ffmpeg==0.5.1 2>&1 | tail -2
  python3 -c "import playwright" 2>/dev/null || { echo "BROWSER_FAILED pip could not install playwright"; exit 0; }
fi

if [ ! -f "$DIR/gsap.min.js" ]; then
  curl -sfL -o "$DIR/gsap.min.js" https://cdn.jsdelivr.net/npm/gsap@3.13.0/dist/gsap.min.js \
    || { echo "BROWSER_FAILED could not download GSAP"; exit 0; }
fi

find_browser() {
  find "$PLAYWRIGHT_BROWSERS_PATH" -type f \( -name headless_shell -o -name chrome-headless-shell \) 2>/dev/null | head -1
}
if [ -z "$(find_browser)" ]; then
  python3 -m playwright install --only-shell chromium 2>&1 | tail -2
fi
BROWSER_BIN="$(find_browser)"
[ -z "$BROWSER_BIN" ] && { echo "BROWSER_FAILED could not download Chromium"; exit 0; }

missing_libs() {
  LD_LIBRARY_PATH="$LIB_PATH:${LD_LIBRARY_PATH:-}" ldd "$BROWSER_BIN" 2>/dev/null | awk '/not found/ {print $1}' | sort -u
}
if [ -n "$(missing_libs)" ]; then
  mkdir -p "$APT/lists/partial" "$APT/cache/archives/partial" "$LIBS"
  APT_OPTS="-o Dir::State::lists=$APT/lists -o Dir::Cache=$APT/cache -o Debug::NoLocking=1 -o APT::Sandbox::User=$(id -un)"
  apt-get $APT_OPTS update -qq >/dev/null 2>&1
  for package in libatomic1 libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libatspi2.0-0 libcups2 libdrm2 libgbm1 \
      libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libxext6 libx11-6 libxcb1 libxshmfence1 \
      libasound2 libpango-1.0-0 libcairo2 libdbus-1-3 libglib2.0-0 libexpat1 libwayland-server0 \
      libavahi-client3 libavahi-common3 libxau6 libxdmcp6 libxi6 libxrender1 libfontconfig1 libfreetype6; do
    (cd "$APT/cache/archives" && apt-get $APT_OPTS download "$package" >/dev/null 2>&1)
  done
  for deb in "$APT"/cache/archives/*.deb; do [ -f "$deb" ] && dpkg -x "$deb" "$LIBS"; done
fi

cat > "$ENV_FILE" <<EOF
export PLAYWRIGHT_BROWSERS_PATH="$PLAYWRIGHT_BROWSERS_PATH"
export PYTHONPATH="$PY\${PYTHONPATH:+:\$PYTHONPATH}"
export LD_LIBRARY_PATH="$LIB_PATH:\${LD_LIBRARY_PATH:-}"
${NODE_BIN:+export PLAYWRIGHT_NODEJS_PATH="$NODE_BIN"}
EOF

STILL_MISSING="$(missing_libs | tr '\n' ' ')"
[ -n "$STILL_MISSING" ] && { echo "BROWSER_FAILED Chromium still lacks: $STILL_MISSING"; exit 0; }

# shellcheck disable=SC1090
. "$ENV_FILE"
python3 - <<'PY'
try:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--no-sandbox"])
        b.new_page().set_content("<p>ok</p>")
        print("BROWSER_OK", b.version)
        b.close()
except Exception as error:
    print("BROWSER_FAILED", str(error).splitlines()[0][:300])
PY
