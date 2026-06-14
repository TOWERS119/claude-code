"""File-based memory for stateless agent runs.

Each invocation wakes with no memory; discipline and continuity live in files.
``state.json`` holds the cursor (last processed bar), the equity peak, the daily
counters, and the serialized broker state. ``trades.jsonl`` is an append-only
audit log of every closed trade. Writes are atomic (temp file + ``os.replace``)
so a crash mid-write can't corrupt state.
"""

from __future__ import annotations

import json
import os
import tempfile
from typing import List


class Memory:
    def __init__(self, state_dir: str) -> None:
        self.dir = state_dir
        os.makedirs(state_dir, exist_ok=True)
        self.state_path = os.path.join(state_dir, "state.json")
        self.trades_path = os.path.join(state_dir, "trades.jsonl")

    def load_state(self) -> dict:
        if not os.path.exists(self.state_path):
            return {}
        with open(self.state_path) as fh:
            return json.load(fh)

    def save_state(self, state: dict) -> None:
        self._atomic_write(self.state_path, json.dumps(state, indent=2, default=str))

    def append_trade(self, trade: dict) -> None:
        with open(self.trades_path, "a") as fh:
            fh.write(json.dumps(trade, default=str) + "\n")

    def read_trades(self) -> List[dict]:
        if not os.path.exists(self.trades_path):
            return []
        with open(self.trades_path) as fh:
            return [json.loads(line) for line in fh if line.strip()]

    def reset(self) -> None:
        for path in (self.state_path, self.trades_path):
            if os.path.exists(path):
                os.remove(path)

    def _atomic_write(self, path: str, text: str) -> None:
        d = os.path.dirname(path) or "."
        fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as fh:
                fh.write(text)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
