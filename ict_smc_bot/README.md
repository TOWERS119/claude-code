# ICT / SMC Strategy Engine (bot addon)

A dependency-free Python implementation of the ICT / Smart Money Concepts entry
gate described in [`../notes/ict-smc-addon.md`](../notes/ict-smc-addon.md), with
a look-ahead-safe backtester and honest out-of-sample validation.

This is the **strategy + validation layer** of the agent architecture in
[`../notes/trading-knowledge-base.md`](../notes/trading-knowledge-base.md) (§4).
It is a *scaffold to test rules*, **not** a profitable system — see the caveats.

## Why it's built this way

- **Pure standard library.** No numpy/pandas. It runs unchanged inside a
  stateless cloud agent run (no install step, no dependency drift).
- **Look-ahead-safe by construction.** Swings are only used after their
  `confirmed_at` bar; setups arm at the MSS bar; fills happen strictly later;
  same-bar stop+target counts as a stop. (Tested.)
- **Validation is the product.** The numbers that matter are out-of-sample. On
  random data the strategy is correctly a net loser — that's the proof there's
  no leak.

## Layout

```
ict_smc_bot/
├── ict_smc/
│   ├── types.py        # Candle, Swing, FVG, Setup, Trade, Params (all knobs)
│   ├── detectors.py    # ATR, swings, displacement, FVGs, order blocks
│   ├── strategy.py     # the entry gate (sweep → MSS → PD array → risk geometry)
│   ├── backtest.py     # simulator, metrics, train_test, walk_forward
│   └── data.py         # CSV loader + synthetic OHLC generator
├── run_backtest.py     # CLI report (full / train-test / walk-forward)
├── strategy_spec.md    # the numeric rule spec
└── tests/test_ict_smc.py
```

## Quick start

```bash
cd ict_smc_bot

# Reproducible synthetic run (no data needed):
python3 run_backtest.py --synthetic --bars 5000 --seed 7 --allow-ob-only

# Your own OHLCV csv (header: open,high,low,close[,volume,timestamp]):
python3 run_backtest.py --csv data/BTCUSDT_15m.csv --min-rr 2.5 --entry-level deep

# Tests:
python3 -m unittest discover -s tests -v
```

### Library use

```python
from ict_smc.types import Params
from ict_smc import data
from ict_smc.backtest import run, walk_forward

candles = data.synthetic(n=4000, seed=7)        # or data.from_csv("ohlcv.csv")
params  = Params(min_rr=2.0, entry_level="mid")

result = run(candles, params)
print(result.report())

folds, oos = walk_forward(candles, params,
                          grid={"min_rr": [1.5, 2.0, 2.5, 3.0]}, n_folds=4)
print("aggregate OOS:", oos.report())
```

## Reading the output

```
trades=50 (L25/S25)  win%=28.0  PF=0.72  expectancy=-0.204R  ...
```

- **expectancy (R)** — average profit per trade in units of risk. This is the
  number to watch. Positive *out-of-sample* is the only thing that counts.
- **PF** — profit factor (gross win / gross loss). >1 to be viable.
- The **walk-forward AGGREGATE OOS** line is the headline. Expect it near
  `−costs` on synthetic data — and treat a big positive number there as a **bug
  signal**, not a discovery.

## Getting real data (optional)

Keep the core import-clean; fetch data with a throwaway script:

```python
# pip install ccxt
import ccxt, csv
ohlcv = ccxt.binance().fetch_ohlcv("BTC/USDT", timeframe="15m", limit=1000)
with open("data/BTCUSDT_15m.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["timestamp","open","high","low","close","volume"])
    w.writerows(ohlcv)
```

Then `--csv data/BTCUSDT_15m.csv`. For multi-timeframe ICT (4H bias → 15m entry,
per addon §10) run the gate on each timeframe and require agreement; that wiring
is the documented next step, not yet built.

## Honest limitations (read this)

This intentionally implements **only the structural core** of the addon (sweep,
MSS, FVG/OB, discount/premium, risk geometry). It omits the softer confluences —
SMT divergence, the two-lines regime, session timing, candle continuity, EMA
bias. Add them **one at a time, each validated out-of-sample**; adding them all
at once is the over-fitting trap the notes warn about.

ICT/SMC is highly discretionary; this encodes one defensible interpretation of
its rules. **No edge is demonstrated or implied.** Backtest profits — especially
optimizer-selected ones — are hypotheses until they survive out-of-sample and
walk-forward. Paper-trade for a meaningful period; enforce risk limits
**broker-side**, not just in code. See `../notes/trading-knowledge-base.md` §5–6.
