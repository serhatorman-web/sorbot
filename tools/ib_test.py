"""Mum içi kırılım vs mum kapanışı teyidi – trend çizgisi kırılımları.
Her mumda, bir önceki mumda aktif olan çizgi (canlıdaki trendlines_close, 300 mumluk pencere, en az 2 temas,
min_span_by_tf) bu mumda fiyatla delinirse (çizgi ± 0.1 ATR) mum içi kırılım sayılır. Mum içi an alt zaman
diliminden bulunur (15dk→1dk, 1s→5dk, 4s→15dk); giriş o alt mumun kapanışı (canlıdaki kontrol gecikmesi gibi).
Planlar Supertrend gibi: stop 1.5 ATR, TP 1R/2R/3R (1/3'er), stop sabit; aynı mumda stop+TP → önce stop.
I1: mum içi gir, kapanışa bakma.  I2: mum içi gir, mum çizginin içinde kapanırsa (❌) kapanışta çık.
C1: kapanış teyidinden sonra kapanışta gir (hacim şartı yok).  C2: C1 + kırılım mumunda hacim ≥1.5x.
Ücret %0.10 (giriş+çıkış) net sonuçtan düşülür."""
import json, os, sys, time
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as S
import indicators as ta

SYMS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT", "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT",
        "DOTUSDT", "LTCUSDT", "NEARUSDT", "SUIUSDT", "APTUSDT", "ARBUSDT", "OPUSDT", "INJUSDT", "TIAUSDT", "SEIUSDT",
        "WIFUSDT", "1000PEPEUSDT", "ENAUSDT", "HYPEUSDT", "ZECUSDT", "AAVEUSDT", "UNIUSDT", "FETUSDT", "TAOUSDT",
        "ONDOUSDT", "TRUMPUSDT", "FILUSDT", "XLMUSDT", "HBARUSDT", "XAUUSDT", "XAGUSDT", "NVDAUSDT", "TSLAUSDT",
        "MSTRUSDT", "COINUSDT", "DASHUSDT"]
CONF = {"15m": ("1m", 30, 900_000, 60_000), "1h": ("5m", 90, 3_600_000, 300_000),
        "4h": ("15m", 300, 14_400_000, 900_000)}
SPAN = {"15m": 30, "1h": 20, "4h": 10}
FEE = 0.10
api = S.Binance(max_weight=1500)
now_ms = int(time.time() * 1000)


def kl(sym, tf, start):
    out, st = [], start
    while True:
        raw = api.get("/fapi/v1/klines", {"symbol": sym, "interval": tf, "startTime": st, "limit": 1500})
        if not raw:
            break
        out += S.parse_klines(raw, now_ms)
        st = int(raw[-1][0]) + 1
        if len(raw) < 1500:
            break
    seen, res = set(), []
    for x in out:
        if x["t"] not in seen:
            seen.add(x["t"]); res.append(x)
    return res


def run_plan(path, d, entry, stop, tps):
    """path: [(h, l, c)] entry sonrası; döner R (1/3'er TP, sabit stop)"""
    R, hit, risk = 0.0, 0, abs(entry - stop)
    for hi, lo, _ in path:
        if (lo <= stop) if d == 1 else (hi >= stop):
            return R - (3 - hit) / 3, hit
        while hit < 3 and ((hi >= tps[hit]) if d == 1 else (lo <= tps[hit])):
            R += (hit + 1) / 3
            hit += 1
        if hit == 3:
            return R, 3
    if not path:
        return 0.0, 0
    return R + (3 - hit) / 3 * (path[-1][2] - entry) * d / risk, hit


