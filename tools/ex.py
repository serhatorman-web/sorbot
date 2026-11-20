import base64, json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as S

api = S.Binance()
now_ms = int(time.time() * 1000)
for sym, tf in (("BULLAUSDT", "4h"),):
    cfg = S.apply_tf_profile(json.load(open(S.CONFIG_PATH, encoding="utf-8")), tf)
    cfg["live_images"]["closed_images"] = True
    allc = S.parse_klines(api.get("/fapi/v1/klines", {"symbol": sym, "interval": tf, "limit": 600}), now_ms)
    meta = {"symbol": sym, "type": "COIN", "precision": 5}
    for cut in range(len(allc) - 1, len(allc) - 80, -1):
        cs = allc[:cut + 1]
        f = S.compute_features(cs, cfg)
        import chart_img as CI
        _orig = CI.render_pattern
        def _rp(cs_, g_, t_, p_=None, tf_ms=None):
            cz = g_.get("ciz") or {}
            print("XX| dbg", sym, len(cs_), "noktalar", [k for k, _ in cz.get("noktalar", [])], "cizgiler", [[a[0], b[0]] for a, b in cz.get("cizgiler", [])], "zig", [k for k, _ in cz.get("zigzag", [])][:12], "kb", cz.get("kb"))
            return _orig(cs_, g_, t_, p_, tf_ms)
        CI.render_pattern = _rp
        out = S.live_images([{"meta": meta, "f": f, "i": len(cs) - 1}], cfg, {}, time.time())
        CI.render_pattern = _orig
        if out:
            print("XX|", sym, tf, out[0][2].split("\n")[0])
            b = base64.b64encode(out[0][1]).decode()
            for j in range(0, len(b), 3000):
                print("IM|", f"{sym}{tf}", j // 3000, b[j:j + 3000])
            break
