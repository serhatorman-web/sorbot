"""Supertrend ayar taraması: ATR periyodu × çarpan, 15dk / 1s / 4s / 1g, listedeki tüm semboller.
A) Her zaman pozisyonda (dönüşte ters yöne geç), işlem başı %0,10 maliyet → kâr faktörü, ortalama %, işlem sayısı.
B) Botun mesaj planı: giriş dönüş mumu kapanışı, stop 1,5×ATR(14), 2R hedef (aynı mumda ikisi varsa stop).
Sağlamlık: dönem ikiye bölünür, iki yarıdaki kâr faktörü ayrı yazılır (tek dönemde iyi görünüp diğerinde kötü olan ayar ezberdir)."""
import json, sys, time
from concurrent.futures import ThreadPoolExecutor
import scanner as sc

FEE = 0.10
PERIODS = (7, 10, 14, 20)
MULTS = (2.0, 2.5, 3.0, 3.5, 4.0)
TFS = {"15m": (60, 192), "1h": (120, 120), "4h": (365, 60), "1d": (730, 30)}
api = sc.Binance()
now_ms = int(time.time() * 1000)
wl = json.load(open("config.json"))["universe"]["tradingview_watchlist"]


def rma_atr(h, l, c, n):
    tr = [h[0] - l[0]] + [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])) for i in range(1, len(c))]
    out, prev = [None] * len(c), None
    for i in range(len(c)):
        if i == n - 1:
            prev = sum(tr[:n]) / n
        elif i >= n:
            prev = (prev * (n - 1) + tr[i]) / n
        out[i] = prev
    return out


def supertrend_dir(h, l, c, atr, m):
    """TradingView ta.supertrend ile aynı mantık: +1 yükseliş, -1 düşüş."""
    n = len(c)
    d = [0] * n
    up = dn = None
    for i in range(n):
        a = atr[i]
        if a is None:
            continue
        src = (h[i] + l[i]) / 2
        u, w = src - m * a, src + m * a
        if up is not None and c[i - 1] > up:
            u = max(u, up)
        if dn is not None and c[i - 1] < dn:
            w = min(w, dn)
        prev = d[i - 1] if i else 0
        if prev == 0:
            nd = 1
        elif prev == -1:
            nd = 1 if c[i] > dn else -1
        else:
            nd = -1 if c[i] < up else 1
        d[i], up, dn = nd, u, w
    return d


def evaluate(d, h, l, c, atr14, start, mid, hz):
    ai = {0: [], 1: []}
    pos, ent = 0, None
    plan = []
    n = len(c)
    for i in range(start, n):
        if not (d[i] and d[i - 1] and d[i] != d[i - 1]):
            continue
        s = d[i]
        half = 0 if i < mid else 1
        if pos:
            ai[half].append((c[i] / ent - 1) * 100 * pos - FEE)
        pos, ent = s, c[i]
        if atr14[i] and i < n - 1:
            e, risk = c[i], 1.5 * atr14[i]
            end = min(n - 1, i + hz)
            r = (c[end] - e) * s / risk
            for j in range(i + 1, end + 1):
                adv = ((e - l[j]) if s == 1 else (h[j] - e)) / risk
                fav = ((h[j] - e) if s == 1 else (e - l[j])) / risk
                if adv >= 1:
                    r = -1.0
                    break
                if fav >= 2:
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
    atr14 = rma_atr(h, l, c, 14)
    out = {}
    for p in PERIODS:
        atr = rma_atr(h, l, c, p)
        for m in MULTS:
            out[f"{p}x{m}"] = evaluate(supertrend_dir(h, l, c, atr, m), h, l, c, atr14, start, mid, hz)
    return out


def pf(x):
    w = sum(v for v in x if v > 0)
    lo = -sum(v for v in x if v <= 0)
    return round(w / lo, 2) if lo else None


for tf in TFS:
    with ThreadPoolExecutor(6) as ex:
        rows = [r for r in ex.map(one, [(s, tf) for s in wl]) if r]
    res = []
    for k in rows[0]:
        a0 = [v for r in rows for v in r[k][0][0]]
        a1 = [v for r in rows for v in r[k][0][1]]
        pl = [v for r in rows for v in r[k][1]]
        al = a0 + a1
        res.append({"ayar": k, "islem": len(al), "pf": pf(al), "pf_1yari": pf(a0), "pf_2yari": pf(a1),
                    "ort_%": round(sum(al) / max(1, len(al)), 3), "kazanan_%": round(100 * sum(1 for v in al if v > 0) / max(1, len(al)), 1),
                    "plan_R": round(sum(pl) / max(1, len(pl)), 3)})
    res.sort(key=lambda x: -(x["pf"] or 0))
    print("SONUC", json.dumps({"tf": tf, "sembol": len(rows), "sonuclar": res}, ensure_ascii=False))
    sys.stdout.flush()
