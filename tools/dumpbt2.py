"""Dump yakalama testi 2 (geçici): farklı dump kuralları, BTC yükselirken / düşerken ayrı ayrı, rastgele short ile kıyas."""
import json, sys, time, urllib.request, urllib.parse, urllib.error
sys.path.insert(0, ".")
import indicators as ta

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


def load(sym, pages=2):
    out, end = [], None
    for _ in range(pages):
        p = {"symbol": sym, "interval": "1h", "limit": 1500}
        if end:
            p["endTime"] = end
        raw = get("/fapi/v1/klines", p)
        if not raw:
            break
        out = raw + out
        end = raw[0][0] - 1
        time.sleep(0.3)
    return out[:-1]


info = get("/fapi/v1/exchangeInfo", {})
coins = {s["symbol"] for s in info["symbols"] if s.get("underlyingType") == "COIN"}
syms = [s for s in cfg["universe"]["tradingview_watchlist"] if s in coins]
btc = load("BTCUSDT")
BTC = {int(x[0]): float(x[4]) for x in btc}
DATA = {}
for sym in syms:
    DATA[sym] = load(sym)
print("coin", len(DATA), "BTC mum", len(btc))


def prep(raw):
    t = [int(x[0]) for x in raw]
    o = [float(x[1]) for x in raw]; h = [float(x[2]) for x in raw]; l = [float(x[3]) for x in raw]
    c = [float(x[4]) for x in raw]; v = [float(x[7]) for x in raw]
    return {"t": t, "o": o, "h": h, "l": l, "c": c, "v": v, "atr": ta.atr(h, l, c, 14), "vma": ta.sma(v, 20),
            "e20": ta.ema(c, 20), "e50": ta.ema(c, 50), "e200": ta.ema(c, 200), "rsi": ta.rsi(c, 14)}


CTX = {s: prep(r) for s, r in DATA.items() if len(r) >= 400}


def btc24(t):
    a, b = BTC.get(t), BTC.get(t - 24 * 3600000)
    return (a / b - 1) if a and b else 0.0


def evaluate(name, picker, cool=12):
    agg = {k: {"n": 0, "w4": 0, "w24": 0, "r24": 0.0, "hit": 0, "stop": 0} for k in ("tümü", "BTC↑", "BTC↓")}
    days = 0
    for sym, x in CTX.items():
        c, h, l, t = x["c"], x["h"], x["l"], x["t"]
        n = len(c)
        days = max(days, (n - 250) / 24)
        last = -10 ** 9
        for i in range(250, n - 24):
            if i - last < cool or not picker(x, i):
                continue
            last = i
            reg = "BTC↑" if btc24(t[i]) > 0 else "BTC↓"
            res = None
            for k in range(i + 1, i + 25):
                if h[k] / c[i] - 1 >= 0.05:
                    res = "stop"; break
                if 1 - l[k] / c[i] >= 0.10:
                    res = "hit"; break
            for key in ("tümü", reg):
                s = agg[key]
                s["n"] += 1; s["w4"] += c[i + 4] < c[i]; s["w24"] += c[i + 24] < c[i]
                s["r24"] += (1 - c[i + 24] / c[i]) * 100
                s["hit"] += res == "hit"; s["stop"] += res == "stop"
    print(f"\n=== {name}")
    for key, s in agg.items():
        nn = s["n"] or 1
        print(f"  {key:5} sinyal {s['n']:5} (günde {s['n'] / max(days, 1):5.1f}) | 4s sonra düşmüş %{s['w4']/nn*100:3.0f} | "
              f"24s sonra düşmüş %{s['w24']/nn*100:3.0f} | 24s ort. short sonucu %{s['r24']/nn:+.2f} | "
              f"%10 önce %{s['hit']/nn*100:3.0f} · %5 stop önce %{s['stop']/nn*100:3.0f}")


def ok(x, i):
    return x["vma"][i - 1] and x["atr"][i] and x["e200"][i] is not None and x["rsi"][i] is not None


def red(x, i, k=0.5):
    return x["o"][i] - x["c"][i] >= k * x["atr"][i]


