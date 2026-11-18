"""TrendFlex (Supertrend kapanış üzerinden, çarpan 4, ATR 11) ile Supertrend (10,3) ve (10,4) karşılaştırması.
TF_renk: mum rengi dönüşü · TF_etiket: BUY/SELL etiketi (kesişim + SMA13 filtresi).
A) Her zaman pozisyonda, işlem başı %0,10 maliyet. B) Bot planı: 1,5×ATR(14) stop, 2R hedef. Dönem iki yarıya bölünür."""
import json, sys, time
from concurrent.futures import ThreadPoolExecutor
import scanner as sc
import indicators as ta

FEE = 0.10
TFS = {"15m": (60, 192), "1h": (120, 120), "4h": (365, 60), "1d": (730, 30)}
api = sc.Binance()
now_ms = int(time.time() * 1000)
wl = json.load(open("config.json"))["universe"]["tradingview_watchlist"]


def flips(d):
    return [0] + [d[i] if d[i] and d[i - 1] and d[i] != d[i - 1] else 0 for i in range(1, len(d))]


def evaluate(sig, h, l, c, atr14, start, mid, hz):
    ai = {0: [], 1: []}
    pos, ent, plan, n = 0, None, [], len(c)
    for i in range(start, n):
        s = sig[i]
        if not s or s == pos:
            continue
        if pos:
            ai[0 if i < mid else 1].append((c[i] / ent - 1) * 100 * pos - FEE)
        pos, ent = s, c[i]
        if atr14[i] and i < n - 1:
            e, risk = c[i], 1.5 * atr14[i]
            end = min(n - 1, i + hz)
            r = (c[end] - e) * s / risk
            for j in range(i + 1, end + 1):
                if (((e - l[j]) if s == 1 else (h[j] - e)) / risk) >= 1:
                    r = -1.0
                    break
                if (((h[j] - e) if s == 1 else (e - l[j])) / risk) >= 2:
                    r = 2.0
                    break
            plan.append(r)
    return ai, plan


def one(args):
    sym, tf = args
    days, hz = TFS[tf]
    try:
        cs = sc.fetch_long_history(api, sym, tf, now_ms, days * 86_400_000 // sc.TF_MS[tf] + 300)
    except Exception:  # noqa: BLE001
        return None
    if len(cs) < (260 if tf == "1d" else 400):
        return None
    h, l, c = [x["h"] for x in cs], [x["l"] for x in cs], [x["c"] for x in cs]
    start = max(210 if tf == "1d" else 300, len(cs) - days * 86_400_000 // sc.TF_MS[tf])
    mid = (start + len(cs)) // 2
    atr14 = ta.atr(h, l, c, 14)
    col, line = ta.trendflex(h, l, c, 4.0, 11)
    sma = [None] * len(c)
    for i in range(12, len(c)):
        sma[i] = sum(c[i - 12:i + 1]) / 13
    lab = [ta.trendflex_signal(c, line, sma, i) for i in range(len(c))]
    sigs = {"ST_10x3": flips(ta.supertrend(h, l, c, 10, 3.0)[0]), "ST_10x4": flips(ta.supertrend(h, l, c, 10, 4.0)[0]),
            "TF_renk": flips(col), "TF_etiket": lab}
    return {k: evaluate(v, h, l, c, atr14, start, mid, hz) for k, v in sigs.items()}


def pf(x):
    w = sum(v for v in x if v > 0)
    lo = -sum(v for v in x if v <= 0)
    return round(w / lo, 2) if lo else None


for tf in TFS:
    with ThreadPoolExecutor(6) as ex:
        rows = [r for r in ex.map(one, [(s, tf) for s in wl]) if r]
    res = {}
    for k in rows[0]:
        a0 = [v for r in rows for v in r[k][0][0]]
        a1 = [v for r in rows for v in r[k][0][1]]
        pl = [v for r in rows for v in r[k][1]]
        al = a0 + a1
        res[k] = {"sinyal": len(pl), "pf": pf(al), "pf_yarilar": [pf(a0), pf(a1)],
                  "kazanan_%": round(100 * sum(1 for v in al if v > 0) / max(1, len(al)), 1),
                  "ort_%": round(sum(al) / max(1, len(al)), 3), "plan_R": round(sum(pl) / max(1, len(pl)), 3)}
    print("SONUC", json.dumps({"tf": tf, "sembol": len(rows), **res}, ensure_ascii=False))
    sys.stdout.flush()
