# Chronify Work Tracker

**Your workday writes itself down.**

It's six in the evening and someone asks what you got done today. You honestly can't remember. There was the bug with the button, then something about auth, then an hour in chat, and all of it has blurred into one grey smear. And at the end of the month you're supposed to recall how many hours you put in, too.

Chronify sits in the menu bar and keeps that log for you. Nothing to start or stop. It just runs while you work.

---

## What it does

### ⏱ Counts hours so you don't have to

It watches which window is in front and splits your day into tasks by itself. Not "Chrome, 4 hours" but `Ticket ABC-123 - 52m`, `Code Review - 24m`. You write the grouping rules once, to match how you actually work.

Went for lunch? It notices the idle stretch and asks when you're back whether that time counts. Were you reading docs without touching the mouse, say yes and the hour isn't lost. Were you watching a show, say no and it never shows up in your report.

Real calls are the exception. Zoom, Meet and Teams count as work even if you didn't touch the keyboard. Slack only counts while the window title says it's a call, a huddle or a meeting, so a messenger left open doesn't quietly log your whole evening. Any other app goes into the same list with one line of config.

And when the laptop is needed for personal things, there's **Pause**. The tracker stops seeing anything.

### 🏷 Keeps projects apart

Every hour belongs to a project. Switch the active one from the menu bar and the tracker follows you. The current project shows up in the title, so you always know where your time is going.

Got it wrong? Move a whole day, or a range of dates, from one project to another in two clicks. Or open the day and fix the recorded stretches by hand: delete what shouldn't be there, move what landed in the wrong place.

Tasks, blockers and notes can be shared across all projects or kept separately for each one. Your call, and you can change your mind later.

### ✨ Writes your daily status

During the day you jot notes down in one motion: "fixed the button in safari", "approved the payments PR". Sloppy is fine.

In the evening you press one button and a local AI model turns that into a normal status:

```
What was done today:
• Fixed the button rendering in Safari
• Reviewed and approved the payments pull request

What is planned next:
• Finish the timesheet export

Blockers: None

Infrastructure status: 🟢 All systems stable

Reminders:
• Ask about the staging database
```

Only "What was done today" goes through the AI, and under tight rules: invent nothing, don't mention durations or hours, don't name apps, don't add praise like "successfully". The rest is assembled as is. The plan section takes your unfinished items, blockers take whatever was still open on that day. You can edit the text in the window and copy it.

The archive fills itself in the background. Even on days when you never pressed the button, a status gets written and saved, so the history is there when someone asks about last Tuesday.

**Everything runs on your machine.** No OpenAI, no cloud. Your work notes never leave the laptop.

### 📋 Remembers what you forget

A plan for the day with checkboxes, and one item can be pinned right into the menu bar so it stares at you all day. Unfinished items move themselves to tomorrow.

Blockers, notes to self, alarms like "13:00, go have lunch". All in one place, without a separate app and without another account.

### 📅 Shows the month at a glance

A calendar with a heat map. You can see straight away which days were heavy and which ones you barely worked. Each day carries a breakdown by project, and what you logged that day is one click away. Open any of the last 30 days and see what you were actually doing, even if you've long forgotten.

If PeopleForce is connected, every day also gets a sync marker: hours match, hours differ, or the day hasn't been pushed yet.

### 📤 Fills in timesheets in one click

Hours and the status text go to PeopleForce for a day, for yesterday, or for the whole month at once. Turn auto-push on and it happens by itself after midnight, catching up to a week back if the Mac was off.

You choose what gets sent: the real stretches the tracker recorded (09:00–10:37, 10:38–12:57 and so on), or one lump entry per project. Days that already have an entry are never overwritten without your say-so. Nothing disappears.

### 🧾 Makes an invoice in a minute

On the last working day of the month it reminds you and offers a split of hours across projects. You confirm, and a finished `.docx` with your details, signature and total is already open, with a PDF next to it. The app tells you which folder they landed in and offers to show them in Finder; you pick that folder yourself in ⚙️ Settings → Invoicing.

Already have an old invoice? Point the app at it and it reads your IBAN, SWIFT, tax number and addresses straight out of the document, so you don't have to type them in.

---

## Who it's for

Developers, designers, anyone on **macOS** who writes a status every day and counts hours, especially on contract or freelance.

