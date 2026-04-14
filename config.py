"""Config loading for pr-monitor."""

import sys
from dataclasses import dataclass, field
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomllib
    except ImportError:
        try:
            import tomli as tomllib
        except ImportError:
            tomllib = None


DEFAULT_CONFIG_PATH = Path.home() / ".pr-monitor.toml"


@dataclass
class PRConfig:
    owner: str
    repo: str
    number: int
    identity: str

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.repo}"


@dataclass
class Config:
    prs: list[PRConfig] = field(default_factory=list)
    refresh_interval: int = 30
    cache_file: Path = field(
        default_factory=lambda: Path.home() / ".pr-monitor-cache.json"
    )


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> Config:
    if not path.exists():
        return Config()
    if tomllib is None:
        raise RuntimeError("tomllib not available. pip install tomli")
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    prs = [
        PRConfig(owner=p["owner"], repo=p["repo"], number=int(p["number"]), identity=p["identity"])
        for p in raw.get("prs", [])
    ]
    return Config(
        prs=prs,
        refresh_interval=raw.get("refresh_interval", 30),
        cache_file=Path(raw.get("cache_file", str(Path.home() / ".pr-monitor-cache.json"))),
    )
