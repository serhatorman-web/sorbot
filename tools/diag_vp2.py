import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as sc
api = sc.Binance(); now_ms = int(time.time() * 1000)
cfg0 = sc.load_json(sc.CONFIG_PATH, {})
syms = ["BTCUSDT","ETHUSDT","SOLUSDT","XRPUSDT","BNBUSDT","DOGEUSDT","ADAUSDT","LINKUSDT","XAUUSDT","NVDAUSDT","TSLAUSDT","QQQUSDT"]
for tf in ("15m", "1h", "4h"):
    cfg = sc.apply_tf_profile(cfg0, tf) if tf != "1h" else cfg0
    for s in syms:
        cs = sc.parse_klines(api.get("/fapi/v1/klines", {"symbol": s, "interval": tf, "limit": 300}), now_ms)
        f = {k: [x[k] for x in cs] for k in ("o", "h", "l", "c", "v")}
        res = {"f": f, "i": len(cs) - 1, "meta": {"precision": 4}}
        sc.compute_volume_profile(res, cfg)
        ls = sc.volume_profile_lines(res, cfg)
        print(tf, s, ls[1] if ls else "-")
