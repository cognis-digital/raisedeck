"""RAISEDECK core engine.

Parses a small metrics YAML (no PyYAML — a focused stdlib parser), computes
investor-update KPIs (MRR, growth, net new MRR, burn, runway, cash zero date),
and renders a monthly update as a table or JSON.

The YAML schema is intentionally small and flat per-month, for example:

    company: Acme Inc
    currency: USD
    cash: 480000
    months:
      - month: 2026-01
        mrr: 42000
        customers: 120
        expenses: 95000
        new_customers: 14
        churned_customers: 3
        highlights:
          - Closed Globex pilot
      - month: 2026-02
        mrr: 47500
        customers: 131
        expenses: 98000

Only the subset of YAML needed for this schema is supported: mappings,
sequences of scalars, and sequences of mappings (one level of nesting).
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import date
from typing import Any


class RaiseDeckError(Exception):
    """Raised on malformed input or impossible computations."""


# --------------------------------------------------------------------------
# Minimal YAML parser (sufficient for the RAISEDECK schema)
# --------------------------------------------------------------------------

def _strip_comment(line: str) -> str:
    out = []
    in_single = in_double = False
    for ch in line:
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "#" and not in_single and not in_double:
            break
        out.append(ch)
    return "".join(out)


def _coerce_scalar(token: str) -> Any:
    t = token.strip()
    if t == "" or t in ("~", "null", "Null", "NULL"):
        return None
    if (len(t) >= 2) and ((t[0] == t[-1] == '"') or (t[0] == t[-1] == "'")):
        return t[1:-1]
    low = t.lower()
    if low in ("true", "yes"):
        return True
    if low in ("false", "no"):
        return False
    try:
        return int(t)
    except ValueError:
        pass
    try:
        return float(t)
    except ValueError:
        pass
    return t


@dataclass
class _Line:
    indent: int
    raw: str


def _tokenize(text: str) -> list[_Line]:
    lines: list[_Line] = []
    for raw in text.splitlines():
        if "\t" in (raw[: len(raw) - len(raw.lstrip())]):
            raise RaiseDeckError("Tabs are not allowed for indentation; use spaces.")
        body = _strip_comment(raw)
        if body.strip() == "":
            continue
        indent = len(body) - len(body.lstrip(" "))
        lines.append(_Line(indent=indent, raw=body.rstrip()))
    return lines


def _parse_block(lines: list[_Line], pos: int, indent: int) -> tuple[Any, int]:
    if pos >= len(lines):
        return None, pos

    first = lines[pos]
    is_seq = first.raw.lstrip().startswith("- ") or first.raw.strip() == "-"

    if is_seq:
        result_list: list[Any] = []
        while pos < len(lines) and lines[pos].indent == indent and (
            lines[pos].raw.lstrip().startswith("- ") or lines[pos].raw.strip() == "-"
        ):
            item_text = lines[pos].raw.lstrip()[1:].strip()
            if item_text == "":
                # nested block belonging to this list item
                nxt = _next_indent(lines, pos + 1, indent)
                if nxt is None or nxt <= indent:
                    result_list.append(None)
                    pos += 1
                else:
                    child, pos = _parse_block(lines, pos + 1, nxt)
                    result_list.append(child)
            elif ":" in item_text:
                # inline mapping start on the dash line: "- key: value [...]"
                child_indent = indent + 2
                synthetic = [_Line(indent=child_indent, raw=(" " * child_indent) + item_text)]
                # gather continuation lines indented deeper than the dash
                scan = pos + 1
                while scan < len(lines) and lines[scan].indent > indent:
                    synthetic.append(lines[scan])
                    scan += 1
                child, _ = _parse_block(synthetic, 0, child_indent)
                result_list.append(child)
                pos = scan
            else:
                result_list.append(_coerce_scalar(item_text))
                pos += 1
        return result_list, pos

    # mapping
    result_map: dict[str, Any] = {}
    while pos < len(lines) and lines[pos].indent == indent:
        line = lines[pos]
        stripped = line.raw.strip()
        if stripped.startswith("- "):
            break
        if ":" not in stripped:
            raise RaiseDeckError(f"Expected 'key: value' mapping line, got: {stripped!r}")
        key, _, rest = stripped.partition(":")
        key = key.strip()
        rest = rest.strip()
        if rest == "":
            child_indent = _next_indent(lines, pos + 1, indent)
            if child_indent is None or child_indent <= indent:
                result_map[key] = None
                pos += 1
            else:
                child, pos = _parse_block(lines, pos + 1, child_indent)
                result_map[key] = child
        else:
            result_map[key] = _coerce_scalar(rest)
            pos += 1
    return result_map, pos


def _next_indent(lines: list[_Line], pos: int, parent_indent: int) -> int | None:
    if pos >= len(lines):
        return None
    return lines[pos].indent


def parse_yaml(text: str) -> dict[str, Any]:
    """Parse the RAISEDECK YAML subset into a dict. Raises RaiseDeckError."""
    lines = _tokenize(text)
    if not lines:
        raise RaiseDeckError("Empty metrics document.")
    base_indent = lines[0].indent
    value, pos = _parse_block(lines, 0, base_indent)
    if pos != len(lines):
        raise RaiseDeckError(
            f"Could not fully parse document (stopped at line {pos + 1}: {lines[pos].raw!r})"
        )
    if not isinstance(value, dict):
        raise RaiseDeckError("Top-level document must be a mapping.")
    return value


# --------------------------------------------------------------------------
# Domain model
# --------------------------------------------------------------------------

@dataclass
class MonthMetrics:
    month: str
    mrr: float
    customers: int = 0
    expenses: float = 0.0
    new_customers: int = 0
    churned_customers: int = 0
    highlights: list[str] = field(default_factory=list)


@dataclass
class InvestorUpdate:
    company: str
    currency: str
    period: str
    cash: float
    mrr: float
    arr: float
    prev_mrr: float
    net_new_mrr: float
    mrr_growth_pct: float | None
    customers: int
    new_customers: int
    churned_customers: int
    logo_churn_pct: float | None
    arpa: float | None
    expenses: float
    net_burn: float
    runway_months: float | None
    cash_zero_date: str | None
    highlights: list[str]
    alerts: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# --------------------------------------------------------------------------
# Computation
# --------------------------------------------------------------------------

def _num(value: Any, name: str, default: float | None = 0.0) -> float:
    if value is None:
        if default is None:
            raise RaiseDeckError(f"Missing required numeric field: {name}")
        return float(default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RaiseDeckError(f"Field {name!r} must be a number, got {value!r}")
    return float(value)


def _build_month(raw: dict[str, Any]) -> MonthMetrics:
    if not isinstance(raw, dict):
        raise RaiseDeckError(f"Each month must be a mapping, got {raw!r}")
    if "month" not in raw or raw["month"] is None:
        raise RaiseDeckError("Each month entry needs a 'month' field (e.g. 2026-01).")
    highlights = raw.get("highlights") or []
    if isinstance(highlights, str):
        highlights = [highlights]
    return MonthMetrics(
        month=str(raw["month"]),
        mrr=_num(raw.get("mrr"), "mrr", default=None),
        customers=int(_num(raw.get("customers"), "customers")),
        expenses=_num(raw.get("expenses"), "expenses"),
        new_customers=int(_num(raw.get("new_customers"), "new_customers")),
        churned_customers=int(_num(raw.get("churned_customers"), "churned_customers")),
        highlights=[str(h) for h in highlights],
    )


def load_metrics(text: str) -> tuple[dict[str, Any], list[MonthMetrics]]:
    """Parse YAML text and return (top-level dict, ordered MonthMetrics list)."""
    doc = parse_yaml(text)
    raw_months = doc.get("months")
    if not raw_months or not isinstance(raw_months, list):
        raise RaiseDeckError("Document must contain a non-empty 'months' sequence.")
    months = [_build_month(m) for m in raw_months]
    return doc, months


def _add_months(d: date, n: int) -> date:
    month_index = (d.year * 12 + (d.month - 1)) + n
    year, month = divmod(month_index, 12)
    return date(year, month + 1, 1)


def compute_update(
    doc: dict[str, Any], months: list[MonthMetrics], period: str | None = None
) -> InvestorUpdate:
    """Compute the investor update for `period` (default: latest month)."""
    if not months:
        raise RaiseDeckError("No months to report on.")

    if period is None:
        target = months[-1]
        idx = len(months) - 1
    else:
        idx = next((i for i, m in enumerate(months) if m.month == period), -1)
        if idx < 0:
            raise RaiseDeckError(
                f"Period {period!r} not found. Available: {', '.join(m.month for m in months)}"
            )
        target = months[idx]

    prev = months[idx - 1] if idx > 0 else None
    prev_mrr = prev.mrr if prev else 0.0

    net_new_mrr = target.mrr - prev_mrr
    mrr_growth_pct = (net_new_mrr / prev_mrr * 100.0) if prev and prev_mrr > 0 else None
    arr = target.mrr * 12.0
    arpa = (target.mrr / target.customers) if target.customers > 0 else None

    prev_customers = prev.customers if prev else 0
    logo_churn_pct = (
        (target.churned_customers / prev_customers * 100.0)
        if prev and prev_customers > 0
        else None
    )

    net_burn = target.expenses - target.mrr
    cash = _num(doc.get("cash"), "cash")

    if net_burn > 0:
        runway_months = cash / net_burn
    else:
        runway_months = None  # profitable / break-even

    cash_zero_date = None
    if runway_months is not None:
        try:
            y, m = (int(x) for x in str(target.month).split("-")[:2])
            anchor = date(y, m, 1)
            cash_zero_date = _add_months(anchor, int(runway_months)).isoformat()[:7]
        except (ValueError, TypeError):
            cash_zero_date = None

    alerts: list[str] = []
    if runway_months is not None and runway_months < 6:
        alerts.append(f"LOW RUNWAY: {runway_months:.1f} months of cash remaining (<6).")
    if net_new_mrr < 0:
        alerts.append(f"MRR CONTRACTION: net new MRR is {net_new_mrr:,.0f}.")
    if logo_churn_pct is not None and logo_churn_pct > 5:
        alerts.append(f"HIGH LOGO CHURN: {logo_churn_pct:.1f}% (>5%).")

    return InvestorUpdate(
        company=str(doc.get("company") or "Untitled Co"),
        currency=str(doc.get("currency") or "USD"),
        period=target.month,
        cash=cash,
        mrr=target.mrr,
        arr=arr,
        prev_mrr=prev_mrr,
        net_new_mrr=net_new_mrr,
        mrr_growth_pct=mrr_growth_pct,
        customers=target.customers,
        new_customers=target.new_customers,
        churned_customers=target.churned_customers,
        logo_churn_pct=logo_churn_pct,
        arpa=arpa,
        expenses=target.expenses,
        net_burn=net_burn,
        runway_months=runway_months,
        cash_zero_date=cash_zero_date,
        highlights=target.highlights,
        alerts=alerts,
    )


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------

def _money(value: float, currency: str) -> str:
    sym = {"USD": "$", "EUR": "EUR ", "GBP": "GBP "}.get(currency, "")
    return f"{sym}{value:,.0f}"


def _pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:+.1f}%"


def render_table(update: InvestorUpdate) -> str:
    cur = update.currency
    rows = [
        ("MRR", _money(update.mrr, cur)),
        ("ARR", _money(update.arr, cur)),
        ("Net New MRR", _money(update.net_new_mrr, cur)),
        ("MRR Growth", _pct(update.mrr_growth_pct)),
        ("Customers", f"{update.customers:,} (+{update.new_customers}/-{update.churned_customers})"),
        ("Logo Churn", _pct(update.logo_churn_pct)),
        ("ARPA", _money(update.arpa, cur) if update.arpa is not None else "n/a"),
        ("Expenses", _money(update.expenses, cur)),
        ("Net Burn", _money(update.net_burn, cur)),
        ("Cash", _money(update.cash, cur)),
        (
            "Runway",
            f"{update.runway_months:.1f} mo" if update.runway_months is not None else "profitable",
        ),
        ("Cash-out", update.cash_zero_date or "n/a"),
    ]
    label_w = max(len(r[0]) for r in rows)
    val_w = max(len(r[1]) for r in rows)

    title = f" {update.company} - Investor Update {update.period} "
    width = max(len(title), label_w + val_w + 5)
    lines = []
    lines.append("=" * width)
    lines.append(title.center(width))
    lines.append("=" * width)
    for label, val in rows:
        lines.append(f"  {label.ljust(label_w)} : {val}")
    if update.highlights:
        lines.append("-" * width)
        lines.append("  Highlights:")
        for h in update.highlights:
            lines.append(f"    - {h}")
    if update.alerts:
        lines.append("-" * width)
        lines.append("  ALERTS:")
        for a in update.alerts:
            lines.append(f"    ! {a}")
    lines.append("=" * width)
    return "\n".join(lines)


def render_json(update: InvestorUpdate) -> str:
    import json

    return json.dumps(update.to_dict(), indent=2, sort_keys=True)
