"""Tests for the integrated bot: risk manager, paper broker, memory, engine."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ict_smc.types import Candle, Params
from ict_smc import data
from ict_smc.risk import RiskLimits, RiskManager
from ict_smc.broker import PaperBroker
from ict_smc.memory import Memory
from ict_smc.config import BotConfig, get_secret
from ict_smc.engine import run_once, build_broker


def C(ts, o, h, l, c, v=0.0):
    return Candle(ts, o, h, l, c, v)


class TestRiskManager(unittest.TestCase):
    def setUp(self):
        self.rm = RiskManager(RiskLimits(
            risk_pct=0.01, max_concurrent_positions=1, max_new_trades_per_day=3,
            max_daily_loss_pct=0.03, max_drawdown_pct=0.15, min_rr=2.0,
            max_position_notional_pct=0.25,
        ))

    def _eval(self, **over):
        base = dict(symbol="X", side="long", entry=100.0, stop=98.0, target=104.0,
                    equity=10_000.0, peak_equity=10_000.0, open_positions=[],
                    trades_today=0, daily_pnl=0.0, day_start_equity=10_000.0)
        base.update(over)
        return self.rm.evaluate(**base)

    def test_approves_and_sizes(self):
        # wide stop so the 25% notional cap doesn't bind: risk/unit = 10
        d = self._eval(entry=100.0, stop=90.0, target=130.0)
        self.assertTrue(d.approved)
        self.assertEqual(d.reason, "approved")
        # risk 1% of 10k = 100; risk/unit = 10 -> qty 10; notional 1000 < 2500 cap
        self.assertAlmostEqual(d.qty, 10.0, places=6)

    def test_rejects_below_min_rr(self):
        d = self._eval(target=101.0)  # rr = 0.5
        self.assertFalse(d.approved)
        self.assertIn("reward:risk", d.reason)

    def test_kill_switch(self):
        d = self._eval(equity=8000.0, peak_equity=10_000.0)  # 20% dd > 15%
        self.assertFalse(d.approved)
        self.assertIn("kill-switch", d.reason)

    def test_daily_breaker(self):
        d = self._eval(daily_pnl=-400.0, day_start_equity=10_000.0)  # -4% > 3%
        self.assertFalse(d.approved)
        self.assertIn("daily", d.reason)

    def test_max_concurrent(self):
        d = self._eval(open_positions=[object()])
        self.assertFalse(d.approved)

    def test_max_trades_per_day(self):
        d = self._eval(trades_today=3)
        self.assertFalse(d.approved)

    def test_whitelist(self):
        rm = RiskManager(RiskLimits(instrument_whitelist=("BTCUSDT",)))
        d = rm.evaluate(symbol="DOGE", side="long", entry=100, stop=98, target=104,
                        equity=10_000, peak_equity=10_000, open_positions=[],
                        trades_today=0, daily_pnl=0, day_start_equity=10_000)
        self.assertFalse(d.approved)
        self.assertIn("whitelist", d.reason)

    def test_notional_cap_shrinks_size(self):
        # tiny stop distance -> huge qty -> capped by 25% notional
        d = self._eval(entry=100.0, stop=99.99, target=100.04)
        self.assertTrue(d.approved)
        self.assertLessEqual(d.qty * 100.0, 10_000.0 * 0.25 + 1e-6)
        self.assertIn("capped", d.reason)


class TestPaperBroker(unittest.TestCase):
    def test_fill_and_target(self):
        b = PaperBroker(starting_equity=10_000.0, slippage_bps=0.0, commission_bps=0.0)
        b.submit_bracket("X", "long", qty=10, entry=100, stop=95, target=110,
                         armed_index=0, ttl=10, max_hold=50)
        # bar 1: dips to 100 (fill) but does not hit stop/target
        f, c = b.on_bar(1, C(1, 101, 102, 99, 101))
        self.assertEqual(len(f), 1)
        self.assertEqual(len(c), 0)
        # bar 2: rallies through target
        f, c = b.on_bar(2, C(2, 101, 112, 101, 111))
        self.assertEqual(len(c), 1)
        self.assertEqual(c[0].outcome, "target")
        self.assertAlmostEqual(c[0].pnl, 100.0, places=6)  # (110-100)*10
        self.assertAlmostEqual(b.get_equity(), 10_100.0, places=6)

    def test_stop_priority_same_bar(self):
        b = PaperBroker(10_000.0, slippage_bps=0.0, commission_bps=0.0)
        b.submit_bracket("X", "long", 10, entry=100, stop=95, target=110,
                         armed_index=0, ttl=10, max_hold=50)
        # one wild bar that spans entry, stop, and target -> stop must win
        f, c = b.on_bar(1, C(1, 100, 115, 90, 100))
        self.assertEqual(len(c), 1)
        self.assertEqual(c[0].outcome, "stop")
        self.assertLess(c[0].pnl, 0)

    def test_expiry(self):
        b = PaperBroker(10_000.0)
        b.submit_bracket("X", "long", 10, entry=50, stop=45, target=60,
                         armed_index=0, ttl=2, max_hold=50)
        for i in range(1, 6):  # price never reaches 50
            b.on_bar(i, C(i, 100, 101, 99, 100))
        self.assertEqual(len(b.get_pending()), 0)
        self.assertEqual(len(b.get_positions()), 0)

    def test_serialization_roundtrip(self):
        b = PaperBroker(10_000.0)
        b.submit_bracket("X", "long", 10, entry=100, stop=95, target=110,
                         armed_index=0, ttl=10, max_hold=50)
        b.on_bar(1, C(1, 101, 102, 99, 101))  # creates a position
        d = b.to_dict()
        b2 = PaperBroker.from_dict(d)
        self.assertEqual(len(b2.get_positions()), len(b.get_positions()))
        self.assertAlmostEqual(b2.get_equity(), b.get_equity(), places=6)
        # restored broker continues to function
        f, c = b2.on_bar(2, C(2, 101, 112, 101, 111))
        self.assertEqual(c[0].outcome, "target")


class TestMemory(unittest.TestCase):
    def test_roundtrip_and_trades(self):
        with tempfile.TemporaryDirectory() as d:
            m = Memory(d)
            self.assertEqual(m.load_state(), {})
            m.save_state({"last_index": 42, "peak_equity": 10_500.0})
            self.assertEqual(m.load_state()["last_index"], 42)
            m.append_trade({"pnl": 10.0, "r_multiple": 1.0})
            m.append_trade({"pnl": -5.0, "r_multiple": -0.5})
            trades = m.read_trades()
            self.assertEqual(len(trades), 2)
            self.assertAlmostEqual(sum(t["pnl"] for t in trades), 5.0)
            m.reset()
            self.assertEqual(m.load_state(), {})
            self.assertEqual(m.read_trades(), [])


class TestEngine(unittest.TestCase):
    def _config(self, d):
        cfg = BotConfig(symbol="SYNTH", state_dir=d)
        cfg.limits.min_rr = 2.0
        cfg.params = Params(require_fvg=False, min_rr=2.0)
        return cfg

    def test_run_once_resumes_and_is_idempotent(self):
        candles = data.synthetic(n=3000, seed=7)
        with tempfile.TemporaryDirectory() as d:
            cfg = self._config(d)
            mem = Memory(d)
            risk = RiskManager(cfg.limits)

            broker = build_broker(cfg, mem)
            r1 = run_once(cfg, broker, risk, mem, candles, max_bars=1500)
            self.assertEqual(r1.processed_from, 0)
            self.assertEqual(r1.processed_to, 1499)

            # second invocation: fresh broker restored from memory, resumes
            broker = build_broker(cfg, mem)
            r2 = run_once(cfg, broker, risk, mem, candles)
            self.assertEqual(r2.processed_from, 1500)
            self.assertEqual(r2.processed_to, len(candles) - 1)

            # third invocation: nothing new -> no-op
            broker = build_broker(cfg, mem)
            r3 = run_once(cfg, broker, risk, mem, candles)
            self.assertGreater(r3.processed_from, r3.processed_to)
            self.assertEqual(r3.fills, 0)
            self.assertEqual(len(r3.submitted), 0)

            # trade log persisted and equity reflects realized PnL
            self.assertEqual(len(mem.read_trades()), r1.closes + r2.closes)

    def test_max_concurrent_enforced_live(self):
        candles = data.synthetic(n=4000, seed=3)
        with tempfile.TemporaryDirectory() as d:
            cfg = self._config(d)
            cfg.limits.max_concurrent_positions = 1
            mem = Memory(d)
            risk = RiskManager(cfg.limits)
            broker = build_broker(cfg, mem)
            run_once(cfg, broker, risk, mem, candles)
            # the broker never holds more than one position at a time
            self.assertLessEqual(len(broker.get_positions()), 1)

    def test_kill_switch_halts_entries(self):
        # Force an immediate kill-switch: start "below peak" via state, then ensure
        # no new orders are submitted while halted.
        candles = data.synthetic(n=2000, seed=11)
        with tempfile.TemporaryDirectory() as d:
            cfg = self._config(d)
            cfg.limits.max_drawdown_pct = 0.0001  # trip instantly
            mem = Memory(d)
            # seed a peak well above starting equity so drawdown is breached at once
            mem.save_state({"last_index": -1, "peak_equity": 1_000_000.0})
            risk = RiskManager(cfg.limits)
            broker = build_broker(cfg, mem)
            r = run_once(cfg, broker, risk, mem, candles)
            self.assertTrue(r.halted_reasons)
            self.assertEqual(len(r.submitted), 0)


class TestConfig(unittest.TestCase):
    def test_get_secret_required_raises(self):
        with self.assertRaises(RuntimeError):
            get_secret("DEFINITELY_MISSING_SECRET_XYZ", required=True)

    def test_get_secret_optional(self):
        self.assertEqual(get_secret("DEFINITELY_MISSING_SECRET_XYZ", required=False), "")

    def test_from_env_overrides(self):
        os.environ["BOT_SYMBOL"] = "ETHUSDT"
        os.environ["BOT_RISK_PCT"] = "0.02"
        try:
            from ict_smc.config import from_env
            cfg = from_env()
            self.assertEqual(cfg.symbol, "ETHUSDT")
            self.assertAlmostEqual(cfg.limits.risk_pct, 0.02)
        finally:
            del os.environ["BOT_SYMBOL"]
            del os.environ["BOT_RISK_PCT"]


if __name__ == "__main__":
    unittest.main(verbosity=2)
