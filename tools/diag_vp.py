import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as sc
api = sc.Binance(); now_ms = int(time.time() * 1000)
cfg0 = sc.load_json(sc.CONFIG_PATH, {})
for tf in ("15m", "1h", "4h"):
    cfg = sc.apply_tf_profile(cfg0, tf) if tf != "1h" else cfg0
    cnt = 0
    for s in ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT", "DOGEUSDT", "XAUUSDT", "NVDAUSDT", "TSLAUSDT", "LINKUSDT"]:
        cs = sc.parse_klines(api.get("/fapi/v1/klines", {"symbol": s, "interval": tf, "limit": 300}), now_ms)
        f = {"h": [x["h"] for x in cs], "l": [x["l"] for x in cs], "c": [x["c"] for x in cs], "v": [x["v"] for x in cs]}
        res = {"f": f, "i": len(cs) - 1, "meta": {"precision": 2}}
        sc.compute_volume_profile(res, cfg)
        ls = sc.volume_profile_lines(res, cfg)
        cnt += bool(ls)
        print(tf, s, " | ".join(ls[1:]) or "-")
    print(tf, "satır çıkan:", cnt, "/ 10")
