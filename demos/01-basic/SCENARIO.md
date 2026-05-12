# Demo 01 — Basic investor update

## What this shows

A three-month metrics history for a small SaaS company (`metrics.yaml`).
RAISEDECK reads it and renders the **latest month's** investor update:
MRR, ARR, net new MRR, MRR growth %, customer counts, logo churn, ARPA,
expenses, net burn, cash, runway, and projected cash-out month.

## Run it

```bash
# Human-readable table (default)
python -m raisedeck render demos/01-basic/metrics.yaml

# Machine-readable JSON for piping / CI
python -m raisedeck render demos/01-basic/metrics.yaml --format json

# A specific historical month
python -m raisedeck render demos/01-basic/metrics.yaml --period 2026-01
```

## Expected result (latest month: 2026-02)

The demo data is intentionally healthy, so **no alerts fire** and the
process exits `0`:

- MRR = **$47,500**, ARR = **$570,000**
- Net New MRR = **$5,500** (vs. Jan's $42,000) -> growth **+13.1%**
- Customers = **131** (+15 / -4)
- Net Burn = expenses - MRR = 98,000 - 47,500 = **$50,500/mo**
- Runway = cash / net burn = 410,000 / 50,500 ~= **8.1 months**
- Cash-out ~= **2026-10**

## CI gate behavior

The tool exits **2** when any alert fires (runway < 6 months,
net new MRR negative, or logo churn > 5%). That makes it usable as a
metrics gate:

```bash
python -m raisedeck render metrics.yaml --format json || echo "investor alerts!"
```
