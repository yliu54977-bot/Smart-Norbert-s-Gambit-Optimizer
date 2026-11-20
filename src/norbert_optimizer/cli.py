"""Command-line entry point.

Examples
--------
python -m norbert_optimizer --amount 10000 --start 2023-01-01 --end 2025-12-31
python -m norbert_optimizer --amount 10000 --csv data/sample_synthetic.csv
"""

from __future__ import annotations

import argparse
import json

from .data import load_csv, load_yfinance
from .models import Assumptions, simulate
from .plots import save_charts
from .stats import break_even_amount, format_summary, summarize


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Bank vs Norbert's Gambit for CAD -> USD.")
    p.add_argument("--amount", type=float, required=True, help="CAD to convert")
    p.add_argument("--csv", help="Aligned CSV (date, cad_price, usd_price, cadusd)")
    p.add_argument("--start", help="Start date for yfinance, YYYY-MM-DD")
    p.add_argument("--end", help="End date for yfinance, YYYY-MM-DD")
    p.add_argument("--cad-ticker", default="DLR.TO")
    p.add_argument("--usd-ticker", default="DLR-U.TO")
    p.add_argument(
        "--derive-usd",
        action="store_true",
        help="Use CAD price x CADUSD as the USD listing's price (automatic if it has no data)",
    )
    p.add_argument("--spread", type=float, default=0.02, help="Bank spread, 0.02 = 2%%")
    p.add_argument("--commission-cad", type=float, default=9.95)
    p.add_argument("--commission-usd", type=float, default=9.95)
    p.add_argument("--delay", type=int, default=4, help="Trading days to journal shares")
    p.add_argument("--charts", default="output", help="Folder for charts")
    p.add_argument("--json", action="store_true", help="Print the summary as JSON")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.csv:
        df = load_csv(args.csv)
    else:
        if not (args.start and args.end):
            raise SystemExit("Give --start and --end for yfinance, or use --csv.")
        df, derived = load_yfinance(
            args.cad_ticker, args.usd_ticker, args.start, args.end, derive_usd=args.derive_usd
        )
        if derived:
            print(
                f"Note: not enough history for {args.usd_ticker}; using "
                f"{args.cad_ticker} price x CADUSD as its USD price."
            )

    a = Assumptions(args.spread, args.commission_cad, args.commission_usd, args.delay)
    result = simulate(df, args.amount, a)
    summary = summarize(result, args.amount)
    summary["break_even_cad"] = break_even_amount(df, simulate, a)

    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(format_summary(summary))
        be = summary["break_even_cad"]
        print(f"Break-even amount: {be:,.2f} CAD" if be else "Break-even amount: not reached")

    for path in save_charts(result, args.charts):
        print(f"Saved {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
