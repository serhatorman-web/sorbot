"""Arka planda pivot indikatörlü grafik resmi örnekleri (canlı live_images ile)."""
import base64, sys, time
sys.path.insert(0, ".")
import scanner as S

base = S.load_json(S.CONFIG_PATH, None)
api = S.Binance()
now = int(time.time() * 1000)
for tf, syms in (("15m", ["1000SHIBUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "SUIUSDT"]),
                 ("1h", ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "LINKUSDT", "AVAXUSDT"])):
    cfg = S.apply_tf_profile(base, tf) if tf != "1h" else base
    meta_all, *_ = S.build_universe(api, cfg)
    metas = {m["symbol"]: m for m in meta_all}
    done = False
    for sym in syms:
        m = metas.get(sym)
        if not m or done:
            continue
        cs = S.parse_klines(api.get("/fapi/v1/klines", {"symbol": sym, "interval": tf, "limit": 600}), now)
        f = S.compute_features(cs, cfg)
        for k in range(len(cs) - 1, len(cs) - 150, -1):
            if sym == "1000SHIBUSDT" and k > len(cs) - 3: continue
            out = S.live_images([{"meta": m, "f": f, "i": k}], cfg, {"img": {}}, (cs[k]["t"] + S.TF_MS[tf]) / 1000)
            if out:
                prio, png, cap, s_, key, body = out[0]
                print(f"PB| {tf} · {sym} · {S.datetime.fromtimestamp(cs[k]['t'] / 1000, S.TR_TZ)}")
                b = base64.b64encode(png).decode()
                for j in range(0, len(b), 3000):
                    print(f"IM| {tf} {j // 3000:04d} {b[j:j + 3000]}", flush=True)
                done = True
                break
