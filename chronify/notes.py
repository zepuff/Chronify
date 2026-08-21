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

from datetime import date, datetime
from typing import Optional

from chronify.store import BASE_DIR, JsonList, new_id

LEGACY_NOTES_DIR = BASE_DIR / "notes"
LEGACY_REMINDERS_DIR = BASE_DIR / "reminders"
NOTES_SEPARATOR = "--- write below this line ---"


def _for_project(items: list, project: Optional[str]) -> list:
    if project is None:
        return items
    return [i for i in items if (i.get("project") or "") == project]


def _by_created(item: dict):
    return item.get("created_at", 0)


_tasks = JsonList("tasks.json", sort_key=_by_created, reverse=True)
_blockers = JsonList("blockers.json", sort_key=_by_created, reverse=True)
_reminders = JsonList("reminders.json", sort_key=_by_created, reverse=True)
_plan = JsonList("planner.json")


def add_task(text: str, target_date: Optional[date] = None, project: str = "") -> None:
    text = (text or "").strip()
    if text:
        _tasks.add(
            text=text,
            date=(target_date or date.today()).isoformat(),
            project=project or "",
        )


def read_all_tasks() -> list:
    return _tasks.read()


def read_tasks_for_date(target_date: date, project: Optional[str] = None) -> list:
    day = target_date.isoformat()
    items = [t for t in _tasks.read() if t.get("date") == day]
    if project is None:
        return items
    return [t for t in items if (t.get("project") or "") == project]


def update_task(task_id: str, text: str) -> bool:
    text = (text or "").strip()
    return bool(text) and _tasks.update(task_id, text=text)


def delete_tasks(task_ids) -> int:
    return _tasks.delete(task_ids)


def tasks_as_text(target_date: date, project: Optional[str] = None) -> str:
    tasks = reversed(read_tasks_for_date(target_date, project))
    return "\n".join(f"- {t['text']}" for t in tasks)


def add_blocker(text: str, target_date: Optional[date] = None, project: str = "") -> None:
    text = (text or "").strip()
    if text:
        _blockers.add(
            text=text,
            date=(target_date or date.today()).isoformat(),
            project=project or "",
            resolved_on="",
        )


def read_all_blockers(project: Optional[str] = None,
                      include_resolved: bool = False) -> list:
    items = _for_project(_blockers.read(), project)
    if include_resolved:
        return items
    return [b for b in items if not b.get("resolved_on")]


def is_resolved(blocker: dict) -> bool:
    return bool(blocker.get("resolved_on"))


def set_blocker_resolved(blocker_id: str, resolved: bool) -> bool:
    stamp = date.today().isoformat() if resolved else ""
    return _blockers.update(blocker_id, resolved_on=stamp)


def update_blocker(blocker_id: str, text: str) -> bool:
    text = (text or "").strip()
    return bool(text) and _blockers.update(blocker_id, text=text)


def delete_blockers(blocker_ids) -> int:
    return _blockers.delete(blocker_ids)


def blockers_on(target_date: date, project: Optional[str] = None) -> list:
    day = target_date.isoformat()
    result = []
    for blocker in _for_project(_blockers.read(), project):
        created = blocker.get("date") or ""
        if created and created > day:
            continue
        resolved = blocker.get("resolved_on") or ""
        if resolved and resolved <= day:
            continue
        result.append(blocker)
    return result


def blockers_as_text(project: Optional[str] = None,
                     target_date: Optional[date] = None) -> str:
    items = (
        blockers_on(target_date, project) if target_date
        else read_all_blockers(project)
    )
    return "\n".join(b["text"] for b in reversed(items))


def append_reminder(
    text: str, target_date: Optional[date] = None, project: str = ""
) -> None:
    text = (text or "").strip()
    if text:
        _reminders.add(
            text=text,
            created_on=(target_date or date.today()).isoformat(),
            project=project or "",
        )


def read_all_reminders(project: Optional[str] = None) -> list:
    return _for_project(_reminders.read(), project)


def update_reminder(reminder_id: str, text: str) -> bool:
    text = (text or "").strip()
    return bool(text) and _reminders.update(reminder_id, text=text)


