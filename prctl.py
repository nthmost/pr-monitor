#!/usr/bin/env python3
"""
prctl - manage which PRs pr-monitor watches

Usage:
    prctl.py add https://github.com/owner/repo/pull/42
    prctl.py add owner/repo#42
    prctl.py remove owner/repo#42
    prctl.py list

The add command auto-detects which gh identity can access the repo.

Config file: ~/.pr-monitor.toml (created if it doesn't exist)
"""

import argparse
import os
import re
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

CONFIG_PATH = Path.home() / ".pr-monitor.toml"

STARTER_CONFIG = """\
# pr-monitor configuration
# Managed by prctl.py — you can also edit this file directly.

refresh_interval = 30
"""

GITHUB_PR_RE = re.compile(r"github\.com/([^/]+)/([^/]+)/pull/(\d+)")
OWNER_REPO_NUM_RE = re.compile(r"^([A-Za-z0-9_.\-]+)/([A-Za-z0-9_.\-]+)#(\d+)$")


# ─── TOML read/write ──────────────────────────────────────────────────────────

def read_config_raw() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    if tomllib is None:
        sys.exit("Error: tomllib not available. pip install tomli")
    with open(CONFIG_PATH, "rb") as f:
        return tomllib.load(f)


def write_config_raw(data: dict):
    lines = []
    for key, value in data.items():
        if key == "prs":
            continue
        if isinstance(value, bool):
            lines.append(f"{key} = {'true' if value else 'false'}")
        elif isinstance(value, str):
            lines.append(f'{key} = "{value}"')
        elif isinstance(value, (int, float)):
            lines.append(f"{key} = {value}")

    for pr in data.get("prs", []):
        lines.append("")
        lines.append("[[prs]]")
        lines.append(f'owner    = "{pr["owner"]}"')
        lines.append(f'repo     = "{pr["repo"]}"')
        lines.append(f'number   = {pr["number"]}')
        lines.append(f'identity = "{pr["identity"]}"')

    with open(CONFIG_PATH, "w") as f:
        f.write("\n".join(lines) + "\n")


def ensure_config_exists():
    if not CONFIG_PATH.exists():
        with open(CONFIG_PATH, "w") as f:
            f.write(STARTER_CONFIG)
        print(f"Created {CONFIG_PATH}")


# ─── gh identity detection ────────────────────────────────────────────────────

def _clean_env() -> dict:
    env = dict(os.environ)
    env.pop("GITHUB_TOKEN", None)
    return env


def get_all_identities() -> list[str]:
    result = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True, env=_clean_env())
    identities = []
    for line in (result.stdout + result.stderr).splitlines():
        line = line.strip()
        if "account" in line and ("✓" in line or "Logged in" in line):
            parts = line.split("account")
            if len(parts) > 1:
                username = parts[1].strip().split()[0]
                identities.append(username)
    return identities


def detect_identity(owner: str, repo: str) -> str | None:
    """Return the identity with push access to the repo, falling back to any read access."""
    read_fallback = None
    for identity in get_all_identities():
        token_result = subprocess.run(
            ["gh", "auth", "token", "--user", identity],
            capture_output=True, text=True, env=_clean_env(),
        )
        if token_result.returncode != 0:
            continue
        env = _clean_env()
        env["GH_TOKEN"] = token_result.stdout.strip()
        result = subprocess.run(
            ["gh", "api", f"/repos/{owner}/{repo}", "--jq", ".permissions.push"],
            capture_output=True, text=True, env=env,
        )
        if result.returncode == 0:
            if result.stdout.strip() == "true":
                return identity          # has push access — best match
            if read_fallback is None:
                read_fallback = identity  # can read, but no push — keep as fallback
    return read_fallback


# ─── Arg parsing ──────────────────────────────────────────────────────────────

