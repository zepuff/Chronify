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

import objc
from AppKit import (
    NSApplication, NSBezelBorder, NSColor, NSFont, NSMakeRect, NSPopUpButton,
    NSScrollView, NSSecureTextField, NSTextField, NSTextView, NSView,
)
from Foundation import NSObject

from chronify.ui_windows import (
    choose_folder, hint_label, make_button, make_panel, top_right_origin,
    wrapped_height,
)

WIDTH = 610
LABEL_WIDTH = 185
ROW_HEIGHT = 32
FIELD_HEIGHT = 22
HINT_GAP = 5
ROW_GAP = 12
PAD = 18
MAX_BODY = 470
BUTTON_HEIGHT = 34
STATUS_HEIGHT = 18
INTRO_HEIGHT = 52
HINT_SIZE = 11


class FlippedView(NSView):
    def isFlipped(self):
        return True


def _static_label(text, frame, color=None):
    field = NSTextField.alloc().initWithFrame_(frame)
    field.setStringValue_(text)
    field.setEditable_(False)
    field.setBezeled_(False)
    field.setDrawsBackground_(False)
    field.setSelectable_(False)
    field.setFont_(NSFont.systemFontOfSize_(11))
    if color is not None:
        field.setTextColor_(color)
    return field


def _hint_label(text, frame):
    label = _static_label(text, frame, NSColor.secondaryLabelColor())
    label.setFont_(NSFont.systemFontOfSize_(HINT_SIZE))
    label.setUsesSingleLineMode_(False)
    label.cell().setWraps_(True)
    return label


def _choice_for(spec, frame):
    button = NSPopUpButton.alloc().initWithFrame_pullsDown_(frame, False)
    titles = [title for title, _ in spec["options"]]
    button.addItemsWithTitles_(titles)

    current = str(spec.get("value") or "")
    for title, value in spec["options"]:
        if value == current:
            button.selectItemWithTitle_(title)
            break

    button.setFont_(NSFont.systemFontOfSize_(12))
    if spec.get("hint"):
        button.setToolTip_(spec["hint"])
    return button


SIDE_BUTTON_WIDTH = 74


def _text_field(cls, spec, frame):
    field = cls.alloc().initWithFrame_(frame)
    field.setStringValue_(str(spec.get("value") or ""))
    field.setFont_(NSFont.systemFontOfSize_(12))
    if spec.get("hint"):
        field.setToolTip_(spec["hint"])
    placeholder = spec.get("placeholder") or (
        "optional" if spec.get("optional", True) else ""
    )
    if placeholder:
        field.setPlaceholderString_(placeholder)
    return field


def _input_for(spec, frame):
    if spec.get("kind") == "choice":
        return _choice_for(spec, frame)

    cls = NSSecureTextField if spec.get("kind") == "secret" else NSTextField
    return _text_field(cls, spec, frame)


def _row_heights(fields, hint_width):
    heights = []
    for spec in fields:
        height = ROW_HEIGHT
        if spec.get("hint"):
            height += HINT_GAP + wrapped_height(spec["hint"], hint_width)
        heights.append(height + ROW_GAP)
    return heights


