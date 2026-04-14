"""GitHub API client for pr-monitor.

Uses the gh CLI as a subprocess to avoid extra dependencies and to
leverage existing gh auth sessions. Supports multiple identities by
caching tokens per identity and injecting GH_TOKEN per call.
"""

import json
import os
import re
import subprocess
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from models import CheckRun, JobStatus, PRStatus, StepStatus


RUN_ID_RE = re.compile(r"/actions/runs/(\d+)/")


class GitHubAPIError(Exception):
    pass


class GitHubClient:
    """Calls GitHub API via gh CLI with per-identity token injection."""

    def __init__(self, identity: str):
        self.identity = identity
        self._token: Optional[str] = None

    def _get_token(self) -> str:
        if self._token is None:
            result = subprocess.run(
                ["gh", "auth", "token", "--user", self.identity],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                raise GitHubAPIError(
                    f"Could not get token for identity '{self.identity}': "
                    f"{result.stderr.strip()}"
                )
            self._token = result.stdout.strip()
        return self._token

    def _run_gh(self, args: List[str]) -> Any:
        """Run a gh command with this identity's token. Returns parsed JSON."""
        token = self._get_token()
        env = {**os.environ, "GH_TOKEN": token}
        result = subprocess.run(
            ["gh"] + args,
            capture_output=True,
            text=True,
            env=env,
        )
        if result.returncode != 0:
            raise GitHubAPIError(result.stderr.strip())
        if not result.stdout.strip():
            return None
        return json.loads(result.stdout)

    def _api(self, path: str) -> Any:
        return self._run_gh(["api", path, "--paginate"])

    def _graphql(self, query: str, variables: Dict[str, Any]) -> Any:
        args = ["api", "graphql", "-f", f"query={query}"]
        for key, value in variables.items():
            args += ["-F", f"{key}={value}"]
        data = self._run_gh(args)
        if data and "errors" in data:
            raise GitHubAPIError(str(data["errors"]))
        return data.get("data") if data else None

    def check_auth(self) -> bool:
        """Return True if this identity is authenticated."""
        try:
            self._get_token()
            return True
        except GitHubAPIError:
            return False

    def get_rate_limit(self) -> Dict[str, Any]:
        data = self._api("/rate_limit")
        return data.get("resources", {}).get("core", {}) if data else {}

    def get_open_prs(self, owner: str, repo: str, max_prs: int = 20) -> List[Dict]:
        """Fetch open PRs with check rollup via GraphQL. Returns raw dicts."""
        query = """
query($owner: String!, $repo: String!, $count: Int!) {
  repository(owner: $owner, name: $repo) {
    pullRequests(first: $count, states: OPEN,
                 orderBy: {field: UPDATED_AT, direction: DESC}) {
      nodes {
        number
        title
        isDraft
        headRefName
        author { login }
        commits(last: 1) {
          nodes {
            commit {
              statusCheckRollup {
                state
                contexts(first: 50) {
                  nodes {
                    __typename
                    ... on CheckRun {
                      name
                      status
                      conclusion
                      startedAt
                      completedAt
                      detailsUrl
                    }
                  }
                  pageInfo { hasNextPage endCursor }
                }
              }
            }
          }
        }
      }
    }
  }
}
"""
        data = self._graphql(query, {"owner": owner, "repo": repo, "count": max_prs})
        if not data:
            return []
        repo_data = data.get("repository", {})
        nodes = repo_data.get("pullRequests", {}).get("nodes", [])
        return nodes

    def get_workflow_run_jobs(
        self, owner: str, repo: str, run_id: int
    ) -> List[JobStatus]:
        """Fetch job + step details for a workflow run. Used for in-progress checks."""
        try:
            data = self._api(f"/repos/{owner}/{repo}/actions/runs/{run_id}/jobs")
        except GitHubAPIError:
            return []
        if not data:
            return []

        jobs = []
        for j in data.get("jobs", []):
            steps = []
            for s in j.get("steps", []):
                steps.append(StepStatus(
                    number=s.get("number", 0),
                    name=s.get("name", ""),
                    status=s.get("status", "queued"),
                    conclusion=s.get("conclusion"),
                    started_at=_parse_dt(s.get("started_at")),
                    completed_at=_parse_dt(s.get("completed_at")),
                ))
            jobs.append(JobStatus(
                job_id=j.get("id", 0),
                name=j.get("name", ""),
                status=j.get("status", "queued"),
                conclusion=j.get("conclusion"),
                started_at=_parse_dt(j.get("started_at")),
                steps=steps,
            ))
        return jobs


def parse_prs(raw_nodes: List[Dict], repo_full_name: str) -> List[PRStatus]:
    """Convert raw GraphQL PR nodes into PRStatus objects."""
    prs = []
    for node in raw_nodes:
        commit_nodes = node.get("commits", {}).get("nodes", [])
        rollup = None
        raw_checks = []
        if commit_nodes:
            commit = commit_nodes[0].get("commit", {})
            rollup_data = commit.get("statusCheckRollup")
            if rollup_data:
                rollup = rollup_data.get("state")
                ctx_nodes = rollup_data.get("contexts", {}).get("nodes", [])
                raw_checks = [c for c in ctx_nodes if c.get("__typename") == "CheckRun"]

        checks = []
        for rc in raw_checks:
            run_id = _extract_run_id(rc.get("detailsUrl"))
            checks.append(CheckRun(
                name=rc.get("name", ""),
                status=(rc.get("status") or "QUEUED").upper(),
                conclusion=(rc.get("conclusion") or "").upper() or None,
                started_at=_parse_dt(rc.get("startedAt")),
                completed_at=_parse_dt(rc.get("completedAt")),
                details_url=rc.get("detailsUrl"),
                workflow_run_id=run_id,
            ))

        prs.append(PRStatus(
            repo=repo_full_name,
            number=node["number"],
            title=node.get("title", ""),
            branch=node.get("headRefName", ""),
            author=(node.get("author") or {}).get("login", ""),
            is_draft=node.get("isDraft", False),
            rollup_state=(rollup or "").upper() or None,
            checks=checks,
        ))
    return prs


def _parse_dt(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _extract_run_id(url: Optional[str]) -> Optional[int]:
    if not url:
        return None
    m = RUN_ID_RE.search(url)
    return int(m.group(1)) if m else None
