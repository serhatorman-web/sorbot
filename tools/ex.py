import json, os, sys, time
from datetime import datetime, timezone, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as S
TR = timezone(timedelta(hours=3))
api = S.Binance()
now_ms = int(time.time() * 1000)
cfg = S.apply_tf_profile(json.load(open(S.CONFIG_PATH, encoding="utf-8")), "15m")
cs = S.parse_klines(api.get("/fapi/v1/klines", {"symbol": "FFUSDT", "interval": "15m", "limit": 600}), now_ms)
ts = lambda k: datetime.fromtimestamp(cs[k]["t"] / 1000, TR).strftime("%d.%m %H:%M")
for k in range(len(cs)):
    if "21.11 18:30" <= ts(k) <= "21.11 19:30":
        f = S.compute_features(cs[:k + 1], cfg)
        c24 = (f["c"][k] / f["c"][k - 96] - 1) * 100
        pd = S.pump_dump_analysis(f, cfg, c24, k)
        rds = S.pump_radar(f, k, pd, c24, cfg, None, None)
        vr = f["v"][k] / f["vol_ma"][k - 1]
        print("XX|", ts(k), f"değişim {(f['c'][k]/f['o'][k]-1)*100:+.2f}%", f"hacim {vr:.1f}x",
              "20 mum desteği kırıldı:", pd["brk_dn"], "| hacim patlaması:", pd["vol_spike"], "| sıkışma:", pd["squeeze"],
              "| ll20", f["ll20"][k - 1], "kapanış", f["c"][k], "| sinyal:", [(r["kind"], r["dir"]) for r in rds])
