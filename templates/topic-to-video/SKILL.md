---
name: topic-to-video
description: >-
  Turns a topic into a 10-second motion-graphics video (1280x720 MP4): a short
  scene plan written for the topic, rendered with animated titles, bullet
  lines, a statistic and a bar chart, plus a poster image.
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
      description: "One line per scene, in order: its type and its words"
      items: { type: string }
    sources:
      type: array
      description: "Where each number in the video comes from"
      items: { type: string }
  required: [status, title, video_file, poster_file, seconds, scenes, sources]
---

# Topic to video

Makes a ten-second explainer about any topic: the run decides what to say, scene by scene, and a fixed renderer turns that plan into a polished video, so the result looks finished whatever the topic.

## Inputs

- **Topic**: the topic in the input text, from one word to a paragraph.
- **Style**: optional text: the audience, a tone, or colours (as hex codes).

## Steps

### 1. Plan the scenes

Write `/tmp/video/plan.json`: a title and 4 or 5 scenes that add up to 10 seconds. Read the plan format at the top of `/workspace/workflow/scripts/render_video.py` first. Scene types are `title`, `bullets`, `stat`, `bars`, `quote` and `closing`.

- Open with a `title` scene and end with a `closing` scene that leaves one idea or action.
- Say one thing per scene, in very few words: a viewer gets about two seconds to read each one. Headlines under 8 words, bullet items under 6 words.
- Use a `stat` or `bars` scene only for a number you are sure of and can name a source for (an official statistic, a well-known fact). Put the source in `sources`. When no number is solid, use `bullets` or `quote` instead; never invent a figure. A `bars` scene may also show relative sizes that are not statistics (steps of a process, a ranking), labelled as such.
- Keep the default palette unless the style asks for colours. Colours you choose must keep the text readable: the renderer refuses a foreground and background with a contrast under 4.5:1.

If the topic asks for something hateful, sexual, violent, about a real private person, or presents claims as fact that are false, do not make the video: write output.json with status `refused`, null files and the reason as the only scene, and say why.

Check the plan:

```bash
python3 /workspace/workflow/scripts/render_video.py /tmp/video/plan.json --check
```

It lays out every scene and reports text that is too long or does not fit. Shorten the words and check again until it prints `"ok": true`.

### 2. Render

The renderer needs ffmpeg. Use the one on the machine, else install the bundled one into /tmp:

```bash
command -v ffmpeg >/dev/null || python3 -c "import imageio_ffmpeg" 2>/dev/null || python3 -m pip install --quiet --target /tmp/video/py imageio-ffmpeg==0.5.1
PYTHONPATH=/tmp/video/py python3 /workspace/workflow/scripts/render_video.py /tmp/video/plan.json /workspace/out/video.mp4 --poster /workspace/out/poster.png
```

If the install or the render fails, try once more; then stop with status `failed` and the error in the answer.

### 3. Report

Write `/workspace/out/output.json`: status `ok`, the title, `video.mp4`, `poster.png`, the seconds the renderer printed, one line per scene (`stat: 75% of the leading food crops benefit from animal pollinators`) and the sources. Put nothing else in /workspace/out/.

The answer gives the title and the scenes in a short list, names each source, and ends with `## Assumptions`.

## Output

- **video.mp4**: the video, 1280x720, 30 fps, about 10 seconds, H.264.
- **poster.png**: a still of the first scene, for a thumbnail.
- **output.json**: status, title, file names, length, the scenes and the sources.

## Workflow map

```pulsar-workflow
{
  "version": 1,
  "steps": [
    {"title": "Plan the scenes", "detail": "Write a 10-second scene plan for the topic and check that every scene fits.", "kind": "action"},
    {"title": "Render", "detail": "Render the plan to an MP4 and a poster with the fixed renderer.", "kind": "action"},
    {"title": "Report", "detail": "Write output.json with the scenes and the sources of every number.", "kind": "action"}
  ]
}
```
