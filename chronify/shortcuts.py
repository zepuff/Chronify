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

"""Main menu, key handling and Dock policy, set up before the event loop."""

from AppKit import (
    NSApplication, NSApplicationActivationPolicyAccessory, NSEvent, NSMenu,
    NSMenuItem,
)

NSEventMaskKeyDown = 1 << 10
NSEventModifierFlagShift = 1 << 17
NSEventModifierFlagControl = 1 << 18
NSEventModifierFlagOption = 1 << 19
NSEventModifierFlagCommand = 1 << 20

# title, selector, key, needs shift
EDIT_ITEMS = (
    ("Undo", "undo:", "z", False),
    ("Redo", "redo:", "z", True),
    (None, None, None, False),
    ("Cut", "cut:", "x", False),
    ("Copy", "copy:", "c", False),
    ("Paste", "paste:", "v", False),
    ("Select All", "selectAll:", "a", False),
)

# Fallback for modal windows, where the main menu is not consulted.
KEY_ACTIONS = {
    "z": ("undo:", "redo:"),
    "x": ("cut:", None),
    "c": ("copy:", None),
    "v": ("paste:", None),
    "a": ("selectAll:", None),
    "w": ("performClose:", None),
}

_monitor = None


def install_edit_menu() -> None:
    """Give the app an Edit menu so the usual text shortcuts work."""
    app = NSApplication.sharedApplication()
    if app.mainMenu() is not None:
        return

    edit_menu = NSMenu.alloc().initWithTitle_("Edit")
    for title, selector, key, shift in EDIT_ITEMS:
        if title is None:
            edit_menu.addItem_(NSMenuItem.separatorItem())
            continue
        item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            title, selector, key
        )
        if shift:
            item.setKeyEquivalentModifierMask_(
                NSEventModifierFlagCommand | NSEventModifierFlagShift
            )
        edit_menu.addItem_(item)

    edit_item = NSMenuItem.alloc().init()
    edit_item.setSubmenu_(edit_menu)

    main_menu = NSMenu.alloc().init()
    main_menu.addItem_(edit_item)
    app.setMainMenu_(main_menu)


def install_key_monitor() -> None:
    """Handle ⌘-keys the menu never sees, such as inside a modal alert."""
    global _monitor
    if _monitor is not None:
        return

    app = NSApplication.sharedApplication()

    def handle(event):
        flags = event.modifierFlags()
        if not flags & NSEventModifierFlagCommand:
            return event
        if flags & (NSEventModifierFlagControl | NSEventModifierFlagOption):
            return event

        actions = KEY_ACTIONS.get((event.charactersIgnoringModifiers() or "").lower())
        if actions is None:
            return event

        plain, shifted = actions
        selector = shifted if (flags & NSEventModifierFlagShift) else plain
        if selector is None:
            return event

        if app.sendAction_to_from_(selector, None, app):
            return None
        return event

    _monitor = NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
        NSEventMaskKeyDown, handle
    )


def hide_from_dock() -> None:
    NSApplication.sharedApplication().setActivationPolicy_(
        NSApplicationActivationPolicyAccessory
    )


def prepare_app() -> None:
    hide_from_dock()
    install_edit_menu()
    install_key_monitor()
