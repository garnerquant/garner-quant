from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from zoneinfo import ZoneInfo

import pandas as pd


OPENING_SOON_SECONDS = 60 * 60
WEEKDAYS = set(range(5))


@dataclass(frozen=True)
class MarketDisplay:
    code: str
    label: str
    full_name: str
    session_code: str
    calendar_code: str | None
    timezone_label: str
    icon: str


@dataclass(frozen=True)
class MarketStatus:
    code: str
    label: str
    full_name: str
    state: str
    display_state: str
    detail: str
    session_label: str
    is_open: bool
    seconds_until_next_open: int | None
    next_session_label: str | None
    icon: str


MARKET_DISPLAYS = {
    "LSE": MarketDisplay(
        code="LSE",
        label="LSE",
        full_name="London Stock Exchange",
        session_code="LSE",
        calendar_code="LSE",
        timezone_label="UK",
        icon="🟢",
    ),
    "US": MarketDisplay(
        code="US",
        label="US Market",
        full_name="US Market",
        session_code="US",
        calendar_code="US",
        timezone_label="ET",
        icon="🔵",
    ),
    "NYSE": MarketDisplay(
        code="NYSE",
        label="NYSE",
        full_name="New York Stock Exchange",
        session_code="US",
        calendar_code="US",
        timezone_label="ET",
        icon="🔵",
    ),
    "NASDAQ": MarketDisplay(
        code="NASDAQ",
        label="NASDAQ",
        full_name="NASDAQ",
        session_code="US",
        calendar_code="US",
        timezone_label="ET",
        icon="🔵",
    ),
    "TSE": MarketDisplay(
        code="TSE",
        label="Tokyo",
        full_name="Tokyo Stock Exchange",
        session_code="TSE",
        calendar_code="TSE",
        timezone_label="JST",
        icon="🔴",
    ),
    "CRYPTO": MarketDisplay(
        code="CRYPTO",
        label="Crypto",
        full_name="Crypto Market",
        session_code="CRYPTO",
        calendar_code=None,
        timezone_label="UTC",
        icon="🟣",
    ),
}


def nth_weekday(year, month, weekday, n):
    current = date(year, month, 1)
    while current.weekday() != weekday:
        current += timedelta(days=1)
    return current + timedelta(days=7 * (n - 1))


def last_weekday(year, month, weekday):
    if month == 12:
        current = date(year, 12, 31)
    else:
        current = date(year, month + 1, 1) - timedelta(days=1)
    while current.weekday() != weekday:
        current -= timedelta(days=1)
    return current


def observed_fixed(year, month, day):
    holiday = date(year, month, day)
    if holiday.weekday() == 5:
        return holiday - timedelta(days=1)
    if holiday.weekday() == 6:
        return holiday + timedelta(days=1)
    return holiday


def easter_date(year):
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def uk_observed_christmas(year):
    holidays = []
    used = set()
    for day in (25, 26):
        candidate = date(year, 12, day)
        observed = candidate
        while observed.weekday() >= 5 or observed in used:
            observed += timedelta(days=1)
        holidays.append(observed)
        used.add(observed)
    return holidays


def us_market_holidays(year):
    easter = easter_date(year)
    holidays = {
        observed_fixed(year, 1, 1),
        nth_weekday(year, 1, 0, 3),
        nth_weekday(year, 2, 0, 3),
        easter - timedelta(days=2),
        last_weekday(year, 5, 0),
        observed_fixed(year, 6, 19),
        observed_fixed(year, 7, 4),
        nth_weekday(year, 9, 0, 1),
        nth_weekday(year, 11, 3, 4),
        observed_fixed(year, 12, 25),
    }

    # New Year's Day can be observed on Dec 31 of the previous year.
    holidays.add(observed_fixed(year + 1, 1, 1))
    return holidays


def lse_holidays(year):
    easter = easter_date(year)
    holidays = {
        observed_fixed(year, 1, 1),
        easter - timedelta(days=2),
        easter + timedelta(days=1),
        nth_weekday(year, 5, 0, 1),
        last_weekday(year, 5, 0),
        last_weekday(year, 8, 0),
    }
    holidays.update(uk_observed_christmas(year))
    return holidays


