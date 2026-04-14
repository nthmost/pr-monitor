#!/usr/bin/env python3
"""
pr-monitor web UI — configure which repos to watch via a browser.

Paste GitHub PR URLs, repo URLs, or owner/repo strings to add repos.
All formats are accepted:
  https://github.com/nthmost/metapub/pull/42
  https://github.com/nthmost/metapub
  nthmost/metapub

Usage:
    python3 web.py          # opens on http://localhost:7842
    python3 web.py --port 8080
"""

import argparse
import re
import sys
from flask import Flask, jsonify, redirect, render_template_string, request, url_for

# Import prctl helpers directly
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from prctl import (
    read_config_raw, write_config_raw, ensure_config_exists,
    detect_identity, get_all_identities, can_identity_access,
    CONFIG_PATH,
)

app = Flask(__name__)

# ─── URL / string parsing ─────────────────────────────────────────────────────

GITHUB_URL_RE = re.compile(
    r"github\.com/([^/\s]+)/([^/\s#?]+)"
)
OWNER_REPO_RE = re.compile(r"^([A-Za-z0-9_.\-]+)/([A-Za-z0-9_.\-]+)$")


def parse_repo_input(text: str) -> list[tuple[str, str]]:
    """
    Parse a block of text containing GitHub URLs or owner/repo strings.
    Returns list of (owner, repo) tuples, deduplicated.
    """
    seen = set()
    results = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Try GitHub URL first
        m = GITHUB_URL_RE.search(line)
        if m:
            owner, repo = m.group(1), m.group(2)
            key = (owner.lower(), repo.lower())
            if key not in seen:
                seen.add(key)
                results.append((owner, repo))
            continue
        # Try bare owner/repo
        m = OWNER_REPO_RE.match(line)
        if m:
            owner, repo = m.group(1), m.group(2)
            key = (owner.lower(), repo.lower())
            if key not in seen:
                seen.add(key)
                results.append((owner, repo))
    return results


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    data = read_config_raw()
    repos = data.get("repos", [])
    identities = get_all_identities()
    return render_template_string(HTML, repos=repos, identities=identities,
                                  config_path=str(CONFIG_PATH),
                                  refresh=data.get("refresh_interval", 30),
                                  show_drafts=data.get("show_drafts", True))


@app.route("/add", methods=["POST"])
def add_repos():
    raw_input = request.form.get("repos_input", "").strip()
    identity_override = request.form.get("identity", "").strip() or None

    parsed = parse_repo_input(raw_input)
    if not parsed:
        return redirect(url_for("index") + "?error=Could+not+parse+any+repos+from+input")

    ensure_config_exists()
    data = read_config_raw()
    existing = {(r["owner"].lower(), r["name"].lower()) for r in data.get("repos", [])}
    repos = data.get("repos", [])

    added = []
    skipped = []
    errors = []

    for owner, repo in parsed:
        key = (owner.lower(), repo.lower())
        if key in existing:
            skipped.append(f"{owner}/{repo}")
            continue
        identity = identity_override
        if identity is None:
            identity = detect_identity(owner, repo)
        if identity is None:
            errors.append(f"{owner}/{repo} (no identity can access it)")
            continue
        repos.append({"owner": owner, "name": repo, "identity": identity})
        existing.add(key)
        added.append(f"{owner}/{repo}")

    data["repos"] = repos
    write_config_raw(data)

    msg_parts = []
    if added:
        msg_parts.append("Added: " + ", ".join(added))
    if skipped:
        msg_parts.append("Already watching: " + ", ".join(skipped))
    if errors:
        msg_parts.append("Could not access: " + ", ".join(errors))

    msg = " | ".join(msg_parts) or "No changes"
    return redirect(url_for("index") + f"?msg={msg.replace(' ', '+')}")


@app.route("/remove", methods=["POST"])
def remove_repo():
    owner = request.form.get("owner", "")
    repo = request.form.get("name", "")
    data = read_config_raw()
    repos = data.get("repos", [])
    data["repos"] = [r for r in repos
                     if not (r["owner"] == owner and r["name"] == repo)]
    write_config_raw(data)
    return redirect(url_for("index") + f"?msg=Removed+{owner}/{repo}")


