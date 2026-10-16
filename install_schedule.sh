#!/usr/bin/env bash
# Install a launchd agent that runs `python -m lottolens refresh` for the
# Sunday 10:00 (Sydney) refresh with a Monday retry. launchd wakes it hourly;
# the Sydney-time window check happens in Python, so it's DST-aware.
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$(pwd)"
LABEL="au.lottolens.refresh"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
VENV="$HOME/Library/Application Support/LottoLens/venv"
LOGS="$HOME/Library/Logs/LottoLens"

if [ ! -x "$VENV/bin/python" ]; then
  echo "Environment not found. Run ./run.sh once first."; exit 1
fi
mkdir -p "$HOME/Library/LaunchAgents" "$LOGS"

xml_escape() { sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g'; }
PY_X="$(printf '%s' "$VENV/bin/python" | xml_escape)"
ROOT_X="$(printf '%s' "$ROOT" | xml_escape)"
LOGS_X="$(printf '%s' "$LOGS" | xml_escape)"

cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PY_X</string><string>-m</string><string>lottolens</string>
    <string>refresh</string><string>--scheduled</string><string>--notify</string>
  </array>
  <key>WorkingDirectory</key><string>$ROOT_X</string>
  <key>StartCalendarInterval</key><dict><key>Minute</key><integer>5</integer></dict>
  <key>StandardOutPath</key><string>$LOGS_X/launchd.out.log</string>
  <key>StandardErrorPath</key><string>$LOGS_X/launchd.err.log</string>
  <key>ProcessType</key><string>Background</string>
</dict>
</plist>
PL

plutil -lint "$PLIST" >/dev/null
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "Installed $PLIST"
echo "Runs hourly at :05 and acts only on Sunday/Monday from 10:00 Sydney time when a result is missing."
echo "Test it now:  launchctl kickstart gui/$(id -u)/$LABEL  (then check $LOGS/launchd.out.log)"
