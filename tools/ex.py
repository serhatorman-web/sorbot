import base64, json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as S

api = S.Binance()
now_ms = int(time.time() * 1000)
cfg = S.apply_tf_profile(json.load(open(S.CONFIG_PATH, encoding="utf-8")), "1h")
cfg["live_images"]["closed_images"] = True
shown = 0
for sym in ("AIOUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT"):
    allc = S.parse_klines(api.get("/fapi/v1/klines", {"symbol": sym, "interval": "1h", "limit": 600}), now_ms)
    meta = {"symbol": sym, "type": "COIN", "precision": 5}
    for cut in range(len(allc) - 1, len(allc) - 60, -1):
        cs = allc[:cut + 1]
        f = S.compute_features(cs, cfg)
        out = S.live_images([{"meta": meta, "f": f, "i": len(cs) - 1}], cfg, {}, time.time())
        if out:
            print("XX|", sym, out[0][2].split("\n")[0])
            b = base64.b64encode(out[0][1]).decode()
            for j in range(0, len(b), 3000):
                print("IM|", f"{sym}", j // 3000, b[j:j + 3000])
            shown += 1
            break
    if shown >= 2:
        break
