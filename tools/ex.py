import base64, json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as S
api = S.Binance()
now_ms = int(time.time() * 1000)
cut_t = 1763677800000  # 21.11.2026 01:30 TSI açılışlı 15dk mum (= 20.11 22:30 UTC)
for sym, tf in (("SIRENUSDT", "15m"),):
    cfg = S.apply_tf_profile(json.load(open(S.CONFIG_PATH, encoding="utf-8")), tf)
    cs = S.parse_klines(api.get("/fapi/v1/klines", {"symbol": sym, "interval": tf, "limit": 600}), now_ms)
    from datetime import datetime, timezone, timedelta
    k = next(k for k in range(len(cs)) if datetime.fromtimestamp(cs[k]["t"] / 1000, timezone(timedelta(hours=3))).strftime("%d.%m %H:%M") == "21.11 01:30")
    cs = cs[:k + 1]
    f = S.compute_features(cs, cfg)
    i = len(cs) - 1
    print("XX|", sym, "son mum", datetime.fromtimestamp(cs[i]["t"] / 1000, timezone(timedelta(hours=3))), "st", f["st_dir"][i - 1], f["st_dir"][i])
    res = {"meta": {"symbol": sym, "type": "COIN", "precision": 5}, "f": f, "i": i}
    png = S.signal_chart_image(res, cfg, "long")
    b = base64.b64encode(png).decode()
    for j in range(0, len(b), 3000):
        print("IM|", f"{sym}{tf}", j // 3000, b[j:j + 3000])
