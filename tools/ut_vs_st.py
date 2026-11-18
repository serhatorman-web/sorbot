"""UT Bot Alerts (QuantNomad; ATR 10, Heikin Ashi kapalı) Key 1 ve Key 2 ile Supertrend (10,3) karşılaştırması.
A) Her zaman pozisyonda: ters sinyalde çık + ters yöne gir (göstergelerin kendi kullanımı). İşlem başı %0,10 maliyet.
B) Botun mesaj planı: giriş sinyal kapanışı, stop 1,5 ATR(14), TP1/TP2 = 1R/2R (aynı mumda ikisi varsa stop)."""
import json, time
from concurrent.futures import ThreadPoolExecutor
import scanner as sc

FEE = 0.10
api = sc.Binance()
now_ms = int(time.time() * 1000)
cfg0 = json.load(open("config.json"))
wl = cfg0["universe"]["tradingview_watchlist"]


def rma(x, n):
    out, prev = [None] * len(x), None
    for i in range(len(x)):
        if i == n - 1:
            prev = sum(x[:n]) / n
        elif i >= n:
            prev = (prev * (n - 1) + x[i]) / n
        out[i] = prev
    return out


def ut_bot(h, l, c, key, period=10):
    tr = [h[0] - l[0]] + [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])) for i in range(1, len(c))]
    atr = rma(tr, period)
    stop, sig = [0.0] * len(c), [0] * len(c)
    for i in range(len(c)):
        nl = key * atr[i] if atr[i] is not None else None
        p = stop[i - 1] if i else 0.0
        s1 = c[i - 1] if i else c[i]
        if nl is None:                                   # Pine'da na → hesap NaN; ilk değerler kullanılmaz
            stop[i] = 0.0
            continue
        if c[i] > p and s1 > p:
            stop[i] = max(p, c[i] - nl)
        elif c[i] < p and s1 < p:
            stop[i] = min(p, c[i] + nl)
        else:
            stop[i] = c[i] - nl if c[i] > p else c[i] + nl
        if i and atr[i - 1] is not None:
            if c[i] > stop[i] and c[i] > stop[i] and s1 <= stop[i - 1]:
                sig[i] = 1
            elif c[i] < stop[i] and s1 >= stop[i - 1]:
                sig[i] = -1
    return sig


def st_sigs(f):
    d = f["st_dir"]
    return [0] + [d[i] if d[i] and d[i - 1] and d[i] != d[i - 1] else 0 for i in range(1, len(d))]


def always_in(sig, c, start):
    out, pos, ent, ei = [], 0, None, None
    for i in range(start, len(c)):
        if sig[i] and sig[i] != pos:
            if pos:
                out.append(((c[i] / ent - 1) * 100 * pos - FEE, i - ei))
            pos, ent, ei = sig[i], c[i], i
    return out


def plan(sig, f, start, horizon):
    res = []
    n = len(f["c"])
    for i in range(start, n - 1):
        s = sig[i]
        if not s or not f["atr"][i]:
            continue
        e, risk = f["c"][i], 1.5 * f["atr"][i]
        end = min(n - 1, i + horizon)
        tp1 = r2 = None
        for j in range(i + 1, end + 1):
            fav = ((f["h"][j] - e) if s == 1 else (e - f["l"][j])) / risk
            adv = ((e - f["l"][j]) if s == 1 else (f["h"][j] - e)) / risk
            if adv >= 1:
                tp1 = bool(tp1)
                r2 = -1.0 if r2 is None else r2
                break
            if fav >= 1 and tp1 is None:
                tp1 = True
            if fav >= 2 and r2 is None:
                r2 = 2.0
        if r2 is None:
            r2 = (f["c"][end] - e) * s / risk
        res.append((bool(tp1), r2))
    return res