To get going you only need to name one project. The rest, PeopleForce and the invoice details, is asked for the first time you use it, one field per window. All the setup lives inside the app.

The PeopleForce integration and the invoices are optional. Without them this is still a full time tracker with daily statuses.

---

## Installing

You need macOS and Homebrew. Homebrew brings Python and every library along with it.

```bash
brew tap zepuff/chronify
brew trust zepuff/chronify
brew install chronify
```

`brew trust` confirms you're fine installing a formula from outside the official Homebrew repo. Without it the install stops with an error about an untrusted tap.

The first install takes about two minutes, since Pillow, lxml and the PyObjC frameworks are built from source. Updates after that are much quicker.

To start it:

```bash
chronify --background
```

If all went well, a ⏱ icon shows up in the top right of your screen. Plain `chronify` runs it in the foreground instead, where Ctrl+C quits it, which is handy while you are trying things out.

To have it start when you log in:

```bash
brew services start chronify
```

Turning that off is `brew services stop chronify`.

### Updating and removing

```bash
brew upgrade chronify
```

Your data in `~/.work_tracker/` is left alone. One thing to know: macOS ties the Screen Recording permission to the exact binary, so after an upgrade you'll have to grant it again.

```bash
brew uninstall chronify
```

That removes the app only. The `~/.work_tracker/` folder with your history, statuses and payment details stays where it is.

### AI for the statuses, optional

Without it the app works fine, the status is just a plain list of your notes.

You don't install anything by hand. Open **⚙️ Settings → Daily status**, pick who writes the status, and Chronify installs it for you through Homebrew, in the background, reporting each step.

- **Ollama** understands Ukrainian and other languages, so it can write the status in a different language from your notes. The app installs the formula, starts the service and pulls the `qwen2.5:3b` model, about 2 GB.
- **Apple Intelligence** (`apfel`) uses the model already in macOS, so nothing gets downloaded. Needs macOS 26 on Apple Silicon, and it can't write Ukrainian.

Both listen on port 11434, so only one of them can run at a time. If you'd rather do it by hand, this is exactly what the app would have run:

```bash
brew install ollama && brew services start ollama && ollama pull qwen2.5:3b
```

Converting invoices to PDF needs LibreOffice, also optional: `brew install --cask libreoffice`.

### Working on the code

If you're editing the code, install from a clone so your changes are picked up without reinstalling:

```bash
git clone https://github.com/zepuff/chronify.git
cd chronify
python3 -m venv venv && source venv/bin/activate
pip install -e .
pip install pytest
python3 -m pytest tests -q
```

The tests need neither macOS nor a display.

### macOS permissions

On the first run the system asks for permissions. You want both:

- **Screen Recording.** Without it window titles are invisible and everything gets logged under the bare app name, with no task breakdown. Grant it in *System Settings → Privacy & Security → Screen Recording*. The app has to be restarted afterwards. **⚙️ Settings → Screen Recording** shows the current state and can bring up the system prompt for you.
- **Notifications.** Otherwise the timed reminders won't fire.

---

## First run

Two seconds after launch the app checks the Screen Recording permission and whether you have any projects. If you don't, you get a **Pick a project to start tracking** notification. Clicking it opens the new project window.

**The project.** A name (required), the numeric PeopleForce id (leave it empty if you never push this one) and an hourly rate (empty falls back to the general rate). You need at least one project, because without it there's nowhere to write the hours and tracking sits paused. Once you save, the app asks whether there's another one, and if you end up with more than one it asks whether tasks and notes should be kept per project.

**⚙️ Settings.** Four sections. You don't have to fill them in up front: press 📤 Send hours to PeopleForce or 🧾 Invoice and the app opens whichever section is missing. Each one carries a state marker: ✅ filled in, ⚠️ partly filled in, a dash for empty.

Every field prints its own explanation underneath: where the value comes from, what format it wants, and what happens if you leave it empty. The API key field has a Show button so you can check what you pasted.

| Section | What's in it |
|---|---|
| PeopleForce | Company API key (PeopleForce only issues company-wide keys), employee id, the hour your working day starts |
| Daily status | Who writes the status (No AI / Ollama / Apple Intelligence) and in which language. Your own notes can be in any language |
| Invoicing | Rate, your name for the document and for the file name, client name and client code, and the folder the finished files go to |
| Payment details | Tax number, IBAN, SWIFT, addresses, VAT, NIP, KRS. The list of fields is read from your own invoice template, so a different template gives a different list |

