"""Pre-trade risk controls — the layer the knowledge base insists matters more
than the strategy itself.

The :class:`RiskManager` is the single chokepoint every proposed trade must pass
through. It enforces, in order: kill-switch (max drawdown), daily loss circuit
breaker, instrument whitelist, max concurrent positions, max new trades per day,
minimum reward:risk, fractional position sizing, and a hard notional cap. Sizing
is *reduced* (never increased) to satisfy the notional cap, so the cap can only
make a position safer.

Nothing here trusts the strategy: a setup is a *request*, not an order.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Sequence, Tuple


@dataclass
class RiskLimits:
    """All risk knobs. Defaults are deliberately conservative."""

    risk_pct: float = 0.01                 # fraction of equity risked per trade
    max_concurrent_positions: int = 1
    max_new_trades_per_day: int = 3
    max_daily_loss_pct: float = 0.03       # daily circuit breaker
    max_drawdown_pct: float = 0.15         # account kill-switch
    max_position_notional_pct: float = 0.25  # hard cap on a single position size
    min_rr: float = 2.0
    instrument_whitelist: Tuple[str, ...] = ()  # empty tuple = allow any symbol


@dataclass
class RiskDecision:
    approved: bool
    reason: str
    qty: float = 0.0


class RiskManager:
    def __init__(self, limits: RiskLimits) -> None:
        self.limits = limits

    # --- account-level halts ---------------------------------------------- #
    def kill_switch_active(self, equity: float, peak_equity: float) -> bool:
        """True once drawdown from the equity peak breaches the hard limit."""
        if peak_equity <= 0:
            return False
        return (peak_equity - equity) / peak_equity >= self.limits.max_drawdown_pct

    def daily_breaker_active(self, daily_pnl: float, day_start_equity: float) -> bool:
        """True once the day's realized loss breaches the circuit breaker."""
        if day_start_equity <= 0:
            return False
        return daily_pnl <= -self.limits.max_daily_loss_pct * day_start_equity

    # --- per-trade gate --------------------------------------------------- #
    def evaluate(
        self,
        *,
        symbol: str,
        side: str,
        entry: float,
        stop: float,
        target: float,
        equity: float,
        peak_equity: float,
        open_positions: Sequence[object],
        trades_today: int,
        daily_pnl: float,
        day_start_equity: float,
    ) -> RiskDecision:
        lim = self.limits
        if self.kill_switch_active(equity, peak_equity):
            return RiskDecision(False, "kill-switch: max drawdown breached")
        if self.daily_breaker_active(daily_pnl, day_start_equity):
            return RiskDecision(False, "daily loss circuit breaker tripped")
        if lim.instrument_whitelist and symbol not in lim.instrument_whitelist:
            return RiskDecision(False, f"symbol {symbol!r} not in whitelist")
        if len(open_positions) >= lim.max_concurrent_positions:
            return RiskDecision(False, "max concurrent positions reached")
        if trades_today >= lim.max_new_trades_per_day:
            return RiskDecision(False, "max new trades per day reached")

        risk_per_unit = abs(entry - stop)
        if risk_per_unit <= 0:
            return RiskDecision(False, "invalid stop (zero risk distance)")
        rr = abs(target - entry) / risk_per_unit
        if rr < lim.min_rr - 1e-9:
            return RiskDecision(False, f"reward:risk {rr:.2f} below min {lim.min_rr}")

        risk_cash = equity * lim.risk_pct
        qty = risk_cash / risk_per_unit
        notional = qty * entry
        max_notional = equity * lim.max_position_notional_pct
        reason = "approved"
        if notional > max_notional:
            qty = max_notional / entry  # shrink size -> real risk drops below target
            reason = "approved (size capped by notional limit)"
        if qty <= 0:
            return RiskDecision(False, "computed size is zero")
        return RiskDecision(True, reason, qty)
