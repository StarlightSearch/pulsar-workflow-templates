---
name: topic-to-video
description: >-
  Turns a topic into a 10-second motion-graphics video (1280x720 MP4): an
  animated HTML page with drawn figures (diagrams, charts, illustrations and
  icons) on one GSAP timeline, captured frame by frame in a headless browser,
  plus a poster image.
output_schema:
  type: object
  properties:
    status: { type: string, enum: [ok, refused, failed] }
    title: { type: [string, "null"], description: "The video's title" }
    video_file: { type: [string, "null"], description: "MP4 file name in the output folder" }
    poster_file: { type: [string, "null"], description: "PNG file name in the output folder" }
    seconds: { type: [number, "null"] }
    scenes:
      type: array
      description: "One line per scene, in order: what it shows and its words"
      items: { type: string }
    sources:
      type: array
      description: "Where each number in the video comes from"
      items: { type: string }
  required: [status, title, video_file, poster_file, seconds, scenes, sources]
---

# Topic to video

Makes a ten-second explainer about any topic as motion graphics: the run designs each scene around a figure that shows the idea (a diagram that draws itself, a chart that grows, an illustration built from shapes and icons), builds it as one animated HTML page, and records that page frame by frame.

## Inputs

- **Topic**: the topic in the input text, from one word to a paragraph.
- **Style**: optional text: the audience, a tone, or colours (as hex codes).

## Steps

### 1. Set up

```bash
bash /workspace/workflow/scripts/setup_browser.sh /tmp/video
```

It copies the page helpers, the icon stylesheet and the fonts into /tmp/video, and downloads a headless Chromium, its libraries and GSAP into /tmp (about a minute). The last line is `BROWSER_OK` or `BROWSER_FAILED <reason>`. On `BROWSER_FAILED`, run the script once more; if it fails again, make the video with the fallback in step 6 instead.

If the topic asks for something hateful, sexual, violent, about a real private person, or presents claims as fact that are false, do not make the video: write output.json with status `refused`, null files and the reason as the only scene, and say why.

### 2. Storyboard

Plan 4 or 5 scenes that add up to 10 seconds (8 to 12.5). For each, write down the one idea it carries and the **figure** that shows it. The figure is the scene; the words only label it.

- Pick figures that show rather than tell: a process is nodes joined by paths that draw themselves with something travelling along them; a share is a donut or a pictogram of icons lighting up; a comparison is two figures side by side; a quantity over time is a line or bars that grow; a place is a simple map shape; a thing is an illustration built from SVG shapes and icons, with a part that moves (wings, wheels, steam, waves).
- Open with a title scene whose figure sets the subject, and end with a closing scene that leaves one action (drawn as a button).
- Very few words: a headline under 7 words per scene, labels of 1 to 4 words. A viewer gets about two seconds per scene.
- Use a number only when you are sure of it and can name a source (an official statistic, a well-known fact); put the source in `sources` and, small, on screen. Never invent a figure. Diagrams of a process or relative sizes need no source.

### 3. Build the page

Read `/workspace/workflow/assets/example.html` in full first: it is a finished 10.5-second video page (a honeycomb that builds itself under a flying bee, a donut chart with a pictogram, a flower to bee to fruit diagram with pollen travelling along the paths, a circle wipe into the closing). Copy it to `/tmp/video/index.html` and rewrite it for this topic. Keep its structure: `#stage` at 1280x720, the `icons.css`, `gsap.min.js` and `stage.js` includes, one paused timeline, `Stage.ready(tl)` at the end. The helpers are described at the top of `/workspace/workflow/assets/stage.js`.

