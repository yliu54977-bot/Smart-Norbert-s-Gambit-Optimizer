"""Broker rules and fees for converting CAD to USD.

Each profile says what a broker charges and allows:

* how much a stock or ETF trade costs,
* what its own CAD -> USD conversion costs (the alternative to the Gambit),
* whether it supports Norbert's Gambit, with which securities, for what fee,
* how many trading days you wait between buying and selling.

Fees were checked on VERIFIED_ON against the sources listed with each broker.
`source_quality` is "official" when every number came from the broker's own
pages, otherwise "mixed" (some numbers from recent third-party fee
comparisons). Brokers change prices and rules: check yours before converting,
and override any number from the command line (--commission, --journal-fee,
--delay, --spread).
"""

from __future__ import annotations

from dataclasses import dataclass

VERIFIED_ON = "2026-11-20"


@dataclass(frozen=True)
class FxTier:
    up_to: float   # tier applies to amounts below this (in `fx_tier_currency`)
    spread: float  # 0.015 = 1.5%


@dataclass(frozen=True)
class Broker:
    key: str
    name: str
    commission: float                 # per stock/ETF trade (each side)
    per_share: float = 0.0
    commission_min: float = 0.0
    commission_max: float = float("inf")
    journal_fee: float = 0.0          # charged once per Gambit, in CAD
    fx_tiers: tuple[FxTier, ...] = ()  # broker's own conversion spread by size
    fx_tier_currency: str = "CAD"     # currency the tier thresholds are in
    fx_tiers_complete: bool = True    # False when only the first tier is published/known
    fx_min_fee_usd: float = 0.0       # fixed minimum per conversion (IBKR)
    gambit: str = "all"               # "all", "dlr_only", "not_needed"
    dlr_delay: int = 3                # trading days from buying DLR to selling DLR.U
    stock_delay: int = 3              # same for interlisted stocks
    how: str = ""                     # how the journal is requested
    notes: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()
    source_quality: str = "official"
    extra_monthly_cost: str = ""      # e.g. USD account subscription

    def fx_spread(self, cad_amount: float, cadusd: float) -> float:
        """Spread the broker charges to convert `cad_amount` directly."""
        amount = cad_amount * cadusd if self.fx_tier_currency == "USD" else cad_amount
        for tier in self.fx_tiers:
            if amount < tier.up_to:
                spread = tier.spread
                break
        else:
            spread = self.fx_tiers[-1].spread if self.fx_tiers else 0.0
        if self.fx_min_fee_usd:
            spread = max(spread, self.fx_min_fee_usd / (cad_amount * cadusd))
        return spread

    def allows(self, cad_ticker: str) -> bool:
        if self.gambit == "not_needed":
            return False
        if self.gambit == "dlr_only":
            return cad_ticker == "DLR.TO"
        return True

    def delay_for(self, cad_ticker: str) -> int:
        return self.dlr_delay if cad_ticker == "DLR.TO" else self.stock_delay


INF = float("inf")
DAVE_MANUEL = "https://www.davemanuel.com/en-ca/best-online-stock-brokers-canada/ (fees checked against broker schedules on 2026-10-18)"

