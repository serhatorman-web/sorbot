"""SNDK: bölünme düzeltmesiyle pump/dump radarı (1s, 15dk) + 15dk'da radar açılırsa günlük uyarı sayısı."""
import json, os, sys, time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as S

TR = timezone(timedelta(hours=3))
api = S.Binance()
now_ms = int(time.time() * 1000)
day0 = int(datetime(2026, 11, 20, 0, 0, tzinfo=TR).timestamp() * 1000)
T = lambda t: datetime.fromtimestamp(t / 1000, TR).strftime("%d %H:%M")


def radar_hits(sym, tf, since, cfg):
    cs = S.parse_klines(api.get("/fapi/v1/klines", {"symbol": sym, "interval": tf, "limit": 499}), now_ms)
    f = S.compute_features(cs, cfg)
    out = []
    for i in range(300, len(cs)):
        if cs[i]["t"] < since:
            continue
        chg24 = S.pct(f["c"][i], f["c"][max(0, i - (96 if tf == "15m" else 24))])
        pdres = S.pump_dump_analysis(f, cfg, chg24, i)
        for rd in S.pump_radar(f, i, pdres, chg24, cfg):
            out.append((cs[i]["t"], rd["dir"], rd["kind"], rd["score"], rd["reasons"]))
    return out, cs


for tf in ("1h", "15m"):
    cfg = S.apply_tf_profile(json.load(open(S.CONFIG_PATH, encoding="utf-8")), tf)
    cfg["pump_radar"]["enabled"] = True
    hits, cs = radar_hits("SNDKUSDT", tf, day0, cfg)
    print("XX| SNDK", tf, "bölünme sonrası ilk mumlar:", [round(x["c"], 2) for x in cs[-60:-50]])
    for h in hits:
        print("XX| SNDK", tf, T(h[0]), "kapanışı sonrası", h[1], h[2], h[3], h[4])
cfg = S.apply_tf_profile(json.load(open(S.CONFIG_PATH, encoding="utf-8")), "15m")
cfg["pump_radar"]["enabled"] = True
uni, *_ = S.build_universe(api, cfg)
since = now_ms - 2 * 86_400_000
cnt = {}
with ThreadPoolExecutor(max_workers=8) as ex:
    for hits, _ in ex.map(lambda m: radar_hits(m["symbol"], "15m", since, cfg), uni):
        for h in hits:
            cnt[(h[1], h[2])] = cnt.get((h[1], h[2]), 0) + 1
print("XX| 15dk radar açık olsaydı son 2 gün (günlük):", {f"{k[0]}/{k[1]}": round(v / 2, 1) for k, v in cnt.items()})
