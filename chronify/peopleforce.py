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

import calendar as calendar_module
import datetime as dt
from datetime import date, timedelta

import requests

from chronify import db

DEFAULT_BASE_URL = "https://app.peopleforce.io/api/public/v3"
DEFAULT_START_HOUR = 9
TIMEOUT = 30


class NotConfiguredError(ValueError):
    pass


class DayOverflowError(ValueError):
    def __init__(self, requested_seconds: float, available_seconds: float):
        self.requested_seconds = requested_seconds
        self.available_seconds = available_seconds
        lost = max(0.0, requested_seconds - available_seconds) / 3600
        super().__init__(
            f"The entry does not fit before midnight: "
            f"{requested_seconds / 3600:.2f} h requested, only "
            f"{available_seconds / 3600:.2f} h left in the day "
            f"({lost:.2f} h would be lost). Start the working day earlier "
            f"or split the entry."
        )


def is_configured(config: dict) -> bool:
    pf_cfg = config.get("peopleforce", {}) or {}
    return bool(pf_cfg.get("api_key")) and bool(pf_cfg.get("employee_id"))


def _credentials(config: dict) -> tuple:
    pf_cfg = config.get("peopleforce", {}) or {}
    api_key = pf_cfg.get("api_key", "")
    employee_id = pf_cfg.get("employee_id", 0)
    base_url = pf_cfg.get("base_url", DEFAULT_BASE_URL).rstrip("/")

    if not api_key or not employee_id:
        raise NotConfiguredError(
            "PeopleForce is not configured. Fill in your details through "
            "'⚙️ Setup wizard'."
        )
    return api_key, employee_id, base_url


def _raise_for_error(response: requests.Response) -> None:
    if response.status_code >= 400:
        raise RuntimeError(
            f"PeopleForce returned an error {response.status_code}: {response.text[:300]}"
        )


def build_comment_for_date(target_date: date) -> str:
    archive = db.get_daily_archive(target_date)
    return archive["summary_text"] if archive else ""


def push_timesheet_entry(
    target_date: date,
    total_seconds: float,
    comment: str,
    config: dict,
    project_id=None,
    start_at: "dt.datetime | None" = None,
    allow_truncate: bool = False,
) -> dict:
    api_key, employee_id, base_url = _credentials(config)
    pf_cfg = config.get("peopleforce", {}) or {}
    if project_id is None:
        project_id = pf_cfg.get("project_id")
    start_hour = pf_cfg.get("start_hour", DEFAULT_START_HOUR)

    start_dt = start_at or dt.datetime.combine(target_date, dt.time(hour=start_hour))
    day_end = dt.datetime.combine(target_date, dt.time(23, 59, 59))
    wanted_end = start_dt + timedelta(seconds=total_seconds)

    if wanted_end > day_end:
        if not allow_truncate:
            raise DayOverflowError(
                total_seconds, max(0.0, (day_end - start_dt).total_seconds())
            )
        wanted_end = day_end

    end_dt = wanted_end

    payload = {
        "employee_id": employee_id,
        "starts_at": int(start_dt.timestamp()),
        "ends_at": int(end_dt.timestamp()),
        "comment": comment or "",
    }
    if project_id:
        payload["project_id"] = project_id

    response = requests.post(
        f"{base_url}/time/timesheet_entries", json=payload,
        headers={"X-API-KEY": api_key}, timeout=TIMEOUT,
    )
    _raise_for_error(response)
    return response.json()


def delete_timesheet_entry(entry_id: int, config: dict) -> None:
    api_key, _, base_url = _credentials(config)
    response = requests.delete(
        f"{base_url}/time/timesheet_entries/{entry_id}",
        headers={"X-API-KEY": api_key}, timeout=TIMEOUT,
    )
    if response.status_code >= 400:
        raise RuntimeError(
            f"Could not delete the existing entry (id={entry_id}): "
            f"{response.status_code} {response.text[:200]}"
        )


