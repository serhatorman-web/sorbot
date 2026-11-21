import json, os, sys, time, itertools
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as S
api = S.Binance()
now_ms = int(time.time() * 1000)
cfg = S.apply_tf_profile(json.load(open(S.CONFIG_PATH, encoding="utf-8")), "15m")
syms = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "SUIUSDT", "BNBUSDT",
        "DOTUSDT", "LTCUSDT", "NEARUSDT", "APTUSDT", "ARBUSDT", "OPUSDT", "INJUSDT", "TIAUSDT", "SEIUSDT", "WIFUSDT",
        "PEPEUSDT", "ENAUSDT", "ONDOUSDT", "TAOUSDT", "FETUSDT", "RENDERUSDT", "AAVEUSDT", "UNIUSDT", "HBARUSDT", "TRXUSDT",
        "FILUSDT", "ATOMUSDT", "ETCUSDT", "BCHUSDT", "XLMUSDT", "ICPUSDT", "JUPUSDT", "WLDUSDT", "TONUSDT", "CRVUSDT",
        "1000BONKUSDT", "ORDIUSDT", "STXUSDT", "GALAUSDT", "SANDUSDT", "MANAUSDT", "APEUSDT", "LDOUSDT", "PENDLEUSDT", "JTOUSDT"]
sc = dict(bars=12, max_range_atr=2.5, body_atr=0.8, volume_x=1.5)
rows = []
for sy in syms:
    try:
        cs = S.parse_klines(api.get("/fapi/v1/klines", {"symbol": sy, "interval": "15m", "limit": 1500}), now_ms)
    except Exception:
        continue
    f = S.compute_features(cs, cfg)
    n = len(cs)
    for i in range(300, n - 33):
        for s in (1, -1):
            if not S.squeeze_break(f, i, s, sc):
                continue
            res = {"meta": {"symbol": sy}, "f": f, "i": i}
            try:
                _, stop, tps, _, _ = S.radar_levels(res, {"dir": "long" if s == 1 else "short", "kind": "start"}, cfg)
            except Exception:
                continue
            e = f["c"][i]
            if (e - stop) * s <= 0:
                continue
            out = 0
            for k in range(i + 1, i + 33):
                if (f["l"][k] if s == 1 else f["h"][k]) * s <= stop * s:
                    out = -1; break
                if (f["h"][k] if s == 1 else f["l"][k]) * s >= tps[0] * s:
                    out = 1; break
            a = f["atr"][i - 1]
            vr = f["v"][i] / f["vol_ma"][i - 1]
            hi, lo = max(f["h"][i - 12:i]), min(f["l"][i - 12:i])
            fl = {"st": f["st_dir"][i] == s, "h4": (f["h4_ema"][i] + f["h4_st"][i]) * s > 0,
                  "ema50": (e - f["ema50"][i]) * s > 0, "ema200": (e - f["ema200"][i]) * s > 0,
                  "vol2": vr >= 2, "vol3": vr >= 3, "body1": (e - f["o"][i]) * s >= a, "rng2": (hi - lo) / a <= 2.0,
                  "rr": abs(tps[0] - e) >= abs(e - stop)}
            rows.append((out, fl))
keys = ["st", "h4", "ema50", "ema200", "vol2", "vol3", "body1", "rng2", "rr"]
def rep(name, sel):
    w = sum(1 for o, _ in sel if o == 1); l_ = sum(1 for o, _ in sel if o == -1)
    print(f"XX| {name:40s} n={len(sel):4d} gün/coin={len(sel)/len(syms)/((1500-333)/96):.3f} TP1={w} stop={l_} başarı%={100*w/max(1,w+l_):.0f}")
rep("hepsi", rows)
for k in keys:
    rep(k, [r for r in rows if r[1][k]])
res_ = []
for r_ in (2, 3, 4):
    for combo in itertools.combinations(keys, r_):
        sel = [r for r in rows if all(r[1][k] for k in combo)]
        w = sum(1 for o, _ in sel if o == 1); l_ = sum(1 for o, _ in sel if o == -1)
        if w + l_ >= 25:
            res_.append((w / (w + l_), combo, len(sel), w, l_))
res_.sort(reverse=True)
for p, combo, nn, w, l_ in res_[:15]:
    print(f"XX| {'+'.join(combo):40s} n={nn:4d} TP1={w} stop={l_} başarı%={100*p:.0f}")
