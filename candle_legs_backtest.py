#!/usr/bin/env python3
"""Honest, no-lookahead backtest of the 4 candle legs on real Binance BTC klines,
now run through a discipline layer built from the documented rules of top
profitable systematic traders:

  * Paul Tudor Jones  — asymmetric reward:risk brackets (target = RR x stop);
                        "losers average losers": one stop, no adds.
  * Richard Dennis /
    Turtles           — volatility (ATR) stops decided BEFORE entry; only trade
                        in the direction of the higher-timeframe trend.
  * Larry Hite /
    Bruce Kovner      — never risk more than ~1% of equity on any single trade.
  * Ed Seykota        — cut losses on the stop, let the target side breathe
                        (time stop only as a last resort).
  * Renaissance-style — an edge that is not statistically distinguishable from
                        zero (t-stat) is noise: verdict is KILL, not "tune it".
  * Every prop desk   — model costs first. Taker vs maker fees + slippage are
                        applied per side; gross-looking edges must survive net.

Each leg keeps the bot's own signal definitions (RSI14, EMA20/50, MACD 12/26/9,
24h change). Two engines run side by side:
  RAW         — the original state machine (enter on signal, exit on max_hold
                or opposite), now also shown net of fees.
  DISCIPLINED — same signals gated by EMA200 regime + fee-aware volatility
                floor, executed as 1xATR-stop / RRxATR-target brackets with
                1%-risk position sizing.
Win = trade closed positive net of costs. Compares to buy & hold."""
import json, math, random, statistics, sys, urllib.request

# ---- costs (per side, as fractions). Binance spot ~5bps taker / 1bp maker;
# ---- 1bp slippage per side keeps us honest about market-order fills.
TAKER = 0.0005
MAKER = 0.0001
SLIP  = 0.0001

def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return json.load(urllib.request.urlopen(req, timeout=20))

def fetch(symbol="BTCUSDT", interval="1h", limit=1000):
    """(high, low, close) per bar. Binance first; Kraken fallback (Binance is
    geo-blocked with HTTP 451 from some cloud regions; Kraken caps at 720 bars)."""
    try:
        data = _get(f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}")
        return [(float(k[2]), float(k[3]), float(k[4])) for k in data], f"binance {symbol}"
    except Exception:
        mins = {"1m":1,"5m":5,"15m":15,"30m":30,"1h":60,"4h":240,"1d":1440}[interval]
        pair = "XBTUSD" if symbol.upper().startswith("BTC") else symbol
        res = _get(f"https://api.kraken.com/0/public/OHLC?pair={pair}&interval={mins}")["result"]
        rows = next(v for k, v in res.items() if k != "last")
        return [(float(k[2]), float(k[3]), float(k[4])) for k in rows[-limit:]], f"kraken {pair}"

def synthetic(limit=1000, seed=7):
    """Deterministic geometric random walk — a no-edge control. Every leg
    SHOULD fail on this; if one 'wins', the harness is lying somewhere."""
    rng = random.Random(seed)
    px, bars = 60000.0, []
    for _ in range(limit):
        c = px * math.exp(rng.gauss(0, 0.006))
        h = max(px, c) * (1 + abs(rng.gauss(0, 0.002)))
        l = min(px, c) * (1 - abs(rng.gauss(0, 0.002)))
        bars.append((h, l, c)); px = c
    return bars

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

def atr_series(bars, p=14):
    """Wilder ATR aligned to bar index (None until enough data)."""
    out = [None] * len(bars)
    if len(bars) <= p: return out
    trs = []
    for i in range(1, len(bars)):
        h, l, _ = bars[i]; pc = bars[i-1][2]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    a = sum(trs[:p]) / p; out[p] = a
    for i in range(p + 1, len(bars)):
        a = (a * (p - 1) + trs[i-1]) / p; out[i] = a
    return out

HOLD = {"candlesig": 8, "macdsig": 8, "coinrev": 24, "diverg": 8}

def build_indicators(closes):
    e20, e50, e200 = ema_series(closes, 20), ema_series(closes, 50), ema_series(closes, 200)
    macd_l = [ (a - b) if (a is not None and b is not None) else None
               for a, b in zip(ema_series(closes, 12), ema_series(closes, 26)) ]
    dense = [m for m in macd_l if m is not None]
    macd_s = [None] * (len(closes) - len(dense)) + ema_series(dense, 9)
    return e20, e50, e200, macd_l, macd_s

