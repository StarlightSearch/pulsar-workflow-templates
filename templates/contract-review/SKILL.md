---
name: contract-review
description: >-
  Reviews a contract (PDF, Word or text) against a checklist given in the
  request, or a sensible default one, and returns an issues report as a Word
  document: each clause rated red, yellow or green with the clause reference,
  the exact wording, the risk and a proposed redline.
output_schema:
  type: object
  properties:
    contract_type: { type: [string, "null"], description: For example software services, NDA, consultancy }
    parties:
      type: array
      items:
        type: object
        properties:
          name: { type: [string, "null"] }
          role: { type: [string, "null"], description: As the contract names them, e.g. Supplier, Customer }
    our_side: { type: [string, "null"], description: The party the review was done for }
    basis: { type: [string, "null"], description: checklist in the request, or default checklist }
    overall_risk: { type: [string, "null"], enum: [high, medium, low, null] }
    red_count: { type: integer }
    yellow_count: { type: integer }
    green_count: { type: integer }
    findings:
      type: array
      items:
        type: object
        properties:
          clause_ref: { type: string, description: Clause number as printed, e.g. 7.2 }
          topic: { type: string }
          rating: { type: string, enum: [RED, YELLOW, GREEN] }
          issue: { type: string }
        required: [clause_ref, topic, rating]
    top_issues: { type: array, items: { type: string } }
  required: [our_side, basis, overall_risk, red_count, yellow_count, green_count, findings]
---

# Contract review

Reads a contract the way a careful in-house reviewer would: the whole document first, then clause by clause against the positions that matter to the person asking, and returns an issues report they can take into a negotiation. It prepares a review; it is not legal advice, and the report says so.

## Inputs

- **Contract**: one PDF, Word (.docx) or text file in /workspace/inputs/.
- **Checklist and context**: optional text: which side you are on, the positions you need (for example "liability cap at least 12 months' fees"), what matters most, any deadline.

## Steps

### 1. Read the contract

Extract the contract's text and the list of numbered clauses, so every finding can quote and cite the right clause.

Check the libraries first: run `python3 -c "import docx"`; if it fails, run `pip install --quiet --user --break-system-packages python-docx`, check again, and if it still fails say it is missing and stop. For a PDF, also run `command -v pdftotext`; only if that finds nothing, make sure `python3 -c "import pypdf"` works the same way (install `pypdf` if it fails).

Run `python3 /workspace/workflow/scripts/extract_text.py <contract> /tmp/contract.txt` with the contract's path from /workspace/inputs/ (if there are several files, review the first contract by name and list the others under Assumptions). It prints the page count, whether the PDF looks scanned, and the clause numbers it found. Then read /tmp/contract.txt from start to finish before judging anything: clauses interact (a broad indemnity can sit outside a liability cap; a renewal clause can turn a short term into a long one).

- If it reports `scanned: true`, the PDF is an image with no text layer: say it needs OCR first and stop, writing no report.
- If it reports an `error` (`encrypted`, `unreadable`, `unsupported`), say so with its `detail` and stop.
- For a Word file, automatic list numbers ("1.", "1.1") are rebuilt and written into the text; `numbers_rebuilt` says how many. If it reports `auto_numbered: true`, some numbering could not be rebuilt: work out each clause's number by counting the headings and numbered paragraphs in order, use those numbers as `clause_ref`, and say under Assumptions that the references were counted rather than read.
- If the contract is not in English, review it in its own language, write the report in English, and say so.

### 2. Set the basis

Work out whose side the review is for and which positions to measure the contract against.

- **Our side**: take it from the request ("we are the customer"). If the request does not say, assume the party that is not the drafter: the one receiving the services, goods or licence. Say which you chose under Assumptions.
- **Checklist**: if the request gives positions, use them, item by item, as the standard, and set `basis` to `checklist in the request`. Topics the request's checklist does not mention are still reviewed, against the default checklist (next bullet).
- **No checklist**: read /workspace/workflow/references/default-checklist.md and use it; set `basis` to `default checklist`. It is written for the customer; when you act for the supplier, read each line from the other side.
- **Contract type**: name it (software services, NDA, consultancy, supply, licence). It decides which clauses matter most: for a service contract, liability, data and termination; for an NDA, scope, term and exceptions.

