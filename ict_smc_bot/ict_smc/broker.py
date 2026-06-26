"""Execution layer: a broker interface plus a deterministic paper broker.

The paper broker processes the market one bar at a time (``on_bar``), which is
what makes it usable in a *live, stateless* run: each agent invocation feeds the
new bars, the broker resolves pending orders and open positions, and its full
state serializes to JSON so the next invocation resumes exactly where it left
off.

Conventions (kept identical to ``backtest.py`` so paper == backtest semantics):
* bracket orders carry their own stop and target;
* adverse slippage and per-side commission are applied to every fill;
* if a single bar trades through both stop and target, the **stop** wins.

``LiveBroker`` is a deliberate stub: real order routing must be wired to a
specific venue with keys pulled from the environment, and is gated behind an
explicit opt-in (see ``config.py``). It is not implemented here so that nothing
in the repo can place a real order by accident.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Tuple

from .types import Candle


@dataclass
class BracketOrder:
    id: str
    symbol: str
    side: str            # "long" | "short"
    qty: float
    entry: float         # limit price
    stop: float
    target: float
    armed_index: int     # bar the setup was armed on; live from the next bar
    expires_index: int   # cancel if unfilled by this bar
    max_hold: int        # bars to hold once filled before a timeout exit
    status: str = "pending"  # pending | filled | cancelled | expired


@dataclass
class Position:
    order_id: str
    symbol: str
    side: str
    qty: float
    entry_index: int
    entry_price: float       # effective (post-slippage) fill
    stop: float
    target: float
    risk_per_unit: float
    entry_commission: float
    max_hold_index: int


@dataclass
class ClosedTrade:
    order_id: str
    symbol: str
    side: str
    qty: float
    entry_index: int
    entry_price: float
    exit_index: int
    exit_price: float
    outcome: str             # target | stop | timeout
    pnl: float
    r_multiple: float


class PaperBroker:
    def __init__(
        self,
        starting_equity: float = 10_000.0,
        slippage_bps: float = 1.0,
        commission_bps: float = 2.0,
    ) -> None:
        self.starting_equity = starting_equity
        self.cash = starting_equity  # realized equity
        self.slip = slippage_bps / 10_000.0
        self.comm = commission_bps / 10_000.0
        self.pending: Dict[str, BracketOrder] = {}
        self.positions: Dict[str, Position] = {}
        self._seq = 0

    # --- queries ---------------------------------------------------------- #
    def get_equity(self) -> float:
        """Realized equity (closed PnL). Open positions are marked only on exit;
        risk sizing uses this conservative realized figure."""
        return self.cash

    def get_positions(self) -> List[Position]:
        return list(self.positions.values())

    def get_pending(self) -> List[BracketOrder]:
        return list(self.pending.values())

    # --- order management ------------------------------------------------- #
    def submit_bracket(
        self, symbol: str, side: str, qty: float, entry: float, stop: float,
        target: float, armed_index: int, ttl: int, max_hold: int,
    ) -> BracketOrder:
        self._seq += 1
        oid = f"ord-{self._seq}"
        order = BracketOrder(
            id=oid, symbol=symbol, side=side, qty=qty, entry=entry, stop=stop,
            target=target, armed_index=armed_index,
            expires_index=armed_index + ttl, max_hold=max_hold,
        )
        self.pending[oid] = order
        return order

    def cancel(self, order_id: str) -> None:
        o = self.pending.pop(order_id, None)
        if o:
            o.status = "cancelled"

    def cancel_all_pending(self) -> None:
        for o in self.pending.values():
            o.status = "cancelled"
        self.pending.clear()

    def flatten(self, idx: int, candle: Candle) -> List[ClosedTrade]:
        """Force-close every open position at the current close (used by the
        kill-switch). Pending orders are cancelled too."""
        self.cancel_all_pending()
        closed: List[ClosedTrade] = []
        for oid, pos in list(self.positions.items()):
            ct = self._exit(pos, idx, candle.close, "flatten")
            closed.append(ct)
            del self.positions[oid]
        return closed

    # --- the per-bar engine ---------------------------------------------- #
    def on_bar(self, idx: int, candle: Candle) -> Tuple[List[Position], List[ClosedTrade]]:
        """Advance one bar. Returns (new fills, closed trades)."""
        closed: List[ClosedTrade] = []
        fills: List[Position] = []

        # 1) resolve existing positions against this bar
        for oid, pos in list(self.positions.items()):
            ct = self._try_close(pos, idx, candle)
            if ct:
                closed.append(ct)
                del self.positions[oid]

        # 2) work pending orders
        for oid, o in list(self.pending.items()):
            if idx > o.expires_index:
                o.status = "expired"
                del self.pending[oid]
                continue
            if idx <= o.armed_index:  # not live on its own arming bar
                continue
            long = o.side == "long"
            touched = (candle.low <= o.entry) if long else (candle.high >= o.entry)
            if not touched:
                continue
            sign = 1 if long else -1
            fill_px = o.entry * (1 + sign * self.slip)
            entry_comm = fill_px * o.qty * self.comm
            self.cash -= entry_comm
            pos = Position(
                order_id=oid, symbol=o.symbol, side=o.side, qty=o.qty,
                entry_index=idx, entry_price=fill_px, stop=o.stop, target=o.target,
                risk_per_unit=abs(fill_px - o.stop), entry_commission=entry_comm,
                max_hold_index=idx + o.max_hold,
            )
            o.status = "filled"
            del self.pending[oid]
            self.positions[oid] = pos
            fills.append(pos)
            # conservative same-bar SL/TP check
            ct = self._try_close(pos, idx, candle)
            if ct:
                closed.append(ct)
                del self.positions[oid]

        return fills, closed

    # --- internals -------------------------------------------------------- #
    def _try_close(self, pos: Position, idx: int, candle: Candle) -> Optional[ClosedTrade]:
        long = pos.side == "long"
        if long:
            hit_stop, hit_tgt = candle.low <= pos.stop, candle.high >= pos.target
        else:
            hit_stop, hit_tgt = candle.high >= pos.stop, candle.low <= pos.target
        if hit_stop:
            return self._exit(pos, idx, pos.stop, "stop")
        if hit_tgt:
            return self._exit(pos, idx, pos.target, "target")
        if idx >= pos.max_hold_index:
            return self._exit(pos, idx, candle.close, "timeout")
        return None

    def _exit(self, pos: Position, idx: int, exit_px: float, outcome: str) -> ClosedTrade:
        sign = 1 if pos.side == "long" else -1
        exit_eff = exit_px * (1 - sign * self.slip)
        gross = (exit_eff - pos.entry_price) * sign * pos.qty
        exit_comm = exit_eff * pos.qty * self.comm
        self.cash += gross - exit_comm
        pnl = gross - pos.entry_commission - exit_comm
        risk_cash = pos.risk_per_unit * pos.qty
        r_multiple = pnl / risk_cash if risk_cash > 0 else 0.0
        return ClosedTrade(
            order_id=pos.order_id, symbol=pos.symbol, side=pos.side, qty=pos.qty,
            entry_index=pos.entry_index, entry_price=pos.entry_price,
            exit_index=idx, exit_price=exit_eff, outcome=outcome,
            pnl=pnl, r_multiple=r_multiple,
        )

    # --- persistence (stateless-run support) ------------------------------ #
    def to_dict(self) -> dict:
        return {
            "starting_equity": self.starting_equity,
            "cash": self.cash,
            "slip": self.slip,
            "comm": self.comm,
            "seq": self._seq,
            "pending": [asdict(o) for o in self.pending.values()],
            "positions": [asdict(p) for p in self.positions.values()],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PaperBroker":
        b = cls(starting_equity=d["starting_equity"])
        b.cash = d["cash"]
        b.slip = d["slip"]
        b.comm = d["comm"]
        b._seq = d.get("seq", 0)
        b.pending = {o["id"]: BracketOrder(**o) for o in d.get("pending", [])}
        b.positions = {p["order_id"]: Position(**p) for p in d.get("positions", [])}
        return b


class LiveBroker:
    """Intentionally unimplemented. Wire a venue (Alpaca/ccxt) here, pull keys
    via ``config.get_secret`` from the environment, and require an explicit
    live opt-in before any method places an order."""

    def __init__(self, *_, **__) -> None:
        raise NotImplementedError(
            "Live trading is not implemented. Build this against your venue's SDK, "
            "load credentials from environment variables only, and gate it behind "
            "an explicit live confirmation. Never commit keys to the repo."
        )
