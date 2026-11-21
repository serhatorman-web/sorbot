import json, os, sys, time
from datetime import datetime, timezone, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as S
TR = timezone(timedelta(hours=3))
api = S.Binance()
now_ms = int(time.time() * 1000)
cfg = S.apply_tf_profile(json.load(open(S.CONFIG_PATH, encoding="utf-8")), "15m")
cs = S.parse_klines(api.get("/fapi/v1/klines", {"symbol": "NATGASUSDT", "interval": "15m", "limit": 600}), now_ms)
f = S.compute_features(cs, cfg)
ts = lambda k: datetime.fromtimestamp(cs[k]["t"] / 1000, TR).strftime("%d.%m %H:%M")
for k in range(len(cs)):
    if "21.11 13:00" <= ts(k) <= "21.11 15:30":
        a = f["atr"][k - 1]; vr = f["v"][k] / f["vol_ma"][k - 1]
        print("XX|", ts(k), "o", f["o"][k], "c", f["c"][k], "h", f["h"][k], "l", f["l"][k], f"body {(f['c'][k]-f['o'][k])/a:.2f}ATR vr {vr:.1f}",
              "st", f["st_dir"][k], "stline", round(f["st_line"][k], 3), "rsi", round(f["rsi"][k], 1), "ema20", round(f["ema20"][k], 3),
              "h4", f["h4_ema"][k] + f["h4_st"][k], "srsi", round(f["srsi_k"][k] or 0), "qqe", (f.get("qqe") or [None]*len(cs))[k])
tc = cfg["trend_turn"]
for k in range(len(cs)):
    if "21.11 14:15" <= ts(k) <= "21.11 15:15":
        why = S.trend_turn(f, k, 1, tc)
        out = ""
        if why:
            res = {"meta": {"symbol": "NATGASUSDT"}, "f": f, "i": k}
            e, sl, tps, sll, tpl = S.radar_levels(res, {"dir": "long", "kind": "start"}, cfg)
            out = f"giriş {e} TP {tps} {tpl} stop {sl} {sll} | TP1 fiyatın ilerisinde: {(tps[0] - f['c'][k]) > 0 if tps else False}"
        print("YY|", ts(k), "Trend Dönüşü:", bool(why), out)
