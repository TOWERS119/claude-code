"""Tests for the LLM provider registry (offline; no keys, no network)."""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ict_smc import providers
from ict_smc.providers import make_client, resolve, require_key, PROVIDERS
from ict_smc.glm import GlmClient


class TestProviderRegistry(unittest.TestCase):
    def test_known_providers_present(self):
        for name in ("gemini", "groq", "openrouter", "ollama", "glm", "glm-zai"):
            self.assertIn(name, PROVIDERS)

    def test_make_client_uses_preset(self):
        c = make_client("groq", api_key="k")
        self.assertIsInstance(c, GlmClient)
        self.assertEqual(c.base_url, "https://api.groq.com/openai/v1")
        self.assertEqual(c.model, "llama-3.3-70b-versatile")

    def test_overrides_apply(self):
        c = make_client("gemini", api_key="k", model="gemini-2.0-flash",
                        base_url="https://example/v1")
        self.assertEqual(c.model, "gemini-2.0-flash")
        self.assertEqual(c.base_url, "https://example/v1")

    def test_ollama_needs_no_key(self):
        # keyless provider builds without an env var and request-builds offline
        c = make_client("ollama")
        self.assertEqual(c.base_url, "http://localhost:11434/v1")
        self.assertIsNone(require_key("ollama"))

    def test_unknown_provider_raises(self):
        with self.assertRaises(ValueError):
            resolve("not-a-provider")

    def test_validate_known_and_unknown(self):
        self.assertIsNone(providers.validate("groq"))
        self.assertIsNone(providers.validate(None))   # defaults to glm
        msg = providers.validate("bogus")
        self.assertIsNotNone(msg)
        self.assertIn("unknown provider", msg)

    def test_require_key_reports_unknown_provider(self):
        # a typo'd provider yields a clean message, not a ValueError
        msg = require_key("bogus")
        self.assertIsNotNone(msg)
        self.assertIn("unknown provider", msg)

    def test_require_key_reports_missing(self):
        os.environ.pop("GROQ_API_KEY", None)
        msg = require_key("groq")
        self.assertIsNotNone(msg)
        self.assertIn("GROQ_API_KEY", msg)

    def test_require_key_passes_when_set(self):
        os.environ["GROQ_API_KEY"] = "x"
        try:
            self.assertIsNone(require_key("groq"))
        finally:
            os.environ.pop("GROQ_API_KEY", None)

    def test_make_client_request_offline(self):
        # confirm a provider client builds a correct request via a fake transport
        seen = {}

        def fake(method, url, headers, body=None):
            seen["url"] = url
            seen["auth"] = headers.get("Authorization")
            import json
            return 200, json.dumps({"choices": [{"message": {"content": "{}"}}]}).encode()

        c = make_client("openrouter", api_key="secret", http=fake)
        c.chat([{"role": "user", "content": "hi"}])
        self.assertTrue(seen["url"].startswith("https://openrouter.ai/api/v1"))
        self.assertEqual(seen["auth"], "Bearer secret")


if __name__ == "__main__":
    unittest.main(verbosity=2)
