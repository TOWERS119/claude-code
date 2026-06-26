"""Orchestrator: a single stateless "run once" that ties every layer together.

This is the agent's one invocation. It:

    1. restores state + broker from memory (stateless wake-up);
    2. advances the market over every bar that arrived since the last run;
    3. on each bar: resolves broker fills/exits, logs closed trades, rolls daily
       counters, updates the equity peak;
    4. enforces the kill-switch / daily breaker (halting new entries, optionally
       flattening);
    5. routes every freshly-armed strategy setup through the risk manager and
       submits the survivors as bracket orders;
    6. persists state + broker back to memory.

Calling it again with more data simply continues from the saved cursor, which is
exactly the stateless-run + file-memory model from the knowledge base.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Tuple

from .types import Candle, Params
from .config import BotConfig
from .risk import RiskManager
from .broker import PaperBroker
from .memory import Memory
from .strategy import generate_setups
from .advisor import TradeAdvisor, AdvisorAction


@dataclass
class RunReport:
    processed_from: int
    processed_to: int
    fills: int = 0
    closes: int = 0
    submitted: List[str] = field(default_factory=list)
    rejections: List[Tuple[int, str, str]] = field(default_factory=list)
    equity: float = 0.0
    peak_equity: float = 0.0
    open_positions: int = 0
    halted_reasons: List[str] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"bars {self.processed_from}..{self.processed_to}  "
            f"fills={self.fills} closes={self.closes} "
            f"submitted={len(self.submitted)} rejected={len(self.rejections)}  "
            f"equity={self.equity:.2f} (peak {self.peak_equity:.2f}) "
            f"open={self.open_positions}"
            + (f"  HALTED: {'; '.join(sorted(set(self.halted_reasons)))}"
               if self.halted_reasons else "")
        )


def build_broker(config: BotConfig, memory: Memory) -> PaperBroker:
    """Restore the paper broker from memory, or create a fresh one."""
    state = memory.load_state()
    if state.get("broker"):
        return PaperBroker.from_dict(state["broker"])
    return PaperBroker(
        starting_equity=config.starting_equity,
        slippage_bps=config.slippage_bps,
        commission_bps=config.commission_bps,
    )


def run_once(
    config: BotConfig,
    broker: PaperBroker,
    risk: RiskManager,
    memory: Memory,
    candles: List[Candle],
    params: Optional[Params] = None,
    max_bars: Optional[int] = None,
    advisor: Optional[TradeAdvisor] = None,
    logger=None,
) -> RunReport:
    params = params or config.params
    log = (lambda m: logger.info(m)) if logger else (lambda m: None)

    state = memory.load_state()
    last_index = state.get("last_index", -1)
    peak = state.get("peak_equity", broker.get_equity())
    daily = state.get("daily") or {
        "day": -1, "pnl": 0.0, "trades": 0, "start_equity": broker.get_equity(),
    }

    n = len(candles)
    start = last_index + 1
    end = n - 1 if max_bars is None else min(n - 1, last_index + max_bars)
    report = RunReport(processed_from=start, processed_to=end)
    if start > end:  # nothing new to process
        report.equity = broker.get_equity()
        report.peak_equity = peak
        report.open_positions = len(broker.get_positions())
        return report

    # Setups are derived from data; only those armed within the new window matter.
    setups, _ = generate_setups(candles, params)
    by_arm: Dict[int, list] = {}
    for s in setups:
        by_arm.setdefault(s.armed_at, []).append(s)

    for idx in range(start, end + 1):
        candle = candles[idx]

        # daily rollover
        day = candle.ts // config.bars_per_day if config.bars_per_day > 0 else 0
        if day != daily["day"]:
            daily = {"day": day, "pnl": 0.0, "trades": 0,
                     "start_equity": broker.get_equity()}

        fills, closes = broker.on_bar(idx, candle)
        for ct in closes:
            memory.append_trade(asdict(ct))
            daily["pnl"] += ct.pnl
            report.closes += 1
            log(f"closed {ct.side} {ct.symbol} @ {ct.exit_price:.2f} "
                f"{ct.outcome} pnl={ct.pnl:+.2f} ({ct.r_multiple:+.2f}R)")
        report.fills += len(fills)

        equity = broker.get_equity()
        peak = max(peak, equity)

        # account-level halts
        if risk.kill_switch_active(equity, peak):
            report.halted_reasons.append("kill-switch (max drawdown)")
            if config.flatten_on_killswitch:
                for ct in broker.flatten(idx, candle):
                    memory.append_trade(asdict(ct))
                    daily["pnl"] += ct.pnl
                    report.closes += 1
            continue
        if risk.daily_breaker_active(daily["pnl"], daily["start_equity"]):
            report.halted_reasons.append("daily loss breaker")
            continue

        # route freshly-armed setups through (optional advisor ->) risk
        for s in by_arm.get(idx, []):
            verdict = None
            if advisor is not None:
                verdict = advisor.review(
                    setup=s, symbol=config.symbol, equity=equity,
                    recent_candles=candles[max(0, idx - 50):idx + 1],
                    open_positions=len(broker.get_positions()), daily_pnl=daily["pnl"],
                )
                if verdict.action == AdvisorAction.VETO:
                    report.rejections.append((idx, s.direction, f"advisor veto: {verdict.reason}"))
                    log(f"advisor veto {s.direction} @ bar {idx}: {verdict.reason}")
                    continue
            decision = risk.evaluate(
                symbol=config.symbol, side=s.direction, entry=s.entry, stop=s.stop,
                target=s.target, equity=equity, peak_equity=peak,
                open_positions=broker.get_positions(), trades_today=daily["trades"],
                daily_pnl=daily["pnl"], day_start_equity=daily["start_equity"],
            )
            if decision.approved:
                qty = decision.qty if verdict is None else TradeAdvisor.apply(decision.qty, verdict)
                if qty <= 0:
                    report.rejections.append((idx, s.direction, "advisor downsized to zero"))
                    continue
                order = broker.submit_bracket(
                    symbol=config.symbol, side=s.direction, qty=qty,
                    entry=s.entry, stop=s.stop, target=s.target,
                    armed_index=idx, ttl=config.entry_ttl, max_hold=config.max_hold,
                )
                report.submitted.append(order.id)
                daily["trades"] += 1
                log(f"submitted {s.direction} {config.symbol} "
                    f"entry={s.entry:.2f} stop={s.stop:.2f} tgt={s.target:.2f} "
                    f"qty={qty:.4f}")
            else:
                report.rejections.append((idx, s.direction, decision.reason))
                log(f"rejected {s.direction} @ bar {idx}: {decision.reason}")

    # persist
    state["last_index"] = end
    state["peak_equity"] = peak
    state["daily"] = daily
    state["broker"] = broker.to_dict()
    memory.save_state(state)

    report.equity = broker.get_equity()
    report.peak_equity = peak
    report.open_positions = len(broker.get_positions())
    return report
