import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as sc, indicators as ta
api = sc.Binance()
now = int(time.time() * 1000)
raw = api.get("/fapi/v1/klines", {"symbol": "BTCUSDT", "interval": "1h", "limit": 1000})
cs = sc.parse_klines(raw, now)
h, l, c, v = [x["h"] for x in cs], [x["l"] for x in cs], [x["c"] for x in cs], [x["v"] for x in cs]
print("son kapanmış", cs[-1]["t"] // 1000)
for tr in ("ema50", "sma50"):
    for sh in (0, 25):
        o = ta.tv_technical_rating(h, l, c, v, trend=tr, ichi_shift=sh)
        osc = [round(x["osc"] * x["osc_n"]) for x in o[-19:]]
        ma = [round(x["ma"] * x["ma_n"]) for x in o[-19:]]
        print(f"ROW {tr} shift{sh} osc={osc} ma={ma}")
o = ta.tv_technical_rating(h, l, c, v)
for x in o[-19:]:
    print("V", x["votes"])
