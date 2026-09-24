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

from datetime import date, datetime, time as dtime
from pathlib import Path

import os
import subprocess
import time

import objc
import rumps
from AppKit import (
    NSApplication, NSBackingStoreBuffered, NSBezelBorder, NSButton, NSOpenPanel,
    NSClosableWindowMask, NSColor, NSDatePicker, NSEvent, NSFloatingWindowLevel,
    NSFont, NSFontAttributeName, NSMakeRect, NSPanel, NSScreen, NSScrollView,
    NSTextField, NSTextView, NSTitledWindowMask,
)

try:
    from AppKit import NSSwitchButton
except ImportError:
    NSSwitchButton = 3
from Foundation import NSDate, NSObject, NSString, NSURL

from chronify import alerts

WEEKDAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def notify(text, title="", sound=False):
    stamp = {"stamp": time.time()}
    for kwargs in (dict(data=stamp, sound=sound), dict(data=stamp), {}):
        try:
            rumps.notification("Work Tracker", title, text, **kwargs)
            return True
        except Exception:
            continue
    return False


def _notify(text):
    notify(text)


DATE_PICKER_STYLE_STEPPER = 0
DATE_PICKER_ELEMENT_HOUR_MINUTE = 0x000C
PANEL_STYLE = NSTitledWindowMask | NSClosableWindowMask


def choose_docx_file(title="Choose an invoice"):
    panel = NSOpenPanel.openPanel()
    panel.setTitle_(title)
    panel.setCanChooseFiles_(True)
    panel.setCanChooseDirectories_(False)
    panel.setAllowsMultipleSelection_(False)
    panel.setAllowedFileTypes_(["docx"])

    NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
    if panel.runModal() != 1:
        return None

    urls = panel.URLs()
    return urls[0].path() if urls else None


def choose_folder(title="Choose a folder", current=""):
    panel = NSOpenPanel.openPanel()
    panel.setTitle_(title)
    panel.setCanChooseFiles_(False)
    panel.setCanChooseDirectories_(True)
    panel.setCanCreateDirectories_(True)
    panel.setAllowsMultipleSelection_(False)

    start = Path(os.path.expanduser(current or "~"))
    if start.is_dir():
        panel.setDirectoryURL_(NSURL.fileURLWithPath_(str(start)))

    NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
    if panel.runModal() != 1:
        return None

    urls = panel.URLs()
    return urls[0].path() if urls else None


def reveal_in_finder(path) -> None:
    subprocess.run(["open", "-R", str(path)])


def screen_frame_at_mouse():
    try:
        mouse_loc = NSEvent.mouseLocation()
        for screen in NSScreen.screens():
            frame = screen.frame()
            if (frame.origin.x <= mouse_loc.x <= frame.origin.x + frame.size.width and
                    frame.origin.y <= mouse_loc.y <= frame.origin.y + frame.size.height):
                return screen.visibleFrame()
        return NSScreen.mainScreen().visibleFrame()
    except Exception:
        return None


def top_right_origin(width, height, margin, fallback):
    frame = screen_frame_at_mouse()
    if frame is None and NSScreen.mainScreen():
        frame = NSScreen.mainScreen().visibleFrame()
    if frame is None:
        return fallback
    return (
        frame.origin.x + frame.size.width - width - margin,
        frame.origin.y + frame.size.height - height - margin,
    )


def center_rumps_window_at_mouse(window):
    try:
        alert_window = window._alert.window()
        screen_frame = screen_frame_at_mouse()
        if screen_frame is None:
            return
        win_frame = alert_window.frame()
        new_x = screen_frame.origin.x + (screen_frame.size.width - win_frame.size.width) / 2
        new_y = screen_frame.origin.y + (screen_frame.size.height - win_frame.size.height) / 2
        alert_window.setFrameOrigin_((new_x, new_y))
    except Exception:
        pass


def make_window_always_on_top(window):
    try:
        center_rumps_window_at_mouse(window)
        alert_window = window._alert.window()
        alert_window.setLevel_(NSFloatingWindowLevel)
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        alert_window.makeKeyAndOrderFront_(None)
    except Exception:
        pass


COMMAND_KEY_MASK = 1 << 20


def make_button(title, frame, target, method, key="", command=False,
                font_size=None):
    button = NSButton.alloc().initWithFrame_(frame)
    button.setTitle_(title)
    button.setBezelStyle_(1)
    button.setTarget_(target)
    button.setAction_(objc.selector(method, signature=b"v@:@"))
    if key:
        # "\r" is the default button, "\x1b" is Esc, command adds ⌘.
        button.setKeyEquivalent_(key)
        if command:
            button.setKeyEquivalentModifierMask_(COMMAND_KEY_MASK)
    if font_size is not None:
        button.setFont_(NSFont.systemFontOfSize_(font_size))
    return button


NS_STRING_LINE_FRAGMENT_ORIGIN = 1 << 0


