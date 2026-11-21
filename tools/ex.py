import json, os, sys, time
from datetime import datetime, timezone, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as S
TR = timezone(timedelta(hours=3))
api = S.Binance(); now_ms = int(time.time() * 1000)
cfg = S.apply_tf_profile(json.load(open(S.CONFIG_PATH, encoding="utf-8")), "15m")
cs = S.parse_klines(api.get("/fapi/v1/klines", {"symbol": "LITUSDT", "interval": "15m", "limit": 600}), 1 << 62)
for k in range(len(cs) - 8, len(cs)):
    f = S.compute_features(cs[:k + 1], cfg); a = f["atr"][k - 1]
    print("XX|", datetime.fromtimestamp(cs[k]["t"] / 1000, TR).strftime("%H:%M"), f"o {f['o'][k]} c {f['c'][k]} h {f['h'][k]}",
          f"gövde {(f['c'][k]-f['o'][k])/a:.2f}ATR hacim {f['v'][k]/f['vol_ma'][k-1]:.1f}x önceki tepe {f['h'][k-1]}",
          "ST", f["st_dir"][k-1], f["st_dir"][k], "üstTF", f["h4_ema"][k] + f["h4_st"][k], "TT", S.trend_turn(f, k, 1, cfg["trend_turn"]))
