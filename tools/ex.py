import json, os, sys, time
from datetime import datetime, timezone, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as S
TR = timezone(timedelta(hours=3))
api = S.Binance()
cfg = S.apply_tf_profile(json.load(open(S.CONFIG_PATH, encoding="utf-8")), "15m")
for sym in ("VETUSDT", "LITUSDT", "AVNTUSDT", "BTCUSDT"):
    cs = S.parse_klines(api.get("/fapi/v1/klines", {"symbol": sym, "interval": "15m", "limit": 600}), 1 << 62)
    m1 = S.parse_klines(api.get("/fapi/v1/klines", {"symbol": sym, "interval": "1m", "limit": 1000}), 1 << 62)
    for k in range(len(cs) - 60, len(cs)):
        t0 = cs[k]["t"]
        for mm in [x for x in m1 if t0 <= x["t"] < t0 + 900000]:
            sub = [x for x in m1 if t0 <= x["t"] <= mm["t"]]
            part = dict(cs[k], h=max(x["h"] for x in sub), l=min(x["l"] for x in sub), c=sub[-1]["c"], v=sum(x["v"] for x in sub))
            f = S.compute_features(cs[:k] + [part], cfg)
            fr = (mm["t"] + 60000 - t0) / 900000
            hit = [s for s in (1, -1) if S.trend_turn(f, k, s, cfg["trend_turn"], frac=fr)]
            if hit:
                print("XX|", sym, datetime.fromtimestamp(t0 / 1000, TR).strftime("%H:%M"), "mumu, sinyal dk",
                      datetime.fromtimestamp((mm["t"] + 60000) / 1000, TR).strftime("%H:%M"), "AL" if hit[0] == 1 else "SAT")
                break
