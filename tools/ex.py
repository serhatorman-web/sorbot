import base64, json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as S
api = S.Binance()
now_ms = int(time.time() * 1000)
cfg = S.apply_tf_profile(json.load(open(S.CONFIG_PATH, encoding="utf-8")), "15m")
universe, all_meta, tickers, funding = S.build_universe(api, cfg)
mb = {m["symbol"]: m for m in universe}
gas = next(s for s, n in S.COMMODITY_NAMES.items() if "GAZ" in S.tr_up(n) and s in mb)
eq = next(m["symbol"] for m in universe if m["type"] == "EQUITY")
for sy in (gas, eq, "SOLUSDT"):
    meta = mb[sy]
    cs = S.parse_klines(api.get("/fapi/v1/klines", {"symbol": sy, "interval": "15m", "limit": 600}), now_ms)
    f = S.compute_features(cs, cfg)
    res = {"meta": meta, "f": f, "i": len(cs) - 1}
    e, sl, tps, _, _ = S.radar_levels(res, {"dir": "long", "kind": "start"}, cfg)
    png = S.signal_chart_image(res, cfg, "long", lv=(e, sl, tps))
    cap = f"{S.display_name(meta)} · {S.kind_label(meta)} · 🔄 Trend Dönüşü · ⏱ mum kapanmadı"
    print("XX|", sy, "AÇIKLAMA:", cap)
    b = base64.b64encode(png).decode()
    for j in range(0, len(b), 3000):
        print("IM|", sy, j // 3000, b[j:j + 3000])
