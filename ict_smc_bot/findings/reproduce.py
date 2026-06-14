#!/usr/bin/env python3
"""Reproduce the headline findings: negative control vs. real data.

Run from the package root:  python3 findings/reproduce.py

It prints, for each dataset, the full-sample backtest, the walk-forward
out-of-sample aggregate, and a robustness check (median trade + expectancy with
the single best trade removed). The point is the *comparison*: an honest harness
shows ~no edge on random data, and the real-data results sit inside (or below)
that random noise floor.

Strategy and data are frozen here for reproducibility: the BTC-USD CSVs in
findings/data/ are a Coinbase snapshot pulled 2026-06-14 (15m ~52 days, 1h ~208
days). Re-fetch fresh data with ../fetch_coinbase.py.
"""

from __future__ import annotations

import os
import statistics as st
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ict_smc import data
from ict_smc.types import Params
from ict_smc.backtest import run, walk_forward

GRID = {"min_rr": [1.5, 2.0, 2.5, 3.0], "displacement_atr_mult": [0.8, 1.0, 1.2]}
HERE = os.path.dirname(os.path.abspath(__file__))


def stress(label: str, candles) -> None:
    base = Params(require_fvg=False, min_rr=2.0)
    full = run(candles, base)
    _, agg = walk_forward(candles, base, grid=GRID, n_folds=4)
    rs = sorted(t.r_multiple for t in agg.trades)
    n = len(rs)
    drop1 = (sum(rs) - rs[-1]) / (n - 1) if n > 1 else 0.0
    print(f"[{label}] bars={len(candles)}")
    print(f"  full-sample (largest n): expectancy={full.expectancy_r:+.3f}R "
          f"PF={full.profit_factor:.2f} ret={full.total_return_pct * 100:+.1f}% "
          f"trades={full.num_trades}")
    print(f"  walk-forward OOS: trades={n} expectancy={agg.expectancy_r:+.3f}R "
          f"PF={agg.profit_factor:.2f} win%={agg.win_rate * 100:.0f}")
    if n > 1:
        print(f"  robustness: median={st.median(rs):+.2f}R | best={rs[-1]:+.2f}R | "
              f"OOS expectancy WITHOUT best trade={drop1:+.3f}R")
    print()


def main() -> int:
    print("=== NEGATIVE CONTROL (random data; an honest rig must show ~no edge) ===")
    for seed in (7, 42, 99):
        stress(f"random seed={seed}", data.synthetic(n=6000, seed=seed))

    print("=== REAL DATA (Coinbase BTC-USD snapshot 2026-06-14) ===")
    stress("BTC-USD 15m", data.from_csv(os.path.join(HERE, "data", "BTC-USD_15m.csv")))
    stress("BTC-USD 1h", data.from_csv(os.path.join(HERE, "data", "BTC-USD_1h.csv")))

    print("Takeaway: the real-data walk-forward results fall inside (or below) the "
          "random-data noise floor, and every positive reading collapses when the "
          "single best trade is removed. That is the empirical signature of no edge.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
