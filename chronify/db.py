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

import calendar as calendar_module
import os
import sqlite3
import time
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterator, Optional

from chronify.config import MONTH_NAMES, WEEKDAY_NAMES

DB_PATH = Path(os.path.expanduser("~/.work_tracker/tracker.db"))


@contextmanager
def _connection() -> Iterator[sqlite3.Connection]:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def init_db() -> None:
    with _connection() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS activity_segments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                app_name TEXT NOT NULL,
                window_title TEXT,
                task_name TEXT NOT NULL,
                start_ts REAL NOT NULL,
                end_ts REAL NOT NULL,
                duration_sec REAL NOT NULL,
                is_idle INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        _ensure_column(conn, "activity_segments", "project", "project TEXT NOT NULL DEFAULT ''")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_start_ts ON activity_segments(start_ts)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_archive (
                date TEXT PRIMARY KEY,
                summary_text TEXT NOT NULL,
                created_at REAL NOT NULL
            )
            """
        )


MERGE_GAP_SECONDS = 90


def _merge_into_previous(conn, app_name, task_name, project, start_ts, end_ts) -> bool:
    row = conn.execute(
        """
        SELECT id, end_ts FROM activity_segments
        WHERE task_name = ? AND project = ? AND app_name = ? AND is_idle = 0
              AND end_ts <= ? AND end_ts >= ?
              AND date(end_ts, 'unixepoch', 'localtime')
                  = date(?, 'unixepoch', 'localtime')
        ORDER BY end_ts DESC LIMIT 1
        """,
        (task_name, project, app_name,
         start_ts + 1, start_ts - MERGE_GAP_SECONDS, start_ts),
    ).fetchone()

    if row is None:
        return False

    conn.execute(
        """
        UPDATE activity_segments
        SET end_ts = ?, duration_sec = duration_sec + ?
        WHERE id = ?
        """,
        (end_ts, max(0.0, end_ts - start_ts), row["id"]),
    )
    return True


def insert_segment(
    app_name: str,
    window_title: str,
    task_name: str,
    start_ts: float,
    end_ts: float,
    is_idle: bool = False,
    project: str = "",
) -> None:
    duration = max(0.0, end_ts - start_ts)
    with _connection() as conn:
        if not is_idle and _merge_into_previous(
            conn, app_name, task_name, project or "", start_ts, end_ts
        ):
            return

        conn.execute(
            """
            INSERT INTO activity_segments
                (app_name, window_title, task_name, start_ts, end_ts,
                 duration_sec, is_idle, project)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (app_name, window_title, task_name, start_ts, end_ts,
             duration, int(is_idle), project or ""),
        )


def _midnight(target_date: date) -> float:
    return datetime.combine(target_date, datetime.min.time()).timestamp()


def _day_bounds(target_date: date) -> tuple:
    return _midnight(target_date), _midnight(target_date + timedelta(days=1))


def _range_bounds(start_date: date, end_date: date) -> tuple:
    return _midnight(start_date), _midnight(end_date + timedelta(days=1))


def get_task_totals_for_date(target_date: date, project: Optional[str] = None) -> dict:
    start_ts, end_ts = _day_bounds(target_date)
    sql = (
        "SELECT task_name, SUM(duration_sec) AS total FROM activity_segments "
        "WHERE start_ts >= ? AND start_ts < ? AND is_idle = 0"
    )
    params = [start_ts, end_ts]
    if project is not None:
        sql += " AND project = ?"
        params.append(project)
    sql += " GROUP BY task_name ORDER BY total DESC"

    with _connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    return {row["task_name"]: row["total"] for row in rows}


def get_project_totals_for_date(target_date: date) -> dict:
    start_ts, end_ts = _day_bounds(target_date)
    with _connection() as conn:
        rows = conn.execute(
            """
            SELECT project, SUM(duration_sec) AS total
            FROM activity_segments
            WHERE start_ts >= ? AND start_ts < ? AND is_idle = 0
            GROUP BY project
            ORDER BY total DESC
            """,
            (start_ts, end_ts),
        ).fetchall()
    return {row["project"]: row["total"] for row in rows}


def count_unassigned_segments() -> int:
    with _connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM activity_segments WHERE project = ''"
        ).fetchone()
    return row["n"]