Everything you type goes into `~/.work_tracker/profile.json`, next to the rest of your data rather than inside the app folder that every Homebrew upgrade rewrites. That's why your API key and payment details can never end up in git. Values from there always override `config.yaml`.

Any section can be reopened later from the menu.

---

## The menu

Everything lives under the ⏱ icon. Lines split the menu into blocks: recording and projects first, then your daily lists, then statistics, then documents and pushing, and settings at the bottom.

Every item carries a small grey line underneath saying what it does, so the menu can be read instead of this table. The table is here for the detail that does not fit in one line.

| Item | What it does |
|---|---|
| `⏸ Pause tracking` | Stops recording completely. The item turns into `▶️ Resume tracking` and the icon into `⏸` |
| `🏷 Project` | Switch the active project, add and edit projects, move days between them |
| `✨ Write today's status` | Builds today's status and opens it in a window for you to edit and copy |
| `✅ What I did today` | What you finished today. The main source for the status |
| `💭 Notes to self` | Context and ideas, no date attached |
| `🚧 What is blocking me` | What's in the way. Its own section in the status. Also holds `✅ Mark as resolved` and `📜 Resolved blockers…` |
| `📋 Plan for today` | The plan with checkboxes, plus `🧹 Clear completed` and `📌 Show in the menu bar` |
| `⏰ Remind me at a time` | Alarms: text, time, days of the week, one-off or not |
| `🚦 Infrastructure status` | 🟢 / 🟡 / 🔴 or your own wording, as one line in the status |
| `📊 Where today went` | Today's time broken down by task |
| `📆 Another day` | The last 30 days: `📄 Summary and hours` and `✏️ Edit tracked segments…` |
| `📅 Month calendar` | The month's HTML calendar in your browser: This month / Last month |
| `🧾 Invoice` | Create an invoice, `📥 Import details…`, `Refresh PDF…` |
| `📤 Send hours to PeopleForce` | Today / Yesterday / Days this month / `📦 Push every day this month`, plus two switches: `Push real time ranges` and `Auto-push at 00:00` |
| `📝 Status history` | `Open status history` for the markdown archive, and `🛑 Stop generating` |
| `⚙️ Settings` | The four settings sections, `📝 Edit invoice template in Word…`, `Screen Recording`, `🏷 Add a project…` |
| `🔄 Reload rules` | Rereads the grouping rules from `config.yaml` without a restart |
| `📁 Show my data folder` | Opens `~/.work_tracker/` in Finder |
| `Quit` | Stops the background loop and closes the current stretch of time |

The three lists, tasks, notes and blockers, all work the same way. The first item adds an entry, clicking an existing one opens it for editing, and saving an empty field deletes it after a confirmation.

Every window the app opens takes the usual keys: ⌘V pastes, ⌘A selects all, Return saves (⌘Return where the field is multi-line, so Return can still start a new line) and Esc closes. Windows stay open when you click away to another app.

---

## PeopleForce

You need three numbers and one key, all from your PeopleForce, all in different places.

| What | Where to find it |
|---|---|
| **Company API key** | One key for the whole company, issued by whoever administers PeopleForce. Ask them for it, then paste it into ⚙️ Settings → PeopleForce |
| **Employee id** | The number at the end of your own profile URL: `https://YOUR-COMPANY.peopleforce.io/people/12345` gives `12345` |
| **PeopleForce project id** | Open *Time → Attendance*, filter the page by the project and look at the URL: `…criteria%5Bproject_id%5D=42` gives `42`. This one doesn't go into Settings but into the project itself: 🏷 Project → ✏️ Edit a project |
| **Working day starts at** | Not from PeopleForce, you pick it yourself. It's the hour a lump timesheet entry is counted from |

The API address `https://app.peopleforce.io/api/public/v3` is the same for everyone and has nothing to do with your subdomain. The subdomain is only how you find the ids in the browser. For a separate server there's the `peopleforce.base_url` key.

A project without a PeopleForce id works like any other: hours are counted, they land in the calendar and the invoice, they're simply never pushed. The confirmation window lists them on their own line.

---

## Configuration

