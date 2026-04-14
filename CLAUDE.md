# pr-monitor

A live terminal dashboard for GitHub PR CI status. Companion to claude-monitor.

## Key Files

- `pr_monitor.py` — main loop + Rich display (mirrors claude-monitor's monitor.py structure)
- `github_client.py` — all GitHub API calls via `gh` CLI subprocess; per-identity token caching
- `models.py` — `PRStatus`, `CheckRun`, `JobStatus`, `StepStatus` dataclasses
- `progress.py` — progress estimation: step-fraction (preferred) + elapsed-time fallback
- `config.py` — TOML config loader; default path `~/.pr-monitor.toml`
- `config.example.toml` — user-facing template; ship this, not a pre-filled config.toml

## Architecture

### Data flow
1. `PRMonitor.poll_all()` iterates configured repos
2. Per repo: one GraphQL call → all open PRs + check rollup state
3. For each IN_PROGRESS check with a `workflow_run_id`: REST call for job/step data
4. Progress estimated from steps (preferred) or elapsed vs. learned baseline
5. Duration baselines persisted to `~/.pr-monitor-cache.json`

### Display loop
- Rich `Live` re-renders every 1 second (animates progress bars between polls)
- GitHub polls every `refresh_interval` seconds (default: 30)
- Three display sizes: `tiny` (1 row/PR), `small` (1 row/check), `medium` (all fields)

### Multi-identity auth
- `gh auth token --user <identity>` called once at startup, token cached in-memory
- `GH_TOKEN=<token>` injected via subprocess env — no `gh auth switch`, no global state mutation
- Auth errors shown in summary panel, that identity's repos skipped

## Config format (`~/.pr-monitor.toml`)
```toml
refresh_interval = 30
display_size = "tiny"
show_drafts = true

[[repos]]
owner = "myorg"
name  = "myrepo"
identity = "my-gh-username"
```

## Relation to claude-monitor

Designed to sit side-by-side with claude-monitor in a split terminal:
- claude-monitor: Claude Code task breadcrumbs (JSON files in ~/.claude-monitor/)
- pr-monitor: GitHub Actions CI status on open PRs

Both use the same `rich` library and similar display conventions (tiny_title concept,
alternating row colors, emoji status indicators, same progress bar rendering).

## Development notes

- No PyGithub dependency — gh CLI subprocess only (keeps deps minimal like claude-monitor)
- `tomllib` is stdlib in Python 3.11+; `tomli` backport for 3.8-3.10
- GraphQL `contexts(first: 50)` may hit pagination for repos with many checks; `pageInfo.hasNextPage` is fetched but pagination is not yet implemented (most repos stay under 50)
- Third-party check apps (Codecov, etc.) have `detailsUrl` pointing offsite — `_extract_run_id()` returns None for these; they fall back to time-based progress
- `--no-drafts` flag suppresses draft PRs at display layer; they are still fetched

## Testing without a config

Run with `--debug` to see startup info. With no `~/.pr-monitor.toml`, the monitor starts
and shows the "no repos configured" message in the summary panel — no crash.
