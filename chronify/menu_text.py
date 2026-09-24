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

"""Menu labels and the grey line printed under each of them."""

from AppKit import (
    NSColor, NSFont, NSFontAttributeName, NSForegroundColorAttributeName,
    NSMutableAttributedString, NSMutableParagraphStyle,
    NSParagraphStyleAttributeName,
)

PAUSE = "⏸ Pause tracking"
RESUME = "▶️ Resume tracking"
PROJECT = "🏷 Project"
STATUS = "✨ Write today's status"
TASKS = "✅ What I did today"
NOTES = "💭 Notes to self"
BLOCKERS = "🚧 What is blocking me"
PLAN = "📋 Plan for today"
ALERTS = "⏰ Remind me at a time"
INFRA = "🚦 Infrastructure status"
STATS = "📊 Where today went"
DAY = "📆 Another day"
CALENDAR = "📅 Month calendar"
INVOICE = "🧾 Invoice"
PUSH = "📤 Send hours to PeopleForce"
HISTORY = "📝 Status history"
SETTINGS = "⚙️ Settings"
RELOAD = "🔄 Reload rules"
DATA_FOLDER = "📁 Show my data folder"
QUIT = "Quit"

PIN = "📌 Show in the menu bar"
SCOPE = "Separate tasks & notes per project"
REAL_INTERVALS = "Push real time ranges"
AUTO_PUSH = "Auto-push at 00:00"

NOTES_BY_TITLE = {
    PAUSE: "Records nothing until you switch it back on",
    RESUME: "Start recording again",
    PROJECT: "Which project today's hours belong to. Add, edit, move days",
    STATUS: "Turns today's notes into text you can paste into Slack",
    TASKS: "Log each thing you finish. The status is written from these",
    NOTES: "Anything worth remembering. No date, stays until you delete it",
    BLOCKERS: "Goes into the daily status as its own section",
    PLAN: "Tick things off. Whatever is left moves to tomorrow",
    ALERTS: "Alarms with your own text, on the days you pick",
    INFRA: "One line added to the status: 🟢 🟡 🔴 or your own wording",
    STATS: "Hours per task so far today",
    DAY: "The last 30 days: hours, the status, and fixing what was recorded",
    CALENDAR: "Opens a heat map of the month in your browser",
    INVOICE: "Make this month's invoice, or read your details from an old one",
    PUSH: "Sends the hours and the status text into your timesheet",
    HISTORY: "Every saved status, collected into one file",
    SETTINGS: "PeopleForce key, who writes the status, invoice details, permissions",
    RELOAD: "Re-read config.yaml after editing how windows become tasks",
    DATA_FOLDER: "Everything the app saves, in ~/.work_tracker. Your backup",
    QUIT: "Stops tracking until you start Chronify again",

    PIN: "Keeps one unfinished item in front of your eyes all day",
    SCOPE: "Off: one shared list. On: every project gets its own",
    REAL_INTERVALS: "On: 09:00-10:37 as recorded. Off: one entry per project",
    AUTO_PUSH: "Sends yesterday by itself, catching up to a week back",
}


def _utf16_length(text: str) -> int:
    """AppKit counts in UTF-16, where an emoji can be two units long."""
    return len(text.encode("utf-16-le")) // 2


def explain(item, note: str = "") -> None:
    title = item.title
    note = note or NOTES_BY_TITLE.get(title, "")
    if not note:
        return

    text = f"{title}\n{note}"
    attributed = NSMutableAttributedString.alloc().initWithString_(text)

    title_length = _utf16_length(title)
    note_range = (title_length + 1, _utf16_length(note))

    attributed.addAttribute_value_range_(
        NSFontAttributeName, NSFont.menuFontOfSize_(0), (0, title_length)
    )
    attributed.addAttribute_value_range_(
        NSFontAttributeName, NSFont.menuFontOfSize_(11), note_range
    )
    attributed.addAttribute_value_range_(
        NSForegroundColorAttributeName, NSColor.secondaryLabelColor(), note_range
    )

    spacing = NSMutableParagraphStyle.alloc().init()
    spacing.setParagraphSpacingBefore_(1.0)
    attributed.addAttribute_value_range_(
        NSParagraphStyleAttributeName, spacing, (0, _utf16_length(text))
    )

    item._menuitem.setAttributedTitle_(attributed)


def explain_all(items) -> None:
    for item in items:
        try:
            explain(item)
        except Exception:
            continue