def _build_rows(fields, inner_width, controller):
    field_x = LABEL_WIDTH + 8
    full_width = inner_width - field_x - 4

    heights = _row_heights(fields, full_width)
    height = max(sum(heights), 1)
    body = FlippedView.alloc().initWithFrame_(NSMakeRect(0, 0, inner_width, height))

    controls = {}
    secrets = {}
    previous = None
    top = 0

    for index, spec in enumerate(fields):
        kind = spec.get("kind", "text")
        caption = spec["label"] + ("" if spec.get("optional", True) else " *")

        label = _static_label(caption, NSMakeRect(0, top + 5, LABEL_WIDTH, 16))
        body.addSubview_(label)

        has_button = kind in ("secret", "folder")
        field_width = full_width - (SIDE_BUTTON_WIDTH + 6 if has_button else 0)
        field_frame = NSMakeRect(field_x, top + 2, field_width, FIELD_HEIGHT)
        button_frame = NSMakeRect(
            field_x + field_width + 6, top, SIDE_BUTTON_WIDTH, FIELD_HEIGHT + 4
        )

        field = _input_for(spec, field_frame)
        body.addSubview_(field)
        controls[spec["key"]] = field

        if kind == "secret":
            plain = _text_field(NSTextField, spec, field_frame)
            plain.setHidden_(True)
            body.addSubview_(plain)
            secrets[spec["key"]] = (field, plain)

            button = make_button(
                "Show", button_frame, controller, controller.toggleSecretClicked_,
                font_size=11,
            )
            button.setTag_(index)
            body.addSubview_(button)
            controller.secret_keys[index] = spec["key"]

        elif kind == "folder":
            button = make_button(
                "Choose…", button_frame, controller, controller.chooseFolderClicked_,
                font_size=11,
            )
            button.setTag_(index)
            body.addSubview_(button)
            controller.folder_keys[index] = spec["key"]

        if spec.get("hint"):
            hint_top = top + ROW_HEIGHT + HINT_GAP - 4
            body.addSubview_(_hint_label(
                spec["hint"],
                NSMakeRect(field_x, hint_top, full_width,
                           wrapped_height(spec["hint"], full_width)),
            ))

        if previous is not None:
            previous.setNextKeyView_(field)
        previous = field
        top += heights[index]

    return body, height, controls, secrets


def _visible_control(controls, secrets, key):
    pair = secrets.get(key)
    if pair is None:
        return controls[key]
    secure, plain = pair
    return plain if secure.isHidden() else secure


def _read(spec, control) -> str:
    if spec.get("kind") == "choice":
        chosen = control.titleOfSelectedItem()
        for title, value in spec["options"]:
            if title == chosen:
                return value
        return ""
    return control.stringValue().strip()


def _problems(fields, values):
    bad = []
    for spec in fields:
        raw = values.get(spec["key"], "")
        kind = spec.get("kind", "text")
        if not raw:
            if not spec.get("optional", True):
                bad.append(f"{spec['label']}: required")
            continue
        try:
            if kind == "int":
                int(raw)
            elif kind == "float":
                float(raw.replace(",", "."))
        except ValueError:
            bad.append(f"{spec['label']}: expected a number")
    return bad


def _first_problem(bad):
    if len(bad) == 1:
        return bad[0]
    return f"{bad[0]} (+{len(bad) - 1} more)"


