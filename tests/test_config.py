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

import ast
import os
import re
from pathlib import Path

from chronify import config

PACKAGE = Path(__file__).resolve().parent.parent / "chronify"


def test_the_data_folder_follows_the_env_var(monkeypatch, tmp_path):
    monkeypatch.setenv("WORK_TRACKER_HOME", str(tmp_path))
    assert config._data_dir() == tmp_path


def test_without_the_env_var_it_is_the_usual_folder(monkeypatch):
    monkeypatch.delenv("WORK_TRACKER_HOME", raising=False)
    assert config._data_dir() == Path(os.path.expanduser("~/.work_tracker"))


def test_no_module_hardcodes_the_data_folder():
    """One definition, or WORK_TRACKER_HOME moves some files and not others."""
    # A literal that IS the path is what quietly ignores the env var.
    path_literal = re.compile(r"^~/\.work_tracker(/[\w.\-]+)*$")

    hardcoded = []
    for source in sorted(PACKAGE.glob("*.py")):
        if source.name == "config.py":
            continue
        tree = ast.parse(source.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                    and path_literal.match(node.value)):
                hardcoded.append((source.name, node.value))
    assert not hardcoded, (
        "these build a path from the literal instead of using config.BASE_DIR: "
        f"{hardcoded}"
    )


def test_the_version_is_the_same_in_both_places():
    """A formula built against a tag that says another version is confusing."""
    pyproject = (PACKAGE.parent / "pyproject.toml").read_text(encoding="utf-8")
    declared = re.search(r'^version = "([^"]+)"', pyproject, re.M).group(1)

    init = (PACKAGE / "__init__.py").read_text(encoding="utf-8")
    module = re.search(r'^__version__ = "([^"]+)"', init, re.M).group(1)

    assert declared == module
