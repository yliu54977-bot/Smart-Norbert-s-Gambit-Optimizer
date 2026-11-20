"""Command-line entry point.

Find the best way to convert, testing every security in the universe:
    norbert-optimizer rank --amount 10000 --start 2021-01-01 --end 2025-12-31

Look at one pair in detail:
    norbert-optimizer compare --amount 10000 --pair RY --start 2021-01-01 --end 2025-12-31

Both commands accept --data FILE (a universe CSV saved with --save-data)
instead of downloading.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .data import clean_pair, download_universe, load_csv, load_wide_csv, pair_frame
from .models import Assumptions, simulate
from .plots import save_charts, save_ranking_chart
from .rank import best_by_amount, build_frames, rank_pairs, recommend, sensitivity
from .stats import break_even_amount, format_summary, summarize
from .universe import UNIVERSE, Pair, find_pair

DEFAULT_AMOUNTS = [1_000, 2_500, 5_000, 10_000, 25_000, 50_000, 100_000]


def add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--amount", type=float, required=True, help="CAD to convert")
    p.add_argument("--data", help="Universe CSV (from --save-data) instead of downloading")
    p.add_argument("--start", help="Start date for downloading, YYYY-MM-DD")
    p.add_argument("--end", help="End date for downloading, YYYY-MM-DD")
    p.add_argument("--save-data", help="Save the downloaded prices to this CSV")
    p.add_argument("--spread", type=float, default=0.02, help="Bank FX spread, 0.02 = 2%%")
    p.add_argument("--commission", type=float, default=9.95, help="Flat fee per trade")
    p.add_argument("--per-share", type=float, default=0.0, help="Fee per share per trade")
    p.add_argument("--commission-min", type=float, default=0.0, help="Minimum fee per trade")
    p.add_argument("--commission-max", type=float, default=float("inf"), help="Maximum fee per trade")
    p.add_argument("--delay", type=int, default=4, help="Trading days to journal (0 = sell right away)")
    p.add_argument("--slippage-bps", type=float, default=5.0, help="Half bid-ask spread per trade, bps")
    p.add_argument("--max-gap", type=float, default=0.03, help="Drop days where listings disagree by more")
    p.add_argument("--out", default="output", help="Folder for charts and tables")
    p.add_argument("--json", action="store_true", help="Print results as JSON")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bank vs Norbert's Gambit for converting CAD to USD.")
    sub = parser.add_subparsers(dest="command", required=True)

    r = sub.add_parser("rank", help="Test every security and recommend the best method")
    add_common(r)
    r.add_argument("--top", type=int, default=15, help="Rows to print and chart")
    r.add_argument("--amounts", default=",".join(str(a) for a in DEFAULT_AMOUNTS),
                   help="Comma-separated amounts for the best-method-by-amount table")

    c = sub.add_parser("compare", help="Bank vs Norbert's Gambit with one security")
    add_common(c)
    c.add_argument("--pair", default="DLR.TO", help="Pair from the universe, e.g. DLR.TO, RY, TD.TO")
    c.add_argument("--cad-ticker", help="Custom CAD listing (with --usd-ticker)")
    c.add_argument("--usd-ticker", help="Custom USD listing")
    c.add_argument("--derive-usd", action="store_true", help="Use CAD price x CADUSD as the USD price")
    c.add_argument("--csv", help="Single-pair CSV (date, cad_price, usd_price, cadusd)")
    return parser


def assumptions_from(args) -> Assumptions:
    return Assumptions(
        bank_spread=args.spread,
        commission=args.commission,
        per_share=args.per_share,
        commission_min=args.commission_min,
        commission_max=args.commission_max,
        delay_days=args.delay,
        slippage_bps=args.slippage_bps,
    )


def get_wide(args, pairs: list[Pair]):
    if args.data:
        return load_wide_csv(args.data)
    if not (args.start and args.end):
        raise SystemExit("Give --start and --end to download prices, or --data FILE.")
    wide = download_universe(pairs, args.start, args.end)
    if args.save_data:
        wide.to_csv(args.save_data)
        print(f"Saved prices to {args.save_data}")
    return wide


def run_rank(args) -> int:
    a = assumptions_from(args)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    frames = build_frames(get_wide(args, UNIVERSE), UNIVERSE, args.max_gap)
    table = rank_pairs(frames, args.amount, a)
    rec = recommend(table)
    amounts = [float(x) for x in args.amounts.split(",") if x.strip()]
    by_amount = best_by_amount(frames, amounts, a)

    table.to_csv(out / "ranking.csv", index=False)
    by_amount.to_csv(out / "best_by_amount.csv", index=False)
    chart = save_ranking_chart(table, args.amount, out / "ranking.png", args.top) if not table.empty else None

    if args.json:
        print(json.dumps({"recommendation": rec, "ranking": table.head(args.top).to_dict("records"),
                          "best_by_amount": by_amount.to_dict("records")}, indent=2, default=str))
        return 0

    print(f"Tested {len(frames)} securities, converting {args.amount:,.0f} CAD "
          f"(bank spread {a.bank_spread:.2%}, fee {a.commission:.2f}/trade, {a.delay_days}-day journal)\n")
    cols = ["cad_ticker", "usd_ticker", "mean_savings_usd", "p5_savings_usd", "worst_savings_usd",
            "win_rate", "break_even_cad"]
    print(table[cols].head(args.top).to_string(index=False, float_format=lambda v: f"{v:,.2f}"))
    print(f"\nRecommended: {rec['method']}")
    if "mean_savings_usd" in rec:
        print(f"  average saving {rec['mean_savings_usd']:,.2f} USD, 5th percentile {rec['p5_savings_usd']:,.2f} USD, "
              f"beat the bank on {rec['win_rate']:.1%} of start dates")
    if "reason" in rec:
        print(f"  {rec['reason']}")
    if "highest_average" in rec:
        print(f"  Highest average (riskier): {rec['highest_average']}")
    print("\nBest method by amount:")
    print(by_amount.to_string(index=False, float_format=lambda v: f"{v:,.2f}"))
    print(f"\nSaved {out / 'ranking.csv'}, {out / 'best_by_amount.csv'}" + (f", {chart}" if chart else ""))
    return 0


def run_compare(args) -> int:
    a = assumptions_from(args)
    if args.csv:
        df, derived = load_csv(args.csv), False
    else:
        if args.cad_ticker and args.usd_ticker:
            pair = Pair(f"{args.cad_ticker}/{args.usd_ticker}", args.cad_ticker, args.usd_ticker,
                        derive_usd=args.derive_usd)
        else:
            pair = find_pair(args.pair)
        df, derived = pair_frame(get_wide(args, [pair]), pair)
        df, dropped = clean_pair(df, args.max_gap)
        if dropped:
            print(f"Note: skipped windows around {dropped} days where the two listings' prices disagreed.")
    if derived:
        print("Note: no price history for the USD listing; using CAD price x CADUSD as its price.")

    result = simulate(df, args.amount, a)
    summary = summarize(result, args.amount)
    summary["break_even_cad"] = break_even_amount(df, simulate, a)
    delays = sensitivity(df, args.amount, a, "delay_days", [0, 1, 2, 3, 4, 5])

    if args.json:
        print(json.dumps({**summary, "by_delay": delays.to_dict("records")}, indent=2))
    else:
        print(format_summary(summary))
        be = summary["break_even_cad"]
        print("Break-even amount: not reached" if be is None else
              "Break-even amount: 100 CAD or less" if be <= 100 else f"Break-even amount: {be:,.2f} CAD")
        print("\nBy journal delay (trading days):")
        print(delays.to_string(index=False, float_format=lambda v: f"{v:,.2f}"))
    for path in save_charts(result, args.out):
        print(f"Saved {path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return run_rank(args) if args.command == "rank" else run_compare(args)


if __name__ == "__main__":
    raise SystemExit(main())
