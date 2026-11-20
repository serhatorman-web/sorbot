import base64, json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as S

api = S.Binance()
now_ms = int(time.time() * 1000)
shown = {"tl": 0, "fm": 0}
for tf in ("15m", "1h", "4h", "1d"):
    cfg = S.apply_tf_profile(json.load(open(S.CONFIG_PATH, encoding="utf-8")), tf)
    uni, *_ = S.build_universe(api, cfg)
    for m in uni[:120]:
        if all(v >= 1 for v in shown.values()):
            break
        cs = S.parse_klines(api.get("/fapi/v1/klines", {"symbol": m["symbol"], "interval": tf, "limit": 499}), 1 << 62)
        f = S.compute_features(cs, cfg)
        for o in S.live_images([{"meta": m, "f": f, "i": len(cs) - 1}], cfg, {}, time.time(), intrabar=True):
            k = "fm" if "🧩" in o[2] else "tl"
            if shown[k] >= 1:
                continue
            shown[k] += 1
            print("XX|", o[2].replace("\n", " // "))
            b = base64.b64encode(o[1]).decode()
            for j in range(0, len(b), 3000):
                print("IM|", f"{k}{tf}", j // 3000, b[j:j + 3000])
