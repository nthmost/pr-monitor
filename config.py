"""Config loading for pr-monitor.

Config file uses TOML format. Default location: ~/.pr-monitor.toml
Copy config.example.toml to get started.
"""

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomllib
    except ImportError:
        try:
            import tomli as tomllib  # pip install tomli for Python < 3.11
        except ImportError:
            tomllib = None


DEFAULT_CONFIG_PATH = Path.home() / ".pr-monitor.toml"


@dataclass
class RepoConfig:
    owner: str
    name: str
    identity: str       # gh username to authenticate as
    max_prs: int = 20   # max open PRs to fetch

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.name}"


@dataclass
class Config:
    repos: List[RepoConfig] = field(default_factory=list)
    refresh_interval: int = 30      # seconds between GitHub polls
    show_drafts: bool = True        # whether to show draft PRs
    max_completed_age_min: int = 60 # hide completed PRs older than N minutes
    cache_file: Path = field(
        default_factory=lambda: Path.home() / ".pr-monitor-cache.json"
    )


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> Config:
    """Load config from TOML file. Returns empty Config if file not found."""
    if not path.exists():
        return Config()

    if tomllib is None:
        raise RuntimeError(
            "tomllib not available. Install tomli: pip install tomli  "
            "(or upgrade to Python 3.11+)"
        )

    with open(path, "rb") as f:
        raw = tomllib.load(f)

    repos = []
    for r in raw.get("repos", []):
        repos.append(RepoConfig(
            owner=r["owner"],
            name=r["name"],
            identity=r["identity"],
            max_prs=r.get("max_prs", 20),
        ))

    return Config(
        repos=repos,
        refresh_interval=raw.get("refresh_interval", 30),
        show_drafts=raw.get("show_drafts", True),
        max_completed_age_min=raw.get("max_completed_age_min", 60),
        cache_file=Path(raw.get("cache_file", str(Path.home() / ".pr-monitor-cache.json"))),
    )
