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

import os
import subprocess
import threading
import time
from functools import partial
from datetime import date, datetime, time as dtime, timedelta

import rumps
from PyObjCTools import AppHelper

from chronify import alerts
from chronify import db
from chronify import invoice
from chronify import invoice_import
from chronify import notes
from chronify import peopleforce
from chronify import projects
from chronify import settings
from chronify.main_setup import SetupMixin
from chronify.config import (
    DEBUG, ProfileWriteError, load_config, read_profile, save_profile_value,
)
from chronify.summarizer import compose_daily, generate_daily_summary, generate_summary_for_date
from chronify.tracker import (
    ActivityTracker,
    DEFAULT_CALL_APPS,
    DEFAULT_CONDITIONAL_CALL_APPS,
    DEFAULT_CALL_TITLE_MARKERS,
)
from chronify.ui_windows import (
    AlertEditorController,
    choose_docx_file,
    QuickInputController,
    make_window_always_on_top,
)

ARCHIVE_LOOKBACK_DAYS = 60
DAY_VIEW_DAYS = 30

LIST_MENUS = {
    "tasks": {
        "add_label": "+ Log a completed task",
        "empty": "(nothing logged today yet)",
        "kind": "task",
        "input_title": "Log a completed task",
        "input_message": "Describe what you finished:",
        "saved_note": "Logged ✅",
        "read": lambda: notes.read_tasks_for_date(date.today(), _scope()),
        "add": lambda text: notes.add_task(text, project=projects.get_active_id()),
        "update": notes.update_task,
        "delete": notes.delete_tasks,
    },
    "reminders": {
        "add_label": "+ Add a reminder",
        "empty": "(no reminders)",
        "kind": "reminder",
        "input_title": "Note to self",
        "input_message": "Context or an idea for the daily status:",
        "saved_note": "Reminder saved ✅",
        "read": lambda: notes.read_all_reminders(_scope()),
        "add": lambda text: notes.append_reminder(text, project=projects.get_active_id()),
        "update": notes.update_reminder,
        "delete": notes.delete_reminders,
    },
    "blockers": {
        "add_label": "+ Add a blocker",
        "empty": "(no blockers — the status will say 'None')",
        "kind": "blocker",
        "input_title": "New blocker",
        "input_message": "What is blocking the work?",
        "saved_note": "Blocker logged 🚧",
        "read": lambda: notes.read_all_blockers(_scope()),
        "add": lambda text: notes.add_blocker(text, project=projects.get_active_id()),
        "update": notes.update_blocker,
        "delete": notes.delete_blockers,
        "resolvable": True,
    },
}

def _format_stats_text(totals: dict) -> str:
    if not totals:
        return "No activity recorded for this day."
    lines = [f"{task} — {db.format_duration(sec)}" for task, sec in totals.items()]
    lines.append("")
    lines.append(f"Total: {db.format_duration(sum(totals.values()))}")
    return "\n".join(lines)


def _previous_month(today: date) -> tuple:
    last_month_date = today.replace(day=1) - timedelta(days=1)
    return last_month_date.year, last_month_date.month


def _scope():
    if not settings.is_project_scoped():
        return None
    return projects.get_active_id()


