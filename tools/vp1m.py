"""Geçici teşhis: GOOGL 4s hacim profili, 4s mum ile ve 1 dakikalık veriyle."""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as sc, indicators as ta
api = sc.Binance(); now = int(time.time() * 1000)
for sym in ("GOOGLUSDT", "BTCUSDT", "ZROUSDT"):
  for tf, ms in (("4h", 4*3600e3), ("1h", 3600e3), ("15m", 900e3)):
    cs = sc.parse_klines(api.get("/fapi/v1/klines", {"symbol": sym, "interval": tf, "limit": 151}), now)[-150:]
    a = ta.volume_profile([x["h"] for x in cs], [x["l"] for x in cs], [x["v"] for x in cs], 24, 0.7)
    start, end = cs[0]["t"], cs[-1]["t"] + int(ms)
    m1 = []; t = start
    while t < end:
        raw = api.get("/fapi/v1/klines", {"symbol": sym, "interval": "1m", "startTime": t, "limit": 1500})
        if not raw: break
        m1 += [x for x in sc.parse_klines(raw, end + 1)]
        t = int(raw[-1][0]) + 60000
    m1 = [x for x in m1 if start <= x["t"] < end]
    hi, lo = max(x["h"] for x in cs), min(x["l"] for x in cs)
    # 1 dakikalık: her 1dk mumun hacmi kendi aralığına; profil aralığı = 4s mumların aralığı
    rows = 24; step = (hi - lo) / rows; vol = [0.0] * rows
    for x in m1:
        lo_r = max(0, min(rows - 1, int((x["l"] - lo) / step))); hi_r = max(0, min(rows - 1, int((x["h"] - lo) / step)))
        span = (x["h"] - x["l"]) or 1e-12
        for r in range(lo_r, hi_r + 1):
            b0, b1 = lo + r * step, lo + (r + 1) * step
            ov = (min(b1, x["h"]) - max(b0, x["l"])) if x["h"] > x["l"] else (1 if r == lo_r else 0)
            vol[r] += x["v"] * (ov / span if x["h"] > x["l"] else ov)
    poc = max(range(rows), key=lambda r: vol[r]); tot = sum(vol); acc = vol[poc]; i0 = i1 = poc
    while acc < 0.7 * tot:
        up = vol[i1 + 1] if i1 + 1 < rows else -1; dn = vol[i0 - 1] if i0 > 0 else -1
        if up >= dn: i1 += 1; acc += up
        else: i0 -= 1; acc += dn
    mid = lambda r: lo + (r + 0.5) * step
    print(f"{sym} {tf}: 4s-mum VAH/POC/VAL = {[round(x, 4) for x in a]} | 1dk = {[round(mid(i1),4), round(mid(poc),4), round(mid(i0),4)]} | 1dk mum sayısı {len(m1)}/{int((end-start)/60000)}", flush=True)