### 3. Review clause by clause

Rate every checklist topic, and anything else material, then write the analysis to /tmp/review.json.

Ratings:

- **RED**: outside what the checklist allows, or matching its RED column, or a risk large enough to need a senior decision (uncapped exposure for our side, rights only the other side has, our data or work owned by them).
- **YELLOW**: worse than the standard position but common in the market and negotiable.
- **GREEN**: at or better than the standard position. Keep these short; they show the topic was checked.

For each finding:

- `clause_ref` is the number as printed (the extract's clause list helps); use the most specific sub-clause. A topic the contract does not cover goes under `missing`, not `findings`.
- `contract_says` is a short exact quote (one sentence or less) copied from /tmp/contract.txt, without the clause number in front; every RED and YELLOW finding needs one. The build script checks it.
- `issue` and `impact` say what the clause does to our side in practice, in plain words, with the numbers (for example "a 6-week notice window on a 3-year renewal").
- `redline` (RED and YELLOW) is replacement wording ready to paste, measured to the checklist position, and `fallback` is the position to accept if the other side refuses. `priority` is Must-have (RED), Should-have or Nice-to-have.

Use this shape (the example is invented and unrelated to any input):

```json
{
  "document": "file name of the contract",
  "title": "Consultancy Agreement review",
  "contract_type": "Consultancy",
  "parties": [{"name": "Example Advisory LLP", "role": "Consultant"}, {"name": "Example Client plc", "role": "Client"}],
  "our_side": "Client",
  "basis": "default checklist",
  "overall_risk": "medium",
  "summary": "Two or three sentences: what the contract is and the overall risk picture.",
  "top_issues": ["Three to five one-line issues, most serious first, each naming its clause"],
  "findings": [
    {"clause_ref": "14.2", "topic": "Confidentiality", "rating": "YELLOW",
     "contract_says": "These obligations end 12 months after termination.",
     "position": "At least 3 years after the end of the agreement",
     "issue": "Confidentiality ends a year after the contract does.",
     "impact": "Pricing and customer lists shared during the project could be used from year two.",
     "redline": "These obligations continue for three years after termination.",
     "fallback": "Two years, with no end date for trade secrets.",
     "priority": "Should-have"}
  ],
  "missing": [{"topic": "Insurance", "note": "No professional indemnity insurance is required of the Consultant."}],
  "negotiation": ["Lead with the RED items; offer the Nice-to-have items as concessions."],
  "next_steps": ["Send the redlines to the other side's counsel", "Confirm the data protection terms with the DPO"]
}
```

Set `overall_risk` to `high` with any RED finding on liability, indemnity, termination or IP, `medium` with other RED or several YELLOW findings, else `low`.

### 4. Build the report

Run the script that checks the review and writes the deliverables.

`python3 /workspace/workflow/scripts/build_report.py /tmp/review.json /tmp/contract.txt /workspace/out`

It writes /workspace/out/issues.docx (summary table, top issues, then each clause RED first with its quote, issue, redline and fallback) and /workspace/out/output.json. It prints a `PROBLEM:` line for each finding without a clause reference, a RED or YELLOW finding without a quote or a redline, or a quote that is not in the contract. Fix /tmp/review.json and rerun until it prints `ok`; a misquote usually means a word was paraphrased, so copy the sentence again from /tmp/contract.txt.

### 5. Answer

Reply with the overall risk, the counts by rating, and the top issues, one line each with its clause number.

Then add `## Assumptions`: the side you reviewed for and why, the basis (the request's checklist or the default), any checklist item you had to interpret, and a reminder that the review is not legal advice.

## Output

- **issues.docx**: the issues report, every finding with its clause reference, quote, rating, impact and proposed redline.
- **output.json**: contract type, parties, side, basis, overall risk, counts, and each finding's clause and rating.

## Adapting this

- Put your own playbook in the knowledge base (for example a checklist.md under /workspace/knowledge/) and change step 2 to read it instead of the default checklist.
- Change the RED column of references/default-checklist.md to your escalation rules, so the ratings match how your team decides.
- To file the report (a document system, a ticket for legal), add a connection in the frontmatter and a final step that sends issues.docx.
