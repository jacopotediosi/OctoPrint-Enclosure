from __future__ import annotations

from datetime import datetime, time, timedelta

HHMM_FORMAT = "%H:%M"


def parse_hhmm(value: str) -> time | None:
    """Read a time of day in the HH:MM format.

    Args:
        value (str): The text to read.

    Returns:
        time | None: The time of day, or None if the text isn't in the HH:MM format.

    Examples:
        >>> parse_hhmm("09:30")
        datetime.time(9, 30)
        >>> parse_hhmm("0") is None
        True

    """
    try:
        return datetime.strptime(value, HHMM_FORMAT).time()
    except ValueError:
        return None


def seconds_until_today_at(time_of_day: time) -> float:
    """Seconds until a time of day today, or 0 if it has already passed."""
    now = datetime.now()
    return max((datetime.combine(now.date(), time_of_day) - now).total_seconds(), 0.0)


def seconds_until_next(time_of_day: time) -> float:
    """Seconds until the next occurrence of a time of day, today or tomorrow."""
    now = datetime.now()
    next_occurrence = datetime.combine(now.date(), time_of_day)
    if next_occurrence < now:
        next_occurrence += timedelta(days=1)

    return (next_occurrence - now).total_seconds()
