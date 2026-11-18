"""Erken giriş sistemi testi (geçici): Supertrend dönmeden önce giren adaylar, mevcut sinyallerle aynı çıkış
(stop 1.5 ATR, TP1/TP2/TP3 = 1R/2R/3R, her TP'de 1/3 kapanır, TP1 sonrası stop girişe) ile Supertrend'e karşı."""
import json, sys, time, urllib.request, urllib.parse, urllib.error
sys.path.insert(0, ".")
import indicators as ta
import scanner

TF = sys.argv[1] if len(sys.argv) > 1 else "1h"
PAGES = {"15m": 3, "1h": 1}[TF]
HOLD = {"15m": 96, "1h": 48}[TF]           # en fazla 24s / 48s tut, sonra piyasadan kapat
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
        time.sleep(0.35)
    return out


info = get("/fapi/v1/exchangeInfo", {})
coins = {s["symbol"] for s in info["symbols"] if s.get("underlyingType") == "COIN"}
syms = [s for s in cfg["universe"]["tradingview_watchlist"] if s in coins]
now = int(time.time() * 1000)


def trade(f, i, s):
    """Mevcut sinyallerle aynı çıkış. Döner: R (risk birimi cinsinden sonuç)."""
    c, h, l = f["c"], f["h"], f["l"]
    e, a = c[i], f["atr"][i]
    risk = 1.5 * a
    sl = e - s * risk
    tps = [e + s * risk * k for k in (1, 2, 3)]
    left, got, be = 1.0, 0.0, False
    for k in range(i + 1, min(len(c), i + 1 + HOLD)):
        hi, lo = (h[k], l[k]) if s == 1 else (-l[k], -h[k])
        slv = sl if s == 1 else -sl
        if lo <= slv:                                   # önce stop (temkinli varsayım)
            got += left * ((sl - e) * s / risk)
            return got
        for n, tp in enumerate(tps):
            tpv = tp if s == 1 else -tp
            if left > 1e-9 and hi >= tpv and (n + 1) / 3 > (1 - left) + 1e-9:
                got += (1 / 3) * (n + 1)
                left -= 1 / 3
                if not be:
                    sl, be = e, True
        if left <= 1e-9:
            return got
    k = min(len(c) - 1, i + HOLD)
    return got + left * ((c[k] - e) * s / risk)


def votes_frac(f, i, s):
    v = scanner.indicator_votes(f, i, 0, "4s trend", trigger="supertrend")
    return sum(1 for _, x in v if x == s) / len(v)


def systems(f):
    c = f["c"]
    e9, e21 = ta.ema(c, 9), ta.ema(c, 21)
    st = f["st_dir"]
    _, fast = None, ta.supertrend(f["h"], f["l"], c, 10, 2.0)[0]
    mtf = lambda i, s: (f["h4_ema"][i] + f["h4_st"][i]) * s > 0
    pre = lambda i, s: st[i] == -s                     # Supertrend henüz ters yönde (erken)
    cache = {}

    def vf(i, s):
        if (i, s) not in cache:
            cache[(i, s)] = votes_frac(f, i, s)
        return cache[(i, s)]

    return {
        "ST: Supertrend dönüşü (şimdiki)": lambda i, s: st[i] == s and st[i - 1] == -s,
        "A: İndikatör çoğunluğu %75'i geçti": lambda i, s: pre(i, s) and vf(i, s) >= 0.75 and vf(i - 1, s) < 0.75,
        "A+: A + üst zaman dilimi aynı yönde": lambda i, s: pre(i, s) and mtf(i, s) and vf(i, s) >= 0.75 and vf(i - 1, s) < 0.75,
        "B: TrendFlex dönüşü": lambda i, s: pre(i, s) and f["tflex"][i] == s and f["tflex"][i - 1] == -s,
        "B+: TrendFlex + üst zaman dilimi": lambda i, s: pre(i, s) and mtf(i, s) and f["tflex"][i] == s and f["tflex"][i - 1] == -s,
        "C: EMA9/21 kesişimi + MACD + RSI": lambda i, s: pre(i, s) and (e9[i] - e21[i]) * s > 0 and (e9[i - 1] - e21[i - 1]) * s <= 0
                                            and f["macd_hist"][i] * s > 0 and (f["rsi"][i] - 50) * s > 0,
        "C+: C + üst zaman dilimi": lambda i, s: pre(i, s) and mtf(i, s) and (e9[i] - e21[i]) * s > 0
                                     and (e9[i - 1] - e21[i - 1]) * s <= 0 and f["macd_hist"][i] * s > 0 and (f["rsi"][i] - 50) * s > 0,
        "D: Hızlı Supertrend (10/2) + üst zaman dilimi": lambda i, s: pre(i, s) and mtf(i, s) and fast[i] == s and fast[i - 1] == -s,
    }


agg = {}
for sym in syms:
    try:
        cs = scanner.parse_klines(load(sym), now)
    except Exception as e:  # noqa: BLE001
        print("ERR", sym, e); continue
    if len(cs) < 400:
        continue
    f = scanner.compute_features(cs, cfg)
    if any(f.get(k) is None for k in ("st_dir", "tflex", "macd_hist", "h4_ema")):
        continue
    st = f["st_dir"]
    n = len(f["c"])
    for name, rule in systems(f).items():
        a = agg.setdefault(name, {"n": 0, "win": 0, "R": 0.0, "pos": 0.0, "neg": 0.0, "early": [], "conf": 0, "days": 0})
        a["days"] = max(a["days"], (n - 250) * scanner.tf_ms(cfg) / 86_400_000)
        busy = 0
        for i in range(250, n - 1):
            if i < busy or f["atr"][i] is None:
                continue
            for s in (1, -1):
                try:
                    hit = rule(i, s)
                except (TypeError, IndexError):
                    hit = False
                if not hit:
                    continue
                r = trade(f, i, s)
                a["n"] += 1; a["R"] += r; a["win"] += r > 0
                a["pos"] += max(r, 0); a["neg"] += min(r, 0)
                if not name.startswith("ST"):
                    flip = next((k for k in range(i + 1, min(n, i + 41)) if st[k] == s and st[k - 1] == -s), None)
                    if flip is not None:
                        a["conf"] += 1; a["early"].append(flip - i)
                busy = i + 1
                break
    time.sleep(0.2)

mins = {"15m": 15, "1h": 60}[TF]
print(f"\n===== {TF} · {len(syms)} coin · çıkış: stop 1.5 ATR, TP 1R/2R/3R (1/3'er), TP1 sonrası stop girişe, en fazla {HOLD} mum")
for name, a in agg.items():
    nn = a["n"] or 1
    pf = a["pos"] / -a["neg"] if a["neg"] else float("inf")
    er = sorted(a["early"])
    med = er[len(er) // 2] if er else None
    early_txt = (f" | Supertrend'den önce: medyan {med} mum (~{med * mins} dk), Supertrend onayladı %{a['conf']/nn*100:.0f}"
                 if med is not None else "")
    print(f"{name:48} işlem {a['n']:5} (günde {a['n'] / max(a['days'], 1):5.1f}) | kazanan %{a['win']/nn*100:3.0f} | "
          f"ort. {a['R']/nn:+.3f}R | PF {pf:.2f}{early_txt}")
