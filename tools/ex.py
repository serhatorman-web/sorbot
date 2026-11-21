import base64, json, os, re, sys, time
from datetime import datetime, timezone, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as S
TR = timezone(timedelta(hours=3))
api = S.Binance()
now_ms = int(time.time() * 1000)
cfg = S.apply_tf_profile(json.load(open(S.CONFIG_PATH, encoding="utf-8")), "15m")
tc = cfg["trend_turn"]
universe, all_meta, tickers, funding = S.build_universe(api, cfg)
meta_by = {m["symbol"]: m for m in universe}
coins = ["MASKUSDT", "KITEUSDT"]
found = {"long": [], "short": []}
for sy in dict.fromkeys(coins):
    try:
        cs = S.parse_klines(api.get("/fapi/v1/klines", {"symbol": sy, "interval": "15m", "limit": 1500}), now_ms)
        f = S.compute_features(cs, cfg)
    except Exception:
        continue
    for k in range(300, len(cs) - 12):
        for d, s in (("long", 1), ("short", -1)):
            if S.trend_turn(f, k, s, tc):
                res = {"meta": {"symbol": sy}, "f": f, "i": k}
                e, sl, tps, _, _ = S.radar_levels(res, {"dir": d, "kind": "start"}, cfg)
                if tps and (tps[0] - f["c"][k]) * s > 0:
                    found[d].append((cs[k]["t"], sy))
for d in found:
    found[d].sort(reverse=True)
print("XX| bulunan:", {d: len(v) for d, v in found.items()})
out = []
for t, sy in [x for x in found["short"] if x[1] == "MASKUSDT"][-1:] + [x for x in found["long"] if x[1] == "KITEUSDT"][:1]:
    cs = S.parse_klines(api.get("/fapi/v1/klines", {"symbol": sy, "interval": "15m", "limit": 1500}), now_ms)
    k = next(j for j in range(len(cs)) if cs[j]["t"] == t)
    ctx = {"leaders": {}, "funding": funding, "tickers": tickers, "now_utc": datetime.fromtimestamp((t + 900000) / 1000, timezone.utc),
           "eth_bias": None, "btc_dom": None, "ndx": None}
    r = S.analyze_symbol(meta_by[sy], cs[:k + 1], ctx, cfg)
    r["_st_hold"] = True
    f = r["f"]
    s = 1 if f["c"][k] > f["o"][k] else -1
    d = "long" if s == 1 else "short"
    why = S.trend_turn(f, k, s, tc)
    S.fetch_tf_trends(api, r, t + 900000, "15m", True)
    S.compute_volume_profile(r, cfg)
    e, sl, tps, _, _ = S.radar_levels(r, {"dir": d, "kind": "start"}, cfg)
    msg = S.build_message(r, d, cfg, ctx["now_utc"]).replace("🔄 <b>TREND DÖNÜŞÜ</b>", "🔄 <b>TREND DÖNÜŞÜ</b>\n📌 " + " · ".join(why), 1)
    hit, res_ = [], "8 saatte TP1'e de stop'a da değmedi"
    for j in range(k + 1, min(len(cs), k + 33)):
        if (cs[j]["l"] if s == 1 else cs[j]["h"]) * s <= sl * s:
            res_ = "STOP"; break
        for n, tp in enumerate(tps, 1):
            if (cs[j]["h"] if s == 1 else cs[j]["l"]) * s >= tp * s and n not in hit:
                hit.append(n)
    if hit:
        res_ = "TP" + "/".join(map(str, hit)) + (" sonra STOP" if res_ == "STOP" else " görüldü")
    name = f"{sy.replace('USDT','')}_TD_{d.upper()}_{datetime.fromtimestamp(t/1000, TR).strftime('%d%m_%H%M')}"
    print("XX|", name, res_)
    out.append(f"==================== {name} · SONUÇ: {res_} ====================\n" + re.sub(r"<[^>]+>", "", msg))
    png = S.signal_chart_image(r, cfg, d, lv=(e, sl, tps))
    b = base64.b64encode(png).decode()
    for j in range(0, len(b), 3000):
        print("IM|", name, j // 3000, b[j:j + 3000])
b = base64.b64encode("\n\n".join(out).encode()).decode()
for j in range(0, len(b), 3000):
    print("TX|", j // 3000, b[j:j + 3000])
