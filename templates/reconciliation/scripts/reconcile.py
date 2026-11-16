"""Reconcile a bank statement with the cash account of a ledger.

Usage:
  python3 reconcile.py <bank file> <ledger file> <out_dir> [--window 5] [--flip-bank] [--flip-ledger]
                       [--bank-cols date=Date,desc=Description,amount=Amount,...] [--ledger-cols ...]

Both files may be CSV or Excel. Columns are found by their headers (date,
description, reference, amount or a pair of in/out columns, balance); pass
--bank-cols / --ledger-cols to name them yourself (keys: date, desc, ref,
amount, in, out, balance). Lines starting with # and title rows above the
header are skipped. Amounts are made signed from the bank's point of view:
money in is positive. On the bank side "debit" means money out; on the ledger
(a cash account) "debit" means money in. --flip-* inverts a side's signs.

Matching, one to one:
  1. same amount within --window days (closest date first, then most similar text)
  2. same direction, close amount, similar text within the window: a recording error
Everything left is an exception, categorised as in the standard bank reconciliation.

Writes <out_dir>/reconciliation.xlsx and <out_dir>/output.json, and
/tmp/recon/result.json (every exception, for the write-up). Prints the result.
"""
import argparse
import json
import os
import re
import sys
from datetime import date

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from xlsx_cache import save_with_values  # noqa: E402

RESULT_DIR = "/tmp/recon"
SKIP_ROW = re.compile(r"opening balance|closing balance|balance b/?f|balance c/?f|brought forward|carried forward", re.I)
FEE = re.compile(r"\b(fee|fees|charge|charges|commission|interest|overdraft)\b", re.I)
CREDIT_WORDS = re.compile(r"\binterest\b|\brefund\b|\bcashback\b", re.I)

HEAD = {
    "date": re.compile(r"^(transaction |posting |value |txn )?date$|^date\b|\bdate$", re.I),
    "desc": re.compile(r"desc|narrative|details|memo|payee|particular|transaction$|^text$", re.I),
    "ref": re.compile(r"^ref|reference|doc(ument)? ?(no|number|#)|voucher|journal", re.I),
    "balance": re.compile(r"balance", re.I),
    "amount": re.compile(r"^(amount|value|net amount|amount \(.*\))$", re.I),
    "in": re.compile(r"money in|paid in|deposit|credit|receipt|^in$", re.I),
    "out": re.compile(r"money out|paid out|withdraw|debit|payment|^out$", re.I),
}


def read_raw(path):
    if path.lower().endswith((".xlsx", ".xlsm", ".xls")):
        return pd.read_excel(path, header=None, dtype=object)
    with open(path, encoding="utf-8-sig") as f:
        lines = [ln for ln in f if not ln.lstrip().startswith("#") and ln.strip()]
    from io import StringIO

    return pd.read_csv(StringIO("".join(lines)), header=None, dtype=str, sep=None, engine="python")


def find_header(raw):
    for i in range(min(20, len(raw))):
        cells = [str(v).strip() for v in raw.iloc[i].tolist() if pd.notna(v)]
        if any(HEAD["date"].search(c) for c in cells) and any(HEAD["amount"].search(c) or HEAD["in"].search(c) or HEAD["out"].search(c) for c in cells):
            return i
    sys.exit("Could not find a header row with a date and an amount column. Pass the column names with --bank-cols / --ledger-cols.")


