import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as sc, indicators as ta
api = sc.Binance()
now = int(time.time() * 1000)
for sym, tf in (("ETHUSDT", "15m"), ("SOLUSDT", "4h")):
    cs = sc.parse_klines(api.get("/fapi/v1/klines", {"symbol": sym, "interval": tf, "limit": 1000}), now)
    h, l, c, v = [x["h"] for x in cs], [x["l"] for x in cs], [x["c"] for x in cs], [x["v"] for x in cs]
    print("son kapanmış", sym, tf, cs[-1]["t"] // 1000)
    for tr in ("ema50", "sma50"):
        o = ta.tv_technical_rating(h, l, c, v, trend=tr)
        print(f"ROW {tr} osc={[round(x['osc'] * x['osc_n']) for x in o[-40:]]}")
    o = ta.tv_technical_rating(h, l, c, v)
    print(f"ROW ma={[round(x['ma'] * x['ma_n']) for x in o[-40:]]}")
