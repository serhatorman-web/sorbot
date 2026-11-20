import json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as S
api = S.Binance()
now_ms = int(time.time() * 1000)
for tf in ("15m", "1h"):
    cfg = S.apply_tf_profile(json.load(open(S.CONFIG_PATH, encoding="utf-8")), tf)
    raw = api.get("/fapi/v1/klines", {"symbol": "BTCUSDT", "interval": tf, "limit": 600})
    for live in (False, True):
        cs = S.parse_klines(raw, now_ms if not live else now_ms + 10**9)
        f = S.compute_features(cs, cfg)
        r = {"f": f, "i": len(cs) - 1}
        S.compute_volume_profile(r, cfg)
        print("XX|", tf, "canli_mum_dahil" if live else "kapanan", len(cs), [round(x, 1) for x in r["vp"]])
