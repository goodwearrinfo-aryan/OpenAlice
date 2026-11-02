#!/usr/bin/env python3
"""10-strategy honest backtest + paper race for the OpenAlice cockpit.

The existing ALGO RACE footnote is right: naive single-symbol TA rules don't beat
random after fees. This set is chosen for documented, durable rationale
(trend/momentum persistence, short-horizon mean reversion, volatility
compression) plus two structural edges (funding carry, dollar-neutral pairs).
Every rule is NO-LOOKAHEAD: the signal uses bars <= i, the fill is bar i+1's
return, and taker fees are charged on every change in weight. Buy&hold over the
same window is printed as the bar to clear.

  #  name            type   rationale
  1  donchian-20/10  TREND  Turtle channel breakout, long/short
  2  tsmom-7d        TREND  time-series momentum (7d), 24h min-hold
  3  regime-ma200    TREND  long-only above SMA200 (skip the left tail)
  4  rsi2-dip        MR     Connors RSI(2) pullback, uptrend regime only
  5  bb-adx-fade     MR     fade Bollinger touch only when ADX<20 (ranging)
  6  day-range-break BREAK  Williams range expansion off the day open
  7  funding-carry   EDGE   delta-neutral spot+perp carry when funding >= 0.5bp/8h
  8  pairs-ethbtc    EDGE   dollar-neutral ETH/BTC z-score mean reversion
  9  xs-momo         TREND  hold the strongest of BTC/ETH/SOL (7d), daily rebalance
 10  squeeze-pop     BREAK  BB-width compression (bottom 20%) -> Donchian break

Usage:
  python3 oa_strategies10.py                                   # report
  python3 oa_strategies10.py --emit ui/public/strategies10.json   # one feed write
  python3 oa_strategies10.py --live ui/public/strategies10.json   # loop (--interval 60)
  python3 oa_strategies10.py --source okx                      # force a data source

Data: Binance -> OKX -> Kraken -> Coinbase, first reachable (Binance/Bybit are
geo-blocked from some networks). Funding: Binance fapi -> OKX. stdlib only.
"""
import json, math, os, sys, time, urllib.request

FEE = 0.0005            # taker, per side, per unit of turnover (5 bps)
NOTIONAL = 100_000.0
BARS = 1500             # 1h bars (~62 days)
SYMS = ("BTC", "ETH", "SOL")

# ------------------------------------------------------------------ data
def _get(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return json.load(urllib.request.urlopen(req, timeout=timeout))

def _binance(sym, want):
    out, end = [], None
    while len(out) < want:
        url = f"https://api.binance.com/api/v3/klines?symbol={sym}USDT&interval=1h&limit={min(1000, want-len(out))}"
        if end: url += f"&endTime={end}"
        rows = _get(url)
        if not rows: break
        out = rows + out
        end = rows[0][0] - 1
        if len(rows) < 1000: break
    return [(int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4])) for r in out]

def _okx(sym, want):
    out, after = [], None
    while len(out) < want:
        url = f"https://www.okx.com/api/v5/market/history-candles?instId={sym}-USDT&bar=1H&limit=100"
        if after: url += f"&after={after}"
        rows = _get(url).get("data", [])
        if not rows: break
        out = list(reversed(rows)) + out          # okx is newest-first
        after = rows[-1][0]
        time.sleep(0.12)
    return [(int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4])) for r in out]

def _kraken(sym, want):
    pair = {"BTC": "XBTUSD", "ETH": "ETHUSD", "SOL": "SOLUSD"}[sym]
    res = _get(f"https://api.kraken.com/0/public/OHLC?pair={pair}&interval=60")["result"]
    rows = next(v for k, v in res.items() if k != "last")
    return [(int(r[0]) * 1000, float(r[1]), float(r[2]), float(r[3]), float(r[4])) for r in rows]

def _coinbase(sym, want):
    out, end = [], int(time.time())
    while len(out) < want:
        start = end - 300 * 3600
        rows = _get(f"https://api.exchange.coinbase.com/products/{sym}-USD/candles"
                    f"?granularity=3600&start={start}&end={end}")
        if not rows: break
        rows.sort(key=lambda r: r[0])             # [t, low, high, open, close, vol]
        out = [(r[0] * 1000, r[3], r[2], r[1], r[4]) for r in rows] + out
        end = start
        time.sleep(0.12)
    return out

SOURCES = [("binance", _binance), ("okx", _okx), ("kraken", _kraken), ("coinbase", _coinbase)]

