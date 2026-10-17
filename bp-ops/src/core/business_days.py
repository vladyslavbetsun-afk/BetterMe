"""Business-day calendar: Europe/Brussels, Monday–Friday, minus settings.holidays (00 §6.4)."""

from collections.abc import Iterable
from datetime import date, datetime, time, timedelta

from config import TZ

DAY = timedelta(days=1)


def _hol(holidays: Iterable | None) -> set[date]:
    out = set()
    for h in holidays or ():
        out.add(h if isinstance(h, date) else date.fromisoformat(str(h)))
    return out


def is_business_day(d: date, holidays: Iterable | None = None) -> bool:
    return d.weekday() < 5 and d not in _hol(holidays)


def elapsed(start: datetime, end: datetime | None = None, holidays: Iterable | None = None) -> float:
    """Elapsed time in days, counting only business days (fractional), in Brussels local time.

    Same idea as the legacy bizDays(): walk day by day and add the part of each weekday that falls in the window.
    """
    if start is None:
        return 0.0
    end = end or datetime.now(TZ)
    start, end = start.astimezone(TZ), end.astimezone(TZ)
    if end <= start:
        return 0.0
    hol = _hol(holidays)
    total = 0.0
    t = start
    while t < end:
        nxt = datetime.combine(t.date() + DAY, time(0), tzinfo=TZ)
        seg_end = min(nxt, end)
        if t.weekday() < 5 and t.date() not in hol:
            total += (seg_end - t).total_seconds() / 86400
        t = seg_end
    return total


def add_business_days(d: date, n: float, holidays: Iterable | None = None) -> date:
    """The date n business days after d (n rounded up to whole days; n <= 0 returns d)."""
    hol = _hol(holidays)
    remaining = int(-(-n // 1)) if n > 0 else 0
    while remaining > 0:
        d += DAY
        if d.weekday() < 5 and d not in hol:
            remaining -= 1
    return d


def business_days_between(a: date, b: date, holidays: Iterable | None = None) -> int:
    """Whole business days in (a, b]. 0 when b <= a."""
    hol = _hol(holidays)
    n, d = 0, a
    while d < b:
        d += DAY
        if d.weekday() < 5 and d not in hol:
            n += 1
    return n


def business_dates(start: date, end: date, holidays: Iterable | None = None) -> list[date]:
    """Business dates in [start, end]."""
    hol = _hol(holidays)
    out, d = [], start
    while d <= end:
        if d.weekday() < 5 and d not in hol:
            out.append(d)
        d += DAY
    return out


def next_weekday_at(now: datetime, hour: int = 9, minute: int = 0) -> datetime:
    """Next weekday (strictly after today) at hh:mm local. Default publishing send time (00 §6.5)."""
    d = now.astimezone(TZ).date() + DAY
    while d.weekday() >= 5:
        d += DAY
    return datetime.combine(d, time(hour, minute), tzinfo=TZ)


def local_today() -> date:
    return datetime.now(TZ).date()
