"""Trend çizgisi: eski (penceredeki en uç kapanış) ve yeni (en dıştaki çizgi) karşılaştırması (geçici)."""
import json, sys, time, urllib.request, urllib.parse
from datetime import datetime, timedelta, timezone
sys.path.insert(0, "."); sys.path.insert(0, "tools")
import scanner, indicators as new, ind_old as old
BASE = "https://www.binance.com"
get = lambda path, p: json.load(urllib.request.urlopen(urllib.request.Request(BASE + path + "?" + urllib.parse.urlencode(p), headers={"User-Agent": "x"}), timeout=30))
TSI = timezone(timedelta(hours=3))
now = int(time.time() * 1000)
for sym, tf in (("CRCLUSDT", "15m"), ("FFUSDT", "15m"), ("BTCUSDT", "15m"), ("BTCUSDT", "1h"), ("ETHUSDT", "1h"),
                ("PENDLEUSDT", "4h"), ("NATGASUSDT", "4h"), ("SOLUSDT", "1h")):
    cs = scanner.parse_klines(get("/fapi/v1/klines", {"symbol": sym, "interval": tf, "limit": 300}), now)
    h = [x["h"] for x in cs]; l = [x["l"] for x in cs]; c = [x["c"] for x in cs]
    ts = lambda k: (datetime.fromtimestamp(cs[k]["t"] / 1000, TSI)).strftime("%d.%m %H:%M")
    print(f"\n=== {sym} {tf} · son kapanış {c[-1]}")
    for lab, mod in (("ESKİ", old), ("YENİ", new)):
        for e in mod.trendlines_close(h, l, c):
            print(f"  {lab} {e['type']:7} 1.temas {ts(e['a'])} {c[e['a']]} · 2.temas {ts(e['b'])} {c[e['b']]} · "
                  f"şimdi çizgi {e['level']:.6g} · {e['state']}{(' ' + str(e['bars_ago']) + ' mum önce') if e['state'] == 'broken' else ''}")
