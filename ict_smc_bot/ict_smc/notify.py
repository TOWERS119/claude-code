"""Alerting / notifications.

A small notifier abstraction so the agent can report run summaries, fills, and
weekly reviews to wherever you watch (console, a file, or a webhook —
Slack/Telegram/ClickUp-style). The webhook transport is injectable so it can be
unit-tested without real network calls, and so swapping providers is trivial.
"""

from __future__ import annotations

import json
import logging
import urllib.request
from typing import Callable, List, Optional


# A transport takes (url, payload_bytes, headers) and returns an HTTP status code.
Transport = Callable[[str, bytes, dict], int]


def _urllib_transport(url: str, payload: bytes, headers: dict) -> int:
    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.status


class NullNotifier:
    """Default no-op sink."""

    def send(self, title: str, message: str, level: str = "info") -> bool:  # noqa: D401
        return True


class ConsoleNotifier:
    def __init__(self, logger: Optional[logging.Logger] = None) -> None:
        self.log = logger or logging.getLogger("bot.notify")

    def send(self, title: str, message: str, level: str = "info") -> bool:
        fn = {"error": self.log.error, "warn": self.log.warning}.get(level, self.log.info)
        fn("[%s] %s", title, message)
        return True


class FileNotifier:
    def __init__(self, path: str) -> None:
        self.path = path

    def send(self, title: str, message: str, level: str = "info") -> bool:
        with open(self.path, "a") as fh:
            fh.write(f"[{level}] {title}\n{message}\n\n")
        return True


class WebhookNotifier:
    """POSTs ``{"title","message","level"}`` JSON. For Slack use a different
    payload key — pass ``payload_key='text'`` and it sends ``{"text": ...}``."""

    def __init__(self, url: str, transport: Transport = _urllib_transport,
                 payload_key: Optional[str] = None) -> None:
        self.url = url
        self.transport = transport
        self.payload_key = payload_key

    def send(self, title: str, message: str, level: str = "info") -> bool:
        if self.payload_key:
            body = {self.payload_key: f"*{title}*\n{message}"}
        else:
            body = {"title": title, "message": message, "level": level}
        try:
            status = self.transport(
                self.url, json.dumps(body).encode(), {"Content-Type": "application/json"}
            )
            return 200 <= status < 300
        except Exception:  # noqa: BLE001 - notifications must never crash the run
            logging.getLogger("bot.notify").exception("notification failed")
            return False


class CompositeNotifier:
    def __init__(self, notifiers: List[object]) -> None:
        self.notifiers = notifiers

    def send(self, title: str, message: str, level: str = "info") -> bool:
        ok = True
        for n in self.notifiers:
            ok = n.send(title, message, level) and ok
        return ok


def from_env(prefix: str = "BOT_") -> object:
    """Build a notifier from the environment. Always includes console; adds a
    webhook if ``BOT_WEBHOOK_URL`` is set and a file sink if ``BOT_NOTIFY_FILE``
    is set."""
    import os

    sinks: List[object] = [ConsoleNotifier()]
    url = os.environ.get(f"{prefix}WEBHOOK_URL")
    if url:
        sinks.append(WebhookNotifier(url, payload_key=os.environ.get(f"{prefix}WEBHOOK_KEY")))
    path = os.environ.get(f"{prefix}NOTIFY_FILE")
    if path:
        sinks.append(FileNotifier(path))
    return CompositeNotifier(sinks) if len(sinks) > 1 else sinks[0]
