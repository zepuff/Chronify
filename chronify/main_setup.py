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

import rumps
from PyObjCTools import AppHelper

from chronify import (
    invoice, invoice_import, projects, tracker,
)
from chronify.config import (
    BASE_DIR, ProfileWriteError, load_config, save_profile_value,
)
from chronify.forms import EditorController, FormController
from chronify.ui_windows import choose_docx_file, notify

SETTINGS_SECTIONS = [
    {
        "key": "peopleforce",
        "title": "PeopleForce",
        "intro": "Lets the app push tracked hours and the daily status "
                 "straight into PeopleForce.",
        "required": [("peopleforce", "api_key"), ("peopleforce", "employee_id")],
        "fields": [
            {"path": ["peopleforce", "api_key"], "label": "Company API key",
             "kind": "secret", "optional": False,
             "hint": "PeopleForce only issues company-wide keys. "
                     "Settings -> API keys."},
            {"path": ["peopleforce", "employee_id"], "label": "Employee id",
             "kind": "int", "optional": False,
             "hint": "The number at the end of your own profile URL "
                     "in PeopleForce."},
            {"path": ["peopleforce", "start_hour"], "label": "Working day starts at",
             "kind": "int", "placeholder": "9",
             "hint": "Hour a timesheet entry starts from."},
        ],
    },
    {
        "key": "status",
        "title": "Daily status",
        "intro": "The language the AI writes your daily status in, whatever "
                 "language your own notes use.",
        "required": [],
        "fields": [
            {"path": ["status_language"], "label": "Status language",
             "placeholder": "English",
             "hint": "e.g. English, Ukrainian, Polish."},
        ],
    },
    {
        "key": "invoice",
        "title": "Invoicing",
        "intro": "Fills your .docx template and produces a PDF in one click "
                 "at the end of the month.",
        "required": [("invoice", "hourly_rate"), ("invoice", "supplier_full_name")],
        "fields": [
            {"path": ["invoice", "hourly_rate"], "label": "Hourly rate",
             "kind": "float", "optional": False},
            {"path": ["invoice", "supplier_full_name"], "label": "Your full name",
             "optional": False,
             "hint": "As it should appear inside the document."},
            {"path": ["invoice", "supplier_name"], "label": "Your name for the file name",
             "hint": "No spaces."},
            {"path": ["invoice", "client_name"], "label": "Client name",
             "hint": "Used in the invoice file name."},
            {"path": ["invoice", "client_code"], "label": "Client code",
             "hint": "Short code that starts the invoice number."},
        ],
    },
    {
        "key": "requisites",
        "title": "Payment details",
        "intro": "Substituted into the {{...}} tokens of your invoice template. "
                 "Anything left empty stays as a visible token. Faster: import "
                 "them from an invoice you have already sent.",
        "required": [],
        "fields": [
            {"path": ["invoice", "requisites", "tax_number"], "label": "Tax number"},
            {"path": ["invoice", "requisites", "iban"], "label": "IBAN"},
            {"path": ["invoice", "requisites", "swift_code"], "label": "SWIFT / BIC"},
            {"path": ["invoice", "requisites", "address"], "label": "Your address"},
            {"path": ["invoice", "requisites", "acquirer_name"], "label": "Client legal name"},
            {"path": ["invoice", "requisites", "acquirer_address"], "label": "Client address"},
            {"path": ["invoice", "requisites", "vat_number"], "label": "Client VAT number"},
            {"path": ["invoice", "requisites", "nip"], "label": "Client NIP"},
            {"path": ["invoice", "requisites", "krs"], "label": "Client KRS"},
        ],
    },
]

STATIC_SECTIONS = {s["key"]: s for s in SETTINGS_SECTIONS}

REQUISITES_KEY = "requisites"
DOCX_INTRO = (
    "Read from your own invoice template, so the list changes when the "
    "template does. Anything left empty simply prints empty."
)


def _requisites_from(fields):
    return {
        "key": REQUISITES_KEY,
        "title": "Payment details",
        "intro": DOCX_INTRO,
        "required": [],
        "fields": fields,
    }


def _label_for_token(token: str) -> str:
    words = token.replace("_", " ").split()
    return " ".join(word.capitalize() for word in words)


