import json, os, sys, time
from datetime import datetime, timezone, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as S
TR = timezone(timedelta(hours=3))
api = S.Binance()
now_ms = int(time.time() * 1000)
cfg = S.apply_tf_profile(json.load(open(S.CONFIG_PATH, encoding="utf-8")), "15m")
cs = S.parse_klines(api.get("/fapi/v1/klines", {"symbol": "BTCUSDT", "interval": "15m", "limit": 900}), now_ms)
f = S.compute_features(cs, cfg)
ts = lambda k: datetime.fromtimestamp(cs[k]["t"] / 1000, TR).strftime("%d.%m %H:%M")
for k in range(len(cs)):
    if "21.11 02:00" <= ts(k) <= "21.11 07:00":
        vr = f["v"][k] / f["vol_ma"][k - 1]
        print("XX|", ts(k), "o", f["o"][k], "h", f["h"][k], "l", f["l"][k], "c", f["c"][k], f"vr {vr:.1f}",
              "ema20", round(f["ema20"][k], 1), "ll20", f["ll20"][k - 1], "atr", round(f["atr"][k], 1), "st", f["st_dir"][k])