@app.route("/settings", methods=["POST"])
def update_settings():
    data = read_config_raw()
    try:
        data["refresh_interval"] = int(request.form.get("refresh_interval", 30))
    except ValueError:
        pass
    data["show_drafts"] = request.form.get("show_drafts") == "on"
    ensure_config_exists()
    write_config_raw(data)
    return redirect(url_for("index") + "?msg=Settings+saved")


# ─── HTML template ────────────────────────────────────────────────────────────

HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>pr-monitor</title>
<style>
  :root {
    --bg: #0d1117;
    --surface: #161b22;
    --border: #30363d;
    --text: #e6edf3;
    --muted: #8b949e;
    --accent: #58a6ff;
    --green: #3fb950;
    --red: #f85149;
    --yellow: #d29922;
    --radius: 6px;
    --font: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: var(--bg); color: var(--text); font-family: var(--font);
         font-size: 14px; line-height: 1.5; padding: 24px; }
  h1 { font-size: 20px; font-weight: 600; margin-bottom: 4px; }
  h2 { font-size: 14px; font-weight: 600; color: var(--muted);
       text-transform: uppercase; letter-spacing: .05em; margin-bottom: 12px; }
  a { color: var(--accent); text-decoration: none; }
  .layout { max-width: 860px; margin: 0 auto; }
  .header { display: flex; align-items: baseline; gap: 12px; margin-bottom: 24px; }
  .header .sub { color: var(--muted); font-size: 12px; }
  .card { background: var(--surface); border: 1px solid var(--border);
          border-radius: var(--radius); padding: 16px; margin-bottom: 16px; }
  .flash { padding: 10px 14px; border-radius: var(--radius); margin-bottom: 16px;
           font-size: 13px; }
  .flash.ok  { background: #1c2d1e; border: 1px solid var(--green); color: var(--green); }
  .flash.err { background: #2d1c1c; border: 1px solid var(--red);   color: var(--red); }
  textarea {
    width: 100%; min-height: 110px; background: var(--bg); border: 1px solid var(--border);
    border-radius: var(--radius); color: var(--text); font-family: monospace;
    font-size: 13px; padding: 10px; resize: vertical;
  }
  textarea:focus { outline: none; border-color: var(--accent); }
  textarea::placeholder { color: var(--muted); }
  .row { display: flex; gap: 10px; align-items: flex-end; margin-top: 10px; flex-wrap: wrap; }
  select, input[type=number], input[type=text] {
    background: var(--bg); border: 1px solid var(--border); border-radius: var(--radius);
    color: var(--text); padding: 6px 10px; font-size: 13px; height: 32px;
  }
  select:focus, input:focus { outline: none; border-color: var(--accent); }
  label { font-size: 12px; color: var(--muted); display: block; margin-bottom: 4px; }
  .btn {
    display: inline-flex; align-items: center; gap: 6px;
    padding: 6px 14px; border-radius: var(--radius); font-size: 13px; font-weight: 500;
    border: none; cursor: pointer; height: 32px; white-space: nowrap;
  }
  .btn-primary { background: var(--accent); color: #0d1117; }
  .btn-primary:hover { background: #79c0ff; }
  .btn-danger  { background: transparent; color: var(--red);
                 border: 1px solid var(--border); }
  .btn-danger:hover  { border-color: var(--red); }
  .btn-subtle  { background: transparent; color: var(--muted);
                 border: 1px solid var(--border); }
  .btn-subtle:hover  { color: var(--text); border-color: var(--text); }
  .repo-list { display: flex; flex-direction: column; gap: 2px; }
  .repo-row {
    display: flex; align-items: center; gap: 10px;
    padding: 8px 10px; border-radius: var(--radius);
  }
  .repo-row:hover { background: var(--bg); }
  .repo-name { flex: 1; font-family: monospace; }
  .repo-name a { color: var(--text); }
  .repo-name a:hover { color: var(--accent); }
  .tag {
    font-size: 11px; padding: 1px 7px; border-radius: 20px;
    background: var(--bg); border: 1px solid var(--border); color: var(--muted);
  }
  .empty { color: var(--muted); font-size: 13px; padding: 12px 0; }
  .settings-row { display: flex; gap: 20px; flex-wrap: wrap; align-items: flex-end; }
  .field { display: flex; flex-direction: column; gap: 4px; }
  .checkbox-row { display: flex; align-items: center; gap: 8px; padding-bottom: 6px; }
  input[type=checkbox] { accent-color: var(--accent); width: 15px; height: 15px; }
  .config-path { font-size: 11px; color: var(--muted); font-family: monospace; margin-top: 4px; }
  .hint { font-size: 12px; color: var(--muted); margin-top: 6px; }
  hr { border: none; border-top: 1px solid var(--border); margin: 16px 0; }
</style>
</head>
<body>
<div class="layout">

  <div class="header">
    <h1>pr-monitor</h1>
    <span class="sub">configure repos to watch</span>
  </div>

  {% set qs = request.args %}
  {% if qs.get('msg') %}
    {% set m = qs.get('msg') %}
    {% if 'error' in qs or 'Could not' in m or 'no identity' in m %}
      <div class="flash err">{{ m }}</div>
    {% else %}
      <div class="flash ok">{{ m }}</div>
    {% endif %}
  {% endif %}

  <!-- Add repos -->
  <div class="card">
    <h2>Add repos to watch</h2>
    <form action="/add" method="post">
      <textarea name="repos_input" placeholder="Paste GitHub URLs or owner/repo — one per line:

https://github.com/nthmost/metapub/pull/42
https://github.com/orkes-io/conductor
myorg/myrepo"></textarea>
      <div class="row">
        <div>
          <label>Identity (optional — auto-detected if blank)</label>
          <select name="identity">
            <option value="">auto-detect</option>
            {% for id in identities %}
              <option value="{{ id }}">{{ id }}</option>
            {% endfor %}
          </select>
        </div>
        <button type="submit" class="btn btn-primary">Add</button>
      </div>
    </form>
    <p class="hint">Paste PR URLs, repo URLs, or <code>owner/repo</code> strings. Multiple lines OK.</p>
  </div>

  <!-- Watched repos -->
  <div class="card">
    <h2>Watched repos ({{ repos|length }})</h2>
    {% if repos %}
      <div class="repo-list">
        {% for r in repos %}
        <div class="repo-row">
          <span class="repo-name">
            <a href="https://github.com/{{ r.owner }}/{{ r.name }}" target="_blank">
              {{ r.owner }}/{{ r.name }}
            </a>
          </span>
          <span class="tag">{{ r.identity }}</span>
          {% if r.get('max_prs', 20) != 20 %}
            <span class="tag">max {{ r.max_prs }} PRs</span>
          {% endif %}
          <form action="/remove" method="post" style="display:inline">
            <input type="hidden" name="owner" value="{{ r.owner }}">
            <input type="hidden" name="name"  value="{{ r.name }}">
            <button type="submit" class="btn btn-danger">Remove</button>
          </form>
        </div>
        {% endfor %}
      </div>
    {% else %}
      <p class="empty">No repos configured yet. Paste some above.</p>
    {% endif %}
  </div>

  <!-- Settings -->
  <div class="card">
    <h2>Settings</h2>
    <form action="/settings" method="post">
      <div class="settings-row">
        <div class="field">
          <label>Refresh interval (seconds)</label>
          <input type="number" name="refresh_interval" value="{{ refresh }}" min="10" max="300" style="width:90px">
        </div>
        <div class="field">
          <label>&nbsp;</label>
          <div class="checkbox-row">
            <input type="checkbox" name="show_drafts" id="show_drafts"
                   {% if show_drafts %}checked{% endif %}>
            <label for="show_drafts" style="margin:0;color:var(--text)">Show draft PRs</label>
          </div>
        </div>
        <div class="field">
          <label>&nbsp;</label>
          <button type="submit" class="btn btn-subtle">Save settings</button>
        </div>
      </div>
    </form>
    <p class="config-path">{{ config_path }}</p>
  </div>

</div>
</body>
</html>
"""


# ─── Entry point ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="pr-monitor web UI")
    parser.add_argument("--port", type=int, default=7842)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--no-open", action="store_true", help="Don't open browser")
    args = parser.parse_args()

    if not args.no_open:
        import threading, webbrowser
        url = f"http://{args.host}:{args.port}"
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
        print(f"Opening {url}")

    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