def docx_requisites_section(config):
    path = invoice._resolve_template(
        (config.get("invoice") or {}).get("template_path", "")
    )
    return _requisites_from([
        {"path": ["invoice", "requisites", token.lower()],
         "label": _label_for_token(token.lower()),
         "hint": "{{" + token + "}}"}
        for token in invoice.party_tokens(path)
    ])


def section_for(key, config):
    if key != REQUISITES_KEY:
        return STATIC_SECTIONS[key]

    raw = (config.get("invoice") or {}).get("template_path", "")
    try:
        if raw and invoice._resolve_template(raw).exists():
            return docx_requisites_section(config)
    except Exception:
        pass
    return STATIC_SECTIONS[key]


def all_sections(config):
    return [section_for(s["key"], config) for s in SETTINGS_SECTIONS]

PROJECT_FIELDS = [
    {"key": "name", "label": "Project name", "optional": False,
     "hint": "Only shown inside the app."},
    {"key": "peopleforce_id", "label": "PeopleForce project id", "kind": "int",
     "hint": "Leave empty if this project is never pushed."},
    {"key": "rate", "label": "Hourly rate", "kind": "float",
     "hint": "Leave empty to use the default rate from Settings."},
]

SECTION_MARKS = {"ok": "✅", "partial": "⚠️", "empty": "—"}


def _read(config, path):
    node = config
    for key in path:
        if not isinstance(node, dict):
            return ""
        node = node.get(key)
    return "" if node is None else node


def _coerce(raw, kind):
    if kind == "int":
        return int(raw)
    if kind == "float":
        return float(raw.replace(",", "."))
    return raw


def _optional(raw, kind):
    return _coerce(raw, kind) if raw else None


def _notify_saved(title, count):
    notify(
        f"{title}: {count} field(s) saved to ~/.work_tracker/profile.json",
    )


def _notify_first_run():
    return notify(
        "Click ⏱ in the menu bar → 🏷 Active project → + Add a project.",
        title="Pick a project to start tracking",
    )


