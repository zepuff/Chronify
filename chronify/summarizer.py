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
from datetime import date
from typing import Optional

import requests

from chronify import db
from chronify import notes
from chronify import settings
from chronify.config import DEBUG, load_config

_LEADING_BULLET_RE = re.compile(r"^[-•*]\s*")
_LEADING_NUMBER_RE = re.compile(r"^\d+[.)]\s*")
_DURATION_RE = re.compile(
    r"(?:\s*[,—–-]\s*|\s+(?:for|in|over)\s+|\s+)"
    r"\d+\s*(?:h|m|hr|hrs|min|mins|hour\w*|minute\w*)"
    r"(?=[\s.,;:)]|$)",
    re.IGNORECASE,
)
_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_TRAILING_JUNK_RE = re.compile(r"[\s,;:—–-]+$")
AI_TIMEOUT_SECONDS = 120

_DUPLICATE_OVERLAP = 0.85
_CONTAINMENT_RATIO = 0.95
_CONTAINMENT_MIN_WORDS = 5


DEFAULT_STATUS_LANGUAGE = "English"


def _language_instruction(config: dict) -> str:
    language = (config.get("status_language") or DEFAULT_STATUS_LANGUAGE).strip()
    return (
        f"Write the status in {language.upper()}, regardless of what language "
        f"the notes below are written in."
    )


def _extract(response, path, source: str) -> str:
    try:
        payload = response.json()
    except ValueError:
        raise RuntimeError(f"{source} returned a non-JSON reply: {response.text[:200]}")

    node = payload
    for key in path:
        if not isinstance(node, dict) or key not in node:
            raise RuntimeError(
                f"{source} returned an unexpected reply shape "
                f"(no '{'.'.join(path)}'): {str(payload)[:200]}"
            )
        node = node[key]

    if not isinstance(node, str):
        raise RuntimeError(f"{source} returned a non-text reply: {str(node)[:200]}")
    return node.strip()


