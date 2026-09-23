"""Weekly delivery schedules ("time of day" in Ads Manager) for Reddit ad groups.

Reddit stores a schedule as a list of time blocks::

    {"start_day": 0, "start_hour": 13, "end_day": 0, "end_hour": 23}

An empty list (or null) means delivery at any time.

Two things the OpenAPI spec gets wrong, both verified against a live
account on 2026-09-13:

* Day numbering. The spec says ``0`` is Sunday. The API and Ads Manager
  agree on ``0`` = Monday: an ad group whose grid reads Mon–Fri comes back
  as days 0–4, delivers on Fridays and is silent on Sundays.
* Time zone. The spec says the ad group's time zone. Delivery follows
  each viewer's local clock: a 13:00–23:59 block reaches German viewers
  from 13:00 CEST and US-Pacific viewers from 22:00 CEST, so an account in
  Europe sees impressions until 09:00 the next morning.

``end_hour`` is inclusive: ``23`` runs through 23:59.

Tools accept day names rather than numbers so nobody has to know which
numbering is in force, and a ``days`` shorthand expands to one block per
day, which is how Ads Manager's grid is stored anyway.
"""

from __future__ import annotations

from typing import Any

DAY_NAMES = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
_DAY_LOOKUP = {name: i for i, name in enumerate(DAY_NAMES)}
_DAY_LOOKUP.update(
    {
        full: i
        for i, full in enumerate(
            ("MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY")
        )
    }
)
_DISPLAY = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def _day_index(value: Any, field: str, errors: list[str]) -> int | None:
    if isinstance(value, bool) or not isinstance(value, str):
        errors.append(
            f"{field}: use a day name (MON..SUN), not {value!r}. Reddit's numeric "
            "days are ambiguous between its spec and its API."
        )
        return None
    key = value.strip().upper()
    if key not in _DAY_LOOKUP:
        errors.append(f"{field}: unknown day {value!r}; use one of {', '.join(DAY_NAMES)}")
        return None
    return _DAY_LOOKUP[key]


def _hour(value: Any, field: str, errors: list[str]) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or int(value) != value:
        errors.append(f"{field}: must be a whole hour 0-23, got {value!r}")
        return None
    hour = int(value)
    if not 0 <= hour <= 23:
        errors.append(f"{field}: must be between 0 and 23, got {hour}")
        return None
    return hour


def _expand_days(spec: Any, errors: list[str]) -> list[int]:
    """``"MON-FRI"``, ``["MON", "WED"]`` or ``"SAT"`` → day indexes."""
    if isinstance(spec, str) and "-" in spec:
        first, _, last = spec.partition("-")
        a = _day_index(first, "days", errors)
        b = _day_index(last, "days", errors)
        if a is None or b is None:
            return []
        if a <= b:
            return list(range(a, b + 1))
        # A range wrapping the weekend ("SAT-MON") is still a range.
        return list(range(a, 7)) + list(range(0, b + 1))
    if isinstance(spec, str):
        idx = _day_index(spec, "days", errors)
        return [] if idx is None else [idx]
    if isinstance(spec, list):
        out: list[int] = []
        for item in spec:
            idx = _day_index(item, "days", errors)
            if idx is not None and idx not in out:
                out.append(idx)
        return out
    errors.append(f"days: expected a day name, a range like MON-FRI or a list, got {spec!r}")
    return []


def parse_schedule(blocks: Any, errors: list[str]) -> list[dict[str, int]] | None:
    """Turn tool input into Reddit's block list, or None when input is absent.

    Accepts, per block, either the native shape with day names
    (``{"start_day": "MON", "start_hour": 13, "end_day": "MON", "end_hour": 23}``)
    or the shorthand ``{"days": "MON-FRI", "start_hour": 13, "end_hour": 23}``,
    which expands to one same-day block per day. An empty list clears the
    schedule (deliver at any time). Problems are appended to ``errors``.
    """
    if blocks is None:
        return None
    if not isinstance(blocks, list):
        errors.append("schedule must be a list of time blocks (or [] to clear it)")
        return None
    out: list[dict[str, int]] = []
    for i, block in enumerate(blocks):
        label = f"schedule[{i}]"
        if not isinstance(block, dict):
            errors.append(f"{label}: each block must be an object")
            continue
        start_hour = _hour(block.get("start_hour"), f"{label}.start_hour", errors)
        end_hour = _hour(block.get("end_hour"), f"{label}.end_hour", errors)
        if "days" in block:
            for day in _expand_days(block["days"], errors):
                if start_hour is not None and end_hour is not None:
                    if end_hour < start_hour:
                        errors.append(
                            f"{label}: end_hour {end_hour} is before start_hour {start_hour}; "
                            "for an overnight window use start_day/end_day"
                        )
                        break
                    out.append(
                        {"start_day": day, "start_hour": start_hour, "end_day": day, "end_hour": end_hour}
                    )
            continue
        start_day = _day_index(block.get("start_day"), f"{label}.start_day", errors)
        end_day = _day_index(block.get("end_day"), f"{label}.end_day", errors)
        if None in (start_day, start_hour, end_day, end_hour):
            continue
        if start_day == end_day and end_hour < start_hour:
            errors.append(f"{label}: end_hour {end_hour} is before start_hour {start_hour} on the same day")
            continue
        out.append(
            {"start_day": start_day, "start_hour": start_hour, "end_day": end_day, "end_hour": end_hour}
        )
    return out


def named_blocks(blocks: Any) -> list[dict[str, Any]]:
    """Reddit's numeric blocks with day names, for tool output."""
    out = []
    for block in blocks or []:
        if not isinstance(block, dict):
            continue
        try:
            out.append(
                {
                    "start_day": DAY_NAMES[int(block.get("start_day", 0)) % 7],
                    "start_hour": int(block.get("start_hour", 0)),
                    "end_day": DAY_NAMES[int(block.get("end_day", 0)) % 7],
                    "end_hour": int(block.get("end_hour", 23)),
                }
            )
        except (TypeError, ValueError):
            continue
    return out


def describe_schedule(blocks: Any) -> str:
    """One line a person can read: ``Mon–Fri 13:00–23:59``, or ``any time``.

    Same-day blocks with identical hours on consecutive days collapse into a
    range; everything else is listed as is.
    """
    named = named_blocks(blocks)
    if not named:
        return "any time"
    parts: list[str] = []
    run: list[int] = []
    run_hours: tuple[int, int] | None = None

    def _flush() -> None:
        if not run:
            return
        days = _DISPLAY[run[0]] if len(run) == 1 else f"{_DISPLAY[run[0]]}–{_DISPLAY[run[-1]]}"
        assert run_hours is not None
        parts.append(f"{days} {run_hours[0]:02d}:00–{run_hours[1]:02d}:59")

    for block in named:
        start = DAY_NAMES.index(block["start_day"])
        end = DAY_NAMES.index(block["end_day"])
        hours = (block["start_hour"], block["end_hour"])
        if start == end:
            if run and run_hours == hours and start == run[-1] + 1:
                run.append(start)
                continue
            _flush()
            run, run_hours = [start], hours
            continue
        _flush()
        run, run_hours = [], None
        parts.append(
            f"{_DISPLAY[start]} {hours[0]:02d}:00 to {_DISPLAY[end]} {hours[1]:02d}:59"
        )
    _flush()
    return "; ".join(parts)
