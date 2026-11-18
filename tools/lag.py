"""Supertrend (10,4) dönüşü, (10,3) dönüşüne göre kaç mum geç ve ne kadar kötü fiyattan geliyor?
Ayrıca (10,3)'ün (10,4) tarafından elenen sinyallerinin sonucu (bot planı: 1,5×ATR(14) stop, 2R hedef)."""
import json, sys, time
from concurrent.futures import ThreadPoolExecutor
import scanner as sc
import indicators as ta

TFS = {"15m": (60, 192), "1h": (120, 120)}
api = sc.Binance()
now_ms = int(time.time() * 1000)
wl = json.load(open("config.json"))["universe"]["tradingview_watchlist"]


def flips(d):
    return [0] + [d[i] if d[i] and d[i - 1] and d[i] != d[i - 1] else 0 for i in range(1, len(d))]


def plan_r(i, s, h, l, c, atr14, hz):
    if not atr14[i]:
        return None
    e, risk, n = c[i], 1.5 * atr14[i], len(c)
    end = min(n - 1, i + hz)
    for j in range(i + 1, end + 1):
        if (((e - l[j]) if s == 1 else (h[j] - e)) / risk) >= 1:
            return -1.0
        if (((h[j] - e) if s == 1 else (e - l[j])) / risk) >= 2:
            return 2.0
    return (c[end] - e) * s / risk


def one(args):
    sym, tf = args
    days, hz = TFS[tf]
    try:
        cs = sc.fetch_long_history(api, sym, tf, now_ms, days * 86_400_000 // sc.TF_MS[tf] + 300)
    except Exception:  # noqa: BLE001
        return None
    if len(cs) < 400:
        return None
    h, l, c = [x["h"] for x in cs], [x["l"] for x in cs], [x["c"] for x in cs]
    start = max(300, len(cs) - days * 86_400_000 // sc.TF_MS[tf])
    atr14 = ta.atr(h, l, c, 14)
    d3, d4 = ta.supertrend(h, l, c, 10, 3.0)[0], ta.supertrend(h, l, c, 10, 4.0)[0]
    f3, f4 = flips(d3), flips(d4)
    lags, kept, dropped = [], [], []
    n = len(c)
    for i in range(start, n - 1):
        s = f3[i]
        if not s:
            continue
        # (10,3) bu yönü koruduğu sürece (10,4) aynı yöne dönüyor mu?
        j = None
        for k in range(i, n):
            if k > i and f3[k] and f3[k] != s:
                break
            if f4[k] == s or (k == i and d4[k] == s and d4[k - 1] == s):
                j = k
                break
        r = plan_r(i, s, h, l, c, atr14, hz)
        if j is None:
            if r is not None:
                dropped.append(r)
            continue
        if r is not None:
            kept.append(r)
        if f4[j] == s:
            lags.append((j - i, (c[j] / c[i] - 1) * 100 * s, (c[j] - c[i]) * s / (1.5 * atr14[i]) if atr14[i] else 0))
    return {"lags": lags, "kept": kept, "dropped": dropped}


for tf in TFS:
    with ThreadPoolExecutor(6) as ex:
        rows = [r for r in ex.map(one, [(s, tf) for s in wl]) if r]
    lg = [x for r in rows for x in r["lags"]]
    kp = [x for r in rows for x in r["kept"]]
    dr = [x for r in rows for x in r["dropped"]]
    bars = sorted(x[0] for x in lg)
    pct = sorted(x[1] for x in lg)
    rr = sorted(x[2] for x in lg)
    med = lambda a: a[len(a) // 2] if a else None
    q = lambda a, p: a[int(len(a) * p)] if a else None
    print("SONUC", json.dumps({
        "tf": tf, "eslesen": len(lg),
        "gecikme_mum_medyan": med(bars), "gecikme_mum_ort": round(sum(bars) / max(1, len(bars)), 2),
        "ayni_mum_%": round(100 * sum(1 for b in bars if b == 0) / max(1, len(bars)), 1),
        "fiyat_farki_%_medyan": round(med(pct), 3) if pct else None,
        "fiyat_farki_%_ort": round(sum(pct) / max(1, len(pct)), 3),
        "fiyat_farki_%_p25_p75": [round(q(pct, .25), 3), round(q(pct, .75), 3)] if pct else None,
        "fiyat_farki_R_ort": round(sum(rr) / max(1, len(rr)), 3),
        "korunan_10x3_sinyal": len(kp), "korunan_ort_R": round(sum(kp) / max(1, len(kp)), 3),
        "elenen_10x3_sinyal": len(dr), "elenen_ort_R": round(sum(dr) / max(1, len(dr)), 3),
        "elenen_kazanan_%": round(100 * sum(1 for x in dr if x > 0) / max(1, len(dr)), 1),
        "korunan_kazanan_%": round(100 * sum(1 for x in kp if x > 0) / max(1, len(kp)), 1)}, ensure_ascii=False))
    sys.stdout.flush()
