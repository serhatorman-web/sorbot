import base64, json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as S
api = S.Binance()
now_ms = int(time.time() * 1000)
for sym, tf in (("SOLUSDT", "15m"), ("ETHUSDT", "1h"), ("BTCUSDT", "15m")):
    cfg = S.apply_tf_profile(json.load(open(S.CONFIG_PATH, encoding="utf-8")), tf)
    cs = S.parse_klines(api.get("/fapi/v1/klines", {"symbol": sym, "interval": tf, "limit": 600}), now_ms)
    f = S.compute_features(cs, cfg)
    i = len(cs) - 1
    d = "long" if f["st_dir"][i] == 1 else "short"
    res = {"meta": {"symbol": sym, "type": "COIN", "precision": 2}, "f": f, "i": i}
    e, sl, tps, lab = S.levels(res, d, cfg)
    print("XX|", sym, tf, d, "giris", round(e, 4), "stop", round(sl, 4), "tp", [round(x, 4) for x in tps], lab)
    png = S.signal_chart_image(res, cfg, d)
    b = base64.b64encode(png).decode()
    for j in range(0, len(b), 3000):
        print("IM|", f"{sym}{tf}", j // 3000, b[j:j + 3000])
