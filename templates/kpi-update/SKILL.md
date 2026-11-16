---
name: kpi-update
description: >-
  Reads a metrics table (CSV or Excel, one row per week or month) and writes a
  short KPI update: what changed since the last period, what moved and why it
  likely did, with a chart and a workbook of live formulas.
---

# KPI update

Turns a metrics export into the update someone would post on Monday morning: the headline, the numbers, and a plain explanation of what moved. The value is in the explanation, so every claim must come from the data, with its size stated.

## Inputs

- **Metrics**: one CSV or Excel file in /workspace/inputs/ with a date column and one numeric column per metric (one row per day, week or month). A long table of date, metric, value also works.
- **Context**: optional text, for example the audience, a target to compare against, or something that happened ("ran a promo the week of 19 October").

## Steps

### 1. Look at the data

Open the file and decide which columns are metrics, what one row covers, and how the metrics relate.

Take the file path from /workspace/inputs/ and read the first rows with pandas. Decide:

- **Metrics**: every numeric column, unless it is an id or a code. Leave out columns that are obviously not KPIs and say so.
- **Rates**: if two metrics form a natural rate, add it, at most two: conversion (signups or orders per visitor) and average value (revenue per order) are the usual ones. A rate often explains a move better than either count.
- **Lower is better**: refunds, churn, cancellations, costs, complaints, errors and response times. Everything else is higher is better.
- **Partial period**: run `date +%F`. If the latest row's period has not finished yet (a week starting less than 7 days ago, a month not yet over), say so in the update and compare the latest complete period instead by dropping that row into a copy of the file under /tmp.

### 2. Compute the numbers

Run the analysis script, which does all the arithmetic, the chart and the workbook.

`python3 /workspace/workflow/scripts/analyse.py <file> /workspace/out --ratio signup_rate=signups/visitors --ratio avg_order_value=revenue_eur/orders --lower-is-better refunds_eur`

Use your own column names; leave out `--ratio` and `--lower-is-better` when nothing applies. Add `--date <column>` if the script cannot find the date column.

It writes /workspace/out/chart.png and /workspace/out/workbook.xlsx and prints a summary (also saved to /tmp/kpi/summary.json): for each metric the latest value, the change against the previous period and against the average of the four before it, a flag `moved` (15% or more against the previous period, or far outside the last eight), and `earlier_spikes` for unusual periods before the latest one. Use these numbers as given; do not recompute them by hand.

### 3. Explain what moved

For each metric with `moved: true`, work out the most likely driver from the other metrics, and check the explanation holds.

- Trace counts back through the funnel: if signups fell while visitors held steady, the problem is conversion, not traffic; if revenue fell with orders while average order value held, it is volume, not price.
- A move that undoes an earlier spike (refunds back to normal after a one-off week) is a return to normal: say that rather than calling it a gain.
- Use the Context input when it explains a period. Otherwise do not invent outside causes such as a campaign, a holiday or a bug: say what the data shows, that it does not say why, and the one thing worth checking first.
- Quantify every claim with the latest value, the change in percent, and the comparison it is against.
- Sanity check before writing: changes have the sign you describe, rates are between 0 and 100%, and the period count matches the file. Note any missing values or gaps the summary reports.

### 4. Write the update

Write /workspace/out/update.md in this shape, short enough to read in a minute:

```markdown
# KPI update: week of 09/11/2026

**Signups fell 26% this week while traffic held steady, taking orders and revenue down with them.**

| Metric | This week | vs last week | vs 4-week average |
|---|---|---|---|
| Visitors | 21,049 | -1.1% | +2.9% |

## What moved
- **Signups: 467, down 26.5% on last week** and 25.7% under the 4-week average. Visitors were flat (-1.1%), so the signup rate fell from 3.0% to 2.2%: the drop is in conversion, not traffic. Check the signup page first.

## Worth watching
- One or two lines on earlier spikes or slow trends worth a look.

## About the data
12 weeks, 24/08/2026 to 09/11/2026. Anything partial, missing or assumed.

![Metrics over the last 12 weeks](chart.png)
```

- The headline is one sentence naming the biggest move and its size.
- The table has every metric, with numbers formatted for reading (thousands separators, rates as percentages, money with its currency).
- "What moved" has one bullet per moved metric, biggest business impact first. Group metrics that moved for one reason into one bullet.
- If nothing moved, say "A steady week" in the headline and keep "What moved" to one line.
- Dates are written dd/mm/yyyy.

### 5. Answer

Reply with the headline and the "What moved" bullets.

Then add `## Assumptions`: the metrics you left out, the rates you added, what you treated as lower is better, and any partial period you dropped.

## Output

- **update.md**: the KPI update.
- **chart.png**: one small chart per metric, the latest point marked (red when it moved the wrong way, green the right way).
- **workbook.xlsx**: the data (inputs in blue) and a Summary sheet of live formulas for the latest period, previous period, change and 4-period average.

## Adapting this

- Name your KPIs and their direction once in step 1 (or in a file under /workspace/knowledge/) so every run reads them the same way.
- Change the 15% threshold with `--threshold 0.1` if your metrics are steadier, or add targets to the Context input to compare against plan.
- To post the update, add a connection (Slack, email) in the frontmatter and a final step that sends update.md with the chart.
