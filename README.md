# Norbert's Gambit Optimizer

Should you convert Canadian dollars to US dollars at your bank, or use
**Norbert's Gambit**? This tool answers that on historical data: give it an
amount in CAD and a date range, and it tests both methods on every possible
start date, then reports the average savings, the risk, the best and worst
cases, and the break-even amount.

## How Norbert's Gambit works

1. Buy a stock listed in both currencies (default: DLR.TO, the CAD side of
   the Global X US Dollar Currency ETF) with CAD.
2. Ask your broker to journal the shares to the USD listing (DLR-U.TO).
3. Sell the shares for USD.

You avoid the bank's FX spread (often about 2%) but pay two trading
commissions and wait for the journal to settle, during which prices can move.

## Model

| Method | USD received |
| --- | --- |
| Bank | CAD × CADUSD rate × (1 − spread) |
| Norbert's Gambit | whole shares bought on day *t* at the CAD price, sold on day *t + delay* at the USD price, minus both commissions; leftover CAD goes through the bank |

Defaults: 2% bank spread, 9.95 commission on each side, 4 trading-day delay.
All of them can be changed from the command line.

## Install

```bash
git clone https://github.com/<your-username>/norbert-gambit-optimizer.git
cd norbert-gambit-optimizer
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## Usage

Real data from Yahoo Finance:

```bash
norbert-optimizer --amount 10000 --start 2023-01-01 --end 2025-12-31
```

Offline, with the bundled synthetic sample (made-up prices, for trying the tool):

```bash
norbert-optimizer --amount 10000 --csv data/sample_synthetic.csv
```

Useful options: `--spread 0.025`, `--commission-cad 0`, `--commission-usd 0`,
`--delay 3`, `--cad-ticker`, `--usd-ticker`, `--json`, `--charts <folder>`.

Output: a text summary plus two charts in `output/` (USD by start date, and
the distribution of Gambit-minus-bank savings).

## Results

_To be added: results and charts from real DLR.TO / DLR-U.TO data._

## Tests

```bash
pytest
```

Tests check the bank and Gambit formulas against hand calculations, the
settlement delay, leftover cash, the break-even search and input validation.

## Limitations

- Uses daily closing prices, not intraday bid/ask, so slippage is ignored.
- Ignores taxes (e.g. capital gains on the price change during the delay).
- Assumes the journal always takes exactly `--delay` trading days.
- The bank spread is a single fixed percentage.

## Project layout

```
src/norbert_optimizer/
    data.py     load and align prices (yfinance or CSV)
    models.py   bank and Gambit simulations
    stats.py    summary statistics and break-even amount
    plots.py    charts
    cli.py      command-line interface
tests/          pytest tests
scripts/        synthetic sample data generator
data/           synthetic sample CSV
```
