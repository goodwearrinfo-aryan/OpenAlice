#!/bin/bash
# Supervised launcher for OpenAlice — run by launchd (com.aryan.openalice).
# Keeps the full dev stack up, re-opens the demo paper position if flat, and
# runs the real-BTC P&L ticker. launchd KeepAlive restarts this whole wrapper
# on crash or reboot, so the live dashboard self-heals.
export PATH="$HOME/.nvm/versions/node/v22.22.3/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export OPENALICE_HOME="$HOME/.openalice"
export OPENALICE_UI_PORT=3002
APP="$HOME/openalice"
ID="mock-simulator-cb1d7528"
T="http://127.0.0.1:47333/api/trading"
S="http://127.0.0.1:47333/api/simulator"
LOG=/tmp/openalice.log
cd "$APP" || exit 1

# free our ports from any stale holder before starting (our ports only)
for p in 3002 47331 47332 47333; do
  pid=$(lsof -nP -iTCP:$p -sTCP:LISTEN 2>/dev/null | awk 'NR==2{print $2}')
  [ -n "$pid" ] && kill -9 "$pid" 2>/dev/null
done
sleep 1

echo "[supervise] $(date) starting pnpm dev" >> "$LOG"
pnpm dev >> "$LOG" 2>&1 &
DEV=$!

# disciplined legs paper runner (writes ui/public/disciplined.json for the tab)
pkill -f disciplined_live.py 2>/dev/null
python3 "$APP/disciplined_live.py" >> /tmp/oa_disciplined.log 2>&1 &

# Post-start worker: wait for UTA, re-open position if flat, then tick P&L.
(
  for i in $(seq 1 40); do
    curl -s -m4 "$T/uta/$ID/account" 2>/dev/null | grep -q totalCashValue && break
    sleep 2
  done
  np=$(curl -s -m5 "$T/uta/$ID/positions" 2>/dev/null | python3 -c "import sys,json;print(len(json.load(sys.stdin).get('positions',[])))" 2>/dev/null)
  if [ "${np:-0}" = "0" ]; then
    BTC=$(curl -s -m6 'https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT' | python3 -c "import sys,json;print(json.load(sys.stdin)['price'])" 2>/dev/null)
    if [ -n "$BTC" ]; then
      curl -s -m5 -X POST "$S/uta/$ID/mark-price" -H 'Content-Type: application/json' -d "{\"nativeKey\":\"BTC\",\"price\":\"$BTC\"}" >/dev/null 2>&1
      curl -s -m8 -X POST "$T/uta/$ID/wallet/place-order" -H 'Content-Type: application/json' \
        -d "{\"aliceId\":\"$ID|BTC\",\"symbol\":\"BTC\",\"action\":\"BUY\",\"orderType\":\"MKT\",\"totalQuantity\":\"10\",\"tif\":\"DAY\",\"message\":\"supervised boot re-open\"}" >/dev/null 2>&1
      echo "[supervise] $(date) re-opened long 10 BTC @ $BTC" >> "$LOG"
    fi
  fi
  # real-BTC -> sim mark -> P&L, every 15s, while the backend lives
  while kill -0 "$DEV" 2>/dev/null; do
    BTC=$(curl -s -m6 'https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT' | python3 -c "import sys,json;print(json.load(sys.stdin)['price'])" 2>/dev/null)
    [ -z "$BTC" ] && BTC=$(curl -s -m6 'https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd' | python3 -c "import sys,json;print(json.load(sys.stdin)['bitcoin']['usd'])" 2>/dev/null)
    if [ -n "$BTC" ]; then
      curl -s -m5 -X POST "$S/uta/$ID/mark-price" -H 'Content-Type: application/json' -d "{\"nativeKey\":\"BTC\",\"price\":\"$BTC\"}" >/dev/null 2>&1
      U=$(curl -s -m5 "$T/uta/$ID/account" | python3 -c "import sys,json;print(json.load(sys.stdin).get('unrealizedPnL','?'))" 2>/dev/null)
      printf '%s  BTC=%s  uPnL=$%s\n' "$(date +%H:%M:%S)" "$BTC" "$U" >> /tmp/oa_live_pnl.log
    fi
    sleep 15
  done
) &

wait "$DEV"
echo "[supervise] $(date) pnpm dev exited — launchd will restart" >> "$LOG"