def adopt_unassigned_segments(project: str) -> int:
    with _connection() as conn:
        return conn.execute(
            "UPDATE activity_segments SET project = ? WHERE project = ''", (project,)
        ).rowcount


def get_project_totals_by_day(start_date: date, end_date: date) -> dict:
    start_ts, end_ts = _range_bounds(start_date, end_date)
    with _connection() as conn:
        rows = conn.execute(
            """
            SELECT date(start_ts, 'unixepoch', 'localtime') AS day,
                   project,
                   SUM(duration_sec) AS total
            FROM activity_segments
            WHERE start_ts >= ? AND start_ts < ? AND is_idle = 0
            GROUP BY day, project
            ORDER BY day ASC, total DESC
            """,
            (start_ts, end_ts),
        ).fetchall()

    by_day = {}
    for row in rows:
        by_day.setdefault(row["day"], []).append((row["project"], row["total"]))
    return by_day


def get_project_totals_for_range(start_date: date, end_date: date) -> dict:
    start_ts, end_ts = _range_bounds(start_date, end_date)
    with _connection() as conn:
        rows = conn.execute(
            """
            SELECT project, SUM(duration_sec) AS total
            FROM activity_segments
            WHERE start_ts >= ? AND start_ts < ? AND is_idle = 0
            GROUP BY project
            ORDER BY total DESC
            """,
            (start_ts, end_ts),
        ).fetchall()
    return {row["project"]: row["total"] for row in rows}


def reassign_all(from_project: str, to_project: str) -> int:
    with _connection() as conn:
        return conn.execute(
            "UPDATE activity_segments SET project = ? WHERE project = ?",
            (to_project, from_project),
        ).rowcount


def known_project_ids() -> set:
    with _connection() as conn:
        rows = conn.execute(
            "SELECT DISTINCT project FROM activity_segments WHERE project != ''"
        ).fetchall()
    return {row["project"] for row in rows}


def reassign_day(target_date: date, project: str, only_from: Optional[str] = None) -> int:
    start_ts, end_ts = _day_bounds(target_date)
    sql = "UPDATE activity_segments SET project = ? WHERE start_ts >= ? AND start_ts < ?"
    params = [project or "", start_ts, end_ts]
    if only_from is not None:
        sql += " AND project = ?"
        params.append(only_from)

    with _connection() as conn:
        return conn.execute(sql, params).rowcount


def get_segments_for_date(target_date: date) -> list:
    start_ts, end_ts = _day_bounds(target_date)
    with _connection() as conn:
        rows = conn.execute(
            """
            SELECT id, app_name, window_title, task_name,
                   start_ts, end_ts, duration_sec, project
            FROM activity_segments
            WHERE start_ts >= ? AND start_ts < ? AND is_idle = 0
            ORDER BY start_ts ASC
            """,
            (start_ts, end_ts),
        ).fetchall()
    return [dict(row) for row in rows]


DEFAULT_INTERVAL_GAP_SECONDS = 15 * 60
DEFAULT_MIN_INTERVAL_SECONDS = 5 * 60


def _absorb_short_intervals(intervals: list, min_interval_seconds: float) -> list:
    intervals = [dict(i) for i in intervals]

    while len(intervals) > 1:
        shortest_index = None
        shortest_span = None

        for index, interval in enumerate(intervals):
            span = interval["end_ts"] - interval["start_ts"]
            if span >= min_interval_seconds:
                continue
            if shortest_span is None or span < shortest_span:
                shortest_index, shortest_span = index, span

        if shortest_index is None:
            break

        interval = intervals[shortest_index]
        previous = intervals[shortest_index - 1] if shortest_index > 0 else None
        following = (
            intervals[shortest_index + 1]
            if shortest_index + 1 < len(intervals) else None
        )

        target = previous
        if target is None:
            target = following
        elif following is not None:
            previous_span = previous["end_ts"] - previous["start_ts"]
            following_span = following["end_ts"] - following["start_ts"]
            if following_span > previous_span:
                target = following

        if target is None:
            break

        target["start_ts"] = min(target["start_ts"], interval["start_ts"])
        target["end_ts"] = max(target["end_ts"], interval["end_ts"])
        target["tracked_sec"] += interval["tracked_sec"]
        intervals.pop(shortest_index)

    return intervals


