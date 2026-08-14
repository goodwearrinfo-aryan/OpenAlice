#!/usr/bin/env bash
# OpenAlice LAN Access Runner
# Usage: ./run-lan.sh [mode]
# Modes: auth (default), noauth, tailscale, reverse-proxy

set -euo pipefail

cd "$(dirname "$0")"

MODE="${1:-auth}"

echo "🚀 OpenAlice LAN Access - Mode: $MODE"
echo ""

case "$MODE" in
  auth)
    echo "🔐 Auth-enabled LAN access"
    echo "   1. First run: generates admin token (run once, copy token)"
    echo "   2. Subsequent runs: use token at http://<LAN-IP>:47331"
    echo ""
    if [ ! -f ~/.openalice/data/config/auth.json ]; then
      echo "📝 No auth token found - running FIRST TIME setup..."
      echo "   Copy the token below, then Ctrl+C and re-run with same mode."
      echo ""
      OPENALICE_BIND_HOST=127.0.0.1 pnpm dev
    else
      echo "✅ Auth token exists - starting with LAN bind..."
      exec pnpm dev
    fi
    ;;

  noauth)
    echo "🔓 No-auth LAN access (trusted network only!)"
    echo "   Access at: http://<LAN-IP>:47331"
    echo ""
    OPENALICE_DISABLE_AUTH=1 exec pnpm dev
    ;;

  tailscale)
    echo "🌐 Tailscale HTTPS access"
    echo "   Requires: tailscale installed and logged in"
    echo "   Will serve at: https://<your-tailnet-name>.ts.net"
    echo ""
    # Start Alice on localhost
    pnpm dev &
    ALICE_PID=$!
    sleep 3
    # Start Tailscale serve
    echo "Starting Tailscale serve..."
    tailscale serve --https=443 --bg http://localhost:47331
    echo ""
    echo "✅ OpenAlice available at: https://$(tailscale status --json | jq -r '.Self.DNSName' | sed 's/\.$//')"
    echo "   Press Ctrl+C to stop both"
    wait $ALICE_PID
    ;;

  reverse-proxy)
    echo "🔀 Reverse proxy mode (Caddy/nginx)"
    echo "   Set OPENALICE_TRUSTED_PROXIES to your proxy IP"
    echo "   Example: OPENALICE_TRUSTED_PROXIES=127.0.0.1 $0 reverse-proxy"
    echo ""
    exec pnpm dev
    ;;

  *)
    echo "Usage: $0 [auth|noauth|tailscale|reverse-proxy]"
    echo ""
    echo "Modes:"
    echo "  auth           - Auth enabled (default), generates token on first run"
    echo "  noauth         - No auth, open on LAN (trusted networks only)"
    echo "  tailscale      - Tailscale HTTPS (best for remote access)"
    echo "  reverse-proxy  - Behind Caddy/nginx with TLS termination"
    exit 1
    ;;
esac
