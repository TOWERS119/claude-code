"""Offline smoke tests for quickstart.py (fake GLM client, --csv, no network)."""

from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import quickstart

DATA = os.path.join(ROOT, "findings", "data", "BTC-USD_1h.csv")


class _FakeResearchClient:
    def complete_json(self, messages, **kw):
        return {"proposals": [{"min_rr": 2.0}, {"min_rr": 1.5, "entry_level": "deep"}]}


class _FakeAdvisorClient:
    def __init__(self, obj):
        self.obj = obj
        self.calls = 0

    def complete_json(self, messages, **kw):
        self.calls += 1
        return self.obj


class TestQuickstart(unittest.TestCase):
    def setUp(self):
        self._orig_factory = quickstart._CLIENT_FACTORY
        os.environ["GLM_API_KEY"] = "test-key"

    def tearDown(self):
        quickstart._CLIENT_FACTORY = self._orig_factory
        os.environ.pop("GLM_API_KEY", None)

    def test_research_runs_offline(self):
        quickstart._CLIENT_FACTORY = lambda *, model: _FakeResearchClient()
        rc = quickstart.main(["research", "--csv", DATA, "--rounds", "1",
                              "--batch", "2", "--n-folds", "3"])
        self.assertEqual(rc, 0)

    def test_advisor_runs_offline_veto(self):
        quickstart._CLIENT_FACTORY = lambda *, model: _FakeAdvisorClient({"action": "veto"})
        rc = quickstart.main(["advisor", "--csv", DATA])
        self.assertEqual(rc, 0)

    def test_advisor_runs_offline_downsize(self):
        quickstart._CLIENT_FACTORY = lambda *, model: _FakeAdvisorClient(
            {"action": "downsize", "size_factor": 0.5})
        rc = quickstart.main(["advisor", "--csv", DATA])
        self.assertEqual(rc, 0)

    def test_refuses_without_key(self):
        os.environ.pop("GLM_API_KEY", None)
        # must refuse before constructing a client or touching the network
        quickstart._CLIENT_FACTORY = lambda *, model: (_ for _ in ()).throw(
            AssertionError("client must not be built without a key"))
        self.assertEqual(quickstart.main(["research", "--csv", DATA]), 2)
        self.assertEqual(quickstart.main(["advisor", "--csv", DATA]), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