def fetch_all(source="auto", want=BARS):
    order = SOURCES if source == "auto" else [s for s in SOURCES if s[0] == source]
    err = None
    for name, fn in order:
        try:
            raw = {s: fn(s, want) for s in SYMS}
            if any(len(v) < 400 for v in raw.values()):
                raise RuntimeError(f"{name}: too little data { {s: len(v) for s, v in raw.items()} }")
            shared = set.intersection(*(set(r[0] for r in v) for v in raw.values()))
            data = {}
            for s in SYMS:
                rows = sorted(r for r in raw[s] if r[0] in shared)
                data[s] = {k: [r[j] for r in rows] for j, k in enumerate(("t", "o", "h", "l", "c"))}
            return name, data
        except Exception as e:
            err = e
    raise RuntimeError(f"no data source reachable: {err}")

def fetch_funding(want=300):
    """BTC perp funding [(ts_ms, rate)] oldest first; [] if unreachable."""
    try:
        rows = _get(f"https://fapi.binance.com/fapi/v1/fundingRate?symbol=BTCUSDT&limit={min(want,1000)}")
        return sorted((int(r["fundingTime"]), float(r["fundingRate"])) for r in rows)
    except Exception:
        pass
    try:
        out, after = [], None
        while len(out) < want:
            url = "https://www.okx.com/api/v5/public/funding-rate-history?instId=BTC-USDT-SWAP&limit=100"
            if after: url += f"&after={after}"
            rows = _get(url).get("data", [])
            if not rows: break
            out = rows[::-1] + out
            after = rows[-1]["fundingTime"]
            time.sleep(0.12)
        return sorted((int(r["fundingTime"]), float(r["realizedRate"] or r["fundingRate"])) for r in out)
    except Exception:
        return []

# ------------------------------------------------------------ indicators
def sma(v, p):
    out, s = [None] * len(v), 0.0
    for i, x in enumerate(v):
        s += x
        if i >= p: s -= v[i - p]
        if i >= p - 1: out[i] = s / p
    return out

def rsi(v, p):
    out = [None] * len(v)
    if len(v) <= p: return out
    up = dn = 0.0
    for j in range(1, p + 1):
        d = v[j] - v[j-1]; up += max(d, 0); dn += max(-d, 0)
    up /= p; dn /= p
    out[p] = 100.0 if dn == 0 else 100 - 100 / (1 + up / dn)
    for i in range(p + 1, len(v)):
        d = v[i] - v[i-1]
        up = (up * (p-1) + max(d, 0)) / p
        dn = (dn * (p-1) + max(-d, 0)) / p
        out[i] = 100.0 if dn == 0 else 100 - 100 / (1 + up / dn)
    return out

def adx(h, l, c, p=14):
    n, out = len(c), [None] * len(c)
    if n <= 2 * p + 1: return out
    trs, pdm, ndm = [], [], []
    for i in range(1, n):
        trs.append(max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1])))
        up, dw = h[i]-h[i-1], l[i-1]-l[i]
        pdm.append(up if up > dw and up > 0 else 0.0)
        ndm.append(dw if dw > up and dw > 0 else 0.0)
    st, sp, sn = sum(trs[:p]), sum(pdm[:p]), sum(ndm[:p])
    dxs, cur = [], None
    for k in range(p, len(trs)):
        st = st - st/p + trs[k]; sp = sp - sp/p + pdm[k]; sn = sn - sn/p + ndm[k]
        pi = 100*sp/st if st else 0; ni = 100*sn/st if st else 0
        dx = 100*abs(pi-ni)/(pi+ni) if pi+ni else 0
        dxs.append(dx)
        if len(dxs) == p: cur = sum(dxs)/p
        elif len(dxs) > p: cur = (cur*(p-1) + dx)/p
        if cur is not None: out[k+1] = cur            # trs[k] is bar k+1
    return out

def boll(v, p=20, k=2.0):
    mid = sma(v, p)
    up, lo, wd = [None]*len(v), [None]*len(v), [None]*len(v)
    for i in range(p-1, len(v)):
        m = mid[i]
        sd = math.sqrt(sum((x-m)**2 for x in v[i-p+1:i+1]) / p)
        up[i], lo[i], wd[i] = m + k*sd, m - k*sd, (2*k*sd/m if m else None)
    return mid, up, lo, wd

