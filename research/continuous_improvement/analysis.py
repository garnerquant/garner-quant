"""Small deterministic analysis catalogue with explicit statistical controls."""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from statistics import NormalDist, mean, median, stdev

from .evidence import ResearchEvidenceSnapshot
from .models import make_observation


@dataclass(frozen=True)
class AnalysisDefinition:
    analysis_id: str
    feature: str
    grouping: str
    control: str
    minimum_group_sample: int
    supported: bool
    unavailable_reason: str | None = None


def analysis_catalogue():
    return (
        AnalysisDefinition("performance_by_strategy", "strategy", "strategy", "all other strategies", 5, True),
        AnalysisDefinition("performance_by_market_regime", "market_regime", "market regime", "all other regimes", 10, False, "Market regime at entry is unavailable"),
        AnalysisDefinition("performance_by_volatility", "volatility_regime", "volatility bucket", "all other buckets", 10, False, "Volatility bucket at entry is unavailable"),
        AnalysisDefinition("holding_period", "holding_period_bucket", "holding-period bucket", "all other buckets", 5, True),
        AnalysisDefinition("stop_loss", "stop_loss_outcome", "stop-loss exit", "non-stop exits", 5, True),
        AnalysisDefinition("profit_target", "profit_target_outcome", "profit-target exit", "non-target exits", 5, True),
        AnalysisDefinition("day_of_week", "entry_day_of_week", "entry weekday", "all other weekdays", 5, True),
        AnalysisDefinition("strategy_agreement", "strategy_agreement", "strategy agreement", "single strategy", 10, False, "Strategy agreement count is unavailable"),
        AnalysisDefinition("risk_rejected_outcome", "risk_rejected_outcome", "risk-rejected signals", "accepted signals", 20, False, "Comparable counterfactual outcomes are unavailable"),
        AnalysisDefinition("temporal_stability", "temporal_period", "calendar half", "other calendar half", 8, True),
    )


def _trade_rows(snapshot):
    rows = []
    for item in snapshot.records:
        if item.evidence_type != "COMPLETED_TRADE": continue
        fields = dict(item.fields)
        try: outcome = float(fields.get("pnl_pct"))
        except (TypeError, ValueError): continue
        if not math.isfinite(outcome): continue
        try:
            opened = datetime.fromisoformat(str(fields.get("open_time")).replace("Z", "+00:00"))
            closed = datetime.fromisoformat(str(fields.get("close_time")).replace("Z", "+00:00"))
        except (TypeError, ValueError): opened = closed = None
        holding_days = (closed - opened).total_seconds() / 86400 if opened and closed else None
        reason = str(fields.get("close_reason") or "").upper().replace(" ", "_")
        rows.append({"return": outcome, "strategy": fields.get("strategy"), "symbol": fields.get("symbol"),
            "open": opened, "close": closed, "holding_period_bucket": ("0-2 days" if holding_days is not None and holding_days < 3 else "3-10 days" if holding_days is not None and holding_days <= 10 else "11+ days" if holding_days is not None else None),
            "stop_loss_outcome": "Stop loss" if "STOP" in reason else "Other exit",
            "profit_target_outcome": "Profit target" if "PROFIT" in reason or "TAKE_PROFIT" in reason else "Other exit",
            "entry_day_of_week": opened.strftime("%A") if opened else None,
            "temporal_period": opened.strftime("%Y-%m") if opened else None,
            "evidence_id": item.evidence_id})
    return rows


def _p_value(left, right):
    if len(left) < 2 or len(right) < 2: return None
    variance = stdev(left) ** 2 / len(left) + stdev(right) ** 2 / len(right)
    if variance <= 0: return None
    z = abs(mean(left) - mean(right)) / math.sqrt(variance)
    return max(0.0, min(1.0, 2 * (1 - NormalDist().cdf(z))))


def _bh(values):
    indexed = sorted(((value, index) for index, value in enumerate(values) if value is not None), reverse=True)
    adjusted = [None] * len(values); running = 1.0; total = len(indexed)
    for reverse_rank, (value, index) in enumerate(indexed, 1):
        rank = total - reverse_rank + 1; running = min(running, value * total / rank); adjusted[index] = running
    return adjusted


