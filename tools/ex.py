import json, os, sys, time
from datetime import datetime, timezone, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as S
TR = timezone(timedelta(hours=3))
api = S.Binance()
now_ms = int(time.time() * 1000)
cfg = S.apply_tf_profile(json.load(open(S.CONFIG_PATH, encoding="utf-8")), "15m")
sb = cfg["pump_radar"]["squeeze_break"]
for sym, s, a_, b_ in (("BTCUSDT", -1, "21.11 05:00", "21.11 06:15"), ("SOLUSDT", 1, "21.11 09:00", "21.11 10:00")):
    cs = S.parse_klines(api.get("/fapi/v1/klines", {"symbol": sym, "interval": "15m", "limit": 900}), now_ms)
    ts = lambda k: datetime.fromtimestamp(cs[k]["t"] / 1000, TR).strftime("%d.%m %H:%M")
    for k in range(len(cs)):
        if a_ <= ts(k) <= b_:
            f = S.compute_features(cs[:k + 1], cfg)
            sb2 = dict(sb, require_h4=False, require_st=False)
            print("XX|", sym, ts(k), "tetik:", bool(S.squeeze_break(f, k, s, sb)), "| filtresiz:", bool(S.squeeze_break(f, k, s, sb2)),
                  "| h4", round(f["h4_ema"][k] + f["h4_st"][k], 1), "st", f["st_dir"][k])
