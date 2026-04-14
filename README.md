# pr-monitor

A compact, live terminal dashboard for GitHub PR CI status. Watch active CI pipeline
jobs and their progress bars across multiple repos and GitHub identities — so you know
the moment a build passes, fails, or needs your attention.

```
┌─ PR Monitor ─────────────────────────────────────────────────────────────────┐
│ 3 open PRs  1 failing  1 running  1 passing  refresh in 22s                 │
└──────────────────────────────────────────────────────────────────────────────┘
┌─ Open Pull Requests ─────────────────────────────────────────────────────────┐
│    PR     Title / Repo              CI Check          Progress   Elapsed     │
│ ───────────────────────────────────────────────────────────────────────────  │
│ 🔄 #42   fix: auth token handling   🔄 build (2 of 3)  ████░░░░   2m        │
│          myorg/myrepo               ✅ lint                                  │
│ ❌ #17   chore: bump deps           ❌ test-matrix      ████████   8m        │
│          myorg/otherapp             ✅ lint                                  │
│ ✅ #103  feat: new endpoint         ✅ all passing      ████████   5m        │
│          myorg/api                                                           │
└──────────────────────────────────────────────────────────────────────────────┘
```

## Works with claude-monitor

`pr-monitor` is designed as a **companion to [claude-monitor](https://github.com/nthmost/claude-monitor)**.
Run both side-by-side in a split terminal:

```
┌────────────────────────┬───────────────────────────┐
│   claude-monitor       │      pr-monitor            │
│  (Claude Code tasks)   │  (GitHub PR CI status)     │
│                        │                            │
│ 🔄 home-assistant      │ 🔄 #42 fix: auth token     │
│    Migrating DB        │    build ████░░░░ 2m       │
│    ████████░░ 80%      │                            │
└────────────────────────┴───────────────────────────┘
```

- **claude-monitor**: Shows what Claude Code is actively working on (task progress, step-level breadcrumbs)
- **pr-monitor**: Shows the CI pipeline status for your open PRs (GitHub Actions jobs, step progress)

## Requirements

- Python 3.8+
- [`gh` CLI](https://cli.github.com/) installed and authenticated
- `rich` library (`pip install -r requirements.txt`)

## Setup

```bash
# 1. Clone
git clone https://github.com/nthmost/pr-monitor.git
cd pr-monitor

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure
cp config.example.toml ~/.pr-monitor.toml
# Edit ~/.pr-monitor.toml and add your repos

# 4. Run
./run_monitor.sh
```

## Configuration

Copy `config.example.toml` to `~/.pr-monitor.toml` and add your repos:

```toml
refresh_interval = 30      # seconds between GitHub polls
display_size = "tiny"      # tiny | small | medium

[[repos]]
owner = "your-org"
name  = "your-repo"
identity = "your-gh-username"

[[repos]]
owner = "another-org"
name  = "another-repo"
identity = "another-gh-account"  # supports multiple identities
```

The `identity` field must match a username that has been logged in via `gh auth login`.

## Multiple GitHub Identities

`pr-monitor` supports multiple `gh` accounts simultaneously. Each `[[repos]]` entry
specifies which identity to use. Tokens are cached at startup — no `gh auth switch`
needed, no global auth state is mutated.

```bash
# Make sure both identities are logged in:
gh auth login          # for your primary account
gh auth login          # for your secondary account
gh auth status         # verify both are listed
```

## Display Modes

| Mode | Columns | Best for |
|------|---------|----------|
| `tiny` | Status, PR#, Title/Repo, Featured Check, Progress, Elapsed | Small screens, companion mode |
| `small` | One row per check run with step detail | Medium screens |
| `medium` | All fields including author and branch | Wide terminals |

```bash
./run_monitor.sh --size small
./run_monitor.sh --size medium
```

## Progress Bars

GitHub doesn't expose a native completion percentage for CI runs. `pr-monitor` estimates
progress two ways:

1. **Step fraction** (preferred): counts completed/total steps within a workflow job.
   Requires a GitHub Actions workflow run. E.g., if a job has 21 steps and 13 are done → 62%.

2. **Elapsed time** (fallback): compares elapsed time against a learned baseline duration.
   Baselines are learned from completed runs and saved to `~/.pr-monitor-cache.json`,
   so estimates improve the more runs you observe.

## CLI Options

```
--config PATH     Path to config file (default: ~/.pr-monitor.toml)
--size SIZE       Display size: tiny | small | medium
--interval N      Poll interval in seconds (overrides config)
--no-drafts       Hide draft PRs
--debug           Show startup info
```

## Shell Alias

```bash
# Add to ~/.zshrc or ~/.bashrc
alias pr-monitor='/path/to/pr-monitor/run_monitor.sh'
```

## Status Indicators

| Symbol | Meaning |
|--------|---------|
| 🔄 | In progress |
| ✅ | Passed |
| ❌ | Failed |
| ⏳ | Queued |
| ⏭️ | Skipped |
| ⚠️ | Action required |

## Architecture

```
pr-monitor/
├── pr_monitor.py       # Main loop + rich display
├── github_client.py    # gh CLI subprocess calls, per-identity token caching
├── models.py           # PRStatus, CheckRun, JobStatus dataclasses
├── progress.py         # Progress estimation (step-fraction + time-based)
├── config.py           # TOML config loader
├── config.example.toml # Config template
└── run_monitor.sh      # Shell wrapper
```

The polling loop:
1. On startup: cache auth tokens for all configured identities
2. Every `refresh_interval` seconds: one GraphQL call per repo fetches all open PRs + check rollup
3. For each in-progress check run: one REST call fetches workflow job steps
4. Display re-renders every second so progress bars animate between polls

## Related

- [claude-monitor](https://github.com/nthmost/claude-monitor) — Live terminal dashboard for Claude Code task status

## License

Free to use and modify.
