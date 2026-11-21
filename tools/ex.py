import base64, json, os, re, sys, time
from datetime import datetime, timezone, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as S
TR = timezone(timedelta(hours=3))
api = S.Binance()
now_ms = int(time.time() * 1000)
cfg = S.apply_tf_profile(json.load(open(S.CONFIG_PATH, encoding="utf-8")), "15m")
universe, all_meta, tickers, funding = S.build_universe(api, cfg)
meta_by = {m["symbol"]: m for m in universe}
out = []
for sy in ("BTCUSDT",):
    cs = S.parse_klines(api.get("/fapi/v1/klines", {"symbol": sy, "interval": "15m", "limit": 700}), now_ms)
    f = S.compute_features(cs, cfg)
    ks = [k for k in range(len(cs) - 60, len(cs)) if f["st_dir"][k] and f["st_dir"][k - 1] == -f["st_dir"][k]]
    if not ks:
        print("XX|", sy, "son 15 saatte Supertrend dönüşü yok"); continue
    k = ks[-1]
    cut = cs[:k + 1]
    t = cs[k]["t"]
    ctx = {"leaders": {}, "funding": funding, "tickers": tickers, "now_utc": datetime.fromtimestamp((t + 900000) / 1000, timezone.utc),
           "eth_bias": None, "btc_dom": None, "ndx": None}
    r = S.analyze_symbol(meta_by[sy], cut, ctx, cfg)
    d = "long" if f["st_dir"][k] == 1 else "short"
    S.fetch_tf_trends(api, r, t + 900000, "15m", True)
    S.compute_volume_profile(r, cfg)
    msg = S.build_message(r, d, cfg, ctx["now_utc"])
    e, sl, tps, _, _ = S.radar_levels(r, {"dir": d, "kind": "start"}, cfg)
    name = f"{sy.replace('USDT','')}_ST_{d.upper()}_{datetime.fromtimestamp(t/1000, TR).strftime('%d%m_%H%M')}"
    print("XX|", name)
    out.append(f"==================== {name} ====================\n" + re.sub(r"<[^>]+>", "", msg))
    png = S.signal_chart_image(r, cfg, d, lv=(e, sl, tps))
    b = base64.b64encode(png).decode()
    for j in range(0, len(b), 3000):
        print("IM|", name, j // 3000, b[j:j + 3000])
b = base64.b64encode("\n\n".join(out).encode()).decode()
for j in range(0, len(b), 3000):
    print("TX|", j // 3000, b[j:j + 3000])
