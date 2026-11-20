import os, sys, time
from datetime import datetime, timezone, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as S
import patterns as pt
import indicators as ta

TR = timezone(timedelta(hours=3))
api = S.Binance()
now_ms = int(time.time() * 1000)
cs = S.parse_klines(api.get("/fapi/v1/klines", {"symbol": "ETHUSDT", "interval": "1h", "limit": 300}), now_ms)
o = [x["o"] for x in cs]; h = [x["h"] for x in cs]; l = [x["l"] for x in cs]; c = [x["c"] for x in cs]
a = ta.atr(h, l, c, 14)
for i in range(len(cs) - 9, len(cs)):
    r = h[i] - l[i]; b = abs(c[i] - o[i]); top = max(o[i], c[i]); bot = min(o[i], c[i])
    print("XX|", datetime.fromtimestamp(cs[i]["t"] / 1000, TR).strftime("%d %H:%M"),
          f"A {o[i]:.2f} Y {h[i]:.2f} D {l[i]:.2f} K {c[i]:.2f} | aralık {r:.2f} gövde {b:.2f} üst {h[i]-top:.2f} alt {bot-l[i]:.2f} ATR {a[i]:.2f} | 5 mum önce→ {c[i-1]-c[i-6]:+.2f}",
          pt.candle_patterns(o, h, l, c, a, i))
