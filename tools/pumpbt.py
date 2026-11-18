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
    DATA[sym] = {"1h": load(sym, "1h", 1), "15m": []}
    try:
        oi = get("/futures/data/openInterestHist", {"symbol": sym, "period": "1h", "limit": 500})
        DATA[sym]["oi"] = {int(x["timestamp"]): float(x["sumOpenInterest"]) for x in oi}
    except Exception:  # noqa: BLE001
        DATA[sym]["oi"] = {}
    time.sleep(0.6)

RULES = [
    ("E: 2 mum üst üste hacim≥2.5x + 20 mum kırılım + 24s %5..%30 + ema50 + OI4s≥%3", "E"),
    ("G: E, OI şartı olmadan", "G"),
    ("F: hacim≥5x + 48 mum (2 gün) kırılım + gövde≥1.5ATR + kapanış mumun üst/alt %25'inde", "F"),
    ("H: E + BTC'den güçlü (24s coin - BTC ≥ %8)", "H"),
]
H_BARS = {"1h": (4, 12, 24)}
COOL = {"1h": 12}
BTC = None


def run(rule):
    global BTC
    name, kind = rule
    tf, per_h = "1h", 1
    if BTC is None:
        bt = load("BTCUSDT", "1h", 1)
        BTC = {int(x[0]): float(x[4]) for x in bt}
    stats = {s_: {"n": 0, "w4": 0, "w12": 0, "w24": 0, "r24": 0.0, "mfe": 0.0, "hit10": 0, "stop5": 0} for s_ in (1, -1)}
    days = 0
    examples = []
    for sym, dd in DATA.items():
        raw = dd[tf]
        if len(raw) < 200:
            continue
        t = [int(x[0]) for x in raw]
        o = [float(x[1]) for x in raw]; h = [float(x[2]) for x in raw]; l = [float(x[3]) for x in raw]
        c = [float(x[4]) for x in raw]; v = [float(x[7]) for x in raw]
        n = len(c)
        a = ta.atr(h, l, c, 14); vma = ta.sma(v, 20); e50 = ta.ema(c, 50)
        oi = dd.get("oi", {})
        last = {1: -10 ** 9, -1: -10 ** 9}
        lo_i = 60
        if kind == "E" and oi:
            lo_i = max(lo_i, next((k for k in range(n) if t[k] in oi), n))
        if kind == "E" and not oi:
            continue
        days = max(days, (n - lo_i) / 24)
        for i in range(lo_i, n - 24):
            if not vma[i - 2] or not a[i]:
                continue
            for s_ in (1, -1):
                if kind in ("E", "G", "H"):
                    if not (v[i] / vma[i - 2] >= 2.5 and v[i - 1] / vma[i - 2] >= 2.5):
                        continue
                    if (c[i] - (max(h[i - 20:i]) if s_ == 1 else min(l[i - 20:i]))) * s_ <= 0:
                        continue
                    ch24 = (c[i] / c[i - 24] - 1) * s_
                    if not 0.05 <= ch24 < 0.30:
                        continue
                    if (c[i] - e50[i]) * s_ <= 0:
                        continue
                    if kind == "E":
                        if t[i] not in oi or t[i] - 4 * 3600000 not in oi:
                            continue
                        if oi[t[i]] / oi[t[i] - 4 * 3600000] - 1 < 0.03:
                            continue
                    if kind == "H":
                        if t[i] not in BTC or t[i - 24] not in BTC:
                            continue
                        rel = ch24 - (BTC[t[i]] / BTC[t[i - 24]] - 1) * s_
                        if rel < 0.08:
                            continue
                else:  # F
                    if v[i] / vma[i - 1] < 5:
                        continue
                    if (c[i] - (max(h[i - 48:i]) if s_ == 1 else min(l[i - 48:i]))) * s_ <= 0:
                        continue
                    if (c[i] - o[i]) * s_ < 1.5 * a[i]:
                        continue
                    rng = h[i] - l[i] or 1e-12
                    if ((c[i] - l[i]) / rng if s_ == 1 else (h[i] - c[i]) / rng) < 0.75:
                        continue
                if i - last[s_] < 12:
                    continue
                last[s_] = i
                st = stats[s_]
                st["n"] += 1
                st["w4"] += (c[i + 4] - c[i]) * s_ > 0
                st["w12"] += (c[i + 12] - c[i]) * s_ > 0
                st["w24"] += (c[i + 24] - c[i]) * s_ > 0
                st["r24"] += (c[i + 24] / c[i] - 1) * s_ * 100
                fut = range(i + 1, i + 25)
                mfe = max(((h[k] if s_ == 1 else l[k]) / c[i] - 1) * s_ for k in fut) * 100
                st["mfe"] += mfe
                res = None
                for k in fut:
                    if ((l[k] if s_ == 1 else h[k]) / c[i] - 1) * s_ <= -0.05:
                        res = "stop"; break
                    if ((h[k] if s_ == 1 else l[k]) / c[i] - 1) * s_ >= 0.10:
                        res = "hit"; break
                st["hit10"] += res == "hit"; st["stop5"] += res == "stop"
                if sym == "PIEVERSEUSDT":
                    examples.append((t[i], s_, c[i], round(mfe, 1)))
    print(f"\n=== {name}  (yaklaşık {days:.0f} gün)")
    for s_, lab in ((1, "PUMP (long)"), (-1, "DUMP (short)")):
        st = stats[s_]; nn = st["n"] or 1
        print(f"  {lab:13} sinyal {st['n']:4} (günde {st['n'] / max(days, 1):.1f}) | yönde: 4s %{st['w4']/nn*100:.0f} "
              f"12s %{st['w12']/nn*100:.0f} 24s %{st['w24']/nn*100:.0f} | 24s ort. %{st['r24']/nn:+.2f} | "
              f"24s içinde en iyi ort. %{st['mfe']/nn:.1f} | %10 hedef önce: %{st['hit10']/nn*100:.0f}, %5 stop önce: %{st['stop5']/nn*100:.0f}")
    from datetime import datetime, timedelta, timezone
    for tt, s_, px, mfe in examples[-6:]:
        print("   PIEVERSE", (datetime.fromtimestamp(tt / 1000, timezone.utc) + timedelta(hours=3)).strftime("%d.%m %H:%M"),
              "PUMP" if s_ == 1 else "DUMP", px, f"sonraki 24s en iyi %{mfe}")


for r in RULES:
    run(r)
