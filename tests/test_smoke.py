"""Smoke tests for RAISEDECK: parse the demo, compute, render, gate."""

import json
import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from raisedeck import TOOL_NAME, TOOL_VERSION  # noqa: E402
from raisedeck.core import (  # noqa: E402
    RaiseDeckError,
    compute_update,
    load_metrics,
    parse_yaml,
    render_json,
    render_table,
)

DEMO = os.path.join(ROOT, "demos", "01-basic", "metrics.yaml")


def _read_demo():
    with open(DEMO, "r", encoding="utf-8") as fh:
        return fh.read()


def test_metadata():
    assert TOOL_NAME == "raisedeck"
    assert TOOL_VERSION.count(".") == 2


def test_yaml_parses_nested_structures():
    doc = parse_yaml(_read_demo())
    assert doc["company"] == "Acme Analytics Inc"
    assert doc["currency"] == "USD"
    assert doc["cash"] == 410000
    assert isinstance(doc["months"], list) and len(doc["months"]) == 3
    feb = doc["months"][-1]
    assert feb["month"] == "2026-02"
    assert feb["mrr"] == 47500
    assert "SOC 2 Type II completed" in feb["highlights"]


def test_compute_latest_month():
    doc, months = load_metrics(_read_demo())
    u = compute_update(doc, months)  # latest = 2026-02
    assert u.period == "2026-02"
    assert u.mrr == 47500
    assert u.arr == 47500 * 12
    assert u.prev_mrr == 42000
    assert u.net_new_mrr == 5500
    assert u.mrr_growth_pct == pytest.approx(5500 / 42000 * 100, rel=1e-6)
    assert u.net_burn == pytest.approx(98000 - 47500)
    assert u.runway_months == pytest.approx(410000 / (98000 - 47500), rel=1e-6)
    assert u.cash_zero_date is not None and u.cash_zero_date.startswith("2026-")
    assert u.alerts == []


def test_period_selection_and_first_month_has_no_growth():
    doc, months = load_metrics(_read_demo())
    first = compute_update(doc, months, period="2025-12")
    assert first.period == "2025-12"
    assert first.prev_mrr == 0
    assert first.mrr_growth_pct is None  # no prior month

    jan = compute_update(doc, months, period="2026-01")
    assert jan.net_new_mrr == 42000 - 38000


def test_unknown_period_raises():
    doc, months = load_metrics(_read_demo())
    with pytest.raises(RaiseDeckError):
        compute_update(doc, months, period="1999-01")


def test_alerts_fire_on_low_runway_and_contraction():
    text = """
company: Bleeder Co
currency: USD
cash: 60000
months:
  - month: 2026-01
    mrr: 30000
    customers: 50
    expenses: 50000
    churned_customers: 1
  - month: 2026-02
    mrr: 25000
    customers: 40
    expenses: 60000
    churned_customers: 8
"""
    doc, months = load_metrics(text)
    u = compute_update(doc, months)
    # net burn = 60000 - 25000 = 35000 ; runway = 60000/35000 ~ 1.7 mo
    assert u.runway_months is not None and u.runway_months < 6
    assert u.net_new_mrr < 0
    # churn 8 of prior 50 customers = 16% > 5%
    assert u.logo_churn_pct == pytest.approx(8 / 50 * 100)
    kinds = " ".join(u.alerts)
    assert "LOW RUNWAY" in kinds
    assert "CONTRACTION" in kinds
    assert "CHURN" in kinds


def test_profitable_company_has_no_runway():
    text = """
company: Profit Co
cash: 100000
months:
  - month: 2026-01
    mrr: 80000
    customers: 100
    expenses: 60000
"""
    doc, months = load_metrics(text)
    u = compute_update(doc, months)
    assert u.net_burn < 0
    assert u.runway_months is None
    assert u.cash_zero_date is None
    assert u.arpa == pytest.approx(800.0)


def test_render_table_and_json():
    doc, months = load_metrics(_read_demo())
    u = compute_update(doc, months)
    table = render_table(u)
    assert "Acme Analytics Inc" in table
    assert "Runway" in table
    assert "SOC 2 Type II completed" in table
    parsed = json.loads(render_json(u))
    assert parsed["period"] == "2026-02"
    assert parsed["mrr"] == 47500


def test_bad_input_raises():
    with pytest.raises(RaiseDeckError):
        load_metrics("company: x\ncurrency: USD\n")  # no months
    with pytest.raises(RaiseDeckError):
        parse_yaml("")  # empty


def test_cli_exit_codes(tmp_path):
    env = dict(os.environ)
    env["PYTHONPATH"] = ROOT + os.pathsep + env.get("PYTHONPATH", "")

    # healthy demo -> exit 0 ; --format after subcommand
    r = subprocess.run(
        [sys.executable, "-m", "raisedeck", "render", DEMO, "--format", "json"],
        capture_output=True, text=True, env=env,
    )
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["company"] == "Acme Analytics Inc"

    # --format before subcommand also works
    r_pre = subprocess.run(
        [sys.executable, "-m", "raisedeck", "--format", "json", "render", DEMO],
        capture_output=True, text=True, env=env,
    )
    assert r_pre.returncode == 0, r_pre.stderr
    assert json.loads(r_pre.stdout)["mrr"] == 47500

    # alerting metrics -> exit 2
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "company: B\ncash: 10000\nmonths:\n"
        "  - month: 2026-01\n    mrr: 30000\n    customers: 10\n    expenses: 50000\n",
        encoding="utf-8",
    )
    r2 = subprocess.run(
        [sys.executable, "-m", "raisedeck", "render", str(bad)],
        capture_output=True, text=True, env=env,
    )
    assert r2.returncode == 2, (r2.stdout, r2.stderr)

    # missing file -> exit 1
    r3 = subprocess.run(
        [sys.executable, "-m", "raisedeck", "render", str(tmp_path / "nope.yaml")],
        capture_output=True, text=True, env=env,
    )
    assert r3.returncode == 1

    # version
    r4 = subprocess.run(
        [sys.executable, "-m", "raisedeck", "--version"],
        capture_output=True, text=True, env=env,
    )
    assert r4.returncode == 0
    assert TOOL_VERSION in r4.stdout
