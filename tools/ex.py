import json, os, sys, time, base64
from datetime import datetime, timezone, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as S
TR = timezone(timedelta(hours=3))
api = S.Binance()
cfg = S.apply_tf_profile(json.load(open(S.CONFIG_PATH, encoding="utf-8")), "15m")
uni = S.build_universe(api, cfg)
uni = uni[0] if isinstance(uni, tuple) else uni
meta = next(m for m in uni if m["symbol"] == "VETUSDT")
cs = S.parse_klines(api.get("/fapi/v1/klines", {"symbol": "VETUSDT", "interval": "15m", "limit": 600}), 1 << 62)
k = next(j for j in range(len(cs)) if datetime.fromtimestamp(cs[j]["t"] / 1000, TR).strftime("%d.%m %H:%M") == "21.11 20:15")
m1 = S.parse_klines(api.get("/fapi/v1/klines", {"symbol": "VETUSDT", "interval": "1m", "limit": 200}), 1 << 62)
sub = [x for x in m1 if cs[k]["t"] <= x["t"] < cs[k]["t"] + 60000]
cs = cs[:k] + [dict(cs[k], h=max(x["h"] for x in sub), l=min(x["l"] for x in sub), c=sub[-1]["c"], v=sum(x["v"] for x in sub))]
now_ms = cs[k]["t"] + 60000
now_utc = datetime.fromtimestamp(now_ms / 1000, timezone.utc)
ctx = {"leaders": {}, "funding": {}, "tickers": {}, "now_utc": now_utc, "eth_bias": None, "btc_dom": None, "ndx": S.nasdaq_index()}
r = S.analyze_symbol(meta, cs, ctx, cfg)
why = S.trend_turn(r["f"], r["i"], 1, cfg["trend_turn"], frac=1 / 15)
print("XX| why", why)
e_, sl_, tps_, _, _ = S.radar_levels(r, {"dir": "long", "kind": "start", "src": "tt"}, cfg)
S.fetch_tf_trends(api, r, now_ms, cfg["timeframe"], True)
S.compute_volume_profile(r, cfg)
msg = S.build_message(r, "long", cfg, now_utc)
msg = msg.replace("🔄 <b>TREND DÖNÜŞÜ</b>", "🔄 <b>TREND DÖNÜŞÜ</b>\n📌 " + " · ".join(why or []), 1).replace("Mum Kapanışı", "Mum içi · mum kapanmadı")
for ln in msg.split("\n"):
    print("XX|", ln)
png = S.signal_chart_image(r, cfg, "long", lv=(e_, sl_, tps_))
b = base64.b64encode(png).decode()
for n in range(0, len(b), 3000):
    print("IM| vet", n // 3000, b[n:n + 3000])
