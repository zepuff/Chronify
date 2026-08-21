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

from typing import Optional

from chronify.store import JsonDict, JsonList

_projects = JsonList("projects.json")
_state = JsonDict("settings.json")

ACTIVE_KEY = "active_project_id"


def all_projects() -> list:
    return _projects.read_raw()


def is_configured() -> bool:
    return bool(all_projects())


def add_project(name: str, peopleforce_id=None, rate=None) -> Optional[dict]:
    name = (name or "").strip()
    if not name:
        return None
    entry = _projects.append(name=name, peopleforce_id=peopleforce_id, rate=rate)
    if len(all_projects()) == 1:
        set_active(entry["id"])
    return entry


def update_project(project_id: str, name: str, peopleforce_id=None, rate=None) -> bool:
    name = (name or "").strip()
    if not name:
        return False
    return _projects.update(
        project_id, name=name, peopleforce_id=peopleforce_id, rate=rate
    )


def rate_for(project_id: str, config: dict):
    project = get_project(project_id)
    if project and project.get("rate"):
        return project["rate"]
    return (config.get("invoice") or {}).get("hourly_rate", 0)


def delete_project(project_id: str) -> int:
    removed = _projects.delete([project_id])
    if get_active_id() == project_id:
        remaining = all_projects()
        set_active(remaining[0]["id"] if remaining else "")
    return removed


def get_project(project_id: str) -> Optional[dict]:
    if not project_id:
        return None
    return _projects.get(project_id)


def get_active_id() -> str:
    active = _state.get(ACTIVE_KEY, "") or ""
    if active and get_project(active):
        return active

    existing = all_projects()
    if existing:
        set_active(existing[0]["id"])
        return existing[0]["id"]
    return ""


def get_active() -> Optional[dict]:
    return get_project(get_active_id())


def set_active(project_id: str) -> None:
    _state.set(ACTIVE_KEY, project_id or "")


def name_for(project_id: str) -> str:
    project = get_project(project_id)
    return project["name"] if project else "Unassigned"


def peopleforce_id_for(project_id: str, config: dict):
    project = get_project(project_id)
    if project and project.get("peopleforce_id"):
        return project["peopleforce_id"]
    return (config.get("peopleforce") or {}).get("project_id")