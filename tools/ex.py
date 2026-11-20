import base64, json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as S
api = S.Binance()
now_ms = int(time.time() * 1000)
for sym, tf, d, kt, pl in (("SOLUSDT", "15m", "short", "DUMP SİNYALİ", True), ("BTCUSDT", "1h", "long", "PUMP ERKEN UYARI", False)):
    cfg = S.apply_tf_profile(json.load(open(S.CONFIG_PATH, encoding="utf-8")), tf)
    cs = S.parse_klines(api.get("/fapi/v1/klines", {"symbol": sym, "interval": tf, "limit": 600}), now_ms)
    f = S.compute_features(cs, cfg)
    res = {"meta": {"symbol": sym, "type": "COIN", "precision": 2}, "f": f, "i": len(cs) - 1}
    png = S.signal_chart_image(res, cfg, d, kind_title=kt, plan=pl)
    b = base64.b64encode(png).decode()
    for j in range(0, len(b), 3000):
        print("IM|", f"{sym}{tf}", j // 3000, b[j:j + 3000])
