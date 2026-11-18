import time
from datetime import datetime, timezone, timedelta
import scanner as sc
import indicators as ta

api = sc.Binance()
now = int(time.time() * 1000)
TR = timezone(timedelta(hours=3))
for tf in ("15m", "1d"):
    a = sc.parse_klines(api.get("/fapi/v1/klines", {"symbol": "BTCUSDT", "interval": tf, "limit": 300}), now)
    b = sc.fetch_long_history(api, "BTCUSDT", tf, now, 499)
    for name, cs in (("scan300", a), ("long499", b), ("long499-1", b[:-1])):
        h, l, c = [x["h"] for x in cs], [x["l"] for x in cs], [x["c"] for x in cs]
        t = lambda k: datetime.fromtimestamp(cs[k]["t"] / 1000, TR).strftime("%d.%m %H:%M")
        print("N", tf, name, len(cs), t(len(cs) - 1))
        for e in ta.trendlines_close(h, l, c):
            print("TL", tf, name, e["type"], e["state"], t(e["a"]), round(c[e["a"]], 1), t(e["b"]), round(c[e["b"]], 1),
                  round(e["level"], 1), e["bars_ago"])
