#!/usr/bin/env python3
"""CLI runner for the ICT/SMC strategy engine.

Examples
--------
    # Synthetic data (no dependencies, reproducible):
    python run_backtest.py --synthetic --bars 4000 --seed 7

    # Your own data:
    python run_backtest.py --csv data/BTCUSDT_15m.csv

    # Tweak the gate:
    python run_backtest.py --synthetic --min-rr 2.5 --entry-level deep --no-shorts

The report prints the full-sample backtest, a 70/30 train/test split, and a
walk-forward (rolling out-of-sample) summary. Treat the *out-of-sample* numbers
as the only ones worth believing.
"""

from __future__ import annotations

import argparse
import sys

from ict_smc.types import Params
from ict_smc import data
from ict_smc.backtest import run, train_test, walk_forward


def build_params(args: argparse.Namespace) -> Params:
    return Params(
        swing_lookback=args.swing_lookback,
        atr_period=args.atr_period,
        displacement_atr_mult=args.displacement_mult,
        min_rr=args.min_rr,
        entry_level=args.entry_level,
        require_fvg=not args.allow_ob_only,
        equilibrium_filter=not args.no_equilibrium,
        risk_pct=args.risk_pct,
        commission_bps=args.commission_bps,
        slippage_bps=args.slippage_bps,
        starting_equity=args.equity,
        allow_long=not args.no_longs,
        allow_short=not args.no_shorts,
    )


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="ICT/SMC backtest runner")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--synthetic", action="store_true", help="use generated data")
    src.add_argument("--csv", type=str, help="path to OHLCV csv")

    ap.add_argument("--bars", type=int, default=4000)
    ap.add_argument("--seed", type=int, default=7)

    ap.add_argument("--swing-lookback", type=int, default=2)
    ap.add_argument("--atr-period", type=int, default=14)
    ap.add_argument("--displacement-mult", type=float, default=1.0)
    ap.add_argument("--min-rr", type=float, default=2.0)
    ap.add_argument("--entry-level", choices=["edge", "mid", "deep"], default="mid")
    ap.add_argument("--allow-ob-only", action="store_true",
                    help="allow order-block entries when no FVG is present")
    ap.add_argument("--no-equilibrium", action="store_true",
                    help="disable the discount/premium filter")
    ap.add_argument("--risk-pct", type=float, default=0.01)
    ap.add_argument("--commission-bps", type=float, default=2.0)
    ap.add_argument("--slippage-bps", type=float, default=1.0)
    ap.add_argument("--equity", type=float, default=10_000.0)
    ap.add_argument("--no-longs", action="store_true")
    ap.add_argument("--no-shorts", action="store_true")
    args = ap.parse_args(argv)

    if args.synthetic:
        candles = data.synthetic(n=args.bars, seed=args.seed)
        source = f"synthetic(n={args.bars}, seed={args.seed})"
    else:
        candles = data.from_csv(args.csv)
        source = args.csv

    params = build_params(args)

    print(f"== ICT/SMC backtest ==")
    print(f"source : {source}")
    print(f"bars   : {len(candles)}")
    print(f"params : min_rr={params.min_rr} entry={params.entry_level} "
          f"disp={params.displacement_atr_mult} eq_filter={params.equilibrium_filter} "
          f"long={params.allow_long} short={params.allow_short}")
    print()

    full = run(candles, params)
    print("FULL SAMPLE (in-sample, do not trust as an edge):")
    print("  " + full.report())
    print()

    tr, te = train_test(candles, params, split=0.7)
    print("TRAIN/TEST 70/30:")
    print("  train : " + tr.report())
    print("  test  : " + te.report() + "   <- out-of-sample")
    print()

    grid = {"min_rr": [1.5, 2.0, 2.5, 3.0],
            "displacement_atr_mult": [0.8, 1.0, 1.2]}
    folds, agg = walk_forward(candles, params, grid=grid, n_folds=4)
    print("WALK-FORWARD (optimize in-sample, score next fold):")
    for f in folds:
        print(f"  fold {f['fold']}: chose {f['chosen']} "
              f"(train E={f['train_expectancy_r']:+.3f}R) -> oos {f['oos'].report()}")
    print("  AGGREGATE OOS: " + agg.report())
    print()
    print("Reminder: on random/synthetic data a real edge should NOT appear. "
          "Aggregate OOS expectancy near -costs is the expected, healthy result.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
