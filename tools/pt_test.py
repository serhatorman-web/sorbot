"""Grafik resmi işlem planı testi: trend çizgisi + formasyon kırılımlarında 3 plan karşılaştırması.
A: Supertrend gibi (stop 1.5 ATR, TP 1R/2R/3R)
B: Pivot birebir (TP = girişin ötesindeki ilk 3 pivot, stop = gerisindeki ilk pivot)
C: Pivot karma (stop = gerisindeki ilk pivot + 0.1 ATR, 1-2.5 ATR arası; TP = ≥0.5R uzaktaki pivotlar, eksikler +1R)
Pozisyon: 1/3 TP1, 1/3 TP2, 1/3 TP3; stop sabit; aynı mumda stop ve TP varsa önce stop sayılır. Giriş: kırılım mumu kapanışı."""
import os, sys, time
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as S
import indicators as ta
import patterns as pt

SYMS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT", "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT",
        "LTCUSDT", "BCHUSDT", "NEARUSDT", "SUIUSDT", "APTUSDT", "ARBUSDT", "OPUSDT", "INJUSDT", "TIAUSDT", "SEIUSDT",
        "WIFUSDT", "1000PEPEUSDT", "ENAUSDT", "HYPEUSDT", "ZECUSDT", "AAVEUSDT", "UNIUSDT", "FETUSDT", "TAOUSDT",
        "RENDERUSDT", "ONDOUSDT", "JUPUSDT", "TRUMPUSDT", "FILUSDT", "ETCUSDT", "XLMUSDT", "HBARUSDT", "ATOMUSDT",
        "XAUUSDT", "XAGUSDT", "NATGASUSDT", "CLUSDT", "NVDAUSDT", "TSLAUSDT", "AAPLUSDT", "MSTRUSDT", "COINUSDT", "AMDUSDT"]
SPAN = {"15m": 30, "1h": 20, "4h": 10}
NAMES = ("R3", "R2", "R1", "P", "S1", "S2", "S3")
api = S.Binance()
now_ms = int(time.time() * 1000)


def kl(sym, tf, lim):
    return S.parse_klines(api.get("/fapi/v1/klines", {"symbol": sym, "interval": tf, "limit": lim}), now_ms)


def piv_map(per_c):
    """dönem başlangıcı -> önceki dönemin HLC'sinden pivotlar"""
    m = {}
    for k in range(1, len(per_c)):
        p = per_c[k - 1]
        m[per_c[k]["t"]] = S.pivot_levels(p["h"], p["l"], p["c"])
    return m


def sim(cs, i, d, entry, stop, tps, maxb=300):
    left, pnl, hit = 3, 0.0, 0
    for k in range(i + 1, min(len(cs), i + 1 + maxb)):
        hi, lo = cs[k]["h"], cs[k]["l"]
        if (lo <= stop) if d == 1 else (hi >= stop):
            pnl += left / 3 * (stop - entry) * d / entry * 100
            return pnl, hit, "stop"
        while hit < 3 and ((hi >= tps[hit]) if d == 1 else (lo <= tps[hit])):
            pnl += (tps[hit] - entry) * d / entry * 100 / 3
            hit += 1
            left -= 1
        if hit == 3:
            return pnl, hit, "tp3"
    last = cs[min(len(cs), i + 1 + maxb) - 1]["c"]
    pnl += left / 3 * (last - entry) * d / entry * 100
    return pnl, hit, "time"


def plans(d, entry, a, pv):
    out = {}
    r = 1.5 * a
    out["A"] = (entry - d * r, [entry + d * r * m for m in (1, 2, 3)])
    lv = [pv[nm] for nm in NAMES]
    ahead = sorted((v for v in lv if (v - entry) * d > 0), key=lambda v: abs(v - entry))
    behind = sorted((v for v in lv if (entry - v) * d > 0), key=lambda v: abs(v - entry))
    out["B"] = (behind[0], ahead[:3]) if behind and len(ahead) >= 3 else None
    if behind:
        sd = abs(entry - behind[0]) + 0.1 * a
    else:
        sd = 1.5 * a
    sd = min(max(sd, 1.0 * a), 2.5 * a)
    st = entry - d * sd
    tp = [v for v in ahead if abs(v - entry) >= 0.5 * sd][:3]
    while len(tp) < 3:
        tp.append((tp[-1] if tp else entry) + d * sd)
    out["C"] = (st, tp)
    return out


