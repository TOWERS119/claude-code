"""LLM provider registry — run the GLM features on free, OpenAI-compatible models.

The user's GLM account may have no balance; every provider here speaks the same
OpenAI chat-completions protocol, so they all reuse :class:`GlmClient` and flow
through the *same* subtractive/fail-closed advisor and the same walk-forward
validation rig. Picking a different or free model only changes which endpoint
answers — it can never create edge or place a real order.

Pick a provider with ``--provider <name>`` or ``BOT_LLM_PROVIDER=<name>``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, List, Optional

from .glm import GlmClient
from .http import HttpFn


@dataclass(frozen=True)
class Provider:
    name: str
    base_url: str
    key_name: str            # env var holding the API key ("" when none needed)
    default_model: str
    signup_url: str = ""
    needs_key: bool = True
    free: bool = False


PROVIDERS: Dict[str, Provider] = {
    # --- free, no-credit-card, OpenAI-compatible competitors ---
    "gemini": Provider(
        "gemini", "https://generativelanguage.googleapis.com/v1beta/openai",
        "GEMINI_API_KEY", "gemini-2.5-flash",
        "https://aistudio.google.com/app/apikey", free=True),
    "groq": Provider(
        "groq", "https://api.groq.com/openai/v1", "GROQ_API_KEY",
        "llama-3.3-70b-versatile", "https://console.groq.com/keys", free=True),
    "openrouter": Provider(
        "openrouter", "https://openrouter.ai/api/v1", "OPENROUTER_API_KEY",
        "deepseek/deepseek-r1:free", "https://openrouter.ai/keys", free=True),
    # --- fully local, no key, nothing leaves your machine ---
    "ollama": Provider(
        "ollama", "http://localhost:11434/v1", "", "llama3.1",
        "https://ollama.com", needs_key=False, free=True),
    # --- the original GLM provider (pay-per-use) ---
    "glm": Provider(
        "glm", GlmClient.DEFAULT_BASE_URL, "GLM_API_KEY", "glm-4.6",
        "https://open.bigmodel.cn"),
    "glm-zai": Provider(
        "glm-zai", GlmClient.ZAI_BASE_URL, "GLM_API_KEY", "glm-4.6",
        "https://z.ai"),
}


def resolve(name: Optional[str]) -> Provider:
    key = (name or "glm").lower()
    if key not in PROVIDERS:
        raise ValueError(f"unknown provider {name!r}; choose from {sorted(PROVIDERS)}")
    return PROVIDERS[key]


def list_providers() -> List[Provider]:
    return list(PROVIDERS.values())


def validate(provider: Optional[str]) -> Optional[str]:
    """Return None if ``provider`` is a known name, else a clean error message.
    Used by the CLIs because argparse only validates ``choices`` for values passed
    on the command line, not for env-var-sourced defaults (BOT_LLM_PROVIDER)."""
    if (provider or "glm").lower() not in PROVIDERS:
        return f"unknown provider {provider!r}; choose from {sorted(PROVIDERS)}"
    return None


def make_client(provider: str = "glm", *, model: Optional[str] = None,
                base_url: Optional[str] = None, api_key: Optional[str] = None,
                http: Optional[HttpFn] = None, timeout: int = 20) -> GlmClient:
    """Build a generic OpenAI-compatible client for the named provider, with
    optional per-call overrides for model/base_url."""
    p = resolve(provider)
    if api_key is None and not p.needs_key:
        api_key = "none"  # keyless providers (ollama) skip the env lookup
    return GlmClient(
        base_url=base_url or p.base_url,
        model=model or p.default_model,
        api_key=api_key,
        key_name=p.key_name or "UNUSED",
        http=http,
        timeout=timeout,
    )


def require_key(provider: str) -> Optional[str]:
    """Return None if the provider is ready, else a user-facing error message
    (unknown provider, or the missing env var and where to get a free key)."""
    unknown = validate(provider)
    if unknown:
        return unknown
    p = resolve(provider)
    if not p.needs_key:
        return None
    if not os.environ.get(p.key_name):
        return (f"refusing: set {p.key_name} in the environment for provider "
                f"'{p.name}' (get a free key at {p.signup_url}). Never put it in the repo.")
    return None