# ------------------------------------------------------------ strategies
# builder(data, funding) -> target(i) -> {sym: weight}; uses bars <= i only.
def s_donchian(d, _f):
    h, l, c = d["BTC"]["h"], d["BTC"]["l"], d["BTC"]["c"]
    st = {"w": 0}
    def t(i):
        if i < 21: return {}
        w = st["w"]
        if w == 0:
            w = 1 if c[i] > max(h[i-20:i]) else (-1 if c[i] < min(l[i-20:i]) else 0)
        elif w == 1 and c[i] < min(l[i-10:i]): w = 0
        elif w == -1 and c[i] > max(h[i-10:i]): w = 0
        st["w"] = w
        return {"BTC": w}
    return t

def s_tsmom(d, _f):
    c = d["BTC"]["c"]
    st = {"w": 0, "since": -999}
    def t(i):
        if i < 168: return {}
        w = 1 if c[i] > c[i-168] else -1
        if w != st["w"] and i - st["since"] >= 24:
            st["w"], st["since"] = w, i
        return {"BTC": st["w"]}
    return t

def s_regime(d, _f):
    c = d["BTC"]["c"]; m = sma(c, 200)
    return lambda i: {"BTC": 1 if m[i] is not None and c[i] > m[i] else 0}

def s_rsi2(d, _f):
    c = d["BTC"]["c"]; m = sma(c, 200); r = rsi(c, 2)
    st = {"w": 0, "since": 0}
    def t(i):
        if r[i] is None or m[i] is None: return {}
        if st["w"] == 0 and c[i] > m[i] and r[i] < 10: st["w"], st["since"] = 1, i
        elif st["w"] == 1 and (r[i] > 60 or i - st["since"] >= 24): st["w"] = 0
        return {"BTC": st["w"]}
    return t

def s_bbadx(d, _f):
    b = d["BTC"]; c = b["c"]
    mid, up, lo, _ = boll(c); ax = adx(b["h"], b["l"], c)
    st = {"w": 0, "since": 0}
    def t(i):
        if up[i] is None or ax[i] is None: return {}
        w = st["w"]
        if w == 0 and ax[i] < 20:
            w = 1 if c[i] < lo[i] else (-1 if c[i] > up[i] else 0)
            if w: st["since"] = i
        elif w != 0:
            if (w == 1 and c[i] >= mid[i]) or (w == -1 and c[i] <= mid[i]) or i - st["since"] >= 24: w = 0
        st["w"] = w
        return {"BTC": w}
    return t

