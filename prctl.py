#!/usr/bin/env python3
"""
prctl - manage which repos pr-monitor watches

Usage:
    prctl.py add OWNER/REPO        # auto-detects gh identity, adds to config
    prctl.py remove OWNER/REPO     # removes repo from config
    prctl.py list                  # show all watched repos

The add command tries each authenticated gh identity and uses the first
one that can access the repo, so you never need to specify it manually.

Config file: ~/.pr-monitor.toml (created if it doesn't exist)
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

try:
    if sys.version_info >= (3, 11):
        import tomllib
    else:
        import tomli as tomllib
except ImportError:
    tomllib = None

try:
    import tomli_w
except ImportError:
    tomli_w = None

CONFIG_PATH = Path.home() / ".pr-monitor.toml"

STARTER_CONFIG = """\
# pr-monitor configuration
# Managed by prctl.py — you can also edit this file directly.

refresh_interval = 30
display_size = "tiny"
show_drafts = true
"""


# ─── TOML read/write ──────────────────────────────────────────────────────────

def read_config_raw() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    if tomllib is None:
        sys.exit("Error: tomllib not available. pip install tomli  (or use Python 3.11+)")
    with open(CONFIG_PATH, "rb") as f:
        return tomllib.load(f)


def write_config_raw(data: dict):
    """Write config back as TOML using [[repos]] array-of-tables style."""
    # Always use manual serialization — produces readable [[repos]] blocks
    # rather than inline tables. tomli_w is only used for reading.
    lines = []
    for key, value in data.items():
        if key == "repos":
            continue
        if isinstance(value, bool):
            lines.append(f"{key} = {'true' if value else 'false'}")
        elif isinstance(value, str):
            lines.append(f'{key} = "{value}"')
        elif isinstance(value, (int, float)):
            lines.append(f"{key} = {value}")

    for repo in data.get("repos", []):
        lines.append("")
        lines.append("[[repos]]")
        lines.append(f'owner    = "{repo["owner"]}"')
        lines.append(f'name     = "{repo["name"]}"')
        lines.append(f'identity = "{repo["identity"]}"')
        if repo.get("max_prs", 20) != 20:
            lines.append(f'max_prs  = {repo["max_prs"]}')

    with open(CONFIG_PATH, "w") as f:
        f.write("\n".join(lines) + "\n")


def ensure_config_exists():
    if not CONFIG_PATH.exists():
        with open(CONFIG_PATH, "w") as f:
            f.write(STARTER_CONFIG)
        print(f"Created {CONFIG_PATH}")


# ─── gh identity detection ────────────────────────────────────────────────────

def _clean_env() -> dict:
    """Return env with GITHUB_TOKEN removed so gh uses its own credential store."""
    env = dict(os.environ)
    env.pop("GITHUB_TOKEN", None)
    return env


def get_all_identities() -> list[str]:
    """Return list of all gh-authenticated usernames."""
    result = subprocess.run(
        ["gh", "auth", "status"],
        capture_output=True, text=True,
        env=_clean_env(),
    )
    identities = []
    for line in (result.stdout + result.stderr).splitlines():
        line = line.strip()
        # e.g. "✓ Logged in to github.com account nthmost (keyring)"
        if "account" in line and ("✓" in line or "Logged in" in line):
            parts = line.split("account")
            if len(parts) > 1:
                username = parts[1].strip().split()[0]
                identities.append(username)
    return identities


def can_identity_access(identity: str, owner: str, repo: str) -> bool:
    """Return True if this gh identity can read the repo."""
    token_result = subprocess.run(
        ["gh", "auth", "token", "--user", identity],
        capture_output=True, text=True,
        env=_clean_env(),
    )
    if token_result.returncode != 0:
        return False
    token = token_result.stdout.strip()
    env = _clean_env()
    env["GH_TOKEN"] = token
    result = subprocess.run(
        ["gh", "api", f"/repos/{owner}/{repo}", "--jq", ".name"],
        capture_output=True, text=True,
        env=env,
    )
    return result.returncode == 0


def detect_identity(owner: str, repo: str) -> str | None:
    """Try each authenticated identity; return first one that can access the repo."""
    identities = get_all_identities()
    if not identities:
        return None
    for identity in identities:
        if can_identity_access(identity, owner, repo):
            return identity
    return None


# ─── Commands ─────────────────────────────────────────────────────────────────

def cmd_add(owner: str, repo: str, identity: str | None, max_prs: int):
    ensure_config_exists()
    data = read_config_raw()
    repos = data.get("repos", [])

    # Check if already present
    for r in repos:
        if r.get("owner") == owner and r.get("name") == repo:
            print(f"Already watching {owner}/{repo} (identity: {r['identity']})")
            return

    if identity is None:
        print(f"Detecting gh identity for {owner}/{repo}...")
        identity = detect_identity(owner, repo)
        if identity is None:
            print(f"Error: no authenticated gh identity can access {owner}/{repo}")
            print("Run `gh auth login` and try again.")
            sys.exit(1)
        print(f"  → using identity: {identity}")

    entry = {"owner": owner, "name": repo, "identity": identity}
    if max_prs != 20:
        entry["max_prs"] = max_prs

    repos.append(entry)
    data["repos"] = repos
    write_config_raw(data)
    print(f"Added {owner}/{repo}  (identity: {identity})")


def cmd_remove(owner: str, repo: str):
    if not CONFIG_PATH.exists():
        print("Config file not found — nothing to remove.")
        return

    data = read_config_raw()
    repos = data.get("repos", [])
    before = len(repos)
    repos = [r for r in repos if not (r.get("owner") == owner and r.get("name") == repo)]

    if len(repos) == before:
        print(f"{owner}/{repo} not found in config.")
        return

    data["repos"] = repos
    write_config_raw(data)
    print(f"Removed {owner}/{repo}")


def cmd_list():
    if not CONFIG_PATH.exists():
        print(f"No config at {CONFIG_PATH}  — run `prctl.py add OWNER/REPO` to get started.")
        return

    data = read_config_raw()
    repos = data.get("repos", [])
    if not repos:
        print("No repos configured. Run: prctl.py add OWNER/REPO")
        return

    # Group by identity
    by_identity: dict[str, list] = {}
    for r in repos:
        by_identity.setdefault(r["identity"], []).append(r)

    for identity, repo_list in by_identity.items():
        print(f"\n[{identity}]")
        for r in repo_list:
            max_pr_str = f"  (max_prs={r['max_prs']})" if r.get("max_prs", 20) != 20 else ""
            print(f"  {r['owner']}/{r['name']}{max_pr_str}")

    print(f"\nConfig: {CONFIG_PATH}")
    print(f"Refresh: {data.get('refresh_interval', 30)}s  "
          f"Size: {data.get('display_size', 'tiny')}  "
          f"Drafts: {data.get('show_drafts', True)}")


# ─── Entry point ──────────────────────────────────────────────────────────────

def parse_repo_arg(s: str) -> tuple[str, str]:
    parts = s.split("/")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        sys.exit(f"Error: expected OWNER/REPO, got: {s!r}")
    return parts[0], parts[1]


def main():
    parser = argparse.ArgumentParser(
        description="Manage which repos pr-monitor watches",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  prctl.py add nthmost/metapub          # auto-detect identity
  prctl.py add orkes-io/conductor       # picks nthmost-orkes automatically
  prctl.py add myorg/repo --identity myuser  # specify identity explicitly
  prctl.py remove nthmost/metapub
  prctl.py list
""",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_add = sub.add_parser("add", help="Add a repo to monitor")
    p_add.add_argument("repo", metavar="OWNER/REPO")
    p_add.add_argument("--identity", default=None,
                       help="gh username to use (auto-detected if omitted)")
    p_add.add_argument("--max-prs", type=int, default=20,
                       help="Max open PRs to fetch (default: 20)")

    p_rm = sub.add_parser("remove", aliases=["rm"], help="Remove a repo from monitoring")
    p_rm.add_argument("repo", metavar="OWNER/REPO")

    sub.add_parser("list", aliases=["ls"], help="List watched repos")

    args = parser.parse_args()

    if args.command == "add":
        owner, repo = parse_repo_arg(args.repo)
        cmd_add(owner, repo, args.identity, args.max_prs)
    elif args.command in ("remove", "rm"):
        owner, repo = parse_repo_arg(args.repo)
        cmd_remove(owner, repo)
    elif args.command in ("list", "ls"):
        cmd_list()


if __name__ == "__main__":
    main()
