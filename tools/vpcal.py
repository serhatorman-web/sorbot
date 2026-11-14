"""Geçici teşhis: 4s pencere kalibrasyonu, 1 dakikalık hacim dağılımıyla (göstergenin LTF 1dk ayarı gibi)."""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as sc, indicators as ta
api = sc.Binance()
H4 = 4 * 3600 * 1000

def m1_range(sym, start, end):
    out, t = [], start
    while t < end:
        raw = api.get("/fapi/v1/klines", {"symbol": sym, "interval": "1m", "startTime": t, "limit": 1500})
        if not raw: break
        out += [{"t": int(k[0]), "h": float(k[2]), "l": float(k[3]), "v": float(k[7])} for k in raw if int(k[0]) < end]
        t = int(raw[-1][0]) + 60000
    return out

def vp_1m(bars4, m1, rows=24, va=0.7):
    hi, lo = max(b["h"] for b in bars4), min(b["l"] for b in bars4)
    step = (hi - lo) / rows; vol = [0.0] * rows
    for x in m1:
        if x["h"] <= x["l"]:
            vol[min(rows - 1, max(0, int((x["h"] - lo) / step)))] += x["v"]; continue
        for r in range(max(0, int((x["l"] - lo) / step)), min(rows - 1, int((x["h"] - lo) / step)) + 1):
            ov = min(lo + (r + 1) * step, x["h"]) - max(lo + r * step, x["l"])
            if ov > 0: vol[r] += x["v"] * ov / (x["h"] - x["l"])
    poc = max(range(rows), key=lambda r: vol[r]); a = b = poc; acc = vol[poc]; tot = sum(vol)
    while acc < va * tot and (a > 0 or b < rows - 1):
        up = vol[b + 1] if b < rows - 1 else -1; dn = vol[a - 1] if a > 0 else -1
        if up >= dn: b += 1; acc += up
        else: a -= 1; acc += dn
    m = lambda r: round(lo + (r + 0.5) * step, 2)
    return m(b), m(poc), m(a)

# (sembol, ekran görüntüsü zamanı UTC ms, hedef, indeks: 0 VAH / 2 VAL)
cases = [("GOOGLUSDT", 1794687420000, 315.08, 0), ("BTCUSDT", 1794678060000, 76573.5, 2)]
for sym, shot, target, idx in cases:
    raw = api.get("/fapi/v1/klines", {"symbol": sym, "interval": "4h", "endTime": shot, "limit": 300})
    bars = [{"t": int(k[0]), "h": float(k[2]), "l": float(k[3]), "v": float(k[7])} for k in raw]
    closed = [b for b in bars if b["t"] + H4 <= shot]
    forming = [b for b in bars if b["t"] + H4 > shot]
    m1 = m1_range(sym, closed[-265]["t"], shot)
    print(f"== {sym} hedef {target} (kapanmış {len(closed)}, oluşan {len(forming)})")
    for n in range(240, 262):
        w = closed[-n:]; s = w[0]["t"]
        r_c = vp_1m(w, [x for x in m1 if s <= x["t"] < w[-1]["t"] + H4])
        wf = closed[-(n - 1):] + forming        # oluşan mum dahil n mum
        sf = wf[0]["t"]
        # oluşan mumun aralığı 1dk verisinden
        if forming:
            fm = [x for x in m1 if x["t"] >= forming[0]["t"]]
            wf = wf[:-1] + [{"h": max(x["h"] for x in fm), "l": min(x["l"] for x in fm)}]
        r_f = vp_1m(wf, [x for x in m1 if sf <= x["t"] < shot])
        r_k = ta.volume_profile([b["h"] for b in w], [b["l"] for b in w], [b["v"] for b in w], 24, 0.7)
        print(f"n={n} kapanmış(1dk)={r_c} {'✓' if abs(r_c[idx]-target)/target<0.002 else ' '} | "
              f"oluşan dahil(1dk)={r_f} {'✓' if abs(r_f[idx]-target)/target<0.002 else ' '} | "
              f"mum={[round(x,2) for x in r_k]} {'✓' if abs(r_k[idx]-target)/target<0.002 else ' '}", flush=True)
