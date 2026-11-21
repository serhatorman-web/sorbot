import json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as S
api = S.Binance()
now_ms = int(time.time() * 1000)
DAYS = 10
for tf, lim, bpd in (("15m", 1300, 96), ("1h", 600, 24), ("4h", 400, 6)):
    cfg = S.apply_tf_profile(json.load(open(S.CONFIG_PATH, encoding="utf-8")), tf)
    universe, all_meta, tickers, funding = S.build_universe(api, cfg)
    types = set(cfg["pump_radar"].get("types", ["COIN"]))
    syms = [m for m in universe if not m.get("leader_only") and m["type"] in types]
    tc, sb = cfg["trend_turn"], cfg["pump_radar"]["squeeze_break"]
    cnt = {"tt_long": 0, "tt_short": 0, "pd_long": 0, "pd_short": 0}
    win = {"tt": [0, 0], "pd": [0, 0]}
    per_type = {}
    for m in syms:
        try:
            kl = api.get(S.kline_path(m) if hasattr(S, "kline_path") else "/fapi/v1/klines", {"symbol": m["symbol"], "interval": tf, "limit": lim})
            cs = S.parse_klines(kl, now_ms)
            if len(cs) < 300:
                continue
            f = S.compute_features(cs, cfg)
        except Exception:
            continue
        moves = {}
        start = max(300, len(cs) - DAYS * bpd)
        for i in range(start, len(cs)):
            for key in list(moves):
                if S.move_ended(moves[key], f, i, 1 if key.endswith("long") else -1):
                    moves.pop(key)
            for d, s in (("long", 1), ("short", -1)):
                for kind, fn, arg in (("tt", S.trend_turn, tc), ("pd", S.squeeze_break, sb)):
                    mk = f"{kind}|{d}"
                    if mk in moves or not fn(f, i, s, arg):
                        continue
                    res = {"meta": m, "f": f, "i": i}
                    e, sl, tps, _, _ = S.radar_levels(res, {"dir": d, "kind": "start"}, cfg)
                    if not tps or (tps[0] - f["c"][i]) * s <= 0:
                        continue
                    moves[mk] = {"t": f["t"][i], "entry": e, "stop": sl, "tps": list(tps)}
                    cnt[f"{kind}_{d}"] += 1
                    per_type[m["type"]] = per_type.get(m["type"], 0) + 1
                    for k in range(i + 1, min(len(cs), i + 33)):
                        if (f["l"][k] if s == 1 else f["h"][k]) * s <= sl * s:
                            win[kind][1] += 1; break
                        if (f["h"][k] if s == 1 else f["l"][k]) * s >= tps[0] * s:
                            win[kind][0] += 1; break
    tt = cnt["tt_long"] + cnt["tt_short"]; pd = cnt["pd_long"] + cnt["pd_short"]
    print(f"XX| {tf}: {len(syms)} sembol, son {DAYS} gün → Trend Dönüşü {tt} ({tt/DAYS:.1f}/gün; LONG {cnt['tt_long']} SHORT {cnt['tt_short']}; TP1 {win['tt'][0]} stop {win['tt'][1]})"
          f" · PUMP/DUMP {pd} ({pd/DAYS:.1f}/gün; PUMP {cnt['pd_long']} DUMP {cnt['pd_short']}; TP1 {win['pd'][0]} stop {win['pd'][1]}) · türe göre {per_type}")
