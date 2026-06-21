"""GLM (Zhipu AI) chat client — the shared transport for both GLM capabilities.

Mirrors the ``AlpacaClient`` pattern: an injectable HTTP transport (so it's
unit-tested with no network and no keys), credentials read lazily from the
environment via ``get_secret`` and never logged, and a thin OpenAI-compatible
chat-completions wrapper. The "latest version" is selected purely by the
``model`` id (default ``glm-4.6``, overridable), so no code change is needed to
move to a newer GLM.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import List, Optional

from .config import get_secret
from .http import HttpFn, urllib_http


class GlmError(RuntimeError):
    """Transport/HTTP failure talking to GLM."""


class GlmParseError(GlmError):
    """A response arrived but no JSON could be extracted from it."""


@dataclass
class GlmResponse:
    text: str                       # choices[0].message.content
    raw: dict = field(default_factory=dict)
    usage: dict = field(default_factory=dict)


def extract_json(text: str) -> object:
    """Best-effort JSON extraction from an LLM reply.

    Tries, in order: the whole string; a fenced ```json / ``` block; the first
    balanced {...} or [...] substring (respecting string literals). Raises
    ``GlmParseError`` if nothing parses.
    """
    if text is None:
        raise GlmParseError("empty response")
    s = text.strip()
    # 1) whole string
    try:
        return json.loads(s)
    except ValueError:
        pass
    # 2) fenced code block
    if "```" in s:
        block = s.split("```", 2)
        if len(block) >= 2:
            inner = block[1]
            if inner.lower().startswith("json"):
                inner = inner[4:]
            inner = inner.strip("`").strip()
            try:
                return json.loads(inner)
            except ValueError:
                pass
    # 3) first balanced {...} or [...] honoring strings/escapes
    for open_ch, close_ch in (("{", "}"), ("[", "]")):
        start = s.find(open_ch)
        if start == -1:
            continue
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(s)):
            c = s[i]
            if in_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
            else:
                if c == '"':
                    in_str = True
                elif c == open_ch:
                    depth += 1
                elif c == close_ch:
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(s[start:i + 1])
                        except ValueError:
                            break
    raise GlmParseError(f"no JSON found in response: {s[:160]!r}")


class GlmClient:
    DEFAULT_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"  # Zhipu (China)
    ZAI_BASE_URL = "https://api.z.ai/api/paas/v4"              # z.ai (international)

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        model: str = "glm-4.6",
        http: Optional[HttpFn] = None,
        api_key: Optional[str] = None,
        key_name: str = "GLM_API_KEY",
        timeout: int = 20,
        temperature: float = 0.4,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        # bind the configured timeout into the default transport while keeping the
        # 4-arg HttpFn contract (injected fakes provide their own transport)
        self.http = http or (lambda m, u, h, b=None: urllib_http(m, u, h, b, timeout=timeout))
        self._api_key = api_key
        self.key_name = key_name
        self.timeout = timeout
        self.temperature = temperature

    def _headers(self) -> dict:
        key = self._api_key or get_secret(self.key_name)
        return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    def chat(self, messages: List[dict], *, temperature: Optional[float] = None,
             json_mode: bool = True) -> GlmResponse:
        body = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature if temperature is None else temperature,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        status, raw = self.http(
            "POST", self.base_url + "/chat/completions", self._headers(),
            json.dumps(body).encode(),
        )
        if not 200 <= status < 300:
            raise GlmError(f"GLM chat -> {status}: {raw[:300]!r}")
        if not raw:
            raise GlmError("GLM returned an empty body")
        try:
            decoded = json.loads(raw)
        except ValueError as e:
            raise GlmError(f"GLM body was not JSON: {raw[:200]!r}") from e
        try:
            text = decoded["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            raise GlmError(f"unexpected GLM response shape: {str(decoded)[:200]!r}") from e
        return GlmResponse(text=text, raw=decoded, usage=decoded.get("usage", {}) or {})

    def complete_json(self, messages: List[dict], *, temperature: Optional[float] = None) -> object:
        resp = self.chat(messages, temperature=temperature, json_mode=True)
        return extract_json(resp.text)