def vernal_equinox_day(year):
    return int(20.8431 + 0.242194 * (year - 1980) - ((year - 1980) // 4))


def autumnal_equinox_day(year):
    return int(23.2488 + 0.242194 * (year - 1980) - ((year - 1980) // 4))


def add_japan_holiday(holidays, holiday):
    holidays.add(holiday)
    if holiday.weekday() == 6:
        observed = holiday + timedelta(days=1)
        while observed in holidays:
            observed += timedelta(days=1)
        holidays.add(observed)


def tse_holidays(year):
    holidays = {date(year, 1, 2), date(year, 1, 3), date(year, 12, 31)}
    base_holidays = [
        date(year, 1, 1),
        nth_weekday(year, 1, 0, 2),
        date(year, 2, 11),
        date(year, 2, 23),
        date(year, 3, vernal_equinox_day(year)),
        date(year, 4, 29),
        date(year, 5, 3),
        date(year, 5, 4),
        date(year, 5, 5),
        nth_weekday(year, 7, 0, 3),
        date(year, 8, 11),
        nth_weekday(year, 9, 0, 3),
        date(year, 9, autumnal_equinox_day(year)),
        nth_weekday(year, 10, 0, 2),
        date(year, 11, 3),
        date(year, 11, 23),
    ]
    for holiday in base_holidays:
        add_japan_holiday(holidays, holiday)
    return holidays


def market_holidays(calendar_code, year):
    if calendar_code == "US":
        return us_market_holidays(year)
    if calendar_code == "LSE":
        return lse_holidays(year)
    if calendar_code == "TSE":
        return tse_holidays(year)
    return set()


def is_market_holiday(calendar_code, local_date):
    if not calendar_code:
        return False
    years = {local_date.year - 1, local_date.year, local_date.year + 1}
    holidays = set()
    for year in years:
        holidays.update(market_holidays(calendar_code, year))
    return local_date in holidays


def local_timestamp(now, timezone):
    if now is None:
        return pd.Timestamp.now(tz=timezone)

    timestamp = pd.Timestamp(now)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    return timestamp.tz_convert(timezone)


def session_datetimes(local_now, open_time, close_time):
    open_dt = local_now.normalize().replace(
        hour=open_time.hour,
        minute=open_time.minute,
        second=0,
        microsecond=0,
    )
    close_dt = local_now.normalize().replace(
        hour=close_time.hour,
        minute=close_time.minute,
        second=0,
        microsecond=0,
    )
    return open_dt, close_dt


def next_session_open(local_now, open_time, calendar_code):
    candidate = local_now.normalize().replace(
        hour=open_time.hour,
        minute=open_time.minute,
        second=0,
        microsecond=0,
    )
    if candidate <= local_now:
        candidate += pd.Timedelta(days=1)

    for _ in range(20):
        candidate_date = candidate.date()
        if (
            candidate.weekday() in WEEKDAYS
            and not is_market_holiday(calendar_code, candidate_date)
        ):
            return candidate
        candidate += pd.Timedelta(days=1)
        candidate = candidate.normalize().replace(
            hour=open_time.hour,
            minute=open_time.minute,
            second=0,
            microsecond=0,
        )

    return None


def market_timezone_label(display, value=None):
    if display.timezone_label == "UK" and value is not None:
        return value.strftime("%Z")
    return display.timezone_label


def format_market_time(value, display):
    return f"{value.strftime('%H:%M')} {market_timezone_label(display, value)}"


def format_next_session(value, display):
    if value is None:
        return "Next session unavailable"
    return f"{value.strftime('%A %H:%M')} {market_timezone_label(display, value)}"


def session_label(session, display):
    if not session:
        return "Schedule unavailable"
    if session.get("always_open"):
        return "Always open"

    open_time = session.get("open")
    close_time = session.get("close")
    timezone = session.get("timezone")
    if open_time is None or close_time is None or not timezone:
        return "Schedule unavailable"

    return (
        f"{open_time.strftime('%H:%M')} - "
        f"{close_time.strftime('%H:%M')} {display.timezone_label}"
    )


def market_status(market, sessions, now=None):
    display = MARKET_DISPLAYS.get(
        market,
        MarketDisplay(
            code=market,
            label=str(market),
            full_name=str(market),
            session_code=market,
            calendar_code=None,
            timezone_label="local",
            icon="⚪",
        ),
    )
    session = sessions.get(display.session_code)
    schedule_label = session_label(session, display)

    if not session:
        return MarketStatus(
            code=display.code,
            label=display.label,
            full_name=display.full_name,
            state="UNAVAILABLE",
            display_state="Schedule unavailable",
            detail="Schedule unavailable",
            session_label=schedule_label,
            is_open=False,
            seconds_until_next_open=None,
            next_session_label=None,
            icon="⚪",
        )

    if session.get("always_open"):
        return MarketStatus(
            code=display.code,
            label=display.label,
            full_name=display.full_name,
            state="24/7",
            display_state="OPEN 24/7",
            detail="Always open",
            session_label=schedule_label,
            is_open=True,
            seconds_until_next_open=0,
            next_session_label="Always open",
            icon=display.icon,
        )

    timezone = session.get("timezone")
    open_time = session.get("open")
    close_time = session.get("close")
    if not timezone or open_time is None or close_time is None:
        return MarketStatus(
            code=display.code,
            label=display.label,
            full_name=display.full_name,
            state="UNAVAILABLE",
            display_state="Schedule unavailable",
            detail="Schedule unavailable",
            session_label=schedule_label,
            is_open=False,
            seconds_until_next_open=None,
            next_session_label=None,
            icon="⚪",
        )

    local_now = local_timestamp(now, ZoneInfo(timezone))
    open_dt, close_dt = session_datetimes(local_now, open_time, close_time)
    local_date = local_now.date()
    is_holiday = is_market_holiday(display.calendar_code, local_date)
    is_weekday = local_now.weekday() in WEEKDAYS
    next_open = next_session_open(local_now, open_time, display.calendar_code)
    seconds = (
        max(0, int((next_open - local_now).total_seconds()))
        if next_open is not None
        else None
    )
    next_label = format_next_session(next_open, display)

    if is_holiday:
        return MarketStatus(
            code=display.code,
            label=display.label,
            full_name=display.full_name,
            state="HOLIDAY",
            display_state="Holiday",
            detail=f"Holiday today | Next session: {next_label}",
            session_label=schedule_label,
            is_open=False,
            seconds_until_next_open=seconds,
            next_session_label=next_label,
            icon=display.icon,
        )

    if is_weekday and open_dt <= local_now <= close_dt:
        return MarketStatus(
            code=display.code,
            label=display.label,
            full_name=display.full_name,
            state="OPEN",
            display_state="Open",
            detail=f"Closes {format_market_time(close_dt, display)}",
            session_label=schedule_label,
            is_open=True,
            seconds_until_next_open=0,
            next_session_label=None,
            icon=display.icon,
        )

    if is_weekday and local_now < open_dt:
        seconds_to_open = max(0, int((open_dt - local_now).total_seconds()))
        state = "OPENING_SOON" if seconds_to_open <= OPENING_SOON_SECONDS else "CLOSED"
        display_state = "Opening soon" if state == "OPENING_SOON" else "Closed"
        return MarketStatus(
            code=display.code,
            label=display.label,
            full_name=display.full_name,
            state=state,
            display_state=display_state,
            detail=f"Opens {format_market_time(open_dt, display)}",
            session_label=schedule_label,
            is_open=False,
            seconds_until_next_open=seconds_to_open,
            next_session_label=format_next_session(open_dt, display),
            icon=display.icon,
        )

    return MarketStatus(
        code=display.code,
        label=display.label,
        full_name=display.full_name,
        state="CLOSED",
        display_state="Closed",
        detail=f"Next session: {next_label}",
        session_label=schedule_label,
        is_open=False,
        seconds_until_next_open=seconds,
        next_session_label=next_label,
        icon=display.icon,
    )


def display_market_codes(configured_markets):
    codes = []
    for market in configured_markets or []:
        if market == "US":
            codes.extend(["NYSE", "NASDAQ"])
        else:
            codes.append(market)
    return list(dict.fromkeys(codes))


def market_statuses(configured_markets, sessions, now=None):
    return [
        market_status(market, sessions, now=now)
        for market in display_market_codes(configured_markets)
    ]


def next_market_event_label(configured_markets, sessions, now=None):
    candidates = [
        status
        for status in market_statuses(configured_markets, sessions, now=now)
        if not status.is_open and status.seconds_until_next_open is not None
    ]
    if not candidates:
        return "None"

    status = min(candidates, key=lambda item: item.seconds_until_next_open)
    if status.state == "HOLIDAY":
        return f"{status.label}: {status.detail}"
    if status.state == "OPENING_SOON":
        return f"{status.label}: Opening soon | {status.detail}"
    return f"{status.label}: {status.detail}"
