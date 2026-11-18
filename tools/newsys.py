"""Yeni sinyal sistemi testi (geçici, Supertrend yok). Her sistem: giriş + stop + TP1/TP2/TP3 (1R/2R/3R, 1/3'er,
TP1 sonrası stop girişe). Aynı coinde açık işlem varken yeni işlem açılmaz. Veri iki yarıya bölünür:
'önceki dönem' ve 'son dönem' – iki dönemde de iyi olan sistem kalıcıdır."""
import json, os, sys, time, urllib.request, urllib.parse, urllib.error
sys.path.insert(0, ".")
import indicators as ta
import scanner

TF = sys.argv[1]
PAGES = {"15m": 6, "1h": 2, "4h": 2}[TF]
HOLD = {"15m": 96, "1h": 72, "4h": 42}[TF]
cfg = json.load(open("config.json", encoding="utf-8"))
if TF in cfg.get("tf_profiles", {}):
    for k, v in cfg["tf_profiles"][TF].items():
        cfg[k] = v if not isinstance(v, dict) else {**cfg.get(k, {}), **v}
cfg["timeframe"] = TF
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


def load(sym):
    out, end = [], None
    for _ in range(PAGES):
        p = {"symbol": sym, "interval": TF, "limit": 1500}
        if end:
            p["endTime"] = end
        raw = get("/fapi/v1/klines", p)
        if not raw:
            break
        out = raw + out
        end = raw[0][0] - 1
        time.sleep(0.3)
    return out


def trade(f, i, s, stop_dist):
    c, h, l = f["c"], f["h"], f["l"]
    e = c[i]
    risk = stop_dist
    sl = e - s * risk
    tps = [e + s * risk * k for k in (1, 2, 3)]
    left, got, be, done_tp = 1.0, 0.0, False, 0
    for k in range(i + 1, min(len(c), i + 1 + HOLD)):
        if (l[k] <= sl) if s == 1 else (h[k] >= sl):
            return got + left * ((sl - e) * s / risk), k
        while done_tp < 3 and ((h[k] >= tps[done_tp]) if s == 1 else (l[k] <= tps[done_tp])):
            done_tp += 1
            got += (1 / 3) * done_tp
            left -= 1 / 3
            if not be:
                sl, be = e, True
        if done_tp == 3:
            return got, k
    k = min(len(c) - 1, i + HOLD)
    return got + left * ((c[k] - e) * s / risk), k


def build(f):
    c, h, l, o, v = f["c"], f["h"], f["l"], f["o"], f["v"]
    a, r = f["atr"], f["rsi"]
    e9, e21 = ta.ema(c, 9), ta.ema(c, 21)
    e20, e50, e200 = f["ema20"], f["ema50"], f["ema200"]
    hist = f["macd_hist"]
    vma = f["vol_ma"]
    htf = f["h4_ema"]                                       # üst zaman diliminin EMA20/50 yönü (+1/-1)

    def clamp(d, i):
        return min(max(d, 0.8 * a[i]), 3.0 * a[i])

    def swing_stop(i, s, n=6):
        ext = min(l[i - n + 1:i + 1]) if s == 1 else max(h[i - n + 1:i + 1])
        return clamp(abs(c[i] - ext) + 0.2 * a[i], i)

    def trend(i, s):
        return (c[i] - e200[i]) * s > 0 and (e50[i] - e200[i]) * s > 0 and htf[i] == s

    S = {}

    # 1) Geri çekilme (trend devamı): trend yönünde, son 5 mumda EMA20'ye geri çekilme, RSI 35-55 bölgesine indi,
    #    şimdi trend yönünde güçlü mum önceki mumun tepesini/dibini geçerek EMA20'nin öbür tarafında kapanıyor.
    def pb(i, s):
        if not trend(i, s):
            return None
        touched = any(((l[k] <= e20[k]) if s == 1 else (h[k] >= e20[k])) for k in range(i - 4, i))
        rsi_ok = any(((35 <= r[k] <= 55) if s == 1 else (45 <= r[k] <= 65)) for k in range(i - 4, i))
        trig = (c[i] - o[i]) * s > 0 and ((c[i] > h[i - 1]) if s == 1 else (c[i] < l[i - 1])) and (c[i] - e20[i]) * s > 0
        return swing_stop(i, s) if touched and rsi_ok and trig and hist[i] * s > hist[i - 1] * s else None
    S["GERİ ÇEKİLME (trend devamı)"] = pb

    # 2) Erken dönüş: EMA9/21 kesişimi + MACD + RSI + üst zaman dilimi (önceki testte en iyi)
    def ev(i, s):
        ok = ((e9[i] - e21[i]) * s > 0 and (e9[i - 1] - e21[i - 1]) * s <= 0 and hist[i] * s > 0
              and (r[i] - 50) * s > 0 and htf[i] == s)
        return swing_stop(i, s, 8) if ok else None
    S["ERKEN DÖNÜŞ (EMA9/21 + MACD + RSI + üst TF)"] = ev

    # 3) Hacimli kırılım: 20 mumluk tepe/dip kapanışla kırıldı, hacim ≥1.5x, RSI aşırı değil, trend aynı yönde
    def bo(i, s):
        ext = max(h[i - 20:i]) if s == 1 else min(l[i - 20:i])
        ok = ((c[i] - ext) * s > 0 and vma[i - 1] and v[i] / vma[i - 1] >= 1.5 and
              ((r[i] < 72) if s == 1 else (r[i] > 28)) and trend(i, s))
        return clamp(abs(c[i] - ((l[i]) if s == 1 else h[i])) + 0.2 * a[i], i) if ok else None
    S["HACİMLİ KIRILIM (trend yönünde)"] = bo

    # 4) Geri çekilme, ATR stoplu (karşılaştırma için)
    S["GERİ ÇEKİLME · stop 1.5 ATR"] = lambda i, s: (1.5 * a[i]) if pb(i, s) else None
    # 5) Erken dönüş, ATR stoplu (önceki testtekiyle aynı)
    S["ERKEN DÖNÜŞ · stop 1.5 ATR"] = lambda i, s: (1.5 * a[i]) if ev(i, s) else None
    # 6) Birleşik: geri çekilme VEYA erken dönüş (ilk gelen)
    S["BİRLEŞİK: geri çekilme + erken dönüş"] = lambda i, s: pb(i, s) or ev(i, s)
    return S


