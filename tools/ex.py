import json, os, sys, time
from datetime import datetime, timezone, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as S
TR = timezone(timedelta(hours=3))
api = S.Binance()
now_ms = int(time.time() * 1000)
for tf in ("15m", "1h"):
    cfg = S.apply_tf_profile(json.load(open(S.CONFIG_PATH, encoding="utf-8")), tf)
    universe, *_ = S.build_universe(api, cfg)
    syms = [m for m in universe if not m.get("leader_only") and m["type"] in set(cfg["pump_radar"]["types"])]
    sb, tc = cfg["pump_radar"]["squeeze_break"], cfg["trend_turn"]
    loose = dict(sb, min_move_pct=0, require_h4=False)
    rows = []
    for m in syms:
        try:
            cs = S.parse_klines(api.get("/fapi/v1/klines", {"symbol": m["symbol"], "interval": tf, "limit": 400}), now_ms)
            f = S.compute_features(cs, cfg)
        except Exception:
            continue
        for i in range(len(cs) - 12, len(cs)):
            hm = datetime.fromtimestamp(cs[i]["t"] / 1000, TR).strftime("%d.%m %H:%M")
            if not ("21.11 15:30" <= hm <= "21.11 16:30"):
                continue
            pd = S.squeeze_break(f, i, 1, sb); tt = S.trend_turn(f, i, 1, tc)
            chg = (f["c"][i] / f["o"][i] - 1) * 100
            if pd or tt or chg >= 2:
                rows.append((hm, m["symbol"], "PUMP" if pd else "", "TD-LONG" if tt else "", f"{chg:+.1f}%",
                             "st", f["st_dir"][i - 1], f["st_dir"][i], "htf", f["h4_ema"][i] + f["h4_st"][i]))
    print("XX|", tf, "kapanmış mumlarda 15:30-16:30 arası:", len(rows))
    for r in sorted(rows)[:40]:
        print("XX|", tf, *r)