def _join_adjacent(intervals: list, merge_gap_seconds: float) -> list:
    joined = []
    for interval in intervals:
        if (
            joined
            and joined[-1]["project"] == interval["project"]
            and interval["start_ts"] - joined[-1]["end_ts"] <= merge_gap_seconds
        ):
            joined[-1]["end_ts"] = max(joined[-1]["end_ts"], interval["end_ts"])
            joined[-1]["tracked_sec"] += interval["tracked_sec"]
        else:
            joined.append(dict(interval))
    return joined


def get_project_intervals_for_date(
    target_date: date,
    merge_gap_seconds: float = DEFAULT_INTERVAL_GAP_SECONDS,
    min_interval_seconds: float = DEFAULT_MIN_INTERVAL_SECONDS,
) -> list:
    segments = get_segments_for_date(target_date)
    if not segments:
        return []

    intervals = []
    for segment in segments:
        project = segment.get("project") or ""
        start_ts = segment["start_ts"]
        end_ts = segment["end_ts"]
        duration = segment["duration_sec"] or 0

        if (
            intervals
            and intervals[-1]["project"] == project
            and start_ts - intervals[-1]["end_ts"] <= merge_gap_seconds
        ):
            intervals[-1]["end_ts"] = max(intervals[-1]["end_ts"], end_ts)
            intervals[-1]["tracked_sec"] += duration
        else:
            intervals.append({
                "project": project,
                "start_ts": start_ts,
                "end_ts": end_ts,
                "tracked_sec": duration,
            })

    intervals = _absorb_short_intervals(intervals, min_interval_seconds)
    intervals = _join_adjacent(intervals, merge_gap_seconds)

    day_start, day_end = _day_bounds(target_date)
    for interval in intervals:
        interval["start_ts"] = max(interval["start_ts"], day_start)
        interval["end_ts"] = min(interval["end_ts"], day_end - 1)

    return [i for i in intervals if i["end_ts"] > i["start_ts"]]


def delete_segments(segment_ids) -> int:
    ids = [int(i) for i in segment_ids]
    if not ids:
        return 0
    placeholders = ",".join("?" * len(ids))
    with _connection() as conn:
        return conn.execute(
            f"DELETE FROM activity_segments WHERE id IN ({placeholders})", ids
        ).rowcount


def reassign_segments(segment_ids, project: str) -> int:
    ids = [int(i) for i in segment_ids]
    if not ids:
        return 0
    placeholders = ",".join("?" * len(ids))
    with _connection() as conn:
        return conn.execute(
            f"UPDATE activity_segments SET project = ? WHERE id IN ({placeholders})",
            [project or ""] + ids,
        ).rowcount


def reassign_range(start_date: date, end_date: date, project: str,
                   only_from: Optional[str] = None) -> int:
    start_ts, end_ts = _range_bounds(start_date, end_date)
    sql = "UPDATE activity_segments SET project = ? WHERE start_ts >= ? AND start_ts < ?"
    params = [project or "", start_ts, end_ts]
    if only_from is not None:
        sql += " AND project = ?"
        params.append(only_from)

    with _connection() as conn:
        return conn.execute(sql, params).rowcount


def get_daily_totals_for_range(start_date: date, end_date: date) -> dict:
    start_ts, end_ts = _range_bounds(start_date, end_date)
    with _connection() as conn:
        rows = conn.execute(
            """
            SELECT date(start_ts, 'unixepoch', 'localtime') AS day,
                   SUM(duration_sec) AS total
            FROM activity_segments
            WHERE start_ts >= ? AND start_ts < ? AND is_idle = 0
            GROUP BY day
            ORDER BY day ASC
            """,
            (start_ts, end_ts),
        ).fetchall()
    return {row["day"]: row["total"] for row in rows}


def format_duration(seconds: float) -> str:
    seconds = int(seconds)
    hours, rem = divmod(seconds, 3600)
    minutes, _ = divmod(rem, 60)
    if hours and minutes:
        return f"{hours}h {minutes}m"
    if hours:
        return f"{hours}h"
    return f"{minutes}m"


def save_daily_archive(target_date: date, summary_text: str) -> None:
    with _connection() as conn:
        conn.execute(
            """
            INSERT INTO daily_archive (date, summary_text, created_at)
            VALUES (?, ?, ?)
            ON CONFLICT(date) DO UPDATE SET
                summary_text = excluded.summary_text,
                created_at = excluded.created_at
            """,
            (target_date.isoformat(), summary_text, time.time()),
        )


