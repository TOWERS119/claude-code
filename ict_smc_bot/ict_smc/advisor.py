"""GLM trade advisor — capability (4), strictly subtractive and fail-closed.

A ``TradeAdvisor`` reviews a setup the deterministic strategy already produced
and returns a verdict that can only *reduce* exposure: VETO (skip) or DOWNSIZE
(multiply the RiskManager-approved quantity by a factor in [0, 1]). It can never
create a trade, increase size, or relax a RiskManager limit — it runs *around*
the RiskManager, which remains the sole final authority.

By construction:
* ``size_factor`` is clamped to [0, 1] on verdict creation, so an upsize is
  structurally impossible (a malformed "2.0" becomes 1.0).
* any GLM error/timeout/garbage is wrapped (never raised into the run loop) and
  resolved per ``fail_mode``: "closed" (default) vetoes the trade; "open" passes
  through to the RiskManager unchanged (advice-only, still risk-gated).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Sequence

from .types import Candle, Setup


class AdvisorAction(str, Enum):
    ALLOW = "allow"
    DOWNSIZE = "downsize"
    VETO = "veto"


def _clamp01(x: object) -> float:
    try:
        f = float(x)
    except (TypeError, ValueError):
        return 1.0
    if f != f:  # NaN
        return 1.0
    return max(0.0, min(1.0, f))


@dataclass
class AdvisorVerdict:
    action: AdvisorAction
    size_factor: float = 1.0
    reason: str = ""
    failed: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.action, AdvisorAction):
            try:
                self.action = AdvisorAction(str(self.action).lower())
            except ValueError:
                self.action = AdvisorAction.ALLOW
        self.size_factor = _clamp01(self.size_factor)


class TradeAdvisor:
    def __init__(self, client, *, enabled: bool = False, fail_mode: str = "closed",
                 min_size_factor: float = 0.0, recent_bars: int = 50) -> None:
        self.client = client
        self.enabled = enabled
        self.fail_mode = fail_mode if fail_mode in ("closed", "open") else "closed"
        self.min_size_factor = _clamp01(min_size_factor)
        self.recent_bars = recent_bars

    # --- the review --------------------------------------------------------- #
    def review(self, *, setup: Setup, symbol: str, equity: float,
               recent_candles: Sequence[Candle], open_positions: int,
               daily_pnl: float) -> AdvisorVerdict:
        if not self.enabled or self.client is None:
            return AdvisorVerdict(AdvisorAction.ALLOW, 1.0, "advisor disabled")
        try:
            messages = self._build_messages(setup, symbol, equity, recent_candles,
                                             open_positions, daily_pnl)
            obj = self.client.complete_json(messages)
            if not isinstance(obj, dict):
                raise ValueError("advisor reply was not a JSON object")
            action = str(obj.get("action", "allow")).lower()
            if action not in (a.value for a in AdvisorAction):
                action = "allow"
            verdict = AdvisorVerdict(
                action=AdvisorAction(action),
                size_factor=obj.get("size_factor", 1.0),
                reason=str(obj.get("reason", ""))[:200],
            )
            # apply the operator's floor on downsizing (never below it unless veto)
            if verdict.action != AdvisorAction.VETO and verdict.size_factor < self.min_size_factor:
                verdict.size_factor = self.min_size_factor
            return verdict
        except Exception as e:  # noqa: BLE001 - the advisor must never crash the run
            return self._on_failure(repr(e))

    def _on_failure(self, reason: str) -> AdvisorVerdict:
        if self.fail_mode == "open":
            return AdvisorVerdict(AdvisorAction.ALLOW, 1.0,
                                  f"advisor unavailable, pass-through: {reason}", failed=True)
        return AdvisorVerdict(AdvisorAction.VETO, 0.0,
                              f"advisor unavailable, fail-closed: {reason}", failed=True)

    def _build_messages(self, setup: Setup, symbol: str, equity: float,
                        recent_candles: Sequence[Candle], open_positions: int,
                        daily_pnl: float) -> List[dict]:
        window = list(recent_candles)[-self.recent_bars:]
        ohlc = ", ".join(f"{c.close:.2f}" for c in window[-20:])
        rr = setup.rr
        user = (
            f"Symbol: {symbol}\n"
            f"Proposed setup: {setup.direction} | entry={setup.entry:.4f} "
            f"stop={setup.stop:.4f} target={setup.target:.4f} reward:risk={rr:.2f} "
            f"source={setup.entry_source}\n"
            f"Account: equity={equity:.2f} open_positions={open_positions} "
            f"daily_pnl={daily_pnl:.2f}\n"
            f"Recent closes (oldest->newest): {ohlc}\n\n"
            'Decide whether to ALLOW, DOWNSIZE, or VETO this trade. You may only '
            'reduce risk: you cannot enlarge the position or create a trade. '
            'Respond ONLY with JSON: '
            '{"action":"allow|downsize|veto","size_factor":0.0-1.0,"reason":"short"}'
        )
        return [
            {"role": "system", "content":
                "You are a conservative risk reviewer for an automated trading agent. "
                "The deterministic strategy already proposed this trade and a separate "
                "risk manager already sized it. Your only power is to veto or shrink it."},
            {"role": "user", "content": user},
        ]

    # --- sizing applied at the call site ----------------------------------- #
    @staticmethod
    def apply(decision_qty: float, verdict: AdvisorVerdict) -> float:
        if verdict.action == AdvisorAction.VETO:
            return 0.0
        return decision_qty * _clamp01(verdict.size_factor)