def fetch_timesheet_entries(start_date: date, end_date: date, config: dict) -> list:
    api_key, employee_id, base_url = _credentials(config)

    all_entries = []
    page, total_pages = 1, 1

    while page <= total_pages:
        response = requests.get(
            f"{base_url}/time/timesheet_entries",
            params={
                "starts_on": start_date.isoformat(),
                "ends_on": end_date.isoformat(),
                "employee_ids[]": employee_id,
                "page": page,
            },
            headers={"X-API-KEY": api_key},
            timeout=TIMEOUT,
        )
        _raise_for_error(response)

        payload = response.json()
        if isinstance(payload, dict):
            entries = payload.get("data") or payload.get("timesheet_entries") or []
            total_pages = ((payload.get("metadata") or {}).get("pagination") or {}).get("pages", 1)
        else:
            entries, total_pages = payload, 1

        all_entries.extend(entries)
        page += 1

    return all_entries


def entry_project_id(entry: dict):
    value = entry.get("project_id")
    if value is not None:
        return value
    project = entry.get("project") or {}
    return project.get("id") if isinstance(project, dict) else None


def _parse_moment(value):
    if value in (None, ""):
        return None
    try:
        if isinstance(value, (int, float)):
            return dt.datetime.fromtimestamp(value)
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone().replace(tzinfo=None)
        return parsed
    except (ValueError, OSError, OverflowError):
        return None


def entry_start_datetime(entry: dict):
    for key in ("starts_at", "start_at", "started_at", "clock_in"):
        parsed = _parse_moment(entry.get(key))
        if parsed is not None:
            return parsed
    return None


def entry_span(entry: dict):
    start = entry_start_datetime(entry)
    if start is None:
        return None

    end = entry_end_datetime(entry)
    if end is None:
        minutes = entry.get("minutes")
        if minutes is None:
            return None
        try:
            end = start + timedelta(minutes=float(minutes))
        except (TypeError, ValueError):
            return None

    if end <= start:
        return None
    return start, end


def entry_end_datetime(entry: dict):
    for key in ("ends_at", "end_at", "finished_at", "clock_out"):
        value = entry.get(key)
        if value in (None, ""):
            continue
        try:
            if isinstance(value, (int, float)):
                return dt.datetime.fromtimestamp(value)
            parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if parsed.tzinfo is not None:
                parsed = parsed.astimezone().replace(tzinfo=None)
            return parsed
        except (ValueError, OSError, OverflowError):
            continue
    return None


def entry_date(entry: dict) -> "date | None":
    raw = entry.get("date")
    if raw:
        try:
            return date.fromisoformat(str(raw)[:10])
        except ValueError:
            pass

    for key in ("starts_at", "start_at", "started_at", "clock_in"):
        value = entry.get(key)
        if value in (None, ""):
            continue
        try:
            if isinstance(value, (int, float)):
                return dt.datetime.fromtimestamp(value).date()
            parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if parsed.tzinfo is not None:
                parsed = parsed.astimezone().replace(tzinfo=None)
            return parsed.date()
        except (ValueError, OSError, OverflowError):
            continue

    end = entry_end_datetime(entry)
    return end.date() if end else None


def fetch_entries_for_date(target_date: date, config: dict, project_id=None) -> list:
    entries = fetch_timesheet_entries(target_date, target_date, config)

    entries = [
        e for e in entries
        if entry_date(e) in (target_date, None)
    ]

    if project_id is None:
        return entries
    return [e for e in entries if entry_project_id(e) == project_id]


def fetch_daily_hours(start_date: date, end_date: date, config: dict) -> dict:
    daily: dict = {}
    for entry in fetch_timesheet_entries(start_date, end_date, config):
        day = entry_date(entry)
        minutes = entry.get("minutes")
        if day is None or minutes is None:
            continue
        day_str = day.isoformat()
        daily[day_str] = daily.get(day_str, 0) + minutes * 60
    return daily


def fetch_project_hours(start_date: date, end_date: date, config: dict) -> dict:
    by_project = {}
    for entry in fetch_timesheet_entries(start_date, end_date, config):
        minutes = entry.get("minutes")
        if minutes is None:
            continue
        key = entry_project_id(entry)
        by_project[key] = by_project.get(key, 0) + minutes * 60
    return by_project


def fetch_total_hours_for_month(year: int, month: int, config: dict) -> float:
    start = date(year, month, 1)
    end = date(year, month, calendar_module.monthrange(year, month)[1])
    return round(sum(fetch_daily_hours(start, end, config).values()) / 3600, 1)