def s_dayrange(d, _f):
    b = d["BTC"]; tt, o, h, l, c = b["t"], b["o"], b["h"], b["l"], b["c"]
    day = [x // 86_400_000 for x in tt]
    # per-day open, and prior-day range, indexed by day number
    first, rng = {}, {}
    for i, dy in enumerate(day):
        first.setdefault(dy, i)
    for dy in sorted(set(day)):
        idx = [i for i in range(len(day)) if day[i] == dy]
        rng[dy] = max(h[j] for j in idx) - min(l[j] for j in idx)
    days = sorted(set(day))
    prev = {days[k]: days[k-1] for k in range(1, len(days))}
    def t(i):
        dy = day[i]
        if dy not in prev or prev[dy] not in rng: return {}
        # long once price clears open + 0.6 x yesterday's range; flat from 23:00 UTC bar
        if (tt[i] // 3_600_000) % 24 >= 23: return {"BTC": 0}
        return {"BTC": 1 if c[i] > o[first[dy]] + 0.6 * rng[prev[dy]] else 0}
    return t

def s_funding(d, fund):
    """Delta-neutral carry: long spot + short perp. Enter when the 3-settlement
    avg funding >= 0.5bp/8h (~5.5%/yr, above the 20bp round-trip fee drag);
    exit below 0.2bp (hysteresis, no churn). Engine books funding only and
    charges fees on BOTH legs."""
    tt = d["BTC"]["t"]
    st = {"on": False}
    def t(i):
        past = [r for ts, r in fund if ts <= tt[i]][-3:]
        if len(past) < 3: return {}
        avg = sum(past) / 3
        st["on"] = avg >= 0.00005 if not st["on"] else avg >= 0.00002
        return {"BTC": 1} if st["on"] else {}
    return t

def s_pairs(d, _f):
    cb, ce = d["BTC"]["c"], d["ETH"]["c"]
    lr = [math.log(ce[i] / cb[i]) for i in range(len(cb))]
    st = {"w": 0}
    def t(i):
        if i < 240: return {}
        win = lr[i-240:i]; mu = sum(win)/240
        sd = math.sqrt(sum((x-mu)**2 for x in win)/240)
        if sd == 0: return {}
        z = (lr[i]-mu)/sd
        w = st["w"]
        if w == 0: w = -1 if z > 2 else (1 if z < -2 else 0)
        elif abs(z) < 0.5: w = 0
        st["w"] = w
        return {"ETH": 0.5*w, "BTC": -0.5*w}      # dollar-neutral
    return t

def s_xsmomo(d, _f):
    cs = {s: d[s]["c"] for s in SYMS}
    st = {"hold": None, "since": -999}
    def t(i):
        if i < 168: return {}
        if i - st["since"] >= 24:
            mo = {s: cs[s][i] / cs[s][i-168] - 1 for s in SYMS}
            best = max(mo, key=mo.get)
            st["hold"] = best if mo[best] > 0 else None
            st["since"] = i
        return {st["hold"]: 1} if st["hold"] else {}
    return t

def s_squeeze(d, _f):
    b = d["BTC"]; c, h, l = b["c"], b["h"], b["l"]
    _, _, _, wd = boll(c)
    st = {"w": 0, "since": 0}
    def t(i):
        if i < 280 or wd[i] is None: return {}
        w = st["w"]
        if w == 0:
            hist = [x for x in wd[i-240:i] if x is not None]
            if hist and sum(1 for x in hist if x < wd[i]) / len(hist) <= 0.20:
                w = 1 if c[i] > max(h[i-20:i]) else (-1 if c[i] < min(l[i-20:i]) else 0)
                if w: st["since"] = i
        elif i - st["since"] >= 48: w = 0
        st["w"] = w
        return {"BTC": w}
    return t

STRATS = [
    ("donchian-20/10",  "TREND", "turtle channel breakout",           s_donchian),
    ("tsmom-7d",        "TREND", "time-series momentum 7d",          s_tsmom),
    ("regime-ma200",    "TREND", "long-only above SMA200",           s_regime),
    ("rsi2-dip",        "MR",    "RSI(2) pullback in uptrend",       s_rsi2),
    ("bb-adx-fade",     "MR",    "fade bands when ADX<20",           s_bbadx),
    ("day-range-break", "BREAK", "range expansion off day open",     s_dayrange),
    ("funding-carry",   "EDGE",  "delta-neutral spot/perp carry",    s_funding),
    ("pairs-ethbtc",    "EDGE",  "ETH/BTC z-score, dollar-neutral",  s_pairs),
    ("xs-momo",         "TREND", "strongest of BTC/ETH/SOL",         s_xsmomo),
    ("squeeze-pop",     "BREAK", "BB squeeze -> Donchian break",     s_squeeze),
]

# ---------------------------------------------------------------- engine
def run(name, builder, data, fund):
    c = {s: data[s]["c"] for s in SYMS}
    tt = data["BTC"]["t"]; n = len(tt)
    target = builder(data, fund)
    carry = name == "funding-carry"
    eq, weights, curve = NOTIONAL, {}, [NOTIONAL] * n
    trades = wins = 0; eq0 = None
    pay = sorted(fund); pj = 0
    sgn = lambda w: {s: (w[s] > 0) - (w[s] < 0) for s in w}
    for i in range(n - 1):
        w_new = {s: w for s, w in (target(i) or {}).items() if w}
        turn = sum(abs(w_new.get(s, 0) - weights.get(s, 0)) for s in set(w_new) | set(weights))
        if carry:
            turn *= 2                               # spot leg + perp leg
            ret = 0.0                               # price exposure hedged out
        else:
            ret = sum(w * (c[s][i+1] / c[s][i] - 1) for s, w in w_new.items())
        while pj < len(pay) and pay[pj][0] <= tt[i]: pj += 1
        k = pj
        while k < len(pay) and pay[k][0] <= tt[i+1]:
            if carry and w_new: ret += pay[k][1]    # short perp collects positive funding
            k += 1
        eq *= (1 + ret - turn * FEE)
        curve[i+1] = eq
        if sgn(w_new) != sgn(weights):              # entry, exit, or flip closes a trade
            if weights and eq0:
                trades += 1; wins += eq > eq0
            eq0 = eq if w_new else None
        weights = w_new
    if weights and eq0:
        trades += 1; wins += eq > eq0
    peak, dd = curve[0], 0.0
    for x in curve:
        peak = max(peak, x); dd = max(dd, 1 - x / peak)
    return {"name": name, "equity": round(eq, 2), "ret_pct": round(100 * (eq / NOTIONAL - 1), 3),
            "trades": trades, "winpct": round(100 * wins / trades, 1) if trades else 0.0,
            "dd_pct": round(100 * dd, 2), "pos": dict(weights), "curve": curve}

def backtest_all(source="auto"):
    src, data = fetch_all(source)
    fund = fetch_funding()
    tt = data["BTC"]["t"]
    res = []
    for name, typ, tag, builder in STRATS:
        r = run(name, builder, data, fund); r.update(type=typ, tag=tag); res.append(r)
    meta = {"source": src, "bars": len(tt), "window_d": round((tt[-1]-tt[0]) / 86_400_000, 1),
            "bh_pct": round(100 * (data["BTC"]["c"][-1] / data["BTC"]["c"][0] - 1), 2),
            "fee_bps": FEE * 1e4, "funding_n": len(fund), "t": tt,
            "btc": data["BTC"]["c"][-1], "eth": data["ETH"]["c"][-1], "sol": data["SOL"]["c"][-1]}
    return meta, res

# --------------------------------------------------------------- output
def report(meta, res):
    print(f"{len(STRATS)} strategies · BTC/ETH/SOL 1h × {meta['bars']} bars (~{meta['window_d']}d) · "
          f"source={meta['source']} · fee={meta['fee_bps']:.0f}bps/side")
    print(f"BTC buy&hold over window: {meta['bh_pct']:+.2f}%   funding records: {meta['funding_n']}\n")
    print(f"{'#':>2} {'strategy':16} {'type':5} {'ret%':>8} {'win%':>6} {'trades':>6} {'maxDD%':>7}")
    for i, r in enumerate(sorted(res, key=lambda r: -r["ret_pct"]), 1):
        print(f"{i:>2} {r['name']:16} {r['type']:5} {r['ret_pct']:>8.3f} {r['winpct']:>6.1f} "
              f"{r['trades']:>6} {r['dd_pct']:>7.2f}")
    print("\nSingle ~60d window, one regime: a ranking here is a hypothesis, not proof.")

def emit(path, meta, res, prev):
    tt = meta["t"]
    applied = (prev or {}).get("applied") or tt[-1]          # forward-record start
    ai = next((j for j, ts in enumerate(tt) if ts >= applied), len(tt) - 1)
    board = []
    for r in sorted(res, key=lambda r: -r["ret_pct"]):
        fwd = 100 * (r["curve"][-1] / r["curve"][ai] - 1) if r["curve"][ai] else 0.0
        pos = ", ".join(f"{'L' if w > 0 else 'S'}{abs(w):g} {s}" for s, w in r["pos"].items()) or "flat"
        board.append({"name": r["name"], "type": r["type"], "tag": r["tag"], "pos": pos,
                      "ret_pct": r["ret_pct"], "fwd_pct": round(fwd, 3), "winpct": r["winpct"],
                      "trades": r["trades"], "dd_pct": r["dd_pct"], "equity": r["equity"]})
    out = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "applied": applied, "source": meta["source"],
           "window_d": meta["window_d"], "fee_bps": meta["fee_bps"], "bh_pct": meta["bh_pct"],
           "btc": meta["btc"], "eth": meta["eth"], "sol": meta["sol"], "board": board}
    tmp = path + ".tmp"
    with open(tmp, "w") as f: json.dump(out, f)
    os.replace(tmp, path)
    return out

def main():
    a = sys.argv[1:]
    arg = lambda f, d=None: a[a.index(f)+1] if f in a and a.index(f)+1 < len(a) and not a[a.index(f)+1].startswith("--") else d
    src = arg("--source", "auto"); interval = int(arg("--interval", 60))
    live = "--live" in a
    path = arg("--live") or arg("--emit") or ("ui/public/strategies10.json" if live or "--emit" in a else None)
    while True:
        try:
            meta, res = backtest_all(src)
            if path:
                prev = None
                if os.path.exists(path):
                    try: prev = json.load(open(path))
                    except Exception: pass
                o = emit(path, meta, res, prev)
                print(f"[strategies10] {o['ts']} wrote {path} leader={o['board'][0]['name']} {o['board'][0]['ret_pct']:+.2f}%", flush=True)
            else:
                report(meta, res)
        except Exception as e:
            print(f"[strategies10] ERROR {e}", file=sys.stderr, flush=True)
            if not live: raise
        if not live: break
        time.sleep(interval)

if __name__ == "__main__":
    main()
