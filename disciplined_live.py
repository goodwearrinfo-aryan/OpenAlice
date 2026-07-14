#!/usr/bin/env python3
"""Live paper runner for the disciplined legs engine (see candle_legs_backtest.py).

Runs the same four leg signals through the top-trader rulebook — EMA200 regime
filter, fee-aware volatility floor, 1xATR stop / RRxATR target brackets set at
entry, 1%-of-equity risk sizing, maker-fee cost model — but forward, on closed
1h bars only (no intrabar peeking, the forming bar is always dropped). State
survives restarts via disciplined_state.json; if the daemon was down, elapsed
closed bars are replayed in order, so the record has no gaps and no lookahead.

Feeds ui/public/disciplined.json for the cockpit tab. The live record starts
empty on install — the seeded 30d disciplined-backtest equity is shown as a
reference column (BT), never mixed into the paper record.

Usage: disciplined_live.py [--once]   (default: tick every 60s, forever)"""
import json, math, os, statistics, sys, time

from candle_legs_backtest import (MAKER, SLIP, HOLD, _get, atr_series,
                                  backtest_disciplined, build_indicators,
                                  leg_signal)

DIR    = os.path.dirname(os.path.abspath(__file__))
FEED   = os.path.join(DIR, "ui", "public", "disciplined.json")
STATE  = os.path.join(DIR, "ui", "public", "disciplined_state.json")
LEGS   = ["candlesig", "macdsig", "coinrev", "diverg"]
RR, RISK, FEE = 2.0, 0.01, MAKER          # maker fills are the point — see backtest
COST     = 2 * (FEE + SLIP)
EQUITY0  = 100_000.0                       # paper equity per leg
WARMUP   = 210                             # bars needed for EMA200 + ATR

def fetch_t(limit=720):
    """(ts, high, low, close) for CLOSED bars only — the forming bar is dropped.
    Binance first; Kraken fallback (HTTP 451 geo-blocks, same as backtest)."""
    try:
        data = _get(f"https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1h&limit={limit}")
        rows = [(int(k[0]) // 1000, float(k[2]), float(k[3]), float(k[4])) for k in data]
        venue = "binance"
    except Exception:
        res = _get("https://api.kraken.com/0/public/OHLC?pair=XBTUSD&interval=60")["result"]
        raw = next(v for k, v in res.items() if k != "last")
        rows = [(int(k[0]), float(k[2]), float(k[3]), float(k[4])) for k in raw][-limit:]
        venue = "kraken"
    return rows[:-1], venue

def save(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w") as f: json.dump(obj, f)
    os.replace(tmp, path)

def load_state():
    try:
        with open(STATE) as f: return json.load(f)
    except Exception:
        return None

def new_state(bars):
    """Fresh install: live record starts empty; the disciplined backtest over
    the fetched window is stored once, as a reference column only."""
    hlc = [(h, l, c) for _, h, l, c in bars]
    st = {"started": bars[-1][0], "last_ts": bars[-1][0], "legs": {}}
    for leg in LEGS:
        bt = backtest_disciplined(hlc, leg, FEE, rr=RR, risk=RISK)
        st["legs"][leg] = {"equity": EQUITY0, "pos": None, "trades": [], "bt_eq": bt["equity_%"]}
    return st

def tick(st, bars, venue):
    closes = [c for _, _, _, c in bars]
    hlc    = [(h, l, c) for _, h, l, c in bars]
    e20, e50, e200, ml, ms = build_indicators(closes)
    atr = atr_series(hlc)
    for i, (ts, h, l, c) in enumerate(bars):
        if ts <= st["last_ts"] or i < WARMUP: continue
        for leg in LEGS:
            L, p = st["legs"][leg], st["legs"][leg]["pos"]
            if p:                                             # manage the bracket
                p["held"] += 1
                d, exit_px = p["d"], None
                if d == 1:                                    # stop checked first — conservative
                    if l <= p["stop"]:      exit_px = p["stop"]
                    elif h >= p["target"]:  exit_px = p["target"]
                else:
                    if h >= p["stop"]:      exit_px = p["stop"]
                    elif l <= p["target"]:  exit_px = p["target"]
                if exit_px is None and p["held"] >= 2 * HOLD[leg]: exit_px = c
                if exit_px is not None:
                    net = d * (exit_px / p["entry"] - 1) - COST
                    sf  = abs(p["entry"] - p["stop"]) / p["entry"]
                    L["equity"] += (L["equity"] * RISK / sf) * net
                    L["trades"] = (L["trades"] + [{"ts": ts, "net": net, "r": net / sf}])[-200:]
                    L["pos"] = None
            if L["pos"] is None:                              # look for an entry
                sig = leg_signal(leg, i, closes, e20, e50, ml, ms)
                if sig == 1 and not (e200[i] and c > e200[i]): sig = 0
                if sig == -1 and not (e200[i] and c < e200[i]): sig = 0
                if sig and (atr[i] is None or atr[i] / c < 4 * COST): sig = 0
                if sig:
                    L["pos"] = {"d": sig, "entry": c, "stop": c - sig * atr[i],
                                "target": c + sig * RR * atr[i], "held": 0, "ts": ts}
        st["last_ts"] = ts
    write_feed(st, bars, venue, atr)
    save(STATE, st)

def verdict(n, t, pnl):
    if n < 20: return "n<20"
    if t >= 2 and pnl > 0: return "KEEP"
    if pnl > 0: return "unproven"
    return "KILL"

def write_feed(st, bars, venue, atr):
    mark = bars[-1][3]
    legs, book = [], 0.0
    for leg in LEGS:
        L = st["legs"][leg]
        rets = [tr["net"] for tr in L["trades"]]
        rs   = [tr["r"] for tr in L["trades"]]
        n    = len(rets); wins = sum(1 for r in rets if r > 0)
        t = 0.0
        if n > 2:
            sd = statistics.stdev(rets)
            if sd > 0: t = sum(rets) / n / (sd / math.sqrt(n))
        pnl, upnl, p = L["equity"] - EQUITY0, 0.0, L["pos"]
        if p:
            sf = abs(p["entry"] - p["stop"]) / p["entry"]
            upnl = (L["equity"] * RISK / sf) * p["d"] * (mark / p["entry"] - 1)
        legs.append({
            "leg": leg, "pos": ("LONG" if p["d"] == 1 else "SHORT") if p else "flat",
            "entry": p and round(p["entry"], 1), "stop": p and round(p["stop"], 1),
            "target": p and round(p["target"], 1),
            "equity": round(L["equity"], 2), "pnl": round(pnl, 2), "upnl": round(upnl, 2),
            "n": n, "wins": wins, "winpct": round(100 * wins / n, 1) if n else 0,
            "avg_r": round(sum(rs) / n, 2) if n else 0, "t": round(t, 2),
            "bt_eq": L["bt_eq"], "verdict": verdict(n, t, pnl),
        })
        book += pnl
    save(FEED, {"ts": int(time.time()), "venue": venue, "btc": mark,
                "atr": round(atr[-1], 1) if atr[-1] else None, "rr": RR,
                "fee_bps": round(COST * 10000, 1), "risk_pct": RISK * 100,
                "equity0": EQUITY0, "book_pnl": round(book, 2),
                "started": st["started"], "legs": legs})

def main():
    once = "--once" in sys.argv
    while True:
        try:
            bars, venue = fetch_t()
            st = load_state() or new_state(bars)
            tick(st, bars, venue)
        except Exception as e:
            print(f"[disciplined] tick failed: {e}", flush=True)
        if once: break
        time.sleep(60)

if __name__ == "__main__":
    main()
