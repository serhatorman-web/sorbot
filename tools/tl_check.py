import time
from datetime import datetime, timezone, timedelta
import scanner as sc
import indicators as ta

api = sc.Binance()
now = int(time.time() * 1000)
TR = timezone(timedelta(hours=3))
for tf in ("15m", "1h", "4h", "1d"):
    cs = sc.fetch_long_history(api, "BTCUSDT", tf, now, 499)[:-1]       # kapanmış mumlar
    h, l, c = [x["h"] for x in cs], [x["l"] for x in cs], [x["c"] for x in cs]
    for e in ta.trendlines_close(h, l, c):
        t = lambda k: datetime.fromtimestamp(cs[k]["t"] / 1000, TR).strftime("%d.%m %H:%M")
        print("TL", tf, e["type"], e["state"], "temas", e["touches"], "| 1. nokta", t(e["a"]), round(c[e["a"]], 1),
              "| 2. nokta", t(e["b"]), round(c[e["b"]], 1), "| çizgi şimdi", round(e["level"], 1), "fiyat", c[-1],
              "| kırılım", e["bars_ago"], e["retest"])
