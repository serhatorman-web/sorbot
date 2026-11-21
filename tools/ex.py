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
k1 = next(k for k in range(len(cs)) if ts(k) == "21.11 07:30")
moves, first = {}, None
for i in range(k0, k1):
    sub = cs[:i + 1]
    f = S.compute_features(sub, cfg)
    c24 = (f["c"][i] / f["c"][i - 96] - 1) * 100
    pdres = S.pump_dump_analysis(f, cfg, c24, i)
    for mk, mv in list(moves.items()):
        if S.move_ended(mv, f, i, 1 if mk == "long" else -1):
            print("XX|", ts(i), "hareket bitti", mk); moves.pop(mk)
        else:
            print("XX|", ts(i), "hareket sürüyor", mk, "izleyen stop", round(mv["stop"], 2))
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
            moves[rd["dir"]] = {"t": f["t"][i], "entry": e, "stop": sl, "tps": list(tps)}
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
# --- sıklık / başarı testi: 40 coin, 15dk, son 900 mum, farklı ayarlar ---
syms = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "SUIUSDT", "BNBUSDT",
        "DOTUSDT", "LTCUSDT", "NEARUSDT", "APTUSDT", "ARBUSDT", "OPUSDT", "INJUSDT", "TIAUSDT", "SEIUSDT", "WIFUSDT",
        "PEPEUSDT", "ENAUSDT", "ONDOUSDT", "TAOUSDT", "FETUSDT", "RENDERUSDT", "AAVEUSDT", "UNIUSDT", "HBARUSDT", "TRXUSDT",
        "FILUSDT", "ATOMUSDT", "ETCUSDT", "BCHUSDT", "XLMUSDT", "ICPUSDT", "JUPUSDT", "WLDUSDT", "TONUSDT", "CRVUSDT"]
data = []
for sy in syms:
    try:
        c2 = S.parse_klines(api.get("/fapi/v1/klines", {"symbol": sy, "interval": "15m", "limit": 900}), now_ms)
        data.append((c2, S.compute_features(c2, cfg)))
    except Exception:
        pass
days = 900 / 96
grid = [dict(bars=12, max_range_atr=2.5, body_atr=0.8, volume_x=1.5), dict(bars=12, max_range_atr=2.0, body_atr=1.0, volume_x=2.0),
        dict(bars=12, max_range_atr=2.0, body_atr=1.0, volume_x=2.0, trend=1), dict(bars=16, max_range_atr=2.0, body_atr=1.2, volume_x=2.5),
        dict(bars=12, max_range_atr=2.5, body_atr=0.8, volume_x=1.5, trend=1)]
for sc in grid:
    tot = win = loss = 0
    for c2, f2 in data:
        for i in range(300, len(c2) - 17):
            for s in (1, -1):
                if sc.get("trend") and (f2["st_dir"][i] != s or (f2["c"][i] - f2["ema200"][i]) * s < 0):
                    continue
                if S.squeeze_break(f2, i, s, sc):
                    tot += 1
                    a = f2["atr"][i]; e = f2["c"][i]; r_ = None
                    for k in range(i + 1, i + 17):
                        if (f2["h"][k] if s == 1 else f2["l"][k]) * s >= (e + s * 2 * a) * s:
                            r_ = "w"; break
                        if (f2["l"][k] if s == 1 else f2["h"][k]) * s <= (e - s * 2 * a) * s:
                            r_ = "l"; break
                    win += r_ == "w"; loss += r_ == "l"
    print("XX| AYAR", sc, "→", tot, "tetik,", round(tot / len(data) / days, 2), "coin/gün; +2ATR", win, "-2ATR", loss,
          "başarı %", round(100 * win / max(1, win + loss)))
