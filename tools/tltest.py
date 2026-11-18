"""Gerçek veride trend çizgisi kırılım resimleri (geçici test)."""
import base64, json, sys, time, urllib.request, urllib.parse
sys.path.insert(0, ".")
import scanner, indicators as ta
SYMS = ["BTC", "ETH", "XRP", "BNB", "SOL", "DOGE", "AVAX", "HYPE", "LINK", "SUI", "ADA", "ZEC", "LTC", "BCH", "NEAR", "UNI",
        "AAVE", "ARB", "OP", "INJ", "TIA", "WLD", "APT", "SEI", "ENA", "PENDLE", "TAO", "FET", "ONDO", "JUP"]
now = int(time.time() * 1000)
picked = {"confirmed": 0, "touch": 0, "none": 0, "away": 0}
for sym in SYMS:
    tl, cs_by = [], {}
    for tf in ("15m", "1h", "4h", "1d"):
        u = "https://www.binance.com/fapi/v1/klines?" + urllib.parse.urlencode({"symbol": sym + "USDT", "interval": tf, "limit": 300})
        cs = scanner.parse_klines(json.load(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "x"}), timeout=30)), now)
        cs_by[tf] = cs
        for ev in ta.trendlines_close([x["h"] for x in cs], [x["l"] for x in cs], [x["c"] for x in cs]):
            tl.append(dict(ev, tf=tf, price=cs[-1]["c"]))
    res = {"meta": {"symbol": sym + "USDT", "type": "COIN", "precision": None}, "tline": tl, "tl_cs": cs_by}
    for png, cap in scanner.trendline_images(res, {"trendline_images": {"max": 9}}):
        st = next((k for k, w in (("confirmed", "Retest yapıldı"), ("touch", "Retest ediliyor"), ("none", "bekle"),
                                   ("away", "güçlü kırılım")) if w in cap), "none")
        print("CAP", sym, cap)
        if picked[st] < 2:
            picked[st] += 1
            print("B64", f"{st}_{sym}.png", base64.b64encode(png).decode())
