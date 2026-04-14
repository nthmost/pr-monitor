"""Progress estimation for CI check runs.

GitHub doesn't provide a native progress percentage, so we estimate using:
  1. Step fraction: steps_completed / steps_total (when job step data is available)
  2. Elapsed time: elapsed / baseline_duration (fallback, capped at 95%)

The duration baseline is learned from completed runs and persisted to
~/.pr-monitor-cache.json so estimates improve over time.
"""

from datetime import datetime, timezone
from typing import Optional, Tuple
from models import CheckRun, JobStatus


def estimate_from_steps(job: JobStatus) -> Optional[float]:
    """0.0-1.0 based on completed/total steps. None if no steps."""
    if not job.steps_total:
        return None
    return job.steps_done / job.steps_total


def estimate_from_elapsed(check: CheckRun, baseline_sec: Optional[float]) -> Optional[float]:
    """0.0-0.95 based on elapsed time vs baseline. None if no data."""
    if not check.started_at or not baseline_sec or baseline_sec <= 0:
        return None
    elapsed = check.elapsed_seconds or 0
    return min(elapsed / baseline_sec, 0.95)


def estimate_progress(
    check: CheckRun,
    baseline_sec: Optional[float],
) -> Optional[float]:
    """Return 0.0-1.0 progress estimate, or None if unknown."""
    if check.status == "COMPLETED":
        return 1.0
    if check.status == "QUEUED":
        return 0.0
    # IN_PROGRESS: prefer step-based, fall back to time-based
    job = check.best_job
    if job:
        step_pct = estimate_from_steps(job)
        if step_pct is not None:
            return step_pct
    return estimate_from_elapsed(check, baseline_sec)


def render_bar(progress: Optional[float], color: str, width: int = 8) -> str:
    """Render a unicode block progress bar with rich markup."""
    if progress is None:
        return f"[dim]{'░' * width}[/dim]"
    filled = max(0, min(width, int(width * progress)))
    bar = "█" * filled + "░" * (width - filled)
    return f"[{color}]{bar}[/{color}]"


def format_elapsed(seconds: Optional[float]) -> str:
    """Format elapsed seconds as a compact string."""
    if seconds is None:
        return ""
    if seconds < 60:
        return f"{int(seconds)}s"
    if seconds < 3600:
        return f"{int(seconds / 60)}m"
    return f"{int(seconds / 3600)}h{int((seconds % 3600) / 60)}m"
