import json, os, sys, time, statistics as st
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as S
api = S.Binance()
now_ms = int(time.time() * 1000)
DAYS = 10
def med(x):
    return round(st.median(x), 2) if x else None
for tf, lim, bpd in (("15m", 1300, 96), ("1h", 600, 24)):
    cfg = S.apply_tf_profile(json.load(open(S.CONFIG_PATH, encoding="utf-8")), tf)
    universe, *_ = S.build_universe(api, cfg)
    syms = [m for m in universe if not m.get("leader_only") and m["type"] in set(cfg["pump_radar"]["types"])]
    tc = cfg["trend_turn"]
    R = {k: {"n": 0, "tp1": 0, "stop": 0, "late": [], "mfe": [], "mae": [], "first": 0} for k in ("tt", "pd_brk", "pd_sb")}
    for m in syms:
        try:
            cs = S.parse_klines(api.get("/fapi/v1/klines", {"symbol": m["symbol"], "interval": tf, "limit": lim}), now_ms)
            if len(cs) < 300:
                continue
            f = S.compute_features(cs, cfg)
        except Exception:
            continue
        moves = {}
        for i in range(max(300, len(cs) - DAYS * bpd), len(cs) - 1):
            for key in list(moves):
                if S.move_ended(moves[key], f, i, 1 if key.endswith("long") else -1):
                    moves.pop(key)
            c24 = (f["c"][i] / f["c"][max(0, i - bpd)] - 1) * 100
            pdres = S.pump_dump_analysis(f, cfg, c24, i)
            fired = []
            for rd in S.pump_radar(f, i, pdres, c24, cfg, None, None):
                if rd["kind"] == "start":
                    sb = any("sıkışma" in w and "kırıldı" in w and "mumluk" in w for w in rd["reasons"])
                    fired.append(("pd_sb" if sb else "pd_brk", rd["dir"]))
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
                r = R[kind]; r["n"] += 1
                c = f["c"][i]
                ext = min(f["l"][i - 12:i + 1]) if s == 1 else max(f["h"][i - 12:i + 1])
                r["late"].append(abs(c / ext - 1) * 100)            # dip/tepeden sinyal anına kadar kaçırılan %
                fut = range(i + 1, min(len(cs), i + 17))
                if fut:
                    r["mfe"].append(max(((f["h"][k] if s == 1 else f["l"][k]) / c - 1) * s * 100 for k in fut))
                    r["mae"].append(max(((f["l"][k] if s == 1 else f["h"][k]) / c - 1) * -s * 100 for k in fut))
                for k in range(i + 1, min(len(cs), i + 33)):
                    if (f["l"][k] if s == 1 else f["h"][k]) * s <= sl * s:
                        r["stop"] += 1; break
                    if (f["h"][k] if s == 1 else f["l"][k]) * s >= tps[0] * s:
                        r["tp1"] += 1; break
    for k, r in R.items():
        print(f"XX| {tf} {k:7s} {r['n']/DAYS:5.1f}/gün  TP1>stop %{100*r['tp1']/max(1,r['tp1']+r['stop']):.0f} ({r['tp1']}/{r['stop']})"
              f"  dip/tepeden sonra sinyale kadar medyan %{med(r['late'])}  sonraki 16 mumda medyan en iyi %{med(r['mfe'])} / en kötü %{med(r['mae'])}")
