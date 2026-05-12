"""RAISEDECK command-line interface.

Render a monthly investor update (MRR / burn / runway) from a metrics YAML.

Examples:
    raisedeck render demos/01-basic/metrics.yaml
    raisedeck render metrics.yaml --period 2026-02 --format json
    raisedeck render metrics.yaml --format json | jq .runway_months

Exit codes:
    0  update rendered, no alerts
    1  bad input / file error
    2  update rendered but ALERTS fired (low runway, MRR contraction, churn)
       — useful as a CI gate on your investor metrics.
"""

from __future__ import annotations

import argparse
import sys

from raisedeck import TOOL_NAME, TOOL_VERSION
from raisedeck.core import (
    RaiseDeckError,
    compute_update,
    load_metrics,
    render_json,
    render_table,
)


def _cmd_render(args: argparse.Namespace) -> int:
    try:
        with open(args.metrics, "r", encoding="utf-8") as fh:
            text = fh.read()
    except OSError as exc:
        print(f"raisedeck: cannot read {args.metrics!r}: {exc}", file=sys.stderr)
        return 1

    try:
        doc, months = load_metrics(text)
        update = compute_update(doc, months, period=args.period)
    except RaiseDeckError as exc:
        print(f"raisedeck: {exc}", file=sys.stderr)
        return 1

    if args.format == "json":
        print(render_json(update))
    else:
        print(render_table(update))

    return 2 if update.alerts else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=TOOL_NAME,
        description="Render monthly investor updates (MRR/burn/runway) from a metrics YAML.",
        epilog=(
            "examples:\n"
            "  raisedeck render demos/01-basic/metrics.yaml\n"
            "  raisedeck render metrics.yaml --period 2026-02 --format json\n"
            "  raisedeck render metrics.yaml --format json | jq .runway_months\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version", action="version", version=f"{TOOL_NAME} {TOOL_VERSION}"
    )

    # --format is accepted both globally (before the subcommand) and after it.
    # The subcommand copy defaults to None so a global value isn't clobbered.
    fmt = argparse.ArgumentParser(add_help=False)
    fmt.add_argument(
        "--format",
        dest="format_sub",
        choices=("table", "json"),
        default=None,
        help="output format (default: table)",
    )
    parser.add_argument(
        "--format",
        choices=("table", "json"),
        default="table",
        help="output format (default: table)",
    )

    sub = parser.add_subparsers(dest="command", metavar="<command>")

    render = sub.add_parser(
        "render",
        parents=[fmt],
        help="render an investor update from a metrics YAML file",
        description="Compute and render a monthly investor update.",
    )
    render.add_argument("metrics", help="path to the metrics YAML file")
    render.add_argument(
        "--period",
        default=None,
        help="month to report (e.g. 2026-02); defaults to the latest month",
    )
    render.set_defaults(func=_cmd_render)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 1
    # Resolve --format from either position (subcommand copy wins if given).
    sub_fmt = getattr(args, "format_sub", None)
    if sub_fmt is not None:
        args.format = sub_fmt
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
