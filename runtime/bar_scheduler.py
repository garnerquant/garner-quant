from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import timedelta
from pathlib import Path

import pandas as pd

from canonical_accounting.instruments import get_instrument_metadata
from execution.atomic_io import atomic_write_json
from runtime.locks import acquire_runtime_write_lock


STATE_SCHEMA_VERSION = "1"
DEFAULT_STATE_FILE = Path("data/runtime/processed_strategy_bars.json")
DEFAULT_LOCK_FILE = Path("data/runtime/strategy_bar_scheduler.lock")
TERMINAL_STATUSES = frozenset({"NO_ACTION", "EXECUTION_BLOCKED", "EXECUTED", "FAILED_FINAL"})
VALID_STATUSES = frozenset({
    "DISCOVERED", "VALIDATED", "SIGNAL_COMPUTED", "NO_ACTION",
    "EXECUTION_BLOCKED", "EXECUTED", "FAILED_RETRYABLE", "FAILED_FINAL",
})


class SchedulerError(RuntimeError):
    pass


@dataclass(frozen=True)
class MarketPolicy:
    symbol: str
    asset_class: str
    exchange: str
    calendar_id: str
    timeframe: str
    session_timezone: str
    session_open: str
    session_close: str
    completed_bar_policy: str
    weekend_policy: str
    holiday_policy: str
    early_close_policy: str
    continuous_market: bool
    minimum_timestamp_requirement: str
    maximum_scheduler_lag_seconds: int


@dataclass(frozen=True)
class BarIdentity:
    symbol: str
    timeframe: str
    bar_close_utc: str
    strategy_version: str
    configuration_version: str
    data_source: str
    data_revision: str = ""

    @property
    def key(self) -> str:
        payload = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ScheduleDecision:
    symbol: str
    eligible: bool
    status: str
    reason: str
    identity: BarIdentity | None
    market_state: str
    next_eligible_at: str | None
    scheduler_lag_seconds: float | None


def market_policies() -> dict[str, MarketPolicy]:
    policies = {}
    for symbol in (
        "BTC-GBP", "ETH-GBP", "IUSA.L", "VWRL.L", "SGLN.L",
        "AAPL", "MSFT", "NVDA", "TSLA",
    ):
        metadata = get_instrument_metadata(symbol)
        if metadata.market_calendar == "24/7":
            policy = MarketPolicy(
                symbol, metadata.asset_class, metadata.exchange, "24/7", "1d",
                "UTC", "00:00", "00:00", "UTC midnight, previous day",
                "allowed", "allowed", "not_applicable", True,
                "timezone-aware provider timestamp at UTC daily close",
                43200,
            )
        else:
            timezone_name = "Europe/London" if metadata.market_calendar == "XLON" else "America/New_York"
            policy = MarketPolicy(
                symbol, metadata.asset_class, metadata.exchange,
                metadata.market_calendar, "1d", timezone_name,
                "calendar", "calendar", "official exchange session close",
                "closed", "official_calendar", "official_calendar", False,
                "timezone-aware timestamp equal to official session close",
                21600,
            )
        policies[symbol] = policy
    return policies


def _aware_timestamp(value, field: str) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        raise SchedulerError(f"{field} must be timezone-aware")
    return timestamp.tz_convert("UTC")


class ExchangeCalendarAdapter:
    def __init__(self, loader=None):
        if loader is None:
            import exchange_calendars as calendars
            loader = calendars.get_calendar
        self.loader = loader

    def completed_session_close(self, calendar_id: str, bar_timestamp, now) -> pd.Timestamp:
        bar = _aware_timestamp(bar_timestamp, "bar timestamp")
        current = _aware_timestamp(now, "runtime clock")
        calendar = self.loader(calendar_id)
        start = (bar - pd.Timedelta(days=2)).date()
        end = (bar + pd.Timedelta(days=2)).date()
        sessions = calendar.sessions_in_range(start, end)
        closes = [calendar.session_close(session).tz_convert("UTC") for session in sessions]
        matches = [close for close in closes if close == bar]
        if not matches:
            raise SchedulerError("bar timestamp is not an official completed session close")
        close = matches[0]
        if close > current:
            raise SchedulerError("latest strategy bar is incomplete")
        return close

    def next_close(self, calendar_id: str, now) -> pd.Timestamp:
        current = _aware_timestamp(now, "runtime clock")
        calendar = self.loader(calendar_id)
        sessions = calendar.sessions_in_range(
            (current - pd.Timedelta(days=1)).date(),
            (current + pd.Timedelta(days=14)).date(),
        )
        for session in sessions:
            close = calendar.session_close(session).tz_convert("UTC")
            if close > current:
                return close
        raise SchedulerError("calendar has no next session close")