info = get("/fapi/v1/exchangeInfo", {})
coins = {s["symbol"] for s in info["symbols"] if s.get("underlyingType") == "COIN"}
syms = [s for s in cfg["universe"]["tradingview_watchlist"] if s in coins]
now = int(time.time() * 1000)
agg = {}
for sym in syms:
    try:
        cs = scanner.parse_klines(load(sym), now)
    except Exception as e:  # noqa: BLE001
        print("ERR", sym, e); continue
    if len(cs) < 600:
        continue
    f = scanner.compute_features(cs, cfg)
    n = len(cs)
    half = 250 + (n - 250) // 2
    for name, rule in build(f).items():
        for part, (lo, hi) in (("önceki", (250, half)), ("son", (half, n - 1))):
            a = agg.setdefault((name, part), {"n": 0, "win": 0, "R": 0.0, "pos": 0.0, "neg": 0.0, "bars": 0})
            a["bars"] = max(a["bars"], hi - lo)
            busy = 0
            for i in range(lo, hi):
                if i < busy or f["atr"][i] is None or f["ema200"][i] is None:
                    continue
                for s in (1, -1):
                    try:
                        d = rule(i, s)
                    except (TypeError, IndexError, ZeroDivisionError):
                        d = None
                    if not d:
                        continue
                    r, k = trade(f, i, s, d)
                    a["n"] += 1; a["R"] += r; a["win"] += r > 0
                    a["pos"] += max(r, 0); a["neg"] += min(r, 0)
                    busy = k + 1
                    break
    time.sleep(0.1)

days = lambda b: b * scanner.tf_ms(cfg) / 86_400_000
print(f"\n===== {TF} · {len(syms)} coin · stop + TP1/TP2/TP3 (1R/2R/3R), TP1 sonrası stop girişe, en fazla {HOLD} mum")
names = []
for (nm, _p) in agg:
    if nm not in names:
        names.append(nm)
for nm in names:
    for part in ("önceki", "son"):
        a = agg[(nm, part)]
        nn = a["n"] or 1
        pf = a["pos"] / -a["neg"] if a["neg"] else float("inf")
        print(f"{nm:44} {part:7} ({days(a['bars']):3.0f} gün) işlem {a['n']:5} (günde {a['n'] / max(days(a['bars']), 1):5.1f}) | "
              f"kazanan %{a['win']/nn*100:3.0f} | ort. {a['R']/nn:+.3f}R | PF {pf:.2f}")
