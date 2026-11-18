"""Botun kendi reversal_radar fonksiyonuyla geçmiş kontrol (geçici): sinyal sayısı ve 24s sonrası."""
import json, sys, time, urllib.request, urllib.parse, urllib.error
from datetime import datetime, timedelta, timezone
sys.path.insert(0, ".")
import scanner

cfg = json.load(open("config.json", encoding="utf-8"))
BASE = "https://www.binance.com"


def get(path, p):
    for k in range(8):
        try:
            return json.load(urllib.request.urlopen(urllib.request.Request(
                BASE + path + "?" + urllib.parse.urlencode(p), headers={"User-Agent": "x"}), timeout=30))
        except urllib.error.HTTPError as e:
            if e.code in (418, 429):
                time.sleep(20 * (k + 1)); continue
            raise


info = get("/fapi/v1/exchangeInfo", {})
coins = {s["symbol"] for s in info["symbols"] if s.get("underlyingType") == "COIN"}
syms = [s for s in cfg["universe"]["tradingview_watchlist"] if s in coins]
now = int(time.time() * 1000)
n = w24 = hit = stop = 0
r24 = 0.0
recent = []
for sym in syms:
    raw = get("/fapi/v1/klines", {"symbol": sym, "interval": "1h", "limit": 1500})
    time.sleep(0.4)
    cs = scanner.parse_klines(raw, now)
    if len(cs) < 300:
        continue
    f = scanner.compute_features(cs, cfg)
    c, h, l = f["c"], f["h"], f["l"]
    last = -10 ** 9
    for i in range(250, len(c)):
        if i - last < 12 or not scanner.reversal_radar(f, i, cfg):
            continue
        last = i
        t = (datetime.fromtimestamp(cs[i]["t"] / 1000 + 3600, timezone.utc) + timedelta(hours=3)).strftime("%d.%m %H:%M")
        if i + 24 >= len(c):
            recent.append(f"{t} {sym} {c[i]}")
            continue
        n += 1
        w24 += c[i + 24] < c[i]
        r24 += (1 - c[i + 24] / c[i]) * 100
        res = None
        for k in range(i + 1, i + 25):
            if h[k] / c[i] - 1 >= 0.05:
                res = "stop"; break
            if 1 - l[k] / c[i] >= 0.10:
                res = "hit"; break
        hit += res == "hit"; stop += res == "stop"
nn = n or 1
print(f"SONUÇ sinyal {n} (~60 gün) | 24s sonra düşmüş %{w24/nn*100:.0f} | ort. short sonucu %{r24/nn:+.2f} | "
      f"%10 önce %{hit/nn*100:.0f} · %5 stop önce %{stop/nn*100:.0f}")
print("Son 24 saatteki uyarılar:", recent or "yok")
