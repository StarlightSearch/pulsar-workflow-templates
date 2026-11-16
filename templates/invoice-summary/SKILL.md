---
name: invoice-summary
description: >-
  Reads an invoice PDF and returns the supplier, invoice number, total, currency
  and due date as structured data, with the arithmetic checked and a one-page
  summary PDF.
output_schema:
  type: object
  properties:
    supplier: { type: [string, "null"], description: Supplier name as printed on the invoice }
    invoice_number: { type: [string, "null"], description: Invoice number as printed }
    invoice_date: { type: [string, "null"], description: Invoice date as an ISO date (YYYY-MM-DD) }
    total: { type: [number, "null"], description: Invoice total including tax }
    currency: { type: [string, "null"], description: ISO 4217 code such as EUR, USD or GBP }
    due_date: { type: [string, "null"], description: Due date as an ISO date, printed or worked out from the payment terms }
    subtotal: { type: [number, "null"], description: Total before tax }
    tax: { type: [number, "null"], description: Tax amount }
    checks_passed: { type: boolean, description: True when every arithmetic check that could run agreed }
    issues: { type: array, items: { type: string }, description: Checks that failed, in plain words }
  required: [supplier, invoice_number, total, currency, due_date, checks_passed, issues]
---

# Invoice summary

Turns one supplier invoice into the handful of facts someone needs to pay or file it, and checks the sums so a typo on the invoice is caught before money moves.

## Inputs

- **Invoice**: one PDF in /workspace/inputs/. If there are several, summarise the first by file name and list the others under Assumptions.
- **Notes**: optional text, for example a purchase order total to compare against or a currency to expect.

## Steps

### 1. Read the invoice

Extract the invoice's text with its layout kept, so table columns stay lined up.

Run `python3 /workspace/workflow/scripts/extract_text.py <invoice> /tmp/invoice.txt` with the invoice path from /workspace/inputs/, then read /tmp/invoice.txt. The script prints the page count and whether the PDF looks scanned.

- If it says `scanned: true`, the PDF is an image with no text layer. Do not guess the figures: write /workspace/out/output.json with every field null, `checks_passed: false` and `issues: ["The PDF is a scan with no text layer; it needs OCR first."]`, say so in the answer, and stop.
- If it reports `encrypted`, do the same with the issue "The PDF is password protected."

### 2. Find the fields

Read the text and write the invoice's facts to /tmp/fields.json, exactly as printed.

Use this shape (null for anything the invoice does not print):

```json
{
  "supplier": "Name of the company that issued the invoice",
  "customer": "Bill-to name",
  "invoice_number": "As printed",
  "invoice_date": "YYYY-MM-DD",
  "due_date": "YYYY-MM-DD",
  "due_date_source": "printed | terms | missing",
  "payment_terms": "As printed, e.g. Net 30",
  "currency": "EUR",
  "line_items": [{"description": "...", "quantity": 2, "unit_price": 74.5, "amount": 149.0}],
  "subtotal": 1314.0,
  "discount": null,
  "tax_label": "VAT 21%",
  "tax": 275.94,
  "total": 1589.94,
  "amount_due": 1589.94,
  "notes": []
}
```

How to decide the judgement calls:

- **Supplier** is the issuer (usually top left, beside the logo or the VAT number), never the bill-to party.
- **Total**: when several totals appear, take the one that includes tax ("Total", "Invoice total", "Total incl. VAT"). If an amount already paid is shown, put what remains in `amount_due` and keep `total` as the invoice total.
- **Dates**: write them as ISO dates. Read day-first (28/10/2026) unless the supplier is in the US or a day number above 12 settles it the other way; when both readings are possible, say which you chose in `notes`.
- **Due date**: if printed, use it (`printed`). If only terms are printed ("Net 14", "30 days", "due on receipt"), add them to the invoice date (`terms`; receipt means the invoice date). If neither is printed, use null (`missing`).
- **Currency**: the ISO code. Map symbols as printed (EUR for the euro sign, GBP for the pound sign); a bare `$` is USD unless the address or the notes say another dollar.
- **Numbers**: plain numbers, no thousands separators or symbols. A comma used as the decimal mark (1.589,94) becomes 1589.94.
- Put anything a reader should know (a purchase order number, a late fee clause, an amount that differs from the notes) in `notes` as short sentences.

### 3. Check and write the results

Run the script that checks the arithmetic and writes both deliverables.

`python3 /workspace/workflow/scripts/summarise.py /tmp/fields.json /workspace/out`

It checks that each line is quantity times unit price, that the lines add up to the subtotal, that subtotal plus tax equals the total, and that the due date is not before the invoice date. It writes /workspace/out/summary.pdf and /workspace/out/output.json, and prints each check.

If a check fails, look at the text again before trusting the result: most failures are a misread number in step 2. Fix /tmp/fields.json and rerun. If the invoice itself is wrong (the printed numbers really do not add up), leave the printed figures as they are; the failed check is the finding.

### 4. Answer

Reply with three or four lines: supplier, invoice number, total with currency, due date, and whether the checks passed (naming any that failed).

Then add `## Assumptions` listing every judgement call from step 2 that was not plain on the page (a due date from terms, a date read day-first, a currency from a symbol).

## Output

- **output.json**: supplier, invoice_number, invoice_date, total, currency, due_date, subtotal, tax, checks_passed, issues.
- **summary.pdf**: one page with the key facts, the line items, and the result of each check.

## Adapting this

- To compare against your purchase orders, put them in the knowledge base and add a step that looks up the PO number from `notes` under /workspace/knowledge/.
- To post the result somewhere (an accounting app, a sheet), add a connection in the frontmatter and a final step that sends output.json.
- Change the fields in step 2 and the `output_schema` together if you need others, such as the supplier's VAT number or bank details.
