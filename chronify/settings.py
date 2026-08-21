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

from datetime import date
from typing import Any, Optional

from chronify.store import JsonDict

INFRA_PRESETS = [
    ("🟢", "All systems stable"),
    ("🟡", "Some issues"),
    ("🔴", "Incident"),
]
DEFAULT_INFRA = {"emoji": "🟢", "text": "All systems stable"}

_settings = JsonDict("settings.json")


def get(key: str, default: Any = None) -> Any:
    return _settings.get(key, default)


def set_value(key: str, value: Any) -> None:
    _settings.set(key, value)


def is_project_scoped() -> bool:
    return bool(get("project_scoped", False))


def set_project_scoped(enabled: bool) -> None:
    set_value("project_scoped", bool(enabled))


def _infra_key(project) -> str:
    return f"infra_status:{project}" if project else "infra_status"


def get_infra_status(project=None) -> dict:
    status = get(_infra_key(project))
    if isinstance(status, dict) and status.get("emoji"):
        return status
    if project:
        return get_infra_status(None)
    return dict(DEFAULT_INFRA)


def set_infra_status(emoji: str, text: str, project=None) -> None:
    status = {"emoji": emoji, "text": (text or "").strip()}
    set_value(_infra_key(project), status)
    set_value(f"{_infra_key(project)}@{date.today().isoformat()}", status)


def get_infra_status_for_date(target_date: date, project=None) -> Optional[dict]:
    status = get(f"{_infra_key(project)}@{target_date.isoformat()}")
    if isinstance(status, dict) and status.get("emoji"):
        return status
    if project:
        return get_infra_status_for_date(target_date, None)
    return None


def infra_status_line(project=None, target_date: Optional[date] = None) -> str:
    if target_date is not None and target_date != date.today():
        status = get_infra_status_for_date(target_date, project)
        if status is None:
            return ""
    else:
        status = get_infra_status(project)

    return f"{status['emoji']} {status['text']}".strip()


def get_pinned_plan_id() -> str:
    return get("pinned_plan_id", "") or ""


def set_pinned_plan_id(item_id: str) -> None:
    set_value("pinned_plan_id", item_id or "")


def is_real_intervals_enabled() -> bool:
    return bool(get("push_real_intervals", True))


def set_real_intervals_enabled(enabled: bool) -> None:
    set_value("push_real_intervals", bool(enabled))


def is_auto_push_enabled() -> bool:
    return bool(get("auto_push_peopleforce", False))


def set_auto_push_enabled(enabled: bool) -> None:
    set_value("auto_push_peopleforce", bool(enabled))


def get_last_auto_push() -> str:
    return get("last_auto_push_date", "") or ""


def set_last_auto_push(day_iso: str) -> None:
    set_value("last_auto_push_date", day_iso)