def run(sym, tf):
    try:
        cs = kl(sym, tf, 1500)
        per_tf = "1d" if tf == "15m" else "1w"
        pm = piv_map(kl(sym, per_tf, 400))
    except Exception as e:  # noqa: BLE001
        return []
    per = 86_400_000 if tf == "15m" else 7 * 86_400_000
    res, seen = [], set()
    v = [x["v"] for x in cs]
    for i in range(300, len(cs) - 1):
        lo = i - 299
        w = cs[lo:i + 1]
        h = [x["h"] for x in w]; l = [x["l"] for x in w]; c = [x["c"] for x in w]
        vm = sum(v[i - 20:i]) / 20
        if not vm or v[i] / vm < 1.5:
            continue
        a = ta.atr(h, l, c, 14)
        ai = a[-1]
        pv = pm.get(S.pivot_period_start(cs[i]["t"], per))
        if not ai or not pv:
            continue
        evs = []
        for ev in ta.trendlines_close(h, l, c):
            if ev["state"] == "broken" and ev["bars_ago"] == 0 and ev["touches"] >= 2 and ev["b"] - ev["a"] >= SPAN[tf]:
                key = ("tl", ev["type"], lo + ev["a"])
                if key not in seen:
                    seen.add(key)
                    evs.append(("trend", 1 if ev["type"] == "falling" else -1))
        for g in pt.chart_patterns(h, l, c, a):
            kb = (g.get("ciz") or {}).get("kb")
            if g["durum"] == "kirildi" and kb == len(c) - 1 and g["ad"] not in ("Fincan Kulp", "Ters Fincan Kulp"):
                key = ("fm", g["ad"], i)
                if key not in seen:
                    seen.add(key)
                    evs.append(("formasyon", g["kirilim"]))
        for kind, d in evs:
            for name, p in plans(d, c[-1], ai, pv).items():
                if p is None:
                    res.append((tf, kind, name, None))
                    continue
                st, tp = p
                pnl, hit, how = sim(cs, i, d, c[-1], st, tp)
                risk = abs(c[-1] - st) / c[-1] * 100
                res.append((tf, kind, name, (pnl, hit, how, risk)))
    return res


jobs = [(s, tf) for tf in ("15m", "1h", "4h") for s in SYMS]
allr = []
with ThreadPoolExecutor(max_workers=6) as ex:
    for r in ex.map(lambda j: run(*j), jobs):
        allr.extend(r)


def rep(label, rows):
    for name in ("A", "B", "C"):
        rr = [x[3] for x in rows if x[2] == name]
        ok = [x for x in rr if x]
        if not ok:
            print("XX|", label, name, "yok"); continue
        n = len(ok)
        avg = sum(x[0] for x in ok) / n
        rexp = sum(x[0] / x[3] for x in ok) / n
        tp1 = sum(1 for x in ok if x[1] >= 1) / n * 100
        tp3 = sum(1 for x in ok if x[1] == 3) / n * 100
        st0 = sum(1 for x in ok if x[1] == 0 and x[2] == "stop") / n * 100
        win = sum(1 for x in ok if x[0] > 0) / n * 100
        gp = sum(x[0] for x in ok if x[0] > 0); gl = -sum(x[0] for x in ok if x[0] < 0)
        risk = sum(x[3] for x in ok) / n
        print("XX|", label, name, f"n={n} atlanan={len(rr)-n} ort={avg:+.3f}% R={rexp:+.3f} kazanan={win:.0f}% "
              f"TP1={tp1:.0f}% TP3={tp3:.0f}% direktstop={st0:.0f}% PF={gp/gl if gl else 0:.2f} ortstop={risk:.2f}%")


rep("TUMU", allr)
for tf in ("15m", "1h", "4h"):
    rep(tf, [x for x in allr if x[0] == tf])
for kind in ("trend", "formasyon"):
    rep(kind, [x for x in allr if x[1] == kind])