BROKERS: dict[str, Broker] = {
    b.key: b
    for b in [
        Broker(
            key="questrade",
            name="Questrade",
            commission=0.0,
            journal_fee=9.95,
            fx_tiers=(FxTier(INF, 0.015),),
            gambit="all",
            dlr_delay=3,
            stock_delay=3,
            how="Online: Management > Journal shares, after the buy settles (T+1).",
            notes=(
                "Journal requests may take up to 5 business days; usually 1-2 after settlement.",
                "Do not trade the shares while the journal is processing.",
                "Journaling is free with Questrade Plus (use --broker questrade-plus).",
            ),
            sources=(
                "https://www.questrade.com/pricing-fees",
                "https://www.questrade.com/pricing/self-directed-commissions-plans-fees/",
                "https://www.questrade.com/learning/stocks-etfs/journaling-shares",
            ),
        ),
        Broker(
            key="questrade-plus",
            name="Questrade (with Questrade Plus)",
            commission=0.0,
            journal_fee=0.0,
            fx_tiers=(FxTier(INF, 0.015),),
            gambit="all",
            dlr_delay=3,
            stock_delay=3,
            how="Online: Management > Journal shares; unlimited free online journals with Plus.",
            notes=("Questrade Plus is a paid subscription.",),
            sources=(
                "https://www.questrade.com/learning/stocks-etfs/journaling-shares",
                "https://www.questrade.com/pricing-fees",
                DAVE_MANUEL,
            ),
            source_quality="mixed",
            extra_monthly_cost="Questrade Plus subscription (about $19.99/month)",
        ),
        Broker(
            key="wealthsimple",
            name="Wealthsimple",
            commission=0.0,
            journal_fee=9.95,
            fx_tiers=(FxTier(10_000, 0.015), FxTier(25_000, 0.010), FxTier(100_000, 0.005), FxTier(INF, 0.0)),
            gambit="dlr_only",
            dlr_delay=3,
            stock_delay=3,
            how="Web only: DLR security page > Journal. Needs an active USD account.",
            notes=(
                "Only DLR/DLR.U can be journaled.",
                "Journal takes about two business days; shares cannot be traded while pending.",
                "Fee is $9.95 plus tax, charged in CAD.",
                "Direct FX fees are charged on top of Wealthsimple's own exchange rate, which already "
                "includes a spread, so its direct conversion costs more than the fee shown (most visible "
                "at $100,000+, where the fee is 0%).",
            ),
            sources=(
                "https://help.wealthsimple.com/hc/en-us/articles/45418222943131",
                "https://help.wealthsimple.com/hc/en-ca/articles/4415548242971",
                "https://www.wealthsimple.com/en-ca/legal/fees/trade",
                "https://help.wealthsimple.com/hc/en-ca/articles/4414660979355",
            ),
            extra_monthly_cost="USD account: $10/month on Core, included for Premium/Generation",
        ),
        Broker(
            key="nbdb",
            name="National Bank Direct Brokerage",
            commission=0.0,
            journal_fee=9.95,
            fx_tiers=(FxTier(25_000, 0.017),),
            fx_tier_currency="USD",
            fx_tiers_complete=False,
            gambit="all",
            how="Internal security transfer between CAD and USD accounts ($9.95 per security).",
            notes=("Only the first FX tier (1.70% under US$25,000) is used; larger amounts are cheaper.",),
            sources=(
                "https://nbdb.ca/en/pricing",
                "https://www.nbc.ca/content/dam/shared/pdf/brokerage/19467-7-nbdb-fee-guide-commission-general-fee-schedule.pdf",
                DAVE_MANUEL,
            ),
            source_quality="mixed",
        ),
        Broker(
            key="td",
            name="TD Direct Investing",
            commission=9.99,
            journal_fee=0.0,
            fx_tiers=(FxTier(25_000, 0.0126), FxTier(100_000, 0.0078), FxTier(500_000, 0.0046),
                      FxTier(1_000_000, 0.0027), FxTier(INF, 0.0019)),
            fx_tier_currency="USD",
            gambit="all",
            how="Online: WebBroker > Accounts > Securities Transfers, after the buy settles.",
            notes=(
                "TD's FX page also mentions an affiliate surcharge, so its real conversion cost "
                "may be higher than the published spread (which makes the Gambit look slightly worse here).",
            ),
            sources=(
                "https://www.td.com/ca/en/investing/direct-investing/pricing/fx-pricing",
                "https://norbertsgambit.pages.dev/brokers/td-direct-investing/",
                DAVE_MANUEL,
            ),
            source_quality="mixed",
        ),
        Broker(
            key="rbc",
            name="RBC Direct Investing",
            commission=9.95,
            journal_fee=0.0,
            fx_tiers=(FxTier(25_000, 0.016),),
            fx_tiers_complete=False,
            gambit="all",
            dlr_delay=0,
            stock_delay=3,
            how="Buy DLR and sell DLR.U in the same account; RBC offsets the positions, no journal request.",
            notes=(
                "DLR.U can be sold right away, so there is no waiting risk with DLR.",
                "Only the first FX tier (1.6% under $25,000) is used; larger amounts are cheaper.",
            ),
            sources=(
                "https://norbertsgambit.pages.dev/brokers/rbc-direct-investing/",
                DAVE_MANUEL,
            ),
            source_quality="mixed",
        ),
        Broker(
            key="bmo",
            name="BMO InvestorLine",
            commission=0.0,
            journal_fee=0.0,
            fx_tiers=(FxTier(25_000, 0.016),),
            fx_tiers_complete=False,
            gambit="all",
            how="DLR.U must be sold by phone through the trade desk; interlisted stocks can be done online.",
            notes=(
                "$0 commissions on Canadian stocks and ETFs since 2026-09-14.",
                "Only the first FX tier (1.6% under $25,000) is used; larger amounts are cheaper.",
            ),
            sources=(
                "https://norbertsgambit.pages.dev/brokers/bmo-investorline/",
                DAVE_MANUEL,
            ),
            source_quality="mixed",
        ),
        Broker(
            key="cibc",
            name="CIBC Investor's Edge",
            commission=6.95,
            journal_fee=0.0,
            fx_tiers=(FxTier(25_000, 0.016),),
            fx_tiers_complete=False,
            gambit="all",
            how="By phone: ask the trade desk to journal DLR to DLR.U and sell it.",
            notes=("Only the first FX tier (1.6% under $25,000) is used; larger amounts are cheaper.",),
            sources=(
                "https://norbertsgambit.pages.dev/brokers/cibc-investors-edge/",
                DAVE_MANUEL,
            ),
            source_quality="mixed",
        ),
        Broker(
            key="ibkr",
            name="Interactive Brokers",
            commission=0.0,
            per_share=0.01,
            commission_min=1.0,
            fx_tiers=(FxTier(INF, 0.00002),),
            fx_min_fee_usd=2.0,
            gambit="not_needed",
            how="Convert directly (CAD.USD) at the interbank rate for 0.002% (US$2 minimum).",
            notes=("Direct conversion is close to the interbank rate, so the Gambit is not needed.",),
            sources=(
                "https://www.interactivebrokers.ca/en/index.php?f=49654",
                DAVE_MANUEL,
            ),
            source_quality="mixed",
        ),
    ]
}


def get_broker(key: str) -> Broker:
    k = key.strip().lower()
    if k not in BROKERS:
        raise KeyError(f"Unknown broker: {key}. Use one of: {', '.join(BROKERS)}")
    return BROKERS[k]
