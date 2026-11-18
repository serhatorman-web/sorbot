"""Botun RSI uyumsuzluklarını TradingView'ın RSI Divergence göstergesiyle karşılaştırır (geçici).
TradingView sonuçları (BTCUSDT.P 15dk, son 10 olay, olayın göründüğü mumun açılış zamanı) aşağıda."""
import json, sys, time, urllib.request, urllib.parse
from datetime import datetime, timedelta, timezone
sys.path.insert(0, ".")
import indicators as ta

TV_BULL = [1794901500, 1794824100, 1794700800, 1794680100, 1794609900, 1794560400, 1794471300, 1794464100, 1794329100, 1794089700]
TV_BEAR = [1794927600, 1794436200, 1794128400, 1793853900, 1793791800, 1793786400, 1793735100, 1793725200, 1793593800, 1793527200]
out, end = [], None
for _ in range(2):
    p = {"symbol": "BTCUSDT", "interval": "15m", "limit": 1500}
    if end:
        p["endTime"] = end
    raw = json.load(urllib.request.urlopen(urllib.request.Request(
        "https://www.binance.com/fapi/v1/klines?" + urllib.parse.urlencode(p), headers={"User-Agent": "x"}), timeout=30))
    out = raw + out
    end = raw[0][0] - 1
now = int(time.time() * 1000)
out = [k for k in out if int(k[6]) < now]
t = [int(k[0]) // 1000 for k in out]; h = [float(k[2]) for k in out]; l = [float(k[3]) for k in out]; c = [float(k[4]) for k in out]
r = ta.rsi(c, 14)
n = len(c); L = R = 5
lows, highs = [], []
for q in range(L, n - R):
    w = r[q - L:q + R + 1]
    if r[q] is None or any(x is None for x in w):
        continue
    if r[q] == min(w):
        lows.append(q)
    if r[q] == max(w):
        highs.append(q)
bot_bull = [t[b + R] for a, b in zip(lows, lows[1:]) if 5 <= b - a <= 60 and r[b] > r[a] and l[b] < l[a]]
bot_bear = [t[b + R] for a, b in zip(highs, highs[1:]) if 5 <= b - a <= 60 and r[b] < r[a] and h[b] > h[a]]
fmt = lambda x: (datetime.fromtimestamp(x, timezone.utc) + timedelta(hours=3)).strftime("%d.%m %H:%M")
for name, tv, bot in (("POZİTİF", TV_BULL, bot_bull), ("NEGATİF", TV_BEAR, bot_bear)):
    lo = min(tv)
    botw = [x for x in bot if x >= lo]
    print(f"\n{name}: TradingView {len(tv)} olay · bot aynı dönemde {len(botw)} olay")
    for x in sorted(set(tv) | set(botw)):
        print(f"  {fmt(x)}  TV {'✅' if x in tv else '—'}  BOT {'✅' if x in botw else '—'}")
