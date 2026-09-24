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

import json
import os
import shutil
import threading
from pathlib import Path

import yaml

# The package itself lives in a read-only, upgrade-managed location when the
# app is installed through Homebrew, so nothing user-editable may live there.
# config.yaml is copied into the data directory on first run instead.
PACKAGE_DIR = Path(__file__).parent


def _data_dir() -> Path:
    # WORK_TRACKER_HOME points the data folder elsewhere while testing.
    return Path(os.path.expanduser(
        os.environ.get("WORK_TRACKER_HOME") or "~/.work_tracker"
    ))


BASE_DIR = _data_dir()
CONFIG_PATH = BASE_DIR / "config.yaml"
DEFAULT_CONFIG_PATH = PACKAGE_DIR / "default_config.yaml"
TEMPLATES_DIR = PACKAGE_DIR / "templates"
PROFILE_PATH = BASE_DIR / "profile.json"


def ensure_user_config() -> Path:
    """Seed ~/.work_tracker/config.yaml from the bundled default once."""
    if CONFIG_PATH.exists():
        return CONFIG_PATH
    try:
        BASE_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(DEFAULT_CONFIG_PATH, CONFIG_PATH)
        return CONFIG_PATH
    except OSError:
        return DEFAULT_CONFIG_PATH

DEBUG = os.environ.get("WORK_TRACKER_DEBUG", "0") == "1"

MONTH_NAMES = {
    1: "January", 2: "February", 3: "March", 4: "April",
    5: "May", 6: "June", 7: "July", 8: "August",
    9: "September", 10: "October", 11: "November", 12: "December",
}

WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

_cache = {"stamp": None, "data": None}
_cache_lock = threading.Lock()


def _mtime(path: Path):
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def _deep_merge(base: dict, overlay: dict) -> dict:
    result = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        elif value not in (None, ""):
            result[key] = value
    return result


def read_profile() -> dict:
    if not PROFILE_PATH.exists():
        return {}
    try:
        data = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


class ProfileWriteError(ValueError):
    pass


def save_profile_value(path_keys, value) -> None:
    data = read_profile()
    node = data
    for index, key in enumerate(path_keys[:-1]):
        child = node.get(key)
        if child is None:
            child = {}
            node[key] = child
        elif not isinstance(child, dict):
            raise ProfileWriteError(
                f"profile.json: '{'.'.join(path_keys[:index + 1])}' holds a "
                f"plain value, so '{'.'.join(path_keys)}' cannot be written. "
                f"Fix or remove that key in ~/.work_tracker/profile.json."
            )
        node = child
    node[path_keys[-1]] = value

    PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = PROFILE_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(PROFILE_PATH)

    with _cache_lock:
        _cache["stamp"] = None


def load_config(force: bool = False) -> dict:
    path = ensure_user_config()
    stamp = (_mtime(path), _mtime(PROFILE_PATH))

    with _cache_lock:
        if force or _cache["data"] is None or _cache["stamp"] != stamp:
            with open(path, "r", encoding="utf-8") as f:
                base = yaml.safe_load(f) or {}
            _cache["data"] = _deep_merge(base, read_profile())
            _cache["stamp"] = stamp

        return _cache["data"]