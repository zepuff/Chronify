# Chronify — a macOS menu bar work tracker.
# Copyright (C) 2026 Zepuff
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

from datetime import datetime, time as dtime, timedelta
from typing import Optional

from chronify.config import WEEKDAY_NAMES
from chronify.store import JsonList

LATE_WINDOW_MINUTES = 120

ALL_DAYS = [0, 1, 2, 3, 4, 5, 6]
WEEKDAYS = [0, 1, 2, 3, 4]
WEEKEND = [5, 6]

_alerts = JsonList(
    "alerts.json",
    sort_key=lambda a: (a.get("hour", 0), a.get("minute", 0)),
)


def _clean_days(days) -> list:
    if not days:
        return []
    try:
        cleaned = sorted({int(d) for d in days if 0 <= int(d) <= 6})
    except (TypeError, ValueError):
        return []
    return [] if len(cleaned) == 7 else cleaned


def add_alert(hour: int, minute: int, text: str,
              days=None, one_shot: bool = False) -> dict:
    return _alerts.add(
        text=text.strip(),
        hour=int(hour),
        minute=int(minute),
        days=_clean_days(days),
        one_shot=bool(one_shot),
        last_fired="",
    )


def read_all_alerts() -> list:
    return _alerts.read()


def get_alert(alert_id: str) -> Optional[dict]:
    return _alerts.get(alert_id)


def update_alert(alert_id: str, hour: int, minute: int, text: str,
                 days=None, one_shot: bool = False) -> bool:
    return _alerts.update(
        alert_id,
        hour=int(hour),
        minute=int(minute),
        text=text.strip(),
        days=_clean_days(days),
        one_shot=bool(one_shot),
        last_fired="",
    )


def delete_alerts(alert_ids) -> int:
    return _alerts.delete(alert_ids)


def mark_fired(alert_id: str, day_iso: str) -> None:
    _alerts.update(alert_id, last_fired=day_iso)


def finish(alert: dict, day_iso: str) -> None:
    if alert.get("one_shot"):
        delete_alerts([alert["id"]])
    else:
        mark_fired(alert["id"], day_iso)


def format_time(alert: dict) -> str:
    return f"{alert.get('hour', 0):02d}:{alert.get('minute', 0):02d}"


def format_schedule(alert: dict) -> str:
    days = _clean_days(alert.get("days"))

    if alert.get("one_shot"):
        rule = "once"
    elif not days:
        rule = "every day"
    elif days == WEEKDAYS:
        rule = "Mon-Fri"
    elif days == WEEKEND:
        rule = "weekend"
    else:
        rule = " ".join(WEEKDAY_NAMES[d] for d in days)

    return f"{format_time(alert)} \u00b7 {rule}"


def runs_on(alert: dict, moment_date) -> bool:
    days = _clean_days(alert.get("days"))
    return not days or moment_date.weekday() in days


def due_alerts(now: Optional[datetime] = None):
    now = now or datetime.now()
    today = now.date().isoformat()
    to_notify, to_silence = [], []

    for alert in read_all_alerts():
        if alert.get("last_fired") == today:
            continue
        if not runs_on(alert, now.date()):
            continue

        target = datetime.combine(
            now.date(),
            dtime(hour=alert.get("hour", 0), minute=alert.get("minute", 0)),
        )
        if now < target:
            continue

        if now - target <= timedelta(minutes=LATE_WINDOW_MINUTES):
            to_notify.append(alert)
        else:
            to_silence.append(alert)

    return to_notify, to_silence