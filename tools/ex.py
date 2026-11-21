import json, os, sys, time
from datetime import datetime, timezone, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as S
TR = timezone(timedelta(hours=3))
api = S.Binance()
now_ms = int(time.time() * 1000)
for tf in ("15m", "1h"):
    cfg = S.apply_tf_profile(json.load(open(S.CONFIG_PATH, encoding="utf-8")), tf)
    cs = S.parse_klines(api.get("/fapi/v1/klines", {"symbol": "BTCUSDT", "interval": tf, "limit": 600}), now_ms)
    ts = lambda k: datetime.fromtimestamp(cs[k]["t"] / 1000, TR).strftime("%d.%m %H:%M")
    for k in range(len(cs)):
        if "21.11 16:45" <= ts(k) <= "21.11 19:45":
            f = S.compute_features(cs[:k + 1], cfg)
            a = f["atr"][k - 1]; vr = f["v"][k] / f["vol_ma"][k - 1]
            c24 = (f["c"][k] / f["c"][k - (96 if tf == "15m" else 24)] - 1) * 100
            pd = S.pump_dump_analysis(f, cfg, c24, k)
            tt = S.trend_turn(f, k, -1, cfg["trend_turn"])
            rds = [(r["kind"], r["dir"]) for r in S.pump_radar(f, k, pd, c24, cfg, None, None)]
            print("XX|", tf, ts(k), f"o {f['o'][k]:.0f} c {f['c'][k]:.0f} {(f['c'][k]/f['o'][k]-1)*100:+.2f}%",
                  f"gövde {(f['o'][k]-f['c'][k])/a:.2f}ATR hacim {vr:.1f}x", "ST", f["st_dir"][k - 1], f["st_dir"][k],
                  "üstTF", f["h4_ema"][k] + f["h4_st"][k], "3mum dibi kırıldı", f["c"][k] < min(f["l"][k - 3:k]),
                  "| TD-SAT", bool(tt), "| destek kırıldı", pd["brk_dn"], "hacim patl.", pd["vol_spike"], "sıkışma", pd["squeeze"], "| radar", rds)