def wrapped_height(text, width, font_size=11):
    if not text:
        return 0
    font = NSFont.systemFontOfSize_(font_size)
    try:
        bounds = NSString.stringWithString_(text).boundingRectWithSize_options_attributes_(
            (width, 400), NS_STRING_LINE_FRAGMENT_ORIGIN, {NSFontAttributeName: font}
        )
        return max(15, int(bounds.size.height) + 3)
    except Exception:
        per_line = max(20, int(width // (font_size * 0.55)))
        return 15 * (len(text) // per_line + 1)


def hint_label(text, frame):
    label = NSTextField.alloc().initWithFrame_(frame)
    label.setStringValue_(text)
    label.setEditable_(False)
    label.setBezeled_(False)
    label.setDrawsBackground_(False)
    label.setSelectable_(False)
    label.setFont_(NSFont.systemFontOfSize_(10))
    label.setTextColor_(NSColor.secondaryLabelColor())
    label.setUsesSingleLineMode_(False)
    label.cell().setWraps_(True)
    return label


def make_panel(origin, width, height, title):
    panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
        NSMakeRect(origin[0], origin[1], width, height),
        PANEL_STYLE, NSBackingStoreBuffered, False,
    )
    panel.setTitle_(title)
    panel.setLevel_(NSFloatingWindowLevel)
    # NSPanel hides itself whenever the app is not frontmost; ours must not.
    panel.setHidesOnDeactivate_(False)
    return panel


class AlertEditorController(NSObject):
    WIDTH = 400
    HEIGHT = 268

    def initWithApp_alertId_(self, app, alert_id):
        self = objc.super(AlertEditorController, self).init()
        if self is None:
            return None
        self.app = app
        self.alert_id = alert_id
        self.window = None
        self.text_field = None
        self.time_picker = None
        self.day_boxes = []
        self.one_shot_box = None
        return self

    @staticmethod
    def _checkbox(title, frame, state=False):
        box = NSButton.alloc().initWithFrame_(frame)
        box.setButtonType_(NSSwitchButton)
        box.setTitle_(title)
        box.setFont_(NSFont.systemFontOfSize_(11))
        box.setState_(1 if state else 0)
        return box

    @staticmethod
    def _label(text, frame):
        label = NSTextField.alloc().initWithFrame_(frame)
        label.setStringValue_(text)
        label.setEditable_(False)
        label.setBezeled_(False)
        label.setDrawsBackground_(False)
        label.setSelectable_(False)
        label.setFont_(NSFont.systemFontOfSize_(11))
        return label

    @staticmethod
    def _initial_date(alert):
        if alert:
            moment = datetime.combine(
                date.today(),
                dtime(hour=alert.get("hour", 0), minute=alert.get("minute", 0)),
            )
        else:
            now = datetime.now()
            moment = datetime.combine(date.today(), dtime(hour=(now.hour + 1) % 24, minute=0))
        return NSDate.dateWithTimeIntervalSince1970_(moment.timestamp())

    def show(self):
        alert = alerts.get_alert(self.alert_id) if self.alert_id else None
        if self.alert_id and alert is None:
            self.app.rebuild_alerts_menu()
            return

        origin = top_right_origin(self.WIDTH, self.HEIGHT, 20, (900, 500))
        self.window = make_panel(
            origin, self.WIDTH, self.HEIGHT,
            "Edit reminder" if alert else "New reminder",
        )
        self.window.setReleasedWhenClosed_(False)

        content = self.window.contentView()

        content.addSubview_(self._label("Remind me about:", NSMakeRect(16, 226, 200, 16)))
        self.text_field = NSTextField.alloc().initWithFrame_(
            NSMakeRect(16, 196, self.WIDTH - 32, 26)
        )
        self.text_field.setStringValue_(alert["text"] if alert else "")
        self.text_field.setPlaceholderString_("e.g. check email")
        self.text_field.setFont_(NSFont.systemFontOfSize_(13))
        content.addSubview_(self.text_field)

        content.addSubview_(self._label("Time:", NSMakeRect(16, 166, 100, 16)))
        self.time_picker = NSDatePicker.alloc().initWithFrame_(NSMakeRect(16, 134, 110, 28))
        self.time_picker.setDatePickerStyle_(DATE_PICKER_STYLE_STEPPER)
        self.time_picker.setDatePickerElements_(DATE_PICKER_ELEMENT_HOUR_MINUTE)
        self.time_picker.setDateValue_(self._initial_date(alert))
        content.addSubview_(self.time_picker)

        content.addSubview_(
            self._label("Repeat on (none ticked = every day):",
                        NSMakeRect(16, 108, 300, 16))
        )

        selected = set(alerts._clean_days((alert or {}).get("days")))
        self.day_boxes = []
        for index, name in enumerate(WEEKDAY_LABELS):
            box = self._checkbox(
                name, NSMakeRect(16 + index * 52, 82, 50, 20), index in selected
            )
            content.addSubview_(box)
            self.day_boxes.append(box)

        self.one_shot_box = self._checkbox(
            "Only once, then delete itself",
            NSMakeRect(16, 54, 260, 20),
            bool((alert or {}).get("one_shot")),
        )
        content.addSubview_(self.one_shot_box)

        content.addSubview_(
            make_button("Save", NSMakeRect(16, 14, 110, 30), self,
                        self.saveClicked_, key="\r")
        )
        if alert:
            content.addSubview_(
                make_button("Delete", NSMakeRect(134, 14, 100, 30), self, self.deleteClicked_)
            )
        content.addSubview_(
            make_button(
                "Cancel", NSMakeRect(self.WIDTH - 110, 14, 94, 30), self,
                self.cancelClicked_, key="\x1b",
            )
        )

        self.window.makeKeyAndOrderFront_(None)
        self.window.makeFirstResponder_(self.text_field)
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)

    def _picked_time(self):
        moment = datetime.fromtimestamp(self.time_picker.dateValue().timeIntervalSince1970())
        return moment.hour, moment.minute

    def saveClicked_(self, sender):
        text = self.text_field.stringValue().strip()
        if not text:
            rumps.alert(title="Empty text", message="Write what you want to be reminded about.")
            return

        hour, minute = self._picked_time()
        days = [i for i, box in enumerate(self.day_boxes) if box.state()]
        one_shot = bool(self.one_shot_box.state())

        if self.alert_id:
            alerts.update_alert(self.alert_id, hour, minute, text, days, one_shot)
        else:
            alerts.add_alert(hour, minute, text, days, one_shot)

        self.window.close()
        self.app.rebuild_alerts_menu()
        _notify(
            "Reminder set: "
            + alerts.format_schedule(
                {"hour": hour, "minute": minute, "days": days, "one_shot": one_shot}
            )
            + " ⏰"
        )

    def deleteClicked_(self, sender):
        alerts.delete_alerts([self.alert_id])
        self.window.close()
        self.app.rebuild_alerts_menu()
        _notify("Reminder deleted 🗑")

    def cancelClicked_(self, sender):
        self.window.close()


class QuickInputController(NSObject):
    WIDTH = 460
    EDITOR_HEIGHT = 110

    def initWithCallback_title_message_(self, callback, title, message):
        self = objc.super(QuickInputController, self).init()
        if self is None:
            return None
        self.callback = callback
        self.title_text = title
        self.message_text = message
        self.window = None
        self.text_view = None
        return self

    def show(self):
        width = self.WIDTH
        inner = width - 28

        message_height = wrapped_height(self.message_text, inner, 12)
        height = 55 + self.EDITOR_HEIGHT + 10 + message_height + 16

        origin = top_right_origin(width, height, 10, (1000, 700))

        self.window = make_panel(origin, width, height, self.title_text)
        self.window.setFrameOrigin_(origin)

        content = self.window.contentView()

        if message_height:
            prompt = hint_label(
                self.message_text,
                NSMakeRect(14, 55 + self.EDITOR_HEIGHT + 10, inner, message_height),
            )
            prompt.setFont_(NSFont.systemFontOfSize_(12))
            prompt.setTextColor_(NSColor.labelColor())
            content.addSubview_(prompt)

        scroll_view = NSScrollView.alloc().initWithFrame_(
            NSMakeRect(14, 55, inner, self.EDITOR_HEIGHT)
        )
        scroll_view.setHasVerticalScroller_(True)
        scroll_view.setBorderType_(NSBezelBorder)

        self.text_view = NSTextView.alloc().initWithFrame_(scroll_view.bounds())
        self.text_view.setAutoresizingMask_(18)
        self.text_view.setRichText_(False)
        self.text_view.setImportsGraphics_(False)
        self.text_view.setFont_(NSFont.systemFontOfSize_(14))
        self.text_view.setTextColor_(NSColor.textColor())
        self.text_view.setInsertionPointColor_(NSColor.textColor())

        scroll_view.setDocumentView_(self.text_view)
        content.addSubview_(scroll_view)

        content.addSubview_(
            make_button(
                "Cancel", NSMakeRect(width - 215, 12, 95, 32), self,
                self.cancelClicked_, key="\x1b",
            )
        )
        content.addSubview_(
            make_button(
                "Save", NSMakeRect(width - 110, 12, 95, 32), self,
                self.saveClicked_, key="\r", command=True,
            )
        )
        content.addSubview_(
            hint_label("⌘V pastes · ⌘⏎ saves · Esc closes",
                       NSMakeRect(16, 20, width - 230, 16))
        )

        self.window.makeKeyAndOrderFront_(None)
        self.window.makeFirstResponder_(self.text_view)
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)

    def saveClicked_(self, sender):
        text = self.text_view.string().strip()
        if text:
            self.callback(text)
        self.window.close()

    def cancelClicked_(self, sender):
        self.window.close()