def get_daily_archive(target_date: date) -> Optional[dict]:
    with _connection() as conn:
        row = conn.execute(
            "SELECT * FROM daily_archive WHERE date = ?", (target_date.isoformat(),)
        ).fetchone()
    return dict(row) if row else None


def get_archived_summaries(start_date: date, end_date: date) -> dict:
    with _connection() as conn:
        rows = conn.execute(
            "SELECT date, summary_text FROM daily_archive WHERE date >= ? AND date <= ?",
            (start_date.isoformat(), end_date.isoformat()),
        ).fetchall()
    return {row["date"]: row["summary_text"] for row in rows}


def export_archive_to_markdown() -> Path:
    with _connection() as conn:
        rows = conn.execute("SELECT * FROM daily_archive ORDER BY date DESC").fetchall()

    lines = ["# Daily status history (archive)\n"]
    if not rows:
        lines.append(
            "The archive is empty for now. It fills up automatically every day, "
            "even if you never press 'Generate Daily' yourself."
        )
    for row in rows:
        lines.append(f"## {row['date']}\n")
        lines.append(row["summary_text"])
        lines.append("\n---\n")

    path = DB_PATH.parent / "history_export.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _escape(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _color_for_seconds(seconds: float, max_seconds: float) -> str:
    if seconds <= 0:
        return "#ebedf0"
    intensity = min(seconds / max_seconds, 1.0)
    green = int(230 - intensity * 100)
    return f"rgb(120,{green},120)"


_CALENDAR_CSS = """
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Helvetica Neue", sans-serif;
    background: #f6f8fa;
    color: #24292f;
    padding: 40px 5vw;
    margin: 0;
  }
  .wrapper { max-width: 1400px; margin: 0 auto; }
  h1 { font-size: 28px; margin-bottom: 6px; }
  .subtitle { color: #57606a; margin-bottom: 28px; font-size: 15px; }
  table { border-collapse: collapse; width: 100%; table-layout: fixed; }
  th { padding: 10px; font-size: 14px; color: #57606a; font-weight: 600; text-align: left; }
  td {
    border-radius: 8px;
    border: 3px solid #f6f8fa;
    height: 110px;
    width: 14.28%;
    vertical-align: top;
    padding: 10px;
    box-sizing: border-box;
  }
  td.empty { background: transparent; border: none; }
  .day-num { font-size: 16px; color: #24292f; font-weight: 700; }
  .day-hours { font-size: 14px; color: #24292f; margin-top: 8px; }
  .day-secondary { margin-top: 6px; display: flex; flex-wrap: wrap; gap: 3px; }
  .sync {
    position: absolute;
    top: 8px;
    right: 8px;
    width: 9px;
    height: 9px;
    border-radius: 50%;
  }
  .sync-ok { background: #1a7f37; }
  .sync-diff { background: #d4a72c; }
  .sync-none { background: #d0d7de; }
  td.day { position: relative; }
  details { margin-top: 6px; }
  details summary {
    cursor: pointer;
    font-size: 11px;
    color: #57606a;
    list-style: none;
    user-select: none;
  }
  details summary::-webkit-details-marker { display: none; }
  details summary:hover { color: #0969da; }
  details[open] summary { margin-bottom: 4px; }
  .task {
    font-size: 11px;
    color: #24292f;
    line-height: 15px;
    padding-left: 9px;
    text-indent: -9px;
  }
  .task::before { content: "• "; color: #57606a; }
  .legend {
    margin: 0 0 18px;
    font-size: 13px;
    color: #57606a;
    display: flex;
    gap: 16px;
    flex-wrap: wrap;
    align-items: center;
  }
  .legend i { display: inline-block; width: 9px; height: 9px; border-radius: 50%; }
  .badge {
    display: inline-block;
    font-size: 11px;
    font-weight: 600;
    color: #0969da;
    background: #ddf4ff;
    border-radius: 10px;
    padding: 2px 7px;
    line-height: 15px;
    white-space: nowrap;
  }
"""

_CALENDAR_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Calendar — {title}</title>
<style>{css}</style>
</head>
<body>
  <div class="wrapper">
    <h1>📅 {title}</h1>
    <div class="subtitle">{subtitle}</div>
    <div class="legend">{legend}</div>
    <table>
      <tr>{header_cells}</tr>
      {rows}
    </table>
  </div>
