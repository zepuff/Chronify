#!/bin/bash
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

set -e

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SANDBOX="${TMPDIR:-/tmp}/chronify-firstrun-$$"

if [ "$1" = "--keep" ]; then
    KEEP=1
    shift
fi

# A checkout's own venv wins over anything installed globally, so testing
# a working copy never silently runs the released build instead.
if [ -x "$ROOT/venv/bin/chronify" ]; then
    BIN="$ROOT/venv/bin/chronify"
elif [ -n "$VIRTUAL_ENV" ] && [ -x "$VIRTUAL_ENV/bin/chronify" ]; then
    BIN="$VIRTUAL_ENV/bin/chronify"
elif command -v chronify &> /dev/null; then
    BIN="$(command -v chronify)"
else
    echo "chronify not found. From a source checkout:"
    echo "    python3 -m venv venv && source venv/bin/activate && pip install -e ."
    exit 1
fi

# The console script's shebang points at the interpreter that owns it, which
# is not always next to the binary.
PY_BIN="$(head -1 "$BIN" | sed -e 's|^#!||' -e 's|^ *||' | awk '{print $1}')"
if [ ! -x "$PY_BIN" ]; then
    PY_BIN="$(dirname "$BIN")/python3"
fi
if [ ! -x "$PY_BIN" ]; then
    PY_BIN="$(command -v python3)"
fi

echo "Using:  $BIN"
echo "        $PY_BIN"
echo
if [ -f "$ROOT/BUILD.txt" ]; then
    head -1 "$ROOT/BUILD.txt"
    echo
fi

# A stale unzip is the likeliest reason a fix seems not to have landed:
# unzip -o overwrites files but never deletes ones the archive dropped.
STALE="$(find "$ROOT/tests" -name 'test_invoice_template.py' -o -name 'test_invoice_autotemplate.py' 2>/dev/null)"
if [ -n "$STALE" ]; then
    echo "Files from an older build are still here:"
    echo "$STALE" | sed 's|^|    |'
    echo
    echo "Delete them, or the test run reports failures that no longer exist:"
    echo "    rm $STALE"
    echo
fi

if ! grep -q "DocxTemplate" "$ROOT/chronify/invoice.py"; then
    echo "chronify/invoice.py is from an older build: invoices are still filled"
    echo "with the regex substitution that corrupts templates edited in Word."
    echo "Check which archive you unzipped:"
    echo "    ls -lt ~/Downloads/chronify-repo*.zip"
    echo
fi

echo "Import check..."
if ! HOME="$SANDBOX" "$PY_BIN" -c "
import chronify.main, chronify.main_setup, chronify.forms
print('  all modules import cleanly')
"; then
    echo
    echo "The interpreter above cannot see the package. Install it there:"
    echo "    source venv/bin/activate && pip install -e ."
    exit 1
fi

mkdir -p "$SANDBOX"
echo "Sandbox HOME: $SANDBOX"
echo "Your real ~/.work_tracker is untouched."
echo
echo "Expected first run:"
echo "  1. menu bar shows  ⏱ ⚠️ no project"
echo "  2. a notification after 2s, no modal window"
echo "  3. 🏷 Active project → + Add a project  → one panel, 3 fields"
echo "  4. Save → '<name> is ready' → Done"
echo "  5. 📤 Push to PeopleForce → Today  → PeopleForce panel appears,"
echo "     and the push continues by itself after Save"
echo "  6. ⚙️ Settings shows — — — — before step 5, then ✅ for PeopleForce"
echo
echo "Ctrl-C or Quit from the menu to stop."
echo

HOME="$SANDBOX" "$BIN" || true

echo
echo "What the run produced:"
find "$SANDBOX/.work_tracker" -type f 2>/dev/null | sed "s|$SANDBOX/.work_tracker|  |" || echo "  (nothing)"

if [ -f "$SANDBOX/.work_tracker/profile.json" ]; then
    echo
    echo "profile.json:"
    sed 's/^/  /' "$SANDBOX/.work_tracker/profile.json"
fi

if [ -n "$KEEP" ]; then
    echo
    echo "Kept at $SANDBOX"
else
    rm -rf "$SANDBOX"
    echo
    echo "Sandbox removed. Pass --keep to inspect it afterwards."
fi
