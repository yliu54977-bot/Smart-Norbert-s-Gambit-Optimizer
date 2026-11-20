"""Generate SYNTHETIC sample data so the project runs without internet.

The numbers are made up (random walks), not real market prices. Use
`python -m norbert_optimizer --start ... --end ...` for real yfinance data.
"""

from pathlib import Path

import numpy as np
import pandas as pd

rng = np.random.default_rng(42)
idx = pd.bdate_range("2024-01-02", "2025-12-31")
n = len(idx)

cadusd = 0.74 * np.exp(np.cumsum(rng.normal(0, 0.003, n)))
usd_price = 10.0 * np.exp(np.cumsum(rng.normal(0, 0.0005, n)))   # DLR-like, very stable
cad_price = usd_price / cadusd * (1 + rng.normal(0, 0.0008, n))  # small listing gap

df = pd.DataFrame(
    {"cad_price": cad_price.round(3), "usd_price": usd_price.round(3), "cadusd": cadusd.round(5)},
    index=pd.Index(idx, name="date"),
)
out = Path(__file__).resolve().parent.parent / "data" / "sample_synthetic.csv"
df.to_csv(out)
print(f"Wrote {len(df)} rows to {out}")
