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

import subprocess

import pytest

from chronify import backends


class _Result:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


@pytest.fixture
def brew_available(monkeypatch):
    monkeypatch.setattr(backends.Path, "exists", lambda self: True)


@pytest.fixture
def nothing_installed(monkeypatch):
    monkeypatch.setattr(backends.shutil, "which", lambda name: None)
    monkeypatch.setattr(backends.Path, "exists",
                        lambda self: str(self).endswith("/brew"))


@pytest.fixture
def ollama_installed(monkeypatch):
    monkeypatch.setattr(
        backends.shutil, "which",
        lambda name: f"/opt/homebrew/bin/{name}"
        if name in ("ollama", "brew") else None)


def test_no_ai_needs_no_installation():
    assert backends.is_ready("none")
    assert backends.steps_for("none") == []


def test_a_missing_backend_is_installed_and_started(nothing_installed):
    steps = backends.steps_for("ollama")
    commands = [" ".join(command) for command, _ in steps]

    assert commands == [
        "/opt/homebrew/bin/brew install ollama",
        "/opt/homebrew/bin/brew services start ollama",
        "ollama pull qwen2.5:3b",
    ]


def test_apple_intelligence_needs_no_model(nothing_installed):
    commands = [" ".join(command) for command, _ in backends.steps_for("apfel")]

    assert commands == ["/opt/homebrew/bin/brew install apfel"]


def test_an_installed_backend_without_its_model_only_pulls(monkeypatch,
                                                           ollama_installed):
    monkeypatch.setattr(backends.subprocess, "run",
                        lambda cmd, **kw: _Result(stdout="llama3.1:8b\n"))

    commands = [" ".join(command) for command, _ in backends.steps_for("ollama")]

    assert commands == ["/opt/homebrew/bin/ollama pull qwen2.5:3b"]


def test_a_ready_backend_is_left_alone(monkeypatch, ollama_installed):
    monkeypatch.setattr(backends.subprocess, "run",
                        lambda cmd, **kw: _Result(stdout="qwen2.5:3b  1.9 GB\n"))

    assert backends.is_ready("ollama")
    assert backends.steps_for("ollama") == []


def test_every_command_is_announced_before_it_runs(monkeypatch,
                                                   nothing_installed):
    monkeypatch.setattr(backends.subprocess, "run",
                        lambda cmd, **kw: _Result())
    lines = []

    backends.install("ollama", lines.append)

    assert any("brew install ollama" in line for line in lines)
    assert any("about 2 GB" in line for line in lines)
    assert lines[-1].endswith("is ready.")


def test_a_failed_command_says_which_one_and_why(monkeypatch,
                                                 nothing_installed):
    monkeypatch.setattr(
        backends.subprocess, "run",
        lambda cmd, **kw: _Result(returncode=1, stderr="No such formula"))

    with pytest.raises(backends.InstallError) as caught:
        backends.install("ollama")

    message = str(caught.value)
    assert "brew install ollama" in message
    assert "No such formula" in message


def test_without_homebrew_the_commands_are_handed_over(monkeypatch):
    monkeypatch.setattr(backends.shutil, "which", lambda name: None)
    monkeypatch.setattr(backends.Path, "exists", lambda self: False)

    with pytest.raises(backends.InstallError) as caught:
        backends.install("ollama")

    message = str(caught.value)
    assert "brew.sh" in message
    assert "brew install ollama" in message


def test_a_hanging_install_does_not_hang_the_app(monkeypatch,
                                                 nothing_installed):
    def timeout(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, backends.INSTALL_TIMEOUT_SECONDS)

    monkeypatch.setattr(backends.subprocess, "run", timeout)

    with pytest.raises(backends.InstallError) as caught:
        backends.install("ollama")

    assert "terminal" in str(caught.value)


def test_an_unknown_backend_is_refused():
    with pytest.raises(backends.InstallError):
        backends.install("gpt5")


def test_the_summaries_say_what_the_person_needs_to_decide():
    assert "Ukrainian" in backends.BACKENDS["ollama"]["summary"]
    assert "not Ukrainian" in backends.BACKENDS["apfel"]["summary"]
    assert "2 GB" in backends.BACKENDS["ollama"]["summary"]
