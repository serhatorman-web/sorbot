import json, os, sys, time, itertools
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as S
api = S.Binance()
now_ms = int(time.time() * 1000)
cfg = S.apply_tf_profile(json.load(open(S.CONFIG_PATH, encoding="utf-8")), "15m")
universe, all_meta, tickers, funding = S.build_universe(api, cfg)
coins = [m["symbol"] for m in universe if m["type"] == "COIN"][:100]
rows = []
for sy in coins:
    try:
        cs = S.parse_klines(api.get("/fapi/v1/klines", {"symbol": sy, "interval": "15m", "limit": 1500}), now_ms)
        f = S.compute_features(cs, cfg)
    except Exception:
        continue
    o, h, l, c = f["o"], f["h"], f["l"], f["c"]
    for i in range(300, len(cs) - 33):
        a = f["atr"][i - 1]
        if not a or not f["vol_ma"][i - 1]:
            continue
        vr = f["v"][i] / f["vol_ma"][i - 1]
        for s in (1, -1):
            body = (c[i] - o[i]) * s / a
            if body < 1.0 or vr < 1.5:
                continue
            brk3 = (c[i] - (max(h[i - 3:i]) if s == 1 else min(l[i - 3:i]))) * s > 0
            if not brk3:
                continue
            res = {"meta": {"symbol": sy}, "f": f, "i": i}
            e, stop, tps, _, _ = S.radar_levels(res, {"dir": "long" if s == 1 else "short", "kind": "start"}, cfg)
            if not tps:
                continue
            ref = c[i]
            out = 0
            for k in range(i + 1, i + 33):
                if (l[k] if s == 1 else h[k]) * s <= stop * s:
                    out = -1; break
                if (h[k] if s == 1 else l[k]) * s >= tps[0] * s:
                    out = 1; break
            mfe = max(((h[k] if s == 1 else l[k]) / ref - 1) * s * 100 for k in range(i + 1, i + 17))
            fl = {"st_ters": f["st_dir"][i] == -s, "st_ayni": f["st_dir"][i] == s,
                  "h4": (f["h4_ema"][i] + f["h4_st"][i]) * s > 0, "h4_ters": (f["h4_ema"][i] + f["h4_st"][i]) * s < 0,
                  "v3": vr >= 3, "b15": body >= 1.5, "c2": (c[i] / o[i] - 1) * s * 100 >= 2,
                  "dip": (c[i] - (min(l[i - 24:i]) if s == 1 else max(h[i - 24:i]))) * s <= 3 * a,
                  "tp_ileri": (tps[0] - ref) * s > 0}
            rows.append((out, mfe, fl))
days = (1500 - 333) / 96
def rep(name, sel):
    if not sel:
        return
    w = sum(1 for o_, _, _ in sel if o_ == 1); l_ = sum(1 for o_, _, _ in sel if o_ == -1)
    m3 = sum(1 for _, m, _ in sel if m >= 3)
    print(f"XX| {name:32s} n={len(sel):5d} ({len(sel)/len(coins)/days*228:6.1f}/gün) TP1>stop %{100*w/max(1,w+l_):.0f} (TP1 {w} stop {l_})  4s'te %3+: %{100*m3/len(sel):.0f}")
rep("hepsi", rows)
keys = list(rows[0][2].keys())
for k in keys:
    rep(k, [r for r in rows if r[2][k]])
best = []
for r_ in (2, 3, 4):
    for combo in itertools.combinations(keys, r_):
        if "st_ters" in combo and "st_ayni" in combo or "h4" in combo and "h4_ters" in combo:
            continue
        if "st_ters" not in combo or "tp_ileri" not in combo:
            continue
        sel = [r for r in rows if all(r[2][k] for k in combo)]
        w = sum(1 for o_, _, _ in sel if o_ == 1); l_ = sum(1 for o_, _, _ in sel if o_ == -1)
        if w + l_ >= 30:
            best.append((w / (w + l_), combo, sel))
best.sort(key=lambda x: -x[0])
for p, combo, sel in best[:12]:
    rep("+".join(combo), sel)
