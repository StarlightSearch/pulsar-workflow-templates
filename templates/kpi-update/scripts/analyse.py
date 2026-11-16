"""Compute a KPI update from a metrics table: changes, notable moves, a chart and a workbook.

Usage:
  python3 analyse.py <metrics.csv|.xlsx> <out_dir> [--date COL] [--ratio NAME=NUM/DEN ...]
                     [--threshold 0.15] [--lower-is-better COL ...]

Reads one row per period (a date column plus numeric metric columns; a long
table of date, metric, value is pivoted). Lines starting with # are skipped.
Writes:
  <out_dir>/chart.png      small multiples, one panel per metric, latest point marked
  <out_dir>/workbook.xlsx  Data sheet (inputs) and Summary sheet (live formulas)
  /tmp/kpi/summary.json    the numbers the update is written from
and prints summary.json.

A metric "moved" when the latest period differs from the previous one by at
least --threshold (default 15%) or sits more than 2 standard deviations from
the mean of the 8 periods before it.
"""
import argparse
import json
import os
import sys

import matplotlib
import matplotlib.dates
import matplotlib.ticker

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
from openpyxl import Workbook  # noqa: E402
from openpyxl.styles import Alignment, Font, PatternFill  # noqa: E402
from openpyxl.utils import get_column_letter  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from xlsx_cache import save_with_values  # noqa: E402

SUMMARY_DIR = "/tmp/kpi"


def load(path, date_col):
    if path.lower().endswith((".xlsx", ".xlsm", ".xls")):
        df = pd.read_excel(path)
    else:
        with open(path, encoding="utf-8-sig") as f:
            lines = [ln for ln in f if not ln.lstrip().startswith("#")]
        from io import StringIO

        df = pd.read_csv(StringIO("".join(lines)), sep=None, engine="python")
    df.columns = [str(c).strip() for c in df.columns]
    if date_col is None:
        for c in df.columns:
            parsed = pd.to_datetime(df[c], errors="coerce")
            if parsed.notna().mean() > 0.8 and not pd.api.types.is_numeric_dtype(df[c]):
                date_col = c
                break
    if date_col is None:
        sys.exit("No date column found. Pass --date <column>.")
    df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
    df = df.dropna(subset=[date_col])
    text_cols = [c for c in df.columns if c != date_col and not pd.api.types.is_numeric_dtype(df[c])]
    num_cols = [c for c in df.columns if c != date_col and pd.api.types.is_numeric_dtype(df[c])]
    if len(text_cols) == 1 and len(num_cols) == 1:  # long format: date, metric, value
        df = df.pivot_table(index=date_col, columns=text_cols[0], values=num_cols[0], aggfunc="sum").reset_index()
        df.columns.name = None
    for c in df.columns:
        if c != date_col and not pd.api.types.is_numeric_dtype(df[c]):
            cleaned = pd.to_numeric(df[c].astype(str).str.replace(r"[,\s%$€£]", "", regex=True), errors="coerce")
            if cleaned.notna().mean() > 0.8:
                df[c] = cleaned
    metrics = [c for c in df.columns if c != date_col and pd.api.types.is_numeric_dtype(df[c])]
    df = df.groupby(date_col, as_index=False)[metrics].sum().sort_values(date_col).reset_index(drop=True)
    return df, date_col, metrics


def period_name(dates):
    if len(dates) < 2:
        return "period"
    gap = dates.diff().dt.days.median()
    return "day" if gap <= 1.5 else "week" if gap <= 8 else "month" if gap <= 31.5 else "quarter" if gap <= 95 else "year"