def evaluate_completed_bar(
    symbol: str,
    bar_timestamp,
    *,
    now,
    strategy_version: str,
    configuration_version: str,
    data_source: str,
    data_revision: str = "",
    policies=None,
    calendar_adapter=None,
) -> ScheduleDecision:
    policies = policies or market_policies()
    policy = policies.get(symbol)
    if policy is None:
        return ScheduleDecision(symbol, False, "FAILED_FINAL", "missing calendar metadata", None, "unknown", None, None)
    try:
        get_instrument_metadata(symbol)
        current = _aware_timestamp(now, "runtime clock")
        bar = _aware_timestamp(bar_timestamp, "bar timestamp")
        if not strategy_version or not configuration_version:
            raise SchedulerError("strategy and configuration versions are required")
        if bar > current:
            raise SchedulerError("bar timestamp is future-dated")
        if policy.timeframe != "1d":
            raise SchedulerError("unsupported strategy timeframe")
        if policy.continuous_market:
            if not (bar.hour == 0 and bar.minute == 0 and bar.second == 0 and bar.microsecond == 0):
                raise SchedulerError("crypto daily bar must close at 00:00 UTC")
            close = bar
            next_close = bar + pd.Timedelta(days=1)
            market_state = "continuous"
        else:
            adapter = calendar_adapter or ExchangeCalendarAdapter()
            close = adapter.completed_session_close(policy.calendar_id, bar, current)
            next_close = adapter.next_close(policy.calendar_id, current)
            market_state = "session_closed"
        identity = BarIdentity(
            symbol=symbol, timeframe=policy.timeframe,
            bar_close_utc=close.isoformat(), strategy_version=strategy_version,
            configuration_version=configuration_version, data_source=data_source,
            data_revision=data_revision,
        )
        lag = max(0.0, (current - close).total_seconds())
        if lag > policy.maximum_scheduler_lag_seconds:
            raise SchedulerError("completed bar is stale for strategy evaluation")
        return ScheduleDecision(symbol, True, "DISCOVERED", "new completed bar is eligible",
                                identity, market_state, next_close.isoformat(), lag)
    except Exception as exc:
        return ScheduleDecision(symbol, False, "FAILED_FINAL", str(exc), None, "blocked", None, None)


class ProcessedBarStore:
    def __init__(self, path=DEFAULT_STATE_FILE, lock_path=DEFAULT_LOCK_FILE):
        self.path = Path(path)
        self.lock_path = Path(lock_path)

    def _empty(self):
        return {"schema_version": STATE_SCHEMA_VERSION, "records": {}, "duplicate_suppressions": {}}

    def load(self) -> dict:
        if not self.path.exists():
            return self._empty()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise SchedulerError("processed-bar state is corrupt") from exc
        if payload.get("schema_version") != STATE_SCHEMA_VERSION or not isinstance(payload.get("records"), dict):
            raise SchedulerError("processed-bar state schema is invalid")
        return payload

    def claim(self, decision: ScheduleDecision, *, decision_timestamp) -> tuple[bool, dict]:
        if not decision.eligible or decision.identity is None:
            raise SchedulerError("cannot claim an ineligible bar")
        instant = _aware_timestamp(decision_timestamp, "decision timestamp").isoformat()
        key = decision.identity.key
        with acquire_runtime_write_lock(path=self.lock_path, context="strategy_bar_claim"):
            payload = self.load()
            existing = payload["records"].get(key)
            if existing and existing.get("status") != "FAILED_RETRYABLE":
                counts = payload.setdefault("duplicate_suppressions", {})
                counts[decision.identity.symbol] = int(counts.get(decision.identity.symbol, 0)) + 1
                atomic_write_json(payload, self.path, lock_path=self.lock_path)
                return False, dict(existing)
            record = {
                "bar_key": key, "identity": asdict(decision.identity),
                "decision_timestamp": instant, "status": "DISCOVERED",
                "signal_result": None, "execution_result": None,
                "related_event_ids": [], "failure_reason": None,
                "retry_eligible": False, "updated_at": instant,
                "market_state": decision.market_state,
                "next_eligible_at": decision.next_eligible_at,
                "scheduler_lag_seconds": decision.scheduler_lag_seconds,
            }
            payload["records"][key] = record
            atomic_write_json(payload, self.path, lock_path=self.lock_path)
            return True, dict(record)

    def transition(self, identity: BarIdentity, status: str, *, timestamp,
                   signal_result=None, execution_result=None, related_event_ids=None,
                   failure_reason=None, retry_eligible=False) -> dict:
        if status not in VALID_STATUSES:
            raise SchedulerError(f"invalid processed-bar status: {status}")
        instant = _aware_timestamp(timestamp, "transition timestamp").isoformat()
        with acquire_runtime_write_lock(path=self.lock_path, context="strategy_bar_transition"):
            payload = self.load()
            record = payload["records"].get(identity.key)
            if record is None:
                raise SchedulerError("processed bar was not claimed")
            if record.get("status") in TERMINAL_STATUSES:
                raise SchedulerError("processed bar is already terminal")
            record.update({
                "status": status, "updated_at": instant,
                "signal_result": signal_result if signal_result is not None else record.get("signal_result"),
                "execution_result": execution_result if execution_result is not None else record.get("execution_result"),
                "related_event_ids": list(related_event_ids or record.get("related_event_ids") or []),
                "failure_reason": failure_reason,
                "retry_eligible": bool(retry_eligible and status == "FAILED_RETRYABLE"),
            })
            atomic_write_json(payload, self.path, lock_path=self.lock_path)
            return dict(record)

    def is_processed(self, identity: BarIdentity) -> bool:
        record = self.load()["records"].get(identity.key)
        return bool(record and record.get("status") != "FAILED_RETRYABLE")

    def health(self) -> dict:
        payload = self.load()
        by_symbol = {}
        for record in payload["records"].values():
            symbol = record.get("identity", {}).get("symbol", "UNKNOWN")
            current = by_symbol.get(symbol)
            if current is None or record.get("updated_at", "") > current.get("updated_at", ""):
                by_symbol[symbol] = dict(record)
        return {
            "schema_version": payload["schema_version"],
            "instruments": by_symbol,
            "duplicate_suppressions": dict(payload.get("duplicate_suppressions", {})),
        }
