"""Örnek: grafik kanalına gidecek resimler ve aynı coin'in sinyal mesajında çıkacak TREND ÇİZGİSİ / FORMASYONLAR satırları."""
import os, sys, time
sys.path.insert(0, ".")
import scanner as S

tfs = sys.argv[1:] or ["1h"]
for tf in tfs:
    base = S.load_json(S.CONFIG_PATH, None)
    cfg = S.apply_tf_profile(base, tf) if tf != "1h" else base
    api = S.Binance()
    now_ms = int(time.time() * 1000)
    uni, *_ = S.build_universe(api, cfg)
    results = []
    for m in uni:
        try:
            cs = S.parse_klines(api.get("/fapi/v1/klines", {"symbol": m["symbol"], "interval": tf,
                                                           "limit": cfg["kline_limit"]}), now_ms)
            f = S.compute_features(cs, cfg)
            results.append({"meta": m, "f": f, "i": len(cs) - 1})
        except Exception:  # noqa: BLE001
            pass
    now = time.time()
    imgs = S.live_images(results, cfg, {"img": {}}, now)[:15]
    S.SENT_IMGS = {x[4]: now for x in imgs}
    S.SENT_TXT = {x[4]: x[5] for x in imgs}
    print(f"MX| ===== {tf}: {len(imgs)} resim =====")
    done = set()
    for x in imgs:
        sym = x[3]
        if sym in done or len(done) >= 4:
            continue
        done.add(sym)
        r = next(r for r in results if r["meta"]["symbol"] == sym)
        S.fetch_tf_trends(api, r, now_ms, tf, False)
        print("MX| ---- KANAL RESMİ ----")
        for ln in x[2].split("\n"):
            print("MX| " + ln)
        print("MX| ---- SİNYAL MESAJINDA ----")
        for ln in S.trendline_lines(r) + [""] + S.formation_lines(r):
            print("MX| " + ln)
        print("MX|")