def base(x, i):
    return True


def p1_post_pump(x, i):
    """Pump sonrası dönüş: son 48 saatte %25+ yükselmiş, zirveden en az %8 düşmüş; 12+ mum EMA20 üstünde
    kaldıktan sonra ilk kez hacimli kırmızı mumla EMA20 altında kapanış."""
    if not ok(x, i):
        return False
    c, e20, h = x["c"], x["e20"], x["h"]
    peak = max(h[i - 48:i])
    if peak / min(x["l"][i - 72:i - 24]) < 1.25 or c[i] > peak * 0.92:
        return False
    if not (c[i] < e20[i] and all(c[k] > e20[k] for k in range(i - 12, i - 1))):
        return False
    return red(x, i, 0.8) and x["v"][i] / x["vma"][i - 1] >= 1.5


def p2_trend_pullback(x, i):
    """Trend içi tepki short: düşüş trendi (fiyat < EMA200, EMA50 < EMA200), fiyat EMA50'ye kadar yükselmiş ve
    kırmızı mumla altında kapatmış (ret), RSI 40-60."""
    if not ok(x, i):
        return False
    c, h, e50, e200, r = x["c"], x["h"], x["e50"], x["e200"], x["rsi"]
    if not (c[i] < e200[i] and e50[i] < e200[i]):
        return False
    if not (max(h[i - 1], h[i]) >= e50[i] and c[i] < e50[i]):
        return False
    return red(x, i, 0.5) and 40 <= r[i] <= 60


def p3_support_break(x, i):
    """5 günlük destek kırılımı: kapanış son 120 mumun en düşüğünün altında, hacim ≥2x, RSI ≥30, 24s düşüş < %12."""
    if not ok(x, i):
        return False
    c = x["c"]
    if not (c[i] < min(x["l"][i - 120:i]) and x["v"][i] / x["vma"][i - 1] >= 2 and x["rsi"][i] >= 30):
        return False
    return c[i] / c[i - 24] - 1 > -0.12 and red(x, i, 0.5)


def p4_weak_vs_btc(x, i):
    """BTC'den zayıf kırılım: 20 mum dibi kırıldı, coin 24s'de BTC'den %5+ kötü, BTC 24s %-1'den iyi, RSI ≥30."""
    if not ok(x, i):
        return False
    c, t = x["c"], x["t"]
    if not (c[i] < min(x["l"][i - 20:i]) and x["rsi"][i] >= 30 and red(x, i, 0.5)):
        return False
    b = btc24(t[i])
    return b > -0.01 and (c[i] / c[i - 24] - 1) - b <= -0.05


def p5_lower_high(x, i):
    """Alçalan tepe teyidi: düşüş trendinde (EMA50<EMA200) son tepe öncekinden düşük, fiyat iki tepe arasındaki
    dibin altına kapanışla indi (yapı kırılımı), hacim ≥1.5x, RSI ≥35."""
    if not ok(x, i):
        return False
    c, h, l = x["c"], x["h"], x["l"]
    if not (x["e50"][i] < x["e200"][i] and x["rsi"][i] >= 35 and x["v"][i] / x["vma"][i - 1] >= 1.5):
        return False
    piv = [k for k in range(i - 40, i - 2) if h[k] == max(h[k - 3:k + 4])]
    if len(piv) < 2:
        return False
    a, b = piv[-2], piv[-1]
    if not h[b] < h[a]:
        return False
    swing_low = min(l[a:b + 1])
    return c[i] < swing_low <= c[i - 1] and red(x, i, 0.5)


evaluate("KARŞILAŞTIRMA: rastgele short (her 12 saatte bir)", base)
evaluate("P1: pump sonrası dönüş", p1_post_pump)
evaluate("P2: trend içi tepki short (EMA50 reddi)", p2_trend_pullback)
evaluate("P3: 5 günlük destek kırılımı", p3_support_break)
evaluate("P4: BTC'den zayıf kırılım", p4_weak_vs_btc)
evaluate("P5: alçalan tepe + yapı kırılımı", p5_lower_high)
