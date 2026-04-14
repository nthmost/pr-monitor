"""Data models for pr-monitor."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, List


@dataclass
class StepStatus:
    number: int
    name: str
    status: str           # queued | in_progress | completed
    conclusion: Optional[str]  # success | failure | skipped | None
    started_at: Optional[datetime]
    completed_at: Optional[datetime]


@dataclass
class JobStatus:
    job_id: int
    name: str
    status: str
    conclusion: Optional[str]
    started_at: Optional[datetime]
    steps: List[StepStatus] = field(default_factory=list)

    @property
    def steps_done(self) -> int:
        return sum(1 for s in self.steps if s.status == "completed")

    @property
    def steps_total(self) -> int:
        return len(self.steps)

    @property
    def current_step_name(self) -> Optional[str]:
        for s in self.steps:
            if s.status == "in_progress":
                return s.name
        return None


@dataclass
class CheckRun:
    name: str
    status: str           # QUEUED | IN_PROGRESS | COMPLETED
    conclusion: Optional[str]   # SUCCESS | FAILURE | SKIPPED | NEUTRAL | etc.
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    details_url: Optional[str]
    workflow_run_id: Optional[int]
    jobs: List[JobStatus] = field(default_factory=list)

    def get_emoji(self) -> str:
        if self.status == "QUEUED":
            return "⏳"
        if self.status == "IN_PROGRESS":
            return "🔄"
        if self.status == "COMPLETED":
            conclusion_map = {
                "SUCCESS": "✅",
                "FAILURE": "❌",
                "SKIPPED": "⏭️",
                "NEUTRAL": "➖",
                "CANCELLED": "🚫",
                "TIMED_OUT": "⌛",
                "ACTION_REQUIRED": "⚠️",
            }
            return conclusion_map.get((self.conclusion or "").upper(), "❓")
        return "❓"

    def get_color(self) -> str:
        if self.status == "QUEUED":
            return "yellow"
        if self.status == "IN_PROGRESS":
            return "cyan"
        conclusion = (self.conclusion or "").upper()
        if conclusion == "SUCCESS":
            return "green"
        if conclusion in ("FAILURE", "TIMED_OUT"):
            return "red"
        return "dim"

    @property
    def elapsed_seconds(self) -> Optional[float]:
        if not self.started_at:
            return None
        end = self.completed_at or datetime.now(timezone.utc)
        return (end - self.started_at).total_seconds()

    @property
    def best_job(self) -> Optional[JobStatus]:
        """Return the most interesting job: first in_progress, else first failure."""
        for j in self.jobs:
            if j.status == "in_progress":
                return j
        for j in self.jobs:
            if j.conclusion == "failure":
                return j
        return self.jobs[0] if self.jobs else None


@dataclass
class PRStatus:
    repo: str           # "owner/name"
    number: int
    title: str
    branch: str
    author: str
    is_draft: bool
    rollup_state: str   # SUCCESS | FAILURE | PENDING | EXPECTED | ERROR | None
    checks: List[CheckRun] = field(default_factory=list)
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def age_seconds(self) -> float:
        return (datetime.now(timezone.utc) - self.fetched_at).total_seconds()

    @property
    def overall_emoji(self) -> str:
        state = (self.rollup_state or "").upper()
        state_map = {
            "SUCCESS": "✅",
            "FAILURE": "❌",
            "PENDING": "🔄",
            "EXPECTED": "⏳",
            "ERROR": "❌",
        }
        return state_map.get(state, "❓")

    @property
    def overall_color(self) -> str:
        state = (self.rollup_state or "").upper()
        color_map = {
            "SUCCESS": "green",
            "FAILURE": "red",
            "PENDING": "cyan",
            "EXPECTED": "yellow",
            "ERROR": "red",
        }
        return color_map.get(state, "dim")

    @property
    def active_checks(self) -> List[CheckRun]:
        """Checks that are queued or in_progress."""
        return [c for c in self.checks if c.status in ("QUEUED", "IN_PROGRESS")]

    @property
    def failed_checks(self) -> List[CheckRun]:
        return [c for c in self.checks
                if c.status == "COMPLETED"
                and (c.conclusion or "").upper() == "FAILURE"]

    @property
    def featured_check(self) -> Optional[CheckRun]:
        """The single most interesting check to highlight."""
        # Prefer failing first
        if self.failed_checks:
            return self.failed_checks[0]
        # Then in_progress
        for c in self.checks:
            if c.status == "IN_PROGRESS":
                return c
        # Then queued
        for c in self.checks:
            if c.status == "QUEUED":
                return c
        return self.checks[0] if self.checks else None
