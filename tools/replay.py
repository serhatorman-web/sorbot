"""NATGAS 4s ve ACT 15dk: neden resim çıkmadı? (geçici)"""
import json, sys, time, urllib.request, urllib.parse
from datetime import datetime, timedelta, timezone
sys.path.insert(0, ".")
import scanner, indicators as ta, patterns as pt
base = json.load(open("config.json", encoding="utf-8"))
BASE = "https://www.binance.com"
get = lambda path, p: json.load(urllib.request.urlopen(urllib.request.Request(BASE + path + "?" + urllib.parse.urlencode(p), headers={"User-Agent": "x"}), timeout=30))
TSI = timezone(timedelta(hours=3))
now = int(time.time() * 1000)
for sym, tf, back in (("NATGASUSDT", "4h", 50), ("ACTUSDT", "15m", 40)):
    cs = scanner.parse_klines(get("/fapi/v1/klines", {"symbol": sym, "interval": tf, "limit": 499}), now)
    v = [x["v"] for x in cs]; vma = ta.sma(v, 20)
    print(f"\n=== {sym} {tf}")
    for end in range(len(cs) - back, len(cs)):
        w = cs[max(0, end - 299):end + 1]
        h = [x["h"] for x in w]; l = [x["l"] for x in w]; c = [x["c"] for x in w]
        n = len(c)
        t = (datetime.fromtimestamp(cs[end]["t"] / 1000, TSI) + timedelta(milliseconds=scanner.tf_ms({"timeframe": tf}))).strftime("%d.%m %H:%M")
        vr = v[end] / vma[end - 1] if vma[end - 1] else 0
        for e in ta.trendlines_close(h, l, c):
            if e["state"] == "broken" and (e["bars_ago"] == 0 or e.get("rc") == n - 1):
                print(f"  {t} TL {e['type']} {'KIRILIM' if e['bars_ago'] == 0 else 'RETEST'} temas {e['touches']} uzunluk {e['b'] - e['a']} mum, hacim {vr:.1f}x")
        for g in pt.chart_patterns(h, l, c, ta.atr(h, l, c, 14)):
            if g["durum"] == "kirildi" and g["ciz"]["kb"] == n - 1:
                print(f"  {t} FM {g['ad']} {'yukarı' if g['kirilim'] == 1 else 'aşağı'} hacim {vr:.1f}x")
