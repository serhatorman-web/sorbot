"""Anlık resim sayısı tahmini (geçici): son 100 mumun her birinde kaç yeni kırılım olurdu?"""
import json, sys, time, urllib.request, urllib.parse
sys.path.insert(0, ".")
import indicators as ta, patterns as pt, scanner
cfg = json.load(open("config.json", encoding="utf-8"))
BASE = "https://www.binance.com"
get = lambda path, p: json.load(urllib.request.urlopen(urllib.request.Request(BASE + path + "?" + urllib.parse.urlencode(p), headers={"User-Agent": "x"}), timeout=30))
info = get("/fapi/v1/exchangeInfo", {})
ok = {s["symbol"] for s in info["symbols"]}
syms = [s for s in cfg["universe"]["tradingview_watchlist"] if s in ok]
now = int(time.time() * 1000)
for tf in ("15m", "1h", "4h"):
    tl = fm = 0
    for sym in syms:
        cs = scanner.parse_klines(get("/fapi/v1/klines", {"symbol": sym, "interval": tf, "limit": 400}), now)
        time.sleep(0.15)
        h = [x["h"] for x in cs]; l = [x["l"] for x in cs]; c = [x["c"] for x in cs]
        for end in range(len(c) - 100, len(c)):
            hh, ll, cc = h[end - 299:end + 1], l[end - 299:end + 1], c[end - 299:end + 1]
            tl += sum(1 for e in ta.trendlines_close(hh, ll, cc) if e["state"] == "broken" and e["bars_ago"] == 0)
            a = ta.atr(hh, ll, cc, 14)
            fm += sum(1 for g in pt.chart_patterns(hh, ll, cc, a) if g["durum"] == "kirildi" and g["ciz"]["kb"] == len(cc) - 1)
    print(f"{tf}: {len(syms)} sembol, son 100 mum → trend çizgisi kırılımı {tl} ({tl/100:.1f}/mum), formasyon {fm} ({fm/100:.2f}/mum)")
