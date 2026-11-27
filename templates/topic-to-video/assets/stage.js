/*
 * Stage helpers for a video page. The page builds ONE paused GSAP timeline and
 * hands it to Stage.ready(tl); render_html.py then seeks it frame by frame.
 *
 *   const tl = gsap.timeline({ paused: true });
 *   ...add tweens...
 *   Stage.ready(tl);
 *
 * Helpers:
 *   Stage.words(el)            wraps each word of el in <span class="w"><span>..</span></span>
 *                              and returns the inner spans (animate them up from y:"110%")
 *   Stage.draw(el)             prepares an SVG path/line/circle/rect/polyline to be drawn:
 *                              returns its length; tween strokeDashoffset to 0 to draw it
 *   Stage.count(tl, el, to, at, opts)   counts el's text from 0 to `to` starting at time `at`
 *                              opts: {duration, decimals, prefix, suffix}
 *   Stage.along(tl, el, path, at, duration)  moves el (an HTML or SVG element) along an SVG path
 *   Stage.scene(tl, el, at, inFn) shows section `el` from time `at` (hiding the previous one)
 *
 * Time is in seconds. Never use setTimeout, requestAnimationFrame loops, CSS
 * transitions or Date.now() for motion: only what is on the timeline is seen.
 */
(function () {
  const Stage = {};
  let current = null;

  Stage.words = function (el) {
    const text = el.textContent.trim().split(/\s+/);
    el.textContent = "";
    const inner = [];
    text.forEach((w, i) => {
      const outer = document.createElement("span");
      outer.className = "w";
      const s = document.createElement("span");
      s.textContent = w;
      outer.appendChild(s);
      el.appendChild(outer);
      if (i < text.length - 1) el.appendChild(document.createTextNode(" "));
      inner.push(s);
    });
    return inner;
  };

  Stage.draw = function (el) {
    const len = el.getTotalLength ? el.getTotalLength() : 0;
    el.style.strokeDasharray = len + " " + len;
    el.style.strokeDashoffset = len;
    return len;
  };

  Stage.count = function (tl, el, to, at, opts) {
    const o = Object.assign({ duration: 1.2, decimals: 0, prefix: "", suffix: "" }, opts || {});
    const state = { v: 0 };
    const fmt = (v) =>
      o.prefix + v.toLocaleString("en-US", { minimumFractionDigits: o.decimals, maximumFractionDigits: o.decimals }) + o.suffix;
    el.textContent = fmt(0);
    tl.to(state, { v: to, duration: o.duration, ease: "expo.out", onUpdate: () => (el.textContent = fmt(state.v)) }, at);
  };

  Stage.along = function (tl, el, path, at, duration) {
    const len = path.getTotalLength();
    const state = { p: 0 };
    const svg = path.ownerSVGElement;
    const place = () => {
      const pt = path.getPointAtLength(len * state.p);
      if (el instanceof SVGElement) {
        el.setAttribute("transform", `translate(${pt.x},${pt.y})`);
      } else {
        const m = path.getScreenCTM();
        const box = document.getElementById("stage").getBoundingClientRect();
        const sp = svg.createSVGPoint();
        sp.x = pt.x; sp.y = pt.y;
        const p = sp.matrixTransform(m);
        el.style.left = p.x - box.left + "px";
        el.style.top = p.y - box.top + "px";
      }
    };
    place();
    tl.to(state, { p: 1, duration: duration || 1, ease: "power1.inOut", onUpdate: place }, at);
  };

  Stage.scene = function (tl, el, at) {
    const prev = current;
    tl.set(el, { autoAlpha: 1 }, at);
    if (prev) tl.set(prev, { autoAlpha: 0 }, at + 0.6);
    current = el;
  };

  Stage.ready = function (tl) {
    window.__tl = tl;
    window.__duration = tl.duration();
    window.__seek = (t) => { tl.seek(t, false); };
    const done = () => {
      tl.seek(0, false);
      window.__ready = true;
    };
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(done);
    else done();
    // Opened in a normal browser (not by the renderer): play it, looping.
    if (!/[?&]render\b/.test(location.search)) tl.repeat(-1).repeatDelay(0.6).play(0);
  };

  window.Stage = Stage;
})();
