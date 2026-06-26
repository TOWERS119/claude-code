"""ICT / Smart Money Concepts strategy engine.

A pure-standard-library, look-ahead-safe implementation of the entry gate
specified in ``notes/ict-smc-addon.md`` and ``strategy_spec.md``:

    liquidity sweep -> market-structure shift -> return to a PD array in
    discount/premium -> entry, stop beyond the sweep, target opposing liquidity.

The package is dependency-free on purpose so it runs unchanged in a stateless
cloud agent run. Real-data loaders (ccxt/yfinance) are optional and isolated in
``data.py``.
"""

from .types import Candle, Swing, FVG, Setup, Trade, Params
from .detectors import (
    compute_atr,
    find_swings,
    detect_fvgs,
    is_displacement,
    find_order_block,
)
from .strategy import generate_setups
from .backtest import backtest, BacktestResult, train_test, walk_forward
from .risk import RiskLimits, RiskDecision, RiskManager
from .broker import PaperBroker, BracketOrder, Position, ClosedTrade, LiveBroker
from .memory import Memory
from .config import BotConfig, from_env, get_secret
from .engine import run_once, build_broker, RunReport
from .performance import PerformanceReport, summarize, weekly_review_text, buy_and_hold_return
from .notify import (
    NullNotifier, ConsoleNotifier, FileNotifier, WebhookNotifier, CompositeNotifier,
)
from .live import (
    VenueClient, SimVenueClient, CoinbaseClient, AlpacaClient, LiveBroker,
    LiveOrderResult, LiveRunReport, run_live_once, urllib_http,
)
from .routine import run_routine, RoutineResult
from .glm import GlmClient, GlmResponse, GlmError, GlmParseError, extract_json
from .advisor import TradeAdvisor, AdvisorVerdict, AdvisorAction
from .research import (
    run_research, ResearchReport, ProposalResult, sanitize_proposal,
    compute_noise_floor, FIELD_SPECS,
)
from .providers import Provider, PROVIDERS, make_client, resolve, list_providers, require_key

__all__ = [
    "Candle",
    "Swing",
    "FVG",
    "Setup",
    "Trade",
    "Params",
    "compute_atr",
    "find_swings",
    "detect_fvgs",
    "is_displacement",
    "find_order_block",
    "generate_setups",
    "backtest",
    "BacktestResult",
    "train_test",
    "walk_forward",
    # risk / execution / memory / engine
    "RiskLimits",
    "RiskDecision",
    "RiskManager",
    "PaperBroker",
    "BracketOrder",
    "Position",
    "ClosedTrade",
    "LiveBroker",
    "Memory",
    "BotConfig",
    "from_env",
    "get_secret",
    "run_once",
    "build_broker",
    "RunReport",
    # performance / benchmarking
    "PerformanceReport",
    "summarize",
    "weekly_review_text",
    "buy_and_hold_return",
    # notifications
    "NullNotifier",
    "ConsoleNotifier",
    "FileNotifier",
    "WebhookNotifier",
    "CompositeNotifier",
    # live execution
    "VenueClient",
    "SimVenueClient",
    "CoinbaseClient",
    "AlpacaClient",
    "urllib_http",
    "LiveBroker",
    "LiveOrderResult",
    "LiveRunReport",
    "run_live_once",
    # routine
    "run_routine",
    "RoutineResult",
    # GLM client (capabilities 3 & 4)
    "GlmClient",
    "GlmResponse",
    "GlmError",
    "GlmParseError",
    "extract_json",
    # GLM trade advisor (capability 4)
    "TradeAdvisor",
    "AdvisorVerdict",
    "AdvisorAction",
    # GLM strategy research (capability 3)
    "run_research",
    "ResearchReport",
    "ProposalResult",
    "sanitize_proposal",
    "compute_noise_floor",
    "FIELD_SPECS",
    # LLM provider registry (free + paid presets)
    "Provider",
    "PROVIDERS",
    "make_client",
    "resolve",
    "list_providers",
    "require_key",
]
