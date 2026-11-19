"""Formasyon resimleri (canlı kodla): XRP ikili tepe + farklı formasyon türlerinden örnekler, giriş kırılımda."""
import base64, sys, time
sys.path.insert(0, ".")
import scanner as S
import chart_img
import patterns as pt
import indicators as ta

api = S.Binance()
now = int(time.time() * 1000)
want = ["XRPUSDT", "BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "ADAUSDT", "LINKUSDT", "SUIUSDT", "AVAXUSDT", "BNBUSDT",
        "LTCUSDT", "NEARUSDT", "AAVEUSDT", "UNIUSDT", "DOTUSDT", "TRXUSDT", "FILUSDT", "APTUSDT", "ARBUSDT", "OPUSDT",
        "INJUSDT", "TIAUSDT", "SEIUSDT", "WLDUSDT", "ENAUSDT", "PEPEUSDT", "WIFUSDT", "ONDOUSDT", "TAOUSDT", "HYPEUSDT"]
got = {}
for sym in want:
    cs_all = S.parse_klines(api.get("/fapi/v1/klines", {"symbol": sym, "interval": "15m", "limit": 900}), now)
    for cut in range(len(cs_all) - 1, 320, -1):
        cs = cs_all[:cut + 1][-300:]
        h = [x["h"] for x in cs]; l = [x["l"] for x in cs]; c = [x["c"] for x in cs]
        a = ta.atr(h, l, c, 14)
        for g in pt.chart_patterns(h, l, c, a):
            if g["durum"] != "kirildi" or (g.get("ciz") or {}).get("kb") != len(c) - 1 or g["ad"] in got:
                continue
            if g["ad"] in ("Fincan Kulp", "Ters Fincan Kulp"):
                continue
            if sym != "XRPUSDT" and len(got) >= 6:
                continue
            d = g["kirilim"]
            g = dict(g, plan=S.trade_plan(h, l, c, a, d, level=g.get("_simdi") or S.lvl_now(g, d)))
            png = chart_img.render_pattern(cs, g, f"{sym[:-4]} · 15dk · {g['ad']} ({'yukarı' if d == 1 else 'aşağı'} kırıldı)", None)
            got[g["ad"]] = sym
            tag = f"{sym}_{len(got)}"
            print("FP|", tag, g["ad"], {k: round(v, 6) if isinstance(v, float) else v for k, v in g["plan"].items() if k != "tp"},
                  S.datetime.fromtimestamp(cs[-1]["t"] / 1000, S.TR_TZ))
            b = base64.b64encode(png).decode()
            for i in range(0, len(b), 3000):
                print(f"IM| {tag} {i // 3000:04d} {b[i:i + 3000]}", flush=True)
        if sym == "XRPUSDT" and "İkili Tepe" in got:
            break
    if len(got) >= 7:
        break
