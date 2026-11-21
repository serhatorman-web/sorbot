import json, os, sys, time, itertools
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as S
api = S.Binance()
now_ms = int(time.time() * 1000)
cfg = S.apply_tf_profile(json.load(open(S.CONFIG_PATH, encoding="utf-8")), "15m")
universe, all_meta, tickers, funding = S.build_universe(api, cfg)
coins = [m["symbol"] for m in universe if m["type"] == "COIN"][:100]
base = dict(bars=12, max_range_atr=3.0, body_atr=0.8, volume_x=1.5, require_h4=False, require_st=False)
rows = []
for sy in coins:
    try:
        cs = S.parse_klines(api.get("/fapi/v1/klines", {"symbol": sy, "interval": "15m", "limit": 1500}), now_ms)
        f = S.compute_features(cs, cfg)
    except Exception:
        continue
    n = len(cs)
    for i in range(300, n - 17):
        for s in (1, -1):
            if not S.squeeze_break(f, i, s, base):
                continue
            e = f["c"][i]; a = f["atr"][i - 1]
            res = {"meta": {"symbol": sy}, "f": f, "i": i}
            try:
                _, stop, tps, _, _ = S.radar_levels(res, {"dir": "long" if s == 1 else "short", "kind": "start"}, cfg)
            except Exception:
                continue
            mfe = 0; stopped = False
            for k in range(i + 1, i + 17):
                if (f["l"][k] if s == 1 else f["h"][k]) * s <= stop * s:
                    stopped = True; break
                mfe = max(mfe, ((f["h"][k] if s == 1 else f["l"][k]) / e - 1) * s * 100)
            vr = f["v"][i] / f["vol_ma"][i - 1]
            body = (e - f["o"][i]) * s / a
            chg = (e / f["o"][i] - 1) * s * 100
            hi, lo = max(f["h"][i - 12:i]), min(f["l"][i - 12:i])
            fl = {"h4": (f["h4_ema"][i] + f["h4_st"][i]) * s > 0, "st": f["st_dir"][i] == s,
                  "v3": vr >= 3, "v5": vr >= 5, "v8": vr >= 8, "b15": body >= 1.5, "b2": body >= 2,
                  "c1": chg >= 1, "c2": chg >= 2, "c3": chg >= 3, "r2": (hi - lo) / a <= 2.0}
            rows.append((mfe, stopped, fl))
days = (1500 - 317) / 96
def rep(name, sel):
    if not sel:
        return
    real = sum(1 for m, st, _ in sel if m >= 3)
    real5 = sum(1 for m, st, _ in sel if m >= 5)
    stp = sum(1 for m, st, _ in sel if st and m < 3)
    print(f"XX| {name:28s} n={len(sel):4d} ({len(sel)/len(coins)/days*228:5.1f}/gün 228 coin) gerçek≥%3: %{100*real/len(sel):.0f}  ≥%5: %{100*real5/len(sel):.0f}  %3 olmadan stop: %{100*stp/len(sel):.0f}")
rep("hepsi", rows)
keys = list(rows[0][2].keys()) if rows else []
for k in keys:
    rep(k, [r for r in rows if r[2][k]])
best = []
for r_ in (1, 2, 3):
    for combo in itertools.combinations(keys, r_):
        sel = [r for r in rows if all(r[2][k] for k in combo)]
        if len(sel) >= 20:
            best.append((sum(1 for m, _, _ in sel if m >= 3) / len(sel), combo, sel))
best.sort(key=lambda x: -x[0])
for p, combo, sel in best[:15]:
    rep("+".join(combo), sel)
