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

import re
from typing import Optional

from chronify.config import load_config


class TaskMapper:
    def __init__(self):
        self._compile(load_config())

    def _compile(self, config: dict) -> None:
        self.config = config
        self.rules = [
            (re.compile(rule["pattern"]), rule["task"])
            for rule in config.get("rules", [])
        ]
        self.ignore_apps = set(config.get("ignore_apps", []))

    def is_ignored(self, app_name: str) -> bool:
        return app_name in self.ignore_apps

    def map_to_task(self, app_name: str, window_title: Optional[str]) -> str:
        haystack = f"{app_name} — {window_title or ''}"

        for pattern, task_template in self.rules:
            match = pattern.search(haystack)
            if not match:
                continue
            task = task_template
            for i, group in enumerate(match.groups(), start=1):
                if group:
                    task = task.replace(f"{{{i}}}", group)
            return task

        return app_name

    def reload(self) -> None:
        self._compile(load_config(force=True))