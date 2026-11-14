"""Geçici test: Supertrend sinyallerinde hangi price action unsurları sonucu etkiliyor?"""
import sys, os, json, time
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as sc
api = sc.Binance(); cfg0 = json.load(open("config.json"))
NB = {"15m": 2900, "1h": 2900, "4h": 1490}; MAXB = {"15m": 96, "1h": 72, "4h": 42}; COST = 0.001
tick = api.get("/fapi/v1/ticker/24hr")
info = {s["symbol"]: s for s in api.get("/fapi/v1/exchangeInfo")["symbols"]}
syms = [t["symbol"] for t in sorted(tick, key=lambda t: -float(t["quoteVolume"]))
        if t["symbol"] in info and info[t["symbol"]].get("underlyingType") == "COIN" and float(t["quoteVolume"]) >= 5e6][:150]
def fetch(sym, tf):
    out, end = [], None
    while len(out) < NB[tf]:
        p = {"symbol": sym, "interval": tf, "limit": 1500}
        if end: p["endTime"] = end
        raw = api.get("/fapi/v1/klines", p)
        if not raw: break
        out = raw + out; end = int(raw[0][0]) - 1
        if len(raw) < 1500: break
    now = int(time.time() * 1000); seen = set(); cs = []
    for k in out:
        if int(k[0]) in seen or int(k[6]) >= now: continue
        seen.add(int(k[0])); cs.append({"t": int(k[0]), "o": float(k[1]), "h": float(k[2]), "l": float(k[3]), "c": float(k[4]), "v": float(k[7]), "bv": float(k[5])})
    return cs[-NB[tf]:]
def outcome(f, i, s, tf):
    e = f["c"][i]; risk = 1.5 * f["atr"][i]; sl = e - s * risk
    tps = [e + s * risk * r for r in (1, 2, 3)]; best, stop = 0, sl
    for k in range(i + 1, i + 1 + MAXB[tf]):
        h, l = f["h"][k], f["l"][k]
        hit = (l <= stop) if s == 1 else (h >= stop)
        reach = max([m for m, tp in enumerate(tps, 1) if ((h >= tp) if s == 1 else (l <= tp))], default=0)
        if hit: return (-1 if best == 0 else sum(range(1, best + 1)) / 3) - COST * e / risk
        if reach > best:
            best = reach; stop = e
            if best == 3: return 2.0 - COST * e / risk
    end = i + MAXB[tf]
    return (sum(range(1, best + 1)) / 3 if best else (f["c"][end] - e) * s / risk) - COST * e / risk
pf = lambda R: (sum(r for r in R if r > 0) / -sum(r for r in R if r < 0)) if any(r < 0 for r in R) else 99
for tf in ("15m", "1h", "4h"):
    cfg = dict(cfg0, timeframe=tf)
    with ThreadPoolExecutor(6) as ex:
        data = dict(zip(syms, ex.map(lambda s: fetch(s, tf), syms)))
    rows = []
    for sym, cs in data.items():
        if len(cs) < 500: continue
        f = sc.compute_features(cs, cfg)
        for i in range(320, len(cs) - MAXB[tf]):
            d, p_ = f["st_dir"][i], f["st_dir"][i - 1]
            if d and p_ and d != p_:
                rows.append((outcome(f, i, d, tf), sc.signal_price_action(f, i, d), f["t"][i]))
    rows.sort(key=lambda x: x[2]); half = rows[len(rows) // 2][2]
    R = [r for r, _, _ in rows]
    print(f"\n===== {tf} Supertrend · {len(rows)} sinyal · PF {pf(R):.2f} =====", flush=True)
    keys = sorted({k for _, F, _ in rows for k in F})
    res = []
    for k in keys:
        y = [x for x in rows if x[1].get(k) is True]; n = [x for x in rows if x[1].get(k) is False]
        if len(y) < 40 or not n: 
            print(f"{k:18} az ({len(y)})"); continue
        py = pf([r for r, _, _ in y]); pn = pf([r for r, _, _ in n])
        y1 = pf([r for r, _, t in y if t < half]); y2 = pf([r for r, _, t in y if t >= half])
        n1 = pf([r for r, _, t in n if t < half]); n2 = pf([r for r, _, t in n if t >= half])
        cons = "+" if (y1 > n1 and y2 > n2) else ("-" if (y1 < n1 and y2 < n2) else "?")
        print(f"{k:18} var {len(y):5} PF {py:.2f} ({y1:.2f}/{y2:.2f}) · yok PF {pn:.2f} ({n1:.2f}/{n2:.2f}) · fark {py - pn:+.2f} {cons}", flush=True)
