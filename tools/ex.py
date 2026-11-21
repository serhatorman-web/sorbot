import base64, json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as S
api = S.Binance()
now_ms = int(time.time() * 1000)
cfg = S.apply_tf_profile(json.load(open(S.CONFIG_PATH, encoding="utf-8")), "15m")
K = [("SOLUSDT", "long", "start", "PUMP SİNYALİ"), ("BTCUSDT", "short", "start", "DUMP SİNYALİ"),
     ("XRPUSDT", "long", "momentum", "PUMP HAREKETİ"), ("ETHUSDT", "short", "momentum", "DUMP HAREKETİ"),
     ("ETHUSDT", "long", "early", "PUMP ERKEN UYARI"), ("BTCUSDT", "short", "early", "DUMP ERKEN UYARI"),
     ("XRPUSDT", "short", "reversal", "PUMP SONRASI DÖNÜŞ"), ("SOLUSDT", "long", "reversal", "DUMP SONRASI DÖNÜŞ")]
cache = {}
for n, (sym, d, kind, kt) in enumerate(K, 1):
    if sym not in cache:
        cs = S.parse_klines(api.get("/fapi/v1/klines", {"symbol": sym, "interval": "15m", "limit": 600}), now_ms)
        cache[sym] = S.compute_features(cs, cfg)
    f = cache[sym]
    res = {"meta": {"symbol": sym, "type": "COIN", "precision": 4 if sym == "XRPUSDT" else 2}, "f": f, "i": len(f["c"]) - 1}
    rd = {"dir": d, "kind": kind}
    png = S.signal_chart_image(res, cfg, d, kind_title=kt, lv=S.radar_levels(res, rd, cfg)[:3])
    b = base64.b64encode(png).decode()
    for j in range(0, len(b), 3000):
        print("IM|", f"{n}_{kind}_{d}", j // 3000, b[j:j + 3000])
