import json, os, sys, time
from datetime import datetime, timezone, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as S
TR = timezone(timedelta(hours=3))
api = S.Binance()
cfg = S.apply_tf_profile(json.load(open(S.CONFIG_PATH, encoding="utf-8")), "15m")
cs = S.parse_klines(api.get("/fapi/v1/klines", {"symbol": "BTCUSDT", "interval": "15m", "limit": 600}), 1 << 62)
m1 = S.parse_klines(api.get("/fapi/v1/klines", {"symbol": "BTCUSDT", "interval": "1m", "limit": 1000}), 1 << 62)
sent = set()
for k in range(len(cs)):
    ts = datetime.fromtimestamp(cs[k]["t"] / 1000, TR).strftime("%d.%m %H:%M")
    if not ("21.11 15:45" <= ts <= "21.11 18:30"):
        continue
    t0 = cs[k]["t"]
    for mm in [x for x in m1 if t0 <= x["t"] < t0 + 900000]:
        sub = [x for x in m1 if t0 <= x["t"] <= mm["t"]]
        part = dict(cs[k], h=max(x["h"] for x in sub), l=min(x["l"] for x in sub), c=sub[-1]["c"], v=sum(x["v"] for x in sub))
        f = S.compute_features(cs[:k] + [part], cfg)
        for s in (1, -1):
            if (k, s) in sent:
                continue
            why = S.trend_turn(f, k, s, cfg["trend_turn"], frac=(mm["t"] + 60000 - t0) / 900000)
            if why:
                e, sl, tps, _, _ = S.radar_levels({"f": f, "i": k}, {"dir": "long" if s == 1 else "short", "kind": "start"}, cfg)
                ok = bool(tps) and (tps[0] - part["c"]) * s > 0
                sent.add((k, s))
                print("XX|", ts, "mumu", datetime.fromtimestamp((mm["t"] + 60000) / 1000, TR).strftime("%H:%M"), "AL" if s == 1 else "SAT",
                      "fiyat", round(part["c"]), "giriş", round(e), "TP1", round(tps[0]) if tps else None, "stop", round(sl), "gönderilir" if ok else "TP1 geçilmiş, gönderilmez")
