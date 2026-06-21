"""GLM strategy research — capability (3), honest by construction.

GLM proposes strategy *parameters* (never code) as a JSON object whose keys are a
whitelist subset of ``Params`` fields. Each proposal is type-coerced and clamped
to a safe range, applied via ``dataclasses.replace`` (no exec/eval), and scored
by the SAME ``walk_forward`` out-of-sample rig the project already trusts — then
compared to a noise floor measured on random data. A proposal that does not clear
the floor by a margin is flagged ``sub_noise_floor`` so a curve-fit can never be
dressed up as a discovery.

Cost/equity fields (commission, slippage, starting equity) are deliberately
excluded from the whitelist, so GLM cannot manufacture "profit" by lowering
modeled costs.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import List, Optional

from .types import Params
from .backtest import walk_forward
from . import data


# (type, lo, hi) for numerics; (type, choices) for enums; (type,) for bools.
# Single source of truth for the prompt schema AND the clamp logic.
FIELD_SPECS = {
    "swing_lookback": ("int", 1, 6),
    "atr_period": ("int", 5, 50),
    "displacement_atr_mult": ("float", 0.5, 3.0),
    "displacement_body_ratio": ("float", 0.3, 0.9),
    "require_displacement_fvg": ("bool",),
    "sweep_max_age": ("int", 5, 60),
    "mss_max_age": ("int", 3, 40),
    "require_fvg": ("bool",),
    "use_ob_fallback": ("bool",),
    "entry_level": ("enum", ("edge", "mid", "deep")),
    "equilibrium_filter": ("bool",),
    "stop_buffer_atr": ("float", 0.0, 1.0),
    "min_rr": ("float", 1.0, 5.0),
    "entry_valid_bars": ("int", 3, 40),
    "trade_max_bars": ("int", 10, 200),
    "allow_long": ("bool",),
    "allow_short": ("bool",),
}


@dataclass
class ProposalResult:
    params_overrides: dict
    oos_expectancy_r: float
    oos_profit_factor: float
    oos_num_trades: int
    noise_floor: float
    margin: float
    passes_noise_floor: bool
    sub_noise_floor: bool
    folds: List[dict] = field(default_factory=list)
    error: str = ""


@dataclass
class ResearchReport:
    ranked: List[ProposalResult]
    noise_floor: float
    rounds: int
    best: Optional[ProposalResult] = None


def _coerce_bool(v: object) -> bool:
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("true", "1", "yes", "y")


def sanitize_proposal(obj: object) -> Optional[dict]:
    """Coerce + clamp a raw proposal into safe ``Params`` overrides. Unknown keys
    are dropped; out-of-range numerics are clamped; invalid enums/values are
    skipped. Returns None if nothing usable remains."""
    if not isinstance(obj, dict):
        return None
    out: dict = {}
    for k, v in obj.items():
        spec = FIELD_SPECS.get(k)
        if spec is None:
            continue
        kind = spec[0]
        try:
            if kind == "int":
                out[k] = int(max(spec[1], min(spec[2], int(round(float(v))))))
            elif kind == "float":
                out[k] = float(max(spec[1], min(spec[2], float(v))))
            elif kind == "bool":
                out[k] = _coerce_bool(v)
            elif kind == "enum":
                if v in spec[1]:
                    out[k] = v
        except (TypeError, ValueError):
            continue
    return out or None


def compute_noise_floor(base_params: Params, n_folds: int,
                        n: int = 4000, seed: int = 7) -> float:
    """OOS expectancy of the base strategy on random data — the noise floor a
    real edge must clear."""
    _, agg = walk_forward(data.synthetic(n=n, seed=seed), base_params,
                          grid=None, n_folds=n_folds)
    return agg.expectancy_r


def evaluate_proposal(real_candles, base_params: Params, overrides: dict,
                      noise_floor: float, n_folds: int, min_oos_trades: int,
                      margin_eps: float) -> ProposalResult:
    try:
        p = replace(base_params, **overrides)
    except TypeError as e:
        return ProposalResult(overrides, 0.0, 0.0, 0, noise_floor, 0.0,
                              False, True, error=f"invalid params: {e}")
    folds, agg = walk_forward(real_candles, p, grid=None, n_folds=n_folds)
    margin = agg.expectancy_r - noise_floor
    passes = (margin > margin_eps) and (agg.num_trades >= min_oos_trades)
    return ProposalResult(
        params_overrides=overrides,
        oos_expectancy_r=agg.expectancy_r,
        oos_profit_factor=agg.profit_factor,
        oos_num_trades=agg.num_trades,
        noise_floor=noise_floor,
        margin=margin,
        passes_noise_floor=passes,
        sub_noise_floor=not passes,
        folds=[{"oos_expectancy_r": f["oos"].expectancy_r,
                "oos_trades": f["oos"].num_trades} for f in folds],
    )


# --------------------------------------------------------------------------- #
# GLM prompting
# --------------------------------------------------------------------------- #
def schema_text() -> str:
    lines = []
    for k, spec in FIELD_SPECS.items():
        if spec[0] in ("int", "float"):
            lines.append(f'  "{k}": {spec[0]} in [{spec[1]}, {spec[2]}]')
        elif spec[0] == "bool":
            lines.append(f'  "{k}": bool')
        elif spec[0] == "enum":
            lines.append(f'  "{k}": one of {list(spec[1])}')
    return "{\n" + ",\n".join(lines) + "\n}"


def _build_research_messages(base_params: Params, noise_floor: float,
                             batch_size: int, history: List[str]) -> List[dict]:
    sys = (
        "You design parameter sets for an ICT/Smart-Money-Concepts trading "
        "strategy. You are judged ONLY by out-of-sample (walk-forward) expectancy "
        "minus a noise floor measured on random data; in-sample numbers are "
        "ignored. You cannot lower trading costs. Propose diverse, plausible "
        "parameter sets."
    )
    hist = ("\n\nResults so far (proposal -> OOS expectancy, margin vs floor, "
            "pass):\n" + "\n".join(history)) if history else ""
    user = (
        f"Noise floor (random-data OOS expectancy): {noise_floor:+.3f}R. A proposal "
        f"is only interesting if its OOS expectancy clears this by a margin.\n\n"
        f"Propose {batch_size} parameter sets as a JSON object "
        f'{{"proposals": [ ... ]}} where each element uses ONLY these keys '
        f"(all optional; omitted keys keep defaults):\n{schema_text()}{hist}\n\n"
        f"Return ONLY the JSON object."
    )
    return [{"role": "system", "content": sys}, {"role": "user", "content": user}]


def _request_proposals(client, base_params, noise_floor, batch_size, history) -> List[dict]:
    obj = client.complete_json(_build_research_messages(base_params, noise_floor, batch_size, history))
    if isinstance(obj, dict):
        if isinstance(obj.get("proposals"), list):
            return obj["proposals"]
        return [obj]
    if isinstance(obj, list):
        return obj
    return []


def _summarize_round(results: List[ProposalResult]) -> str:
    parts = []
    for r in results:
        if r.error:
            parts.append(f"  (skipped: {r.error})")
        else:
            parts.append(f"  {r.params_overrides} -> {r.oos_expectancy_r:+.3f}R "
                         f"margin={r.margin:+.3f} {'PASS' if r.passes_noise_floor else 'sub-floor'}")
    return "\n".join(parts)


def run_research(client, real_candles, base_params: Optional[Params] = None, *,
                 n_rounds: int = 3, batch_size: int = 4, n_folds: int = 4,
                 min_oos_trades: int = 10, margin_eps: float = 0.0,
                 synthetic_n: int = 4000, synthetic_seed: int = 7,
                 logger=None) -> ResearchReport:
    """Run the honest propose -> validate-OOS -> compare-to-floor -> feed-back loop.

    Robust to a bad round (malformed proposals become skipped results and the loop
    continues). Always returns a ranked report; ``best`` is set only if the top
    proposal actually clears the noise floor.
    """
    base_params = base_params or Params(require_fvg=False, min_rr=2.0)
    floor = compute_noise_floor(base_params, n_folds, n=synthetic_n, seed=synthetic_seed)
    results: List[ProposalResult] = []
    history: List[str] = []

    for _ in range(n_rounds):
        try:
            proposals = _request_proposals(client, base_params, floor, batch_size, history)
        except Exception as e:  # noqa: BLE001 - one bad round must not abort the loop
            proposals = []
            if logger:
                logger.warning("proposal request failed: %r", e)
        round_results: List[ProposalResult] = []
        for prop in proposals:
            clean = sanitize_proposal(prop)
            if clean is None:
                round_results.append(ProposalResult(
                    {}, 0.0, 0.0, 0, floor, 0.0, False, True, error="unusable proposal"))
                continue
            round_results.append(evaluate_proposal(
                real_candles, base_params, clean, floor, n_folds, min_oos_trades, margin_eps))
        results.extend(round_results)
        history.append(_summarize_round(round_results))

    ranked = sorted(
        results,
        key=lambda r: (r.passes_noise_floor, r.oos_expectancy_r, r.oos_num_trades),
        reverse=True,
    )
    best = ranked[0] if ranked and ranked[0].passes_noise_floor else None
    return ResearchReport(ranked=ranked, noise_floor=floor, rounds=n_rounds, best=best)
