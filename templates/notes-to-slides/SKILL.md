---
name: notes-to-slides
description: >-
  Turns rough notes (Markdown or text) into a designed PowerPoint deck: one
  message per slide, varied layouts (big numbers, a native chart, a comparison,
  a timeline), and speaker notes on every slide.
---

# Notes to slides

Takes the notes someone wrote before a meeting and returns a deck they could present: a clear storyline, slide titles that say the point, and visuals instead of walls of bullets. The design is fixed in the build script, so the run's job is the storyline and the words.

## Inputs

- **Notes**: one Markdown or text file in /workspace/inputs/ (a .docx works too). Headings, bullets, numbers and quotes all help.
- **Brief**: optional text: the audience, how long the talk is, a palette, or slides to add or leave out.

## Steps

### 1. Install the slide library

Install python-pptx, which the run sandbox does not include.

Run `pip install --quiet python-pptx`. If that fails, try `pip install --quiet --user python-pptx`. If it still fails (no network), there is no way to write a .pptx here: say so in the answer and stop, rather than writing a different format.

### 2. Plan the storyline

Read the notes and decide what the deck is for and the one message each slide carries.

Take the notes path from /workspace/inputs/ (for a .docx, read the paragraphs with python-docx). Work out:

- **Purpose**: a decision, an update, a pitch. If the notes end with an ask, the deck builds toward it. Without a brief, assume a live talk to people who know the topic, about 1.5 minutes a slide.
- **Size**: 6 to 10 slides for most notes; fewer for a short talk. Do not pad and do not drop content the notes treat as important.
- **Order**: the main message first (the title slide says it), then the reasons and evidence, then what happens next. Keep the order of the notes where it already works.
- **Titles**: each content title is the point of the slide as a short sentence ("Replies got faster within three weeks and stayed fast"), not a topic label ("Results"). No full stop at the end, under about 60 characters.

### 3. Write the slide plan

Write /tmp/deck.json, choosing for each slide the layout that shows its content best.

```json
{
  "title": "Deck title", "author": "Presenter", "palette": "forest", "footer": "Short footer text",
  "slides": [
    {"kind": "title", "title": "The main message", "subtitle": "What this is", "byline": "Name, role", "notes": "..."},
    {"kind": "bullets", "title": "...", "bullets": ["3 to 5 short lines"], "takeaway": "Optional one-line point shown in a side panel", "notes": "..."},
    {"kind": "stats", "title": "...", "stats": [{"value": "3.1 h", "label": "Median first response", "detail": "from 14.2 hours"}], "note": "Source or basis", "notes": "..."},
    {"kind": "chart", "title": "...", "chart": {"type": "line", "categories": ["Wk 1", "Wk 2"], "series": [{"name": "Before", "values": [13.8, 14.5]}], "value_title": "Hours"}, "caption": "What to see in it", "notes": "..."},
    {"kind": "compare", "title": "...", "left": {"heading": "Before", "bullets": ["..."]}, "right": {"heading": "After", "bullets": ["..."]}, "notes": "..."},
    {"kind": "timeline", "title": "...", "steps": [{"label": "December", "text": "What happens"}], "notes": "..."},
    {"kind": "statement", "title": "Small heading", "text": "A quote or one big sentence", "attribution": "Who said it", "notes": "..."},
    {"kind": "closing", "title": "The ask or the next steps", "bullets": ["Up to 4 items"], "notes": "..."}
  ]
}
```

How to choose:

- **Numbers** (2 to 4 headline figures) go on a `stats` slide; a series over time or across categories goes on a `chart` (`line` for time, `column` or `bar` to compare). Put the before value in `detail` so a number never stands alone.
- **Before and after, or two options**, go on `compare`; the right side is highlighted, so put the recommended or new one there.
- **Steps or dates** go on a `timeline` (3 to 5 steps).
- **A quote** goes on a `statement` slide, kept word for word.
- Use `bullets` only when nothing else fits, and not on two slides in a row. Each bullet is one line of at most about 10 words; move the detail to the speaker notes.
- **Palette**: `midnight`, `forest`, `terracotta`, `ocean`, `charcoal` or `berry`. Use the brief's choice, else pick one that suits the topic (forest for growth or operations, ocean for data, terracotta or berry for people and brand, charcoal for finance or legal, midnight otherwise).
- **Speaker notes**: two to four sentences per slide with what to say, including the details cut from the slide.

Use only facts from the notes. Keep their numbers exactly and do not round them differently on different slides.

### 4. Build and check the deck

Build the deck, then read its text back and fix anything the script warns about.

Run `python3 /workspace/workflow/scripts/build_deck.py /tmp/deck.json /workspace/out/deck.pptx`. It prints warnings for text that may not fit, too many bullets, and slides without notes. For each one, shorten the words in /tmp/deck.json (never make text smaller by hand) and build again until there are none.

Then run `python3 /workspace/workflow/scripts/build_deck.py --text /workspace/out/deck.pptx` and read it: every slide in order, numbers matching the notes, no typos, no placeholder text, notes on every slide.

### 5. Answer

Reply with the slide titles as a numbered list, which is the storyline at a glance, and one line on the palette and the talk length it fits.

Then add `## Assumptions`: the audience and purpose you assumed, anything from the notes you left out or moved to speaker notes, and how you handled anything unclear.

## Output

- **deck.pptx**: a 16:9 PowerPoint deck with speaker notes, editable in PowerPoint, Keynote or Google Slides.

## Adapting this

- Put your brand colours and fonts in `PALETTES`, `HEAD_FONT` and `BODY_FONT` at the top of `scripts/build_deck.py`, and set `palette` to your entry in step 3.
- Add your logo or a fixed footer by extending `footer()` in the script.
- If your decks always follow one structure (a weekly update, a pitch), write it into step 2 as the default order.
