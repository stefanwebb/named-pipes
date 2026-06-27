#!/bin/bash
set -e

INPUT=$(cat)
SESSION_ID=$(echo "$INPUT" | python3 -c "import json,sys; print(json.load(sys.stdin).get('session_id',''))")

if [ -z "$SESSION_ID" ]; then
  exit 0
fi

BUNDLE_FILE="/tmp/claude-sessions/$SESSION_ID"
if [ ! -f "$BUNDLE_FILE" ]; then
  exit 0
fi

BUNDLE_ID=$(cat "$BUNDLE_FILE")
terminal-notifier -title "Claude Code" -message "Waiting for your input" -activate "$BUNDLE_ID" -group "$SESSION_ID" -appIcon "/Applications/Claude.app/Contents/Resources/ion-dist/images/claude_app_icon.png" -sound default
