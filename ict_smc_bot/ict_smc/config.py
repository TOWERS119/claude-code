"""Bot configuration and secret handling.

Configuration is plain data with conservative defaults; it can be overridden
from environment variables (prefix ``BOT_``). Secrets (API keys) are *never*
part of config or the repo — they are read from the environment on demand via
``get_secret`` and never logged.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from .risk import RiskLimits
from .types import Params


@dataclass
class BotConfig:
    symbol: str = "SYNTH"
    timeframe: str = "15m"
    mode: str = "paper"          # "paper" | "live"
    broker: str = "paper"        # "paper" | "alpaca" | "ccxt"
    starting_equity: float = 10_000.0
    slippage_bps: float = 1.0
    commission_bps: float = 2.0
    state_dir: str = ".bot_state"
    entry_ttl: int = 15          # pending-order lifetime (bars)
    max_hold: int = 60           # max bars to hold a filled position
    bars_per_day: int = 96       # for daily counter rollover (96 = 15m bars/day)
    flatten_on_killswitch: bool = True
    limits: RiskLimits = field(default_factory=RiskLimits)
    params: Params = field(default_factory=Params)


def _env_float(name: str, default: float) -> float:
    v = os.environ.get(name)
    return float(v) if v is not None else default


def _env_int(name: str, default: int) -> int:
    v = os.environ.get(name)
    return int(v) if v is not None else default


def from_env(prefix: str = "BOT_") -> BotConfig:
    """Build a config, letting ``BOT_*`` environment variables override the
    non-secret fields. Risk limits use the ``BOT_RISK_*`` namespace."""
    cfg = BotConfig()
    cfg.symbol = os.environ.get(f"{prefix}SYMBOL", cfg.symbol)
    cfg.timeframe = os.environ.get(f"{prefix}TIMEFRAME", cfg.timeframe)
    cfg.mode = os.environ.get(f"{prefix}MODE", cfg.mode)
    cfg.broker = os.environ.get(f"{prefix}BROKER", cfg.broker)
    cfg.starting_equity = _env_float(f"{prefix}STARTING_EQUITY", cfg.starting_equity)
    cfg.state_dir = os.environ.get(f"{prefix}STATE_DIR", cfg.state_dir)
    cfg.entry_ttl = _env_int(f"{prefix}ENTRY_TTL", cfg.entry_ttl)
    cfg.max_hold = _env_int(f"{prefix}MAX_HOLD", cfg.max_hold)
    cfg.bars_per_day = _env_int(f"{prefix}BARS_PER_DAY", cfg.bars_per_day)

    lim = cfg.limits
    lim.risk_pct = _env_float(f"{prefix}RISK_PCT", lim.risk_pct)
    lim.max_concurrent_positions = _env_int(
        f"{prefix}RISK_MAX_CONCURRENT", lim.max_concurrent_positions)
    lim.max_new_trades_per_day = _env_int(
        f"{prefix}RISK_MAX_TRADES_PER_DAY", lim.max_new_trades_per_day)
    lim.max_daily_loss_pct = _env_float(f"{prefix}RISK_MAX_DAILY_LOSS", lim.max_daily_loss_pct)
    lim.max_drawdown_pct = _env_float(f"{prefix}RISK_MAX_DRAWDOWN", lim.max_drawdown_pct)
    wl = os.environ.get(f"{prefix}RISK_WHITELIST")
    if wl:
        lim.instrument_whitelist = tuple(s.strip() for s in wl.split(",") if s.strip())
    return cfg


def get_secret(name: str, required: bool = True) -> str:
    """Read a secret from the environment. Never falls back to a file or a
    literal; never log the return value."""
    val = os.environ.get(name)
    if required and not val:
        raise RuntimeError(
            f"Missing required secret {name!r}. Set it as an environment variable "
            f"(e.g. in your routine's cloud env), never in the repo or a .env file."
        )
    return val or ""
