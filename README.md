# Chronify Work Tracker

**Your workday writes itself down.**

At six in the evening someone asks what you got done today. And you honestly can't remember. There was a bug with a button, then something about authentication, then an hour in chat — and all of it has blurred into one grey smudge. At the end of the month you also have to recall how many hours you actually worked.

Chronify lives in the menu bar and quietly keeps that log for you. There is nothing to switch on or off — it simply runs while you work.

---

## What it does

### ⏱ Counts your hours so you don't have to

It watches which window is active and breaks the day into tasks on its own — not "Chrome, 4 hours", but `Ticket ABC-123 — 52m`, `Code Review — 24m`. You write the grouping rules once, to match how you actually work.

Went to lunch? It notices the idle stretch and asks when you get back whether to count that time. Reading documentation without touching the mouse — say yes, and the hour isn't lost. Watching a show — say no, and it never reaches your report.

Real calls are the exception: Zoom, Meet and Teams count as work even when you haven't touched the keyboard. Slack and Discord count only while the window title says it's a huddle or a call, so a messenger left open won't quietly log you a whole evening.

And when the laptop is needed for personal things, one **Pause** click and the tracker sees nothing.

### 🏷 Keeps projects apart

Every hour belongs to a project. Switch the active one straight from the menu bar and the tracker follows you — the current project is visible right in the title, so you always know where your time is going.

Made a mistake? Move a whole day, or a date range, from one project to another in two clicks. Or open a day and fix the recorded segments by hand: delete what doesn't belong, move what landed in the wrong place.

Tasks, blockers and notes can be either shared across all projects or separate for each one — your choice, and you can change it at any time.

### ✨ Writes your daily status for you

Through the day you jot notes down in one motion: "fixed the button in safari", "approved the pull request". Roughly, however they come out.

In the evening you press one button and a local AI model turns that into a proper status, together with your tasks, plans for tomorrow, blockers and infrastructure status. The text can be edited right in the window and copied to the clipboard.

The archive fills itself in the background: even on days when you never pressed the button, a status is written and saved — so the history is there when someone asks about last Tuesday.

**Everything runs on your machine.** No OpenAI, no cloud. Your work notes never leave the laptop.

### 📋 Remembers what you forget

A day plan with checkboxes — and one item can be pinned right in the menu bar so it stares at you all day and doesn't let you forget. Unfinished items move themselves to the next day.

Blockers, notes to self, alarms along the lines of "13:00 — go get lunch". All in one place, without a separate app and without yet another account.

### 📅 Shows the month at a glance

A calendar with a heat map: you can see immediately where the heavy days were and where you barely worked. Each day shows the split across projects, and what you logged that day is one click away. Open any of the last 30 days and look at what you were really doing — even if you forgot long ago.

If PeopleForce is connected, every day also gets a sync indicator: hours match, hours differ, or the day hasn't been pushed yet.

### 📤 Fills in timesheets in one click

Hours and status text go to PeopleForce for a day, for yesterday, or for the whole month at once. Turn on auto-push and it happens by itself after midnight, including catching up on up to a week if the Mac was switched off.

You choose what exactly gets sent: the real intervals the tracker recorded (09:00–10:37, 10:38–12:57…), or one summary entry per project. Days that already have an entry are never overwritten without your confirmation. Nothing disappears.

### 🧾 Produces an invoice in a minute

On the last working day of the month it reminds you and proposes a split of hours across projects. You confirm — and a finished `.docx` with your payment details, signature and total is already open, with a PDF next to it.

Already have an old invoice? Point the app at it and it will read your IBAN, SWIFT, tax number and addresses straight out of the document, so you don't have to type them in.

---

## Who it's for

Developers, designers, anyone on **macOS** who writes a status every day and counts hours — especially on contract or freelance.

Setup is one panel: name a project and tracking starts. PeopleForce credentials and invoice details are asked for the first time you actually use those features, never up front.

The PeopleForce integration and invoice generation are optional. Without them this is still a full time tracker with daily statuses.

---

## Installation

macOS required. The easiest way is Homebrew:

```bash
brew tap zepuff/chronify
brew trust zepuff/chronify
brew install chronify
```

The `brew trust` step is Homebrew asking you to confirm that you're willing to
run a formula from outside its official repository. Without it the install stops
with an "untrusted tap" error.