def parse_pr_arg(s: str) -> tuple[str, str, int]:
    """Parse a PR URL or owner/repo#number into (owner, repo, number)."""
    m = GITHUB_PR_RE.search(s)
    if m:
        return m.group(1), m.group(2), int(m.group(3))
    m = OWNER_REPO_NUM_RE.match(s)
    if m:
        return m.group(1), m.group(2), int(m.group(3))
    sys.exit(f"Error: expected a GitHub PR URL or owner/repo#number, got: {s!r}")


# ─── Commands ─────────────────────────────────────────────────────────────────

def cmd_add(owner: str, repo: str, number: int, identity: str | None):
    ensure_config_exists()
    data = read_config_raw()
    prs = data.get("prs", [])

    for p in prs:
        if p["owner"] == owner and p["repo"] == repo and p["number"] == number:
            print(f"Already watching {owner}/{repo}#{number}")
            return

    if identity is None:
        print(f"Detecting gh identity for {owner}/{repo}...")
        identity = detect_identity(owner, repo)
        if identity is None:
            print(f"Error: no authenticated gh identity can access {owner}/{repo}")
            sys.exit(1)
        print(f"  → using identity: {identity}")

    prs.append({"owner": owner, "repo": repo, "number": number, "identity": identity})
    data["prs"] = prs
    write_config_raw(data)
    print(f"Added {owner}/{repo}#{number}  (identity: {identity})")


def cmd_remove(owner: str, repo: str, number: int):
    if not CONFIG_PATH.exists():
        print("Config file not found.")
        return
    data = read_config_raw()
    prs = data.get("prs", [])
    before = len(prs)
    prs = [p for p in prs if not (p["owner"] == owner and p["repo"] == repo and p["number"] == number)]
    if len(prs) == before:
        print(f"{owner}/{repo}#{number} not found in config.")
        return
    data["prs"] = prs
    write_config_raw(data)
    print(f"Removed {owner}/{repo}#{number}")


def cmd_list():
    if not CONFIG_PATH.exists():
        print(f"No config at {CONFIG_PATH} — run `prctl.py add <PR URL>` to get started.")
        return
    data = read_config_raw()
    prs = data.get("prs", [])
    if not prs:
        print("No PRs configured. Run: prctl.py add <GitHub PR URL>")
        return
    by_identity: dict[str, list] = {}
    for p in prs:
        by_identity.setdefault(p["identity"], []).append(p)
    for identity, pr_list in by_identity.items():
        print(f"\n[{identity}]")
        for p in pr_list:
            print(f"  {p['owner']}/{p['repo']}#{p['number']}")
    print(f"\nConfig: {CONFIG_PATH}")
    print(f"Refresh: {data.get('refresh_interval', 30)}s")


# ─── Entry point ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Manage which PRs pr-monitor watches",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  prctl.py add https://github.com/nthmost/metapub/pull/42
  prctl.py add conductor-oss/conductor#1001
  prctl.py add conductor-oss/conductor#1001 --identity nthmost-orkes
  prctl.py remove conductor-oss/conductor#1001
  prctl.py list
""",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_add = sub.add_parser("add", help="Watch a specific PR")
    p_add.add_argument("pr", metavar="PR_URL or OWNER/REPO#NUMBER")
    p_add.add_argument("--identity", default=None)

    p_rm = sub.add_parser("remove", aliases=["rm"], help="Stop watching a PR")
    p_rm.add_argument("pr", metavar="PR_URL or OWNER/REPO#NUMBER")

    sub.add_parser("list", aliases=["ls"], help="List watched PRs")

    args = parser.parse_args()

    if args.command == "add":
        owner, repo, number = parse_pr_arg(args.pr)
        cmd_add(owner, repo, number, args.identity)
    elif args.command in ("remove", "rm"):
        owner, repo, number = parse_pr_arg(args.pr)
        cmd_remove(owner, repo, number)
    elif args.command in ("list", "ls"):
        cmd_list()


if __name__ == "__main__":
    main()
