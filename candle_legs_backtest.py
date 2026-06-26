#!/usr/bin/env python3
"""Honest, no-lookahead backtest of the 4 candle legs on real Binance BTC klines.
Each leg: state machine (flat -> enter on signal -> exit on max_hold or opposite).
Win = trade closed with positive return in its own direction. Compares to buy&hold.
Reuses the bot's own signal definitions (RSI14, EMA20/50, MACD 12/26/9, 24h change)."""
import json, urllib.request, sys

def fetch(symbol="BTCUSDT", interval="1h", limit=1000):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    data = json.load(urllib.request.urlopen(req, timeout=20))
    return [float(k[4]) for k in data]  # close prices

def ema_series(vals, p):
    """EMA aligned to vals index (None until enough data)."""
    out = [None] * len(vals)
    if len(vals) < p: return out
    k = 2.0 / (p + 1); e = sum(vals[:p]) / p; out[p-1] = e
    for i in range(p, len(vals)):
        e = vals[i] * k + e * (1 - k); out[i] = e
    return out

def rsi_at(closes, i, p=14):
    if i < p: return 50.0
    gains = losses = 0.0
    for j in range(i - p + 1, i + 1):
        d = closes[j] - closes[j-1]
        gains += max(d, 0); losses += max(-d, 0)
    if losses == 0: return 100.0
    rs = (gains / p) / (losses / p)
    return 100 - 100 / (1 + rs)

def backtest(closes, leg):
    e20, e50 = ema_series(closes, 20), ema_series(closes, 50)
    macd_l = [ (a - b) if (a is not None and b is not None) else None
               for a, b in zip(ema_series(closes, 12), ema_series(closes, 26)) ]
    msig = ema_series([m for m in macd_l if m is not None], 9)
    # pad macd signal back to full length
    pad = len(closes) - len([m for m in macd_l if m is not None])
    macd_s = [None]*pad + msig

    trades = []          # (dir, entry, exit)
    pos = None           # (dir, entry_price, entry_i)
    HOLD = {"candlesig": 8, "macdsig": 8, "coinrev": 24, "diverg": 8}[leg]

    for i in range(55, len(closes)):
        px = closes[i]
        sig = 0
        if leg == "candlesig":                       # RSI pullback inside EMA trend
            r = rsi_at(closes, i)
            if e20[i] and e50[i]:
                if r < 45 and e20[i] > e50[i]*1.002: sig = 1
                elif r > 55 and e20[i] < e50[i]*0.998: sig = -1
        elif leg == "macdsig":                        # MACD mean-reversion + stretch from EMA20
            if e20[i] and macd_l[i] is not None and macd_s[i] is not None:
                dev = px / e20[i] - 1
                if dev < -0.015 and macd_l[i] > macd_s[i]: sig = 1
                elif dev > 0.015 and macd_l[i] < macd_s[i]: sig = -1
        elif leg == "coinrev":                        # fade a >7% 24h move
            if i >= 24:
                chg = closes[i]/closes[i-24] - 1
                if chg < -0.07: sig = 1
                elif chg > 0.07: sig = -1
        elif leg == "diverg":                         # price vs RSI(14) divergence over 12 bars
            if i >= 12:
                r_now, r_prev = rsi_at(closes, i), rsi_at(closes, i-12)
                if closes[i] < closes[i-12] and r_now > r_prev: sig = 1   # bullish div
                elif closes[i] > closes[i-12] and r_now < r_prev: sig = -1  # bearish div

        if pos is None:
            if sig != 0: pos = (sig, px, i)
        else:
            d, ep, ei = pos
            if (i - ei) >= HOLD or sig == -d:         # exit on time or opposite signal
                trades.append((d, ep, px)); pos = None
                if sig != 0 and sig != d: pos = (sig, px, i)  # flip
    if pos: trades.append((pos[0], pos[1], closes[-1]))

    rets = [d*(xp/ep - 1) for d, ep, xp in trades]
    wins = sum(1 for r in rets if r > 0)
    n = len(rets)
    return {
        "leg": leg, "trades": n,
        "win_rate": round(100*wins/n, 1) if n else 0.0,
        "avg_ret_%": round(100*sum(rets)/n, 3) if n else 0.0,
        "total_ret_%": round(100*sum(rets), 2),
    }

if __name__ == "__main__":
    closes = fetch(limit=1000)
    bh = round(100*(closes[-1]/closes[0]-1), 2)
    print(f"BTC 1h, {len(closes)} bars (~{len(closes)//24}d).  Buy&hold over window: {bh:+.2f}%\n")
    print(f"{'leg':10} {'trades':>7} {'win%':>7} {'avg/trade%':>11} {'total%':>9}")
    for leg in ["candlesig", "macdsig", "coinrev", "diverg"]:
        r = backtest(closes, leg)
        print(f"{r['leg']:10} {r['trades']:>7} {r['win_rate']:>7} {r['avg_ret_%']:>11} {r['total_ret_%']:>9}")