def leg_signal(leg, i, closes, e20, e50, macd_l, macd_s):
    """The bot's own signal definitions — unchanged."""
    px = closes[i]
    if leg == "candlesig":                       # RSI pullback inside EMA trend
        r = rsi_at(closes, i)
        if e20[i] and e50[i]:
            if r < 45 and e20[i] > e50[i]*1.002: return 1
            if r > 55 and e20[i] < e50[i]*0.998: return -1
    elif leg == "macdsig":                        # MACD mean-reversion + stretch from EMA20
        if e20[i] and macd_l[i] is not None and macd_s[i] is not None:
            dev = px / e20[i] - 1
            if dev < -0.015 and macd_l[i] > macd_s[i]: return 1
            if dev > 0.015 and macd_l[i] < macd_s[i]: return -1
    elif leg == "coinrev":                        # fade a >7% 24h move
        if i >= 24:
            chg = closes[i]/closes[i-24] - 1
            if chg < -0.07: return 1
            if chg > 0.07: return -1
    elif leg == "diverg":                         # price vs RSI(14) divergence over 12 bars
        if i >= 12:
            r_now, r_prev = rsi_at(closes, i), rsi_at(closes, i-12)
            if closes[i] < closes[i-12] and r_now > r_prev: return 1   # bullish div
            if closes[i] > closes[i-12] and r_now < r_prev: return -1  # bearish div
    return 0

def stats(rets):
    n = len(rets)
    if n == 0:
        return {"trades": 0, "win_rate": 0.0, "avg_ret_%": 0.0, "total_ret_%": 0.0, "t": 0.0}
    wins = sum(1 for r in rets if r > 0)
    mean = sum(rets) / n
    t = 0.0
    if n > 2:
        sd = statistics.stdev(rets)
        if sd > 0: t = mean / (sd / math.sqrt(n))
    return {"trades": n, "win_rate": round(100*wins/n, 1),
            "avg_ret_%": round(100*mean, 3), "total_ret_%": round(100*sum(rets), 2),
            "t": round(t, 2)}

def backtest_raw(bars, leg, fee_side):
    """Original engine: flat -> enter on signal -> exit on max_hold or opposite."""
    closes = [b[2] for b in bars]
    e20, e50, _, macd_l, macd_s = build_indicators(closes)
    trades, pos = [], None
    for i in range(55, len(closes)):
        px = closes[i]
        sig = leg_signal(leg, i, closes, e20, e50, macd_l, macd_s)
        if pos is None:
            if sig != 0: pos = (sig, px, i)
        else:
            d, ep, ei = pos
            if (i - ei) >= HOLD[leg] or sig == -d:    # exit on time or opposite signal
                trades.append((d, ep, px)); pos = None
                if sig != 0 and sig != d: pos = (sig, px, i)  # flip
    if pos: trades.append((pos[0], pos[1], closes[-1]))
    cost = 2 * (fee_side + SLIP)
    gross = [d*(xp/ep - 1) for d, ep, xp in trades]
    return stats(gross), stats([g - cost for g in gross])

