"""Command-line entry point.

Find the cheapest way to convert at your broker:
    norbert-optimizer rank --amount 10000 --broker questrade --data prices.csv

Compare brokers:
    norbert-optimizer brokers --amount 10000 --data prices.csv
    norbert-optimizer brokers --list

Look at one pair in detail:
    norbert-optimizer compare --amount 10000 --pair RY --data prices.csv

Download prices once with --start/--end and --save-data, then reuse them with --data.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
from pathlib import Path

import pandas as pd

from .brokers import BROKERS, VERIFIED_ON, Broker, FxTier, get_broker
from .data import clean_pair, download_universe, load_csv, load_wide_csv, pair_frame, with_tsx_close_fx
from .models import Assumptions, simulate
from .plots import save_broker_chart, save_charts, save_ranking_chart
from .rank import (best_by_amount, broker_assumptions, build_frames, compare_brokers, mean_fx, rank_pairs,
                   recommend, sensitivity)
from .stats import break_even_amount, format_summary, summarize
from .ticket import append_log, live_quotes, make_ticket
from .universe import UNIVERSE, Pair, find_pair

DEFAULT_AMOUNTS = [1_000, 2_500, 5_000, 10_000, 25_000, 50_000, 100_000]
DEFAULTS = dict(spread=0.02, commission=9.95, per_share=0.0, commission_min=0.0,
                commission_max=float("inf"), delay=4, journal_fee=0.0)


def money(v: float) -> str:
    return f"{v:,.2f}"


def add_data_args(p: argparse.ArgumentParser, amount_required: bool = True) -> None:
    p.add_argument("--amount", type=float, required=amount_required, help="CAD to convert")
    p.add_argument("--data", help="Universe CSV (from --save-data) instead of downloading")
    p.add_argument("--start", help="Start date for downloading, YYYY-MM-DD")
    p.add_argument("--end", help="End date for downloading, YYYY-MM-DD")
    p.add_argument("--save-data", help="Save the downloaded prices to this CSV")
    p.add_argument("--slippage-bps", type=float, default=5.0, help="Half bid-ask spread per trade, bps")
    p.add_argument("--max-gap", type=float, default=0.03, help="Flag days where listings disagree by more")
    p.add_argument("--fx-source", choices=["dlr", "yahoo"], default="dlr",
                   help="Exchange rate: 4 pm rate measured from DLR (default) or Yahoo's CADUSD=X close")
    p.add_argument("--out", default="output", help="Folder for charts and tables")
    p.add_argument("--json", action="store_true", help="Print results as JSON")


def add_cost_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--broker", help=f"Use a broker's fees and rules: {', '.join(BROKERS)}")
    p.add_argument("--spread", type=float, help="Direct FX spread, 0.02 = 2%% (default 2%%, or the broker's)")
    p.add_argument("--commission", type=float, help="Flat fee per trade (default 9.95, or the broker's)")
    p.add_argument("--per-share", type=float, help="Fee per share per trade")
    p.add_argument("--commission-min", type=float, help="Minimum fee per trade")
    p.add_argument("--commission-max", type=float, help="Maximum fee per trade")
    p.add_argument("--journal-fee", type=float, help="Fee to journal the shares, CAD (default 0, or the broker's)")
    p.add_argument("--delay", type=int, help="Trading days from buy to sell (default 4, or the broker's)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Find the cheapest way to convert CAD to USD.")
    sub = parser.add_subparsers(dest="command", required=True)

    r = sub.add_parser("rank", help="Test every security and recommend the best method")
    add_data_args(r)
    add_cost_args(r)
    r.add_argument("--top", type=int, default=15, help="Rows to print and chart")
    r.add_argument("--amounts", default=",".join(str(a) for a in DEFAULT_AMOUNTS),
                   help="Comma-separated amounts for the best-method-by-amount table")

    b = sub.add_parser("brokers", help="Compare brokers: cheapest safe method and its cost at each")
    add_data_args(b, amount_required=False)
    b.add_argument("--list", action="store_true", help="Show each broker's fees, rules and sources, then exit")
    b.add_argument("--amounts", default=",".join(str(a) for a in DEFAULT_AMOUNTS),
                   help="Comma-separated amounts for the cost-by-amount table")

    t = sub.add_parser("ticket", help="Paper-test one Gambit step by step, or check a real one")
    add_data_args(t)
    add_cost_args(t)
    t.add_argument("--pair", default="DLR.TO", help="Security to use, e.g. DLR.TO or RY")
    src = t.add_mutually_exclusive_group(required=True)
    src.add_argument("--date", help="Use closing prices from this start date (needs --data or --start/--end)")
    src.add_argument("--live", action="store_true", help="Use live quotes from yfinance (market hours)")
    src.add_argument("--cad-price", type=float, help="Price you buy the CAD listing at (the ask)")
    t.add_argument("--usd-price", type=float, help="Price you sell the USD listing at (the bid)")
    t.add_argument("--fx", type=float, help="Mid-market USD per CAD when you start")
    t.add_argument("--actual-usd", type=float, help="USD you really received, to compare with the ticket")
    t.add_argument("--log", help="Append the ticket to this CSV")
    t.add_argument("--label", default="", help="Note stored with the logged ticket")

    c = sub.add_parser("compare", help="Direct conversion vs Norbert's Gambit with one security")
    add_data_args(c)
    add_cost_args(c)
    c.add_argument("--pair", default="DLR.TO", help="Pair from the universe, e.g. DLR.TO, RY, TD.TO")
    c.add_argument("--cad-ticker", help="Custom CAD listing (with --usd-ticker)")
    c.add_argument("--usd-ticker", help="Custom USD listing")
    c.add_argument("--derive-usd", action="store_true", help="Use CAD price x CADUSD as the USD price")
    c.add_argument("--csv", help="Single-pair CSV (date, cad_price, usd_price, cadusd)")
    return parser


def effective_broker(args) -> Broker | None:
    """The chosen broker with any numbers the user overrode on the command line."""
    if not args.broker:
        return None
    b = get_broker(args.broker)
    changes = {}
    for name in ("commission", "per_share", "commission_min", "commission_max", "journal_fee"):
        if getattr(args, name) is not None:
            changes[name] = getattr(args, name)
    if args.spread is not None:
        changes.update(fx_tiers=(FxTier(float("inf"), args.spread),), fx_min_fee_usd=0.0, fx_tiers_complete=True)
    if args.delay is not None:
        changes.update(dlr_delay=args.delay, stock_delay=args.delay)
    return dataclasses.replace(b, **changes)


def plain_assumptions(args) -> Assumptions:
    def pick(name):
        v = getattr(args, name)
        return DEFAULTS[name] if v is None else v

    return Assumptions(
        bank_spread=pick("spread"),
        commission=pick("commission"),
        per_share=pick("per_share"),
        commission_min=pick("commission_min"),
        commission_max=pick("commission_max"),
        delay_days=pick("delay"),
        slippage_bps=args.slippage_bps,
        journal_fee=pick("journal_fee"),
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


def describe_broker(b: Broker) -> str:
    tiers = ", ".join(
        (f"{t.spread:.2%} under {t.up_to:,.0f} {b.fx_tier_currency}" if t.up_to != float("inf")
         else f"{t.spread:.3%} above") for t in b.fx_tiers)
    gambit = {"all": "DLR and interlisted stocks", "dlr_only": "DLR only",
              "not_needed": "not needed (direct conversion is near the interbank rate)"}[b.gambit]
    fee = f"{b.commission:.2f}/trade" + (f" + {b.per_share}/share (min {b.commission_min})" if b.per_share else "")
    lines = [
        f"{b.name}  [--broker {b.key}]  sources: {b.source_quality}",
        f"  Trade commission: {fee}",
        f"  Direct FX: {tiers}" + ("" if b.fx_tiers_complete else " (only the first tier is known)")
        + (f", minimum US${b.fx_min_fee_usd:.2f}" if b.fx_min_fee_usd else ""),
        f"  Norbert's Gambit: {gambit}; journal fee {b.journal_fee:.2f} CAD; "
        f"wait {b.dlr_delay} trading days with DLR, {b.stock_delay} with stocks",
        f"  How: {b.how}",
    ]
    lines += [f"  Note: {n}" for n in b.notes]
    if b.extra_monthly_cost:
        lines.append(f"  Extra cost: {b.extra_monthly_cost}")
    lines += [f"  Source: {s}" for s in b.sources]
    return "\n".join(lines)


def run_rank(args) -> int:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    frames = build_frames(get_wide(args, UNIVERSE), UNIVERSE, args.max_gap, args.fx_source)
    broker = effective_broker(args)
    if broker:
        a = broker_assumptions(broker, args.amount, mean_fx(frames), Assumptions(slippage_bps=args.slippage_bps))
    else:
        a = plain_assumptions(args)
    if broker and broker.gambit == "not_needed":
        print(f"{broker.name}: {broker.how}")
        return 0
    table = rank_pairs(frames, args.amount, a, broker=broker)
    rec = recommend(table)
    amounts = [float(x) for x in args.amounts.split(",") if x.strip()]
    by_amount = best_by_amount(frames, amounts, a, broker=broker)

    table.to_csv(out / "ranking.csv", index=False)
    by_amount.to_csv(out / "best_by_amount.csv", index=False)
    chart = save_ranking_chart(table, args.amount, out / "ranking.png", args.top) if not table.empty else None

    if args.json:
        print(json.dumps({"recommendation": rec, "ranking": table.head(args.top).to_dict("records"),
                          "best_by_amount": by_amount.to_dict("records")}, indent=2, default=str))
        return 0

    against = f"{broker.name}'s direct conversion" if broker else "the bank"
    print(f"Tested {len(table)} securities, converting {args.amount:,.0f} CAD; savings are vs {against} "
          f"({a.bank_spread:.2%} spread), fee {a.commission:.2f}/trade, journal fee {a.journal_fee:.2f}\n")
    cols = ["cad_ticker", "usd_ticker", "delay_days", "mean_savings_usd", "p5_savings_usd",
            "worst_savings_usd", "win_rate", "break_even_cad"]
    print(table[cols].head(args.top).to_string(index=False, float_format=money))
    print(f"\nRecommended: {rec['method']}".replace("Bank", "Convert directly" if broker else "Bank"))
    if "mean_savings_usd" in rec:
        print(f"  average saving {money(rec['mean_savings_usd'])} USD, 5th percentile "
              f"{money(rec['p5_savings_usd'])} USD, beat {against} on {rec['win_rate']:.1%} of start dates")
    if "reason" in rec:
        print(f"  {rec['reason']}")
    if "highest_average" in rec:
        print(f"  Highest average (riskier): {rec['highest_average']}")
    if broker and not broker.fx_tiers_complete and args.amount >= 25_000:
        print(f"  Note: only {broker.name}'s first FX tier is known; its real spread at this amount is lower.")
    print("\nBest method by amount:")
    print(by_amount.to_string(index=False, float_format=money))
    print(f"\nSaved {out / 'ranking.csv'}, {out / 'best_by_amount.csv'}" + (f", {chart}" if chart else ""))
    return 0


def run_brokers(args) -> int:
    if args.list:
        print(f"Broker fees and rules, checked {VERIFIED_ON}. Confirm with your broker before converting.\n")
        print("\n\n".join(describe_broker(b) for b in BROKERS.values()))
        return 0
    if args.amount is None:
        raise SystemExit("Give --amount, or --list to see the brokers.")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    frames = build_frames(get_wide(args, UNIVERSE), UNIVERSE, args.max_gap, args.fx_source)
    base = Assumptions(slippage_bps=args.slippage_bps)
    brokers = list(BROKERS.values())
    table = compare_brokers(frames, brokers, args.amount, base)
    amounts = [float(x) for x in args.amounts.split(",") if x.strip()]
    matrix = pd.DataFrame(
        {f"{amt:,.0f}": compare_brokers(frames, brokers, amt, base).set_index("broker")["mean_cost_usd"]
         for amt in amounts}
    ).loc[table["broker"]]

    table.to_csv(out / "brokers.csv", index=False)
    matrix.to_csv(out / "brokers_by_amount.csv")
    chart = save_broker_chart(table, args.amount, out / "brokers.png")

    if args.json:
        print(json.dumps({"brokers": table.to_dict("records"),
                          "mean_cost_by_amount": matrix.to_dict()}, indent=2, default=str))
        return 0
    print(f"Converting {args.amount:,.0f} CAD to USD. Cost = USD lost vs the mid-market rate "
          f"(lower is better). Fees checked {VERIFIED_ON}.\n")
    cols = ["broker", "recommended", "mean_cost_usd", "p95_cost_usd", "direct_cost_usd", "gambit_pair"]
    print(table[cols].to_string(index=False, float_format=money))
    best = table.iloc[0]
    print(f"\nCheapest: {best['broker']} - {best['recommended']}, about {money(best['mean_cost_usd'])} USD "
          f"(at most {money(best['p95_cost_usd'])} USD in 95% of start dates).")
    if (~table["fx_tiers_complete"]).any() and args.amount >= 25_000:
        print("Note: some brokers publish only their first FX tier here, so their direct conversion "
              "cost is overstated at this amount (see brokers --list).")
    print("\nAverage cost (USD) of each broker's recommended method, by amount (CAD):")
    print(matrix.to_string(float_format=money))
    print(f"\nSaved {out / 'brokers.csv'}, {out / 'brokers_by_amount.csv'}, {chart}")
    print("Run `norbert-optimizer brokers --list` for each broker's rules and sources.")
    return 0


def run_compare(args) -> int:
    pair = None
    if args.csv:
        df, derived = load_csv(args.csv), False
    else:
        if args.cad_ticker and args.usd_ticker:
            pair = Pair(f"{args.cad_ticker}/{args.usd_ticker}", args.cad_ticker, args.usd_ticker,
                        derive_usd=args.derive_usd)
        else:
            pair = find_pair(args.pair)
        wide = get_wide(args, [pair] if pair.cad == "DLR.TO" else [find_pair("DLR.TO"), pair])
        if args.fx_source == "dlr":
            wide = with_tsx_close_fx(wide)
        df, derived = pair_frame(wide, pair)
        df, flagged = clean_pair(df, args.max_gap)
        if flagged:
            print(f"Note: skipped windows around {flagged} days where the two listings' prices disagreed.")
    if derived:
        print("Note: no price history for the USD listing; using CAD price x CADUSD as its price.")

    broker = effective_broker(args)
    if broker:
        cad = pair.cad if pair else "DLR.TO"
        if not broker.allows(cad):
            raise SystemExit(f"{broker.name} does not support Norbert's Gambit with {cad}: {broker.how}")
        a = broker_assumptions(broker, args.amount, float(df["cadusd"].mean()),
                               Assumptions(slippage_bps=args.slippage_bps))
        a = a.with_(delay_days=broker.delay_for(cad))
    else:
        a = plain_assumptions(args)

    result = simulate(df, args.amount, a)
    summary = summarize(result, args.amount)
    summary["break_even_cad"] = break_even_amount(df, simulate, a)
    delays = sensitivity(df, args.amount, a, "delay_days", [0, 1, 2, 3, 4, 5])

    if args.json:
        print(json.dumps({**summary, "by_delay": delays.to_dict("records")}, indent=2))
    else:
        if broker:
            print(f"Broker: {broker.name} (direct FX {a.bank_spread:.2%}, fee {a.commission:.2f}/trade, "
                  f"journal fee {a.journal_fee:.2f}, {a.delay_days}-day wait)")
        print(format_summary(summary))
        be = summary["break_even_cad"]
        print("Break-even amount: not reached" if be is None else
              "Break-even amount: 100 CAD or less" if be <= 100 else f"Break-even amount: {be:,.2f} CAD")
        print("\nBy waiting time (trading days):")
        print(delays.to_string(index=False, float_format=money))
    for path in save_charts(result, args.out):
        print(f"Saved {path}")
    return 0


def run_ticket(args) -> int:
    pair = find_pair(args.pair)
    broker = effective_broker(args)
    if broker and not broker.allows(pair.cad):
        raise SystemExit(f"{broker.name} does not support Norbert's Gambit with {pair.cad}: {broker.how}")
    divs = 0.0
    if args.date:
        frames = build_frames(get_wide(args, [find_pair("DLR.TO"), pair]), [pair], args.max_gap, args.fx_source)
        if pair.cad not in frames:
            raise SystemExit(f"No clean data for {pair.cad}.")
        df = frames[pair.cad]["df"]
        start = df.index[df.index >= args.date]
        if len(start) == 0:
            raise SystemExit(f"No trading day on or after {args.date} in the data.")
        i = df.index.get_loc(start[0])
        fx_mid = float(df["cadusd"].iloc[i])
        a = (broker_assumptions(broker, args.amount, fx_mid, Assumptions(slippage_bps=args.slippage_bps))
             if broker else plain_assumptions(args))
        d = broker.delay_for(pair.cad) if broker else a.delay_days
        if i + d >= len(df):
            raise SystemExit("Not enough data after that date for the wait.")
        slip = args.slippage_bps / 10_000
        cad_price = float(df["cad_price"].iloc[i]) * (1 + slip)
        usd_price = float(df["usd_price"].iloc[i + d]) * (1 - slip)
        divs = float(df["usd_dividend"].iloc[i + 1 : i + d + 1].sum())
        when = f"bought {df.index[i].date()}, sold {df.index[i + d].date()} ({d}-day wait), closes +/- {args.slippage_bps:g} bps"
    else:
        if args.live:
            q = live_quotes(pair.cad, pair.usd if not pair.derive_usd else "DLR-U.TO")
            cad_price, usd_price, fx_mid = q["cad_price"], q["usd_price"], q["fx_mid"]
            when = f"live quotes (ask size {q['ask_size']}, bid size {q['bid_size']})"
        else:
            if args.usd_price is None or args.fx is None:
                raise SystemExit("Give --cad-price, --usd-price and --fx together.")
            cad_price, usd_price, fx_mid = args.cad_price, args.usd_price, args.fx
            when = "prices given on the command line"
        a = (broker_assumptions(broker, args.amount, fx_mid, Assumptions(slippage_bps=args.slippage_bps))
             if broker else plain_assumptions(args))

    t = make_ticket(args.amount, cad_price, usd_price, fx_mid, a, divs, args.actual_usd)
    if args.json:
        print(json.dumps(t.__dict__, indent=2, default=str))
    else:
        who = broker.name if broker else "custom costs"
        print(f"Norbert's Gambit with {pair.cad} -> {pair.usd} at {who}; {when}\n")
        print("\n".join(t.lines()))
    if args.log:
        print(f"\nLogged to {append_log(args.log, t, args.label or (broker.key if broker else ''))}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    commands = {"rank": run_rank, "brokers": run_brokers, "compare": run_compare, "ticket": run_ticket}
    return commands[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