- **Colour**: set the five `:root` colours to suit the topic (dark backgrounds suit tech and science, warm ones food and people, a light paper one history and business), or to the colours the style asks for. Text must stay readable on its background.
- **Icons**: `<i class="ph ph-NAME"></i>`, sized with `font-size`. Find names with `grep -i coffee /workspace/workflow/assets/icon-names.txt`. When no icon fits (the set has no bee, for example), draw the thing with SVG shapes, as the example does.
- **Motion**: every element enters with motion (rise, scale with a little overshoot, draw a stroke, count up, travel along a path), staggered rather than all at once; something keeps moving while a scene holds (a slow zoom, a drifting background, a bobbing node). Change scenes with a slide, a wipe or a circle reveal, never a plain cut. Hold the last frame about a second.
- **Layout**: keep text at least 40 px from the edges, nothing smaller than 22 px, figures large (most of the frame). Use only Geist (`font-family: Geist`, weights 500, 700, 900).
- **Only the timeline moves things.** No CSS transitions or animations, `setTimeout`, `requestAnimationFrame` or `Date.now()`: the recorder seeks the timeline frame by frame and sees nothing else. Load nothing from the web: no images, fonts or scripts other than the files in /tmp/video.

### 4. Check

```bash
. /tmp/video-browser-env.sh
python3 /workspace/workflow/scripts/render_html.py /tmp/video/index.html --check
```

It seeks through the whole video and reports script errors, text leaving the frame or overflowing its box, text overlapping other text in a scene, icon names that do not exist and a length outside 8 to 12.5 s, each with the time it starts. Fix every problem and check again until it prints `"ok": true`. It also writes `/tmp/video/stills.png`, eight frames across the video: look at it if you can view images, and fix anything empty, crowded or unreadable.

### 5. Render

```bash
. /tmp/video-browser-env.sh
python3 /workspace/workflow/scripts/render_html.py /tmp/video/index.html /workspace/out/video.mp4 --poster /workspace/out/poster.png
```

About 20 to 40 seconds. If it fails, read the error, fix the page, check and render again, at most twice; then use the fallback.

### 6. Fallback (only when the browser cannot run)

Write `/tmp/video/plan.json` for the built-in renderer (its format and scene types are at the top of `/workspace/workflow/scripts/render_video.py`): a style and 5 scenes, at least three different types, the same rules on words and numbers. Then:

```bash
python3 /workspace/workflow/scripts/render_video.py /tmp/video/plan.json --check
PYTHONPATH=/tmp/video/py python3 /workspace/workflow/scripts/render_video.py /tmp/video/plan.json /workspace/out/video.mp4 --poster /workspace/out/poster.png
```

Shorten text until the check prints `"ok": true`. If the render fails twice, stop with status `failed` and the error in the answer.

### 7. Report

Write `/workspace/out/output.json`: status `ok`, the title, `video.mp4`, `poster.png`, the seconds the renderer printed, one line per scene (`diagram: flower, bee and fruit joined by paths, pollen travelling; labels "Flower makes pollen", "Bee carries it", "Fruit grows"`) and the sources. Put nothing else in /workspace/out/.

The answer lists the scenes in a short list (the figure and the words), names each source, says if the fallback renderer was used, and ends with `## Assumptions`.

## Output

- **video.mp4**: the video, 1280x720, 30 fps, 8 to 12.5 seconds, H.264.
- **poster.png**: a frame from the title scene, for a thumbnail.
- **output.json**: status, title, file names, length, the scenes and the sources.

## Workflow map

```pulsar-workflow
{
  "version": 1,
  "steps": [
    {"title": "Set up", "detail": "Download a headless browser, its libraries and GSAP into /tmp.", "kind": "action"},
    {"title": "Storyboard", "detail": "Plan 4 or 5 scenes, each built around a figure that shows its idea.", "kind": "action"},
    {"title": "Build the page", "detail": "Write the animated HTML page from the example, with drawn figures and icons on one timeline.", "kind": "action"},
    {"title": "Check", "detail": "Seek through the page and fix every layout or script problem the checker reports.", "kind": "action"},
    {"title": "Render", "detail": "Record the page frame by frame to an MP4 and a poster.", "kind": "action"},
    {"title": "Report", "detail": "Write output.json with the scenes and the sources of every number.", "kind": "action"}
  ]
}
```
