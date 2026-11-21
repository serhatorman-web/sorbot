import base64, json, os, re, sys, time
from datetime import datetime, timezone, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as S
TR = timezone(timedelta(hours=3))
api = S.Binance()
now_ms = int(time.time() * 1000)
cfg = S.apply_tf_profile(json.load(open(S.CONFIG_PATH, encoding="utf-8")), "15m")
universe, all_meta, tickers, funding = S.build_universe(api, cfg)
syms = [m for m in universe if not m.get("leader_only") and m["type"] in set(cfg["pump_radar"]["types"])]
want = {("tt", "long"): None, ("tt", "short"): None, ("pd", "long"): None, ("pd", "short"): None}
data = {}
for m in syms:
    if all(want.values()):
        break
    try:
        cs = S.parse_klines(api.get("/fapi/v1/klines", {"symbol": m["symbol"], "interval": "15m", "limit": 500}), now_ms)
        f = S.compute_features(cs, cfg)
    except Exception:
        continue
    for i in range(len(cs) - 1, len(cs) - 60, -1):
        c24 = (f["c"][i] / f["c"][i - 96] - 1) * 100
        kinds = []
        for d, s in (("long", 1), ("short", -1)):
            if S.trend_turn(f, i, s, cfg["trend_turn"]):
                kinds.append(("tt", d))
        pdres = S.pump_dump_analysis(f, cfg, c24, i)
        kinds += [("pd", rd["dir"]) for rd in S.pump_radar(f, i, pdres, c24, cfg, None, None) if rd["kind"] == "start"]
        for key in kinds:
            if want.get(key) is None:
                want[key] = (m, cs, i)
for (kind, d), v in want.items():
    if not v:
        print("XX|", kind, d, "son 15 saatte örnek yok"); continue
    m, cs, i = v
    t = cs[i]["t"]
    ctx = {"leaders": {}, "funding": funding, "tickers": tickers, "now_utc": datetime.fromtimestamp((t + 900000) / 1000, timezone.utc),
           "eth_bias": None, "btc_dom": None, "ndx": None}
    r = S.analyze_symbol(m, cs[:i + 1], ctx, cfg)
    S.compute_volume_profile(r, cfg)
    rd = {"dir": d, "kind": "start", **({"src": "tt"} if kind == "tt" else {})}
    e, sl, tps, sll, tpl = S.radar_levels(r, rd, cfg)
    s = 1 if d == "long" else -1
    hm = lambda k: datetime.fromtimestamp(cs[k]["t"] / 1000, TR).strftime("%d.%m %H:%M")
    ek = r["_entry_k"]
    run = " ".join(f"{hm(k)[6:]}{'🟩' if cs[k]['c'] > cs[k]['o'] else '🟥'}" for k in range(max(0, ek - 2), i + 1))
    name = f"{m['symbol'].replace('USDT','')}_{'TD' if kind == 'tt' else ('PUMP' if s == 1 else 'DUMP')}_{d.upper()}"
    print("XX|", name, "| sinyal mumu", hm(i), "| AL/SAT ve giriş mumu", hm(ek), "| mumlar:", run)
    print("XX|    giriş", e, "TP", [f"{n} {round(v,6)}" for n, v in zip(tpl, tps)], "stop", round(sl, 6), sll)
    png = S.signal_chart_image(r, cfg, d, kind_title=None if kind == "tt" else ("PUMP SİNYALİ" if s == 1 else "DUMP SİNYALİ"), lv=(e, sl, tps))
    b = base64.b64encode(png).decode()
    for j in range(0, len(b), 3000):
        print("IM|", name, j // 3000, b[j:j + 3000])
