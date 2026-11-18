"""Grafik kanalı için örnek resimler (geçici). Gerçek veri, güncel kod."""
import base64, json, sys, time, urllib.request, urllib.parse
sys.path.insert(0, ".")
import scanner, indicators as ta
SYMS = ["PENDLE", "BTC", "ETH", "SOL", "DOGE", "XRP", "LINK", "NEAR", "FET", "ONDO", "APT", "TIA", "JUP", "UNI", "AAVE"]
now = int(time.time() * 1000)
want = {"confirmed": 2, "touch": 1, "none": 1, "away": 1, "form": 3}
cfg = {"timeframe": "15m", "trendline_images": {"max": 9}, "formations": {"images_max": 9}}
for sym in SYMS:
    tl, cs_by, forms = [], {}, {}
    for tf in ("15m", "1h", "4h", "1d"):
        u = "https://www.binance.com/fapi/v1/klines?" + urllib.parse.urlencode({"symbol": sym + "USDT", "interval": tf, "limit": 300})
        cs = scanner.parse_klines(json.load(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "x"}), timeout=30)), now)
        cs_by[tf] = cs
        forms[tf] = scanner.tf_formations(cs)
        for ev in ta.trendlines_close([x["h"] for x in cs], [x["l"] for x in cs], [x["c"] for x in cs]):
            tl.append(dict(ev, tf=tf, price=cs[-1]["c"]))
    typ = "COIN"
    res = {"meta": {"symbol": sym + "USDT", "type": typ, "precision": None}, "tline": tl, "tl_cs": cs_by, "forms": forms}
    head = scanner.image_head(res, cfg, "long")
    items = [("tl", x) for x in scanner.trendline_images(res, cfg)] + [("form", x) for x in scanner.pattern_images(res, cfg)]
    for kind, (png, cap) in items:
        st = "form" if kind == "form" else next((k for k, w in (("confirmed", "Retest yapıldı"), ("touch", "Retest ediliyor"),
                                                                ("none", "bekle"), ("away", "güçlü kırılım")) if w in cap), "none")
        if want.get(st, 0) > 0:
            want[st] -= 1
            name = f"{st}_{sym}.png"
            print("CAP", name, (f"<b>{head}</b>\n{cap}").replace("\n", " ⏎ "))
            print("B64", name, base64.b64encode(png).decode())
