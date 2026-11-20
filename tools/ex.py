import base64, json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as S

api = S.Binance()
now_ms = int(time.time() * 1000)
shown = 0
for tf in ("15m", "1h"):
    cfg = S.apply_tf_profile(json.load(open(S.CONFIG_PATH, encoding="utf-8")), tf)
    for sym in ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "ZECUSDT", "LINKUSDT", "ADAUSDT"]:
        allc = S.parse_klines(api.get("/fapi/v1/klines", {"symbol": sym, "interval": tf, "limit": 700}), now_ms)
        meta = {"symbol": sym, "type": "COIN", "precision": 4}
        for cut in range(len(allc) - 1, 450, -1):
            cs = allc[:cut + 1]
            f = S.compute_features(cs, cfg)
            m5, m2 = f["ma50"], f["ma200"]
            if None in (m5[-1], m2[-1], m5[-2], m2[-2]) or (m5[-1] - m2[-1]) * (m5[-2] - m2[-2]) >= 0:
                continue
            out = S.live_images([{"meta": meta, "f": f, "i": len(cs) - 1}], cfg, {}, cs[-1]["t"] / 1000)
            out = [o for o in out if "CROSS" in o[2]]
            if not out:
                continue
            o = out[0]
            print("XX|", sym, tf, cut, o[2].replace("\n", " / "))
            b = base64.b64encode(o[1]).decode()
            for k in range(0, len(b), 3000):
                print("IM|", f"{sym}{tf}", k // 3000, b[k:k + 3000])
            shown += 1
            break
        if shown >= 3:
            break
    if shown >= 3:
        break