Personal data goes through **⚙️ Settings**. `config.yaml` is for the fine tuning of the tracking itself. It lives at `~/.work_tracker/config.yaml` and is seeded from a bundled sample on the first run. That's the copy to edit, because the one inside the installed package is overwritten by every `brew upgrade`. The file is thoroughly commented, and the main keys are below.

| Key | What it does |
|---|---|
| `poll_interval` | how often to check the active window, in seconds |
| `min_segment_seconds` | shorter stretches aren't stored |
| `idle_threshold_seconds` | how many seconds without input count as idle |
| `treat_media_as_active` | count calls as active time even without input |
| `call_apps` / `call_apps_conditional` / `call_title_markers` | what counts as a call |
| `alert_sound` | any name from `/System/Library/Sounds`, empty for silence |
| `ai_backend` | `ollama`, `apfel` or `none` (the default), easier to switch from ⚙️ Settings |
| `status_language` | the language of the generated status: `English`, `Ukrainian`, `Polish` and so on |
| `rules` | how windows are grouped into tasks |
| `ignore_apps` | never recorded |

Rules are read top to bottom and the first match wins. The regex is applied to the string `app name - window title`. Capture groups can be dropped into the task name:

```yaml
rules:
  - pattern: "(?i)(TASK-\\d+|[A-Z]+-\\d+)"
    task: "Ticket {1}"
```

If nothing matched, the task is simply named after the app.

You don't need to restart after editing rules. Use the **🔄 Reload rules** menu item.

### The invoice template

`Invoice_Template_TOKENS.docx` ships with the app. It's an ordinary Word document where every value is marked with a `{{TOKEN}}`. If you have your own template, point `invoice.template_path` at it.

The main tokens are `{{INVOICE_NUMBER}}`, `{{INVOICE_DATE}}`, `{{PERIOD_START}}`, `{{PERIOD_END}}`, `{{TOTAL_HOURS}}`, `{{RATE}}`, `{{TOTAL_AMOUNT}}`, `{{CURRENCY}}`, `{{SUPPLIER_FULL_NAME}}`, and everything from Payment details: `{{IBAN}}`, `{{TAX_NUMBER}}`, `{{SWIFT_CODE}}`, `{{ADDRESS}}`, `{{ACQUIRER_NAME}}`, `{{ACQUIRER_ADDRESS}}`, `{{VAT_NUMBER}}`, `{{NIP}}`, `{{KRS}}`. The invoice number builds itself from the client code, the month and the year, so `AMYNEBO` for August 2026 gives `AMYNEBO082026`.

The field list in the Payment details section is read from the template itself. A template for another country only needs its own tokens added, no code changes.

The table row holding `{{ROW_PROJECT}}` is a row template. It gets repeated once per project on the invoice, together with `{{ROW_DATES}}`, `{{ROW_HOURS}}`, `{{ROW_RATE}}` and `{{ROW_AMOUNT}}`. Empty fields stay visible as `{{TOKENS}}` on purpose, so you can see what's missing, and the app lists them for you after the invoice is created.

If the template has more than one image, set `invoice.signature_image_name` so the app knows which one to replace with your signature. Or just name the picture "signature" in Word, right click on it and choose Edit Alt Text.

> **The template can only be edited in Word or LibreOffice.** Pages and TextEdit don't support the nested table the project rows live in. On save they replace it with plain text, and every invoice from such a template comes out with no table at all. The app checks for this when you connect the file and refuses a broken template.

The convenient way in is **⚙️ Settings → 📝 Edit invoice template in Word…**. It copies the stock template to `~/.work_tracker/my_invoice_template.docx`, opens it in Word, and connects it in place of the stock one once you've saved.

---

## Where the data lives

All of it is in `~/.work_tracker/`:

| File | What's inside |
|---|---|
| `tracker.db` | SQLite with the activity stretches and the status archive |
| `config.yaml` | tracking settings, seeded from the bundled sample on the first run |
| `profile.json` | everything from ⚙️ Settings: API key, payment details, rate |
| `my_invoice_template.docx` | your invoice template, if you connected one |
| `projects.json` | projects |
| `tasks.json` | completed tasks |
| `blockers.json` | blockers |
| `reminders.json` | notes to self |
| `planner.json` | the plan for the day |
| `alerts.json` | timed reminders |
| `settings.json` | active project, infrastructure status, pinned item, the auto-push flag |