class SetupMixin:

    def _present(self, spec):
        if not hasattr(self, "_live_controllers"):
            self._live_controllers = set()
        spec = dict(spec, on_close=self._live_controllers.discard)
        controller = FormController.alloc().initWithSpec_(spec)
        self._live_controllers.add(controller)
        controller.show()
        return controller

    @staticmethod
    def _section_state(config, section):
        required = section["required"]
        if not required:
            filled = any(_read(config, s["path"]) for s in section["fields"])
            return "ok" if filled else "empty"
        if all(_read(config, path) for path in required):
            return "ok"
        if any(_read(config, s["path"]) for s in section["fields"]):
            return "partial"
        return "empty"

    def section_is_ready(self, key):
        config = load_config()
        return self._section_state(config, section_for(key, config)) == "ok"

    def open_section(self, key, on_done=None):
        config = load_config()
        section = section_for(key, config)

        fields = [
            dict(spec, key=".".join(spec["path"]), value=_read(config, spec["path"]))
            for spec in section["fields"]
        ]

        def save(values):
            written, rejected = 0, []
            for spec in section["fields"]:
                path = spec["path"]
                raw = values.get(".".join(path), "")
                if raw == str(_read(config, path) or ""):
                    continue
                try:
                    save_profile_value(
                        path, _coerce(raw, spec.get("kind", "text")) if raw else ""
                    )
                    written += 1
                except ProfileWriteError as e:
                    rejected.append(f"{spec['label']}: {e}")

            if rejected:
                return rejected[0]

            load_config(force=True)
            self.rebuild_settings_menu()
            self.rebuild_peopleforce_menu()
            if written:
                _notify_saved(section["title"], written)
            if on_done:
                AppHelper.callAfter(on_done)
            return None

        spec = {
            "title": section["title"],
            "intro": section["intro"],
            "fields": fields,
            "on_save": save,
        }
        if key == "requisites":
            spec["extra_label"] = "Import from an invoice…"
            spec["on_extra"] = self.import_invoice_details

        self._present(spec)

    def require_section(self, key, then):
        if self.section_is_ready(key):
            then()
            return
        self.open_section(key, on_done=then)

    WORD_INTRO = (
        "Chronify has opened the default invoice template in Word (or revealed it in Finder).\n\n"
        "1. Do NOT create new {{TOKENS}}. Simply type your own payment details, bank accounts, or static information directly into the document.\n"
        "2. Keep existing placeholders like {{SUPPLIER_FULL_NAME}} or {{TOTAL_AMOUNT}} so automated values can still be inserted.\n"
        "3. Save as .docx. Do not use Pages or TextEdit: they flatten the invoice table into plain text.\n"
        "4. Save your file, return here, and click 'Select saved file' to select your updated template."
    )

    NO_WORD_WARNING = (
        "Microsoft Word was not found, so macOS will open the template in "
        "whatever app is set for .docx files.\n\n"
        "Pages and TextEdit both turn the invoice table into plain text when "
        "they save, and the finished invoice then has no table at all. "
        "LibreOffice keeps it intact.\n\n"
        "Open anyway?"
    )

    TABLE_LOST = (
        "{{ROW_PROJECT}} is still in the document, but it is no longer inside a "
        "table row: the app that saved this file replaced the invoice table with "
        "plain text. Pages and TextEdit both do this.\n\n"
        "Edit the template in Word or LibreOffice instead, then connect it again."
    )

    def _present_editor(self, spec):
        if not hasattr(self, "_live_controllers"):
            self._live_controllers = set()
        spec = dict(spec, on_close=self._live_controllers.discard)
        controller = EditorController.alloc().initWithSpec_(spec)
        self._live_controllers.add(controller)
        controller.show()
        return controller

    @staticmethod
    def _open_in_word(path):
        for candidate in (Path("/Applications/Microsoft Word.app"),
                          Path.home() / "Applications" / "Microsoft Word.app"):
            if candidate.exists():
                subprocess.run(["open", "-a", str(candidate), str(path)])
                return True
        return False

    def edit_word_template(self, _sender=None):
        target = BASE_DIR / "my_invoice_template.docx"
        bundled = invoice._resolve_template("Invoice_Template_TOKENS.docx")

        if not target.exists() and bundled.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(bundled, target)

        path_to_open = target if target.exists() else bundled

        if not self._open_in_word(path_to_open):
            if not rumps.alert(
                title="Microsoft Word not found",
                message=self.NO_WORD_WARNING,
                ok="Open anyway", cancel="Cancel",
            ):
                return
            opened = subprocess.run(
                ["open", str(path_to_open)], capture_output=True, text=True
            )
            if opened.returncode != 0:
                subprocess.run(["open", "-R", str(path_to_open)])

        AppHelper.callAfter(self._wait_for_word, target)

    def _wait_for_word(self, default_target):
        response = rumps.alert(
            title="Word Invoice Template Setup",
            message=self.WORD_INTRO,
            ok="Select saved file", cancel="Later",
        )
        if not response:
            return

        picked = choose_docx_file("Choose your saved invoice template (.docx)")
        if not picked:
            return

        picked_path = Path(picked)

        try:
            tokens = invoice.read_template_tokens(picked_path)
        except Exception as e:
            rumps.alert(title="Could not read the document", message=str(e))
            return

        if not tokens:
            rumps.alert(
                title="No tokens found",
                message="Every {{FIELD}} placeholder has been removed, so nothing "
                        "will be auto-filled. Re-add the required fields and try again.",
            )
            return

        if invoice.row_template_state(picked_path) == "flattened":
            rumps.alert(title="The invoice table is gone", message=self.TABLE_LOST)
            return

        dest_path = BASE_DIR / "my_invoice_template.docx"
        try:
            shutil.copyfile(picked_path, dest_path)
        except Exception as e:
            rumps.alert(title="Could not save template", message=str(e))
            return

        save_profile_value(["invoice", "template_path"], str(dest_path.resolve()))
        load_config(force=True)
        self.rebuild_settings_menu()

        party = invoice.party_tokens(dest_path)
        notify(
            f"{len(party)} field(s) to fill in under Payment details.",
            title="Word template successfully connected!",
        )

    def permissions_state(self):
        return "ok" if tracker.has_window_title_access() else "empty"

    def check_permissions(self, _sender=None):
        if tracker.has_window_title_access():
            rumps.alert(
                title="Screen Recording is on",
                message="Window titles are readable, so activity is grouped "
                        "into tasks by your rules.",
            )
            return

        if rumps.alert(
            title="Screen Recording is off",
            message="Without it macOS hides every window title, so the day is "
                    "logged as bare app names with no task breakdown.\n\n"
                    "macOS ties this permission to the exact binary, so a "
                    "'brew upgrade' can drop it and nothing warns you.\n\n"
                    "Open the system prompt now?",
            ok="Ask macOS",
            cancel="Later",
        ):
            tracker.request_window_title_access()
            AppHelper.callAfter(self._permission_followup)

    def _permission_followup(self):
        rumps.alert(
            title="Finish in System Settings",
            message="If the switch is already listed, turn it on under\n"
                    "Privacy & Security → Screen Recording, then quit and "
                    "start Chronify again — macOS only re-reads it at launch.",
        )
        self.rebuild_settings_menu()

    def warn_if_titles_are_hidden(self):
        if tracker.has_window_title_access():
            return
        if not notify(
            "Window titles are hidden, so there is no task breakdown. "
            "⚙️ Settings → Screen Recording.",
            title="Screen Recording is off",
        ):
            AppHelper.callAfter(self.check_permissions)

    def rebuild_settings_menu(self, _sender=None):
        self._clear_menu(self.settings_menu)
        config = load_config()

        for section in all_sections(config):
            state = self._section_state(config, section)
            self.settings_menu.add(rumps.MenuItem(
                f"{SECTION_MARKS[state]}  {section['title']}",
                callback=self._make_section_callback(section["key"]),
            ))

        self._add_separator(self.settings_menu)
        self.settings_menu.add(rumps.MenuItem(
            "📝 Edit invoice template in Word…", callback=self.edit_word_template
        ))

        self.settings_menu.add(rumps.MenuItem(
            f"{SECTION_MARKS[self.permissions_state()]}  Screen Recording",
            callback=self.check_permissions,
        ))
        self.settings_menu.add(
            rumps.MenuItem("🏷 Add a project…", callback=self.add_project)
        )

    def _make_section_callback(self, key):
        def _callback(_sender):
            self.open_section(key)

        return _callback

    def check_first_run(self, _sender=None):
        self._first_run_timer.stop()
        self.warn_if_titles_are_hidden()
        if projects.is_configured():
            return
        if not _notify_first_run():
            rumps.alert(
                title="Welcome to Chronify",
                message="Nothing is tracked until you name a project.\n\n"
                        "Click ⏱ in the menu bar → 🏷 Active project → "
                        "+ Add a project.",
            )
        self.refresh_title()

    def add_project(self, _sender=None):
        first = not projects.is_configured()

        def save(values):
            entry = projects.add_project(
                values["name"],
                _optional(values["peopleforce_id"], "int"),
                _optional(values["rate"], "float"),
            )
            if entry is None:
                return "A project needs a name."

            self.rebuild_project_menu()
            self.refresh_title()
            if first:
                self._adopt_unassigned()

            AppHelper.callAfter(self._after_project_added, entry)
            return None

        self._present({
            "title": "New project",
            "intro": "Every tracked hour belongs to a project. Only the name is "
                     "required — the rest can wait." if first else "",
            "fields": [dict(f, value="") for f in PROJECT_FIELDS],
            "on_save": save,
        })

    def _after_project_added(self, entry):
        if rumps.alert(
            title=f"{entry['name']} is ready",
            message="Tracking starts now. Everything else — PeopleForce, "
                    "invoicing — is asked for the first time you use it.\n\n"
                    "Do you work on another project as well?",
            ok="Add another",
            cancel="Done",
        ):
            self.add_project()
        elif len(projects.all_projects()) > 1:
            self._ask_scoping_mode()

    def edit_project(self, project_id):
        project = projects.get_project(project_id)
        if project is None:
            self.rebuild_project_menu()
            return

        current = {
            "name": project["name"],
            "peopleforce_id": project.get("peopleforce_id") or "",
            "rate": project.get("rate") or "",
        }

        def save(values):
            projects.update_project(
                project_id,
                values["name"],
                _optional(values["peopleforce_id"], "int"),
                _optional(values["rate"], "float"),
            )
            self.rebuild_project_menu()
            self.refresh_title()
            return None

        self._present({
            "title": f"Edit {project['name']}",
            "intro": "",
            "fields": [dict(f, value=current[f["key"]]) for f in PROJECT_FIELDS],
            "on_save": save,
            "extra_label": "Delete this project…",
            "on_extra": lambda: self._delete_project(project),
        })