"""Pump/dump radarının 6 türünü botun kendi fonksiyonlarıyla geçmiş veride çalıştırır ve her uyarının
kurallarını bağımsız olarak yeniden doğrular (geçici)."""
import json, sys, time, urllib.request, urllib.parse, urllib.error
from datetime import datetime, timedelta, timezone
sys.path.insert(0, ".")
import scanner

cfg = json.load(open("config.json", encoding="utf-8"))
pdc = cfg["pump_dump"]
rc = cfg["pump_radar"]
mc = rc["momentum"]
BASE = "https://www.binance.com"
TSI = timezone(timedelta(hours=3))


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
typ = {s["symbol"]: s.get("underlyingType") for s in info["symbols"]}
types = set(rc.get("types", ["COIN"]))
syms = [s for s in cfg["universe"]["tradingview_watchlist"] if typ.get(s) in ("COIN", "EQUITY") and
        ("COIN" if typ.get(s) == "COIN" else "EQUITY") in types]
print("taranan sembol", len(syms))
now = int(time.time() * 1000)
KINDS = [("start", "long", "🚀 PUMP SİNYALİ"), ("start", "short", "💥 DUMP SİNYALİ"),
         ("early", "long", "👀 PUMP ERKEN UYARI"), ("early", "short", "👀 DUMP ERKEN UYARI"),
         ("momentum", "long", "⚡ PUMP HAREKETİ"), ("momentum", "short", "⚡ DUMP HAREKETİ")]
st = {(k, d): {"n": 0, "bad": 0, "w4": 0, "w24": 0, "r24": 0.0, "ex": []} for k, d, _ in KINDS}
errors = []
days_oi = days_all = 0
for sym in syms:
    raw = get("/fapi/v1/klines", {"symbol": sym, "interval": "1h", "limit": 1000})
    try:
        oi = {int(x["timestamp"]): float(x["sumOpenInterest"])
              for x in get("/futures/data/openInterestHist", {"symbol": sym, "period": "1h", "limit": 500})}
    except Exception:  # noqa: BLE001
        oi = {}
    time.sleep(0.5)
    cs = scanner.parse_klines(raw, now)
    if len(cs) < 400:
        continue
    try:
        f = scanner.compute_features(cs, cfg)
    except Exception as e:  # noqa: BLE001
        errors.append(f"{sym}: özellik hatası {e}"); continue
    c, h, l, o, v = f["c"], f["h"], f["l"], f["o"], f["v"]
    n = len(c)
    days_all = max(days_all, (n - 300) / 24)
    last = {"long": -10 ** 9, "short": -10 ** 9}
    for i in range(300, n):
        chg24 = (c[i] / c[i - 24] - 1) * 100
        t = cs[i]["t"]
        oc = (oi[t] / oi[t - 4 * 3600000] - 1) if (t in oi and t - 4 * 3600000 in oi) else None
        try:
            pdres = scanner.pump_dump_analysis(f, cfg, chg24, i)
            rds = scanner.pump_radar(f, i, pdres, chg24, cfg, oc, None)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{sym} {i}: radar hatası {e}"); break
        for rd in rds:
            d, k = rd["dir"], rd["kind"]
            if i - last[d] < rc.get("cooldown_hours", 12):
                continue
            last[d] = i
            s = 1 if d == "long" else -1
            # ── kuralları bağımsız yeniden doğrula ──
            bad = []
            if k == "start":
                if not pdres["squeeze"]: bad.append("sıkışma yok")
                if not pdres["vol_spike"]: bad.append("hacim patlaması yok")
                if not (pdres["brk_up"] if s == 1 else pdres["brk_dn"]): bad.append("20 mum kırılımı yok")
                if pdres["chg3"] * s >= pdc["already_pumped_3h"] or chg24 / 100 * s >= pdc["already_pumped_24h"]:
                    bad.append("geç kalınmış")
                if rd["score"] < rc.get("min_score", 70): bad.append("skor düşük")
            elif k == "early":
                if not pdres["squeeze"]: bad.append("sıkışma yok")
                if not (pdres["accumulation"] if s == 1 else pdres["distribution"]): bad.append("birikim/dağıtım yok")
                if pdres["brk_up"] if s == 1 else pdres["brk_dn"]: bad.append("kırılım olmuş (erken değil)")
                if oc is None or oc < 0.05: bad.append("OI artışı yok")
                if rd["score"] < rc.get("min_score_early", 55): bad.append("skor düşük")
            else:
                lb = mc["breakout_lookback"]
                ext = max(h[i - lb:i]) if s == 1 else min(l[i - lb:i])
                vr = v[i] / f["vol_ma"][i - 1]
                rng = (h[i] - l[i]) or 1e-12
                pos = (c[i] - l[i]) / rng if s == 1 else (h[i] - c[i]) / rng
                if vr < mc["volume_x"]: bad.append(f"hacim {vr:.1f}x")
                if (c[i] - ext) * s <= 0: bad.append("2 günlük kırılım yok")
                if (c[i] - o[i]) * s < mc["body_atr"] * f["atr"][i]: bad.append("gövde küçük")
                if pos < mc["close_pos"]: bad.append("kapanış uçta değil")
            x = st[(k, d)]
            x["n"] += 1
            if bad:
                x["bad"] += 1
                errors.append(f"{sym} {k} {d}: {bad}")
            if i + 24 < n:
                x["w4"] += (c[i + 4] - c[i]) * s > 0
                x["w24"] += (c[i + 24] - c[i]) * s > 0
                x["r24"] += (c[i + 24] / c[i] - 1) * s * 100
            x["ex"].append((t, sym, c[i]))
print(f"\nDönem: son ~{days_all:.0f} gün (erken uyarılar için OI verisi ~20 gün)")
for k, d, name in KINDS:
    x = st[(k, d)]
    nn = max(1, sum(1 for t, _, _ in x["ex"] if t < (now - 25 * 3600000)))
    print(f"{name:22} uyarı {x['n']:4} (günde {x['n'] / max(days_all, 1):4.1f}) | kural hatası {x['bad']} | "
          f"4s sonra yönünde %{x['w4']/nn*100:3.0f} · 24s sonra yönünde %{x['w24']/nn*100:3.0f} · 24s ort. %{x['r24']/nn:+.2f}")
    for t, sym, px in x["ex"][-3:]:
        print("     son örnek:", datetime.fromtimestamp(t / 1000 + 3600, TSI).strftime("%d.%m %H:%M"), sym, px)
print("\nHatalar:", errors[:20] or "yok")
