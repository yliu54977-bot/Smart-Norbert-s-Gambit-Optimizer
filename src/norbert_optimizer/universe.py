"""Securities you can use for Norbert's Gambit.

Each pair is one security listed twice: in CAD on the TSX and in USD (on the
TSX for DLR, on the NYSE or Nasdaq for interlisted companies). Your broker
buys the CAD listing, journals the shares to the USD listing, and you sell.

Check with your broker before using a pair: not every broker journals every
interlisted stock, and some charge for it.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Pair:
    name: str
    cad: str            # CAD listing (Yahoo ticker)
    usd: str            # USD listing (Yahoo ticker)
    kind: str = "stock"  # "etf" or "stock"
    derive_usd: bool = False  # True when Yahoo has no history for the USD listing


DLR = Pair("Global X US Dollar Currency ETF", "DLR.TO", "DLR-U.TO", "etf", derive_usd=True)

UNIVERSE: list[Pair] = [
    DLR,
    Pair("Royal Bank of Canada", "RY.TO", "RY"),
    Pair("Toronto-Dominion Bank", "TD.TO", "TD"),
    Pair("Bank of Nova Scotia", "BNS.TO", "BNS"),
    Pair("Bank of Montreal", "BMO.TO", "BMO"),
    Pair("CIBC", "CM.TO", "CM"),
    Pair("Manulife Financial", "MFC.TO", "MFC"),
    Pair("Sun Life Financial", "SLF.TO", "SLF"),
    Pair("Enbridge", "ENB.TO", "ENB"),
    Pair("TC Energy", "TRP.TO", "TRP"),
    Pair("Canadian Natural Resources", "CNQ.TO", "CNQ"),
    Pair("Suncor Energy", "SU.TO", "SU"),
    Pair("Cenovus Energy", "CVE.TO", "CVE"),
    Pair("Imperial Oil", "IMO.TO", "IMO"),
    Pair("Canadian Pacific Kansas City", "CP.TO", "CP"),
    Pair("Canadian National Railway", "CNR.TO", "CNI"),
    Pair("BCE", "BCE.TO", "BCE"),
    Pair("TELUS", "T.TO", "TU"),
    Pair("Shopify", "SHOP.TO", "SHOP"),
    Pair("Brookfield Corporation", "BN.TO", "BN"),
    Pair("Brookfield Asset Management", "BAM.TO", "BAM"),
    Pair("Thomson Reuters", "TRI.TO", "TRI"),
    Pair("Nutrien", "NTR.TO", "NTR"),
    Pair("Cameco", "CCO.TO", "CCJ"),
    Pair("Barrick Mining", "ABX.TO", "B"),
    Pair("Agnico Eagle Mines", "AEM.TO", "AEM"),
    Pair("Wheaton Precious Metals", "WPM.TO", "WPM"),
    Pair("Franco-Nevada", "FNV.TO", "FNV"),
    Pair("Kinross Gold", "K.TO", "KGC"),
    Pair("Teck Resources", "TECK-B.TO", "TECK"),
    Pair("Restaurant Brands International", "QSR.TO", "QSR"),
    Pair("Waste Connections", "WCN.TO", "WCN"),
    Pair("Gildan Activewear", "GIL.TO", "GIL"),
    Pair("Open Text", "OTEX.TO", "OTEX"),
    Pair("CGI", "GIB-A.TO", "GIB"),
    Pair("Magna International", "MG.TO", "MGA"),
    Pair("Fortis", "FTS.TO", "FTS"),
    Pair("CAE", "CAE.TO", "CAE"),
    Pair("Celestica", "CLS.TO", "CLS"),
    Pair("Ovintiv", "OVV.TO", "OVV"),
    Pair("Pembina Pipeline", "PPL.TO", "PBA"),
    Pair("TFI International", "TFII.TO", "TFII"),
    Pair("Rogers Communications", "RCI-B.TO", "RCI"),
    Pair("BlackBerry", "BB.TO", "BB"),
]


def find_pair(key: str) -> Pair:
    """Look up a pair by its CAD ticker, USD ticker or name (case-insensitive)."""
    k = key.strip().lower()
    for p in UNIVERSE:
        if k in (p.cad.lower(), p.usd.lower(), p.name.lower(), p.cad.lower().removesuffix(".to")):
            return p
    raise KeyError(f"Unknown pair: {key}. Use one of: {', '.join(p.cad for p in UNIVERSE)}")