def delete_reminders(reminder_ids) -> int:
    return _reminders.delete(reminder_ids)


def reminders_as_text(project: Optional[str] = None) -> str:
    return "\n".join(r["text"] for r in reversed(read_all_reminders(project)))


def read_plan_items(project: Optional[str] = None,
                    target_date: Optional[date] = None) -> list:
    items = _for_project(_all_plan_items(), project)
    if target_date is None:
        return items
    day = target_date.isoformat()
    return [i for i in items if (i.get("date") or day) == day]


def _all_plan_items() -> list:
    items = _plan.read_raw()
    dirty = False
    today = date.today().isoformat()

    for item in items:
        if not item.get("id"):
            item["id"] = new_id()
            dirty = True
        if not item.get("date"):
            item["date"] = today
            dirty = True

    if dirty:
        _plan.write(items)
    return items


def roll_over_plan(target_date: Optional[date] = None) -> int:
    day = (target_date or date.today()).isoformat()
    items = _all_plan_items()

    moved = 0
    for item in items:
        if item.get("done"):
            continue
        if (item.get("date") or day) < day:
            item["date"] = day
            moved += 1

    if moved:
        _plan.write(items)
    return moved


def write_plan_items(items: list) -> None:
    _plan.write(items)


def add_plan_item(text: str, project: str = "") -> None:
    text = (text or "").strip()
    if not text:
        return
    items = _all_plan_items()
    items.append({
        "id": new_id(), "text": text, "done": False, "project": project or "",
        "date": date.today().isoformat(),
    })
    _plan.write(items)


def toggle_plan_item_by_id(item_id: str) -> bool:
    items = _all_plan_items()
    for item in items:
        if item.get("id") == item_id:
            item["done"] = not item.get("done")
            _plan.write(items)
            return item["done"]
    return False


def get_plan_item(item_id: str) -> Optional[dict]:
    for item in _all_plan_items():
        if item.get("id") == item_id:
            return item
    return None


def clear_done_plan_items(project: Optional[str] = None,
                          target_date: Optional[date] = None) -> int:
    items = _all_plan_items()
    scoped_ids = {
        item["id"] for item in read_plan_items(project, target_date)
    }
    remaining = [
        item for item in items
        if not (item.get("done") and item["id"] in scoped_ids)
    ]
    _plan.write(remaining)
    return len(items) - len(remaining)


def pending_plan_items(project: Optional[str] = None,
                       target_date: Optional[date] = None) -> list:
    return [
        item for item in read_plan_items(project, target_date)
        if not item.get("done")
    ]


def pending_plan_as_text(project: Optional[str] = None,
                         target_date: Optional[date] = None) -> str:
    return "\n".join(
        item["text"] for item in pending_plan_items(project, target_date)
    )


def _migrate(legacy_dir, marker_name: str, store: JsonList, date_field: str) -> int:
    marker = BASE_DIR / marker_name
    if marker.exists() or not legacy_dir.exists():
        return 0

    imported = []
    for path in sorted(legacy_dir.glob("*.md")):
        try:
            day = date.fromisoformat(path.stem).isoformat()
        except ValueError:
            day = date.today().isoformat()

        text = path.read_text(encoding="utf-8")
        if NOTES_SEPARATOR in text:
            text = text.split(NOTES_SEPARATOR, 1)[1]

        for line in text.splitlines():
            line = line.strip().lstrip("-•*").strip()
            if line:
                imported.append({
                    "id": new_id(),
                    "text": line,
                    date_field: day,
                    "created_at": 0.0,
                })

    if imported:
        store.write(imported + store.read_raw())

    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(
        f"Imported {len(imported)} entries from {legacy_dir.name}/*.md "
        f"{datetime.now().isoformat(timespec='seconds')}\n"
        f"Original files were not deleted, they are still in {legacy_dir}\n",
        encoding="utf-8",
    )
    return len(imported)


def migrate_legacy_notes() -> int:
    return _migrate(LEGACY_NOTES_DIR, ".tasks_migrated", _tasks, "date")


def migrate_legacy_reminders() -> int:
    return _migrate(LEGACY_REMINDERS_DIR, ".reminders_migrated", _reminders, "created_on")