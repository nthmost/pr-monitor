#!/usr/bin/env python3
"""
pr-monitor: Live terminal dashboard for GitHub PR CI status.

Watches configured GitHub repos and displays open PRs with their CI
check status and progress bars. Designed as a companion to claude-monitor
(github.com/nthmost/claude-monitor) — run both side-by-side in a
split terminal to see both code-level tasks and CI pipeline status.

Usage:
    python3 pr_monitor.py                      # use ~/.pr-monitor.toml
    python3 pr_monitor.py --config ./my.toml   # custom config
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from config import Config, load_config, DEFAULT_CONFIG_PATH
from github_client import GitHubClient, GitHubAPIError, parse_prs
from models import CheckRun, PRStatus
from progress import estimate_progress, render_bar, format_elapsed


console = Console()


# ─── Monitor core ────────────────────────────────────────────────────────────

class PRMonitor:
    def __init__(self, config: Config):
        self.config = config
        self._clients: Dict[str, GitHubClient] = {}
        self._pr_cache: Dict[str, List[PRStatus]] = {}
        self._duration_cache: Dict[str, float] = {}  # "repo/check_name" -> seconds
        self._auth_errors: Dict[str, str] = {}       # identity -> error message
        self._last_poll: Optional[datetime] = None
        self._next_poll: Optional[datetime] = None
        self._load_duration_cache()

    def get_client(self, identity: str) -> GitHubClient:
        if identity not in self._clients:
            self._clients[identity] = GitHubClient(identity)
        return self._clients[identity]

    def check_all_auth(self):
        """Pre-flight: verify all configured identities are authenticated."""
        identities = {r.identity for r in self.config.repos}
        for identity in identities:
            client = self.get_client(identity)
            if not client.check_auth():
                self._auth_errors[identity] = f"Not authenticated (run: gh auth login --user {identity})"

    def seconds_until_refresh(self) -> float:
        if self._next_poll is None:
            return 0
        delta = (self._next_poll - datetime.now(timezone.utc)).total_seconds()
        return max(0.0, delta)

    def poll_all(self):
        """Poll all configured repos. Updates internal cache."""
        for repo_cfg in self.config.repos:
            if repo_cfg.identity in self._auth_errors:
                continue
            try:
                self._poll_repo(repo_cfg)
            except GitHubAPIError as e:
                # Don't crash; store error and continue
                self._auth_errors[repo_cfg.identity] = str(e)

        self._last_poll = datetime.now(timezone.utc)
        self._next_poll = datetime.fromtimestamp(
            self._last_poll.timestamp() + self.config.refresh_interval,
            tz=timezone.utc
        )
        self._save_duration_cache()

    def _poll_repo(self, repo_cfg):
        client = self.get_client(repo_cfg.identity)
        raw_nodes = client.get_open_prs(repo_cfg.owner, repo_cfg.name, repo_cfg.max_prs)
        prs = parse_prs(raw_nodes, repo_cfg.full_name)

        # Fetch job details for in-progress checks and update duration cache
        for pr in prs:
            if not self.config.show_drafts and pr.is_draft:
                continue
            for check in pr.checks:
                cache_key = f"{repo_cfg.full_name}/{check.name}"
                # Learn duration from completed checks
                if check.status == "COMPLETED" and check.elapsed_seconds:
                    self._duration_cache[cache_key] = check.elapsed_seconds
                # Fetch step-level data for in-progress checks
                if check.status == "IN_PROGRESS" and check.workflow_run_id:
                    try:
                        check.jobs = client.get_workflow_run_jobs(
                            repo_cfg.owner, repo_cfg.name, check.workflow_run_id
                        )
                    except GitHubAPIError:
                        pass  # fallback to time-based progress

        self._pr_cache[repo_cfg.full_name] = prs

    def get_all_prs(self) -> List[PRStatus]:
        """Flat sorted list of all cached PRs."""
        prs = []
        for pr_list in self._pr_cache.values():
            for pr in pr_list:
                if not self.config.show_drafts and pr.is_draft:
                    continue
                prs.append(pr)

        # Sort: failing first, then in-progress, then success
        state_order = {"FAILURE": 0, "ERROR": 0, "PENDING": 1, "EXPECTED": 2, "SUCCESS": 3}
        prs.sort(key=lambda p: state_order.get((p.rollup_state or "").upper(), 4))
        return prs

    def get_baseline(self, repo: str, check_name: str) -> Optional[float]:
        return self._duration_cache.get(f"{repo}/{check_name}")

    def _load_duration_cache(self):
        try:
            if self.config.cache_file.exists():
                with open(self.config.cache_file) as f:
                    self._duration_cache = json.load(f)
        except (OSError, json.JSONDecodeError):
            pass

    def _save_duration_cache(self):
        try:
            with open(self.config.cache_file, "w") as f:
                json.dump(self._duration_cache, f, indent=2)
        except OSError:
            pass


# ─── Display helpers ──────────────────────────────────────────────────────────

def _truncate(s: str, max_len: int) -> str:
    return s if len(s) <= max_len else s[:max_len - 1] + "…"


def create_summary_panel(monitor: PRMonitor) -> Panel:
    all_prs = monitor.get_all_prs()
    n_failing = sum(1 for p in all_prs if (p.rollup_state or "").upper() in ("FAILURE", "ERROR"))
    n_running = sum(1 for p in all_prs if (p.rollup_state or "").upper() == "PENDING")
    n_ok = sum(1 for p in all_prs if (p.rollup_state or "").upper() == "SUCCESS")

    refresh_in = int(monitor.seconds_until_refresh())
    if monitor._last_poll is None:
        timing = "[dim]polling...[/dim]"
    else:
        timing = f"[dim]refresh in {refresh_in}s[/dim]"

    parts = [f"[cyan]{len(all_prs)} open PRs[/cyan]"]
    if n_failing:
        parts.append(f"[red bold]{n_failing} failing[/red bold]")
    if n_running:
        parts.append(f"[yellow]{n_running} running[/yellow]")
    if n_ok:
        parts.append(f"[green]{n_ok} passing[/green]")
    parts.append(timing)

    # Auth errors
    auth_warnings = []
    for identity, err in monitor._auth_errors.items():
        auth_warnings.append(f"[red]⚠ {identity}: {err}[/red]")

    body = "  ".join(parts)
    if auth_warnings:
        body += "\n" + "  ".join(auth_warnings)

    if not monitor.config.repos:
        body = ("[yellow]No repos configured.[/yellow]  "
                "Copy [bold]config.example.toml[/bold] → [bold]~/.pr-monitor.toml[/bold] to get started.")

    return Panel(body, title="[bold cyan]PR Monitor[/bold cyan]", border_style="cyan bold", expand=True)


def _check_cell(check: CheckRun, repo: str, monitor: PRMonitor) -> Tuple[str, str, str]:
    """Returns (name_markup, bar_markup, elapsed_markup) for a check."""
    baseline = monitor.get_baseline(repo, check.name)
    progress = estimate_progress(check, baseline)
    bar = render_bar(progress, check.get_color(), width=8)
    elapsed = format_elapsed(check.elapsed_seconds)
    name = f"{check.get_emoji()} [bold]{_truncate(check.name, 24)}[/bold]"
    return name, bar, elapsed


def create_pr_table(prs: List[PRStatus], monitor: PRMonitor) -> Table:
    """One row per PR, featuring the most interesting active check."""
    table = Table(
        title="Open Pull Requests",
        show_header=True,
        border_style="cyan",
        expand=True,
        show_lines=True,
    )
    table.add_column("", width=3)        # overall status emoji
    table.add_column("PR", width=6)
    table.add_column("Title / Repo", no_wrap=False)
    table.add_column("CI Check", width=28)
    table.add_column("Progress", width=10)
    table.add_column("Elapsed", width=8, style="dim")

    for idx, pr in enumerate(prs):
        overall = pr.overall_emoji
        draft_marker = " [dim]draft[/dim]" if pr.is_draft else ""
        pr_num = f"[bold]#{pr.number}[/bold]"
        title_repo = f"{_truncate(pr.title, 40)}{draft_marker}\n[dim]{pr.repo}[/dim]"

        check = pr.featured_check
        if check:
            check_name, bar, elapsed = _check_cell(check, pr.repo, monitor)
            # Show count of other active checks
            n_active = len(pr.active_checks)
            if n_active > 1:
                check_name += f"\n[dim]+{n_active - 1} more running[/dim]"
            elif len(pr.failed_checks) > 1:
                check_name += f"\n[dim]+{len(pr.failed_checks) - 1} more failing[/dim]"
        else:
            check_name = "[dim]no checks[/dim]"
            bar = render_bar(None, "dim")
            elapsed = ""

        row_style = "bold red" if (pr.rollup_state or "").upper() in ("FAILURE", "ERROR") else (
            "bright_white" if idx % 2 == 0 else "light_coral"
        )

        table.add_row(
            overall, pr_num, title_repo, check_name, bar, elapsed,
            style=row_style,
        )

    return table


def create_display(monitor: PRMonitor) -> Group:
    components = [create_summary_panel(monitor)]

    prs = monitor.get_all_prs()
    if prs:
        components.append(create_pr_table(prs, monitor))
    elif monitor.config.repos:
        components.append(Panel(
            "[green]No open PRs — all clear! 🎉[/green]",
            border_style="green",
            expand=True,
        ))

    return Group(*components)


# ─── Entry point ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Live terminal dashboard for GitHub PR CI status"
    )
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help=f"Path to TOML config file (default: {DEFAULT_CONFIG_PATH})",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=None,
        help="Poll interval in seconds (overrides config)",
    )
    parser.add_argument(
        "--no-drafts",
        action="store_true",
        help="Hide draft PRs",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Show startup info",
    )
    args = parser.parse_args()

    config_path = Path(args.config).expanduser()
    config = load_config(config_path)

    if args.interval:
        config.refresh_interval = args.interval
    if args.no_drafts:
        config.show_drafts = False

    if args.debug:
        console.print(f"[dim]Config: {config_path}[/dim]")
        console.print(f"[dim]Repos: {[r.full_name for r in config.repos]}[/dim]")
        console.print(f"[dim]Refresh: {config.refresh_interval}s[/dim]\n")

    monitor = PRMonitor(config)

    if config.repos:
        monitor.check_all_auth()

    try:
        with console.screen(hide_cursor=True):
            with Live(console=console, refresh_per_second=1, screen=True) as live:
                while True:
                    if monitor.seconds_until_refresh() <= 0:
                        monitor.poll_all()
                    display = create_display(monitor)
                    live.update(display)
                    time.sleep(1)
    except KeyboardInterrupt:
        pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
