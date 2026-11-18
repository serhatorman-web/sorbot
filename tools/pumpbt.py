"""Pump/dump yakalama testi (geçici): izleme listesindeki coinlerde son ~60 günlük 1s ve 15dk verisiyle
farklı 'trend içinde hızlanma' kurallarının kaç sinyal ürettiğini ve sonrasında ne olduğunu ölçer."""
import json, sys, urllib.request, urllib.parse, urllib.error
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, ".")
import indicators as ta

cfg = json.load(open("config.json", encoding="utf-8"))
import time
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
print("coin sayısı", len(syms))


def load(sym, tf, pages):
    out, end = [], None
    for _ in range(pages):
        p = {"symbol": sym, "interval": tf, "limit": 1500}
        if end:
            p["endTime"] = end
        raw = get("/fapi/v1/klines", p)
        if not raw:
            break
        out = raw + out
        end = raw[0][0] - 1
        time.sleep(0.25)
    return out[:-1]


DATA = {}
for sym in syms:
    DATA[sym] = {"1h": load(sym, "1h", 1), "15m": load(sym, "15m", 4)}
    time.sleep(1.2)

# kurallar: (ad, tf, hacim_x, kırılım_mum, gövde_atr, son_3s_max, son_24s_max, ema50 şartı)
RULES = [
    ("1s-A hacim3 kırılım", "1h", 3.0, 20, 0.0, 0.20, 0.40, False),
    ("1s-B hacim3 kırılım gövde1ATR ema50", "1h", 3.0, 20, 1.0, 0.20, 0.40, True),
    ("1s-C hacim4 kırılım gövde1ATR ema50", "1h", 4.0, 20, 1.0, 0.20, 0.40, True),
    ("1s-D hacim3 kırılım gövde1ATR ema50 (3s<%15,24s<%30)", "1h", 3.0, 20, 1.0, 0.15, 0.30, True),
    ("15dk-A hacim4 kırılım gövde1ATR ema50", "15m", 4.0, 20, 1.0, 0.12, 0.40, True),
    ("15dk-B hacim5 kırılım gövde1.5ATR ema50", "15m", 5.0, 20, 1.5, 0.12, 0.40, True),
]
H_BARS = {"1h": (4, 12, 24), "15m": (16, 48, 96)}     # 4s / 12s / 24s sonrası
COOL = {"1h": 12, "15m": 48}                           # 12 saat aynı yönde tekrar yok


def run(rule):
    name, tf, vx, lb, body_atr, max3, max24, ema_ok = rule
    per_h = 4 if tf == "15m" else 1
    stats = {s: {"n": 0, "w4": 0, "w12": 0, "w24": 0, "r24": 0.0, "mfe": 0.0, "hit10": 0, "stop5": 0} for s in (1, -1)}
    days = 0
    examples = []
    for sym, dd in DATA.items():
        raw = dd[tf]
        if len(raw) < 200:
            continue
        o = [float(x[1]) for x in raw]; h = [float(x[2]) for x in raw]; l = [float(x[3]) for x in raw]
        c = [float(x[4]) for x in raw]; v = [float(x[7]) for x in raw]
        n = len(c)
        days = max(days, n / (24 * per_h))
        a = ta.atr(h, l, c, 14); vma = ta.sma(v, 20); e50 = ta.ema(c, 50)
        last = {1: -10 ** 9, -1: -10 ** 9}
        for i in range(60, n - H_BARS[tf][2]):
            if not vma[i - 1] or not a[i]:
                continue
            vr = v[i] / vma[i - 1]
            if vr < vx:
                continue
            for s in (1, -1):
                ext = max(h[i - lb:i]) if s == 1 else min(l[i - lb:i])
                if (c[i] - ext) * s <= 0:
                    continue
                if (c[i] - o[i]) * s < body_atr * a[i]:
                    continue
                if ema_ok and (c[i] - e50[i]) * s <= 0:
                    continue
                ch3 = (c[i] / c[i - 3 * per_h] - 1) * s
                ch24 = (c[i] / c[i - 24 * per_h] - 1) * s
                if ch3 >= max3 or ch24 >= max24:
                    continue
                if i - last[s] < COOL[tf] * per_h:
                    continue
                last[s] = i
                st = stats[s]
                b4, b12, b24 = H_BARS[tf]
                st["n"] += 1
                st["w4"] += (c[i + b4] - c[i]) * s > 0
                st["w12"] += (c[i + b12] - c[i]) * s > 0
                st["w24"] += (c[i + b24] - c[i]) * s > 0
                st["r24"] += (c[i + b24] / c[i] - 1) * s * 100
                fut = range(i + 1, i + b24 + 1)
                mfe = max(((h[k] if s == 1 else l[k]) / c[i] - 1) * s for k in fut) * 100
                st["mfe"] += mfe
                # +%10'a, %5 zarardan önce ulaştı mı
                res = None
                for k in fut:
                    up = ((h[k] if s == 1 else l[k]) / c[i] - 1) * s
                    dn = ((l[k] if s == 1 else h[k]) / c[i] - 1) * s
                    if dn <= -0.05:
                        res = "stop"; break
                    if up >= 0.10:
                        res = "hit"; break
                st["hit10"] += res == "hit"; st["stop5"] += res == "stop"
                if sym == "PIEVERSEUSDT":
                    examples.append((int(raw[i][0]), s, c[i], round(mfe, 1)))
    print(f"\n=== {name}  (yaklaşık {days:.0f} gün, {len(DATA)} coin)")
    for s, lab in ((1, "PUMP (long)"), (-1, "DUMP (short)")):
        st = stats[s]; nn = st["n"] or 1
        print(f"  {lab:13} sinyal {st['n']:4} (günde {st['n'] / max(days, 1):.1f}) | yönde: 4s %{st['w4']/nn*100:.0f} "
              f"12s %{st['w12']/nn*100:.0f} 24s %{st['w24']/nn*100:.0f} | 24s ort. %{st['r24']/nn:+.2f} | "
              f"24s içinde en iyi ort. %{st['mfe']/nn:.1f} | %10 hedef önce: %{st['hit10']/nn*100:.0f}, %5 stop önce: %{st['stop5']/nn*100:.0f}")
    from datetime import datetime, timedelta, timezone
    for t, s, px, mfe in examples[-6:]:
        print("   PIEVERSE", (datetime.fromtimestamp(t / 1000, timezone.utc) + timedelta(hours=3)).strftime("%d.%m %H:%M"),
              "PUMP" if s == 1 else "DUMP", px, f"sonraki 24s en iyi %{mfe}")


for r in RULES:
    run(r)