def pct(a, b):
    return None if b in (0, None) or pd.isna(b) else (a - b) / abs(b)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("out_dir")
    ap.add_argument("--date")
    ap.add_argument("--ratio", action="append", default=[])
    ap.add_argument("--threshold", type=float, default=0.15)
    ap.add_argument("--lower-is-better", nargs="*", default=[])
    a = ap.parse_args()

    df, dcol, metrics = load(a.src, a.date)
    if len(df) < 2:
        sys.exit("Need at least two periods to compare.")
    ratio_cols = []
    for spec in a.ratio:
        name, expr = spec.split("=", 1)
        num, den = expr.split("/", 1)
        df[name] = df[num] / df[den].where(df[den] != 0)
        ratio_cols.append({"name": name, "num": num, "den": den})
    allm = metrics + [r["name"] for r in ratio_cols]
    unit = period_name(df[dcol])

    last, prev = df.iloc[-1], df.iloc[-2]
    rows = []
    for m in allm:
        s = df[m]
        base = s.iloc[max(0, len(s) - 9):-1]
        avg4 = s.iloc[max(0, len(s) - 5):-1].mean()
        sd = base.std() if len(base) >= 3 else None
        z = None if not sd else (s.iloc[-1] - base.mean()) / sd
        ch = pct(last[m], prev[m])
        moved = (ch is not None and abs(ch) >= a.threshold) or (z is not None and abs(z) > 2)
        good = None if ch is None or ch == 0 else bool((ch < 0) == (m in a.lower_is_better))
        peak_i = int(s.idxmax())
        rows.append({
            "metric": m, "is_ratio": m in [r["name"] for r in ratio_cols],
            "latest": round(float(last[m]), 4), "previous": round(float(prev[m]), 4),
            "change": round(float(last[m] - prev[m]), 4), "change_pct": None if ch is None else round(float(ch) * 100, 1),
            "vs_4_period_avg_pct": None if pd.isna(avg4) or avg4 == 0 else round((last[m] - avg4) / abs(avg4) * 100, 1),
            "z_vs_8_periods": None if z is None else round(float(z), 2),
            "moved": bool(moved), "direction_good": good,
            "first": round(float(s.iloc[0]), 4), "change_over_range_pct": None if pct(s.iloc[-1], s.iloc[0]) is None else round(pct(s.iloc[-1], s.iloc[0]) * 100, 1),
            "peak": round(float(s.max()), 4), "peak_period": df[dcol].iloc[peak_i].date().isoformat(),
        })
    # Earlier spikes: any period (not the latest) more than 2 sd from the rest of the series.
    spikes = []
    for m in allm:
        s = df[m].iloc[:-1]
        for i in range(len(s)):
            rest = s.drop(s.index[i])
            if len(rest) >= 4 and rest.std() and abs(s.iloc[i] - rest.mean()) / rest.std() > 2.5:
                spikes.append({"metric": m, "period": df[dcol].iloc[i].date().isoformat(), "value": round(float(s.iloc[i]), 4),
                               "pct_vs_rest_mean": round(float((s.iloc[i] - rest.mean()) / abs(rest.mean()) * 100), 1)})

    os.makedirs(a.out_dir, exist_ok=True)
    os.makedirs(SUMMARY_DIR, exist_ok=True)
    chart(df, dcol, allm, unit, os.path.join(a.out_dir, "chart.png"), {r["metric"]: r for r in rows})
    workbook(df, dcol, metrics, ratio_cols, unit, os.path.join(a.out_dir, "workbook.xlsx"))

    gaps = int((df[dcol].diff().dt.days > 1.6 * df[dcol].diff().dt.days.median()).sum())
    summary = {
        "period_unit": unit, "periods": len(df),
        "first_period": df[dcol].iloc[0].date().isoformat(), "latest_period": df[dcol].iloc[-1].date().isoformat(),
        "previous_period": df[dcol].iloc[-2].date().isoformat(), "threshold_pct": a.threshold * 100,
        "metrics": rows, "earlier_spikes": spikes,
        "data_notes": {"missing_values": {m: int(df[m].isna().sum()) for m in allm if df[m].isna().any()},
                       "gaps_in_dates": gaps, "ratios": ratio_cols},
    }
    with open(os.path.join(SUMMARY_DIR, "summary.json"), "w") as f:
        json.dump(summary, f, indent=2)
    print(json.dumps(summary, indent=2))