</body>
</html>
"""


SYNC_TOLERANCE_SECONDS = 300


def _sync_state(local_seconds: float, remote_seconds) -> tuple:
    if remote_seconds is None:
        return "", ""
    if not remote_seconds:
        return "sync-none", "not pushed to PeopleForce"
    if abs(local_seconds - remote_seconds) <= SYNC_TOLERANCE_SECONDS:
        return "sync-ok", f"in PeopleForce: {format_duration(remote_seconds)}"
    return "sync-diff", (
        f"PeopleForce has {format_duration(remote_seconds)}, "
        f"tracker has {format_duration(local_seconds)}"
    )


def export_calendar_html(
    year: int,
    month: int,
    project_names: Optional[dict] = None,
    remote_totals: Optional[dict] = None,
    logged_by_day: Optional[dict] = None,
) -> Path:
    start = date(year, month, 1)
    end = date(year, month, calendar_module.monthrange(year, month)[1])
    daily_totals = get_daily_totals_for_range(start, end)
    by_project = get_project_totals_by_day(start, end)
    project_names = project_names or {}
    logged_by_day = logged_by_day or {}

    max_seconds = max(daily_totals.values()) if daily_totals else 1
    total_seconds_month = sum(daily_totals.values())

    month_by_project = {}
    for entries in by_project.values():
        for project_id, seconds in entries:
            month_by_project[project_id] = month_by_project.get(project_id, 0) + seconds

    rows_html = []
    for week in calendar_module.monthcalendar(year, month):
        cells = []
        for day_num in week:
            if day_num == 0:
                cells.append('<td class="empty"></td>')
                continue

            day_str = date(year, month, day_num).isoformat()
            seconds = daily_totals.get(day_str, 0)
            color = _color_for_seconds(seconds, max_seconds)
            hours_label = format_duration(seconds) if seconds else ""

            badges = ""
            for project_id, project_seconds in by_project.get(day_str, []):
                if project_seconds <= 0:
                    continue
                name = _escape(project_names.get(project_id, "no project"))
                badges += (
                    f'<span class="badge">{name} '
                    f'{format_duration(project_seconds)}</span>'
                )
            if badges:
                badges = f'<div class="day-secondary">{badges}</div>'

            sync_html = ""
            if seconds and remote_totals is not None:
                css_class, hint = _sync_state(seconds, remote_totals.get(day_str, 0))
                if css_class:
                    sync_html = (
                        f'<span class="sync {css_class}" '
                        f'title="{_escape(hint)}"></span>'
                    )

            logged = logged_by_day.get(day_str, [])
            details_html = ""
            if logged:
                lines = "".join(
                    f'<div class="task">{_escape(item)}</div>'
                    for item in logged[:12]
                )
                if len(logged) > 12:
                    lines += f'<div class="task">+{len(logged) - 12} more</div>'
                details_html = (
                    f"<details><summary>what I did ›</summary>{lines}</details>"
                )

            cells.append(
                f'<td class="day" style="background:{color}">'
                f"{sync_html}"
                f'<div class="day-num">{day_num}</div>'
                f'<div class="day-hours">{hours_label}</div>'
                f"{badges}{details_html}"
                f"</td>"
            )
        rows_html.append(f"<tr>{''.join(cells)}</tr>")

    summary = f"Total this month: {format_duration(total_seconds_month)}"
    if month_by_project:
        parts = [
            f"{_escape(project_names.get(pid, 'no project'))} {format_duration(sec)}"
            for pid, sec in sorted(month_by_project.items(), key=lambda x: -x[1])
        ]
        summary += "  ·  " + "  ·  ".join(parts)

    legend = ""
    if remote_totals is not None:
        legend = (
            '<span><i class="sync-ok"></i> matches PeopleForce</span>'
            '<span><i class="sync-diff"></i> hours differ</span>'
            '<span><i class="sync-none"></i> not pushed yet</span>'
        )

    html = _CALENDAR_TEMPLATE.format(
        title=_escape(f"{MONTH_NAMES[month]} {year}"),
        css=_CALENDAR_CSS,
        subtitle=summary,
        legend=legend,
        header_cells="".join(f"<th>{w}</th>" for w in WEEKDAY_NAMES),
        rows="".join(rows_html),
    )

    path = DB_PATH.parent / f"calendar_{year}-{month:02d}.html"
    path.write_text(html, encoding="utf-8")
    return path