def one(args):
    sym, tf, days = args
    try:
        bars = days * 86_400_000 // sc.TF_MS[tf] + 300
        cs = sc.fetch_long_history(api, sym, tf, now_ms, bars)
        if len(cs) < 400:
            return None
        f = sc.compute_features(cs, dict(cfg0, timeframe=tf))
    except Exception as e:  # noqa: BLE001
        return {"err": str(e)[:80]}
    start = max(300, len(cs) - days * 86_400_000 // sc.TF_MS[tf])
    hz = {"15m": 192, "1h": 120}[tf]
    out = {"sym": sym}
    sigs = {"UT1": ut_bot(f["h"], f["l"], f["c"], 1), "UT2": ut_bot(f["h"], f["l"], f["c"], 2), "ST": st_sigs(f)}
    for k, sg in sigs.items():
        out[k] = {"ai": always_in(sg, f["c"], start), "plan": plan(sg, f, start, hz)}
    # ST dönüşüne göre UT2 ne zaman geldi
    lead = []
    st, u = sigs["ST"], sigs["UT2"]
    for j in range(start, len(cs)):
        if not st[j]:
            continue
        k = None
        for i in range(j, max(start, j - 40), -1):
            if u[i]:
                k = (j - i) if u[i] == st[j] else None
                break
        if k is None:
            for i in range(j + 1, min(len(cs), j + 40)):
                if u[i]:
                    k = -(i - j) if u[i] == st[j] else None
                    break
        lead.append(k)
    out["lead"] = lead
    return out


def stats(rows, k):
    ai = [t for r in rows for t in r[k]["ai"]]
    pl = [t for r in rows for t in r[k]["plan"]]
    rr = [x for x, _ in ai]
    w = [x for x in rr if x > 0]
    lo = [-x for x in rr if x <= 0]
    hold = sorted(h for _, h in ai)
    return {"sinyal": len(pl), "AI_kazanan_%": round(100 * len(w) / max(1, len(rr)), 1),
            "AI_ort_%": round(sum(rr) / max(1, len(rr)), 3), "AI_kar_faktoru": round(sum(w) / max(1e-9, sum(lo)), 2),
            "AI_medyan_mum": hold[len(hold) // 2] if hold else None,
            "PLAN_TP1_%": round(100 * sum(1 for a, _ in pl if a) / max(1, len(pl)), 1),
            "PLAN_2R_ort_R": round(sum(b for _, b in pl) / max(1, len(pl)), 3)}


# Doğrulama: BTCUSDT 1s Key 2 sinyal zamanları
cs = sc.fetch_long_history(api, "BTCUSDT", "1h", now_ms, 1000)
s2 = ut_bot([x["h"] for x in cs], [x["l"] for x in cs], [x["c"] for x in cs], 2)
print("BTC_UT2", json.dumps(sorted([(cs[i]["t"] // 1000, s2[i]) for i in range(len(cs)) if s2[i] and cs[i]["t"] // 1000 >= 1793916000])))

for tf, days in (("1h", 120), ("15m", 60)):
    with ThreadPoolExecutor(6) as ex:
        rows = [r for r in ex.map(one, [(s, tf, days) for s in wl]) if r and "sym" in r]
    ld = [x for r in rows for x in r["lead"]]
    pos = sorted(x for x in ld if x is not None and x > 0)
    neg = sorted(-x for x in ld if x is not None and x < 0)
    print("SONUC", json.dumps({"tf": tf, "gun": days, "sembol": len(rows),
                                "UT1": stats(rows, "UT1"), "UT2": stats(rows, "UT2"), "SUPERTREND": stats(rows, "ST"),
                                "UT2_once": len(pos), "UT2_once_medyan": pos[len(pos) // 2] if pos else None,
                                "ayni_mum": sum(1 for x in ld if x == 0), "UT2_sonra": len(neg),
                                "UT2_sonra_medyan": neg[len(neg) // 2] if neg else None,
                                "eslesme_yok": sum(1 for x in ld if x is None), "st_donusu": len(ld)}, ensure_ascii=False))
