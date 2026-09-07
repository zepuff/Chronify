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
import sys
import types

import pytest

from chronify import summarizer


class _Result:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


@pytest.fixture
def apfel_installed(monkeypatch):
    monkeypatch.setattr(summarizer.shutil, "which",
                        lambda name: "/opt/homebrew/bin/apfel"
                        if name == "apfel" else None)


@pytest.fixture
def apfel_missing(monkeypatch):
    monkeypatch.setattr(summarizer.shutil, "which", lambda name: None)


def test_the_cli_is_preferred_over_a_running_server(monkeypatch, apfel_installed):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs.get("input")))
        return _Result(stdout="Fixed the invoice table.\n")

    monkeypatch.setattr(summarizer.subprocess, "run", fake_run)
    monkeypatch.setattr(summarizer.requests, "post", _no_http)

    answer = summarizer._run_ai({"ai_backend": "apfel"}, "prompt")

    assert answer == "Fixed the invoice table."
    assert calls == [(["/opt/homebrew/bin/apfel"], "prompt")]


def test_without_the_binary_it_falls_back_to_the_server(monkeypatch, apfel_missing):
    posted = {}

    class Response:
        status_code = 200
        text = ""

        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": "From the server."}}]}

    def fake_post(url, **kwargs):
        posted["url"] = url
        return Response()

    monkeypatch.setattr(summarizer.requests, "post", fake_post)

    answer = summarizer._run_ai({"ai_backend": "apfel"}, "prompt")

    assert answer == "From the server."
    assert posted["url"].endswith("/v1/chat/completions")


def test_a_multiline_prompt_goes_through_stdin(monkeypatch, apfel_installed):
    """Real prompts carry newlines and quotes; argv is the wrong channel."""
    seen = {}

    def fake_run(cmd, **kwargs):
        seen.update(cmd=cmd, input=kwargs.get("input"))
        return _Result(stdout="• Fixed it")

    monkeypatch.setattr(summarizer.subprocess, "run", fake_run)

    prompt = 'Rules:\n- do not invent\n- start with "• "\nTasks:\n1. fixed it'
    summarizer._call_apfel_cli("/opt/homebrew/bin/apfel", prompt)

    assert seen["cmd"] == ["/opt/homebrew/bin/apfel"]
    assert seen["input"] == prompt


def test_a_failing_binary_explains_how_to_check_the_model(monkeypatch,
                                                          apfel_installed):
    monkeypatch.setattr(summarizer.subprocess, "run",
                        lambda cmd, **kw: _Result(returncode=1,
                                                  stderr="model unavailable"))

    with pytest.raises(RuntimeError) as caught:
        summarizer._call_apfel_cli("/opt/homebrew/bin/apfel", "prompt")

    assert "--model-info" in str(caught.value)


def test_empty_output_is_an_error_rather_than_an_empty_status(monkeypatch,
                                                              apfel_installed):
    monkeypatch.setattr(summarizer.subprocess, "run",
                        lambda cmd, **kw: _Result(stdout="   \n"))

    with pytest.raises(RuntimeError):
        summarizer._call_apfel_cli("/opt/homebrew/bin/apfel", "prompt")


def test_a_backend_failure_never_reaches_the_caller(monkeypatch, apfel_installed):
    """The menu asks for a status; a broken backend means no AI, not a crash."""
    monkeypatch.setattr(summarizer.subprocess, "run",
                        lambda cmd, **kw: _Result(returncode=1))

    assert summarizer._run_ai({"ai_backend": "apfel"}, "prompt") is None


def test_no_backend_selected_means_no_call_at_all(monkeypatch):
    monkeypatch.setattr(summarizer.requests, "post", _no_http)
    monkeypatch.setattr(summarizer.subprocess, "run", _no_subprocess)

    assert summarizer._run_ai({"ai_backend": "none"}, "prompt") is None


def test_ollama_still_goes_over_http(monkeypatch):
    posted = {}

    class Response:
        status_code = 200
        text = ""

        def raise_for_status(self):
            pass

        def json(self):
            return {"message": {"content": "Ollama answer."}}

    def fake_post(url, **kwargs):
        posted["url"] = url
        return Response()

    monkeypatch.setattr(summarizer.requests, "post", fake_post)
    monkeypatch.setattr(summarizer.subprocess, "run", _no_subprocess)

    answer = summarizer._run_ai({"ai_backend": "ollama"}, "prompt")

    assert answer == "Ollama answer."
    assert posted["url"].endswith("/api/chat")


def test_the_error_text_points_at_brew_services(monkeypatch):
    import requests as real_requests

    def refuse(url, **kwargs):
        raise real_requests.exceptions.ConnectionError()

    monkeypatch.setattr(summarizer.requests, "post", refuse)

    with pytest.raises(RuntimeError) as caught:
        summarizer._call_ollama("http://localhost:11434", "llama3.1", "prompt")

    assert "brew services start ollama" in str(caught.value)


def _no_http(*args, **kwargs):
    raise AssertionError("the backend should not have been reached over HTTP")


def _no_subprocess(*args, **kwargs):
    raise AssertionError("no subprocess should have been started")