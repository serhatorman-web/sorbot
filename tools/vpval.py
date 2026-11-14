"""Geçici teşhis: botun hacim profili kodu – 15dk ve 1s ekran görüntüleri."""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as sc
api = sc.Binance(); cfg0 = json.load(open("config.json"))
def candles_at(sym, tf, ms, shot):
    raw = api.get("/fapi/v1/klines", {"symbol": sym, "interval": tf, "endTime": shot, "limit": 499})
    cs = [{"t": int(k[0]), "o": float(k[1]), "h": float(k[2]), "l": float(k[3]), "c": float(k[4]),
           "v": float(k[7]), "bv": float(k[5])} for k in raw]
    last = cs[-1]
    if last["t"] + ms > shot:
        m1 = api.get("/fapi/v1/klines", {"symbol": sym, "interval": "1m", "startTime": last["t"], "endTime": shot - 1, "limit": 1500})
        if m1:
            cs[-1] = {"t": last["t"], "o": float(m1[0][1]), "h": max(float(k[2]) for k in m1), "l": min(float(k[3]) for k in m1),
                      "c": float(m1[-1][4]), "v": sum(float(k[7]) for k in m1), "bv": sum(float(k[5]) for k in m1)}
        else:
            cs = cs[:-1]
    return cs
T = {("BTCUSDT", "1h"): (76795.4, 76119.6, 68685.9), ("BTCUSDT", "15m"): (70482.9, 68849.1, 65173.2),
     ("ETHUSDT", "1h"): (2223.04, 2116.25, 1822.60), ("ETHUSDT", "15m"): (2027.44, 1933.09, 1885.91),
     ("SOLUSDT", "1h"): (90.87, 89.75, 78.54), ("SOLUSDT", "15m"): (83.29, 81.50, 75.53),
     ("XRPUSDT", "1h"): (1.1627, 1.0600, 0.9574), ("XRPUSDT", "15m"): (1.0434, 1.0258, 0.9847)}
MS = {"1h": 3600e3, "15m": 900e3}
SHOTS = [1794688800000, 1794689100000, 1794689280000, 1794689400000, 1794689520000, 1794689580000]
tot = ok = 0
for (sym, tf), tgt in T.items():
    best = None
    for shot in SHOTS:
        cs = candles_at(sym, tf, MS[tf], shot)
        cfg = dict(cfg0, timeframe=tf)
        f = sc.compute_features(cs, cfg); res = {"f": f, "i": len(cs) - 1, "meta": {"symbol": sym}}
        sc.compute_volume_profile(res, cfg)
        got = res["vp"]; n = sum(1 for g, t in zip(got, tgt) if abs(g - t) / t < 0.0003)
        if best is None or n > best[0]: best = (n, shot, got)
    n, shot, got = best; tot += 3; ok += n
    marks = " ".join("✓" if abs(g - t) / t < 0.0003 else "✗" for g, t in zip(got, tgt))
    print(f"{sym} {tf}: bot {[round(x, 4) for x in got]} gösterge {tgt} {marks} (an {shot})")
print(f"TOPLAM {ok}/{tot}")
