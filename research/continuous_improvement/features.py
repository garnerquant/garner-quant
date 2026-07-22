"""Controlled, versioned and look-ahead-safe feature catalogue."""
from .models import FeatureDefinition


def feature_catalogue():
    def feature(name, meaning, fields, values=(), minimum=10, leakage="LOW"):
        return FeatureDefinition(name, meaning, tuple(fields), tuple(values), "UNKNOWN_EXCLUDED", "feature-v1",
            "Only fields recorded at or before the relevant decision are eligible; outcome fields are used only as outcomes.",
            leakage, minimum)
    return (
        feature("strategy", "Explicit strategy recorded for a completed trade", ("strategy",)),
        feature("market_regime", "Explicit market regime at entry", ("market_regime",), minimum=15),
        feature("volatility_bucket", "Explicit volatility bucket at entry", ("volatility_regime",), minimum=15),
        feature("holding_period_bucket", "Elapsed time from recorded entry to exit", ("open_time", "close_time")),
        feature("stop_loss_outcome", "Exit explicitly recorded as stop loss", ("close_reason",), ("STOP_LOSS", "OTHER")),
        feature("profit_target_outcome", "Exit explicitly recorded as profit target", ("close_reason",), ("TAKE_PROFIT", "OTHER")),
        feature("entry_day_of_week", "Weekday of recorded entry timestamp", ("open_time",)),
        feature("strategy_agreement", "Explicit strategy agreement count at entry", ("strategy_agreement_count",), minimum=15),
        feature("risk_rejected_outcome", "Observable outcome for an explicitly rejected signal", ("risk_status", "outcome"), minimum=20, leakage="HIGH"),
        feature("temporal_period", "Calendar subperiod of completed trade", ("close_time",), minimum=15),
    )
