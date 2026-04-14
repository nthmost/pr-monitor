#!/usr/bin/env python3
"""
pr-monitor: Poll GitHub PR CI status and write breadcrumbs for claude-monitor.

Writes one JSON file per open PR to ~/.claude-monitor/, which claude-monitor
picks up and displays alongside Claude Code task status.

Usage:
    python3 pr_monitor.py                  # use ~/.pr-monitor.toml
    python3 pr_monitor.py --once           # single poll then exit
    python3 pr_monitor.py --config ./my.toml
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from config import Config, load_config, DEFAULT_CONFIG_PATH
from github_client import GitHubAPIError, GitHubClient, parse_prs
from models import PRStatus
from progress import estimate_progress


BREADCRUMB_DIR = Path.home() / ".claude-monitor"


def rollup_to_status(rollup_state: str | None) -> str:
    mapping = {
        "SUCCESS":  "completed",
        "FAILURE":  "error",
        "ERROR":    "error",
        "PENDING":  "in_progress",
        "EXPECTED": "pending",
    }
    return mapping.get((rollup_state or "").upper(), "pending")


def pr_to_breadcrumb(pr: PRStatus, duration_cache: dict) -> dict:
    status = rollup_to_status(pr.rollup_state)
    needs_attention = status == "error"

    check = pr.featured_check
    progress_percent = None
    current_step = None

    if check:
        baseline = duration_cache.get(f"{pr.repo}/{check.name}")
        pct = estimate_progress(check, baseline)
        if pct is not None:
            progress_percent = int(pct * 100)
        job = check.best_job
        if job and job.steps_total:
            current_step = f"{check.name}: step {job.steps_done}/{job.steps_total}"
            if job.current_step_name:
                current_step += f" — {job.current_step_name}"
        else:
            current_step = check.name

    draft_marker = " [draft]" if pr.is_draft else ""
    data = {
        "task_name": f"#{pr.number}: {pr.title}{draft_marker}",
        "status": status,
        "message": pr.repo,
        "needs_attention": needs_attention,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "tiny_title": f"#{pr.number} {pr.title[:24]}",
    }
    if current_step:
        data["current_step"] = current_step
    if progress_percent is not None:
        data["progress_percent"] = progress_percent

    return data


def breadcrumb_filename(pr: PRStatus) -> str:
    safe_repo = pr.repo.replace("/", "_")
    return f"pr_{safe_repo}_{pr.number}.json"


class PRMonitor:
    def __init__(self, config: Config):
        self.config = config
        self._clients: dict[str, GitHubClient] = {}
        self._duration_cache: dict[str, float] = {}
        self._known_files: set[str] = set()
        self._load_duration_cache()
        BREADCRUMB_DIR.mkdir(parents=True, exist_ok=True)

    def get_client(self, identity: str) -> GitHubClient:
        if identity not in self._clients:
            self._clients[identity] = GitHubClient(identity)
        return self._clients[identity]

    def poll_all(self):
        current_files = set()

        for repo_cfg in self.config.repos:
            try:
                client = self.get_client(repo_cfg.identity)
                raw = client.get_open_prs(repo_cfg.owner, repo_cfg.name, repo_cfg.max_prs)
                prs = parse_prs(raw, repo_cfg.full_name)
            except GitHubAPIError as e:
                print(f"[{repo_cfg.full_name}] API error: {e}", file=sys.stderr)
                continue

            for pr in prs:
                if not self.config.show_drafts and pr.is_draft:
                    continue

                # Fetch step data for in-progress checks; update duration cache
                for check in pr.checks:
                    key = f"{repo_cfg.full_name}/{check.name}"
                    if check.status == "COMPLETED" and check.elapsed_seconds:
                        self._duration_cache[key] = check.elapsed_seconds
                    if check.status == "IN_PROGRESS" and check.workflow_run_id:
                        try:
                            check.jobs = client.get_workflow_run_jobs(
                                repo_cfg.owner, repo_cfg.name, check.workflow_run_id
                            )
                        except GitHubAPIError:
                            pass

                filename = breadcrumb_filename(pr)
                filepath = BREADCRUMB_DIR / filename
                data = pr_to_breadcrumb(pr, self._duration_cache)

                with open(filepath, "w") as f:
                    json.dump(data, f, indent=2)

                current_files.add(filename)

        # Remove breadcrumbs for PRs that are no longer open
        for filename in self._known_files - current_files:
            stale = BREADCRUMB_DIR / filename
            if stale.exists():
                stale.unlink()

        self._known_files = current_files
        self._save_duration_cache()

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


def main():
    parser = argparse.ArgumentParser(
        description="Poll GitHub PR CI status and write claude-monitor breadcrumbs"
    )
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument("--once", action="store_true", help="Poll once and exit")
    parser.add_argument("--interval", type=float, default=None)
    args = parser.parse_args()

    config = load_config(Path(args.config).expanduser())
    if args.interval:
        config.refresh_interval = args.interval

    monitor = PRMonitor(config)

    if args.once:
        monitor.poll_all()
        return

    while True:
        monitor.poll_all()
        time.sleep(config.refresh_interval)


if __name__ == "__main__":
    main()
