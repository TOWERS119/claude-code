"""Scheduled routine: the one function a cron job / Claude Code routine calls.

It wakes statelessly, runs one trading step (paper or live), notifies a summary,
and on request produces a weekly performance review benchmarked against buy &
hold. This is the glue that turns the layers into an autonomous agent.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from .types import Candle
from .config import BotConfig
from .risk import RiskManager
from .memory import Memory
from .engine import run_once, build_broker
from .notify import NullNotifier
from . import performance


@dataclass
class RoutineResult:
    mode: str
    run_summary: str
    weekly_review: Optional[str] = None


def run_routine(
    config: BotConfig,
    candles: List[Candle],
    *,
    notifier=None,
    weekly_review: bool = False,
    max_bars: Optional[int] = None,
    logger=None,
) -> RoutineResult:
    """Run one scheduled step. Currently drives the paper engine; switch to the
    live path by constructing a LiveBroker + run_live_once once your venue client
    is implemented and BOT_ALLOW_LIVE=1."""
    notifier = notifier or NullNotifier()
    memory = Memory(config.state_dir)
    risk = RiskManager(config.limits)
    broker = build_broker(config, memory)

    report = run_once(config, broker, risk, memory, candles,
                      max_bars=max_bars, logger=logger)
    summary = report.summary()
    level = "warn" if report.halted_reasons else "info"
    notifier.send(f"{config.symbol} run", summary, level=level)

    review_text = None
    if weekly_review:
        trades = memory.read_trades()
        perf = performance.summarize(trades, config.starting_equity, candles)
        review_text = performance.weekly_review_text(perf, period_label=config.symbol)
        notifier.send(f"{config.symbol} weekly review", review_text)

    return RoutineResult(mode=config.mode, run_summary=summary, weekly_review=review_text)
