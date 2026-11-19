"""DUSK ve Doğal Gaz 15dk resimleri: şimdiki pivot çizimi ve 'sadece bu günün pivotları + P/R1/S1 her zaman' önerisi."""
import base64, copy, sys, time
sys.path.insert(0, ".")
import scanner as S

base = S.load_json(S.CONFIG_PATH, None)
cfg0 = S.apply_tf_profile(base, "15m")
api = S.Binance()
now = int(time.time() * 1000)
uni, *_ = S.build_universe(api, cfg0)
metas = {m["symbol"]: m for m in uni}
for sym in ("DUSKUSDT", "NATGASUSDT"):
    m = metas[sym]
    cs = S.parse_klines(api.get("/fapi/v1/klines", {"symbol": sym, "interval": "15m", "limit": 600}), now)
    f = S.compute_features(cs, cfg0)
    for k in range(len(cs) - 1, len(cs) - 40, -1):
        out = S.live_images([{"meta": m, "f": f, "i": k}], cfg0, {"img": {}}, (cs[k]["t"] + 900000) / 1000)
        if not out:
            continue
        for mode in (False, True):
            cfg = copy.deepcopy(cfg0)
            cfg["live_images"]["pivot_current_only"] = mode
            o = S.live_images([{"meta": m, "f": f, "i": k}], cfg, {"img": {}}, (cs[k]["t"] + 900000) / 1000)
            tag = f"{sym}_{'yeni' if mode else 'eski'}"
            print("PM|", tag, S.datetime.fromtimestamp(cs[k]["t"] / 1000, S.TR_TZ))
            b = base64.b64encode(o[0][1]).decode()
            for j in range(0, len(b), 3000):
                print(f"IM| {tag} {j // 3000:04d} {b[j:j + 3000]}", flush=True)
        break