def _play_alert_sound() -> None:
    name = load_config().get("alert_sound", "Glass")
    if not name:
        return

    path = f"/System/Library/Sounds/{name}.aiff"
    try:
        subprocess.Popen(
            ["afplay", path],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        if DEBUG:
            print(f"[sound] {e}")


def _notify(text: str, sound: bool = False, title: str = "") -> None:
    stamp = {"stamp": time.time()}
    attempts = (
        dict(data=stamp, sound=sound),
        dict(data=stamp),
        {},
    )

    for kwargs in attempts:
        try:
            rumps.notification("Work Tracker", title, text, **kwargs)
            break
        except Exception as e:
            if DEBUG:
                print(f"[notify] {text!r} kwargs={list(kwargs)} -> {type(e).__name__}: {e}")

    if sound:
        _play_alert_sound()


def copy_to_clipboard(text: str) -> None:
    env = dict(os.environ)
    env["LANG"] = "en_US.UTF-8"
    process = subprocess.Popen("pbcopy", env=env, stdin=subprocess.PIPE)
    process.communicate(text.encode("utf-8"))


def _run_async(worker) -> None:
    threading.Thread(target=worker, daemon=True).start()


class WorkTrackerApp(SetupMixin, rumps.App):
    def __init__(self):
        super().__init__("⏱", quit_button=None)

        config = load_config()

        db.init_db()

        notes.roll_over_plan()

        migrated_reminders = notes.migrate_legacy_reminders()
        migrated_tasks = notes.migrate_legacy_notes()
        if migrated_reminders or migrated_tasks:
            _notify(
                f"Migrated to the new storage: {migrated_tasks} tasks, "
                f"{migrated_reminders} reminders"
            )

        self._input_controller = None
        self._alert_editor = None

        self._generation_running = False
        self._generation_token = 0

        self.day_view_menu = rumps.MenuItem("📆 Open a specific day")
        self.pause_item = rumps.MenuItem(
            "⏸ Pause (personal use)", callback=self.toggle_pause
        )

        self.invoice_menu = rumps.MenuItem("🧾 Invoice")
        self.invoice_menu.add(rumps.MenuItem(
            "Create for this month",
            callback=self._make_month_callback(self._prompt_and_create_invoice, False),
        ))
        self.invoice_menu.add(rumps.MenuItem(
            "Create for last month",
            callback=self._make_month_callback(self._prompt_and_create_invoice, True),
        ))
        self._add_separator(self.invoice_menu)
        self.invoice_menu.add(rumps.MenuItem(
            "📥 Import details from an existing invoice…",
            callback=self.import_invoice_details,
        ))
        self._add_separator(self.invoice_menu)
        self.invoice_menu.add(rumps.MenuItem(
            "Refresh PDF for this month (after editing details)",
            callback=self._make_month_callback(self._refresh_invoice_pdf, False),
        ))
        self.invoice_menu.add(rumps.MenuItem(
            "Refresh PDF for last month (after editing details)",
            callback=self._make_month_callback(self._refresh_invoice_pdf, True),
        ))

        self.peopleforce_menu = rumps.MenuItem("📤 Push to PeopleForce")
        self.pf_days_menu = rumps.MenuItem("Days this month")
        self.pf_auto_item = rumps.MenuItem(
            "Auto-push at 00:00", callback=self.toggle_auto_push
        )
        self.pf_intervals_item = rumps.MenuItem(
            "Push real time ranges", callback=self.toggle_real_intervals
        )

        self.project_menu = rumps.MenuItem("🏷 Active project")
        self.tasks_menu = rumps.MenuItem("✅ Completed tasks")
        self.reminders_menu = rumps.MenuItem("💭 Notes to self")
        self.blockers_menu = rumps.MenuItem("🚧 Blockers")
        self.alerts_menu = rumps.MenuItem("⏰ Timed reminders")
        self.plan_menu = rumps.MenuItem("📋 Today's plan")
        self.pin_menu = rumps.MenuItem("📌 Show in the menu bar")
        self.infra_menu = rumps.MenuItem("🚦 Infrastructure status")
        self.settings_menu = rumps.MenuItem("⚙️ Settings")

        self.calendar_menu = rumps.MenuItem("📅 Hours calendar")
        self.calendar_menu.add(rumps.MenuItem(
            "This month",
            callback=self._make_month_callback(self._show_combined_calendar, False),
        ))
        self.calendar_menu.add(rumps.MenuItem(
            "Last month",
            callback=self._make_month_callback(self._show_combined_calendar, True),
        ))

        self.notes_menu = rumps.MenuItem("📝 Daily statuses")
        self.notes_menu.add(
            rumps.MenuItem("Open status history", callback=self.open_history)
        )
        self.notes_menu.add(
            rumps.MenuItem("🛑 Stop generating", callback=self.cancel_generation)
        )

        self.menu = [
            self.pause_item,
            self.project_menu,
            None,
            "✨ Generate daily status",
            self.tasks_menu,
            self.reminders_menu,
            self.blockers_menu,
            self.plan_menu,
            self.alerts_menu,
            self.infra_menu,
            None,
            "📊 Today's stats",
            self.day_view_menu,
            self.calendar_menu,
            None,
            self.invoice_menu,
            self.peopleforce_menu,
            self.notes_menu,
            None,
            self.settings_menu,
            "🔄 Reload rules",
            "📁 Open saved data folder",
            None,
            rumps.MenuItem("Quit", callback=self.quit_app),
        ]

        self.rebuild_project_menu()
        self._rebuild_day_view_menu()
        for key in LIST_MENUS:
            self._rebuild_list_menu(key)
        self.rebuild_alerts_menu()
        self.rebuild_plan_menu()
        self.rebuild_infra_menu()
        self.rebuild_peopleforce_menu()
        self.rebuild_settings_menu()

        self.tracker = ActivityTracker(
            poll_interval=config.get("poll_interval", 5),
            min_segment_seconds=config.get("min_segment_seconds", 8),
            idle_threshold_seconds=config.get("idle_threshold_seconds", 300),
            on_update=self.on_activity_update,
            on_idle_return=self.handle_idle_return,
            on_missing_project=self.handle_missing_project,
            project_provider=projects.get_active_id,
            watch_screen=config.get("treat_media_as_active", True),
            call_apps=config.get("call_apps") or DEFAULT_CALL_APPS,
            conditional_call_apps=(
                config.get("call_apps_conditional") or DEFAULT_CONDITIONAL_CALL_APPS
            ),
            call_title_markers=(
                config.get("call_title_markers") or DEFAULT_CALL_TITLE_MARKERS
            ),
        )
        self.tracker.start()

        self.refresh_title()
        self.check_and_archive_past_days()
        self.check_invoice_reminder()
        self.check_auto_push()
        self.check_alerts()

        self._first_run_timer = rumps.Timer(self.check_first_run, 2)
        self._first_run_timer.start()

        self._timers = [
            rumps.Timer(self.refresh_title, 30),
            rumps.Timer(self.check_and_archive_past_days, 600),
            rumps.Timer(self.check_invoice_reminder, 3600),
            rumps.Timer(self._rebuild_day_view_menu, 900),
            rumps.Timer(self.check_auto_push, 600),
            rumps.Timer(self.check_plan_rollover, 900),
        ]
        for timer in self._timers:
            timer.start()

        self._alerts_stop = threading.Event()
        self._alerts_thread = threading.Thread(target=self._alerts_loop, daemon=True)
        self._alerts_thread.start()

    @staticmethod
    def _clear_menu(menu):
        try:
            menu.clear()
        except Exception:
            try:
                if getattr(menu, "_menu", None) is not None:
                    menu.clear()
            except Exception:
                pass

    @staticmethod
    def _add_separator(menu):
        try:
            menu.add(rumps.separator)
        except Exception:
            pass

    @staticmethod
    def _shorten(text, limit=48):
        text = " ".join((text or "").split())
        return text if len(text) <= limit else text[: limit - 1] + "…"

    def _quick_input(self, title, message, on_save):
        self._input_controller = QuickInputController.alloc().initWithCallback_title_message_(
            on_save, title, message
        )
        self._input_controller.show()

    def _make_month_callback(self, handler, previous):
        def _callback(_sender):
            today = date.today()
            year, month = _previous_month(today) if previous else (today.year, today.month)
            handler(year, month)

        return _callback

    def handle_idle_return(self, idle_info: dict):
        duration_min = round(idle_info["duration"] / 60, 1)

        def ask_user():
            window = rumps.Window(
                title="Were you away or working?",
                message=(
                    f"No mouse or keyboard activity for {duration_min} min.\n"
                    f"App: {idle_info['app_name']} ({idle_info['task_name']})\n\n"
                    f"Count this time as work (reading, for example)?"
                ),
                ok="Yes, that was work",
                cancel="No, that was idle",
            )
            make_window_always_on_top(window)
            if not window.run().clicked:
                return

            db.insert_segment(
                app_name=idle_info["app_name"],
                window_title=idle_info["window_title"],
                task_name=idle_info["task_name"],
                start_ts=idle_info["start_ts"],
                end_ts=idle_info["end_ts"],
                is_idle=False,
            )
            self.refresh_title()
            _notify("Time added to your stats ⏱")

        AppHelper.callAfter(ask_user)

    def handle_missing_project(self, orphan_seconds):
        def warn():
            _notify(
                f"{db.format_duration(orphan_seconds)} recorded with no project "
                f"— pick one in 🏷 Active project so the hours can be pushed",
                title="⚠️ No active project",
            )

        AppHelper.callAfter(warn)

    def on_activity_update(self, app_name, task_name):
        if DEBUG and task_name != getattr(self, "_last_task", None):
            print(f"[tracker] app={app_name!r} task={task_name!r}")
        self._last_task = task_name

    def refresh_title(self, _sender=None):
        if self.tracker.is_manually_paused():
            self.title = "⏸"
            return
        if self.tracker.is_idle():
            self.title = "💤"
            return

        totals = db.get_task_totals_for_date(date.today(), _scope())
        total_seconds = sum(totals.values())
        time_part = f"⏱ {db.format_duration(total_seconds)}" if total_seconds else "⏱"

        if not projects.is_configured():
            self.title = "⏱ ⚠️ no project"
            return

        if len(projects.all_projects()) > 1:
            active = projects.get_active()
            if active:
                time_part = f"🏷 {self._shorten(active['name'], 14)}  ·  {time_part}"

        pinned = notes.get_plan_item(settings.get_pinned_plan_id())
        if pinned and not pinned.get("done"):
            self.title = f"📌 {self._shorten(pinned['text'], 28)}  ·  {time_part}"
        else:
            self.title = time_part

    def toggle_pause(self, sender):
        if self.tracker.is_manually_paused():
            self.tracker.resume()
            sender.title = "⏸ Pause (personal use)"
            _notify("Tracking resumed ▶️")
        else:
            self.tracker.pause()
            sender.title = "▶️ Resume tracking"
            _notify("Tracking paused ⏸ — use your laptop freely")
        self.refresh_title()

    def _rebuild_list_menu(self, key, _sender=None):
        spec = LIST_MENUS[key]
        menu = getattr(self, f"{key}_menu")

        self._clear_menu(menu)
        menu.add(rumps.MenuItem(spec["add_label"], callback=self._make_add_callback(key)))
        self._add_separator(menu)

        items = spec["read"]()
        if not items:
            menu.add(rumps.MenuItem(spec["empty"]))
            return

        rebuild = lambda _sender=None, _key=key: self._rebuild_list_menu(_key)

        for item in items:
            entry = rumps.MenuItem(
                self._shorten(item["text"]),
                callback=self._make_edit_callback(
                    spec["kind"], item["id"], item["text"],
                    spec["update"], spec["delete"], rebuild,
                ),
            )
            menu.add(entry)

        if spec.get("resolvable"):
            self._add_separator(menu)
            menu.add(self._build_resolve_menu(items))
            menu.add(rumps.MenuItem(
                "📜 Resolved blockers…", callback=self.show_resolved_blockers
            ))

    def _build_resolve_menu(self, items):
        resolve_menu = rumps.MenuItem("✅ Mark as resolved")
        if not items:
            resolve_menu.add(rumps.MenuItem("(nothing to resolve)"))
            return resolve_menu

        for item in items:
            resolve_menu.add(rumps.MenuItem(
                self._shorten(item["text"], 40),
                callback=self._make_resolve_callback(item["id"]),
            ))
        return resolve_menu

    def _make_resolve_callback(self, blocker_id):
        def _callback(_sender):
            notes.set_blocker_resolved(blocker_id, True)
            self._rebuild_list_menu("blockers")
            _notify("Blocker resolved ✅ — it will not appear in new statuses")

        return _callback

    def show_resolved_blockers(self, _sender=None):
        everything = notes.read_all_blockers(_scope(), include_resolved=True)
        resolved = [b for b in everything if notes.is_resolved(b)]

        if not resolved:
            rumps.alert(
                title="No resolved blockers",
                message="Blockers you mark as resolved are kept here so the "
                        "history stays intact.",
            )
            return

        listing = "\n".join(
            f"{b.get('resolved_on', '?')}  —  {b['text']}" for b in resolved
        )
        reopen = rumps.alert(
            title=f"Resolved blockers ({len(resolved)})",
            message=f"{listing}\n\nReopen the most recent one?",
            ok="Reopen the newest",
            cancel="Close",
        )
        if reopen:
            notes.set_blocker_resolved(resolved[0]["id"], False)
            self._rebuild_list_menu("blockers")
            _notify("Blocker reopened 🚧")

    def rebuild_tasks_menu(self, _sender=None):
        self._rebuild_list_menu("tasks")

    def rebuild_reminders_menu(self, _sender=None):
        self._rebuild_list_menu("reminders")

    def rebuild_blockers_menu(self, _sender=None):
        self._rebuild_list_menu("blockers")

    def _make_add_callback(self, key):
        spec = LIST_MENUS[key]

        def _callback(_sender):
            def save(text):
                spec["add"](text)
                self._rebuild_list_menu(key)
                _notify(spec["saved_note"])

            self._quick_input(spec["input_title"], spec["input_message"], save)

        return _callback

    def _make_edit_callback(self, kind, item_id, current_text, update_fn, delete_fn, rebuild_fn):
        def _callback(_sender):
            window = rumps.Window(
                title=f"Edit {kind}",
                message="Edit the text and save.\n"
                        "Clearing the field deletes the entry (you will be asked "
                        "to confirm).",
                default_text=current_text,
                dimensions=(360, 120),
                ok="Save",
                cancel="Cancel",
            )
            make_window_always_on_top(window)
            response = window.run()
            if not response.clicked:
                return

            text = (response.text or "").strip()
            if text:
                update_fn(item_id, text)
                _notify("Saved ✅")
            else:
                confirmed = rumps.alert(
                    title=f"Delete this {kind}?",
                    message=f"“{self._shorten(current_text, 120)}”\n\n"
                            f"This cannot be undone.",
                    ok="Delete",
                    cancel="Keep it",
                )
                if not confirmed:
                    return
                delete_fn([item_id])
                _notify("Deleted 🗑")

            rebuild_fn()
            self.refresh_title()

        return _callback

    def _ask_scoping_mode(self):
        separate = rumps.alert(
            title="Keep projects separate?",
            message="Tasks, notes to self, blockers and the infrastructure "
                    "status can either belong to a single project, or be shared "
                    "across all of them.\n\n"
                    "SEPARATE — switching the project also switches what you "
                    "see in the menus, and each project gets its own daily "
                    "status. Best when the projects are unrelated.\n\n"
                    "SHARED — one list of tasks and blockers for everything, "
                    "exactly how it works now. Only the hours are split by "
                    "project.\n\n"
                    "You can change this later in the menu.",
            ok="Separate",
            cancel="Shared",
        )
        settings.set_project_scoped(bool(separate))
        self.rebuild_all_lists()

    def toggle_scoping(self, sender):
        enabled = not settings.is_project_scoped()
        settings.set_project_scoped(enabled)
        sender.state = 1 if enabled else 0
        self.rebuild_all_lists()
        _notify(
            "Tasks and notes are now separate per project 🏷"
            if enabled else "Tasks and notes are shared across projects"
        )

    def rebuild_all_lists(self):
        for key in LIST_MENUS:
            self._rebuild_list_menu(key)
        self.rebuild_plan_menu()
        self.rebuild_infra_menu()
        self.refresh_title()

    def _adopt_unassigned(self):
        orphans = db.count_unassigned_segments()
        if not orphans:
            return

        options = projects.all_projects()
        names = ", ".join(p["name"] for p in options)
        answer = rumps.alert(
            title="Older hours have no project",
            message=f"{orphans} recorded segments were tracked before projects "
                    f"existed.\n\nAssign all of them to {options[0]['name']}?\n"
                    f"You can move any single day later from "
                    f"🏷 Active project → Move a day.\n\nProjects: {names}",
            ok=f"Assign to {options[0]['name']}",
            cancel="Leave them",
        )
        if answer:
            moved = db.adopt_unassigned_segments(options[0]["id"])
            _notify(f"{moved} older segments moved to {options[0]['name']}")

    def _ask_text(self, title, message, default="", ok="Save", cancel="Skip", height=24):
        window = rumps.Window(
            title=title,
            message=message,
            default_text=str(default or ""),
            dimensions=(320, height),
            ok=ok,
            cancel=cancel,
        )
        make_window_always_on_top(window)
        response = window.run()
        return response.text.strip() if response.clicked else None

    def rebuild_project_menu(self, _sender=None):
        self._clear_menu(self.project_menu)
        active_id = projects.get_active_id()
        items = projects.all_projects()

        if not items:
            self.project_menu.add(
                rumps.MenuItem("⚠️ No project — tracking is paused",
                               callback=self.add_project)
            )
            self._add_separator(self.project_menu)
            self.project_menu.add(
                rumps.MenuItem("+ Add a project", callback=self.add_project)
            )
            return

        for project in items:
            item = rumps.MenuItem(
                project["name"], callback=self._make_project_callback(project["id"])
            )
            item.state = 1 if project["id"] == active_id else 0
            self.project_menu.add(item)

        self._add_separator(self.project_menu)
        scope_item = rumps.MenuItem(
            "Separate tasks & notes per project", callback=self.toggle_scoping
        )
        scope_item.state = 1 if settings.is_project_scoped() else 0
        self.project_menu.add(scope_item)

        self._add_separator(self.project_menu)
        self.project_menu.add(rumps.MenuItem("+ Add a project", callback=self.add_project))

        edit_menu = rumps.MenuItem("✏️ Edit a project")
        for project in items:
            edit_menu.add(rumps.MenuItem(
                project["name"], callback=self._make_edit_project_callback(project["id"])
            ))
        self.project_menu.add(edit_menu)

        self.project_menu.add(self._build_move_day_menu(items))

    def _build_move_day_menu(self, items):
        move_menu = rumps.MenuItem("🔀 Move a day")
        today = date.today()
        totals_by_day = db.get_daily_totals_for_range(today - timedelta(days=13), today)
        added = 0

        for offset in range(14):
            target = today - timedelta(days=offset)
            seconds = totals_by_day.get(target.isoformat(), 0)
            if not seconds:
                continue

            suffix = {0: " (today)", 1: " (yesterday)"}.get(offset, "")
            day_item = rumps.MenuItem(
                f"{target.isoformat()}{suffix} — {db.format_duration(seconds)}"
            )
            for project in items:
                day_item.add(rumps.MenuItem(
                    f"→ {project['name']}",
                    callback=self._make_move_day_callback(target, project["id"]),
                ))
            day_item.add(rumps.MenuItem(
                "→ no project (personal time)",
                callback=self._make_move_day_callback(target, ""),
            ))
            move_menu.add(day_item)
            added += 1

        if not added:
            move_menu.add(rumps.MenuItem("(no tracked days in the last two weeks)"))

        self._add_separator(move_menu)
        range_menu = rumps.MenuItem("📅 Move a date range…")
        for project in items:
            range_menu.add(rumps.MenuItem(
                f"→ {project['name']}",
                callback=self._make_move_range_callback(project["id"]),
            ))
        range_menu.add(rumps.MenuItem(
            "→ no project (personal time)",
            callback=self._make_move_range_callback(""),
        ))
        move_menu.add(range_menu)

        return move_menu

    def _make_move_range_callback(self, project_id):
        def _callback(_sender):
            label = projects.name_for(project_id) if project_id else "no project"
            today = date.today()
            raw = self._ask_text(
                f"Move a date range to {label}",
                "Two dates, from and to, inclusive.\n"
                "Format: YYYY-MM-DD .. YYYY-MM-DD",
                default=f"{(today - timedelta(days=6)).isoformat()} .. {today.isoformat()}",
                ok="Move", cancel="Cancel",
            )
            if not raw:
                return

            parts = [p.strip() for p in raw.replace("..", " ").split() if p.strip()]
            try:
                start = date.fromisoformat(parts[0])
                end = date.fromisoformat(parts[-1])
            except (ValueError, IndexError):
                rumps.alert(
                    title="Could not read the dates",
                    message="Expected two dates like 2026-08-01 .. 2026-08-14.",
                )
                return

            if end < start:
                start, end = end, start

            confirmed = rumps.alert(
                title="Move these days?",
                message=f"Everything tracked from {start.isoformat()} to "
                        f"{end.isoformat()} will be reassigned to {label}.",
                ok="Move", cancel="Cancel",
            )
            if not confirmed:
                return

            moved = db.reassign_range(start, end, project_id)
            self.rebuild_project_menu()
            self.refresh_title()
            _notify(f"{moved} segments moved to {label}")

        return _callback

    def _make_move_day_callback(self, target_date, project_id):
        def _callback(_sender):
            moved = db.reassign_day(target_date, project_id)
            self.rebuild_project_menu()
            self.refresh_title()
            label = projects.name_for(project_id) if project_id else "no project"
            _notify(f"{target_date.isoformat()}: {moved} segments → {label}")

        return _callback

    def _make_project_callback(self, project_id):
        def _callback(_sender):
            projects.set_active(project_id)
            self.rebuild_project_menu()
            if settings.is_project_scoped():
                self.rebuild_all_lists()
            else:
                self.refresh_title()
            _notify(f"Active project: {projects.name_for(project_id)} 🏷")

        return _callback

    def _make_edit_project_callback(self, project_id):
        def _callback(_sender):
            self.edit_project(project_id)

        return _callback

    def _delete_project(self, project):
        tracked = project["id"] in db.known_project_ids()
        last_one = len(projects.all_projects()) == 1

        message = f"Delete {project['name']}?"
        if tracked:
            message += (
                "\n\nHours already recorded against it are NOT moved to another "
                "project — that would falsify its numbers. They stay in your "
                "calendar and stats as unassigned time, and are never pushed "
                "to PeopleForce."
            )
        if last_one:
            message += (
                "\n\nThis is your last project, so tracking pauses until you "
                "create a new one."
            )

        if not rumps.alert(title="Delete project", message=message,
                           ok="Delete", cancel="Cancel"):
            return

        detached = db.reassign_all(project["id"], "") if tracked else 0
        projects.delete_project(project["id"])

        self.rebuild_project_menu()
        self.refresh_title()

        if detached:
            _notify(f"Deleted {project['name']} — {detached} segments are now unassigned")
        else:
            _notify(f"Deleted {project['name']}")

    def rebuild_alerts_menu(self, _sender=None):
        self._clear_menu(self.alerts_menu)
        self.alerts_menu.add(rumps.MenuItem("+ New timed reminder", callback=self.add_alert))
        self._add_separator(self.alerts_menu)

        items = alerts.read_all_alerts()
        if not items:
            self.alerts_menu.add(rumps.MenuItem("(empty — press '+ New reminder')"))
            return

        for alert in items:
            self.alerts_menu.add(rumps.MenuItem(
                f"{alerts.format_schedule(alert)}  ·  "
                f"{self._shorten(alert['text'], 32)}",
                callback=self._make_alert_edit_callback(alert["id"]),
            ))

    def add_alert(self, _sender):
        self._open_alert_editor(None)

    def _open_alert_editor(self, alert_id):
        self._alert_editor = AlertEditorController.alloc().initWithApp_alertId_(self, alert_id)
        self._alert_editor.show()

    def _make_alert_edit_callback(self, alert_id):
        def _callback(_sender):
            self._open_alert_editor(alert_id)

        return _callback

    def _alerts_loop(self):
        while not self._alerts_stop.wait(20):
            try:
                self.check_alerts()
            except Exception as e:
                if DEBUG:
                    print(f"[alerts] {e}")

    def check_alerts(self, _sender=None):
        now = datetime.now()
        today = now.date().isoformat()
        to_notify, to_silence = alerts.due_alerts(now)

        removed_one_shot = False

        for alert in to_silence:
            alerts.finish(alert, today)
            removed_one_shot = removed_one_shot or bool(alert.get("one_shot"))

        for alert in to_notify:
            alerts.finish(alert, today)
            removed_one_shot = removed_one_shot or bool(alert.get("one_shot"))
            AppHelper.callAfter(
                partial(_notify, alert["text"], True,
                        f"⏰ {alerts.format_time(alert)}")
            )

        if removed_one_shot:
            AppHelper.callAfter(self.rebuild_alerts_menu)

    def rebuild_plan_menu(self, _sender=None):
        self._clear_menu(self.plan_menu)
        self.plan_menu.add(rumps.MenuItem("+ Add an item", callback=self.add_plan_item))
        self._add_separator(self.plan_menu)

        items = notes.read_plan_items(_scope(), date.today())
        if not items:
            self.plan_menu.add(rumps.MenuItem("(the plan is empty)"))
        else:
            for item in items:
                menu_item = rumps.MenuItem(
                    self._shorten(item["text"]),
                    callback=self._make_plan_toggle_callback(item["id"]),
                )
                menu_item.state = 1 if item.get("done") else 0
                self.plan_menu.add(menu_item)

        self._add_separator(self.plan_menu)
        self.plan_menu.add(
            rumps.MenuItem("🧹 Clear completed", callback=self.clear_done_plan_items)
        )
        self.rebuild_pin_menu()
        self.plan_menu.add(self.pin_menu)

    def add_plan_item(self, _sender):
        def save(text):
            notes.add_plan_item(text, project=projects.get_active_id())
            self.rebuild_plan_menu()
            _notify("Added to the plan 📋")

        self._quick_input("New plan item", "What do you plan to do?", save)

    def _make_plan_toggle_callback(self, item_id):
        def _callback(_sender):
            notes.toggle_plan_item_by_id(item_id)
            self.rebuild_plan_menu()
            self.refresh_title()

        return _callback

    def check_plan_rollover(self, _sender=None):
        moved = notes.roll_over_plan()
        if moved:
            self.rebuild_plan_menu()
            self.refresh_title()

    def clear_done_plan_items(self, _sender):
        removed = notes.clear_done_plan_items(_scope(), date.today())
        if not notes.get_plan_item(settings.get_pinned_plan_id()):
            settings.set_pinned_plan_id("")
        self.rebuild_plan_menu()
        self.refresh_title()
        _notify(f"Completed items cleared: {removed}")

    def rebuild_pin_menu(self, _sender=None):
        self._clear_menu(self.pin_menu)
        pinned_id = settings.get_pinned_plan_id()

        none_item = rumps.MenuItem("Show nothing", callback=self._make_pin_callback(""))
        none_item.state = 0 if pinned_id else 1
        self.pin_menu.add(none_item)

        pending = notes.pending_plan_items(_scope(), date.today())
        if not pending:
            self.pin_menu.add(rumps.MenuItem("(no unfinished items)"))
            return

        for item in pending:
            pin_item = rumps.MenuItem(
                self._shorten(item["text"], 36),
                callback=self._make_pin_callback(item["id"]),
            )
            pin_item.state = 1 if item["id"] == pinned_id else 0
            self.pin_menu.add(pin_item)

    def _make_pin_callback(self, item_id):
        def _callback(_sender):
            settings.set_pinned_plan_id(item_id)
            self.rebuild_pin_menu()
            self.refresh_title()

        return _callback

    def rebuild_infra_menu(self, _sender=None):
        self._clear_menu(self.infra_menu)
        current = settings.get_infra_status(_scope())

        for emoji, text in settings.INFRA_PRESETS:
            item = rumps.MenuItem(
                f"{emoji} {text}", callback=self._make_infra_callback(emoji, text)
            )
            item.state = 1 if current.get("emoji") == emoji else 0
            self.infra_menu.add(item)

        self._add_separator(self.infra_menu)
        self.infra_menu.add(
            rumps.MenuItem("✏️ Custom text…", callback=self.set_custom_infra_status)
        )

    def _make_infra_callback(self, emoji, text):
        def _callback(_sender):
            settings.set_infra_status(emoji, text, _scope())
            self.rebuild_infra_menu()

        return _callback

    def set_custom_infra_status(self, _sender):
        current = settings.get_infra_status(_scope())
        window = rumps.Window(
            title="Infrastructure status",
            message="Describe the state. A leading emoji (🟢 🟡 🔴) sets the status colour.",
            default_text=f"{current['emoji']} {current['text']}",
            dimensions=(340, 24),
            ok="Save",
            cancel="Cancel",
        )
        make_window_always_on_top(window)
        response = window.run()
        if not (response.clicked and response.text.strip()):
            return

        text = response.text.strip()
        emoji = current["emoji"]
        for candidate, _ in settings.INFRA_PRESETS:
            if text.startswith(candidate):
                emoji = candidate
                text = text[len(candidate):].strip()
                break

        settings.set_infra_status(emoji, text, _scope())
        self.rebuild_infra_menu()

    def _rebuild_day_view_menu(self, _sender=None):
        self._clear_menu(self.day_view_menu)
        today = date.today()

        for i in range(DAY_VIEW_DAYS):
            target_date = today - timedelta(days=i)
            suffix = {0: " (today)", 1: " (yesterday)"}.get(i, "")

            day_item = rumps.MenuItem(f"{target_date.isoformat()}{suffix}")
            day_item.add(rumps.MenuItem(
                "📄 Summary and hours",
                callback=self._make_day_view_callback(target_date),
            ))
            day_item.add(rumps.MenuItem(
                "✏️ Edit tracked segments…",
                callback=self._make_segment_editor_callback(target_date),
            ))
            self.day_view_menu.add(day_item)

    def _make_day_view_callback(self, target_date):
        def _callback(_sender):
            self.show_day_detail(target_date)

        return _callback

    def _make_segment_editor_callback(self, target_date):
        def _callback(_sender):
            self.edit_day_segments(target_date)

        return _callback

    @staticmethod
    def _segment_line(segment, project_names):
        start = datetime.fromtimestamp(segment["start_ts"]).strftime("%H:%M")
        end = datetime.fromtimestamp(segment["end_ts"]).strftime("%H:%M")
        project = project_names.get(segment.get("project") or "", "no project")
        return (
            f"{segment['id']} | {start}-{end} | "
            f"{db.format_duration(segment['duration_sec'])} | "
            f"{segment['task_name']} | {project}"
        )

    def edit_day_segments(self, target_date):
        segments = db.get_segments_for_date(target_date)
        if not segments:
            rumps.alert(
                title=f"{target_date.isoformat()}",
                message="Nothing was tracked on this day.",
            )
            return

        project_names = {p["id"]: p["name"] for p in projects.all_projects()}
        project_names[""] = "no project"
        by_name = {name.lower(): pid for pid, name in project_names.items()}

        listing = "\n".join(
            self._segment_line(s, project_names) for s in segments
        )
        total = sum(s["duration_sec"] for s in segments)

        window = rumps.Window(
            title=f"Segments on {target_date.isoformat()}",
            message=(
                f"{len(segments)} segments, {db.format_duration(total)} in total.\n\n"
                f"id | from-to | length | task | project\n\n"
                f"• delete a line to remove that segment\n"
                f"• change the project at the end of a line to move it\n"
                f"Known projects: {', '.join(sorted(project_names.values()))}"
            ),
            default_text=listing,
            dimensions=(560, 320),
            ok="Apply",
            cancel="Cancel",
        )
        make_window_always_on_top(window)
        response = window.run()
        if not response.clicked:
            return

        kept, moves, unknown = set(), {}, []
        for line in (response.text or "").splitlines():
            parts = [p.strip() for p in line.split("|")]
            if len(parts) < 5 or not parts[0].isdigit():
                continue

            segment_id = int(parts[0])
            kept.add(segment_id)

            wanted = by_name.get(parts[4].lower())
            if wanted is None:
                unknown.append(parts[4])
                continue
            moves.setdefault(wanted, []).append(segment_id)

        removed_ids = [s["id"] for s in segments if s["id"] not in kept]
        if removed_ids:
            confirmed = rumps.alert(
                title=f"Delete {len(removed_ids)} segments?",
                message="The removed lines will be erased from the database. "
                        "This cannot be undone.",
                ok="Delete", cancel="Keep everything",
            )
            if not confirmed:
                removed_ids = []

        deleted = db.delete_segments(removed_ids)

        moved = 0
        current = {s["id"]: (s.get("project") or "") for s in segments}
        for project_id, ids in moves.items():
            changed = [i for i in ids if current.get(i) != project_id and i not in removed_ids]
            moved += db.reassign_segments(changed, project_id)

        self.refresh_title()
        self.rebuild_project_menu()

        summary = f"Deleted: {deleted}, moved: {moved}"
        if unknown:
            summary += f"\nUnknown project names, left untouched: {', '.join(set(unknown))}"
        rumps.alert(title="Segments updated", message=summary)

    @staticmethod
    def _is_error_summary(text: str) -> bool:
        return bool(text) and (
            text.startswith("[Error") or text.startswith("Generation failed")
        )

    def show_day_detail(self, target_date):
        stats_text = _format_stats_text(db.get_task_totals_for_date(target_date))
        archive = db.get_daily_archive(target_date)

        if archive and not self._is_error_summary(archive["summary_text"]):
            self._show_day_alert(target_date, stats_text, archive["summary_text"])
            return

        if target_date >= date.today():
            self._show_day_alert(
                target_date, stats_text,
                "(the day is still going, the status appears once it ends)",
            )
            return

        _notify("Generating the status for that day...")

        def worker():
            try:
                summary = generate_summary_for_date(target_date)
            except Exception as e:
                summary = f"Generation failed: {e}"
            if not self._is_error_summary(summary):
                db.save_daily_archive(target_date, summary)
            AppHelper.callAfter(self._show_day_alert, target_date, stats_text, summary)

        _run_async(worker)

    def _show_day_alert(self, target_date, stats_text, status_text):
        rumps.alert(
            title=f"Day {target_date.isoformat()}",
            message=f"⏱ Tracked time:\n{stats_text}\n\n📝 Status:\n{status_text}",
        )

    @rumps.clicked("📊 Today's stats")
    def show_today_stats(self, _sender):
        rumps.alert(
            title="Today's stats",
            message=_format_stats_text(db.get_task_totals_for_date(date.today())),
        )

    def import_invoice_details(self, _sender=None):
        path = choose_docx_file("Choose a filled-in invoice (.docx)")
        if not path:
            return

        try:
            lines = invoice_import.read_lines(path)
        except Exception as e:
            rumps.alert(title="Could not read the file", message=str(e))
            return

        if invoice_import.is_blank_template(lines):
            rumps.alert(
                title="That is the empty template",
                message="This file still contains {{...}} tokens, so there is "
                        "nothing to read from it. Pick an invoice you have "
                        "already filled in and sent.",
            )
            return

        found = invoice_import.extract_fields(lines)
        rows = invoice_import.merge_with_config(found, load_config())
        self._show_invoice_details_window(rows, len(found))

    def _show_invoice_details_window(self, rows, found_count):
        missing = [r["label"] for r in rows if not r["value"]]
        summary = f"Read {found_count} of {len(rows)} fields from the invoice."
        if missing:
            summary += "\nStill empty: " + ", ".join(missing)

        window = rumps.Window(
            title="Check the details before saving",
            message=f"{summary}\n\nEdit anything that is wrong and fill in what is "
                    f"missing. Keep the 'Label: value' format, one per line. "
                    f"Clear a value to leave that field untouched.",
            default_text=invoice_import.rows_to_text(rows),
            dimensions=(460, 300),
            ok="Save to profile",
            cancel="Cancel",
        )
        make_window_always_on_top(window)
        response = window.run()
        if not response.clicked:
            return

        values = invoice_import.text_to_values(response.text, rows)
        saved, rejected = 0, []

        for row in rows:
            path = tuple(row["path"])
            value = values.get(path, "")
            if not value or value == row["value"] and row["source"] == "config":
                continue

            coerced = invoice_import.coerce(path, value)
            if coerced is None:
                rejected.append(row["label"])
                continue

            try:
                save_profile_value(list(path), coerced)
            except ProfileWriteError as e:
                rejected.append(f"{row['label']} ({e})")
                continue
            saved += 1

        load_config(force=True)

        message = (f"Saved {saved} fields to ~/.work_tracker/profile.json.\n\n"
                   f"Nothing was written to config.yaml, so none of this can end "
                   f"up in git.")
        if rejected:
            message += "\n\nSkipped (expected a number): " + ", ".join(rejected)

        rumps.alert(title="Invoice details updated", message=message)

    def _refresh_invoice_pdf(self, year, month):
        config = load_config()

        docx_path = invoice.get_invoice_docx_path(year, month, config)

        if not docx_path.exists():
            rumps.alert(
                title="File not found",
                message=f"Could not find {docx_path.name} in {docx_path.parent}. "
                        f"Create the invoice first via 'Create for...'.",
            )
            return

        _notify("Refreshing the PDF...")

        def worker():
            pdf_path = invoice.convert_docx_to_pdf(docx_path)
            if pdf_path:
                AppHelper.callAfter(_notify, f"PDF refreshed: {pdf_path.name}")
                AppHelper.callAfter(subprocess.run, ["open", str(pdf_path)])
            else:
                AppHelper.callAfter(
                    rumps.alert,
                    "Could not create the PDF",
                    "LibreOffice was not found. Install it for free: "
                    "brew install --cask libreoffice",
                )

        _run_async(worker)

        def worker():
            pdf_path = invoice.convert_docx_to_pdf(docx_path)
            if pdf_path:
                AppHelper.callAfter(_notify, f"PDF refreshed: {pdf_path.name}")
                AppHelper.callAfter(subprocess.run, ["open", str(pdf_path)])
            else:
                AppHelper.callAfter(
                    rumps.alert,
                    "Could not create the PDF",
                    "LibreOffice was not found. Install it for free: "
                    "brew install --cask libreoffice",
                )

        _run_async(worker)

    def _prompt_and_create_invoice(self, year, month):
        config = load_config()
        if not self.section_is_ready("invoice"):
            self.require_section(
                "invoice", lambda: self._prompt_and_create_invoice(year, month)
            )
            return
        pf_cfg = config.get("peopleforce", {}) or {}
        use_pf = (
            bool(pf_cfg.get("use_for_invoice_hours")) and peopleforce.is_configured(config)
        )

        def worker():
            breakdown, source = None, "local tracker"
            problems = []

            if use_pf:
                try:
                    breakdown = self._peopleforce_breakdown(year, month, config)
                    if breakdown:
                        source = "from PeopleForce"
                except Exception as e:
                    problems.append(str(e))

            if not breakdown:
                hours = invoice.compute_suggested_hours(
                    year, month, config,
                    on_error=lambda e: problems.append(str(e)),
                )
                breakdown = self._tracker_breakdown(year, month, hours, config)
                if problems and use_pf:
                    source = "local tracker — PeopleForce unavailable"

            AppHelper.callAfter(
                self._show_invoice_window, year, month, breakdown, source,
                config, problems,
            )

        _run_async(worker)

    @staticmethod
    def _peopleforce_breakdown(year, month, config):
        start, end = invoice.month_bounds(year, month)
        totals = peopleforce.fetch_project_hours(start, end, config)
        if not totals:
            return []

        by_pf_id = {}
        for project in projects.all_projects():
            pf_id = project.get("peopleforce_id")
            if pf_id is not None:
                by_pf_id[str(pf_id)] = project

        rows, unknown = [], 0.0
        for pf_id, seconds in totals.items():
            if seconds <= 0:
                continue

            project = by_pf_id.get(str(pf_id)) if pf_id is not None else None
            if project is None:
                unknown += seconds
                continue

            rows.append({
                "name": project["name"],
                "hours": round(seconds / 3600, 2),
                "rate": projects.rate_for(project["id"], config),
            })

        if unknown > 0:
            rows.append({
                "name": "Other (not matched to a project)",
                "hours": round(unknown / 3600, 2),
                "rate": (config.get("invoice") or {}).get("hourly_rate", 0),
            })

        return rows

    @staticmethod
    def _tracker_breakdown(year, month, total_hours, config):
        start, end = invoice.month_bounds(year, month)
        totals = db.get_project_totals_for_range(start, min(end, date.today()))

        tracked = {pid: sec for pid, sec in totals.items() if pid and sec > 0}
        if not tracked:
            single = projects.get_active()
            return [{
                "name": single["name"] if single else "IT services",
                "hours": round(total_hours, 2),
                "rate": projects.rate_for(single["id"], config) if single else None,
            }]

        tracked_total = sum(tracked.values())
        scale = (total_hours * 3600 / tracked_total) if tracked_total else 1

        return [{
            "name": projects.name_for(pid),
            "hours": round(seconds * scale / 3600, 2),
            "rate": projects.rate_for(pid, config),
        } for pid, seconds in tracked.items()]

    def _show_invoice_window(self, year, month, breakdown, source_note, config,
                             problems=None):
        month_label = f"{invoice.MONTH_NAMES.get(month, month)} {year}"
        currency = (config.get("invoice") or {}).get("currency", "USD")

        lines = "\n".join(
            f"{index}. {item['name']}: {item['hours']}"
            for index, item in enumerate(breakdown, 1)
        )
        estimate = sum(
            (item["hours"] or 0) * float(item.get("rate") or 0) for item in breakdown
        )

        message = (
            f"Suggested split ({source_note}), about "
            f"{round(estimate, 2)} {currency} in total.\n"
            f"Edit the hours if needed — keep the line numbers, they decide "
            f"which project a line belongs to. Delete a line to leave that "
            f"project off the invoice."
        )
        if problems:
            message = (
                "⚠️ PeopleForce could not be read:\n"
                + "\n".join(p[:160] for p in problems[:2])
                + "\n\n" + message
            )

        window = rumps.Window(
            title=f"Hours worked in {month_label}",
            message=message,
            default_text=lines,
            dimensions=(380, 60 + 26 * len(breakdown)),
            ok="Create invoice",
            cancel="Cancel",
        )
        make_window_always_on_top(window)
        response = window.run()
        if not response.clicked:
            return

        edited = []
        for line in (response.text or "").splitlines():
            stripped = line.strip()
            if not stripped or ":" not in stripped:
                continue

            number, _, rest = stripped.partition(".")
            if not number.strip().isdigit():
                rumps.alert(
                    title="Error",
                    message=f"Line without a number: {stripped[:80]}\n\n"
                            f"Keep the '1. Project: hours' format.",
                )
                return

            index = int(number.strip()) - 1
            if not 0 <= index < len(breakdown):
                rumps.alert(title="Error", message=f"There is no project number {index + 1}.")
                return

            item = breakdown[index]
            _, _, value = rest.rpartition(":")
            try:
                item["hours"] = float(value.strip().replace(",", "."))
            except ValueError:
                rumps.alert(
                    title="Error",
                    message=f"{item['name']}: hours must be a number.",
                )
                return
            if item["hours"] > 0:
                edited.append(item)

        if not edited:
            rumps.alert(title="Nothing to invoice", message="Every project has zero hours.")
            return

        total_hours = sum(item["hours"] for item in edited)
        _notify("Creating the invoice...")

        def worker():
            try:
                result = invoice.create_invoice(
                    year, month, total_hours, config, breakdown=edited
                )
            except Exception as e:
                AppHelper.callAfter(rumps.alert, "Could not create the invoice", str(e))
                return
            AppHelper.callAfter(self._show_invoice_result, month_label, result)

        _run_async(worker)

    def _show_invoice_result(self, month_label, result):
        docx_path, pdf_path = result.get("docx"), result.get("pdf")
        made = [p.name for p in (docx_path, pdf_path) if p]

        if made:
            files_line = "Created:\n  " + "\n  ".join(made)
        else:
            files_line = "Nothing was created."

        if docx_path and not pdf_path:
            files_line += (
                "\n\nNo PDF was generated because LibreOffice was not found. "
                "Install it for free (`brew install --cask libreoffice`) and "
                "next time the PDF will appear alongside automatically."
            )

        if pdf_path:
            subprocess.run(["open", str(pdf_path)])

        notes_lines = []

        missing = result.get("missing_tokens") or []
        if missing:
            empty = ", ".join(t.strip("{}") for t in missing[:12])
            notes_lines.append(
                ("Left blank because the field is empty:\n  " if docx_path is None
                 else "Still showing as {{...}} because the field is empty:\n  ")
                + empty
                + "\nFill them in via ⚙️ Settings and create the invoice again."
            )

        if not result.get("row_token_found", True):
            notes_lines.append(
                "⚠️ The template has no per-project row, so the breakdown "
                "could not be added. Only the totals are in the document."
            )

        body = files_line
        if notes_lines:
            body += "\n\n" + "\n\n".join(notes_lines)
        else:
            body += "\n\nAll fields were filled in."

        rumps.alert(title=f"Invoice for {month_label} is ready", message=body)

    def check_invoice_reminder(self, _sender=None):
        if not invoice.should_show_reminder_now():
            return

        today = date.today()
        invoice.mark_reminder_shown(today)

        _notify(
            "Raise it from 🧾 Invoice whenever you are ready.",
            sound=True,
            title="Today is the last working day of the month 🧾",
        )

    def _show_combined_calendar(self, year, month):
        names = {p["id"]: p["name"] for p in projects.all_projects()}
        names[""] = "no project"
        config = load_config()

        start, end = invoice.month_bounds(year, month)
        logged = {}
        cursor = start
        while cursor <= end:
            items = notes.read_tasks_for_date(cursor)
            if items:
                logged[cursor.isoformat()] = [t["text"] for t in reversed(items)]
            cursor += timedelta(days=1)

        def worker():
            remote = None
            if peopleforce.is_configured(config):
                try:
                    start, end = invoice.month_bounds(year, month)
                    remote = peopleforce.fetch_daily_hours(start, end, config)
                except Exception as e:
                    AppHelper.callAfter(_notify, f"PeopleForce: {str(e)[:120]}")

            path = db.export_calendar_html(
                year, month, project_names=names, remote_totals=remote,
                logged_by_day=logged,
            )
            AppHelper.callAfter(subprocess.run, ["open", str(path)])

        _run_async(worker)

    def open_history(self, _sender):
        subprocess.run(["open", str(db.export_archive_to_markdown())])

    def check_and_archive_past_days(self, _sender=None):
        def worker():
            today = date.today()
            start = today - timedelta(days=ARCHIVE_LOOKBACK_DAYS)
            archived = db.get_archived_summaries(start, today - timedelta(days=1))

            cursor_date = start
            while cursor_date < today:
                existing = archived.get(cursor_date.isoformat())
                if existing is None or self._is_error_summary(existing):
                    has_data = (
                        db.get_task_totals_for_date(cursor_date)
                        or notes.tasks_as_text(cursor_date)
                    )
                    if has_data:
                        try:
                            summary = generate_summary_for_date(cursor_date)
                        except Exception as e:
                            summary = f"[Error while archiving: {e}]"
                        if not self._is_error_summary(summary):
                            db.save_daily_archive(cursor_date, summary)
                cursor_date += timedelta(days=1)

        _run_async(worker)

    @rumps.clicked("✨ Generate daily status")
    def generate_daily(self, _sender):
        if self._generation_running:
            rumps.alert(
                title="Already generating",
                message="A status is being written right now. Wait for it, or "
                        "use 📝 Daily statuses → Stop generating.",
            )
            return

        self._generation_running = True
        self._generation_token += 1
        token = self._generation_token
        _notify("Generating the daily status...")

        def worker():
            try:
                summary = generate_daily_summary(_scope())
            except Exception as e:
                summary = f"Generation failed: {e}"

            def deliver():
                self._generation_running = False
                if token != self._generation_token:
                    return
                self._show_editable_daily(summary)

            AppHelper.callAfter(deliver)

        _run_async(worker)

    def cancel_generation(self, _sender=None):
        if not self._generation_running:
            _notify("Nothing is being generated right now")
            return
        self._generation_token += 1
        self._generation_running = False
        _notify("Generation cancelled 🛑")

    def _show_editable_daily(self, summary):
        window = rumps.Window(
            title="Daily Summary",
            message="You can edit the text before copying:",
            default_text=summary,
            dimensions=(400, 300),
            ok="Copy to clipboard",
            cancel="Close without copying",
        )
        make_window_always_on_top(window)
        response = window.run()
        if response.clicked:
            copy_to_clipboard(response.text)
            _notify("Copied to clipboard ✅")

    @rumps.clicked("🔄 Reload rules")
    def reload_rules(self, _sender):
        self.tracker.mapper.reload()
        _notify("Grouping rules reloaded")

    @rumps.clicked("📁 Open saved data folder")
    def open_data_folder(self, _sender):
        subprocess.run(["open", str(db.DB_PATH.parent)])

    def rebuild_peopleforce_menu(self, _sender=None):
        self._clear_menu(self.peopleforce_menu)
        self.peopleforce_menu.add(
            rumps.MenuItem("Today", callback=self.push_peopleforce_today)
        )
        self.peopleforce_menu.add(
            rumps.MenuItem("Yesterday", callback=self.push_peopleforce_yesterday)
        )
        self._add_separator(self.peopleforce_menu)

        self._rebuild_pf_days_menu()
        self.peopleforce_menu.add(self.pf_days_menu)
        self.peopleforce_menu.add(rumps.MenuItem(
            "📦 Push every day this month", callback=self.push_peopleforce_month
        ))
        self._add_separator(self.peopleforce_menu)

        self.pf_intervals_item.state = 1 if settings.is_real_intervals_enabled() else 0
        self.peopleforce_menu.add(self.pf_intervals_item)

        self.pf_auto_item.state = 1 if settings.is_auto_push_enabled() else 0
        self.peopleforce_menu.add(self.pf_auto_item)

    def _rebuild_pf_days_menu(self):
        self._clear_menu(self.pf_days_menu)
        today = date.today()
        totals = db.get_daily_totals_for_range(today.replace(day=1), today)

        if not totals:
            self.pf_days_menu.add(rumps.MenuItem("(no data for this month)"))
            return

        for day_str, seconds in sorted(totals.items(), reverse=True):
            self.pf_days_menu.add(rumps.MenuItem(
                f"{day_str} — {db.format_duration(seconds)}",
                callback=self._make_pf_day_callback(date.fromisoformat(day_str)),
            ))

    def _make_pf_day_callback(self, target_date):
        def _callback(_sender):
            self._push_to_peopleforce(target_date)

        return _callback

    def toggle_real_intervals(self, sender):
        enabled = not settings.is_real_intervals_enabled()
        settings.set_real_intervals_enabled(enabled)
        sender.state = 1 if enabled else 0

        if enabled:
            _notify("Pushing real time ranges ⏱")
        else:
            _notify("Pushing one entry per project ⏱")

    def toggle_auto_push(self, sender):
        enabled = not settings.is_auto_push_enabled()
        config = load_config()

        if enabled and not peopleforce.is_configured(config):
            self.require_section("peopleforce", lambda: self.toggle_auto_push(sender))
            return

        settings.set_auto_push_enabled(enabled)
        sender.state = 1 if enabled else 0
        _notify(
            "Auto-push enabled — every day after midnight for the previous day ✅"
            if enabled else "Auto-push disabled"
        )

    AUTO_PUSH_CATCHUP_DAYS = 7

    def _auto_push_targets(self):
        yesterday = date.today() - timedelta(days=1)
        last_pushed = settings.get_last_auto_push()

        start = yesterday - timedelta(days=self.AUTO_PUSH_CATCHUP_DAYS - 1)
        if last_pushed:
            try:
                start = max(start, date.fromisoformat(last_pushed) + timedelta(days=1))
            except ValueError:
                pass

        days, cursor = [], start
        while cursor <= yesterday:
            days.append(cursor)
            cursor += timedelta(days=1)
        return days

    def check_auto_push(self, _sender=None):
        if not settings.is_auto_push_enabled():
            return

        config = load_config()
        if not peopleforce.is_configured(config):
            return

        for target in self._auto_push_targets():
            self._auto_push_day(target, config)

    def _auto_push_day(self, target, config):
        blocks = self._project_blocks(target, only_active=False)
        if not blocks:
            settings.set_last_auto_push(target.isoformat())
            return

        def worker():
            try:
                day_entries = peopleforce.fetch_entries_for_date(target, config)
            except Exception:
                day_entries = []
            starts, overflow = self._start_times(target, blocks, config, day_entries)
            if overflow > 0:
                AppHelper.callAfter(
                    _notify,
                    f"Auto-push skipped {target.isoformat()}: "
                    f"{db.format_duration(overflow)} does not fit before midnight",
                )
                return
            pushed, failed = [], []
            skipped = 0

            entries_by_project = {}
            comments = {}
            broken = set()

            for block in blocks:
                project_id = block["project_id"]
                if project_id in comments:
                    continue
                comments[project_id] = self._comment_for(target, project_id)
                try:
                    entries_by_project[project_id] = (
                        peopleforce.fetch_entries_for_date(
                            target, config, block["peopleforce_id"]
                        )
                    )
                except Exception as e:
                    failed.append(f"{block['name']}: {e}")
                    broken.add(project_id)

            pending = [b for b in blocks if b["project_id"] not in broken]
            missing, covered = self._missing_blocks(pending, entries_by_project)
            missing_ids = {id(b) for b in missing}
            skipped += len(covered)

            for block, start_at in zip(blocks, starts):
                if id(block) not in missing_ids:
                    continue
                try:
                    peopleforce.push_timesheet_entry(
                        target, block["seconds"], comments[block["project_id"]],
                        config,
                        project_id=block["peopleforce_id"], start_at=start_at,
                    )
                    pushed.append(
                        f"{self._block_label(block)} "
                        f"{db.format_duration(block['seconds'])}"
                    )
                except Exception as e:
                    failed.append(f"{self._block_label(block)}: {e}")

            if not failed:
                settings.set_last_auto_push(target.isoformat())

            if pushed:
                suffix = f" (+{skipped} already there)" if skipped else ""
                AppHelper.callAfter(
                    _notify,
                    f"Auto-push for {target.isoformat()}: "
                    f"{', '.join(pushed)}{suffix} ✅"
                )
            if failed:
                AppHelper.callAfter(
                    _notify, f"Auto-push for {target.isoformat()} failed: {failed[0]}"
                )

        _run_async(worker)

    def push_peopleforce_month(self, _sender):
        config = load_config()
        if not peopleforce.is_configured(config):
            self.require_section(
                "peopleforce", lambda: self.push_peopleforce_month(_sender)
            )
            return

        today = date.today()
        totals = db.get_daily_totals_for_range(today.replace(day=1), today)
        if not totals:
            rumps.alert(title="No data", message="No activity was recorded this month.")
            return

        confirm = rumps.alert(
            title="Push the whole month?",
            message=(
                f"Days with activity: {len(totals)}\n"
                f"Total: {round(sum(totals.values()) / 3600, 2)} h\n\n"
                f"Days that already have an entry in PeopleForce will be "
                f"skipped — nothing gets overwritten."
            ),
            ok="Push",
            cancel="Cancel",
        )
        if not confirm:
            return

        def worker():
            sent, skipped, failed, no_project = [], [], [], []
            topped_up = 0

            for day_str in sorted(totals):
                target = date.fromisoformat(day_str)

                blocks = self._project_blocks(target, only_active=False)
                if not blocks:
                    no_project.append(day_str)
                    continue

                try:
                    day_entries = peopleforce.fetch_entries_for_date(target, config)
                except Exception as e:
                    failed.append(f"{day_str}: {e}")
                    continue

                starts, overflow = self._start_times(target, blocks, config, day_entries)
                if overflow > 0:
                    failed.append(
                        f"{day_str}: {db.format_duration(overflow)} does not fit "
                        f"before midnight"
                    )
                    continue

                entries_by_project = {}
                comments = {}
                broken = set()

                for block in blocks:
                    project_id = block["project_id"]
                    if project_id in comments:
                        continue
                    comments[project_id] = self._comment_for(target, project_id)
                    try:
                        entries_by_project[project_id] = (
                            peopleforce.fetch_entries_for_date(
                                target, config, block["peopleforce_id"]
                            )
                        )
                    except Exception as e:
                        failed.append(f"{day_str} / {block['name']}: {e}")
                        broken.add(project_id)

                pending = [b for b in blocks if b["project_id"] not in broken]
                missing, covered = self._missing_blocks(pending, entries_by_project)
                missing_ids = {id(b) for b in missing}
                if missing and covered:
                    topped_up += 1

                day_sent = False
                for block, start_at in zip(blocks, starts):
                    if id(block) not in missing_ids:
                        continue
                    try:
                        peopleforce.push_timesheet_entry(
                            target, block["seconds"],
                            comments[block["project_id"]], config,
                            project_id=block["peopleforce_id"], start_at=start_at,
                        )
                        day_sent = True
                    except Exception as e:
                        failed.append(
                            f"{day_str} / {self._block_label(block)}: {e}"
                        )

                (sent if day_sent else skipped).append(day_str)

            lines = [
                f"Pushed: {len(sent)}",
                f"Skipped (already fully in PeopleForce): {len(skipped)}",
            ]
            if topped_up:
                lines.append(f"Topped up (missing stretches added): {topped_up}")
            if no_project:
                lines.append(
                    f"Skipped (no project with a PeopleForce id): {len(no_project)}"
                )
            if failed:
                lines.append(f"Errors: {len(failed)}")
                lines += failed[:5]

            AppHelper.callAfter(rumps.alert, "Monthly push", "\n".join(lines))
            AppHelper.callAfter(self.rebuild_peopleforce_menu)

        _notify("Pushing the days of this month...")
        _run_async(worker)

    def push_peopleforce_today(self, _sender):
        self._push_to_peopleforce(date.today())

    def push_peopleforce_yesterday(self, _sender):
        self._push_to_peopleforce(date.today() - timedelta(days=1))

    def _push_to_peopleforce(self, target_date):
        config = load_config()

        if not peopleforce.is_configured(config):
            self.require_section(
                "peopleforce", lambda: self._push_to_peopleforce(target_date)
            )
            return

        scoped = settings.is_project_scoped()
        blocks = self._project_blocks(target_date, only_active=scoped)

        if not blocks:
            if scoped:
                active = projects.get_active()
                name = active["name"] if active else "the active project"
                rumps.alert(
                    title="Nothing to push",
                    message=f"No hours were recorded for {name} on "
                            f"{target_date.isoformat()}.\n\nSwitch the active "
                            f"project from the 🏷 menu to push a different one.",
                )
            else:
                rumps.alert(
                    title="No data",
                    message=f"No activity was recorded for {target_date.isoformat()}, "
                            f"there is nothing to push.",
                )
            return

        _notify(f"Checking PeopleForce for {target_date.isoformat()}...")

        def worker():
            existing_by_project = {}
            comment_by_project = {}

            for block in blocks:
                project_id = block["project_id"]

                if project_id not in existing_by_project:
                    try:
                        existing_by_project[project_id] = (
                            peopleforce.fetch_entries_for_date(
                                target_date, config, block["peopleforce_id"]
                            )
                        )
                    except Exception:
                        existing_by_project[project_id] = []
                    comment_by_project[project_id] = self._comment_for(
                        target_date, project_id
                    )

                block["comment"] = comment_by_project[project_id]
                block["covered"] = self._block_is_covered(
                    block, existing_by_project[project_id]
                )
                block["existing"] = []

            for project_id, entries in existing_by_project.items():
                for block in blocks:
                    if block["project_id"] == project_id:
                        block["existing"] = entries
                        break

            try:
                day_entries = peopleforce.fetch_entries_for_date(target_date, config)
            except Exception:
                day_entries = []

            AppHelper.callAfter(
                self._show_pf_window, target_date, blocks, config, day_entries
            )

        _run_async(worker)

    def _project_blocks(self, target_date, only_active=False):
        if settings.is_real_intervals_enabled():
            blocks = self._interval_blocks(target_date, only_active)
            if blocks:
                return blocks

        totals = db.get_project_totals_for_date(target_date)
        config = load_config()

        active_id = projects.get_active_id() if only_active else None

        blocks = []
        for project_id, seconds in totals.items():
            if seconds <= 0 or not project_id:
                continue
            if active_id is not None and project_id != active_id:
                continue

            peopleforce_id = projects.peopleforce_id_for(project_id, config)
            if not peopleforce_id:
                continue

            blocks.append({
                "project_id": project_id,
                "name": projects.name_for(project_id),
                "seconds": seconds,
                "peopleforce_id": peopleforce_id,
            })
        return blocks

    def _interval_blocks(self, target_date, only_active=False):
        config = load_config()
        pf_cfg = config.get("peopleforce") or {}

        gap = float(pf_cfg.get("interval_merge_gap_minutes", 15)) * 60
        minimum = float(pf_cfg.get("min_interval_minutes", 5)) * 60

        active_id = projects.get_active_id() if only_active else None
        intervals = db.get_project_intervals_for_date(target_date, gap, minimum)

        blocks = []
        for interval in intervals:
            project_id = interval["project"]
            if not project_id:
                continue
            if active_id is not None and project_id != active_id:
                continue

            peopleforce_id = projects.peopleforce_id_for(project_id, config)
            if not peopleforce_id:
                continue

            start_at = datetime.fromtimestamp(interval["start_ts"]).replace(
                second=0, microsecond=0
            )
            end_at = datetime.fromtimestamp(interval["end_ts"]).replace(
                second=0, microsecond=0
            )
            if end_at <= start_at:
                end_at = start_at + timedelta(minutes=1)

            blocks.append({
                "project_id": project_id,
                "name": projects.name_for(project_id),
                "seconds": (end_at - start_at).total_seconds(),
                "peopleforce_id": peopleforce_id,
                "start_at": start_at,
                "end_at": end_at,
            })

        return blocks

    COVERED_OVERLAP_RATIO = 0.5

    @staticmethod
    def _overlap_seconds(start_a, end_a, start_b, end_b):
        latest_start = max(start_a, start_b)
        earliest_end = min(end_a, end_b)
        if earliest_end <= latest_start:
            return 0.0
        return (earliest_end - latest_start).total_seconds()

    @classmethod
    def _block_is_covered(cls, block, entries):
        start_at = block.get("start_at")
        end_at = block.get("end_at")

        if not start_at or not end_at:
            return bool(entries)

        span_seconds = (end_at - start_at).total_seconds()
        if span_seconds <= 0:
            return True

        covered = 0.0
        for entry in entries:
            span = peopleforce.entry_span(entry)
            if span is None:
                return True
            covered += cls._overlap_seconds(start_at, end_at, span[0], span[1])

        return covered / span_seconds >= cls.COVERED_OVERLAP_RATIO

    @classmethod
    def _missing_blocks(cls, blocks, entries_by_project):
        missing, covered = [], []
        for block in blocks:
            entries = entries_by_project.get(block["project_id"], [])
            if cls._block_is_covered(block, entries):
                covered.append(block)
            else:
                missing.append(block)
        return missing, covered

    @staticmethod
    def _block_label(block):
        start_at = block.get("start_at")
        end_at = block.get("end_at")
        if not start_at or not end_at:
            return block["name"]
        return (
            f"{block['name']} {start_at.strftime('%H:%M')}-{end_at.strftime('%H:%M')}"
        )

    def _comment_for(self, target_date, project_id):
        if len(projects.all_projects()) < 2:
            return peopleforce.build_comment_for_date(target_date)

        try:
            if settings.is_project_scoped():
                comment = compose_daily(load_config(), target_date, project_id)
            else:
                comment = generate_summary_for_date(target_date, project_id)
        except Exception:
            return ""
        return "" if self._is_error_summary(comment) else comment

    @staticmethod
    def _unique_projects(blocks):
        ordered = []
        for block in blocks:
            if block["project_id"] not in [p["project_id"] for p in ordered]:
                ordered.append(block)
        return ordered

    @classmethod
    def _comments_to_text(cls, blocks):
        unique = cls._unique_projects(blocks)
        if len(unique) == 1:
            return unique[0]["comment"]
        return "\n\n".join(
            f"=== {block['name']} ===\n{block['comment']}".rstrip()
            for block in unique
        )

    @classmethod
    def _text_to_comments(cls, text, blocks):
        unique = cls._unique_projects(blocks)

        if len(unique) == 1:
            comment = (text or "").strip()
            for block in blocks:
                block["comment"] = comment
            return

        by_name = {block["name"]: block["project_id"] for block in unique}
        current = None
        collected = {}

        for line in (text or "").splitlines():
            stripped = line.strip()
            if stripped.startswith("===") and stripped.endswith("==="):
                name = stripped.strip("= ").strip()
                current = by_name.get(name)
                if current is not None:
                    collected[current] = []
                continue
            if current is not None:
                collected[current].append(line)

        for project_id, lines in collected.items():
            comment = "\n".join(lines).strip()
            for block in blocks:
                if block["project_id"] == project_id:
                    block["comment"] = comment

    DAY_END_LIMIT = dtime(23, 59, 59)

    @staticmethod
    def _first_free_slot(target_date, config, day_entries, replacing_ids):
        start_hour = (config.get("peopleforce") or {}).get("start_hour", 9)
        cursor = datetime.combine(target_date, datetime.min.time()).replace(hour=start_hour)

        latest, minutes = None, 0
        for entry in day_entries or []:
            if entry.get("id") in replacing_ids:
                continue
            end = peopleforce.entry_end_datetime(entry)
            if end and (latest is None or end > latest):
                latest = end
            minutes += entry.get("minutes") or 0

        if latest and latest > cursor:
            return latest
        if minutes:
            return cursor + timedelta(minutes=minutes)
        return cursor

    @classmethod
    def _start_times(cls, target_date, blocks, config, day_entries=None):
        if blocks and all(block.get("start_at") for block in blocks):
            return [block["start_at"] for block in blocks], 0.0

        replacing = {
            entry.get("id")
            for block in blocks for entry in block.get("existing") or []
        }
        cursor = cls._first_free_slot(target_date, config, day_entries, replacing)

        needed = sum(max(0.0, b["seconds"]) for b in blocks)
        day_end = datetime.combine(target_date, cls.DAY_END_LIMIT)
        day_start = datetime.combine(target_date, datetime.min.time())

        available = (day_end - cursor).total_seconds()
        if needed > available:
            earliest = max(day_start, day_end - timedelta(seconds=needed))
            if earliest < cursor:
                cursor = earliest
                available = (day_end - cursor).total_seconds()

        overflow = max(0.0, needed - available)

        starts = []
        for block in blocks:
            starts.append(cursor)
            cursor = cursor + timedelta(seconds=block["seconds"])
        return starts, overflow

    def _show_pf_window(self, target_date, blocks, config, day_entries=None):
        total = sum(b["seconds"] for b in blocks)
        all_totals = db.get_project_totals_for_date(target_date)
        pushable = {b["project_id"] for b in blocks}

        elsewhere, never = {}, {}
        for pid, seconds in all_totals.items():
            if pid in pushable or seconds <= 0:
                continue
            if pid and projects.get_project(pid):
                elsewhere[projects.name_for(pid)] = seconds
            else:
                never[projects.name_for(pid) if pid else "no project"] = seconds
        breakdown = "\n".join(
            f"  {self._block_label(b)}: {db.format_duration(b['seconds'])}"
            + ("  ⚠️ already in PeopleForce" if b.get("covered") else "")
            for b in blocks
        )

        has_existing = any(b["existing"] for b in blocks)
        by_intervals = any(b.get("start_at") for b in blocks)
        heading = "Real time ranges:" if by_intervals else "Split by project:"

        header = (
            f"Going to PeopleForce: {db.format_duration(total)} "
            f"({round(total / 3600, 2)} h)\n\n"
            f"{heading}\n{breakdown}\n"
        )
        if never:
            not_pushed = "\n".join(
                f"  {name}: {db.format_duration(seconds)}"
                for name, seconds in never.items()
            )
            header += (
                f"\nStaying in your calendar only, never pushed:\n{not_pushed}\n"
            )

        if elsewhere:
            other = "\n".join(
                f"  {name}: {db.format_duration(seconds)}"
                for name, seconds in elsewhere.items()
            )
            header += (
                f"\nOther projects, pushed separately — switch the active "
                f"project first:\n{other}\n"
            )

        if has_existing:
            header += (
                "\nEntries marked ⚠️ will be REPLACED: the old one is deleted, "
                "a new one created.\n"
            )
        if len(self._unique_projects(blocks)) > 1:
            header += (
                "\nEach project gets its own comment. Keep the === Name === "
                "headers so the text ends up in the right timesheet entry."
            )
        else:
            header += "\nYou can edit the comment before pushing:"

        title = f"Push {target_date.isoformat()} to PeopleForce?"
        if len(self._unique_projects(blocks)) == 1 and settings.is_project_scoped():
            title = f"Push {blocks[0]['name']} — {target_date.isoformat()}?"

        window = rumps.Window(
            title=title,
            message=header,
            default_text=self._comments_to_text(blocks),
            dimensions=(430, 120 + 70 * len(self._unique_projects(blocks))),
            ok="Replace" if has_existing else "Push",
            cancel="Cancel",
        )
        make_window_always_on_top(window)
        response = window.run()
        if not response.clicked:
            return

        self._text_to_comments(response.text, blocks)

        starts, overflow = self._start_times(target_date, blocks, config, day_entries)
        if overflow > 0:
            proceed = rumps.alert(
                title="The hours do not fit into one day",
                message=(
                    f"{db.format_duration(overflow)} would fall past midnight "
                    f"and be cut off.\n\nLower 'Working day starts at' in the "
                    f"⚙️ Settings, or push part of the time by hand.\n\n"
                    f"Pushing anyway loses that time in PeopleForce."
                ),
                ok="Push anyway (time will be cut)",
                cancel="Cancel",
            )
            if not proceed:
                return

        def worker():
            pushed, failed = [], []
            for block, start_at in zip(blocks, starts):
                try:
                    for entry in block["existing"]:
                        entry_id = entry.get("id")
                        if entry_id:
                            peopleforce.delete_timesheet_entry(entry_id, config)

                    peopleforce.push_timesheet_entry(
                        target_date, block["seconds"], block["comment"], config,
                        project_id=block["peopleforce_id"], start_at=start_at,
                        allow_truncate=True,
                    )
                    pushed.append(self._block_label(block))
                except Exception as e:
                    failed.append(f"{self._block_label(block)}: {e}")

            if failed:
                AppHelper.callAfter(
                    rumps.alert, "Some entries failed", "\n".join(failed)
                )
            if pushed:
                AppHelper.callAfter(
                    _notify,
                    f"Pushed {target_date.isoformat()}: {', '.join(pushed)} ✅",
                )

        _run_async(worker)

    def quit_app(self, _sender):
        self._alerts_stop.set()
        for timer in getattr(self, "_timers", []):
            try:
                timer.stop()
            except Exception:
                pass
        self.tracker.stop()
        rumps.quit_application()


def main() -> None:
    import sys

    args = sys.argv[1:]
    if args and args[0] in ("-v", "--version"):
        from chronify import __version__

        print(f"chronify {__version__}")
        return
    if args and args[0] in ("-h", "--help"):
        print(
            "chronify — macOS menu bar work tracker\n\n"
            "Usage: chronify [--version] [--help]\n\n"
            "Run without arguments to start the menu bar app.\n"
            "Data and settings live in ~/.work_tracker/"
        )
        return

    WorkTrackerApp().run()


if __name__ == "__main__":
    main()