def backtest_disciplined(bars, leg, fee_side, rr=2.0, risk=0.01):
    """Same signals through the top-trader rulebook:
    EMA200 regime filter (longs above / shorts below), fee-aware volatility
    floor (skip when ATR can't pay for the round trip several times over),
    1xATR stop + rr xATR target set at entry, time stop at 2x the leg's hold,
    1%-of-equity risk sizing. Stop is checked before target inside a bar —
    the conservative, no-lookahead assumption."""
    highs  = [b[0] for b in bars]
    lows   = [b[1] for b in bars]
    closes = [b[2] for b in bars]
    e20, e50, e200, macd_l, macd_s = build_indicators(closes)
    atr = atr_series(bars)
    cost = 2 * (fee_side + SLIP)
    nets, rmults, pos = [], [], None
    equity, peak, maxdd = 1.0, 1.0, 0.0
    for i in range(210, len(closes)):
        px = closes[i]
        if pos is not None:
            d, entry, stop, target, ei = pos
            exit_px = None
            if d == 1:
                if lows[i] <= stop:      exit_px = stop
                elif highs[i] >= target: exit_px = target
            else:
                if highs[i] >= stop:     exit_px = stop
                elif lows[i] <= target:  exit_px = target
            if exit_px is None and (i - ei) >= 2 * HOLD[leg]: exit_px = px
            if exit_px is not None:
                net = d * (exit_px / entry - 1) - cost
                stop_frac = abs(entry - stop) / entry
                nets.append(net); rmults.append(net / stop_frac)
                equity += (equity * risk / stop_frac) * net   # 1R loss == `risk` of equity
                peak = max(peak, equity); maxdd = max(maxdd, 1 - equity / peak)
                pos = None
        if pos is None:
            sig = leg_signal(leg, i, closes, e20, e50, macd_l, macd_s)
            if sig == 1 and not (e200[i] and px > e200[i]): sig = 0   # trend filter
            if sig == -1 and not (e200[i] and px < e200[i]): sig = 0
            if sig and (atr[i] is None or atr[i] / px < 4 * cost): sig = 0  # vol floor
            if sig:
                pos = (sig, px, px - sig * atr[i], px + sig * rr * atr[i], i)
    s = stats(nets)
    s["avg_R"] = round(sum(rmults) / len(rmults), 2) if rmults else 0.0
    s["equity_%"] = round(100 * (equity - 1), 2)
    s["maxdd_%"] = round(100 * maxdd, 2)
    return s

def verdict(s):
    made_money = s.get("equity_%", s["total_ret_%"]) > 0   # sized result when we have one
    if s["trades"] < 20: return "n<20 — no verdict"
    if s["t"] >= 2 and made_money: return "KEEP (edge significant)"
    if made_money: return "unproven (t<2 — likely noise)"
    return "KILL"

if __name__ == "__main__":
    args = sys.argv[1:]
    def opt(name, default):
        return args[args.index(name)+1] if name in args else default
    symbol, interval = opt("--symbol", "BTCUSDT"), opt("--interval", "1h")
    limit, rr = int(opt("--limit", 1000)), float(opt("--rr", 2.0))
    fee_side = MAKER if "--maker" in args else TAKER
    if "--synthetic" in args:
        bars = synthetic(limit); src = "SYNTHETIC random walk (no-edge control)"
    else:
        try:
            bars, venue = fetch(symbol, interval, limit); src = f"{venue} {interval} live klines"
        except Exception as e:
            bars = synthetic(limit); src = f"SYNTHETIC random walk (fetch failed: {e})"
    closes = [b[2] for b in bars]
    bh = round(100*(closes[-1]/closes[0]-1), 2)
    cost = 2 * (fee_side + SLIP)
    print(f"{src}, {len(bars)} bars.  Buy&hold: {bh:+.2f}%.  "
          f"Round-trip cost {cost*10000:.0f}bps ({'maker' if fee_side==MAKER else 'taker'}+slip).  RR {rr}:1\n")
    print(f"{'leg':10} {'engine':12} {'trades':>6} {'win%':>6} {'avg%':>7} {'total%':>8} "
          f"{'avgR':>6} {'eq%':>7} {'maxDD%':>7} {'t':>6}  verdict")
    for leg in ["candlesig", "macdsig", "coinrev", "diverg"]:
        g, n = backtest_raw(bars, leg, fee_side)
        d = backtest_disciplined(bars, leg, fee_side, rr=rr)
        print(f"{leg:10} {'raw gross':12} {g['trades']:>6} {g['win_rate']:>6} {g['avg_ret_%']:>7} "
              f"{g['total_ret_%']:>8} {'':>6} {'':>7} {'':>7} {g['t']:>6}")
        print(f"{'':10} {'raw net':12} {n['trades']:>6} {n['win_rate']:>6} {n['avg_ret_%']:>7} "
              f"{n['total_ret_%']:>8} {'':>6} {'':>7} {'':>7} {n['t']:>6}  {verdict(n)}")
        print(f"{'':10} {'disciplined':12} {d['trades']:>6} {d['win_rate']:>6} {d['avg_ret_%']:>7} "
              f"{d['total_ret_%']:>8} {d['avg_R']:>6} {d['equity_%']:>7} {d['maxdd_%']:>7} {d['t']:>6}  {verdict(d)}")
    print("\nHONEST: verdicts are per this window only; a KEEP still needs out-of-sample proof.")
