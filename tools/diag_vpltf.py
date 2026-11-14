import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as sc, indicators as ta
api = sc.Binance(); now_ms = int(time.time() * 1000) + 10**9   # oluşan mumu da al
target = (70919.2, 68891.8, 65242.3)
def m1(start, end):
    out = []
    while start < end:
        raw = api.get("/fapi/v1/klines", {"symbol": "BTCUSDT", "interval": "1m", "startTime": start, "limit": 1500})
        if not raw:
            break
        out += raw
        start = raw[-1][0] + 60000
    return [{"h": float(r[2]), "l": float(r[3]), "v": float(r[5]), "t": r[0]} for r in out]
for tf, ms in (("5m", 300000), ("15m", 900000), ("30m", 1800000), ("1h", 3600000)):
    raw = api.get("/fapi/v1/klines", {"symbol": "BTCUSDT", "interval": tf, "limit": 150})
    cs = [{"h": float(r[2]), "l": float(r[3]), "v": float(r[5]), "t": r[0]} for r in raw]
    r1 = ta.volume_profile([x["h"] for x in cs], [x["l"] for x in cs], [x["v"] for x in cs], 24, 0.7)
    mm = m1(cs[0]["t"], cs[-1]["t"] + ms)
    r2 = ta.volume_profile([x["h"] for x in mm], [x["l"] for x in mm], [x["v"] for x in mm], 24, 0.7)
    # aralık = ana zaman dilimi mumlarının en düşük–en yüksek değeri, hacim 1dk mumlardan
    print(tf, "150 mum (kendi mumu):", [round(x, 1) for x in r1], " | 1dk hacimle:", [round(x, 1) for x in r2],
          " | hata:", round(sum(abs(a - b) for a, b in zip(r2, target))), "| aralık", min(x["l"] for x in cs), max(x["h"] for x in cs))
