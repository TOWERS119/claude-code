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
]
