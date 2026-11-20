"""SNDK bugün: fiyat hareketi, Supertrend dönüşleri (sinyal), kırılım resimleri (kapanış bazlı tekrar)."""
import json, os, sys, time
from datetime import datetime, timezone, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as S
import indicators as ta

SYM = "SNDKUSDT"
TR = timezone(timedelta(hours=3))
api = S.Binance()
now_ms = int(time.time() * 1000)
day0 = int(datetime(2026, 11, 20, 0, 0, tzinfo=TR).timestamp() * 1000)
T = lambda t: datetime.fromtimestamp(t / 1000, TR).strftime("%d %H:%M")
tk = api.get("/fapi/v1/ticker/24hr", {"symbol": SYM})
print("XX| 24s", tk.get("lastPrice"), tk.get("priceChangePercent"), "hacim", round(float(tk.get("quoteVolume", 0)) / 1e6, 1), "M$")
for tf in ("15m", "1h", "4h"):
    cfg = S.apply_tf_profile(json.load(open(S.CONFIG_PATH, encoding="utf-8")), tf)
    cs = S.parse_klines(api.get("/fapi/v1/klines", {"symbol": SYM, "interval": tf, "limit": 499}), now_ms)
    f = S.compute_features(cs, cfg)
    meta = {"symbol": SYM, "type": "EQUITY", "precision": 2}
    for i in range(len(cs)):
        if cs[i]["t"] < day0:
            continue
        x = cs[i]
        mv = (x["c"] / x["o"] - 1) * 100
        flip = f["st_dir"][i] != f["st_dir"][i - 1]
        vr = f["v"][i] / f["vol_ma"][i - 1] if f["vol_ma"][i - 1] else 0
        imgs = []
        sub = cs[:i + 1]
        fs = S.compute_features(sub, cfg)
        for o in S.live_images([{"meta": meta, "f": fs, "i": i}], cfg, {}, x["t"] / 1000 + 60):
            imgs.append(o[2].split("\n")[0].replace("<b>", "").replace("</b>", ""))
        if tf != "15m" or abs(mv) >= 1 or flip or imgs:
            print("XX|", tf, T(x["t"]), f"A {x['o']:.2f} K {x['c']:.2f} D {x['l']:.2f} %{mv:+.2f} hacim x{vr:.1f}",
                  "ST:" + ("AL" if f["st_dir"][i] == 1 else "SAT"), "DÖNÜŞ→SİNYAL" if flip else "", imgs)