The first install takes a few minutes: this tap has no pre-built bottles, so
Pillow and the PyObjC frameworks are compiled from source on your machine.

Run it:

```bash
chronify
```

To start it automatically at login:

```bash
brew services start chronify
```

Disable autostart: `brew services stop chronify`

Upgrade: `brew update && brew upgrade chronify`.

Uninstall:

```bash
brew services stop chronify
brew uninstall chronify
brew untap zepuff/chronify
```

Your data in `~/.work_tracker/` survives an uninstall — delete that folder by
hand if you want it gone too.

### Local AI (optional)

Statuses are written by a local model. Without it the app still works, but the status stays a plain list of tasks:

```bash
brew install ollama
brew services start ollama
ollama pull qwen2.5:3b
```

Then set `ai_backend: "ollama"` in `~/.work_tracker/config.yaml`. On macOS 26+ with Apple Silicon there is an alternative, `apfel` (`brew install apfel && brew services start apfel`, then `ai_backend: "apfel"`).

PDF export for invoices: `brew install --cask libreoffice` (the `.docx` itself is created without it).

### From source

```bash
git clone https://github.com/zepuff/Chronify.git
cd Chronify
python3 -m venv venv && source venv/bin/activate
pip install -e .
chronify
```

### macOS permissions

On first launch the system will ask for permissions. Both are needed:

- **Screen Recording** — without it window titles are invisible and all activity is logged as a bare app name, with no breakdown into tasks. Granted in *System Settings → Privacy & Security → Screen Recording*. The app has to be restarted after the change.

  macOS attaches this permission to the exact executable, and `brew upgrade` installs a new one, so an upgrade can quietly revoke it. The app checks at launch and warns you; **⚙️ Settings → Screen Recording** shows the current state at any time and can reopen the system prompt.
- **Notifications** — otherwise timed reminders never fire.

---

## First launch

Nothing opens by itself. The menu bar shows ⏱ ⚠️ no project until you add one.

**Projects.** 🏷 Active project → + Add a project. A name is required; the PeopleForce id and the hourly rate can stay empty. At least one project is needed, otherwise there is nowhere to log hours and tracking stays paused.

**⚙️ Settings.** Four sections, each opened on its own and marked ✅ ⚠️ — depending on how complete it is. A section you never use can stay empty:

| Section | What it covers |
|---|---|
| PeopleForce | Company API key (PeopleForce only issues company-wide keys), employee id, hour the workday starts |
| Daily status | The language the AI writes in — your own notes can be in any language |
| Invoicing | Rate, your name for the document and for the file name, client name and code |
| Payment details | Tax number, IBAN, SWIFT, addresses and the client's registration numbers |

Everything you enter is stored in `~/.work_tracker/profile.json`, **outside the project folder**, so your API key and payment details never end up in git. Values from there override `config.yaml`.

Every section can be reopened at any time from ⚙️ Settings.

---

## Configuration

Personal data goes through ⚙️ Settings. `~/.work_tracker/config.yaml` is for fine-tuning the tracking itself — the file is created on first launch from a bundled default, is thoroughly commented, and is not overwritten by upgrades. The main keys:

| Key | What it does |
|---|---|
| `poll_interval` | how often to check the active window, in seconds |
| `min_segment_seconds` | shorter segments are not stored |
| `idle_threshold_seconds` | how many seconds without input count as idle |
| `treat_media_as_active` | count calls as active time even without input |
| `call_apps` / `call_apps_conditional` / `call_title_markers` | what counts as a call |
| `alert_sound` | any name from `/System/Library/Sounds`, empty means silence |
| `ai_backend` | `ollama`, `apfel` or `none` |
| `status_language` | language of the generated status: `English`, `Ukrainian`, `Polish`… |
| `rules` | how windows are grouped into tasks |
| `ignore_apps` | never recorded |

Rules are read top to bottom, first match wins. The regular expression is applied to the string `app name — window title`. Capture groups can be substituted into the task name:

```yaml
rules:
  - pattern: "(?i)(TASK-\\d+|[A-Z]+-\\d+)"
    task: "Ticket {1}"
```

If no rule matches, the task is simply named after the app.

