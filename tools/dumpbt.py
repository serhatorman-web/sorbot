"""Dump yakalama testi (geçici): izleme listesindeki coinlerde son ~60 günlük 1s verisiyle dump kuralları."""
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


info = get("/fapi/v1/exchangeInfo", {})
coins = {s["symbol"] for s in info["symbols"] if s.get("underlyingType") == "COIN"}
syms = [s for s in cfg["universe"]["tradingview_watchlist"] if s in coins]
DATA = {}
for sym in syms:
    raw = get("/fapi/v1/klines", {"symbol": sym, "interval": "1h", "limit": 1500})
    DATA[sym] = raw[:-1]
    time.sleep(0.5)
print("coin", len(DATA))


def evaluate(name, picker):
    """picker(ctx, i) -> True ise i. mumda short uyarısı. 12 saat aynı coinde tekrar yok."""
    n_all = w4 = w12 = w24 = hit = stop = 0
    r24 = mfe_s = 0.0
    days = 0
    for sym, raw in DATA.items():
        if len(raw) < 300:
            continue
        o = [float(x[1]) for x in raw]; h = [float(x[2]) for x in raw]; l = [float(x[3]) for x in raw]
        c = [float(x[4]) for x in raw]; v = [float(x[7]) for x in raw]
        n = len(c)
        days = max(days, (n - 250) / 24)
        ctx = {"o": o, "h": h, "l": l, "c": c, "v": v, "atr": ta.atr(h, l, c, 14), "vma": ta.sma(v, 20),
               "e50": ta.ema(c, 50), "e200": ta.ema(c, 200), "rsi": ta.rsi(c, 14)}
        last = -10 ** 9
        for i in range(250, n - 24):
            if i - last < 12 or not picker(ctx, i):
                continue
            last = i
            n_all += 1
            w4 += c[i + 4] < c[i]; w12 += c[i + 12] < c[i]; w24 += c[i + 24] < c[i]
            r24 += (1 - c[i + 24] / c[i]) * 100
            mfe_s += max(1 - l[k] / c[i] for k in range(i + 1, i + 25)) * 100
            res = None
            for k in range(i + 1, i + 25):
                if h[k] / c[i] - 1 >= 0.05:
                    res = "stop"; break
                if 1 - l[k] / c[i] >= 0.10:
                    res = "hit"; break
            hit += res == "hit"; stop += res == "stop"
    nn = n_all or 1
    print(f"\n=== {name}")
    print(f"  sinyal {n_all} (günde {n_all / max(days, 1):.1f}) | düşüş yönünde: 4s %{w4/nn*100:.0f} 12s %{w12/nn*100:.0f} "
          f"24s %{w24/nn*100:.0f} | 24s ort. short sonucu %{r24/nn:+.2f} | 24s içinde en iyi ort. %{mfe_s/nn:.1f} | "
          f"%10 hedef önce %{hit/nn*100:.0f}, %5 stop önce %{stop/nn*100:.0f}")


def base(ctx, i):                                   # karşılaştırma: her 12 saatte bir rastgele short
    return True


def panic(ctx, i):                                  # önceki test (kapalı olan): panik mumu
    o, h, l, c, v, a, vm = ctx["o"], ctx["h"], ctx["l"], ctx["c"], ctx["v"], ctx["atr"], ctx["vma"]
    if not vm[i - 1] or not a[i]:
        return False
    rng = (h[i] - l[i]) or 1e-12
    return (v[i] / vm[i - 1] >= 5 and c[i] < min(l[i - 48:i]) and (o[i] - c[i]) >= 1.5 * a[i]
            and (h[i] - c[i]) / rng >= 0.75)


def second_leg(ctx, i, max_bounce=0.5):
    """Tepki sonrası ikinci düşüş: son 3-24 mum içinde bir panik/sert düşüş mumu (hacim≥3x, 48 mum dibi),
    ardından zayıf tepki (düşüşün en fazla %50'si geri alınmış), şimdi kapanış o dibin altında."""
    o, h, l, c, v, a, vm = ctx["o"], ctx["h"], ctx["l"], ctx["c"], ctx["v"], ctx["atr"], ctx["vma"]
    if c[i - 1] < min(l[i - 30:i - 1]):            # bir önceki mum zaten yeni dipteyse ikinci ayak değil
        return False
    for k in range(i - 24, i - 2):
        if not vm[k - 1] or not a[k]:
            continue
        if not (v[k] / vm[k - 1] >= 3 and l[k] <= min(l[k - 48:k]) and (o[k] - c[k]) >= a[k]):
            continue
        low_k = min(l[k:i])
        top = max(h[k - 24:k + 1])
        drop = top - low_k
        bounce = max(h[k + 1:i]) - low_k
        if drop <= 0 or bounce < 0.01 * low_k or bounce > max_bounce * drop:
            continue
        if c[i] < low_k and (o[i] - c[i]) >= 0.5 * a[i]:
            return True
    return False


def pressure(ctx, i, vx=3.0, rsi_min=30, need_rsi=True):
    """Düzenli satış baskısı: hacim≥vx, 20 mum dibi kırıldı, gövde≥1 ATR kırmızı, kapanış dibe yakın,
    fiyat EMA50 ve EMA200 altında (EMA50<EMA200), 24s düşüş %15'ten az (panik değil), RSI aşırı satımda değil."""
    o, h, l, c, v, a, vm = ctx["o"], ctx["h"], ctx["l"], ctx["c"], ctx["v"], ctx["atr"], ctx["vma"]
    e50, e200, r = ctx["e50"], ctx["e200"], ctx["rsi"]
    if not vm[i - 1] or not a[i] or e200[i] is None:
        return False
    rng = (h[i] - l[i]) or 1e-12
    if not (v[i] / vm[i - 1] >= vx and c[i] < min(l[i - 20:i]) and (o[i] - c[i]) >= a[i] and (h[i] - c[i]) / rng >= 0.75):
        return False
    if not (c[i] < e50[i] < e200[i]):
        return False
    if c[i] / c[i - 24] - 1 <= -0.15:
        return False
    return (not need_rsi) or (r[i] is not None and r[i] >= rsi_min)


evaluate("KARŞILAŞTIRMA: her 12 saatte bir rastgele short", base)
evaluate("Önceki test: panik mumu (hacim 5x, 2 günlük dip) – kapalı olan", panic)
evaluate("D1: tepki sonrası ikinci düşüş (tepki ≤ %50)", second_leg)
evaluate("D1b: tepki sonrası ikinci düşüş (tepki ≤ %38)", lambda x, i: second_leg(x, i, 0.38))
evaluate("D2: düzenli satış baskısı (hacim 3x, trend aşağı, RSI≥30)", pressure)
evaluate("D2b: düzenli satış baskısı (hacim 2x)", lambda x, i: pressure(x, i, vx=2.0))
evaluate("D2c: düzenli satış baskısı (hacim 3x, RSI şartı yok)", lambda x, i: pressure(x, i, need_rsi=False))
