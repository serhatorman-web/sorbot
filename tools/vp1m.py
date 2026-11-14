"""Geçici teşhis: GOOGL 4s – hangi pencere VAH 315.08 verir."""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as sc, indicators as ta
api = sc.Binance(); now = int(time.time() * 1000)
cs = sc.parse_klines(api.get("/fapi/v1/klines", {"symbol": "GOOGLUSDT", "interval": "4h", "limit": 1000}), now)
print("mum", len(cs))
H = [x["h"] for x in cs]; L = [x["l"] for x in cs]; V = [x["v"] for x in cs]
for drop in (0, 1):
    e = len(cs) - drop
    for n in range(50, e + 1):
        r = ta.volume_profile(H[e-n:e], L[e-n:e], V[e-n:e], 24, 0.7)
        if r and abs(r[0] - 315.08) < 0.8:
            print("drop", drop, "n", n, [round(x, 2) for x in r], "aralık", min(L[e-n:e]), max(H[e-n:e]))
for n in (150, 200, 250, 300, 400, 500):
    r = ta.volume_profile(H[-n:], L[-n:], V[-n:], 24, 0.7); print("n", n, [round(x, 2) for x in r])