No restart is needed after editing rules — use the **🔄 Reload rules** menu item.

### Invoice template

`Invoice_Template_TOKENS.docx` ships with the app — an ordinary Word document where every value is marked with a `{{TOKEN}}`. If you have your own template, put it in `~/.work_tracker/` and set the file name (or a full path) in `invoice.template_path`.

The bundled template is one example layout: the currency is fixed to USD, the payment terms say full post-payment, and it carries a few jurisdiction-specific registration fields. If that doesn't match your situation, edit the document directly — only the `{{TOKENS}}` are substituted, everything else is plain text you can change.

Chronify ships with a working invoice template, so there is nothing to set up before the first invoice — fill in **⚙️ Settings → Payment details** and create one.

**⚙️ Settings → 📝 Edit the invoice template…** copies the bundled template to `~/.work_tracker/my_invoice_template.docx` and opens it in Microsoft Word. Change only the parts that don't match your own paperwork — a label your country words differently, a registration number you have and the form does not. Anything in `{{DOUBLE BRACES}}` is filled in when an invoice is created; add one of your own the same way, for example `{{REGON}}`, and it appears in Payment details too.

> **Edit the template in Word or LibreOffice — not in Pages or TextEdit.** Neither of those supports the nested table the invoice rows live in. They save the file with that table replaced by plain text, and every invoice made from it then comes out without a table. Chronify checks for this when you connect a template and refuses one whose table is gone.

The app computes these itself and never asks for them: `{{INVOICE_NUMBER}}` `{{INVOICE_DATE}}` `{{PERIOD_START}}` `{{PERIOD_END}}` `{{MONTH_NAME}}` `{{YEAR}}` `{{TOTAL_HOURS}}` `{{RATE}}` `{{TOTAL_AMOUNT}}` `{{CURRENCY}}` `{{SUPPLIER_FULL_NAME}}`, plus the `{{ROW_*}}` fields of the project row.

The PDF beside the `.docx` is produced by LibreOffice: `brew install --cask libreoffice`. Without it the `.docx` is still created, and the PDF can be added later through **🧾 Invoice → Refresh PDF**.
**🧾 Invoice → 📥 Import details from an existing invoice…** reads values — IBAN, tax number, addresses — out of an invoice you have already sent, so you don't retype them. The same import is one click away inside **⚙️ Settings → Payment details**.

The table row containing `{{ROW_PROJECT}}` is a row template: it is duplicated once per project in the invoice. Empty fields deliberately stay as visible `{{TOKENS}}`, so you can see at once what's missing.

If the template has more than one image, set `invoice.signature_image_name` so the app knows which one to replace with your signature — or simply name the picture "signature" in Word (right-click the image → Edit Alt Text).

---

## Where the data lives

Everything is in `~/.work_tracker/`:

| File | Contents |
|---|---|
| `config.yaml` | tracking settings (rules, intervals, AI backend) |
| `tracker.db` | SQLite with activity segments and the status archive |
| `profile.json` | everything from ⚙️ Settings: API key, payment details, rate |
| `projects.json` | projects |
| `tasks.json` | completed tasks |
| `blockers.json` | blockers |
| `reminders.json` | notes to self |
| `planner.json` | the day plan |
| `alerts.json` | timed reminders |
| `settings.json` | active project, infrastructure status, pinned item, auto-push flag |

The generated calendar (`calendar_2026-08.html`) and the history export (`history_export.md`) live there too. Open the folder from the menu: **📁 Open saved data folder**.

A backup is a copy of that one folder. Invoices are stored separately, in the folder from `invoice.output_dir` (by default `~/Documents/Invoices`).

---

## Code structure

| File | Responsibility |
|---|---|
| `main.py` | the menu bar, all its items, timers, PeopleForce sync logic |
| `tracker.py` | the background loop polling the active window |
| `task_mapper.py` | the "window → task" rules |
| `db.py` | SQLite: time segments, status archive, HTML calendar |
| `store.py` | the base layer for working with JSON files |
| `notes.py` | tasks, blockers, reminders, the plan |
| `projects.py` | projects and the active one |
| `alerts.py` | timed reminders |
| `settings.py` | small persisted settings |
| `summarizer.py` | assembling the status text, requests to the AI |
| `main_setup.py` | the Settings panels and the first-run wizard |
| `forms.py` | the field definitions each Settings panel is built from |
| `invoice.py` | filling the template, conversion to PDF |
| `docx_layout.py` | measuring an existing invoice so its details can be read |
| `invoice_import.py` | reading payment details out of an existing invoice |
| `peopleforce.py` | the PeopleForce API |
| `ui_windows.py` | native input windows |
| `config.py` | reading `config.yaml` and `profile.json`, shared constants |