def label(m):
    words = m.replace("_", " ").strip().split()
    units = {"eur": "(EUR)", "usd": "(USD)", "gbp": "(GBP)", "pct": "(%)"}
    if len(words) > 1 and words[-1].lower() in units:
        words[-1] = units[words[-1].lower()]
    return " ".join(words).capitalize().replace("(eur)", "(EUR)").replace("(usd)", "(USD)").replace("(gbp)", "(GBP)")


def tick_format(series, is_ratio):
    top = float(series.abs().max() or 0)
    if is_ratio and top <= 1:
        return lambda v, _p: f"{v:.1%}"
    if top >= 100:
        return lambda v, _p: f"{v:,.0f}"
    return lambda v, _p: f"{v:,.2f}"


def chart(df, dcol, allm, unit, path, info):
    n = len(allm)
    cols = 3 if n > 4 else 2 if n > 1 else 1
    rws = -(-n // cols)
    fig, axes = plt.subplots(rws, cols, figsize=(4.4 * cols, 2.7 * rws), squeeze=False)
    for i, m in enumerate(allm):
        ax = axes[i // cols][i % cols]
        ax.plot(df[dcol], df[m], color="#5B6B7A", linewidth=1.8)
        r = info[m]
        hl = "#B42318" if r["moved"] and r["direction_good"] is False else "#1E7B45" if r["moved"] else "#1F2A36"
        ax.scatter([df[dcol].iloc[-1]], [df[m].iloc[-1]], color=hl, s=36, zorder=3)
        ch = r["change_pct"]
        tail = "" if ch is None else "  flat vs last " + unit if abs(ch) < 0.05 else f"  {ch:+.1f}% vs last {unit}"
        ax.set_title(label(m) + tail, fontsize=10, loc="left",
                     color=hl if r["moved"] else "#1F2A36", fontweight="bold" if r["moved"] else "normal")
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        ax.tick_params(labelsize=8)
        ax.grid(axis="y", color="#E5E8EC", linewidth=0.8)
        if df[m].min() >= 0:
            ax.set_ylim(bottom=0)
        ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(tick_format(df[m], r["is_ratio"])))
        ax.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%d/%m"))
        ax.xaxis.set_major_locator(matplotlib.ticker.MaxNLocator(6))
    for j in range(n, rws * cols):
        axes[j // cols][j % cols].axis("off")
    latest = df[dcol].iloc[-1].strftime("%d/%m/%Y")
    fig.suptitle(f"Last {len(df)} {unit}s, latest {unit} starting {latest}", fontsize=11, x=0.01, ha="left")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def workbook(df, dcol, metrics, ratio_cols, unit, path):
    wb = Workbook()
    base = Font(name="Arial", size=10)
    bold = Font(name="Arial", size=10, bold=True)
    blue = Font(name="Arial", size=10, color="0000FF")  # hard-coded inputs
    head_fill = PatternFill("solid", fgColor="1F2A36")
    head_font = Font(name="Arial", size=10, bold=True, color="FFFFFF")

    cache = {"Data": {}, "Summary": {}}
    data = wb.active
    data.title = "Data"
    cols = [dcol] + metrics
    for j, c in enumerate(cols, 1):
        cell = data.cell(1, j, c)
        cell.font, cell.fill = head_font, head_fill
        data.column_dimensions[get_column_letter(j)].width = 14
    for i, row in df.iterrows():
        r = i + 2
        d = data.cell(r, 1, row[dcol].date())
        d.number_format, d.font = "dd/mm/yyyy", base
        for j, m in enumerate(metrics, 2):
            v = row[m]
            c = data.cell(r, j, None if pd.isna(v) else float(v))
            c.font = blue
            c.number_format = "#,##0" if float(df[m].dropna().abs().max() or 0) >= 100 and (df[m].dropna() % 1 == 0).all() else "#,##0.00"
    # ratio columns as formulas on the Data sheet
    letter = {m: get_column_letter(j) for j, m in enumerate(cols, 1)}
    for k, rc in enumerate(ratio_cols):
        j = len(cols) + 1 + k
        col = get_column_letter(j)
        letter[rc["name"]] = col
        h = data.cell(1, j, rc["name"])
        h.font, h.fill = head_font, head_fill
        data.column_dimensions[col].width = 14
        for r in range(2, len(df) + 2):
            c = data.cell(r, j, f'=IF({letter[rc["den"]]}{r}=0,"",{letter[rc["num"]]}{r}/{letter[rc["den"]]}{r})')
            v = df[rc["name"]].iloc[r - 2]
            cache["Data"][f"{col}{r}"] = "" if pd.isna(v) else float(v)
            c.font, c.number_format = base, "0.00%" if float(df[rc["name"]].max()) <= 1 else "#,##0.00"
    data.freeze_panes = "B2"
    last, prev = len(df) + 1, len(df)

    s = wb.create_sheet("Summary", 0)
    s["A1"], s["A1"].font = "KPI update", Font(name="Arial", size=14, bold=True)
    s["A2"] = "Latest"
    s["B2"] = f"=Data!A{last}"
    s["A3"] = "Previous"
    s["B3"] = f"=Data!A{prev}"
    cache["Summary"].update(B2=df[dcol].iloc[-1].date(), B3=df[dcol].iloc[-2].date())
    for c in ("A2", "A3"):
        s[c].font = bold
    for c in ("B2", "B3"):
        s[c].font, s[c].number_format = base, "dd/mm/yyyy"
    hdr = ["Metric", f"Latest {unit}", f"Previous {unit}", "Change", "Change %", "4-period average", "vs average %"]
    for j, h in enumerate(hdr, 1):
        c = s.cell(5, j, h)
        c.font, c.fill = head_font, head_fill
        c.alignment = Alignment(horizontal="center", wrap_text=True)
        s.column_dimensions[get_column_letter(j)].width = 16 if j > 1 else 22
    first4 = max(2, last - 4)
    for i, m in enumerate(metrics + [r["name"] for r in ratio_cols]):
        r = 6 + i
        L = letter[m]
        fmt = data[f"{L}2"].number_format
        s.cell(r, 1, m).font = base
        s.cell(r, 2, f"=Data!{L}{last}")
        s.cell(r, 3, f"=Data!{L}{prev}")
        s.cell(r, 4, f"=B{r}-C{r}")
        s.cell(r, 5, f'=IF(C{r}=0,"",B{r}/C{r}-1)')
        s.cell(r, 6, f"=AVERAGE(Data!{L}{first4}:{L}{last - 1})")
        s.cell(r, 7, f'=IF(F{r}=0,"",B{r}/F{r}-1)')
        ser = df[m]
        lv, pv, av = float(ser.iloc[-1]), float(ser.iloc[-2]), float(ser.iloc[first4 - 2:last - 2].mean())
        cache["Summary"].update({f"B{r}": lv, f"C{r}": pv, f"D{r}": lv - pv, f"E{r}": "" if pv == 0 else lv / pv - 1,
                                 f"F{r}": av, f"G{r}": "" if av == 0 else lv / av - 1})
        for j in range(2, 8):
            c = s.cell(r, j)
            c.font = base
            c.number_format = "0.0%;-0.0%;-" if j in (5, 7) else fmt
    note = 7 + len(metrics) + len(ratio_cols)
    s.cell(note, 1, "Inputs are on the Data sheet (blue). Every number here is a formula, so it updates when you paste new rows and adjust the row references.").font = Font(name="Arial", size=9, italic=True, color="5B6570")
    save_with_values(wb, path, cache)


if __name__ == "__main__":
    main()
