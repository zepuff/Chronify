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

import shutil
import subprocess
from pathlib import Path
from typing import Callable, Optional

BREW_PATHS = ("/opt/homebrew/bin/brew", "/usr/local/bin/brew")

INSTALL_TIMEOUT_SECONDS = 900

BACKENDS = {
    "none": {
        "label": "No AI",
        "summary": "The status is a plain list of the notes you wrote, "
                   "unchanged. Nothing to install.",
        "formula": None,
        "binary": None,
    },
    "ollama": {
        "label": "Ollama",
        "summary": "Understands Ukrainian and other languages, so it can "
                   "translate notes into the status language. Downloads a "
                   "model of about 2 GB.",
        "formula": "ollama",
        "binary": "ollama",
        "service": "ollama",
        "model": "qwen2.5:3b",
    },
    "apfel": {
        "label": "Apple Intelligence",
        "summary": "Uses the model already in macOS, so nothing is "
                   "downloaded. Writes English and a dozen other languages, "
                   "but not Ukrainian. Needs macOS 26 on Apple Silicon.",
        "formula": "apfel",
        "binary": "apfel",
    },
}

DEFAULT_BACKEND = "none"


class InstallError(RuntimeError):
    pass


def brew_path() -> Optional[str]:
    for candidate in BREW_PATHS:
        if Path(candidate).exists():
            return candidate
    return shutil.which("brew")


def binary_path(backend: str) -> Optional[str]:
    name = (BACKENDS.get(backend) or {}).get("binary")
    if not name:
        return None

    found = shutil.which(name)
    if found:
        return found

    for prefix in ("/opt/homebrew/bin", "/usr/local/bin"):
        candidate = Path(prefix) / name
        if candidate.exists():
            return str(candidate)
    return None


def is_installed(backend: str) -> bool:
    if backend == "none":
        return True
    return binary_path(backend) is not None


def has_model(backend: str) -> bool:
    spec = BACKENDS.get(backend) or {}
    wanted = spec.get("model")
    if not wanted:
        return True

    binary = binary_path(backend)
    if binary is None:
        return False

    try:
        listed = subprocess.run([binary, "list"], capture_output=True,
                                text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return False

    return wanted in (listed.stdout or "")


def is_ready(backend: str) -> bool:
    return is_installed(backend) and has_model(backend)


def steps_for(backend: str) -> list:
    spec = BACKENDS.get(backend) or {}
    brew = brew_path()
    steps = []

    if spec.get("formula") and not is_installed(backend):
        steps.append(([brew or "brew", "install", spec["formula"]],
                      f"Installing {spec['label']}"))

    if spec.get("service") and not is_installed(backend):
        steps.append(([brew or "brew", "services", "start", spec["service"]],
                      "Starting it in the background"))

    if spec.get("model") and not has_model(backend):
        binary = binary_path(backend) or spec["binary"]
        steps.append(([binary, "pull", spec["model"]],
                      f"Downloading the {spec['model']} model, about 2 GB"))

    return steps


def install(backend: str,
            on_progress: Optional[Callable[[str], None]] = None) -> None:
    """Install and start a backend, reporting progress as plain lines.

    Every command is announced before it runs, so a failure halfway through
    leaves the person knowing exactly which step to finish by hand.
    """
    def report(line):
        if on_progress is not None:
            on_progress(line)

    if backend not in BACKENDS:
        raise InstallError(f"There is no backend called '{backend}'.")

    steps = steps_for(backend)
    if not steps:
        report(f"{BACKENDS[backend]['label']} is ready.")
        return

    if BACKENDS[backend].get("formula") and brew_path() is None:
        raise InstallError(
            "Homebrew was not found, and it is what installs the AI backends. "
            "Install it from https://brew.sh and try again, or run these by "
            "hand:\n\n" + "\n".join(" ".join(command) for command, _ in steps)
        )

    for command, description in steps:
        report(f"{description}…")
        report("  " + " ".join(command))
        try:
            result = subprocess.run(command, capture_output=True, text=True,
                                    timeout=INSTALL_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            raise InstallError(
                f"'{' '.join(command)}' is still running after "
                f"{INSTALL_TIMEOUT_SECONDS // 60} minutes. Run it in a "
                f"terminal to see what it is waiting for."
            )
        except OSError as e:
            raise InstallError(f"Could not run '{' '.join(command)}': {e}")

        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            raise InstallError(
                f"'{' '.join(command)}' failed with code {result.returncode}.\n\n"
                f"{detail[:400] or 'It said nothing.'}\n\n"
                f"Run it in a terminal to finish the setup by hand."
            )

    report(f"{BACKENDS[backend]['label']} is ready.")


def describe(backend: str) -> str:
    spec = BACKENDS.get(backend)
    if spec is None:
        return f"Unknown backend '{backend}'."

    if backend == "none":
        return spec["summary"]
    if is_ready(backend):
        return f"{spec['label']} is installed and ready."
    if is_installed(backend):
        return f"{spec['label']} is installed, but the model is still missing."
    return f"{spec['label']} is not installed yet."