def run(sym, tf):
    sub, days, tfms, subms = CONF[tf]
    start = now_ms - (days + 60) * 86_400_000
    try:
        cs = kl(sym, tf, start)
        ss = kl(sym, sub, now_ms - days * 86_400_000)
    except Exception:  # noqa: BLE001
        return []
    if len(cs) < 400 or not ss:
        return []
    sub_by = {}
    for x in ss:
        sub_by.setdefault(x["t"] - x["t"] % tfms if tf != "4h" else x["t"] - (x["t"] % tfms), []).append(x)
    h = [x["h"] for x in cs]; l = [x["l"] for x in cs]; c = [x["c"] for x in cs]; v = [x["v"] for x in cs]
    a_all = ta.atr(h, l, c, 14)
    t0 = now_ms - days * 86_400_000
    res = []
    used = set()
    for k in range(320, len(cs) - 1):
        if cs[k]["t"] < t0 or cs[k]["t"] not in sub_by:
            continue
        lo = k - 300
        w_h, w_l, w_c = h[lo:k], l[lo:k], c[lo:k]          # k-1'e kadar (kırılım mumu henüz yok)
        evs = [e for e in ta.trendlines_close(w_h, w_l, w_c)
               if e["state"] == "active" and e["touches"] >= 2 and e["b"] - e["a"] >= SPAN[tf]]
        if not evs:
            continue
        ai = a_all[k - 1]
        if not ai:
            continue
        for e in evs:
            A, B = lo + e["a"], lo + e["b"]
            key = (e["type"], A, B, k)
            if key in used:
                continue
            slope = (c[B] - c[A]) / (B - A)
            L = c[B] + slope * (k - B)
            d = 1 if e["type"] == "falling" else -1
            thr = L + d * 0.1 * ai
            subs = sub_by[cs[k]["t"]]
            j = next((q for q, x in enumerate(subs) if (x["h"] >= thr if d == 1 else x["l"] <= thr)), None)
            if j is None:
                continue
            used.add(key)
            conf = (c[k] - thr) * d > 0
            vm = sum(v[k - 20:k]) / 20
            vr = v[k] / vm if vm else 0
            r = 1.5 * ai
            after = [(x["h"], x["l"], x["c"]) for x in cs[k + 1:k + 301]]
            # mum içi
            e_i = subs[j]["c"]
            st_i, tp_i = e_i - d * r, [e_i + d * r * m for m in (1, 2, 3)]
            rest = [(x["h"], x["l"], x["c"]) for x in subs[j + 1:]]
            R1, hit1 = run_plan(rest + after, d, e_i, st_i, tp_i)
            if conf:
                R2, hit2 = R1, hit1
            else:
                R2, hit2 = run_plan(rest, d, e_i, st_i, tp_i)       # ❌: kapanışta çık
                if hit2 < 3 and not any(((x[1] <= st_i) if d == 1 else (x[0] >= st_i)) for x in rest):
                    R2 = R2  # run_plan kapanışta (son alt mum) değerledi
            out = {"tf": tf, "conf": conf, "vr": vr, "risk_i": r / e_i * 100, "I1": R1, "I2": R2}
            if conf:
                e_c = c[k]
                Rc, hitc = run_plan(after, d, e_c, e_c - d * r, [e_c + d * r * m for m in (1, 2, 3)])
                out.update(C=Rc, risk_c=r / e_c * 100)
            res.append(out)
    return res


rows = []
jobs = [(s, tf) for tf in ("15m", "1h", "4h") for s in SYMS]
with ThreadPoolExecutor(max_workers=4) as ex:
    for r in ex.map(lambda j: run(*j), jobs):
        rows += r
print("XX| olay", len(rows))


def st(vals):
    if not vals:
        return "n=0"
    n = len(vals)
    gp = sum(x for x in vals if x > 0); gl = -sum(x for x in vals if x < 0)
    return f"n={n:5d} ort={sum(vals) / n:+.3f}R PF={gp / gl if gl else 0:.2f} kazanan={sum(1 for x in vals if x > 0) / n * 100:.0f}%"


for tf in ("15m", "1h", "4h", None):
    x = [r for r in rows if tf is None or r["tf"] == tf]
    if not x:
        continue
    lab = tf or "HEPSİ"
    fake = sum(1 for r in x if not r["conf"]) / len(x) * 100
    print("XX|", lab, f"mum içi kırılım {len(x)}, kapanışta teyit edilmeyen (sahte) %{fake:.0f}")
    print("XX|", lab, "I1 mum içi, tut      :", st([r["I1"] - FEE / r["risk_i"] for r in x]))
    print("XX|", lab, "I2 mum içi, ❌'de çık :", st([r["I2"] - FEE / r["risk_i"] for r in x]))
    print("XX|", lab, "C1 kapanışta gir     :", st([r["C"] - FEE / r["risk_c"] for r in x if r["conf"]]))
    print("XX|", lab, "C2 kapanış+hacim≥1.5 :", st([r["C"] - FEE / r["risk_c"] for r in x if r["conf"] and r["vr"] >= 1.5]))
    print("XX|", lab, "I1 sadece teyitliler :", st([r["I1"] - FEE / r["risk_i"] for r in x if r["conf"]]))
