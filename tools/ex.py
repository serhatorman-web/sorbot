import json, os, sys, time
from datetime import datetime, timezone, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as S
TR = timezone(timedelta(hours=3))
api = S.Binance()
cfg = S.apply_tf_profile(json.load(open(S.CONFIG_PATH, encoding="utf-8")), "15m")
cs = S.parse_klines(api.get("/fapi/v1/klines", {"symbol": "VETUSDT", "interval": "15m", "limit": 600}), 1 << 62)
m1 = S.parse_klines(api.get("/fapi/v1/klines", {"symbol": "VETUSDT", "interval": "1m", "limit": 120}), 1 << 62)
for k in range(len(cs) - 4, len(cs)):
    t0 = cs[k]["t"]
    for mm in [x for x in m1 if t0 <= x["t"] < t0 + 900000]:
        sub = [x for x in m1 if t0 <= x["t"] <= mm["t"]]
        part = dict(cs[k], h=max(x["h"] for x in sub), l=min(x["l"] for x in sub), c=sub[-1]["c"], v=sum(x["v"] for x in sub))
        f = S.compute_features(cs[:k] + [part], cfg); a = f["atr"][k - 1]
        why = S.trend_turn(f, k, 1, cfg["trend_turn"])
        print("XX|", datetime.fromtimestamp(t0 / 1000, TR).strftime("%H:%M"), "dk", datetime.fromtimestamp(mm["t"] / 1000, TR).strftime("%H:%M"),
              f"gövde {(part['c']-part['o'])/a:.2f} hacim {part['v']/f['vol_ma'][k-1]:.2f}x kırılım {part['c'] > f['h'][k-1]} ST {f['st_dir'][k-1]}{f['st_dir'][k]} üst {f['h4_ema'][k]+f['h4_st'][k]}", "TT" if why else "")