The modules live in the `chronify/` package; the entry point is the `chronify` command (`chronify.main:main`).

---

## Development

```bash
git clone https://github.com/zepuff/Chronify.git
cd Chronify
python3 -m venv venv && source venv/bin/activate
pip install -e .
pip install pytest
python3 -m pytest tests -q
```

The tests run anywhere — they need neither macOS nor a display. `test_invoice.py` fills real `.docx` files and checks the result is still a valid document; `test_setup_wiring.py` reads the Settings code as a syntax tree and catches the mistakes PyObjC only reports at runtime: a selector with the wrong number of arguments, a `self.` attribute nothing defines, a mixin that lost its place in the MRO.

Two scripts help with the parts tests can't reach:

| Script | What it does |
|---|---|
| `scripts/check_template.py` | reports what an invoice template contains and fills a sample invoice from it |
| `scripts/first_run_sandbox.sh` | runs the app against a throwaway `HOME`, so a first run can be tried without touching your data |

---

## If something doesn't work

**Only app names are recorded, no tasks.**
Screen Recording permission hasn't been granted, or an upgrade dropped it. Check **⚙️ Settings → Screen Recording**; a — instead of ✅ means macOS is hiding window titles.

**Nothing is recorded at all.**
Look at the menu bar icon: `⏸` means tracking is paused, `⚠️ no project` means there is no project to log to.

**The status comes out as a plain list, with no rewriting.**
The AI backend is unavailable. Check that Ollama is running (`ollama list`) and that `ollama_model` in the config matches the model name exactly, including a tag like `:3b`. Ollama and apfel use the same port, 11434 — run only one of them (`lsof -i :11434` shows who took it).

**The invoice PDF isn't created.**
LibreOffice is missing: `brew install --cask libreoffice`. The `.docx` is created either way, and the PDF can be generated later via **🧾 Invoice → Refresh PDF**.

**The invoice still shows `{{TOKENS}}`.**
The corresponding field is empty. Fill it in through **⚙️ Settings** and create the invoice again — after every run the app lists exactly which values are missing.

**The invoice has no table: the rows come out as plain text.**
The template lost it. Pages and TextEdit both drop the nested table the rows live in when they save a `.docx`. Delete `~/.work_tracker/my_invoice_template.docx` and remove `template_path` from `~/.work_tracker/profile.json` to go back to the bundled template, then edit it in Word or LibreOffice instead. `python3 scripts/check_template.py <file>` reports what a template still contains.

**PeopleForce returns an error.**
Usually a missing project id, or a key taken from the wrong place. You need a Company API key from *Settings → API keys*. Project ids are set per project: **🏷 Active project → ✏️ Edit a project**.

**PeopleForce says the hours don't fit in the day.**
The total, counted from your workday start hour, runs past midnight. Lower that hour in ⚙️ Settings → PeopleForce, or push part of the time manually.

**The app didn't start after a reboot.**
Check `brew services list` — Chronify should be `started`. Logs: `cat $(brew --prefix)/var/log/chronify.log`

---

## Limitations

- macOS only — tracking depends on Quartz and AppKit.
- Status quality depends on the local model. `qwen2.5:3b` is fast, but small and occasionally muddles details. If the text looks odd, try a bigger model. apfel has a 4096-token context, so very long days get truncated.
- Deleting a project doesn't move its hours anywhere — they stay in your statistics as time without a project and are never pushed.
- Copy `~/.work_tracker/` before upgrading. Nothing has ever eaten it, but it is the one folder that matters.

---

## License

Copyright (C) 2026 Zepuff.

Chronify is free software, released under the GNU General Public License v3 or later. You may use, study, modify and redistribute it — but any distributed derivative work has to stay under the same license and ship its source. The full terms are in [LICENSE](LICENSE); there is no warranty of any kind.