from __future__ import annotations

from datetime import datetime, timedelta

HHMM_FORMAT = "%H:%M"


def is_hhmm(value: str) -> bool:
    """Whether a value is a time of day in the HH:MM format."""
    try:
        datetime.strptime(value, HHMM_FORMAT)
    except (TypeError, ValueError):
        return False
    else:
        return True


def today_at(hhmm: str) -> datetime:
    """Today's date at the given HH:MM time."""
    time_of_day = datetime.strptime(hhmm, HHMM_FORMAT).time()
    return datetime.combine(datetime.now().date(), time_of_day)


def seconds_until_today_at(hhmm: str) -> float:
    """Seconds until an HH:MM time of day today, or 0 if it has already passed."""
    return max((today_at(hhmm) - datetime.now()).total_seconds(), 0.0)


def seconds_until_next(hhmm: str) -> float:
    """Seconds until the next occurrence of an HH:MM time of day, today or tomorrow."""
    now = datetime.now()
    next_occurrence = today_at(hhmm)
    if next_occurrence < now:
        next_occurrence += timedelta(days=1)

    return (next_occurrence - now).total_seconds()
