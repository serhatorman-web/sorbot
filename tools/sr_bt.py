"""Geçici test: YAPI DÖNÜŞÜ sinyali."""
import sys, os, json, time
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as sc, indicators as ta
api = sc.Binance(); cfg0 = json.load(open("config.json"))
NB = {"15m": 2900, "1h": 2900, "4h": 1490}; MAXB = {"15m": 96, "1h": 72, "4h": 42}; COST = 0.001
tick = api.get("/fapi/v1/ticker/24hr")
info = {s["symbol"]: s for s in api.get("/fapi/v1/exchangeInfo")["symbols"]}
syms = [t["symbol"] for t in sorted(tick, key=lambda t: -float(t["quoteVolume"]))
        if t["symbol"] in info and info[t["symbol"]].get("underlyingType") == "COIN" and float(t["quoteVolume"]) >= 3e6][:150]
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
def outcome(f, i, s, e, sl, tf):
    risk = abs(e - sl); tps = [e + s * risk * r for r in (1, 2, 3)]; best, stop = 0, sl
    for k in range(i + 1, i + 1 + MAXB[tf]):
        h, l = f["h"][k], f["l"][k]
        hit = (l <= stop) if s == 1 else (h >= stop)
        reach = max([m for m, tp in enumerate(tps, 1) if ((h >= tp) if s == 1 else (l <= tp))], default=0)
        if hit: return (-1 if best == 0 else sum(range(1, best + 1)) / 3) - COST * e / risk, best
        if reach > best:
            best = reach; stop = e
            if best == 3: return 2.0 - COST * e / risk, 3
    end = i + MAXB[tf]
    return (sum(range(1, best + 1)) / 3 if best else (f["c"][end] - e) * s / risk) - COST * e / risk, best
pf = lambda R: (sum(r for r in R if r > 0) / -sum(r for r in R if r < 0)) if any(r < 0 for r in R) else 99
def line(nm, rows, half):
    if not rows: return f"{nm:40} –"
    R = [o[0] for o, *_ in rows]; n = len(R); tp1 = sum(1 for o, *_ in rows if o[1] >= 1); st = sum(1 for o, *_ in rows if o[0] <= -0.99)
    h1 = [o[0] for o, t, *_ in rows if t < half]; h2 = [o[0] for o, t, *_ in rows if t >= half]
    return f"{nm:40} {n:5} · TP1 %{tp1*100/n:4.1f} · Stop %{st*100/n:4.1f} · ort {sum(R)/n:+.2f}R · PF {pf(R):.2f} · yarılar {pf(h1) if h1 else 0:.2f}/{pf(h2) if h2 else 0:.2f}"
VARS = [("piv3 hacim1.5x", 3, 1.5), ("piv3 hacim1.0x", 3, 1.0), ("piv3 hacim2.0x", 3, 2.0), ("piv2 hacim1.5x", 2, 1.5)]
for tf in ("15m", "1h", "4h"):
    cfg = dict(cfg0, timeframe=tf)
    with ThreadPoolExecutor(6) as ex:
        data = dict(zip(syms, ex.map(lambda s: fetch(s, tf), syms)))
    feats = {s: sc.compute_features(cs, cfg) for s, cs in data.items() if len(cs) > 400}
    allt = sorted(t for f in feats.values() for t in f["t"]); half = allt[len(allt) // 2]
    st_rows = []
    for f in feats.values():
        for i in range(320, len(f["c"]) - MAXB[tf]):
            d, p_ = f["st_dir"][i], f["st_dir"][i - 1]
            if d and p_ and d != p_:
                st_rows.append((outcome(f, i, d, f["c"][i], f["c"][i] - d * 1.5 * f["atr"][i], tf), f["t"][i]))
    print(f"\n========== {tf} · {len(feats)} coin ==========")
    print(line("Supertrend (karşılaştırma)", st_rows, half), flush=True)
    for nm, piv, vx in VARS:
        for d, s_ in (("LONG", 1), ("SHORT", -1)):
            rows, rows_cap, early_n, late_n, adv = [], [], 0, 0, []
            for f in feats.values():
                for i in range(320, len(f["c"]) - MAXB[tf]):
                    ev = ta.structure_reversal(f["h"][:i+1], f["l"][:i+1], f["c"][:i+1], f["v"][:i+1], f["vol_ma"][:i+1], s_, piv, 80, vx)
                    if not ev: continue
                    a = f["atr"][i]; sl = ev["l2_price"] - s_ * 0.2 * a; e = f["c"][i]
                    if (e - sl) * s_ <= 0: continue
                    o = outcome(f, i, s_, e, sl, tf)
                    rows.append((o, f["t"][i]))
                    risk = abs(e - sl)
                    if risk <= 3 * a and risk / e * 100 <= 5: rows_cap.append((o, f["t"][i]))
                    # Supertrend'e göre zamanlama
                    if f["st_dir"][i] == s_:
                        late_n += 1
                    else:
                        nx = next((k for k in range(i + 1, min(len(f["c"]), i + 40)) if f["st_dir"][k] == s_), None)
                        if nx is not None:
                            early_n += 1; adv.append((f["c"][nx] - e) / e * s_ * 100)
            print(line(f"{nm} {d}", rows, half))
            print(line(f"   + stop ≤3 ATR ve ≤%5", rows_cap, half))
            if adv:
                adv.sort()
                print(f"   Supertrend'den önce: {early_n} ({early_n*100/max(1,len(rows)):.0f}%) · ST zaten dönmüş: {late_n} · ST'ye göre giriş avantajı ort %{sum(adv)/len(adv):+.2f}, medyan %{adv[len(adv)//2]:+.2f}", flush=True)
