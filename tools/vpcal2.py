"""Geçici teşhis: 4s Teometric kalibrasyonu – 4 sembol x 3 seviye."""
import sys, os, time, itertools
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as sc
api = sc.Binance(); H4 = 4 * 3600 * 1000
SHOT = int(time.time() * 1000)
TARGET = {"BTCUSDT": (85857.1, 81215.3, 76573.5), "ETHUSDT": (2556.77, 2435.55, 2233.52),
          "SOLUSDT": (110.49, 103.80, 79.26), "XRPUSDT": (1.5134, 1.2992, 1.1653)}

def m1_range(sym, start, end):
    out, t = [], start
    while t < end:
        raw = api.get("/fapi/v1/klines", {"symbol": sym, "interval": "1m", "startTime": t, "limit": 1500})
        if not raw: break
        out += [(int(k[0]), float(k[2]), float(k[3]), float(k[7]), float(k[5])) for k in raw if int(k[0]) < end]
        t = int(raw[-1][0]) + 60000
    return out

def profile(hi, lo, items, rows=24):
    step = (hi - lo) / rows; vol = [0.0] * rows
    for h, l, v in items:
        if h <= l:
            vol[min(rows - 1, max(0, int((h - lo) / step)))] += v; continue
        for r in range(max(0, int((l - lo) / step)), min(rows - 1, int((h - lo) / step)) + 1):
            ov = min(lo + (r + 1) * step, h) - max(lo + r * step, l)
            if ov > 0: vol[r] += v * ov / (h - l)
    return step, vol

def va1(vol, va=0.7):
    rows = len(vol); poc = max(range(rows), key=lambda r: vol[r]); a = b = poc; acc = vol[poc]; tot = sum(vol)
    while acc < va * tot and (a > 0 or b < rows - 1):
        up = vol[b + 1] if b < rows - 1 else -1; dn = vol[a - 1] if a > 0 else -1
        if up >= dn: b += 1; acc += up
        else: a -= 1; acc += dn
    return b, poc, a

def va2(vol, va=0.7):          # TradingView: iki satır birden karşılaştırılır
    rows = len(vol); poc = max(range(rows), key=lambda r: vol[r]); a = b = poc; acc = vol[poc]; tot = sum(vol)
    while acc < va * tot and (a > 0 or b < rows - 1):
        up = sum(vol[b + 1:min(rows, b + 3)]) if b < rows - 1 else -1
        dn = sum(vol[max(0, a - 2):a]) if a > 0 else -1
        if up >= dn: b = min(rows - 1, b + 2); acc += up
        else: a = max(0, a - 2); acc += dn
    return b, poc, a

res = {}
for sym, tgt in TARGET.items():
    raw = api.get("/fapi/v1/klines", {"symbol": sym, "interval": "4h", "endTime": SHOT, "limit": 400})
    bars = [(int(k[0]), float(k[2]), float(k[3]), float(k[7]), float(k[5])) for k in raw]
    m1 = m1_range(sym, bars[-330][0], SHOT)
    for n in range(140, 330):
        for incl in (0, 1):
            w = bars[-n:] if incl else bars[-n - 1:-1]
            s = w[0][0]; e = w[-1][0] + H4
            mm = [x for x in m1 if s <= x[0] < e]
            hi = max(x[1] for x in (mm if incl else w)); lo = min(x[2] for x in (mm if incl else w))
            for dist in ("mum", "1dk"):
                for vk, vi in (("usdt", 3), ("adet", 4)):
                    items = [(x[1], x[2], x[vi]) for x in (w if dist == "mum" else mm)]
                    step, vol = profile(hi, lo, items)
                    for vname, f in (("va1", va1), ("va2", va2)):
                        b, p, a = f(vol)
                        vals = [lo + (r + 0.5) * step for r in (b, p, a)]
                        ok = sum(1 for x, t in zip(vals, tgt) if abs(x - t) / t < 0.0008)
                        res.setdefault((n, incl, dist, vk, vname), {})[sym] = (ok, [round(x, 4) for x in vals])
for sym in TARGET:
    rows = [(v[sym][0], k) for k, v in res.items() if sym in v]
    top = max(r[0] for r in rows)
    ks = sorted(k for o, k in rows if o == top)
    print(sym, "en iyi", top, "/3:", len(ks), "kombinasyon")
    for k in ks[:12]:
        print("   n=%d oluşan_dahil=%d dağılım=%s hacim=%s %s" % k, res[k][sym][1])
