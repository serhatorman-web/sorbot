import json, os, sys, time, copy
from datetime import datetime, timezone, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as S
TR = timezone(timedelta(hours=3))
api = S.Binance(); now_ms = int(time.time() * 1000)
base = json.load(open(S.CONFIG_PATH, encoding="utf-8"))
cfg = S.apply_tf_profile(copy.deepcopy(base), "15m")
for sym in ("VETUSDT", "LITUSDT", "AVNTUSDT"):
    cs = S.parse_klines(api.get("/fapi/v1/klines", {"symbol": sym, "interval": "15m", "limit": 600}), 1 << 62)
    m1 = S.parse_klines(api.get("/fapi/v1/klines", {"symbol": sym, "interval": "1m", "limit": 120}), 1 << 62)
    for k in range(len(cs) - 6, len(cs)):
        t0 = cs[k]["t"]
        for mm in [x for x in m1 if t0 <= x["t"] < t0 + 900000]:
            sub = [x for x in m1 if t0 <= x["t"] <= mm["t"]]
            part = dict(cs[k], h=max(x["h"] for x in sub), l=min(x["l"] for x in sub), c=sub[-1]["c"], v=sum(x["v"] for x in sub))
            f = S.compute_features(cs[:k] + [part], cfg)
            if S.trend_turn(f, k, 1, cfg["trend_turn"], frac=(mm["t"] + 60000 - t0) / 900000):
                print("XX|", sym, "AL sinyali", datetime.fromtimestamp((mm["t"] + 60000) / 1000, TR).strftime("%H:%M")); break
tk = api.get("/fapi/v1/ticker/24hr", {})
syms = [t["symbol"] for t in sorted(tk, key=lambda t: -float(t["quoteVolume"])) if t["symbol"].endswith("USDT")][:100]
for tf in ("15m", "1h"):
    cfg = S.apply_tf_profile(copy.deepcopy(base), tf)
    st = {"hacimli(1.5x)": [0, 0, 0], "hacimsiz": [0, 0, 0]}
    for sym in syms:
        try:
            cs = S.parse_klines(api.get("/fapi/v1/klines", {"symbol": sym, "interval": tf, "limit": 1000}), now_ms)
            f = S.compute_features(cs, cfg)
        except Exception:
            continue
        n = len(cs); days = n * (15 if tf == "15m" else 60) / 1440
        for nm, vx in (("hacimli(1.5x)", 1.5), ("hacimsiz", 0)):
            tc = dict(cfg["trend_turn"], volume_x=vx); last = {1: -99, -1: -99}
            for k in range(60, n - 1):
                for s in (1, -1):
                    if k - last[s] < 8 or not S.trend_turn(f, k, s, tc):
                        continue
                    e, sl, tps, _, _ = S.radar_levels({"f": f, "i": k}, {"dir": "long" if s == 1 else "short", "kind": "start"}, cfg)
                    if not tps or (tps[0] - f["c"][k]) * s <= 0:
                        continue
                    last[s] = k; out = 2
                    for j in range(k + 1, min(n, k + 33)):
                        if (f["l"][j] if s == 1 else f["h"][j]) * s <= sl * s:
                            out = 1; break
                        if (f["h"][j] if s == 1 else f["l"][j]) * s >= tps[0] * s:
                            out = 0; break
                    st[nm][out] += 1
    for nm in st:
        w, lo, op = st[nm]
        print("XX|", tf, nm, f"günde {(w+lo+op)/days*228/100:.0f}", f"TP1 önce {w} stop önce {lo} -> %{100*w/max(1,w+lo):.0f}")
