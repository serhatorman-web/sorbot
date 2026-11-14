import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import perf, scanner as sc
api = sc.Binance()
# 2 gün önceki bir 1s mum kapanışından sahte LONG ve SHORT kaydı → update ile sonuç
t = (int(time.time() * 1000) // 3_600_000 - 48) * 3_600_000
k = api.get("/fapi/v1/klines", {"symbol": "BTCUSDT", "interval": "1h", "endTime": t - 1, "limit": 2})[-1]
c = float(k[4]); atr = c * 0.006
for d, s_ in (("long", 1), ("short", -1)):
    perf.record_signal("BTCUSDT", "COIN", "1h", d, t, c, c - s_ * 1.5 * atr, [c + s_ * 1.5 * atr * r for r in (1, 2, 3)],
                       "B", {"htf": True, "ichi": False, "retest": True, "leader": True})
perf.update()
for x in perf.load()["signals"]: print(x["id"], x["status"], "best", x["best"])
print(perf.weekly_message(perf.load()))
