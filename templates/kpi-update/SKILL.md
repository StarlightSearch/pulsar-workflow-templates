---
name: kpi-update
description: >-
  Reads a metrics table (CSV or Excel, one row per week or month) and writes a
  short KPI update: what changed since the last period, what moved and why it
  likely did, with a chart and a workbook.
---

# KPI update

Turns a metrics export into the update someone would post on Monday morning: the headline, the numbers, and a plain explanation of what moved. The value is in the explanation, so every claim must come from the data, with its size stated.

## Inputs

- **Metrics**: one CSV or Excel file in /workspace/inputs/ with a date column and one numeric column per metric (one row per day, week or month). A long table of date, metric, value also works.
- **Context**: optional text, for example the audience, a target to compare against, or something that happened ("ran a promo the week of 19 October").

## Steps

### 1. Look at the data

Open the file and decide which columns are metrics, what one row covers, and how the metrics relate.

Check the libraries first: run `python3 -c "import pandas, openpyxl, matplotlib"`; if it fails, run `pip install --quiet --user --break-system-packages pandas openpyxl matplotlib`, check again, and if it still fails say which package is missing and stop.

Take the file path from /workspace/inputs/ and read the first rows with pandas. Decide:

- **Metrics**: every numeric column, unless it is an id or a code. Leave out columns that are obviously not KPIs and say so.
- **Rates**: if two metrics form a natural rate, add it, at most three (each rate is another panel in the chart and row in the table, so more crowd the update): a conversion rate (an outcome per visit, lead or trial) and an average value (an amount per order or per customer) are the usual ones. In a funnel with several steps (visits, then leads, then sales), add the rate for each step you may need to explain a move, such as leads per visit as well as sales per visit. A rate often explains a move better than either count.
- **Lower is better**: refunds, churn, cancellations, costs, complaints, errors and response times. Everything else is higher is better.
- **Partial period**: decide from the data, never from today's date. Treat the last row as incomplete only when the file or the Context says so (a note, a "partial" or "to date" label, a column marking it), or when step 2 reports `last_period_looks_partial: true` (every count fell by more than 35% at once, steady ones included, which is what a cut-off period looks like). Then rerun step 2 with `--drop-last` and say so in the update. Otherwise the last row is the latest period.

### 2. Compute the numbers

Run the analysis script, which does all the arithmetic, the chart and the workbook.

`python3 /workspace/workflow/scripts/analyse.py <file> /workspace/out --ratio <rate name>=<numerator column>/<denominator column> --lower-is-better <column> <column>`

For example `--ratio tickets_per_account=tickets/active_accounts --lower-is-better tickets churned`. Leave out `--ratio` and `--lower-is-better` when nothing applies. Add `--date <column>` if the script cannot find the date column.

It writes /workspace/out/chart.png and /workspace/out/workbook.xlsx and prints a summary (also saved to /tmp/kpi/summary.json): for each metric the latest value, the change against the previous period and against the average of the four before it, a flag `moved` (15% or more against the previous period, or far outside the last eight), `earlier_spikes` for unusual periods before the latest one, and `last_period_looks_partial` (see step 1). Use these numbers as given; do not recompute them by hand.

### 3. Explain what moved

For each metric with `moved: true`, work out the most likely driver from the other metrics, and check the explanation holds.

- Trace counts back through the funnel: if an outcome fell while the step before it held steady, the problem is the conversion between them, not the volume coming in; if an amount fell with the count while the average value held, it is volume, not price.
- A move that undoes an earlier spike (a cost back to its usual level after a one-off period) is a return to normal: say that rather than calling it a gain or a loss.
- Use the Context input when it explains a period. Otherwise do not invent outside causes such as a campaign, a holiday or a bug: say what the data shows, that it does not say why, and the one thing worth checking first.
- Quantify every claim with the latest value, the change in percent, and the comparison it is against. Every number in the update comes from the summary: if the explanation needs a rate step 2 did not compute, rerun step 2 with that `--ratio` added rather than working it out by hand, so the update, the chart and the workbook agree.
- Sanity check before writing: changes have the sign you describe, rates are between 0 and 100%, and the period count matches the file. Note any missing values or gaps the summary reports.

### 4. Write the update

Write /workspace/out/update.md in this shape, short enough to read in a minute:

```markdown
# KPI update: month of 03/2026

**Support tickets rose 31% in March while active accounts grew only 4%, so tickets per account are up a quarter.**

| Metric | This month | vs last month | vs 4-month average |
|---|---|---|---|
| Active accounts | 4,120 | +4.0% | +6.2% |

## What moved
- **Tickets: 1,388, up 31.0% on February** and 28.4% above the 4-month average. Accounts grew 4.0%, so tickets per account rose from 0.27 to 0.34: the rise is per customer, not from growth. Check which ticket topics grew first.

## Worth watching
- One or two lines on earlier spikes or slow trends worth a look.

## About the data
12 months, 04/2025 to 03/2026. Anything partial, missing or assumed.

![Metrics over the last 12 months](chart.png)
```

- The headline is one sentence naming the biggest move and its size. When several metrics moved for one reason, name the one where it starts (the first step of the funnel that fell or rose, found in step 3) with its size, then what followed from it; a downstream total alone hides the cause.
- The table has every metric, with numbers formatted for reading (thousands separators, rates as percentages, money with its currency).
- "What moved" has one bullet per moved metric, biggest business impact first. Group metrics that moved for one reason into one bullet.
- If nothing moved, say "A steady week" in the headline and keep "What moved" to one line.
- Dates are written dd/mm/yyyy.
- The chart line is the last line of update.md. Assumptions go in the answer (step 5), not in the file: the file is what gets posted.

### 5. Answer

Reply with the headline and the "What moved" bullets.

Then add `## Assumptions`: the metrics you left out, the rates you added, what you treated as lower is better, and any partial period you dropped.

## Output

- **update.md**: the KPI update.
- **chart.png**: one small chart per metric, the latest point marked (red when it moved the wrong way, green the right way).
- **workbook.xlsx**: the data (inputs in blue, with any rates) and a Summary sheet with the latest period, previous period, change and 4-period average for each metric.

## Adapting this

- Name your KPIs and their direction once in step 1 (or in a file under /workspace/knowledge/) so every run reads them the same way.
- Change the 15% threshold with `--threshold 0.1` if your metrics are steadier, or add targets to the Context input to compare against plan.
- To post the update, add a connection (Slack, email) in the frontmatter and a final step that sends update.md with the chart.