def to_num(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(" ", "").replace(" ", "")
    if not s or s in ("-", "nan"):
        return None
    neg = s.startswith("(") and s.endswith(")") or s.endswith("-")
    s = s.strip("()").rstrip("-")
    s = re.sub(r"[^\d,.\-]", "", s)
    if re.search(r",\d{2}$", s) and "." in s:  # 1.234,56
        s = s.replace(".", "").replace(",", ".")
    elif re.search(r",\d{2}$", s) and s.count(",") == 1 and "." not in s:  # 234,56
        s = s.replace(",", ".")
    else:
        s = s.replace(",", "")
    try:
        n = float(s)
    except ValueError:
        return None
    return -abs(n) if neg else n


def to_date(v, dayfirst):
    if isinstance(v, (pd.Timestamp,)) or hasattr(v, "year"):
        return pd.Timestamp(v).date()
    d = pd.to_datetime(str(v), dayfirst=dayfirst, errors="coerce")
    return None if pd.isna(d) else d.date()


def load(path, side, cols_arg, flip):
    raw = read_raw(path)
    h = find_header(raw)
    headers = [str(v).strip() if pd.notna(v) else "" for v in raw.iloc[h].tolist()]
    body = raw.iloc[h + 1:].reset_index(drop=True)
    body.columns = range(len(headers))
    given = dict(kv.split("=", 1) for kv in cols_arg.split(",")) if cols_arg else {}
    cmap = {}
    for key in ("date", "balance", "amount", "in", "out", "ref", "desc"):
        if key in given:
            if given[key] not in headers:
                sys.exit(f"{side}: column {given[key]!r} not found in {headers}")
            cmap[key] = headers.index(given[key])
            continue
        for j, name in enumerate(headers):
            if j in cmap.values() or not name:
                continue
            if HEAD[key].search(name) and not (key in ("in", "out") and HEAD["balance"].search(name)):
                cmap[key] = j
                break
    if "amount" in cmap:
        cmap.pop("in", None)
        cmap.pop("out", None)
    if "date" not in cmap or not ("amount" in cmap or "in" in cmap or "out" in cmap):
        sys.exit(f"{side}: found columns {cmap} in {headers}; pass --{side}-cols.")
    # Day-first unless a value only parses month-first.
    sample = [str(v) for v in body[cmap["date"]].dropna().tolist() if not hasattr(v, "year")]
    dayfirst = not any(re.match(r"^\d{1,2}/(1[3-9]|2\d|3[01])/", s) for s in sample)
    # On a bank statement "debit" is money out; in a cash ledger it is money in.
    in_col, out_col = cmap.get("in"), cmap.get("out")
    if side == "ledger" and in_col is not None and out_col is not None:
        hi, ho = headers[in_col].lower(), headers[out_col].lower()
        if "credit" in hi and "debit" in ho:
            in_col, out_col = out_col, in_col
            cmap["in"], cmap["out"] = in_col, out_col
    rows, opening = [], None
    for i, r in body.iterrows():
        desc = str(r[cmap["desc"]]).strip() if "desc" in cmap and pd.notna(r[cmap["desc"]]) else ""
        d = to_date(r[cmap["date"]], dayfirst) if pd.notna(r[cmap["date"]]) else None
        bal = to_num(r[cmap["balance"]]) if "balance" in cmap else None
        if SKIP_ROW.search(desc):
            if re.search(r"opening|b/?f|brought", desc, re.I) and bal is not None:
                opening = bal
            continue
        if "amount" in cmap:
            amt = to_num(r[cmap["amount"]])
        else:
            vin = to_num(r[in_col]) if in_col is not None else None
            vout = to_num(r[out_col]) if out_col is not None else None
            amt = None if vin is None and vout is None else (abs(vin or 0) - abs(vout or 0))
        if d is None or amt is None or amt == 0:
            continue
        rows.append({"row": int(i) + h + 2, "date": d, "desc": desc, "amount": round(-amt if flip else amt, 2),
                     "ref": str(r[cmap["ref"]]).strip() if "ref" in cmap and pd.notna(r[cmap["ref"]]) else "", "balance": bal})
    return rows, opening, {k: headers[v] for k, v in cmap.items()}


def closing_balance(rows, opening):
    """(closing, note). Uses the balance column when it runs consistently in file or reverse order."""
    bals = [r["balance"] for r in rows]
    if rows and all(b is not None for b in bals):
        for seq in (rows, rows[::-1]):
            ok = all(abs(seq[k - 1]["balance"] + seq[k]["amount"] - seq[k]["balance"]) < 0.005 for k in range(1, len(seq)))
            if ok:
                first_open = round(seq[0]["balance"] - seq[0]["amount"], 2)
                return seq[-1]["balance"], first_open, "from the balance column"
        return rows[-1]["balance"], None, "from the last balance printed (the column does not run consistently: check it)"
    if opening is not None:
        return round(opening + sum(r["amount"] for r in rows), 2), opening, "opening balance plus the period's entries"
    return None, None, "no balances in the file: movements only"


LABELS = {
    "Deposit in transit": "Add: deposits in transit",
    "Outstanding payment": "Less: outstanding payments",
    "Ledger item to investigate": "Add/(less): ledger items to investigate",
    "Unrecorded bank charge": "Less: bank charges not in the ledger",
    "Unrecorded bank credit": "Add: bank credits not in the ledger",
    "Recording error": "Add/(less): ledger recording errors",
    "Bank item to investigate": "Add/(less): bank items to investigate",
}

TOKEN = re.compile(r"[a-z]{3,}|\d{3,}")


def tokens(s):
    return set(TOKEN.findall(s.lower())) - {"fps", "credit", "debit", "card", "payment", "the", "and", "bacs", "inv", "ltd"}


def sim(a, b):
    ta, tb = tokens(a["desc"] + " " + a["ref"]), tokens(b["desc"] + " " + b["ref"])
    return len(ta & tb) / max(1, min(len(ta), len(tb)))


def match(bank, ledger, window):
    pairs, used_b, used_l = [], set(), set()
    cands = []
    for i, b in enumerate(bank):
        for j, l in enumerate(ledger):
            gap = abs((b["date"] - l["date"]).days)
            if b["amount"] == l["amount"] and gap <= window:
                cands.append((gap, -sim(b, l), i, j))
    for gap, s, i, j in sorted(cands):
        if i not in used_b and j not in used_l:
            used_b.add(i)
            used_l.add(j)
            pairs.append({"b": i, "l": j, "type": "exact" if gap == 0 else "date differs", "gap": gap})
    near = []
    for i, b in enumerate(bank):
        if i in used_b:
            continue
        for j, l in enumerate(ledger):
            if j in used_l or (b["amount"] > 0) != (l["amount"] > 0):
                continue
            gap = abs((b["date"] - l["date"]).days)
            diff = round(b["amount"] - l["amount"], 2)
            s = sim(b, l)
            transposed = round(abs(diff) * 100) % 9 == 0
            if gap <= window and s >= 0.5 and (abs(diff) <= 0.1 * abs(l["amount"]) or transposed):
                near.append((-s, gap, abs(diff), i, j))
    for _s, gap, _d, i, j in sorted(near):
        if i not in used_b and j not in used_l:
            used_b.add(i)
            used_l.add(j)
            pairs.append({"b": i, "l": j, "type": "amount differs", "gap": gap})
    return pairs, [i for i in range(len(bank)) if i not in used_b], [j for j in range(len(ledger)) if j not in used_l]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("bank")
    ap.add_argument("ledger")
    ap.add_argument("out_dir")
    ap.add_argument("--window", type=int, default=5)
    ap.add_argument("--flip-bank", action="store_true")
    ap.add_argument("--flip-ledger", action="store_true")
    ap.add_argument("--bank-cols", default="")
    ap.add_argument("--ledger-cols", default="")
    ap.add_argument("--timing-days", type=int, default=10, help="ledger items this close to period end are timing differences")
    a = ap.parse_args()

    bank, bank_open, bank_cols = load(a.bank, "bank", a.bank_cols, a.flip_bank)
    ledger, led_open, led_cols = load(a.ledger, "ledger", a.ledger_cols, a.flip_ledger)
    if not bank or not ledger:
        sys.exit("One of the files has no transactions after reading.")
    bank_close, bank_open2, bank_note = closing_balance(bank, bank_open)
    led_close, led_open2, led_note = closing_balance(ledger, led_open)
    pairs, ub, ul = match(bank, ledger, a.window)
    period_end = max(max(r["date"] for r in bank), max(r["date"] for r in ledger))

    exceptions = []
    for p in pairs:
        if p["type"] == "amount differs":
            b, l = bank[p["b"]], ledger[p["l"]]
            exceptions.append({"source": "Amount differs", "date": b["date"], "desc": f"{l['desc']} (bank: {b['desc']})", "ref": l["ref"],
                               "bank_amount": b["amount"], "ledger_amount": l["amount"], "adjust": round(b["amount"] - l["amount"], 2),
                               "side": "Ledger", "category": "Adjustment required", "treatment": "Recording error",
                               "action": f"Correct the ledger entry from {l['amount']:,.2f} to {b['amount']:,.2f} if the bank amount is right; check the invoice."})
    for i in ub:
        b = bank[i]
        if FEE.search(b["desc"]):
            credit = b["amount"] > 0 or CREDIT_WORDS.search(b["desc"])
            t = "Unrecorded bank credit" if b["amount"] > 0 else "Unrecorded bank charge"
            act = "Record it in the ledger." if not credit else "Record the credit in the ledger."
            cat = "Adjustment required"
        else:
            t, cat = "Bank item to investigate", "Requires investigation"
            act = "Find the source document; record it in the ledger if it belongs to this account."
        exceptions.append({"source": "Bank only", "date": b["date"], "desc": b["desc"], "ref": b["ref"], "bank_amount": b["amount"],
                           "ledger_amount": None, "adjust": b["amount"], "side": "Ledger", "category": cat, "treatment": t, "action": act})
    for j in ul:
        l = ledger[j]
        age = (period_end - l["date"]).days
        if age <= a.timing_days:
            t = "Deposit in transit" if l["amount"] > 0 else "Outstanding payment"
            cat, act = "Timing difference", "Should clear in the next few days; confirm on next month's statement."
        else:
            t, cat = "Ledger item to investigate", "Requires investigation"
            act = f"Not in the bank after {age} days: check whether it was paid, cancelled or posted twice."
        exceptions.append({"source": "Ledger only", "date": l["date"], "desc": l["desc"], "ref": l["ref"], "bank_amount": None,
                           "ledger_amount": l["amount"], "adjust": l["amount"], "side": "Bank", "category": cat, "treatment": t, "action": act})
    for e in exceptions:
        e["age_days"] = (period_end - e["date"]).days
    exceptions.sort(key=lambda e: (e["category"] != "Requires investigation", -abs(e["adjust"])))

    movements_only = bank_close is None or led_close is None
    bank_base = round(sum(r["amount"] for r in bank), 2) if movements_only else bank_close
    led_base = round(sum(r["amount"] for r in ledger), 2) if movements_only else led_close
    adj_bank = round(bank_base + sum(e["adjust"] for e in exceptions if e["side"] == "Bank"), 2)
    adj_led = round(led_base + sum(e["adjust"] for e in exceptions if e["side"] == "Ledger"), 2)
    exact = [p for p in pairs if p["type"] != "amount differs"]
    out = {
        "period_end": period_end.isoformat(),
        "basis": "movements" if movements_only else "closing balances",
        "matched_count": len(exact),
        "matched_total": round(sum(bank[p["b"]]["amount"] for p in exact), 2),
        "amount_differences_count": len(pairs) - len(exact),
        "amount_differences_total": round(sum(e["adjust"] for e in exceptions if e["source"] == "Amount differs"), 2),
        "unmatched_bank_count": len(ub),
        "unmatched_bank_total": round(sum(bank[i]["amount"] for i in ub), 2),
        "unmatched_ledger_count": len(ul),
        "unmatched_ledger_total": round(sum(ledger[j]["amount"] for j in ul), 2),
        "bank_closing_balance": bank_close,
        "ledger_closing_balance": led_close,
        "adjusted_bank_balance": adj_bank,
        "adjusted_ledger_balance": adj_led,
        "difference": round(adj_bank - adj_led, 2),
        "reconciled": abs(adj_bank - adj_led) < 0.005,
    }
    os.makedirs(a.out_dir, exist_ok=True)
    os.makedirs(RESULT_DIR, exist_ok=True)
    write_xlsx(os.path.join(a.out_dir, "reconciliation.xlsx"), bank, ledger, pairs, exceptions, out, bank_base, led_base, movements_only)
    with open(os.path.join(a.out_dir, "output.json"), "w") as f:
        json.dump(out, f, indent=2)
    detail = {**out, "columns": {"bank": bank_cols, "ledger": led_cols}, "balance_notes": {"bank": bank_note, "ledger": led_note},
              "opening_balances": {"bank": bank_open2, "ledger": led_open2},
              "transactions": {"bank": len(bank), "ledger": len(ledger)},
              "exceptions": [{**e, "date": e["date"].isoformat()} for e in exceptions],
              "matched_with_date_gap": [{"date_bank": bank[p["b"]]["date"].isoformat(), "date_ledger": ledger[p["l"]]["date"].isoformat(),
                                         "desc": ledger[p["l"]]["desc"], "amount": ledger[p["l"]]["amount"]} for p in pairs if p["type"] == "date differs"]}
    with open(os.path.join(RESULT_DIR, "result.json"), "w") as f:
        json.dump(detail, f, indent=2, default=str)
    print(json.dumps(detail, indent=2, default=str))


def write_xlsx(path, bank, ledger, pairs, exceptions, out, bank_base, led_base, movements_only):
    wb = Workbook()
    f = Font(name="Arial", size=10)
    fb = Font(name="Arial", size=10, bold=True)
    blue = Font(name="Arial", size=10, color="0000FF")
    hf = Font(name="Arial", size=10, bold=True, color="FFFFFF")
    fill = PatternFill("solid", fgColor="1F2A36")
    money = "#,##0.00;(#,##0.00);-"
    cache = {"Summary": {}}

    def header(ws, names, widths):
        for j, (n, w) in enumerate(zip(names, widths), 1):
            c = ws.cell(1, j, n)
            c.font, c.fill = hf, fill
            c.alignment = Alignment(wrap_text=True, vertical="center")
            ws.column_dimensions[get_column_letter(j)].width = w
        ws.freeze_panes = "A2"

    # Exceptions
    ex = wb.active
    ex.title = "Exceptions"
    header(ex, ["#", "Source", "Date", "Description", "Reference", "Bank amount", "Ledger amount", "Adjustment", "Adjust on",
                "Category", "Treatment", "Age (days)", "Suggested action"], [5, 14, 12, 44, 12, 14, 14, 14, 10, 22, 24, 10, 60])
    for k, e in enumerate(exceptions, 2):
        vals = [k - 1, e["source"], e["date"], e["desc"], e["ref"], e["bank_amount"], e["ledger_amount"], e["adjust"], e["side"],
                e["category"], e["treatment"], e["age_days"], e["action"]]
        for j, v in enumerate(vals, 1):
            c = ex.cell(k, j, v)
            c.font = f
            if j == 3:
                c.number_format = "dd/mm/yyyy"
            if j in (6, 7, 8):
                c.number_format = money
    n_ex = len(exceptions) + 1

    # Matched
    mt = wb.create_sheet("Matched")
    header(mt, ["Bank date", "Bank description", "Bank amount", "Ledger date", "Ledger ref", "Ledger description", "Ledger amount", "Match", "Days apart"],
           [12, 38, 14, 12, 12, 38, 14, 16, 10])
    for k, p in enumerate(sorted(pairs, key=lambda p: bank[p["b"]]["date"]), 2):
        b, l = bank[p["b"]], ledger[p["l"]]
        for j, v in enumerate([b["date"], b["desc"], b["amount"], l["date"], l["ref"], l["desc"], l["amount"], p["type"], p["gap"]], 1):
            c = mt.cell(k, j, v)
            c.font = f
            c.number_format = "dd/mm/yyyy" if j in (1, 4) else money if j in (3, 7) else "General"

    # Inputs as read
    for name, rows in (("Bank", bank), ("Ledger", ledger)):
        ws = wb.create_sheet(name)
        header(ws, ["Date", "Description", "Reference", "Amount (in +, out -)", "Source row"], [12, 44, 12, 18, 10])
        for k, r in enumerate(rows, 2):
            for j, v in enumerate([r["date"], r["desc"], r["ref"], r["amount"], r["row"]], 1):
                c = ws.cell(k, j, v)
                c.font = blue if j == 4 else f
                c.number_format = "dd/mm/yyyy" if j == 1 else money if j == 4 else "General"

    # Summary, the standard format, as formulas over Exceptions
    s = wb.create_sheet("Summary", 0)
    s.column_dimensions["A"].width = 46
    s.column_dimensions["B"].width = 16
    s.column_dimensions["C"].width = 40
    s["A1"] = "Bank reconciliation"
    s["A1"].font = Font(name="Arial", size=14, bold=True)
    s["A2"] = f"Period ending {date.fromisoformat(out['period_end']).strftime('%d/%m/%Y')}" + (" (movements only: no balances in the files)" if movements_only else "")
    s["A2"].font = Font(name="Arial", size=10, italic=True, color="5B6570")
    rng = f"Exceptions!$K$2:$K${max(n_ex, 2)}"
    amt = f"Exceptions!$H$2:$H${max(n_ex, 2)}"

    def line(r, label, value=None, formula=None, cached=None, bold=False, inp=False):
        s.cell(r, 1, label).font = fb if bold else f
        c = s.cell(r, 2, formula if formula else value)
        c.font = fb if bold else blue if inp else f
        c.number_format = money
        if formula:
            cache["Summary"][f"B{r}"] = cached

    by_t = {}
    for e in exceptions:
        by_t[e["treatment"]] = round(by_t.get(e["treatment"], 0) + e["adjust"], 2)
    r = 4
    line(r, "Movements per bank statement" if movements_only else "Balance per bank statement", value=bank_base, inp=True)
    first_b = r
    for t in ("Deposit in transit", "Outstanding payment", "Ledger item to investigate"):
        r += 1
        line(r, LABELS[t], formula=f'=SUMIFS({amt},{rng},"{t}")', cached=by_t.get(t, 0))
    r += 1
    line(r, "Adjusted bank balance", formula=f"=SUM(B{first_b}:B{r - 1})", cached=out["adjusted_bank_balance"], bold=True)
    adj_b = r
    r += 2
    line(r, "Movements per ledger" if movements_only else "Balance per ledger", value=led_base, inp=True)
    first_l = r
    for t in ("Unrecorded bank charge", "Unrecorded bank credit", "Recording error", "Bank item to investigate"):
        r += 1
        line(r, LABELS[t], formula=f'=SUMIFS({amt},{rng},"{t}")', cached=by_t.get(t, 0))
    r += 1
    line(r, "Adjusted ledger balance", formula=f"=SUM(B{first_l}:B{r - 1})", cached=out["adjusted_ledger_balance"], bold=True)
    adj_l = r
    r += 2
    line(r, "Difference", formula=f"=B{adj_b}-B{adj_l}", cached=out["difference"], bold=True)
    s.cell(r, 3, "Reconciled" if out["reconciled"] else "Not reconciled: see Exceptions").font = fb
    r += 2
    stats = [("Matched", out["matched_count"], out["matched_total"]), ("Amount differs", out["amount_differences_count"], out["amount_differences_total"]),
             ("In bank only", out["unmatched_bank_count"], out["unmatched_bank_total"]), ("In ledger only", out["unmatched_ledger_count"], out["unmatched_ledger_total"])]
    for j, h in enumerate(("Items", "Count", "Net amount"), 1):
        c = s.cell(r, j, h)
        c.font, c.fill = hf, fill
    for label, cnt, tot in stats:
        r += 1
        s.cell(r, 1, label).font = f
        s.cell(r, 2, cnt).font = f
        c = s.cell(r, 3, tot)
        c.font, c.number_format = f, money
    r += 2
    s.cell(r, 1, "Blue = taken from the files. The adjustments are formulas over the Exceptions sheet. Prepared automatically; review before sign-off.").font = Font(name="Arial", size=9, italic=True, color="5B6570")
    save_with_values(wb, path, cache)


if __name__ == "__main__":
    main()