def _call_ollama(host: str, model: str, prompt: str) -> str:
    options = {"temperature": 0.3, "num_predict": 600}

    try:
        response = requests.post(
            f"{host}/api/chat",
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "options": options,
            },
            timeout=AI_TIMEOUT_SECONDS,
        )
    except requests.exceptions.ConnectionError:
        raise RuntimeError(
            f"Cannot reach Ollama at {host}. Make sure Ollama is running "
            f"(`ollama serve`, or just open Ollama.app) and that the model "
            f"{model} is downloaded (`ollama pull {model}`)."
        )

    if response.status_code == 404:
        try:
            error_detail = response.json().get("error", "")
        except Exception:
            error_detail = ""

        if "model" in error_detail.lower():
            raise RuntimeError(
                f"Model '{model}' was not found in Ollama (404). Check that "
                f"ollama_model in config.yaml matches a name from `ollama list` "
                f"exactly, including the tag such as ':14b'. "
                f"Ollama said: {error_detail or 'nothing'}"
            )

        response = requests.post(
            f"{host}/api/generate",
            json={"model": model, "prompt": prompt, "stream": False, "options": options},
            timeout=AI_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return _extract(response, ("response",), "Ollama /api/generate")

    response.raise_for_status()
    return _extract(response, ("message", "content"), "Ollama /api/chat")


def _call_apfel(host: str, prompt: str) -> str:
    try:
        response = requests.post(
            f"{host}/v1/chat/completions",
            json={
                "model": "apple-foundationmodel",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3,
            },
            timeout=60,
        )
    except requests.exceptions.ConnectionError:
        raise RuntimeError(
            f"Cannot reach apfel at {host}. Make sure the server is running "
            f"(`apfel --serve` in a separate terminal window) and that the port "
            f"is not already taken by Ollama or something else "
            f"(`lsof -i :11434` shows what is using it)."
        )

    response.raise_for_status()
    try:
        choice = response.json()["choices"][0]
        text = choice["message"]["content"].strip()
    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
        raise RuntimeError(
            f"apfel returned an unexpected reply: {response.text[:200]}"
        )

    if choice.get("finish_reason") == "length":
        text += (
            "\n\n[Warning: the reply was cut off. The notes exceed the apfel "
            "context window (4096 tokens). Use shorter notes, or switch to "
            "Ollama for long days.]"
        )
    return text


def _run_ai(config: dict, prompt: str) -> Optional[str]:
    backend = config.get("ai_backend", "none")
    if backend not in ("ollama", "apfel"):
        return None

    try:
        if backend == "ollama":
            host = config.get("ollama_host", "http://localhost:11434").rstrip("/")
            return _call_ollama(host, config.get("ollama_model", "llama3.1"), prompt)

        host = config.get("apfel_host", "http://localhost:11434").rstrip("/")
        return _call_apfel(host, prompt)
    except Exception as e:
        if isinstance(e, NameError):
            raise
        if DEBUG:
            print(f"[summarizer] AI request failed: {e}")
        return None


DONE_PROMPT = """You are writing the "What was done today" section of a work status update. {language_instruction}

Here are the tasks the person RECORDED as done today ({count} of them):
{tasks}

Rewrite them as a short, businesslike list for a daily status update.
HARD RULES:
- DO NOT INVENT anything that is not in the recorded tasks. No new tasks,
  no numbers, no service names, no outcomes.
- DO NOT MENTION time, duration, hours or minutes. No "for 40 min", "2h".
- DO NOT MENTION application or browser names (Chrome, Safari, VS Code,
  Terminal). Describe only the substance of the work.
- Do not add judgements ("successfully", "great") and do not draw conclusions.
- You may merge several small entries into one line if they are about the
  same thing.
- At most {count} lines. Start every line with "• ".
- No headings, no intro, no explanations. ONLY the list lines.
"""


def _source_lines(text: str) -> list:
    return [line.strip() for line in (text or "").splitlines() if line.strip()]


def _numbered(text: str) -> str:
    return "\n".join(f"{i}. {_LEADING_BULLET_RE.sub('', line)}"
                     for i, line in enumerate(_source_lines(text), 1))


def _strip_duration(line: str) -> str:
    return _TRAILING_JUNK_RE.sub("", _DURATION_RE.sub("", line))


def _normalize(line: str) -> str:
    return " ".join(_PUNCT_RE.sub(" ", line.lower()).split())


def _tokens(line: str) -> frozenset:
    return frozenset(_normalize(line).split())


def _is_duplicate(tokens: frozenset, seen: list) -> bool:
    for previous in seen:
        if tokens == previous:
            return True

        shared = len(tokens & previous)
        union = len(tokens | previous)
        if union and shared / union >= _DUPLICATE_OVERLAP:
            return True

        shorter = min(len(tokens), len(previous))
        if shorter >= _CONTAINMENT_MIN_WORDS and shared / shorter >= _CONTAINMENT_RATIO:
            return True

    return False


def _clean_bullets(text: str, limit: int) -> list:
    kept, seen = [], []

    for raw in _source_lines(text):
        content = _LEADING_NUMBER_RE.sub("", _LEADING_BULLET_RE.sub("", raw)).strip()
        content = _strip_duration(content).strip()
        if not content:
            continue

        tokens = _tokens(content)
        if not tokens or _is_duplicate(tokens, seen):
            continue

        kept.append(f"• {content}")
        seen.append(tokens)
        if len(kept) >= limit:
            break

    return kept


def _as_bullets(text: str) -> list:
    return [f"• {_LEADING_BULLET_RE.sub('', line)}" for line in _source_lines(text)]


def _section(heading: str, body_lines: list, empty_value: Optional[str] = None) -> Optional[str]:
    if not body_lines:
        if empty_value is None:
            return None
        return f"{heading}: {empty_value}"
    if len(body_lines) == 1:
        return f"{heading}: {_LEADING_BULLET_RE.sub('', body_lines[0]).strip()}"
    return heading + ":\n" + "\n".join(body_lines)


def _done_lines(config: dict, tasks_text: str) -> list:
    limit = len(_source_lines(tasks_text))
    ai_done = _run_ai(config, DONE_PROMPT.format(
        language_instruction=_language_instruction(config),
        count=limit,
        tasks=_numbered(tasks_text),
    ))
    return _clean_bullets(ai_done, limit) if ai_done else _as_bullets(tasks_text)


def compose_daily(config: dict, target_date: date, project: Optional[str] = None) -> str:
    tasks_text = notes.tasks_as_text(target_date, project)
    done_lines = _done_lines(config, tasks_text) if tasks_text else []

    plan_text = notes.pending_plan_as_text(project, target_date)
    blockers_text = notes.blockers_as_text(project, target_date)
    infra_line = settings.infra_status_line(project, target_date)

    sections = [
        _section("What was done today", done_lines, empty_value="—"),
        _section("What is planned next",
                 _as_bullets(plan_text), empty_value="—"),
        _section("Blockers", _as_bullets(blockers_text), empty_value="None"),
        f"Infrastructure status: {infra_line}" if infra_line else None,
        _section("Reminders", _as_bullets(notes.reminders_as_text(project))),
    ]
    return "\n\n".join(s for s in sections if s)


def generate_daily_summary(project: Optional[str] = None) -> str:
    return compose_daily(load_config(), date.today(), project)


def generate_summary_for_date(target_date: date, project: Optional[str] = None) -> str:
    config = load_config()
    tasks_text = notes.tasks_as_text(target_date, project)

    if not tasks_text:
        return f"{target_date.isoformat()}:\n• No data"

    lines = _done_lines(config, tasks_text)
    return f"{target_date.isoformat()}:\n" + "\n".join(lines)