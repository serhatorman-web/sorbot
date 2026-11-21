import base64, json, os, sys, time
from datetime import datetime, timezone, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as S
TR = timezone(timedelta(hours=3))
api = S.Binance()
now_ms = int(time.time() * 1000)
cfg = S.apply_tf_profile(json.load(open(S.CONFIG_PATH, encoding="utf-8")), "15m")
sb = cfg["pump_radar"]["squeeze_break"]
universe, all_meta, tickers, funding = S.build_universe(api, cfg)
coins = [m["symbol"] for m in universe if m["type"] == "COIN"]
got = []
for sy in coins:
    try:
        cs = S.parse_klines(api.get("/fapi/v1/klines", {"symbol": sy, "interval": "15m", "limit": 800}), now_ms)
        f = S.compute_features(cs, cfg)
    except Exception:
        continue
    for k in range(len(cs) - 1, 300, -1):
        for s in (1, -1):
            if f["st_dir"][k - 1] == -s and S.squeeze_break(f, k, s, sb):
                got.append((cs[k]["t"], sy, k, s))
    if len(got) >= 2:
        break
for t, sy, k, s in sorted(got, reverse=True)[:2]:
    cs = S.parse_klines(api.get("/fapi/v1/klines", {"symbol": sy, "interval": "15m", "limit": 800}), now_ms)
    k = next(j for j in range(len(cs)) if cs[j]["t"] == t)
    f = S.compute_features(cs[:k + 1], cfg)
    d = "long" if s == 1 else "short"
    for hold in (False, True):
        res = {"meta": {"symbol": sy, "type": "COIN", "precision": 4}, "f": f, "i": k, "_st_hold": hold}
        e, sl, tps, _, _ = S.radar_levels(res, {"dir": d, "kind": "start"}, cfg)
        png = S.signal_chart_image(res, cfg, d, kind_title="PUMP SİNYALİ" if s == 1 else "DUMP SİNYALİ", lv=(e, sl, tps))
        name = f"{sy.replace('USDT','')}_{'PUMP' if s == 1 else 'DUMP'}_{datetime.fromtimestamp(t/1000, TR).strftime('%d%m_%H%M')}_{'yeni' if hold else 'eski'}"
        print("XX|", name)
        b = base64.b64encode(png).decode()
        for j in range(0, len(b), 3000):
            print("IM|", name, j // 3000, b[j:j + 3000])
