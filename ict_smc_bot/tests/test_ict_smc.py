"""Unit + integration tests for the ICT/SMC engine.

Run from the package root:  python -m unittest discover -s tests -v
(or simply:  python -m pytest)
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ict_smc.types import Candle, Params
from ict_smc.detectors import (
    compute_atr, find_swings, detect_fvgs, is_displacement, find_order_block,
)
from ict_smc import data
from ict_smc.strategy import generate_setups
from ict_smc.backtest import backtest, run, train_test, walk_forward


def C(ts, o, h, l, c, v=0.0):
    return Candle(ts, o, h, l, c, v)


class TestDetectors(unittest.TestCase):
    def test_atr_basic(self):
        candles = [C(i, 10, 11, 9, 10) for i in range(20)]  # range 2 every bar
        atr = compute_atr(candles, 14)
        self.assertIsNone(atr[12])
        self.assertIsNotNone(atr[13])
        self.assertAlmostEqual(atr[19], 2.0, places=6)

    def test_swings_detects_peak_and_trough(self):
        highs = [10, 11, 12, 20, 12, 11, 10, 5, 3, 5, 11, 12, 13]
        candles = [C(i, h - 1, h, h - 2, h - 1) for i, h in enumerate(highs)]
        swings = find_swings(candles, 2)
        peak = [s for s in swings if s.kind == "high" and s.index == 3]
        self.assertTrue(peak, "should find the high at index 3")
        self.assertEqual(peak[0].confirmed_at, 5)  # index + lookback
        troughs = [s for s in swings if s.kind == "low"]
        self.assertTrue(any(s.index == 8 for s in troughs), "should find the low at index 8")

    def test_bull_fvg(self):
        # candle0 high=10, candle1 a big up displacement, candle2 low=12 > 10 => bull FVG
        candles = [
            C(0, 9, 10, 8, 9),
            C(1, 9, 20, 9, 19),   # displacement up
            C(2, 18, 22, 12, 21),
        ]
        atr = compute_atr(candles, 1)
        p = Params(require_displacement_fvg=False)
        fvgs = detect_fvgs(candles, atr, p)
        bull = [f for f in fvgs if f.direction == "bull"]
        self.assertEqual(len(bull), 1)
        self.assertAlmostEqual(bull[0].bottom, 10.0)
        self.assertAlmostEqual(bull[0].top, 12.0)

    def test_bear_fvg(self):
        candles = [
            C(0, 19, 22, 18, 19),
            C(1, 19, 19, 5, 6),   # displacement down
            C(2, 6, 8, 4, 5),
        ]
        atr = compute_atr(candles, 1)
        p = Params(require_displacement_fvg=False)
        fvgs = detect_fvgs(candles, atr, p)
        bear = [f for f in fvgs if f.direction == "bear"]
        self.assertEqual(len(bear), 1)
        self.assertAlmostEqual(bear[0].top, 18.0)   # low of candle0
        self.assertAlmostEqual(bear[0].bottom, 8.0)  # high of candle2

    def test_displacement_requires_body_and_range(self):
        p = Params(displacement_atr_mult=1.0, displacement_body_ratio=0.5)
        big_body = C(0, 10, 20, 10, 19)   # range 10, body 9
        self.assertTrue(is_displacement(big_body, 5.0, p, "bull"))
        small = C(0, 10, 12, 10, 11)      # range 2 < 1*5
        self.assertFalse(is_displacement(small, 5.0, p, "bull"))
        all_wick = C(0, 10, 20, 0, 10)    # range 20, body 0
        self.assertFalse(is_displacement(all_wick, 5.0, p, "bull"))

    def test_order_block(self):
        candles = [
            C(0, 10, 11, 9, 10.5),  # bull
            C(1, 10.5, 11, 9, 9.5),  # bear  <- expected OB before up displacement at 2
            C(2, 9.5, 20, 9.5, 19),  # bull displacement
        ]
        ob = find_order_block(candles, 2, long=True)
        self.assertEqual(ob, 1)


class TestNoLookahead(unittest.TestCase):
    def test_setup_fields_use_only_past(self):
        candles = data.synthetic(n=2500, seed=3)
        params = Params(require_fvg=False, min_rr=1.5)
        setups, _ = generate_setups(candles, params)
        for s in setups:
            # the canonical ordering must hold
            self.assertLess(s.sweep_index, s.mss_index)
            self.assertEqual(s.armed_at, s.mss_index)
            # geometry must be self-consistent for the direction
            if s.direction == "long":
                self.assertLess(s.stop, s.entry)
                self.assertGreater(s.target, s.entry)
            else:
                self.assertGreater(s.stop, s.entry)
                self.assertLess(s.target, s.entry)
            self.assertGreaterEqual(s.rr + 1e-9, params.min_rr)


class TestSimulation(unittest.TestCase):
    def test_no_overlapping_trades(self):
        candles = data.synthetic(n=3000, seed=11)
        params = Params(require_fvg=False, min_rr=1.5)
        res = run(candles, params)
        last_exit = -1
        for t in res.trades:
            self.assertGreaterEqual(t.entry_index, last_exit)
            self.assertGreaterEqual(t.exit_index, t.entry_index)
            last_exit = t.exit_index

    def test_crafted_long_hits_target(self):
        # A clean long with lookback=1: protected swing high, swing low that gets
        # swept, displacement up that breaks the high (MSS) AND leaves a bull FVG
        # that is complete *by* the MSS bar (no look-ahead), then a retrace into
        # that FVG fills the entry and price runs to target.
        seq = [
            C(0, 50, 55, 49, 50),
            C(1, 50, 60, 50, 59),   # swing high = 60 (protected high)
            C(2, 59, 58, 40, 41),   # down
            C(3, 41, 42, 30, 31),   # swing low = 30 (the liquidity level)
            C(4, 31, 35, 31, 34),   # bounce -> confirms the low at idx 3
            C(5, 32, 33, 25, 31),   # SWEEP: low 25 < 30, close 31 >= 30
            C(6, 31, 56, 31, 55),   # displacement up (middle candle of the FVG)
            C(7, 55, 75, 55, 74),   # MSS: close 74 > 60; FVG[33,55]: low55 > high5=33
            C(8, 74, 74, 40, 50),   # retrace into the FVG (low 40 <= entry ~44)
            C(9, 50, 100, 50, 99),  # continuation toward target
        ]

        params = Params(
            swing_lookback=1, atr_period=2, displacement_atr_mult=0.5,
            require_displacement_fvg=False, require_fvg=True, equilibrium_filter=False,
            min_rr=1.0, target_synthetic_fallback=True, entry_valid_bars=10,
            trade_max_bars=20, slippage_bps=0.0, commission_bps=0.0,
            allow_short=False,
        )
        setups, _ = generate_setups(seq, params)
        self.assertTrue(setups, "expected at least one long setup")
        res = backtest(seq, setups, params)
        self.assertTrue(res.trades, "expected at least one trade")
        self.assertEqual(res.trades[0].direction, "long")
        self.assertEqual(res.trades[0].outcome, "target")
        self.assertGreater(res.trades[0].r_multiple, 0)


class TestValidation(unittest.TestCase):
    def test_determinism(self):
        c1 = data.synthetic(n=2000, seed=42)
        c2 = data.synthetic(n=2000, seed=42)
        r1 = run(c1, Params(require_fvg=False))
        r2 = run(c2, Params(require_fvg=False))
        self.assertEqual(r1.num_trades, r2.num_trades)
        self.assertAlmostEqual(r1.final_equity, r2.final_equity, places=6)

    def test_end_to_end_runs(self):
        candles = data.synthetic(n=4000, seed=5)
        params = Params(require_fvg=False, min_rr=2.0)
        tr, te = train_test(candles, params)
        self.assertIsInstance(tr.num_trades, int)
        self.assertIsInstance(te.num_trades, int)
        folds, agg = walk_forward(
            candles, params,
            grid={"min_rr": [1.5, 2.0, 2.5]}, n_folds=3,
        )
        self.assertEqual(len(folds), 3)
        self.assertGreaterEqual(agg.num_trades, 0)

    def test_no_edge_on_random_data(self):
        # Sanity guard against look-ahead: aggregated OOS expectancy on random
        # data must not be implausibly positive. A real bug (lookahead) tends to
        # produce huge positive expectancy; we allow generous slack.
        candles = data.synthetic(n=6000, seed=99)
        params = Params(require_fvg=False, min_rr=2.0)
        _, agg = walk_forward(
            candles, params,
            grid={"min_rr": [1.5, 2.0, 2.5, 3.0]}, n_folds=5,
        )
        if agg.num_trades >= 20:
            self.assertLess(agg.expectancy_r, 0.5,
                            "implausible OOS edge on random data -> suspect lookahead")


if __name__ == "__main__":
    unittest.main(verbosity=2)
