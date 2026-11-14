"""Geçici teşhis: botun yeni hacim profili kodu, ekran görüntüsü anındaki verilerle (oluşan mum o ana kadarki haliyle)."""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as sc
api = sc.Binance(); cfg0 = json.load(open("config.json"))
def candles_at(sym, tf, ms, shot):
    raw = api.get("/fapi/v1/klines", {"symbol": sym, "interval": tf, "endTime": shot, "limit": 499})
    cs = [{"t": int(k[0]), "o": float(k[1]), "h": float(k[2]), "l": float(k[3]), "c": float(k[4]),
           "v": float(k[7]), "bv": float(k[5])} for k in raw]
    last = cs[-1]
    if last["t"] + ms > shot:          # oluşan mum: ekran görüntüsü anına kadarki 1dk verisinden
        m1 = api.get("/fapi/v1/klines", {"symbol": sym, "interval": "1m", "startTime": last["t"], "endTime": shot - 1, "limit": 1500})
        cs[-1] = {"t": last["t"], "o": float(m1[0][1]), "h": max(float(k[2]) for k in m1), "l": min(float(k[3]) for k in m1),
                  "c": float(m1[-1][4]), "v": sum(float(k[7]) for k in m1), "bv": sum(float(k[5]) for k in m1)}
    return cs
cases = [("BTCUSDT", "4h", 14400e3, 1794688320000, (85857.1, 81215.3, 76573.5)),
         ("ETHUSDT", "4h", 14400e3, 1794688320000, (2556.77, 2435.55, 2233.52)),
         ("SOLUSDT", "4h", 14400e3, 1794688320000, (110.49, 103.80, 79.26)),
         ("XRPUSDT", "4h", 14400e3, 1794688320000, (1.5134, 1.2992, 1.1653)),
         ("GOOGLUSDT", "4h", 14400e3, 1794687420000, (315.08, None, None)),
         ("ZROUSDT", "15m", 900e3, 1794676980000, (1.5998, 1.5797, 1.5259))]
tot = ok = 0
for sym, tf, ms, shot, tgt in cases:
    cs = candles_at(sym, tf, ms, shot)
    cfg = dict(cfg0, timeframe=tf)
    f = sc.compute_features(cs, cfg); res = {"f": f, "i": len(cs) - 1, "meta": {"symbol": sym}}
    sc.compute_volume_profile(res, cfg)
    got = res["vp"]
    marks = []
    for g, t in zip(got, tgt):
        if t is None: marks.append("-"); continue
        tot += 1; good = abs(g - t) / t < 0.0003; ok += good; marks.append("✓" if good else "✗")
    print(f"{sym} {tf}: bot {[round(x, 4) for x in got]} gösterge {tgt} {' '.join(marks)}")
print(f"TOPLAM {ok}/{tot}")
