#!/usr/bin/env bash
# Run pr-monitor. Pass any extra args through (e.g. --size small --debug).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python3 "$SCRIPT_DIR/pr_monitor.py" "$@"
