#!/usr/bin/env bash
# Run pr-monitor. Polls GitHub and writes breadcrumbs to ~/.claude-monitor/.
# Pass --once to poll once and exit, --interval N to override refresh rate.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python3 "$SCRIPT_DIR/pr_monitor.py" "$@"
