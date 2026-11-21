import json, os, sys, time, copy
from datetime import datetime, timezone, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as S
TR = timezone(timedelta(hours=3))
api = S.Binance()
now_ms = int(time.time() * 1000)
base = json.load(open(S.CONFIG_PATH, encoding="utf-8"))
tk = api.get("/fapi/v1/ticker/24hr", {})
syms = [t["symbol"] for t in sorted(tk, key=lambda t: -float(t["quoteVolume"])) if t["symbol"].endswith("USDT")][:100]
for tf in ("15m", "1h"):
    cfg = S.apply_tf_profile(copy.deepcopy(base), tf)
    st = {v: [0, 0, 0] for v in ("dönüş/düzeltme", "trend içi")}
    for sym in (["BTCUSDT"] + [x for x in syms if x != "BTCUSDT"]):
        try:
            cs = S.parse_klines(api.get("/fapi/v1/klines", {"symbol": sym, "interval": tf, "limit": 1000}), now_ms)
            f = S.compute_features(cs, cfg)
        except Exception:
            continue
        n = len(cs); days = n * (15 if tf == "15m" else 60) / 1440
        tc = cfg["trend_turn"]
        last = {1: -99, -1: -99}
        for k in range(60, n - 1):
            for s in (1, -1):
                if k - last[s] < 8:
                    continue
                why = S.trend_turn(f, k, s, tc)
                if not why:
                    continue
                res = {"f": f, "i": k}
                e, sl, tps, _, _ = S.radar_levels(res, {"dir": "long" if s == 1 else "short", "kind": "start"}, cfg)
                if not tps or (tps[0] - f["c"][k]) * s <= 0:
                    continue
                last[s] = k
                out = 2
                for j in range(k + 1, min(n, k + 33)):
                    if (f["l"][j] if s == 1 else f["h"][j]) * s <= sl * s:
                        out = 1; break
                    if (f["h"][j] if s == 1 else f["l"][j]) * s >= tps[0] * s:
                        out = 0; break
                kind = "trend içi" if any("Trend içi" in w for w in why) else "dönüş/düzeltme"
                st[kind][out] += 1
                if sym == "BTCUSDT" and cs[k]["t"] > now_ms - 12 * 3600000:
                    print("XX| BTC", tf, kind, datetime.fromtimestamp(cs[k]["t"] / 1000, TR).strftime("%H:%M"),
                          "AL" if s == 1 else "SAT", "giriş", round(e), "stop", round(sl), "TP", [round(x) for x in tps],
                          ["TP1", "STOP", "açık"][out])
    for nm in st:
        w, lo, op = st[nm]
        print("XX|", tf, nm, f"günde {(w+lo+op)/days*228/100:.0f}", f"TP1 önce {w} stop önce {lo} açık {op} -> %{100*w/max(1,w+lo):.0f}")
