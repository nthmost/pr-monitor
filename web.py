#!/usr/bin/env python3
"""
pr-monitor web UI — configure which PRs to watch via a browser.

Paste GitHub PR URLs to add them. All of these work:
  https://github.com/nthmost/metapub/pull/42
  https://github.com/orkes-io/conductor/pull/1001

Usage:
    python3 web.py          # opens on http://localhost:7842
    python3 web.py --port 8080
"""

import argparse
import sys
from flask import Flask, redirect, render_template_string, request, url_for

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from prctl import (
    read_config_raw, write_config_raw, ensure_config_exists,
    detect_identity, get_all_identities,
    GITHUB_PR_RE, OWNER_REPO_NUM_RE,
    CONFIG_PATH,
)

app = Flask(__name__)


def parse_pr_input(text: str) -> list[tuple[str, str, int]]:
    """Parse a block of text into (owner, repo, number) tuples."""
    seen = set()
    results = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = GITHUB_PR_RE.search(line) or OWNER_REPO_NUM_RE.match(line)
        if m:
            owner, repo, number = m.group(1), m.group(2), int(m.group(3))
            key = (owner.lower(), repo.lower(), number)
            if key not in seen:
                seen.add(key)
                results.append((owner, repo, number))
    return results


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    data = read_config_raw()
    return render_template_string(HTML,
        prs=data.get("prs", []),
        identities=get_all_identities(),
        config_path=str(CONFIG_PATH),
        refresh=data.get("refresh_interval", 30),
    )


@app.route("/add", methods=["POST"])
def add_prs():
    raw_input = request.form.get("prs_input", "").strip()
    identity_override = request.form.get("identity", "").strip() or None

    parsed = parse_pr_input(raw_input)
    if not parsed:
        return redirect(url_for("index") + "?msg=Could+not+parse+any+PR+URLs+from+input")

    ensure_config_exists()
    data = read_config_raw()
    existing = {(p["owner"].lower(), p["repo"].lower(), p["number"]) for p in data.get("prs", [])}
    prs = data.get("prs", [])
    added, skipped, errors = [], [], []

    for owner, repo, number in parsed:
        key = (owner.lower(), repo.lower(), number)
        if key in existing:
            skipped.append(f"{owner}/{repo}#{number}")
            continue
        identity = identity_override or detect_identity(owner, repo)
        if identity is None:
            errors.append(f"{owner}/{repo}#{number}")
            continue
        prs.append({"owner": owner, "repo": repo, "number": number, "identity": identity})
        existing.add(key)
        added.append(f"{owner}/{repo}#{number}")

    data["prs"] = prs
    write_config_raw(data)

    parts = []
    if added:    parts.append("Added: " + ", ".join(added))
    if skipped:  parts.append("Already watching: " + ", ".join(skipped))
    if errors:   parts.append("Could not access: " + ", ".join(errors))
    msg = " | ".join(parts) or "No changes"
    return redirect(url_for("index") + f"?msg={msg.replace(' ', '+')}")


@app.route("/remove", methods=["POST"])
def remove_pr():
    owner  = request.form.get("owner", "")
    repo   = request.form.get("repo", "")
    number = int(request.form.get("number", 0))
    data = read_config_raw()
    data["prs"] = [p for p in data.get("prs", [])
                   if not (p["owner"] == owner and p["repo"] == repo and p["number"] == number)]
    write_config_raw(data)
    return redirect(url_for("index") + f"?msg=Removed+{owner}/{repo}%23{number}")


