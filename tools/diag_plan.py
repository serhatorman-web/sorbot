"""NVDA 15dk: kırılım anındaki resim, giriş / TP / stop bölgeleriyle (resim base64 olarak log'a yazılır)."""
import base64, sys, time
sys.path.insert(0, ".")
import scanner as S
import chart_img
import indicators as ta

api = S.Binance()
now = int(time.time() * 1000)
cs_all = S.parse_klines(api.get("/fapi/v1/klines", {"symbol": "NVDAUSDT", "interval": "15m", "limit": 400}), now)
best = None
for cut in range(len(cs_all) - 1, len(cs_all) - 40, -1):     # kırılım mumu son mum olacak şekilde geriye git
    cs = cs_all[:cut + 1][-300:]
    h = [x["h"] for x in cs]; l = [x["l"] for x in cs]; c = [x["c"] for x in cs]
    evs = [e for e in ta.trendlines_close(h, l, c) if e["state"] == "broken" and e["bars_ago"] == 0 and e["type"] == "falling"]
    if evs:
        best = (cs, evs[0])
        break
cs, ev = best
h = [x["h"] for x in cs]; l = [x["l"] for x in cs]; c = [x["c"] for x in cs]
n = len(c)
a_, b_ = ev["a"], ev["b"]
m = (c[b_] - c[a_]) / (b_ - a_)
ln = lambda k: c[b_] + m * (k - b_)
g = {"kirilim": 1, "seviye": ln(n - 1), "hedef": None,
     "ciz": {"noktalar": [(a_, c[a_]), (b_, c[b_])], "cizgiler": [((a_, c[a_]), (n - 1, ln(n - 1)))], "kb": n - 1, "retest": None},
     "plan": S.trade_plan(h, l, c, ta.atr(h, l, c, 14), 1)}
png = chart_img.render_pattern(cs, g, "NVDA · 15dk · Düşen trend çizgisi kırıldı", 2)
print("PL|", g["plan"], S.datetime.fromtimestamp(cs[-1]["t"] / 1000, S.TR_TZ))
b = base64.b64encode(png).decode()
for i in range(0, len(b), 3000):
    print(f"IM| {i // 3000:04d} {b[i:i + 3000]}", flush=True)