class FormController(NSObject):

    def initWithSpec_(self, spec):
        self = objc.super(FormController, self).init()
        if self is None:
            return None
        self.title_text = spec.get("title", "Settings")
        self.intro_text = spec.get("intro", "")
        self.fields = [dict(f) for f in spec.get("fields", [])]
        self.on_save = spec.get("on_save")
        self.extra_label = spec.get("extra_label")
        self.on_extra = spec.get("on_extra")
        self.on_close = spec.get("on_close")
        self.window = None
        self.controls = {}
        self.secrets = {}
        self.secret_keys = {}
        self.folder_keys = {}
        self.status = None
        return self

    def show(self):
        inner_width = WIDTH - PAD * 2
        body, body_height, self.controls, self.secrets = _build_rows(
            self.fields, inner_width, self
        )
        body_visible = min(body_height, MAX_BODY)

        intro_height = (
            max(INTRO_HEIGHT, wrapped_height(self.intro_text, inner_width) + 6)
            if self.intro_text else 0
        )
        height = (
            PAD * 2
            + BUTTON_HEIGHT
            + 8 + STATUS_HEIGHT
            + 10 + body_visible
            + (8 + intro_height if intro_height else 0)
        )

        origin = top_right_origin(WIDTH, height, 20, (900, 400))
        self.window = make_panel(origin, WIDTH, height, self.title_text)
        self.window.setReleasedWhenClosed_(False)
        content = self.window.contentView()

        buttons_y = PAD
        status_y = buttons_y + BUTTON_HEIGHT + 8
        body_y = status_y + STATUS_HEIGHT + 10
        intro_y = body_y + body_visible + 8

        if intro_height:
            intro = _static_label(
                self.intro_text,
                NSMakeRect(PAD, intro_y, inner_width, intro_height),
                NSColor.secondaryLabelColor(),
            )
            intro.setUsesSingleLineMode_(False)
            content.addSubview_(intro)

        scroll = NSScrollView.alloc().initWithFrame_(
            NSMakeRect(PAD, body_y, inner_width, body_visible)
        )
        scroll.setDrawsBackground_(False)
        scroll.setHasVerticalScroller_(body_height > body_visible)
        scroll.setDocumentView_(body)
        content.addSubview_(scroll)

        self.status = _static_label(
            "", NSMakeRect(PAD, status_y, inner_width, STATUS_HEIGHT),
            NSColor.systemRedColor(),
        )
        content.addSubview_(self.status)

        content.addSubview_(make_button(
            "Save", NSMakeRect(WIDTH - 118, buttons_y, 100, 30),
            self, self.saveClicked_, key="\r",
        ))
        content.addSubview_(make_button(
            "Cancel", NSMakeRect(WIDTH - 226, buttons_y, 100, 30),
            self, self.cancelClicked_, key="\x1b",
        ))
        if self.extra_label and self.on_extra:
            content.addSubview_(make_button(
                self.extra_label, NSMakeRect(PAD, buttons_y, 240, 30),
                self, self.extraClicked_,
            ))
        else:
            content.addSubview_(hint_label(
                "⌘V pastes · ⏎ saves · Esc closes",
                NSMakeRect(PAD, buttons_y + 8, 260, 16),
            ))

        self.window.makeKeyAndOrderFront_(None)
        if self.fields:
            self.window.makeFirstResponder_(self.controls[self.fields[0]["key"]])
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)

    def toggleSecretClicked_(self, sender):
        key = self.secret_keys.get(int(sender.tag()))
        if key is None:
            return
        secure, plain = self.secrets[key]

        if secure.isHidden():
            secure.setStringValue_(plain.stringValue())
            plain.setHidden_(True)
            secure.setHidden_(False)
            sender.setTitle_("Show")
            self.window.makeFirstResponder_(secure)
        else:
            plain.setStringValue_(secure.stringValue())
            secure.setHidden_(True)
            plain.setHidden_(False)
            sender.setTitle_("Hide")
            self.window.makeFirstResponder_(plain)

    def chooseFolderClicked_(self, sender):
        key = self.folder_keys.get(int(sender.tag()))
        if key is None:
            return
        control = self.controls[key]
        picked = choose_folder("Choose a folder", control.stringValue())
        if picked:
            control.setStringValue_(picked)

    def saveClicked_(self, sender):
        by_key = {spec["key"]: spec for spec in self.fields}
        values = {
            key: _read(
                by_key.get(key, {}),
                _visible_control(self.controls, self.secrets, key),
            )
            for key in self.controls
        }

        bad = _problems(self.fields, values)
        if bad:
            self.status.setStringValue_(_first_problem(bad))
            return

        error = self.on_save(values) if self.on_save else None
        if error:
            self.status.setStringValue_(str(error))
            return

        self.dismiss()

    def extraClicked_(self, sender):
        self.dismiss()
        self.on_extra()

    def cancelClicked_(self, sender):
        self.dismiss()

    def dismiss(self):
        self.window.close()
        if self.on_close:
            self.on_close(self)


EDITOR_WIDTH = 720
EDITOR_BODY_HEIGHT = 460


