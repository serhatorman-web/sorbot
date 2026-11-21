import json, os, sys, time
from datetime import datetime, timezone, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as S
TR = timezone(timedelta(hours=3))
api = S.Binance()
now_ms = int(time.time() * 1000)
DAYS = 10
for tf, lim, bpd in (("15m", 1300, 96), ("1h", 600, 24), ("4h", 400, 6)):
    cfg = S.apply_tf_profile(json.load(open(S.CONFIG_PATH, encoding="utf-8")), tf)
    universe, *_ = S.build_universe(api, cfg)
    syms = [m for m in universe if not m.get("leader_only") and m["type"] in set(cfg["pump_radar"]["types"])]
    tc = cfg["trend_turn"]
    cnt = {"tt_long": 0, "tt_short": 0, "pd_long": 0, "pd_short": 0}
    win = {"tt": [0, 0], "pd": [0, 0]}
    at16 = 0
    for m in syms:
        try:
            cs = S.parse_klines(api.get("/fapi/v1/klines", {"symbol": m["symbol"], "interval": tf, "limit": lim}), now_ms)
            if len(cs) < 300:
                continue
            f = S.compute_features(cs, cfg)
        except Exception:
            continue
        moves = {}
        for i in range(max(300, len(cs) - DAYS * bpd), len(cs)):
            for key in list(moves):
                if S.move_ended(moves[key], f, i, 1 if key.endswith("long") else -1):
                    moves.pop(key)
            c24 = (f["c"][i] / f["c"][max(0, i - bpd)] - 1) * 100
            pdres = S.pump_dump_analysis(f, cfg, c24, i)
            fired = []
            for rd in S.pump_radar(f, i, pdres, c24, cfg, None, None):
                if rd["kind"] == "start":
                    fired.append(("pd", rd["dir"]))
            for d, s in (("long", 1), ("short", -1)):
                if S.trend_turn(f, i, s, tc):
                    fired.append(("tt", d))
            for kind, d in fired:
                s = 1 if d == "long" else -1
                mk = f"{kind}|{d}"
                if mk in moves:
                    continue
                res = {"meta": m, "f": f, "i": i}
                e, sl, tps, _, _ = S.radar_levels(res, {"dir": d, "kind": "start"}, cfg)
                if not tps or (tps[0] - f["c"][i]) * s <= 0:
                    continue
                moves[mk] = {"t": f["t"][i], "entry": e, "stop": sl, "tps": list(tps)}
                cnt[f"{kind}_{d}"] += 1
                if datetime.fromtimestamp(cs[i]["t"] / 1000, TR).strftime("%d.%m %H") in ("21.11 15", "21.11 16"):
                    at16 += 1
                for k in range(i + 1, min(len(cs), i + 33)):
                    if (f["l"][k] if s == 1 else f["h"][k]) * s <= sl * s:
                        win[kind][1] += 1; break
                    if (f["h"][k] if s == 1 else f["l"][k]) * s >= tps[0] * s:
                        win[kind][0] += 1; break
    tt = cnt["tt_long"] + cnt["tt_short"]; pd = cnt["pd_long"] + cnt["pd_short"]
    print(f"XX| {tf}: Trend Dönüşü {tt/DAYS:.1f}/gün (LONG {cnt['tt_long']} SHORT {cnt['tt_short']}; TP1 {win['tt'][0]} stop {win['tt'][1]})"
          f" · PUMP/DUMP {pd/DAYS:.1f}/gün (PUMP {cnt['pd_long']} DUMP {cnt['pd_short']}; TP1 {win['pd'][0]} stop {win['pd'][1]}) · bugün 15:00-16:59 arası: {at16}")