The generated calendar (`calendar_2026-08.html`) and the history export (`history_export.md`) sit there too. To open the folder from the menu: **📁 Show my data folder**.

A backup is a copy of that one folder. Invoices are kept separately, in the folder from `invoice.output_dir`, by default `~/Documents/Invoices`.

---

## How the code is laid out

| File | What it's responsible for |
|---|---|
| `main.py` | the menu bar, every item, timers, the PeopleForce sync logic |
| `main_setup.py` | the settings panels and the first run |
| `forms.py` | the field definitions each panel is built from |
| `tracker.py` | the background loop polling the active window |
| `task_mapper.py` | the window to task rules |
| `db.py` | SQLite: time stretches, the status archive, the HTML calendar |
| `store.py` | the base layer for working with JSON files |
| `notes.py` | tasks, blockers, reminders, the plan |
| `projects.py` | projects and which one is active |
| `alerts.py` | timed reminders |
| `settings.py` | small stored settings |
| `summarizer.py` | assembling the status text, talking to the AI |
| `backends.py` | checking and installing the AI backends through Homebrew |
| `invoice.py` | filling the template, converting to PDF |
| `invoice_import.py` | reading details out of an existing invoice |
| `docx_layout.py` | measuring an existing invoice so its data can be read |
| `peopleforce.py` | the PeopleForce API |
| `ui_windows.py` | native input windows |
| `config.py` | reading `config.yaml` and `profile.json`, shared constants |

The modules live in the `chronify/` package and the entry point is the `chronify` command (`chronify.main:main`). Tests are in `tests/`, helper scripts in `scripts/`.

---

## When something doesn't work

**Only app names get recorded, no tasks.**
Screen Recording hasn't been granted, see the permissions section above. macOS ties the permission to the exact binary, so after `brew upgrade chronify` you have to grant it again.

**Nothing gets recorded at all.**
Look at the menu bar icon. `⏸` means tracking is paused and `⚠️ no project` means there's no project to record against.

**The status comes out as a plain list, without any rewriting.**
The AI backend is unavailable or wasn't picked. Start with **⚙️ Settings → Daily status**. For Ollama, check that it's running (`ollama list`) and that `ollama_model` in the config matches the model name exactly, tag like `:3b` included. Ollama and apfel share port 11434, so run only one of them. `lsof -i :11434` shows who took it.

**The invoice PDF isn't created.**
LibreOffice is missing: `brew install --cask libreoffice`. The `.docx` is created either way, and the PDF can be generated later through **🧾 Invoice → Refresh PDF**.

**The invoice has no table, the rows run as plain text.**
The template was saved in Pages or TextEdit and the nested table became text. Delete `~/.work_tracker/my_invoice_template.docx` to go back to the stock template, and from then on edit it only in Word or LibreOffice. To check any template: `python3 scripts/check_template.py <file>`.

**The invoice still shows `{{TOKENS}}`.**
That field is empty. Fill it in through **⚙️ Settings → Payment details** and create the invoice again. The app lists exactly which values were missing after every run.

**PeopleForce returns an error.**
Usually a missing project id, or a key that is not the company one. Ask whoever administers PeopleForce for the right key. Project ids are set per project: **🏷 Project → ✏️ Edit a project**.

**PeopleForce says the hours don't fit into the day.**
The total, counted from your start of the working day, runs past midnight. Lower that hour in **⚙️ Settings → PeopleForce** or push part of the time by hand.

**The app didn't start after a reboot.**
Check the service: `brew services list`. If it's in the `error` state, the log is at `/opt/homebrew/var/log/chronify.log`.

---

## Limitations

- macOS only. The tracking depends on Quartz and AppKit.
- It's worth copying `~/.work_tracker/` before an upgrade. Nothing has ever eaten it, but it's the one folder that matters.
- The quality of the status depends on the local model. `qwen2.5:3b` is fast but small and gets details muddled now and then. If the text looks odd, try a bigger model. apfel has a 4096 token context, so very long days get cut off.
- Deleting a project doesn't move its hours anywhere. They stay in your stats as unassigned time and are never pushed.
- The tests cover the logic that runs without macOS: invoices, backends, status assembly, menu wiring. The tracking itself, the windows and the PeopleForce sync aren't covered and get checked by hand.
