"""ACT 15dk yükselen kama: hangi mumda tanınıyor? (geçici)"""
import json, sys, time, urllib.request, urllib.parse
from datetime import datetime, timedelta, timezone
sys.path.insert(0, ".")
import scanner, indicators as ta, patterns as pt
BASE = "https://www.binance.com"
get = lambda path, p: json.load(urllib.request.urlopen(urllib.request.Request(BASE + path + "?" + urllib.parse.urlencode(p), headers={"User-Agent": "x"}), timeout=30))
TSI = timezone(timedelta(hours=3))
now = int(time.time() * 1000)
cs = scanner.parse_klines(get("/fapi/v1/klines", {"symbol": "ACTUSDT", "interval": "15m", "limit": 499}), now)
v = [x["v"] for x in cs]; vma = ta.sma(v, 20)
ts = lambda k: (datetime.fromtimestamp(cs[k]["t"] / 1000, TSI) + timedelta(minutes=15)).strftime("%d.%m %H:%M")
for end in range(len(cs) - 30, len(cs)):
    w = cs[end - 299:end + 1]
    h = [x["h"] for x in w]; l = [x["l"] for x in w]; c = [x["c"] for x in w]
    n = len(c); off = end - 299
    gs = pt.chart_patterns(h, l, c, ta.atr(h, l, c, 14))
    txt = "; ".join(f"{g['ad']} {g['durum']} kb={(ts(off + g['ciz']['kb']) if g['ciz'].get('kb') is not None else '-')}" for g in gs) or "-"
    print(f"{ts(end)} kapanış {c[-1]} hacim {v[end] / vma[end - 1]:.1f}x | {txt}")
