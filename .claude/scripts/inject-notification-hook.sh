#!/bin/bash
set -e

INPUT=$(cat)
SESSION_ID=$(echo "$INPUT" | python3 -c "import json,sys; print(json.load(sys.stdin).get('session_id',''))")

if [ -z "$SESSION_ID" ]; then
  echo "Warning: No session_id in hook input" >&2
  exit 0
fi

BUNDLE_ID=$(osascript -e 'id of (path to frontmost application)' 2>/dev/null) || true

if [ -z "$BUNDLE_ID" ]; then
  echo "Warning: Could not detect frontmost app bundle ID" >&2
  exit 0
fi

mkdir -p /tmp/claude-sessions
echo "$BUNDLE_ID" > "/tmp/claude-sessions/$SESSION_ID"
echo "Registered bundle ID $BUNDLE_ID for session $SESSION_ID"
