import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as sc, indicators as ta
api = sc.Binance(); now_ms = int(time.time() * 1000)
target = (70919.2, 68891.8, 65242.3)
best = []
for tf in ("15m", "30m", "1h", "2h", "4h", "1d"):
    cs = sc.parse_klines(api.get("/fapi/v1/klines", {"symbol": "BTCUSDT", "interval": tf, "limit": 1000}), now_ms)
    h = [x["h"] for x in cs]; l = [x["l"] for x in cs]; v = [x["v"] for x in cs]
    for n in (24, 48, 50, 96, 100, 150, 200, 250, 300, 400, 500, 1000):
        if n > len(cs):
            continue
        for rows in (24, 25, 50, 70, 100, 200):
            r = ta.volume_profile(h[-n:], l[-n:], v[-n:], rows, 0.70)
            if not r:
                continue
            err = sum(abs(a - b) for a, b in zip(r, target))
            best.append((err, tf, n, rows, [round(x, 1) for x in r]))
    if tf in ("15m", "1h", "4h"):
        n = {"15m": 96, "1h": 96, "4h": 90}[tf]
        print("BOT", tf, n, "bar 24 satır:", [round(x, 1) for x in ta.volume_profile(h[-n:], l[-n:], v[-n:], 24, 0.7)])
best.sort()
for b in best[:12]:
    print("YAKIN", b)
