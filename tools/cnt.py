import json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as S
import indicators as ta
from datetime import datetime, timezone, timedelta

cfg = S.apply_tf_profile(json.load(open(S.CONFIG_PATH, encoding="utf-8")), "4h")
api = S.Binance()
now_ms = int(time.time() * 1000)
cs = S.parse_klines(api.get("/fapi/v1/klines", {"symbol": "CHIPUSDT", "interval": "4h", "limit": 499}), now_ms)
f = S.compute_features(cs, cfg)
i = len(cs) - 1
lo = max(0, i + 1 - 300)
w = cs[lo:i + 1]
h = [x["h"] for x in w]; l = [x["l"] for x in w]; c = [x["c"] for x in w]
TR = timezone(timedelta(hours=3))
for k in range(len(w) - 6, len(w)):
    print("XX| mum", datetime.fromtimestamp(w[k]["t"] / 1000, TR).strftime("%d %H:%M"), w[k]["o"], w[k]["c"],
          "vr", round(f["v"][lo + k] / f["vol_ma"][lo + k - 1], 2))
for ev in ta.trendlines_close(h, l, c):
    if ev["state"] == "broken":
        print("XX| ev", {k: v for k, v in ev.items() if k in ("type", "state", "bars_ago", "touches", "a", "b", "level")})
lc = cfg["live_images"]
print("XX| ayar", {k: lc.get(k) for k in ("volume_x", "follow_through", "follow_bars", "late_max", "min_touches", "min_span")})
