"""Geçici teşhis: BTC 4s VAL 76573.5 hangi pencereyle çıkar."""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as sc, indicators as ta
api = sc.Binance(); now = int(time.time() * 1000)
cs = sc.parse_klines(api.get("/fapi/v1/klines", {"symbol": "BTCUSDT", "interval": "4h", "limit": 1000}), now)
H = [x["h"] for x in cs]; L = [x["l"] for x in cs]; V = [x["v"] for x in cs]
for drop in (0, 1, 2):
    e = len(cs) - drop
    hits = [n for n in range(50, 600) if abs(ta.volume_profile(H[e-n:e], L[e-n:e], V[e-n:e], 24, 0.7)[2] - 76573.5) < 300]
    print("drop", drop, "VAL≈76573.5 veren n:", hits[:40])
    for n in (150, 250):
        print("   n", n, [round(x, 1) for x in ta.volume_profile(H[e-n:e], L[e-n:e], V[e-n:e], 24, 0.7)])
