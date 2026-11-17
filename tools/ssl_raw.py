"""SSL Hybrid Advanced (SSL-HYBRID, NO-FILTER) kendi Buy/Sell sinyalleri ile Supertrend (10,3) karşılaştırması.
Her ikisi de 'her zaman pozisyonda' (ters sinyalde çık + ters yöne gir). Komisyon+kayma: işlem başı %0,10."""
import json, sys, time
from concurrent.futures import ThreadPoolExecutor
import scanner as sc

FEE = 0.10
api = sc.Binance()
now_ms = int(time.time() * 1000)
cfg0 = json.load(open("config.json"))
wl = cfg0["universe"]["tradingview_watchlist"]


def ssl_sigs(f):
    c, s = f["c"], f["ssl"]
    out = [0] * len(c)
    for i in range(1, len(c)):
        if s[i] is None or s[i - 1] is None:
            continue
        if c[i] > s[i] and c[i - 1] <= s[i - 1]:
            out[i] = 1
        elif c[i] < s[i] and c[i - 1] >= s[i - 1]:
            out[i] = -1
    return out


def st_sigs(f):
    d = f["st_dir"]
    return [0] + [d[i] if d[i] and d[i - 1] and d[i] != d[i - 1] else 0 for i in range(1, len(d))]


def trades(sig, c, start):
    out, pos, ent, ei = [], 0, None, None
    for i in range(start, len(c)):
        if sig[i] and sig[i] != pos:
            if pos:
                out.append(((c[i] / ent - 1) * 100 * pos - FEE, i - ei))
            pos, ent, ei = sig[i], c[i], i
    return out


def one(args):
    sym, tf, days = args
    try:
        bars = days * 86_400_000 // sc.TF_MS[tf] + 300
        cs = sc.fetch_long_history(api, sym, tf, now_ms, bars)
        if len(cs) < 400:
            return None
        cfg = dict(cfg0, timeframe=tf)
        f = sc.compute_features(cs, cfg)
    except Exception as e:  # noqa: BLE001
        return {"err": str(e)[:80]}
    start = max(300, len(cs) - days * 86_400_000 // sc.TF_MS[tf])
    a, b = ssl_sigs(f), st_sigs(f)
    lead = []
    for j in range(start, len(cs)):
        if not b[j]:
            continue
        s = b[j]
        k = None
        for i in range(j, max(start, j - 40), -1):          # ST dönüşünden önceki son SSL sinyali
            if a[i]:
                k = i if a[i] == s else None
                break
        if k is not None:
            lead.append(j - k)
        else:
            for i in range(j + 1, min(len(cs), j + 40)):    # SSL sonra mı geldi?
                if a[i]:
                    lead.append(-(i - j) if a[i] == s else None)
                    break
            else:
                lead.append(None)
    return {"sym": sym, "ssl": trades(a, f["c"], start), "st": trades(b, f["c"], start), "lead": lead}


def stats(ts):
    if not ts:
        return {}
    r = [x for x, _ in ts]
    w = [x for x in r if x > 0]
    l = [-x for x in r if x <= 0]
    hold = sorted(h for _, h in ts)
    return {"islem": len(r), "kazanan_%": round(100 * len(w) / len(r), 1), "ort_%": round(sum(r) / len(r), 3),
            "ort_kazanc_%": round(sum(w) / max(1, len(w)), 2), "ort_kayip_%": round(sum(l) / max(1, len(l)), 2),
            "kar_faktoru": round(sum(w) / max(1e-9, sum(l)), 2), "medyan_mum": hold[len(hold) // 2]}


# 1) Doğrulama: BTCUSDT 1s sinyal zamanları (TradingView ile karşılaştırma için)
cs = sc.fetch_long_history(api, "BTCUSDT", "1h", now_ms, 700)
f = sc.compute_features(cs, dict(cfg0, timeframe="1h"))
sg = ssl_sigs(f)
print("BTC_SSL", json.dumps([(cs[i]["t"] // 1000, sg[i]) for i in range(len(cs)) if sg[i] and cs[i]["t"] // 1000 >= 1794229200]))

for tf, days in (("1h", 120), ("15m", 60)):
    with ThreadPoolExecutor(6) as ex:
        rows = [r for r in ex.map(one, [(s, tf, days) for s in wl]) if r and "sym" in r]
    ssl_t = [t for r in rows for t in r["ssl"]]
    st_t = [t for r in rows for t in r["st"]]
    ld = [x for r in rows for x in r["lead"]]
    pos = sorted(x for x in ld if x is not None and x > 0)
    zero = sum(1 for x in ld if x == 0)
    neg = sorted(-x for x in ld if x is not None and x < 0)
    none = sum(1 for x in ld if x is None)
    print("SONUC", json.dumps({"tf": tf, "gun": days, "sembol": len(rows), "SSL": stats(ssl_t), "SUPERTREND": stats(st_t),
                                "st_donusu": len(ld), "ssl_once": len(pos), "ssl_once_medyan_mum": pos[len(pos) // 2] if pos else None,
                                "ayni_mum": zero, "ssl_sonra": len(neg), "ssl_sonra_medyan_mum": neg[len(neg) // 2] if neg else None,
                                "eslesme_yok": none}, ensure_ascii=False))
