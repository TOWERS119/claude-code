"""Tests for the GLM integration: client, JSON extraction, subtractive advisor
(capability 4), and the honest research loop (capability 3). All offline via a
fake HTTP transport or a fake client — no keys, no network."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ict_smc.types import Candle, Params
from ict_smc import data
from ict_smc.glm import GlmClient, GlmError, GlmParseError, extract_json
from ict_smc.advisor import TradeAdvisor, AdvisorAction, AdvisorVerdict
from ict_smc import research
from ict_smc.research import sanitize_proposal, run_research, ProposalResult
from ict_smc.config import BotConfig
from ict_smc.risk import RiskManager
from ict_smc.memory import Memory
from ict_smc.live import SimVenueClient, LiveBroker, run_live_once
from ict_smc.engine import run_once, build_broker


def _chat_payload(content: str) -> bytes:
    return json.dumps({"choices": [{"message": {"content": content}}],
                       "usage": {"total_tokens": 1}}).encode()


# --------------------------------------------------------------------------- #
class TestExtractJson(unittest.TestCase):
    def test_bare(self):
        self.assertEqual(extract_json('{"a": 1}'), {"a": 1})

    def test_json_fence(self):
        self.assertEqual(extract_json('```json\n{"a": 2}\n```'), {"a": 2})

    def test_plain_fence(self):
        self.assertEqual(extract_json('```\n{"a": 3}\n```'), {"a": 3})

    def test_prose_wrapped(self):
        self.assertEqual(extract_json('Sure! Here: {"a": 4} hope that helps'), {"a": 4})

    def test_array(self):
        self.assertEqual(extract_json('noise [1, 2, 3] trailing'), [1, 2, 3])

    def test_nested_braces_in_string(self):
        self.assertEqual(extract_json('{"reason": "a } b", "x": 1}'), {"reason": "a } b", "x": 1})

    def test_malformed_raises(self):
        with self.assertRaises(GlmParseError):
            extract_json("absolutely not json")


# --------------------------------------------------------------------------- #
class TestGlmClient(unittest.TestCase):
    def _client(self, status=200, body=b'{}'):
        calls = []

        def fake(method, url, headers, body_bytes=None):
            calls.append({"method": method, "url": url, "headers": headers,
                          "body": json.loads(body_bytes) if body_bytes else None})
            return status, body

        return GlmClient(http=fake, api_key="secret-key", model="glm-4.6"), calls

    def test_chat_builds_request(self):
        c, calls = self._client(body=_chat_payload('{"ok": true}'))
        resp = c.chat([{"role": "user", "content": "hi"}])
        self.assertEqual(resp.text, '{"ok": true}')
        self.assertTrue(calls[0]["url"].endswith("/chat/completions"))
        self.assertEqual(calls[0]["headers"]["Authorization"], "Bearer secret-key")
        self.assertEqual(calls[0]["body"]["model"], "glm-4.6")
        self.assertEqual(calls[0]["body"]["messages"][0]["content"], "hi")

    def test_non_2xx_raises(self):
        c, _ = self._client(status=429, body=b'{"error":"rate"}')
        with self.assertRaises(GlmError):
            c.chat([{"role": "user", "content": "x"}])

    def test_empty_body_raises(self):
        c, _ = self._client(status=200, body=b'')
        with self.assertRaises(GlmError):
            c.chat([{"role": "user", "content": "x"}])

    def test_complete_json_extracts(self):
        c, _ = self._client(body=_chat_payload('```json\n{"action":"veto"}\n```'))
        self.assertEqual(c.complete_json([{"role": "user", "content": "x"}]), {"action": "veto"})

    def test_key_never_leaks_into_response(self):
        c, _ = self._client(body=_chat_payload('{"ok":1}'))
        resp = c.chat([{"role": "user", "content": "x"}])
        self.assertNotIn("secret-key", json.dumps(resp.raw))

    def test_default_transport_honors_timeout(self):
        # when no transport is injected, the configured timeout must reach urllib_http
        seen = {}

        def fake_urllib(method, url, headers, body=None, timeout=20):
            seen["timeout"] = timeout
            return 200, _chat_payload('{"ok":1}')

        import ict_smc.glm as glm_mod
        original = glm_mod.urllib_http
        glm_mod.urllib_http = fake_urllib
        try:
            c = GlmClient(api_key="k", timeout=3)  # no http= -> uses default transport
            c.chat([{"role": "user", "content": "x"}])
        finally:
            glm_mod.urllib_http = original
        self.assertEqual(seen.get("timeout"), 3)


# --------------------------------------------------------------------------- #
class _FakeAdvisorClient:
    """A fake GlmClient whose complete_json returns a fixed object or raises."""
    def __init__(self, obj=None, raises=None):
        self.obj = obj
        self.raises = raises
        self.calls = 0

    def complete_json(self, messages, **kw):
        self.calls += 1
        if self.raises is not None:
            raise self.raises
        return self.obj


def _advisor_setup_candles():
    candles = data.synthetic(n=2500, seed=7)
    return candles


def _run_engine_with_advisor(advisor, candles, max_concurrent=99):
    d = tempfile.mkdtemp(prefix="glm_")
    cfg = BotConfig(symbol="AAPL", state_dir=d)
    cfg.params = Params(require_fvg=False, min_rr=2.0)
    cfg.limits.max_concurrent_positions = max_concurrent
    cfg.limits.max_new_trades_per_day = 99
    mem = Memory(d)
    risk = RiskManager(cfg.limits)
    broker = build_broker(cfg, mem)
    report = run_once(cfg, broker, risk, mem, candles, advisor=advisor)
    return report


class TestTradeAdvisorVerdict(unittest.TestCase):
    def test_size_factor_clamped_on_construction(self):
        self.assertEqual(AdvisorVerdict(AdvisorAction.DOWNSIZE, 2.0).size_factor, 1.0)
        self.assertEqual(AdvisorVerdict(AdvisorAction.DOWNSIZE, -1).size_factor, 0.0)
        self.assertEqual(AdvisorVerdict(AdvisorAction.DOWNSIZE, float("nan")).size_factor, 1.0)

    def test_apply(self):
        self.assertEqual(TradeAdvisor.apply(100.0, AdvisorVerdict(AdvisorAction.VETO, 0.5)), 0.0)
        self.assertEqual(TradeAdvisor.apply(100.0, AdvisorVerdict(AdvisorAction.DOWNSIZE, 0.25)), 25.0)
        self.assertEqual(TradeAdvisor.apply(100.0, AdvisorVerdict(AdvisorAction.ALLOW, 2.0)), 100.0)

    def test_disabled_is_noop(self):
        adv = TradeAdvisor(_FakeAdvisorClient({"action": "veto"}), enabled=False)
        v = adv.review(setup=_DummySetup(), symbol="X", equity=1000,
                       recent_candles=[], open_positions=0, daily_pnl=0)
        self.assertEqual(v.action, AdvisorAction.ALLOW)


class _DummySetup:
    direction = "long"; entry = 100.0; stop = 95.0; target = 110.0
    entry_source = "fvg"
    @property
    def rr(self):
        return 2.0


class TestAdvisorInEngine(unittest.TestCase):
    def setUp(self):
        self.candles = _advisor_setup_candles()

    def test_baseline_no_advisor_submits(self):
        rep = _run_engine_with_advisor(None, self.candles)
        self.assertGreater(len(rep.submitted), 0)

    def test_veto_blocks_all_orders(self):
        adv = TradeAdvisor(_FakeAdvisorClient({"action": "veto", "reason": "no"}),
                           enabled=True)
        rep = _run_engine_with_advisor(adv, self.candles)
        self.assertEqual(len(rep.submitted), 0)

    def test_downsize_keeps_same_setups(self):
        # downsizing must not change WHICH setups trade, only their size (the
        # exact qty scaling is asserted at the venue in TestAdvisorDownsizeQtyLive)
        base = _run_engine_with_advisor(None, self.candles)
        adv = TradeAdvisor(_FakeAdvisorClient({"action": "downsize", "size_factor": 0.25}),
                           enabled=True)
        downsized = _run_engine_with_advisor(adv, self.candles)
        self.assertEqual(len(downsized.submitted), len(base.submitted))

    def test_upsize_attempt_is_clamped(self):
        base = _run_engine_with_advisor(None, self.candles)
        adv = TradeAdvisor(_FakeAdvisorClient({"action": "downsize", "size_factor": 5.0}),
                           enabled=True)
        rep = _run_engine_with_advisor(adv, self.candles)
        self.assertEqual(len(rep.submitted), len(base.submitted))  # 5.0 -> 1.0, same as baseline

    def test_fail_closed_blocks(self):
        adv = TradeAdvisor(_FakeAdvisorClient(raises=RuntimeError("boom")),
                           enabled=True, fail_mode="closed")
        rep = _run_engine_with_advisor(adv, self.candles)
        self.assertEqual(len(rep.submitted), 0)

    def test_fail_open_passes_through(self):
        base = _run_engine_with_advisor(None, self.candles)
        adv = TradeAdvisor(_FakeAdvisorClient(raises=RuntimeError("boom")),
                           enabled=True, fail_mode="open")
        rep = _run_engine_with_advisor(adv, self.candles)
        self.assertEqual(len(rep.submitted), len(base.submitted))

    def test_advisor_never_raises(self):
        adv = TradeAdvisor(_FakeAdvisorClient(raises=ValueError("bad")),
                           enabled=True, fail_mode="closed")
        # should complete normally despite the client raising every call
        rep = _run_engine_with_advisor(adv, self.candles)
        self.assertIsNotNone(rep)


class TestAdvisorDownsizeQtyLive(unittest.TestCase):
    """Verify the downsize factor actually scales the order qty at the venue."""
    def setUp(self):
        os.environ["BOT_ALLOW_LIVE"] = "1"
        from ict_smc.strategy import generate_setups
        full = data.from_csv(os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "findings", "data", "BTC-USD_1h.csv"))
        # run_live_once acts only on the LAST bar, so truncate the series to end
        # exactly where a setup is armed (guarantees the baseline places an order)
        setups, _ = generate_setups(full, Params(require_fvg=False, min_rr=2.0))
        self.assertTrue(setups, "fixture data must produce at least one setup")
        cut = setups[-1].armed_at
        self.candles = full[:cut + 1]

    def tearDown(self):
        os.environ.pop("BOT_ALLOW_LIVE", None)

    def _placed_qty(self, advisor):
        d = tempfile.mkdtemp(prefix="glm_live_")
        cfg = BotConfig(symbol="AAPL", state_dir=d)
        cfg.params = Params(require_fvg=False, min_rr=2.0)
        mem = Memory(d)
        risk = RiskManager(cfg.limits)
        sim = SimVenueClient(equity=10_000.0)
        broker = LiveBroker(sim, symbol="AAPL", allow_live=True)
        run_live_once(cfg, broker, risk, mem, self.candles, advisor=advisor)
        return sim.placed

    def test_downsize_scales_qty(self):
        base = self._placed_qty(None)
        adv = TradeAdvisor(_FakeAdvisorClient({"action": "downsize", "size_factor": 0.5}),
                           enabled=True)
        half = self._placed_qty(adv)
        self.assertTrue(base, "baseline should place an order on the latest bar")
        self.assertEqual(len(half), len(base))
        for b, h in zip(base, half):
            self.assertAlmostEqual(h["qty"], b["qty"] * 0.5, places=8)


# --------------------------------------------------------------------------- #
class TestSanitizeProposal(unittest.TestCase):
    def test_drops_unknown_keys(self):
        self.assertEqual(sanitize_proposal({"not_a_field": 1, "min_rr": 2.0}), {"min_rr": 2.0})

    def test_clamps_numeric(self):
        self.assertEqual(sanitize_proposal({"min_rr": 99})["min_rr"], 5.0)
        self.assertEqual(sanitize_proposal({"swing_lookback": 0})["swing_lookback"], 1)

    def test_bad_enum_skipped(self):
        self.assertIsNone(sanitize_proposal({"entry_level": "banana"}))
        self.assertEqual(sanitize_proposal({"entry_level": "deep"}), {"entry_level": "deep"})

    def test_cost_field_cannot_be_set(self):
        # commission/slippage/equity are NOT in the whitelist -> dropped
        self.assertIsNone(sanitize_proposal({"commission_bps": 0, "slippage_bps": 0}))

    def test_non_dict_is_none(self):
        self.assertIsNone(sanitize_proposal([1, 2, 3]))
        self.assertIsNone(sanitize_proposal("nope"))

    def test_no_exec_in_module(self):
        import inspect
        src = inspect.getsource(research)
        for forbidden in ("exec(", "eval(", "compile("):
            self.assertNotIn(forbidden, src)


class _FakeResearchClient:
    """Returns a queued list of proposal-batches, one per complete_json call."""
    def __init__(self, batches):
        self.batches = list(batches)
        self.calls = 0

    def complete_json(self, messages, **kw):
        self.calls += 1
        if not self.batches:
            return {"proposals": []}
        return {"proposals": self.batches.pop(0)}


class TestResearchLoop(unittest.TestCase):
    def setUp(self):
        self.candles = data.synthetic(n=3000, seed=7)

    def test_flags_sub_noise_floor_and_ranks(self):
        # two proposals: base-ish and a tweaked one; on random data neither has edge
        client = _FakeResearchClient([
            [{"min_rr": 2.0}, {"min_rr": 1.5, "entry_level": "deep"}],
        ])
        report = run_research(client, self.candles,
                              base_params=Params(require_fvg=False, min_rr=2.0),
                              n_rounds=1, batch_size=2, n_folds=3, min_oos_trades=5)
        self.assertGreater(len(report.ranked), 0)
        for r in report.ranked:
            self.assertEqual(r.noise_floor, report.noise_floor)
            # honesty invariant: nothing with margin<=0 is marked as passing
            if r.margin <= 0:
                self.assertFalse(r.passes_noise_floor)
                self.assertTrue(r.sub_noise_floor)

    def test_bad_round_is_robust(self):
        client = _FakeResearchClient([["not a dict", {"min_rr": 2.0}]])
        report = run_research(client, self.candles,
                              base_params=Params(require_fvg=False),
                              n_rounds=1, batch_size=2, n_folds=3, min_oos_trades=5)
        # the unusable proposal is recorded with an error, the loop still finishes
        self.assertTrue(any(r.error for r in report.ranked))
        self.assertEqual(report.rounds, 1)

    def test_ranking_passes_first(self):
        results = [
            ProposalResult({}, -0.1, 0.9, 20, -0.2, 0.1, False, True),
            ProposalResult({}, 0.3, 1.4, 30, -0.2, 0.5, True, False),
        ]
        ranked = sorted(results, key=lambda r: (r.passes_noise_floor, r.oos_expectancy_r,
                                                r.oos_num_trades), reverse=True)
        self.assertTrue(ranked[0].passes_noise_floor)


if __name__ == "__main__":
    unittest.main(verbosity=2)
