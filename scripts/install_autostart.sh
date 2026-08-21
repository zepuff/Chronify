#!/bin/bash
# Registers Work Tracker as a macOS LaunchAgent so it starts at login.
# Run with:     chmod +x install_autostart.sh && ./install_autostart.sh
# Remove with:  ./install_autostart.sh --remove

set -e

PLIST_NAME="com.chronify.app"
PLIST_PATH="$HOME/Library/LaunchAgents/${PLIST_NAME}.plist"
LOG_PATH="$HOME/.work_tracker/autostart.log"

# Installed through Homebrew? Use that binary. Otherwise fall back to the
# local venv next to the source checkout.
if command -v chronify &> /dev/null; then
    CHRONIFY_BIN="$(command -v chronify)"
    WORK_DIR="$HOME"
else
    WORK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
    CHRONIFY_BIN="$WORK_DIR/venv/bin/chronify"
fi

if [ "$1" = "--remove" ]; then
    echo "Disabling autostart..."
    launchctl unload "$PLIST_PATH" 2>/dev/null || true
    rm -f "$PLIST_PATH"
    echo "✅ Autostart disabled. The app will no longer start by itself at login."
    exit 0
fi

if [ ! -x "$CHRONIFY_BIN" ]; then
    echo "❌ chronify not found at $CHRONIFY_BIN"
    echo "   Install it first:  brew install YOUR_GITHUB_USER/chronify/chronify"
    echo "   (or, from a source checkout:  pip install -e .)"
    exit 1
fi

mkdir -p "$HOME/.work_tracker"
mkdir -p "$HOME/Library/LaunchAgents"

cat > "$PLIST_PATH" << PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${PLIST_NAME}</string>
    <key>ProgramArguments</key>
    <array>
        <string>${CHRONIFY_BIN}</string>
    </array>
    <key>WorkingDirectory</key>
    <string>${WORK_DIR}</string>
    <key>RunAtLoad</key>
    <true/>
    <!-- Restart after a crash, but not after a clean quit from the menu -->
    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key>
        <false/>
    </dict>
    <key>ThrottleInterval</key>
    <integer>30</integer>
    <!-- launchd gives a minimal PATH, so Homebrew tools (ollama, soffice)
         were invisible to the app even though they work in a terminal -->
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>
    <key>StandardOutPath</key>
    <string>${LOG_PATH}</string>
    <key>StandardErrorPath</key>
    <string>${LOG_PATH}</string>
</dict>
</plist>
PLIST_EOF

launchctl unload "$PLIST_PATH" 2>/dev/null || true
launchctl load "$PLIST_PATH"

echo "✅ Autostart enabled!"
echo ""
echo "Work Tracker will now start every time you turn on or restart the Mac,"
echo "or log back in — no need to open a terminal manually anymore."
echo "It also restarts itself if it ever crashes (but not when you quit it"
echo "from the menu)."
echo ""
echo "Check that it works right now (without rebooting):"
echo "  launchctl start ${PLIST_NAME}"
echo ""
echo "Logs (if something goes wrong):"
echo "  cat ${LOG_PATH}"
echo ""
echo "Disable autostart:"
echo "  ./install_autostart.sh --remove"