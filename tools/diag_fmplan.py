"""Formasyon resmi örneği (canlı kodla aynı): kırılım anında giriş / TP / stop bölgeleri."""
import base64, sys, time
sys.path.insert(0, ".")
import scanner as S
import chart_img
import patterns as pt
import indicators as ta

api = S.Binance()
now = int(time.time() * 1000)
for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT", "LINKUSDT", "SUIUSDT", "AVAXUSDT", "BNBUSDT",
            "LTCUSDT", "NEARUSDT", "AAVEUSDT", "UNIUSDT", "DOTUSDT"):
    cs_all = S.parse_klines(api.get("/fapi/v1/klines", {"symbol": sym, "interval": "15m", "limit": 600}), now)
    for cut in range(len(cs_all) - 1, len(cs_all) - 200, -1):
        cs = cs_all[:cut + 1][-300:]
        h = [x["h"] for x in cs]; l = [x["l"] for x in cs]; c = [x["c"] for x in cs]
        a = ta.atr(h, l, c, 14)
        fs = [g for g in pt.chart_patterns(h, l, c, a) if g["durum"] == "kirildi" and (g.get("ciz") or {}).get("kb") == len(c) - 1
              and g["ad"] not in ("Fincan Kulp", "Ters Fincan Kulp")]
        if fs:
            g = dict(fs[0], plan=S.trade_plan(h, l, c, a, fs[0]["kirilim"]))
            yonu = "yukarı" if g["kirilim"] == 1 else "aşağı"
            png = chart_img.render_pattern(cs, g, f"{sym[:-4]} · 15dk · {g['ad']} ({yonu} kırıldı)", None)
            print("FP|", sym, g["ad"], g["plan"], S.datetime.fromtimestamp(cs[-1]["t"] / 1000, S.TR_TZ))
            b = base64.b64encode(png).decode()
            for i in range(0, len(b), 3000):
                print(f"IM| {i // 3000:04d} {b[i:i + 3000]}", flush=True)
            sys.exit(0)
print("FP| bulunamadı")
