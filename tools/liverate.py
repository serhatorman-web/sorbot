"""Anlık resim sayısı tahmini, filtrelerle (geçici)."""
import json, sys, time, urllib.request, urllib.parse
sys.path.insert(0, ".")
import indicators as ta, patterns as pt, scanner
cfg = json.load(open("config.json", encoding="utf-8"))
BASE = "https://www.binance.com"
get = lambda path, p: json.load(urllib.request.urlopen(urllib.request.Request(BASE + path + "?" + urllib.parse.urlencode(p), headers={"User-Agent": "x"}), timeout=30))
info = get("/fapi/v1/exchangeInfo", {})
ok = {s["symbol"] for s in info["symbols"]}
syms = [s for s in cfg["universe"]["tradingview_watchlist"] if s in ok]
majors = set(cfg["telegram"]["major_symbols"])
now = int(time.time() * 1000)
PER_DAY = {"15m": 96, "1h": 24, "4h": 6}
for tf in ("15m", "1h", "4h"):
    cnt = {}
    for sym in syms:
        cs = scanner.parse_klines(get("/fapi/v1/klines", {"symbol": sym, "interval": tf, "limit": 400}), now)
        time.sleep(0.12)
        h = [x["h"] for x in cs]; l = [x["l"] for x in cs]; c = [x["c"] for x in cs]; v = [x["v"] for x in cs]
        vma = ta.sma(v, 20)
        for end in range(len(c) - 100, len(c)):
            s0 = end - 299
            hh, ll, cc = h[s0:end + 1], l[s0:end + 1], c[s0:end + 1]
            vr = v[end] / vma[end - 1] if vma[end - 1] else 0
            for e in ta.trendlines_close(hh, ll, cc):
                if e["state"] != "broken" or e["bars_ago"] != 0:
                    continue
                span = e["b"] - e["a"]
                cnt["TL tümü"] = cnt.get("TL tümü", 0) + 1
                if e["touches"] >= 3:
                    cnt["TL 3+ temas"] = cnt.get("TL 3+ temas", 0) + 1
                if e["touches"] >= 3 and vr >= 1.5:
                    cnt["TL 3+ temas + hacim 1.5x"] = cnt.get("TL 3+ temas + hacim 1.5x", 0) + 1
                if e["touches"] >= 3 and vr >= 1.5 and span >= 30:
                    cnt["TL 3+ temas + hacim + uzun çizgi(30+)"] = cnt.get("TL 3+ temas + hacim + uzun çizgi(30+)", 0) + 1
                if sym in majors and e["touches"] >= 3 and vr >= 1.5:
                    cnt["TL (sadece majör) 3+ temas + hacim"] = cnt.get("TL (sadece majör) 3+ temas + hacim", 0) + 1
            a = ta.atr(hh, ll, cc, 14)
            for g in pt.chart_patterns(hh, ll, cc, a):
                if g["durum"] != "kirildi" or g["ciz"]["kb"] != len(cc) - 1:
                    continue
                cnt["FM tümü"] = cnt.get("FM tümü", 0) + 1
                cnt[f"FM · {g['ad']}"] = cnt.get(f"FM · {g['ad']}", 0) + 1
                if vr >= 1.5:
                    cnt["FM hacim 1.5x"] = cnt.get("FM hacim 1.5x", 0) + 1
                if vr >= 1.5 and g["ad"] not in ("Fincan Kulp", "Ters Fincan Kulp"):
                    cnt["FM hacim 1.5x, fincansız"] = cnt.get("FM hacim 1.5x, fincansız", 0) + 1
    print(f"\n{tf} ({len(syms)} sembol, son 100 mum) – günde ortalama olay:")
    for k in sorted(cnt):
        print(f"   {k:45} {cnt[k] / 100 * PER_DAY[tf]:7.1f}/gün")
