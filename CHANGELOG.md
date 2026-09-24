# Changelog

## 0.3.0

Menu and settings
- Menu items renamed to plain language, each with a line underneath saying what it does
- Every settings field prints where its value comes from and what happens if it is left empty
- The API key field has a Show button
- The invoicing section lets you pick the folder invoices are written to
- First launch explains what the app is and offers to create the first project

Windows and keyboard
- Windows no longer disappear when another app comes to the front
- ⌘C, ⌘V, ⌘A and ⌘Z work everywhere, Return saves, Esc closes
- The prompt in the quick input window is now actually shown
- The app no longer takes a Dock icon

Invoices
- The result says which folder the files went to and offers to show them in Finder
- Empty name fields no longer leave underscores in the file name
- The PDF is no longer converted and opened twice

Running it
- `chronify --background` starts it without holding the terminal
- `WORK_TRACKER_HOME` points the data folder elsewhere, for testing against real data safely
- Pillow is optional: a signature already in the template's format needs no conversion

Packaging
- The formula installs prebuilt wheels instead of building from source
- `packaging/wheels.py` regenerates the resource blocks when the Python version moves

## 0.2.0

- Installed through Homebrew instead of a setup script
