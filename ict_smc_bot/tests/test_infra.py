"""Tests for the infrastructure layer: performance, notify, live, routine."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ict_smc.types import Candle, Params
from ict_smc import data, performance
from ict_smc.notify import (
    NullNotifier, FileNotifier, WebhookNotifier, CompositeNotifier,
)
from ict_smc.config import BotConfig
from ict_smc.risk import RiskManager
from ict_smc.memory import Memory
from ict_smc.live import (
    SimVenueClient, CoinbaseClient, AlpacaClient, LiveBroker, run_live_once,
)
from ict_smc.routine import run_routine
import json


def C(ts, o, h, l, c, v=0.0):
    return Candle(ts, o, h, l, c, v)


class TestPerformance(unittest.TestCase):
    def test_alpha_vs_buy_and_hold(self):
        # market doubles -> buy&hold = +100%
        candles = [C(i, 100 + i, 100 + i, 100 + i, 100 + i) for i in range(101)]  # 100->200
        self.assertAlmostEqual(performance.buy_and_hold_return(candles), 1.0, places=6)
        trades = [{"pnl": 50.0, "r_multiple": 1.0}, {"pnl": -25.0, "r_multiple": -0.5}]
        rep = performance.summarize(trades, starting_equity=1000.0, candles=candles)
        self.assertAlmostEqual(rep.total_return, 0.025, places=6)  # +25 net on 1000
        self.assertAlmostEqual(rep.buy_hold_return, 1.0, places=6)
        self.assertLess(rep.alpha, 0)  # lagged the benchmark
        self.assertEqual(rep.num_trades, 2)

    def test_grade_insufficient_sample(self):
        rep = performance.summarize([{"pnl": 1.0, "r_multiple": 1.0}], 1000.0, [C(0, 1, 1, 1, 1)])
        self.assertIn("insufficient", rep.grade.lower())

    def test_weekly_review_mentions_benchmark(self):
        candles = [C(i, 100, 100, 100, 100) for i in range(10)]
        rep = performance.summarize([], 1000.0, candles)
        text = performance.weekly_review_text(rep, "TEST")
        self.assertIn("benchmark", text.lower())
        self.assertIn("Self-grade", text)


class TestNotify(unittest.TestCase):
    def test_file_notifier(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "alerts.log")
            n = FileNotifier(p)
            self.assertTrue(n.send("hello", "world"))
            with open(p) as fh:
                content = fh.read()
            self.assertIn("hello", content)
            self.assertIn("world", content)

    def test_webhook_with_fake_transport(self):
        captured = {}

        def fake(url, payload, headers):
            captured["url"] = url
            captured["payload"] = payload
            return 200

        n = WebhookNotifier("http://example/hook", transport=fake)
        self.assertTrue(n.send("t", "m", "info"))
        self.assertEqual(captured["url"], "http://example/hook")
        self.assertIn(b"\"title\"", captured["payload"])

    def test_webhook_failure_is_swallowed(self):
        def boom(url, payload, headers):
            raise RuntimeError("network down")

        n = WebhookNotifier("http://x", transport=boom)
        self.assertFalse(n.send("t", "m"))  # returns False, does not raise

    def test_composite(self):
        sent = []

        class Spy:
            def send(self, title, message, level="info"):
                sent.append(title)
                return True

        c = CompositeNotifier([Spy(), Spy()])
        self.assertTrue(c.send("x", "y"))
        self.assertEqual(len(sent), 2)


class TestLiveSafety(unittest.TestCase):
    def setUp(self):
        os.environ.pop("BOT_ALLOW_LIVE", None)

    def tearDown(self):
        os.environ.pop("BOT_ALLOW_LIVE", None)

    def test_order_blocked_without_allow_live_flag(self):
        b = LiveBroker(SimVenueClient(), symbol="BTC", allow_live=False)
        os.environ["BOT_ALLOW_LIVE"] = "1"
        res = b.submit_bracket(symbol="BTC", side="long", qty=1, entry=100, stop=95, target=110)
        self.assertFalse(res.ok)
        self.assertIn("allow_live", res.error)

    def test_order_blocked_without_env(self):
        b = LiveBroker(SimVenueClient(), symbol="BTC", allow_live=True)
        # BOT_ALLOW_LIVE not set
        res = b.submit_bracket(symbol="BTC", side="long", qty=1, entry=100, stop=95, target=110)
        self.assertFalse(res.ok)
        self.assertIn("BOT_ALLOW_LIVE", res.error)

    def test_order_allowed_with_both_switches(self):
        sim = SimVenueClient()
        b = LiveBroker(sim, symbol="BTC", allow_live=True)
        os.environ["BOT_ALLOW_LIVE"] = "1"
        res = b.submit_bracket(symbol="BTC", side="long", qty=1, entry=100, stop=95, target=110)
        self.assertTrue(res.ok)
        self.assertEqual(len(sim.placed), 1)

    def test_notional_cap_inside_broker(self):
        b = LiveBroker(SimVenueClient(), symbol="BTC", allow_live=True, max_order_notional=50.0)
        os.environ["BOT_ALLOW_LIVE"] = "1"
        res = b.submit_bracket(symbol="BTC", side="long", qty=1, entry=100, stop=95, target=110)
        self.assertFalse(res.ok)
        self.assertIn("notional", res.error)

    def test_read_only_queries_always_allowed(self):
        b = LiveBroker(SimVenueClient(equity=12345.0), symbol="BTC", allow_live=False)
        self.assertEqual(b.get_equity(), 12345.0)
        self.assertEqual(b.get_positions(), [])

    def test_coinbase_client_refuses_until_implemented(self):
        c = CoinbaseClient()
        with self.assertRaises(NotImplementedError):
            c.place_bracket(symbol="BTC", side="long", qty=1, entry=1, stop=1, target=1)


class TestAlpacaClient(unittest.TestCase):
    """Exercises the Alpaca paper client with a fake HTTP transport: no network,
    no keys. Verifies request construction, auth headers, and parsing."""

    def _client_with(self, responses):
        calls = []

        def fake_http(method, url, headers, body=None):
            calls.append({"method": method, "url": url, "headers": headers,
                          "body": json.loads(body) if body else None})
            status, payload = responses.get((method, url.split("alpaca.markets")[-1]),
                                            (200, b"{}"))
            return status, payload

        client = AlpacaClient(http=fake_http, key="k", secret="s")
        return client, calls

    def test_defaults_to_paper_sandbox(self):
        c = AlpacaClient(key="k", secret="s")
        self.assertIn("paper-api.alpaca.markets", c.base_url)

    def test_get_equity_parses(self):
        c, calls = self._client_with({
            ("GET", "/v2/account"): (200, b'{"equity": "10500.25"}'),
        })
        self.assertAlmostEqual(c.get_account_equity(), 10500.25, places=2)
        self.assertEqual(calls[0]["headers"]["APCA-API-KEY-ID"], "k")
        self.assertEqual(calls[0]["headers"]["APCA-API-SECRET-KEY"], "s")

    def test_place_bracket_builds_correct_payload(self):
        c, calls = self._client_with({
            ("POST", "/v2/orders"): (200, b'{"id": "abc-123"}'),
        })
        resp = c.place_bracket(symbol="AAPL", side="long", qty=3,
                               entry=100.0, stop=95.0, target=110.0)
        self.assertEqual(resp["id"], "abc-123")
        body = calls[0]["body"]
        self.assertEqual(body["order_class"], "bracket")
        self.assertEqual(body["side"], "buy")
        self.assertEqual(body["type"], "limit")
        self.assertEqual(body["limit_price"], 100.0)
        self.assertEqual(body["take_profit"]["limit_price"], 110.0)
        self.assertEqual(body["stop_loss"]["stop_price"], 95.0)

    def test_short_maps_to_sell(self):
        c, calls = self._client_with({("POST", "/v2/orders"): (200, b'{"id":"x"}')})
        c.place_bracket(symbol="AAPL", side="short", qty=1, entry=100, stop=105, target=90)
        self.assertEqual(calls[0]["body"]["side"], "sell")

    def test_http_error_raises(self):
        c, _ = self._client_with({("GET", "/v2/account"): (403, b'{"message":"forbidden"}')})
        with self.assertRaises(RuntimeError):
            c.get_account_equity()

    def test_alpaca_through_livebroker_gates(self):
        # AlpacaClient behind LiveBroker still obeys the fail-closed gates.
        c, calls = self._client_with({("POST", "/v2/orders"): (200, b'{"id":"ord1"}')})
        b = LiveBroker(c, symbol="AAPL", allow_live=True)
        # without the env switch -> rejected, no HTTP call made
        os.environ.pop("BOT_ALLOW_LIVE", None)
        res = b.submit_bracket(symbol="AAPL", side="long", qty=1, entry=100, stop=95, target=110)
        self.assertFalse(res.ok)
        self.assertEqual(len(calls), 0)
        # with the env switch -> order placed
        os.environ["BOT_ALLOW_LIVE"] = "1"
        try:
            res = b.submit_bracket(symbol="AAPL", side="long", qty=1, entry=100, stop=95, target=110)
        finally:
            os.environ.pop("BOT_ALLOW_LIVE", None)
        self.assertTrue(res.ok)
        self.assertEqual(res.id, "ord1")
        self.assertEqual(len(calls), 1)


class TestLiveOrchestrator(unittest.TestCase):
    def test_run_live_once_submits_fresh_setups(self):
        candles = data.synthetic(n=2500, seed=7)
        with tempfile.TemporaryDirectory() as d:
            cfg = BotConfig(symbol="BTC", state_dir=d)
            cfg.params = Params(require_fvg=False, min_rr=2.0)
            mem = Memory(d)
            risk = RiskManager(cfg.limits)
            sim = SimVenueClient(equity=10_000.0)
            broker = LiveBroker(sim, symbol="BTC", allow_live=True)
            os.environ["BOT_ALLOW_LIVE"] = "1"
            try:
                r1 = run_live_once(cfg, broker, risk, mem, candles)
                # second call with no new bar is a no-op
                r2 = run_live_once(cfg, broker, risk, mem, candles)
                self.assertEqual(r2.skipped, "no new closed bar")
            finally:
                os.environ.pop("BOT_ALLOW_LIVE", None)
            self.assertEqual(r1.acted_on_bar, len(candles) - 1)
            # any submitted orders were actually placed at the venue
            self.assertEqual(len(sim.placed), len(r1.submitted))


class TestRoutine(unittest.TestCase):
    def test_routine_runs_and_reviews(self):
        candles = data.synthetic(n=3000, seed=5)
        sent = []

        class Spy:
            def send(self, title, message, level="info"):
                sent.append((title, level))
                return True

        with tempfile.TemporaryDirectory() as d:
            cfg = BotConfig(symbol="SYNTH", state_dir=d)
            cfg.params = Params(require_fvg=False, min_rr=2.0)
            res = run_routine(cfg, candles, notifier=Spy(), weekly_review=True)
            self.assertTrue(res.run_summary)
            self.assertIsNotNone(res.weekly_review)
            # both a run summary and a weekly review were notified
            titles = [t for t, _ in sent]
            self.assertTrue(any("run" in t for t in titles))
            self.assertTrue(any("review" in t for t in titles))


if __name__ == "__main__":
    unittest.main(verbosity=2)