@app.route("/settings", methods=["POST"])
def update_settings():
    data = read_config_raw()
    try:
        data["refresh_interval"] = int(request.form.get("refresh_interval", 30))
    except ValueError:
        pass
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
  :root { --bg:#0d1117; --surface:#161b22; --border:#30363d; --text:#e6edf3;
          --muted:#8b949e; --accent:#58a6ff; --green:#3fb950; --red:#f85149;
          --radius:6px; --font:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }
  * { box-sizing:border-box; margin:0; padding:0; }
  body { background:var(--bg); color:var(--text); font-family:var(--font);
         font-size:14px; line-height:1.5; padding:24px; }
  h1 { font-size:20px; font-weight:600; margin-bottom:4px; }
  h2 { font-size:13px; font-weight:600; color:var(--muted); text-transform:uppercase;
       letter-spacing:.05em; margin-bottom:12px; }
  a { color:var(--accent); text-decoration:none; }
  .layout { max-width:760px; margin:0 auto; }
  .header { display:flex; align-items:baseline; gap:12px; margin-bottom:24px; }
  .header .sub { color:var(--muted); font-size:12px; }
  .card { background:var(--surface); border:1px solid var(--border);
          border-radius:var(--radius); padding:16px; margin-bottom:16px; }
  .flash { padding:10px 14px; border-radius:var(--radius); margin-bottom:16px; font-size:13px; }
  .flash.ok  { background:#1c2d1e; border:1px solid var(--green); color:var(--green); }
  .flash.err { background:#2d1c1c; border:1px solid var(--red);   color:var(--red); }
  textarea { width:100%; min-height:100px; background:var(--bg); border:1px solid var(--border);
             border-radius:var(--radius); color:var(--text); font-family:monospace;
             font-size:13px; padding:10px; resize:vertical; }
  textarea:focus { outline:none; border-color:var(--accent); }
  textarea::placeholder { color:var(--muted); }
  .row { display:flex; gap:10px; align-items:flex-end; margin-top:10px; flex-wrap:wrap; }
  select, input[type=number] { background:var(--bg); border:1px solid var(--border);
    border-radius:var(--radius); color:var(--text); padding:6px 10px; font-size:13px; height:32px; }
  label { font-size:12px; color:var(--muted); display:block; margin-bottom:4px; }
  .btn { display:inline-flex; align-items:center; padding:6px 14px; border-radius:var(--radius);
         font-size:13px; font-weight:500; border:none; cursor:pointer; height:32px; }
  .btn-primary { background:var(--accent); color:#0d1117; }
  .btn-primary:hover { background:#79c0ff; }
  .btn-danger  { background:transparent; color:var(--red); border:1px solid var(--border); }
  .btn-danger:hover { border-color:var(--red); }
  .btn-subtle  { background:transparent; color:var(--muted); border:1px solid var(--border); }
  .btn-subtle:hover { color:var(--text); }
  .pr-list { display:flex; flex-direction:column; gap:2px; }
  .pr-row { display:flex; align-items:center; gap:10px; padding:8px 10px;
            border-radius:var(--radius); }
  .pr-row:hover { background:var(--bg); }
  .pr-link { flex:1; font-family:monospace; }
  .pr-link a { color:var(--text); }
  .pr-link a:hover { color:var(--accent); }
  .tag { font-size:11px; padding:1px 7px; border-radius:20px;
         background:var(--bg); border:1px solid var(--border); color:var(--muted); }
  .empty { color:var(--muted); font-size:13px; padding:8px 0; }
  .hint { font-size:12px; color:var(--muted); margin-top:6px; }
  .config-path { font-size:11px; color:var(--muted); font-family:monospace; margin-top:8px; }
</style>
</head>
<body>
<div class="layout">
  <div class="header">
    <h1>pr-monitor</h1>
    <span class="sub">PRs to watch in claude-monitor</span>
  </div>

  {% set m = request.args.get('msg', '') %}
  {% if m %}
    <div class="flash {{ 'err' if 'Could not' in m else 'ok' }}">{{ m }}</div>
  {% endif %}

  <div class="card">
    <h2>Add PRs</h2>
    <form action="/add" method="post">
      <textarea name="prs_input" placeholder="Paste GitHub PR URLs — one per line:

https://github.com/nthmost/metapub/pull/42
https://github.com/orkes-io/conductor/pull/1001"></textarea>
      <div class="row">
        <div>
          <label>Identity (auto-detected if blank)</label>
          <select name="identity">
            <option value="">auto-detect</option>
            {% for id in identities %}<option value="{{ id }}">{{ id }}</option>{% endfor %}
          </select>
        </div>
        <button type="submit" class="btn btn-primary">Add</button>
      </div>
    </form>
    <p class="hint">Paste one or more GitHub PR URLs. Multiple lines OK.</p>
  </div>

  <div class="card">
    <h2>Watching ({{ prs|length }})</h2>
    {% if prs %}
      <div class="pr-list">
        {% for p in prs %}
        <div class="pr-row">
          <span class="pr-link">
            <a href="https://github.com/{{ p.owner }}/{{ p.repo }}/pull/{{ p.number }}" target="_blank">
              {{ p.owner }}/{{ p.repo }}#{{ p.number }}
            </a>
          </span>
          <span class="tag">{{ p.identity }}</span>
          <form action="/remove" method="post" style="display:inline">
            <input type="hidden" name="owner"  value="{{ p.owner }}">
            <input type="hidden" name="repo"   value="{{ p.repo }}">
            <input type="hidden" name="number" value="{{ p.number }}">
            <button type="submit" class="btn btn-danger">Remove</button>
          </form>
        </div>
        {% endfor %}
      </div>
    {% else %}
      <p class="empty">No PRs yet. Paste some URLs above.</p>
    {% endif %}
  </div>

  <div class="card">
    <h2>Settings</h2>
    <form action="/settings" method="post">
      <div class="row">
        <div>
          <label>Refresh interval (seconds)</label>
          <input type="number" name="refresh_interval" value="{{ refresh }}"
                 min="10" max="300" style="width:80px">
        </div>
        <button type="submit" class="btn btn-subtle">Save</button>
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
