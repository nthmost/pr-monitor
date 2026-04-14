#!/usr/bin/env bash
# install.sh — install pr-monitor as a local service with Apache proxy routing
#
# Run once (and re-run whenever you add a new service config to apache/):
#   sudo ./install.sh
#
# What it does:
#   1. Enables mod_proxy + mod_proxy_http in /etc/apache2/httpd.conf
#   2. Copies apache/*.conf to /etc/apache2/other/
#   3. Adds /etc/hosts entries for each service hostname
#   4. Validates and restarts Apache
#
# The Flask web UI runs as your user via launchd (see below — no sudo needed for that).
# To add a new service:
#   1. Add apache/myservice.localhost.conf  (copy pr-monitor.localhost.conf as a template)
#   2. Add an add_host "myservice.localhost" line in this script
#   3. Re-run: sudo ./install.sh

set -euo pipefail

APACHE_CONF=/etc/apache2/httpd.conf
APACHE_OTHER=/etc/apache2/other
HOSTS=/etc/hosts
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ $EUID -ne 0 ]]; then
    echo "Run with sudo: sudo $0"
    exit 1
fi

# ── 1. Enable proxy modules ───────────────────────────────────────────────────

enable_module() {
    local pattern="$1"
    if grep -q "^#LoadModule ${pattern}" "$APACHE_CONF"; then
        sed -i '' "s|^#LoadModule ${pattern}|LoadModule ${pattern}|" "$APACHE_CONF"
        echo "  enabled: LoadModule $pattern"
    else
        echo "  already enabled: $(echo "$pattern" | cut -d' ' -f1)"
    fi
}

echo "→ Enabling Apache proxy modules..."
enable_module "proxy_module libexec/apache2/mod_proxy.so"
enable_module "proxy_http_module libexec/apache2/mod_proxy_http.so"

# Suppress "ServerName not set" warning if not already configured
if ! grep -qE "^ServerName[[:space:]]" "$APACHE_CONF"; then
    printf '\nServerName localhost\n' >> "$APACHE_CONF"
    echo "  added: ServerName localhost"
fi

# ── 2. Install vhost configs ──────────────────────────────────────────────────

echo "→ Installing vhost configs to $APACHE_OTHER..."
for conf in "$SCRIPT_DIR"/apache/*.conf; do
    name="$(basename "$conf")"
    cp "$conf" "$APACHE_OTHER/$name"
    echo "  installed: $name"
done

# ── 3. /etc/hosts entries ─────────────────────────────────────────────────────

add_host() {
    local hostname="$1"
    if grep -qE "^127\.0\.0\.1[[:space:]].*\b${hostname}\b" "$HOSTS"; then
        echo "  already present: $hostname"
    else
        printf '127.0.0.1  %s\n' "$hostname" >> "$HOSTS"
        echo "  added: $hostname"
    fi
}

echo "→ Updating /etc/hosts..."
# ── add service hostnames here ────────────────────────
add_host "pr-monitor.localhost"
# add_host "myservice.localhost"
# ──────────────────────────────────────────────────────

# ── 4. Validate + restart Apache ──────────────────────────────────────────────

echo "→ Validating Apache config..."
apachectl configtest

echo "→ Restarting Apache..."
# 'restart' fails if Apache isn't running yet; fall back to 'start'
apachectl restart 2>/dev/null || apachectl start

echo ""
echo "✓ Done."
echo ""
echo "  Services:"
echo "    http://pr-monitor.localhost  →  http://127.0.0.1:7842"
echo ""
echo "  Start the Flask web UI (run as yourself, not sudo):"
echo "    launchctl load ~/Library/LaunchAgents/com.nthmost.pr-monitor-web.plist"
echo ""
echo "  Or just run it directly:"
echo "    python3 $SCRIPT_DIR/web.py --no-open"
