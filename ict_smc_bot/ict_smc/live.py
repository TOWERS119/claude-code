"""Live execution architecture — safe by default.

Live and paper trading have genuinely different execution models: the paper
broker *simulates* fills bar-by-bar, while a live venue holds real positions and
fills asynchronously between scheduled runs. So the live path has its own thin
orchestrator (:func:`run_live_once`) that acts only on the latest closed bar and
delegates fill/stop management to the venue.

Safety is layered and fail-closed:

* ``LiveBroker`` refuses to place any order unless it was constructed with
  ``allow_live=True`` **and** the environment has ``BOT_ALLOW_LIVE=1`` — two
  independent switches, so neither a stray config nor a stray env var alone can
  arm live trading.
* a hard per-order notional cap is enforced *inside* the broker, below the
  ``RiskManager`` (defence in depth).
* the venue HTTP layer is injectable, so the order-building and the safety gates
  are unit-tested with a fake venue and **no real network or keys**.

``CoinbaseClient`` is a documented skeleton: it intentionally raises until you
implement signing for your account, so no untested order-placing code can run by
accident. ``SimVenueClient`` lets you exercise the entire live path on paper.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field, asdict
from typing import Callable, Dict, List, Optional, Protocol, Tuple, runtime_checkable

from .types import Candle, Params
from .config import BotConfig, get_secret
from .risk import RiskManager
from .memory import Memory
from .strategy import generate_setups


# A method-aware HTTP transport: (method, url, headers, body) -> (status, bytes).
# Injectable so REST clients can be unit-tested with no network or keys.
HttpFn = Callable[[str, str, dict, Optional[bytes]], Tuple[int, bytes]]


def urllib_http(method: str, url: str, headers: dict, body: Optional[bytes] = None) -> Tuple[int, bytes]:
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:  # surface the body so callers can see why
        return e.code, e.read()


# --------------------------------------------------------------------------- #
# Venue client interface
# --------------------------------------------------------------------------- #
@runtime_checkable
class VenueClient(Protocol):
    def get_account_equity(self) -> float: ...
    def get_open_positions(self) -> List[dict]: ...
    def place_bracket(self, *, symbol: str, side: str, qty: float,
                      entry: float, stop: float, target: float) -> dict: ...
    def cancel_all(self, symbol: str) -> None: ...


class SimVenueClient:
    """In-memory venue for exercising the live path without real money. It just
    records placed orders and reports a fixed equity / no open positions, which
    is enough to test ``LiveBroker`` and ``run_live_once`` end-to-end."""

    def __init__(self, equity: float = 10_000.0) -> None:
        self._equity = equity
        self.placed: List[dict] = []

    def get_account_equity(self) -> float:
        return self._equity

    def get_open_positions(self) -> List[dict]:
        return []

    def place_bracket(self, *, symbol, side, qty, entry, stop, target) -> dict:
        order = {"symbol": symbol, "side": side, "qty": qty,
                 "entry": entry, "stop": stop, "target": target,
                 "id": f"sim-{len(self.placed) + 1}"}
        self.placed.append(order)
        return order

    def cancel_all(self, symbol: str) -> None:
        pass


class CoinbaseClient:
    """Skeleton adapter for Coinbase Advanced Trade. The transport is injectable;
    signing and the exact order payloads are deliberately left unimplemented so
    this cannot place a real order until you wire it to your account."""

    def __init__(self, key_name: str = "COINBASE_API_KEY",
                 secret_name: str = "COINBASE_API_SECRET",
                 http: Optional[Callable] = None) -> None:
        # Credentials are read lazily, from the environment only.
        self.key_name = key_name
        self.secret_name = secret_name
        self.http = http

    def _not_ready(self, what: str):
        raise NotImplementedError(
            f"CoinbaseClient.{what} is not implemented. Wire it to the Coinbase "
            "Advanced Trade API: load credentials via config.get_secret from the "
            "environment, sign each request per Coinbase's spec, and map "
            "place_bracket to a bracket/OCO order. Test against the sandbox first."
        )

    def get_account_equity(self) -> float:
        self._not_ready("get_account_equity")

    def get_open_positions(self) -> List[dict]:
        self._not_ready("get_open_positions")

    def place_bracket(self, **_) -> dict:
        self._not_ready("place_bracket")

    def cancel_all(self, symbol: str) -> None:
        self._not_ready("cancel_all")


class AlpacaClient:
    """Alpaca venue client, defaulting to the **paper sandbox**.

    Auth is two headers (no request signing), so this stays pure-stdlib and the
    HTTP layer is injectable for testing. Credentials are read lazily from the
    environment (``ALPACA_API_KEY_ID`` / ``ALPACA_API_SECRET_KEY``) so the client
    can be constructed and unit-tested without keys.

    Notes:
    * Default base URL is ``https://paper-api.alpaca.markets`` (the sandbox).
      Switch to ``https://api.alpaca.markets`` only for real money.
    * Bracket orders on Alpaca are an equities feature and require **whole-share**
      quantities; demo the live path with an equity symbol (e.g. ``AAPL``). Crypto
      has limited order types.
    """

    PAPER_URL = "https://paper-api.alpaca.markets"
    LIVE_URL = "https://api.alpaca.markets"

    def __init__(
        self,
        *,
        base_url: str = PAPER_URL,
        http: Optional[HttpFn] = None,
        key: Optional[str] = None,
        secret: Optional[str] = None,
        key_name: str = "ALPACA_API_KEY_ID",
        secret_name: str = "ALPACA_API_SECRET_KEY",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.http = http or urllib_http
        self._key = key
        self._secret = secret
        self.key_name = key_name
        self.secret_name = secret_name

    def _headers(self) -> dict:
        key = self._key or get_secret(self.key_name)
        secret = self._secret or get_secret(self.secret_name)
        return {
            "APCA-API-KEY-ID": key,
            "APCA-API-SECRET-KEY": secret,
            "Content-Type": "application/json",
        }

    def _request(self, method: str, path: str, body: Optional[bytes] = None) -> object:
        status, raw = self.http(method, self.base_url + path, self._headers(), body)
        if not 200 <= status < 300:
            raise RuntimeError(f"Alpaca {method} {path} -> {status}: {raw[:300]!r}")
        return json.loads(raw) if raw else {}

    def get_account_equity(self) -> float:
        acct = self._request("GET", "/v2/account")
        return float(acct.get("equity") or acct.get("portfolio_value") or 0.0)

    def get_open_positions(self) -> List[dict]:
        return self._request("GET", "/v2/positions") or []

    def place_bracket(self, *, symbol: str, side: str, qty: float,
                      entry: float, stop: float, target: float) -> dict:
        payload = {
            "symbol": symbol,
            "qty": str(qty),
            "side": "buy" if side == "long" else "sell",
            "type": "limit",
            "limit_price": round(entry, 2),
            "time_in_force": "gtc",
            "order_class": "bracket",
            "take_profit": {"limit_price": round(target, 2)},
            "stop_loss": {"stop_price": round(stop, 2)},
        }
        return self._request("POST", "/v2/orders", json.dumps(payload).encode())

    def cancel_all(self, symbol: Optional[str] = None) -> None:
        self._request("DELETE", "/v2/orders")


# --------------------------------------------------------------------------- #
# Live broker with fail-closed safety gates
# --------------------------------------------------------------------------- #
@dataclass
class LiveOrderResult:
    ok: bool
    id: str = ""
    raw: dict = field(default_factory=dict)
    error: str = ""


class LiveBroker:
    def __init__(self, client: VenueClient, *, symbol: str,
                 allow_live: bool = False, max_order_notional: Optional[float] = None) -> None:
        self.client = client
        self.symbol = symbol
        self.allow_live = allow_live
        self.max_order_notional = max_order_notional

    # read-only queries are always allowed
    def get_equity(self) -> float:
        return self.client.get_account_equity()

    def get_positions(self) -> List[dict]:
        return self.client.get_open_positions()

    def _require_live(self) -> None:
        if not self.allow_live:
            raise RuntimeError(
                "live trading disabled: construct LiveBroker(allow_live=True) to permit orders")
        if os.environ.get("BOT_ALLOW_LIVE") != "1":
            raise RuntimeError(
                "live trading disabled: set BOT_ALLOW_LIVE=1 in the environment to arm orders")

    def submit_bracket(self, *, symbol: str, side: str, qty: float,
                       entry: float, stop: float, target: float) -> LiveOrderResult:
        # All failure modes return a structured rejection (never crash the run).
        try:
            self._require_live()
        except RuntimeError as e:
            return LiveOrderResult(False, error=str(e))
        notional = qty * entry
        if self.max_order_notional is not None and notional > self.max_order_notional:
            return LiveOrderResult(
                False, error=f"order notional {notional:.2f} exceeds cap {self.max_order_notional:.2f}")
        try:
            raw = self.client.place_bracket(
                symbol=symbol, side=side, qty=qty, entry=entry, stop=stop, target=target)
            return LiveOrderResult(True, id=str(raw.get("id", "")), raw=raw)
        except Exception as e:  # noqa: BLE001
            return LiveOrderResult(False, error=str(e))

    def cancel_all_pending(self) -> None:
        self._require_live()
        self.client.cancel_all(self.symbol)


# --------------------------------------------------------------------------- #
# Live orchestrator (acts on the latest closed bar only)
# --------------------------------------------------------------------------- #
@dataclass
class LiveRunReport:
    acted_on_bar: int
    submitted: List[str] = field(default_factory=list)
    rejections: List[str] = field(default_factory=list)
    equity: float = 0.0
    skipped: str = ""

    def summary(self) -> str:
        if self.skipped:
            return f"live run skipped: {self.skipped}"
        return (f"live bar {self.acted_on_bar}: submitted={len(self.submitted)} "
                f"rejected={len(self.rejections)} equity={self.equity:.2f}")


def run_live_once(
    config: BotConfig,
    broker: LiveBroker,
    risk: RiskManager,
    memory: Memory,
    candles: List[Candle],
    params: Optional[Params] = None,
    notifier=None,
) -> LiveRunReport:
    """One live invocation: reconcile with the venue, evaluate setups armed on the
    latest closed bar, and submit the survivors. Fills are handled by the venue
    between runs, so we never simulate bars here."""
    params = params or config.params
    last = len(candles) - 1
    state = memory.load_state()
    last_acted = state.get("last_live_bar", -1)
    if last <= last_acted:
        return LiveRunReport(acted_on_bar=last, skipped="no new closed bar")

    equity = broker.get_equity()
    peak = max(state.get("peak_equity", equity), equity)
    positions = broker.get_positions()

    # daily counters keyed by UTC day from the bar timestamp
    day = candles[last].ts // 86400
    daily = state.get("daily") or {"day": day, "pnl": 0.0, "trades": 0, "start_equity": equity}
    if daily.get("day") != day:
        daily = {"day": day, "pnl": 0.0, "trades": 0, "start_equity": equity}

    setups, _ = generate_setups(candles, params)
    fresh = [s for s in setups if s.armed_at == last]

    report = LiveRunReport(acted_on_bar=last, equity=equity)
    for s in fresh:
        decision = risk.evaluate(
            symbol=config.symbol, side=s.direction, entry=s.entry, stop=s.stop,
            target=s.target, equity=equity, peak_equity=peak, open_positions=positions,
            trades_today=daily["trades"], daily_pnl=daily["pnl"],
            day_start_equity=daily["start_equity"],
        )
        if not decision.approved:
            report.rejections.append(f"{s.direction}: {decision.reason}")
            continue
        res = broker.submit_bracket(
            symbol=config.symbol, side=s.direction, qty=decision.qty,
            entry=s.entry, stop=s.stop, target=s.target)
        if res.ok:
            report.submitted.append(res.id)
            daily["trades"] += 1
            if notifier:
                notifier.send("order submitted",
                              f"{s.direction} {config.symbol} qty={decision.qty:.4f} "
                              f"entry={s.entry:.2f} stop={s.stop:.2f} tgt={s.target:.2f}")
        else:
            report.rejections.append(f"{s.direction}: broker rejected ({res.error})")
            if notifier:
                notifier.send("order rejected", res.error, level="warn")

    state["last_live_bar"] = last
    state["peak_equity"] = peak
    state["daily"] = daily
    memory.save_state(state)
    return report
