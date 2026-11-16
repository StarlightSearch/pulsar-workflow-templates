---
name: reconciliation
description: >-
  Reconciles a bank statement with the cash account in the ledger: matches the
  transactions, explains every difference (timing, missing entries, recording
  errors), and returns a reconciliation workbook and an exceptions list with
  proposed journal entries.
output_schema:
  type: object
  properties:
    period_end: { type: string, description: Last transaction date in either file, ISO date }
    basis: { type: string, description: closing balances, or movements when the files have no balances }
    matched_count: { type: integer, description: Transactions matched one to one with the same amount }
    matched_total: { type: number, description: Net amount of the matched transactions, money in positive }
    amount_differences_count: { type: integer, description: Pairs matched with a different amount (recording errors) }
    amount_differences_total: { type: number, description: Bank amount minus ledger amount, summed over those pairs }
    unmatched_bank_count: { type: integer }
    unmatched_bank_total: { type: number }
    unmatched_ledger_count: { type: integer }
    unmatched_ledger_total: { type: number }
    bank_closing_balance: { type: [number, "null"] }
    ledger_closing_balance: { type: [number, "null"] }
    adjusted_bank_balance: { type: number }
    adjusted_ledger_balance: { type: number }
    difference: { type: number, description: Adjusted bank minus adjusted ledger; 0 when every difference is explained }
    reconciled: { type: boolean }
  required: [matched_count, matched_total, unmatched_bank_count, unmatched_bank_total, unmatched_ledger_count, unmatched_ledger_total, difference, reconciled]
---

# Bank reconciliation

Does the month-end bank reconciliation: every bank line is matched to a ledger entry or explained, and the two balances are brought to the same adjusted figure. It prepares the work for an accountant to review; it does not post anything.

## Inputs

- **Bank statement**: a CSV or Excel export for one account and period, in /workspace/inputs/.
- **Ledger**: the cash account's entries for the same period (CSV or Excel), in /workspace/inputs/. A general ledger with several accounts also works; the run picks out the bank account.
- **Notes**: optional text, for example which account to use, the period, or known items ("the 860.00 transfer to the landlord went out on the last day of the month").

## Steps

### 1. Identify the files

Work out which file is the bank statement and which is the ledger, and the period they cover.

List /workspace/inputs/ and look at the first rows of each file with pandas (skip lines starting with `#`). The bank statement has bank-style descriptions and usually a running balance; the ledger has references, debit and credit columns, and often an opening balance row.

- If the ledger holds several accounts, keep only the bank account (named like "Cash at bank", "Bank", or a 10xx code) in a copy under /tmp, and use that copy.
- If the files cover different periods, use the overlap and say so.
- If there are more than two files, use the pair that matches the Notes, else the first statement and ledger by name, and list the others under Assumptions.

### 2. Match the transactions

Run the matcher, then check it read both files the right way round.

`python3 /workspace/workflow/scripts/reconcile.py <bank file> <ledger file> /workspace/out`

It prints the columns it used, the balances, and every exception, and writes /workspace/out/reconciliation.xlsx and /workspace/out/output.json (the detail is also in /tmp/recon/result.json). It matches one to one: the same amount within 5 days first, then the same direction with a close amount and similar description, which it reports as a recording error.

Check before going on:

- **Signs**: money in is positive on both sides. Payments out (wages, suppliers, fees) should be negative in the Matched sheet, customer receipts positive. If a side is inverted, rerun with `--flip-bank` or `--flip-ledger`.
- **Columns**: if it picked the wrong column (or could not find one), rerun with `--bank-cols date=...,desc=...,amount=...` or `--ledger-cols ...` using the real header names (keys: date, desc, ref, amount, in, out, balance).
- **Balances**: the opening balances it reports should agree. If they do not, the difference comes from an earlier period: say so, it is not an item in this one.
- If many items are unmatched only because the dates are far apart, rerun with `--window 10` and say so.

### 3. Review the exceptions

Go through each exception and confirm or correct how it is treated, because the matcher only sees amounts, dates and words.

The categories are the standard ones:

- **Timing difference**: in the ledger, not yet at the bank, dated within 10 days of the period end (deposits in transit, outstanding payments). These clear on their own.
- **Adjustment required**: bank charges or interest not yet in the ledger, and recording errors (the same transaction with a different amount). These need a journal entry.
- **Requires investigation**: anything else, such as a bank line with no ledger entry or a ledger entry older than 10 days that never reached the bank.

Look for what the matcher cannot see: two unmatched entries on one side that add up to one on the other (a split or combined deposit), the same amount posted twice in the ledger, or a recording error where digits were swapped (a difference divisible by 9). Describe such a finding in the write-up; do not change the workbook by hand.

Flag for review any item over 1,000 in the account's currency or older than 30 days.

### 4. Write the exceptions list

Write /workspace/out/exceptions.md for the reviewer.

- **Status** first, one line: "Reconciled: adjusted balances agree at 8,402.15 GBP" or "Not reconciled: 250.00 unexplained".
- **The reconciliation** in the standard format: balance per bank, each adjustment on the bank side, adjusted bank balance; balance per ledger, each adjustment on the ledger side, adjusted ledger balance; difference. Use the numbers from /tmp/recon/result.json, which match the workbook's Summary sheet.
- **Exceptions**: a table with date (dd/mm/yyyy), description, amount, category, and the action. Investigation items first, then by size.
- **Proposed journal entries** for every "Adjustment required" item, as debit and credit lines with the amount. A bank charge is debit Bank charges, credit Cash at bank. A receipt recorded too high is debit the account it was posted from (usually Accounts receivable), credit Cash at bank, for the difference; recorded too low, the reverse. Mark them as proposed.
- **Matched with a date gap** in one line if any (for example "Client receipt, 640.00: ledger 12/03, bank 15/03").

Keep it to one page. Write amounts with thousands separators and two decimals, and name the currency once.

### 5. Answer

Reply with the status line, the count and total of matched items, and each exception in one line.

Then add `## Assumptions`: which file you treated as which, the account and period used, any rerun flags, and any category you changed from the matcher's.

## Output

- **reconciliation.xlsx**: Summary (the reconciliation, each adjustment the total of its treatment on the Exceptions sheet), Exceptions, Matched, and the Bank and Ledger entries as read.
- **exceptions.md**: status, the reconciliation, each exception with its action, and proposed journal entries.
- **output.json**: matched and unmatched counts and totals, balances, difference.

## Adapting this

- Set your own thresholds in step 3 (review limit, ageing) and the timing window with `--timing-days`.
- Put your chart of accounts in /workspace/knowledge/ and tell step 4 to use its account names and codes in the journal entries.
- For a card or a second bank account, run it once per account; to pull the statement from your bank or accounting app instead of an upload, add a connection and a first step that downloads it.
