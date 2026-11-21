import base64, json, os, re, sys, time
from datetime import datetime, timezone, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as S
TR = timezone(timedelta(hours=3))
api = S.Binance()
now_ms = int(time.time() * 1000)
cfg = S.apply_tf_profile(json.load(open(S.CONFIG_PATH, encoding="utf-8")), "1h")
universe, all_meta, tickers, funding = S.build_universe(api, cfg)
mb = {m["symbol"]: m for m in universe}
cs = S.parse_klines(api.get("/fapi/v1/klines", {"symbol": "IRYSUSDT", "interval": "1h", "limit": 600}), now_ms)
ts = lambda k: datetime.fromtimestamp(cs[k]["t"] / 1000, TR).strftime("%d.%m %H:%M")
k = next(j for j in range(len(cs)) if ts(j) == "21.11 15:00")
t = cs[k]["t"]
ctx = {"leaders": {}, "funding": funding, "tickers": tickers, "now_utc": datetime.fromtimestamp((t + 3600000) / 1000, timezone.utc),
       "eth_bias": None, "btc_dom": None, "ndx": None}
r = S.analyze_symbol(mb["IRYSUSDT"], cs[:k + 1], ctx, cfg)
S.fetch_tf_trends(api, r, t + 3600000, "1h", True)
S.compute_volume_profile(r, cfg)
print("XX| VP (VAH, POC, VAL):", r.get("vp"))
e, sl, tps, sll, tpl = S.radar_levels(r, {"dir": "long", "kind": "start"}, cfg)
print("XX| giriş", e, "TP", list(zip(tpl, tps)), "stop", sl, sll)
msg = re.sub(r"<[^>]+>", "", S.build_message(r, "long", cfg, ctx["now_utc"]))
for ln in msg.split("\n"):
    if ln.startswith(("Giriş", "TP", "Stop")):
        print("XX|", ln)
png = S.signal_chart_image(r, cfg, "long", lv=(e, sl, tps))
b = base64.b64encode(png).decode()
for j in range(0, len(b), 3000):
    print("IM|", "IRYS", j // 3000, b[j:j + 3000])