class EditorController(NSObject):

    def initWithSpec_(self, spec):
        self = objc.super(EditorController, self).init()
        if self is None:
            return None
        self.title_text = spec.get("title", "")
        self.intro_text = spec.get("intro", "")
        self.body_text = spec.get("body", "")
        self.on_save = spec.get("on_save")
        self.on_close = spec.get("on_close")
        self.extra_label = spec.get("extra_label")
        self.on_extra = spec.get("on_extra")
        self.window = None
        self.view = None
        self.status = None
        return self

    def show(self):
        inner_width = EDITOR_WIDTH - PAD * 2
        intro_height = 34 if self.intro_text else 0
        height = (
            PAD * 2 + BUTTON_HEIGHT + 8 + STATUS_HEIGHT
            + 10 + EDITOR_BODY_HEIGHT
            + (8 + intro_height if intro_height else 0)
        )

        origin = top_right_origin(EDITOR_WIDTH, height, 20, (760, 260))
        self.window = make_panel(origin, EDITOR_WIDTH, height, self.title_text)
        self.window.setReleasedWhenClosed_(False)
        content = self.window.contentView()

        buttons_y = PAD
        status_y = buttons_y + BUTTON_HEIGHT + 8
        body_y = status_y + STATUS_HEIGHT + 10
        intro_y = body_y + EDITOR_BODY_HEIGHT + 8

        if intro_height:
            intro = _static_label(
                self.intro_text,
                NSMakeRect(PAD, intro_y, inner_width, intro_height),
                NSColor.secondaryLabelColor(),
            )
            intro.setUsesSingleLineMode_(False)
            content.addSubview_(intro)

        scroll = NSScrollView.alloc().initWithFrame_(
            NSMakeRect(PAD, body_y, inner_width, EDITOR_BODY_HEIGHT)
        )
        scroll.setHasVerticalScroller_(True)
        scroll.setBorderType_(NSBezelBorder)

        self.view = NSTextView.alloc().initWithFrame_(scroll.bounds())
        self.view.setAutoresizingMask_(18)
        self.view.setRichText_(False)
        self.view.setAutomaticQuoteSubstitutionEnabled_(False)
        self.view.setAutomaticDashSubstitutionEnabled_(False)
        self.view.setFont_(NSFont.userFixedPitchFontOfSize_(12)
                           or NSFont.systemFontOfSize_(12))
        self.view.setTextColor_(NSColor.textColor())
        self.view.setString_(self.body_text)
        scroll.setDocumentView_(self.view)
        content.addSubview_(scroll)

        self.status = _static_label(
            "", NSMakeRect(PAD, status_y, inner_width, STATUS_HEIGHT),
            NSColor.systemRedColor(),
        )
        content.addSubview_(self.status)

        content.addSubview_(make_button(
            "Save", NSMakeRect(EDITOR_WIDTH - 118, buttons_y, 100, 30),
            self, self.saveClicked_, key="\r", command=True,
        ))
        content.addSubview_(make_button(
            "Cancel", NSMakeRect(EDITOR_WIDTH - 226, buttons_y, 100, 30),
            self, self.cancelClicked_, key="\x1b",
        ))
        if self.extra_label and self.on_extra:
            content.addSubview_(make_button(
                self.extra_label, NSMakeRect(PAD, buttons_y, 240, 30),
                self, self.extraClicked_,
            ))
        else:
            content.addSubview_(hint_label(
                "⌘V pastes · ⌘⏎ saves · Esc closes",
                NSMakeRect(PAD, buttons_y + 8, 260, 16),
            ))

        self.window.makeKeyAndOrderFront_(None)
        self.window.makeFirstResponder_(self.view)
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)

    def saveClicked_(self, sender):
        self.status.setStringValue_("Checking…")
        error = self.on_save(self.view.string()) if self.on_save else None
        if error:
            self.status.setStringValue_(str(error))
            return
        self.dismiss()

    def extraClicked_(self, sender):
        message = self.on_extra(self.view.string())
        if message:
            self.status.setStringValue_(str(message))

    def cancelClicked_(self, sender):
        self.dismiss()

    def dismiss(self):
        self.window.close()
        if self.on_close:
            self.on_close(self)