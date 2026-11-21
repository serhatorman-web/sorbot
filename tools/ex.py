import base64, json, os, sys, time
from datetime import datetime, timezone, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as S
TR = timezone(timedelta(hours=3))
api = S.Binance()
now_ms = int(time.time() * 1000)
sym, tf = "BTCUSDT", "15m"
cfg = S.apply_tf_profile(json.load(open(S.CONFIG_PATH, encoding="utf-8")), tf)
cs = S.parse_klines(api.get("/fapi/v1/klines", {"symbol": sym, "interval": tf, "limit": 900}), now_ms)
ts = lambda k: datetime.fromtimestamp(cs[k]["t"] / 1000, TR).strftime("%d.%m %H:%M")
k0 = next(k for k in range(len(cs)) if ts(k) == "21.11 04:00")
k1 = next(k for k in range(len(cs)) if ts(k) == "21.11 09:00")
moves, first = {}, None
for i in range(k0, k1):
    sub = cs[:i + 1]
    f = S.compute_features(sub, cfg)
    c24 = (f["c"][i] / f["c"][i - 96] - 1) * 100
    pdres = S.pump_dump_analysis(f, cfg, c24, i)
    for mk, mv in list(moves.items()):
        s_ = 1 if mk == "long" else -1
        if (f["c"][i] - mv["stop"]) * s_ <= 0 or (f["h"][i] if s_ == 1 else f["l"][i]) * s_ >= mv["tp3"] * s_:
            print("XX|", ts(i), "hareket bitti", mk); moves.pop(mk)
    for rd in S.pump_radar(f, i, pdres, c24, cfg, None, None):
        res = {"meta": {"symbol": sym, "type": "COIN", "precision": 2}, "f": f, "i": i}
        if rd["dir"] in moves:
            print("XX|", ts(i), rd["kind"], rd["dir"], "→ ENGELLENDİ (aynı hareket, ilk sinyal zaten gitti)")
            continue
        out = "XX| " + ts(i) + f" {rd['kind']} {rd['dir']} → GÖNDERİLİR"
        if rd["kind"] != "early":
            e, sl, tps, slab, tlab = S.radar_levels(res, rd, cfg)
            st_e, st_sl, st_tps, _ = S.levels(res, rd["dir"], cfg)
            out += f" | RADAR giriş {e:.2f} stop {sl:.2f} ({slab}) TP {[round(x, 2) for x in tps]} {tlab}"
            out += f" | (eski Supertrend: stop {st_sl:.2f} TP {[round(x, 2) for x in st_tps]})"
            moves[rd["dir"]] = {"stop": sl, "tp3": tps[2]}
            moves.pop("short" if rd["dir"] == "long" else "long", None)
            if first is None:
                first = (res, rd, i)
        print(out)
if first:
    res, rd, i = first
    kt = {"start": "PUMP SİNYALİ" if rd["dir"] == "long" else "DUMP SİNYALİ", "momentum": "PUMP HAREKETİ" if rd["dir"] == "long" else "DUMP HAREKETİ"}.get(rd["kind"], rd["kind"])
    png = S.signal_chart_image(res, cfg, rd["dir"], kind_title=kt, lv=S.radar_levels(res, rd, cfg)[:3])
    b = base64.b64encode(png).decode()
    for j in range(0, len(b), 3000):
        print("IM|", "first", j // 3000, b[j:j + 3000])
