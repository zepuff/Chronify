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

import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

import Quartz
from AppKit import NSWorkspace

from chronify import db
from chronify.task_mapper import TaskMapper

MISSING_PROJECT_WARNING_SECONDS = 15 * 60


def get_frontmost_app_name() -> str:
    app = NSWorkspace.sharedWorkspace().frontmostApplication()
    return (app.localizedName() if app else None) or "Unknown"


def get_frontmost_window_title() -> str:
    window_list = Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID
    )
    frontmost_app = get_frontmost_app_name()

    for window in window_list:
        if (
            window.get("kCGWindowOwnerName", "") == frontmost_app
            and window.get("kCGWindowLayer", 0) == 0
            and window.get("kCGWindowName", "")
        ):
            return window["kCGWindowName"]
    return ""


DEFAULT_CALL_APPS = (
    "zoom", "meet", "google meet", "teams", "webex", "skype", "facetime",
)

DEFAULT_CONDITIONAL_CALL_APPS = ("slack", "discord")

DEFAULT_CALL_TITLE_MARKERS = ("huddle", "call", "meeting", "voice")


def is_screen_busy(
    app_name: str,
    window_title: str,
    call_apps=DEFAULT_CALL_APPS,
    conditional_apps=DEFAULT_CONDITIONAL_CALL_APPS,
    title_markers=DEFAULT_CALL_TITLE_MARKERS,
) -> bool:
    haystack = f"{app_name} {window_title}".lower()

    if any(hint in haystack for hint in call_apps):
        return True

    if any(hint in haystack for hint in conditional_apps):
        title = (window_title or "").lower()
        return any(marker in title for marker in title_markers)

    return False


def get_system_idle_seconds() -> float:
    return Quartz.CGEventSourceSecondsSinceLastEventType(
        Quartz.kCGEventSourceStateCombinedSessionState,
        Quartz.kCGAnyInputEventType,
    )


@dataclass
class _OpenSegment:
    app_name: str
    window_title: str
    task_name: str
    start_ts: float
    project: str = ""


class ActivityTracker:
    def __init__(
        self,
        poll_interval: int = 5,
        min_segment_seconds: int = 8,
        idle_threshold_seconds: int = 300,
        on_update: Optional[Callable[[str, str], None]] = None,
        on_idle_return: Optional[Callable[[dict], None]] = None,
        project_provider: Optional[Callable[[], str]] = None,
        watch_screen: bool = True,
        call_apps=DEFAULT_CALL_APPS,
        conditional_call_apps=DEFAULT_CONDITIONAL_CALL_APPS,
        call_title_markers=DEFAULT_CALL_TITLE_MARKERS,
        on_missing_project: Optional[Callable[[float], None]] = None,
    ):
        self.poll_interval = poll_interval
        self.min_segment_seconds = min_segment_seconds
        self.idle_threshold_seconds = idle_threshold_seconds
        self.on_update = on_update
        self.on_idle_return = on_idle_return
        self.project_provider = project_provider
        self.watch_screen = watch_screen
        self.call_apps = tuple(call_apps or ())
        self.conditional_call_apps = tuple(conditional_call_apps or ())
        self.call_title_markers = tuple(call_title_markers or ())
        self.on_missing_project = on_missing_project
        self._orphan_seconds = 0.0
        self._last_orphan_warning = 0.0

        self.mapper = TaskMapper()
        self._current: Optional[_OpenSegment] = None
        self._paused = False
        self._is_idle = False
        self._idle_start_ts: float = 0.0
        self._idle_context: Optional[dict] = None
        self._last_flush_ts: float = 0.0
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        db.init_db()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._flush_current_segment(time.time())

    def is_paused(self) -> bool:
        return self._paused or self._is_idle

    def is_manually_paused(self) -> bool:
        return self._paused

    def is_idle(self) -> bool:
        return self._is_idle

    def pause(self) -> None:
        self._flush_current_segment(time.time())
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    def _current_project(self) -> str:
        if self.project_provider is None:
            return ""
        try:
            return self.project_provider() or ""
        except Exception:
            return ""

    def _warn_missing_project(self) -> None:
        if not self.on_missing_project:
            return
        now = time.time()
        if now - self._last_orphan_warning < MISSING_PROJECT_WARNING_SECONDS:
            return
        self._last_orphan_warning = now
        try:
            self.on_missing_project(self._orphan_seconds)
        except Exception:
            pass

    def _notify_update(self, app_name: str, task_name: str) -> None:
        if not self.on_update:
            return
        try:
            self.on_update(app_name, task_name)
        except Exception:
            pass

    def _flush_current_segment(self, end_ts: float) -> None:
        with self._lock:
            segment = self._current
            self._current = None

        if segment is None:
            return

        duration = end_ts - segment.start_ts

        if self.project_provider is not None and not segment.project:
            self._orphan_seconds += max(0.0, duration)
            self._warn_missing_project()

        recent = end_ts - self._last_flush_ts < db.MERGE_GAP_SECONDS
        if duration >= self.min_segment_seconds or (recent and duration > 0):
            db.insert_segment(
                app_name=segment.app_name,
                window_title=segment.window_title,
                task_name=segment.task_name,
                start_ts=segment.start_ts,
                end_ts=end_ts,
                is_idle=False,
                project=segment.project,
            )
            self._last_flush_ts = end_ts

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            if self._paused:
                time.sleep(self.poll_interval)
                continue

            now = time.time()
            idle_seconds = get_system_idle_seconds()

            app_name = get_frontmost_app_name()
            window_title = get_frontmost_window_title()

            if self.watch_screen and is_screen_busy(
                app_name, window_title,
                self.call_apps, self.conditional_call_apps, self.call_title_markers,
            ):
                idle_seconds = 0.0

            if idle_seconds >= self.idle_threshold_seconds:
                if not self._is_idle:
                    self._is_idle = True
                    idle_start = now - idle_seconds
                    self._idle_start_ts = idle_start

                    segment = self._current
                    self._idle_context = None if segment is None else {
                        "app_name": segment.app_name,
                        "window_title": segment.window_title,
                        "task_name": segment.task_name,
                        "project": segment.project,
                    }

                    self._flush_current_segment(idle_start)
                    self._notify_update("Idle", "Idle")
                time.sleep(self.poll_interval)
                continue

            if self._is_idle:
                self._is_idle = False
                context = self._idle_context
                self._idle_context = None

                if context and self.on_idle_return:
                    try:
                        self.on_idle_return(dict(
                            context,
                            start_ts=self._idle_start_ts,
                            end_ts=now,
                            duration=now - self._idle_start_ts,
                        ))
                    except Exception:
                        pass

                with self._lock:
                    self._current = None

            if self.mapper.is_ignored(app_name):
                time.sleep(self.poll_interval)
                continue

            task_name = self.mapper.map_to_task(app_name, window_title)
            project = self._current_project()

            current = self._current
            task_changed = (
                current is None
                or app_name != current.app_name
                or task_name != current.task_name
                or project != current.project
            )

            if task_changed:
                self._flush_current_segment(now)
                with self._lock:
                    self._current = _OpenSegment(
                        app_name, window_title, task_name, now, project
                    )
            else:
                current.window_title = window_title

            self._notify_update(app_name, task_name)

            time.sleep(self.poll_interval)