# pr-monitor

Watch specific GitHub PRs and see their CI status in [claude-monitor](https://github.com/nthmost/claude-monitor).

You pick which PRs to track. Each one shows up as a card in claude-monitor with a progress bar, the current CI step, and an alert if something fails — right alongside your Claude Code tasks.

## How it works

`pr-monitor` runs as a background daemon. Every 30 seconds it polls GitHub for the CI status of your watched PRs and writes a JSON breadcrumb file to `~/.claude-monitor/` for each one. claude-monitor picks these up automatically.

```
~/.claude-monitor/
├── pr_conductor-oss_conductor_1001.json   ← written by pr-monitor
├── pr_nthmost_metapub_42.json             ← written by pr-monitor
├── home_assistant.json                    ← written by Claude Code
└── ...
```

## Requirements

- Python 3.11+ (or 3.8+ with `pip install tomli`)
- [`gh` CLI](https://cli.github.com/) installed and authenticated
- [claude-monitor](https://github.com/nthmost/claude-monitor) running somewhere

```bash
pip install -r requirements.txt
```

## Setup

```bash
git clone https://github.com/nthmost/pr-monitor.git
cd pr-monitor
pip install -r requirements.txt

# Start the daemon (add to launchd/systemd to run at login)
python3 pr_monitor.py
```

## Adding PRs to watch

### CLI

```bash
# Paste a GitHub PR URL — identity is auto-detected
python3 prctl.py add https://github.com/myorg/myrepo/pull/42

# Remove
python3 prctl.py remove myorg/myrepo#42

# List
python3 prctl.py list
```

### Web UI

```bash
python3 web.py   # opens http://localhost:7842
```

Paste one or more PR URLs into the text box. Done.

## Multiple GitHub identities

If you work across personal and work GitHub accounts, identity is detected automatically by checking which account has push access to the repo. No `gh auth switch` required.

```bash
gh auth status   # verify both accounts are listed
```

You can always override: `prctl.py add <url> --identity myuser`

## Config

`~/.pr-monitor.toml` — managed by `prctl.py` and the web UI, but you can edit it directly:

```toml
refresh_interval = 30   # seconds between GitHub polls

[[prs]]
owner    = "myorg"
repo     = "myrepo"
number   = 42
identity = "my-gh-username"
```

## Progress bars

GitHub doesn't expose a native completion percentage. pr-monitor estimates it two ways:

1. **Step fraction** — if a workflow job has 21 steps and 13 are done, that's 62%
2. **Elapsed time** — falls back to comparing elapsed time against a learned baseline, saved to `~/.pr-monitor-cache.json` and improving over time

## Related

- [claude-monitor](https://github.com/nthmost/claude-monitor) — the terminal dashboard this feeds into