def analyse_patterns(snapshot: ResearchEvidenceSnapshot, *, generated_at: datetime):
    rows = _trade_rows(snapshot); attempts = []; unsupported = []
    observed_times = [value for row in rows for value in (row.get("open"), row.get("close")) if value is not None]
    observation_period = ((min(observed_times).date().isoformat(), max(observed_times).date().isoformat())
                          if observed_times else (snapshot.source_cutoff.date().isoformat(), snapshot.source_cutoff.date().isoformat()))
    for definition in analysis_catalogue():
        if not definition.supported:
            unsupported.append(f"{definition.analysis_id}: {definition.unavailable_reason}"); continue
        groups = sorted({str(row.get(definition.feature)) for row in rows if row.get(definition.feature) not in (None, "")})
        for group in groups:
            left = [row["return"] for row in rows if str(row.get(definition.feature)) == group]
            right = [row["return"] for row in rows if row.get(definition.feature) not in (None, "") and str(row.get(definition.feature)) != group]
            attempts.append((definition, group, left, right, _p_value(left, right)))
    adjusted = _bh([item[4] for item in attempts]); observations = []
    for (definition, group, left, right, raw), corrected in zip(attempts, adjusted):
        if len(left) < definition.minimum_group_sample or len(right) < definition.minimum_group_sample: continue
        difference = mean(left) - mean(right)
        pooled = math.sqrt(((len(left)-1)*stdev(left)**2 + (len(right)-1)*stdev(right)**2) / (len(left)+len(right)-2)) if len(left)>1 and len(right)>1 else 0
        effect = difference / pooled if pooled else 0.0
        quality = "MODERATE" if corrected is not None and corrected <= .05 and abs(effect) >= .5 else "EXPLORATORY"
        limitations = ["Observed association is not causal", "Historical paper evidence may not generalise",
                       f"Multiple-testing correction covered {len(attempts)} attempted comparisons"]
        if len({row["symbol"] for row in rows if str(row.get(definition.feature)) == group}) < 3: limitations.append("Evidence is concentrated in fewer than three instruments")
        description = f"{group} was associated with a {difference:+.2f} percentage-point difference in observed mean trade return and may warrant investigation."
        observation_type = ("HOLDING_PERIOD_EFFECT" if definition.analysis_id == "holding_period" else
                            "EXIT_CHARACTERISTIC" if definition.analysis_id in {"stop_loss", "profit_target"} else
                            "ENTRY_CHARACTERISTIC" if definition.analysis_id == "day_of_week" else "PERFORMANCE_DIFFERENCE")
        observations.append(make_observation(observation_type=observation_type, title=f"Observed return difference for {group}",
            description=description, source_population="completed paper trades", strategy_scope=tuple(sorted({str(row['strategy']) for row in rows if row.get('strategy')})),
            instrument_scope=tuple(sorted({str(row['symbol']) for row in rows if row.get('symbol')})), market_scope=(),
            observation_period=observation_period,
            comparison_groups=(group, definition.control), sample_size=len(left)+len(right),
            observed_metric=("mean_return_pct", f"{mean(left):.6f}"), control_metric=("mean_return_pct", f"{mean(right):.6f}"),
            absolute_difference=f"{difference:.6f}", relative_difference=None,
            uncertainty_information=(("effect_size", f"{effect:.6f}"), ("group_median", f"{median(left):.6f}"), ("control_median", f"{median(right):.6f}")),
            evidence_quality=quality, limitations=tuple(limitations), provenance_references=tuple(sorted({row['evidence_id'] for row in rows})),
            generated_at=generated_at, attempted_comparisons=len(attempts), raw_significance=f"{raw:.8f}" if raw is not None else None,
            adjusted_significance=f"{corrected:.8f}" if corrected is not None else None))
    return tuple(sorted(observations, key=lambda item: item.observation_id)), tuple(unsupported), len(attempts)
