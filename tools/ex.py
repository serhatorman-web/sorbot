import base64, json, os, sys, time
from datetime import datetime, timezone, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as S
TR = timezone(timedelta(hours=3))
api = S.Binance()
now_ms = int(time.time() * 1000)
cfg = S.apply_tf_profile(json.load(open(S.CONFIG_PATH, encoding="utf-8")), "15m")
for sym, d, cut, kt in (("SOLUSDT", "long", "21.11 09:30", "PUMP SİNYALİ"), ("BTCUSDT", "short", "21.11 06:00", "DUMP SİNYALİ")):
    cs = S.parse_klines(api.get("/fapi/v1/klines", {"symbol": sym, "interval": "15m", "limit": 900}), now_ms)
    ts = lambda k: datetime.fromtimestamp(cs[k]["t"] / 1000, TR).strftime("%d.%m %H:%M")
    k = next(k for k in range(len(cs)) if ts(k) == cut)
    cs = cs[:k + 1]
    f = S.compute_features(cs, cfg)
    res = {"meta": {"symbol": sym, "type": "COIN", "precision": 2}, "f": f, "i": len(cs) - 1}
    e, sl, tps, slab, tlab = S.radar_levels(res, {"dir": d, "kind": "start"}, cfg)
    print("XX|", sym, kt, "son mum", cut, "fiyat", f["c"][-1], "| giriş", round(e, 2), "| TP", [round(x, 2) for x in tps], tlab, "| stop", round(sl, 2), slab)
    png = S.signal_chart_image(res, cfg, d, kind_title=kt, lv=(e, sl, tps))
    b = base64.b64encode(png).decode()
    for j in range(0, len(b), 3000):
        print("IM|", sym, j // 3000, b[j:j + 3000])
