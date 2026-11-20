import base64, json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as S

cfg = S.apply_tf_profile(json.load(open(S.CONFIG_PATH, encoding="utf-8")), os.environ.get("TF", "15m"))
api = S.Binance()
now_ms = int(time.time() * 1000)
syms = sys.argv[1:]
shown = 0
for sym in syms:
    allc = S.parse_klines(api.get("/fapi/v1/klines", {"symbol": sym, "interval": os.environ.get("TF", "15m"), "limit": 600}), now_ms)
    meta = {"symbol": sym, "type": "COMMODITY" if sym == "NATGASUSDT" else "COIN", "precision": 4}
    for cut in range(len(allc) - 1, len(allc) - 120, -1):
        cs = allc[:cut + 1]
        f = S.compute_features(cs, cfg)
        i = len(cs) - 1
        out = S.live_images([{"meta": meta, "f": f, "i": i}], cfg, {}, cs[-1]["t"] / 1000)
        out = [o for o in out if "🧩" in o[2] or "TREND" in o[2] or "RETEST" in o[2]]
        if not out:
            continue
        o = out[0]
        print("XX|", sym, cut, o[2].replace("\n", " / "))
        b = base64.b64encode(o[1]).decode()
        for k in range(0, len(b), 3000):
            print("IM|", f"{sym}{cut}", k // 3000, b[k:k + 3000])
        shown += 1
        break
    if shown >= 3:
        break
