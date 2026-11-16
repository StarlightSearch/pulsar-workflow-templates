---
name: meeting-notes
description: >-
  Turns a meeting transcript into clean notes as a Word document: a short
  summary, the decisions made, action items with owner and due date, and the
  questions still open.
output_schema:
  type: object
  properties:
    title: { type: [string, "null"], description: Meeting title }
    date: { type: [string, "null"], description: Meeting date as an ISO date, null when the transcript does not give one }
    decisions: { type: array, items: { type: string }, description: Each decision in one sentence }
    actions:
      type: array
      description: Action items
      items:
        type: object
        properties:
          action: { type: string }
          owner: { type: [string, "null"], description: Full name of the person who took it on, null when nobody did }
          due: { type: [string, "null"], description: ISO date, or null when no date was said }
        required: [action, owner, due]
    open_questions: { type: array, items: { type: string } }
    parked: { type: array, items: { type: string }, description: Ideas discussed and explicitly left undecided }
  required: [title, date, decisions, actions, open_questions, parked]
---

# Meeting notes

Reads a transcript and writes the notes someone would want five minutes after the call: what was decided, who does what by when, and what is still open. The value is in being exact: a proposal is not a decision, and an action nobody took on must not be given an owner.

## Inputs

- **Transcript**: one text file in /workspace/inputs/ (.txt, .md, .vtt or .srt; a .docx works too). Speaker names at the start of lines help but are not required.
- **Instructions**: optional text, for example a title to use or whose actions to focus on.

## Steps

### 1. Read the transcript

Read the whole transcript and note the meeting's date, title and attendees.

Take the transcript path from /workspace/inputs/. For a .docx, read it with python-docx (`python3 -c "import docx,sys; print('\n'.join(p.text for p in docx.Document(sys.argv[1]).paragraphs))" <path>`). Ignore timestamps, filler and cross-talk.

- **Date**: from a header line or the file name. If none is given, use null; do not use today's date, because relative dates like "Friday" would then point at the wrong week.
- **Title**: from the header, else a short descriptive title from the main topic (for example "Q3 hiring plan review").
- **Attendees**: everyone named as present or who speaks, with their full name the first time it appears.

### 2. Find decisions, actions, questions

Go through the conversation in order and sort what was said into four kinds.

- **Decision**: something the group settled ("let's go with the cheaper vendor", "we pause hiring until July"). A suggestion nobody confirmed is not a decision. A decision not to do something ("we won't renew the office lease") is still a decision. Keep the reasoning in a short `detail` when it was given.
- **Action item**: a task one person said they will do, or was asked to do and accepted. The owner is that person's full name. If a task was raised but nobody took it ("someone should tidy the shared drive"), keep it with `owner: null`; never assign it yourself.
- **Due date**: resolve what was said against the meeting date ("by Friday" is the Friday after the meeting, "end of next week" is the Friday of the following week, "today" is the meeting date) and keep the words as said in `due_note`. Without a meeting date, leave `due` null and put the words in `due_note`. No date said: `due` null.
- **Open question**: something raised and left unresolved, including "I'll ask around" or "let's figure that out later". Name who follows up if anyone said they would.
- **Parked**: ideas discussed and explicitly left undecided, if any.

When something is ambiguous (two people could own it, a date could be this week or next), pick the plainer reading and list it under Assumptions in the answer.

### 3. Write the notes

Write the notes as JSON, then build the document with the script, so the layout is the same every time.

Write /tmp/notes.json:

```json
{
  "title": "Q3 hiring plan review",
  "date": "2026-05-18",
  "attendees": ["Jordan Vale (chair)", "Kim Achebe"],
  "summary": "Three or four sentences: what the meeting was for, the main outcomes, the biggest open item.",
  "decisions": [{"decision": "One sentence, starting with the outcome.", "detail": "Why, if said."}],
  "actions": [{"action": "Starts with a verb", "owner": "Full name or null", "due": "YYYY-MM-DD or null", "due_note": "said: by Friday"}],
  "open_questions": [{"question": "Phrased as a question", "owner": "Who follows up, or null"}],
  "parked": ["Idea: what was said about it"],
  "source": "the transcript's file name"
}
```

Write in plain, neutral sentences. Do not quote people at length or add anything that was not said.

Then run `python3 /workspace/workflow/scripts/build_notes.py /tmp/notes.json /workspace/out/notes.docx`. It writes /workspace/out/notes.docx and /workspace/out/output.json and prints the counts. Unassigned actions are shown in red in the document so they are not lost.

### 4. Answer

Reply with the summary, then the action items as a short list (owner, action, due).

Then add `## Assumptions` with each judgement call from steps 1 and 2: dates you resolved, a missing meeting date, an owner you inferred from context.

## Output

- **notes.docx**: the meeting notes, one or two pages.
- **output.json**: decisions, action items (action, owner, due), open questions and parked topics.

## Adapting this

- Change the sections in step 3 and in `scripts/build_notes.py` if your team keeps notes differently (for example a "Risks" section, or one table per project).
- To post the action items to a tracker, add a connection in the frontmatter and a final step that creates one task per action item from output.json.
- If your meetings always have the same attendees, put a roster in the knowledge base and tell step 1 to read full names from /workspace/knowledge/.
