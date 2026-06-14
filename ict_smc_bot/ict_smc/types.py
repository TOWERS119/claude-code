"""Core data types and the strategy parameter set.

Everything is plain dataclasses so the engine has zero third-party dependencies.
A ``Candle`` carries OHLCV; the rest are detector/strategy outputs. ``Params``
is the single knob bag — every ICT rule is expressed as an explicit *number*
here so the whole gate is backtestable (the entire point of the addon: turn the
discretionary method into testable rules).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Candle:
    """One OHLCV bar. ``ts`` is any monotonically increasing index/epoch."""

    ts: int
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    @property
    def body(self) -> float:
        return abs(self.close - self.open)

    @property
    def range(self) -> float:
        return self.high - self.low

    @property
    def bullish(self) -> bool:
        return self.close > self.open

    @property
    def bearish(self) -> bool:
        return self.close < self.open


@dataclass(frozen=True)
class Swing:
    """A confirmed swing pivot.

    ``confirmed_at`` is the bar index at which this pivot first becomes *known*
    (``index + swing_lookback``). The strategy may only reference a swing once
    the scan has reached ``confirmed_at`` — this is what keeps the backtest free
    of look-ahead bias.
    """

    index: int
    price: float
    kind: str  # "high" or "low"
    confirmed_at: int


@dataclass(frozen=True)
class FVG:
    """A 3-candle fair value gap. ``top`` >= ``bottom`` always."""

    direction: str  # "bull" or "bear"
    start_index: int  # index of candle 3 (the bar completing the gap)
    top: float
    bottom: float

    @property
    def mid(self) -> float:
        return (self.top + self.bottom) / 2.0


@dataclass
class Setup:
    """An armed setup: everything below is computed from data at or before
    ``armed_at`` (the MSS bar). The pending entry goes live the *next* bar."""

    direction: str  # "long" or "short"
    sweep_index: int
    sweep_price: float  # the wick extreme of the sweep (basis for the stop)
    mss_index: int
    entry: float
    stop: float
    target: float
    equilibrium: float
    range_low: float
    range_high: float
    armed_at: int
    entry_source: str = "fvg"  # "fvg" or "order_block"

    @property
    def rr(self) -> float:
        risk = abs(self.entry - self.stop)
        return abs(self.target - self.entry) / risk if risk > 0 else 0.0


@dataclass
class Trade:
    """A simulated trade and its outcome."""

    direction: str
    setup: Setup
    entry_index: int
    entry_price: float
    exit_index: int
    exit_price: float
    outcome: str  # "target", "stop", "timeout"
    r_multiple: float
    pnl: float = 0.0
    equity_after: float = 0.0


@dataclass
class Params:
    """Numeric rule set for the whole gate. Defaults are deliberately
    conservative; every value is a backtest parameter, not a fact."""

    # --- structure detection ---
    swing_lookback: int = 2          # fractal half-width (bars each side)
    atr_period: int = 14

    # --- displacement / FVG quality ---
    displacement_atr_mult: float = 1.0   # candle range must exceed mult * ATR
    displacement_body_ratio: float = 0.5  # body must be >= ratio * range
    require_displacement_fvg: bool = True  # FVG must come from displacement

    # --- sequence windows (bars) ---
    sweep_max_age: int = 30   # max bars from swept pivot to the sweep bar
    mss_max_age: int = 20     # max bars from sweep to the MSS bar

    # --- entry array selection ---
    require_fvg: bool = True          # if False, order block alone may be used
    use_ob_fallback: bool = True      # fall back to order block when no FVG
    entry_level: str = "mid"          # "edge" | "mid" | "deep" within the zone
    equilibrium_filter: bool = True   # long only in discount, short in premium

    # --- risk geometry ---
    stop_buffer_atr: float = 0.25     # stop placed this far beyond the sweep
    min_rr: float = 2.0
    target_synthetic_fallback: bool = True  # synth target if no liquidity gives RR

    # --- execution simulation ---
    entry_valid_bars: int = 15        # pending order time-to-live
    trade_max_bars: int = 60          # force exit after this many bars in-trade

    # --- sizing & costs ---
    risk_pct: float = 0.01            # fraction of equity risked per trade
    commission_bps: float = 2.0       # per side, in basis points of notional
    slippage_bps: float = 1.0         # adverse, per fill
    starting_equity: float = 10_000.0

    # --- direction toggles ---
    allow_long: bool = True
    allow_short: bool = True
