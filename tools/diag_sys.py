"""Yeni sinyal sistemi analizi: dipten / tepeden dönüş, trend içi devam, pump/dump kurulumları.
Giriş = sinyal mumunun kapanışı · stop = yapı (son diplerin/tepelerin ötesi, 0.5–3 ATR arası) · TP1/2/3 = 1R/2R/3R.
İşlem ücreti + kayma: giriş+çıkış toplam %0.12. Aynı sembol + kurulumda aynı anda tek işlem."""
import sys, time, random, statistics as st
from multiprocessing import Pool
sys.path.insert(0, ".")
from scanner import Binance, parse_klines
import indicators as ta

NSYM = 80
TFS = {"15m": (90, 96), "1h": (365, 72), "4h": (1095, 42)}     # gün, en uzun bekleme (mum)
COST = 0.0012
TF_MS = {"15m": 900000, "1h": 3600000, "4h": 14400000}


def fetch(api, sym, tf, days, now):
    out, end, need = [], now, days * 86400000 // TF_MS[tf] + 250
    while len(out) < need:
        raw = api.get("/fapi/v1/klines", {"symbol": sym, "interval": tf, "limit": 1500, "endTime": end})
        if not raw:
            break
        out = parse_klines(raw, now) + out
        end = int(raw[0][0]) - 1
        if len(raw) < 1500:
            break
    return out[-need:]


def setups(o, h, l, c, v, i, x):
    """Bu mumda oluşan kurulumlar: [(ad, yön, stop)]"""
    a, e20, e50, e200, r, vma = x["a"][i], x["e20"], x["e50"], x["e200"], x["r"], x["vma"]
    if not a or e200[i] is None or vma[i - 1] is None or r[i] is None:
        return []
    out = []
    rng = h[i] - l[i] or 1e-12
    pos = (c[i] - l[i]) / rng
    vr = v[i] / vma[i - 1] if vma[i - 1] else 0
    lo10, hi10 = min(l[i - 9:i + 1]), max(h[i - 9:i + 1])
    lo48, hi48 = min(l[i - 48:i]), max(h[i - 48:i])
    up = e50[i] > e200[i] and e50[i] > e50[i - 10]
    dn = e50[i] < e200[i] and e50[i] < e50[i - 10]
    rs = r[i - 5:i]
    if None in rs:
        return []
    # ── DİPTEN / TEPEDEN DÖNÜŞ ──
    if min(rs) < 30 and r[i - 1] <= 30 < r[i] and c[i] > o[i]:
        out.append(("Dip · RSI 30 dönüşü", 1, lo10 - 0.2 * a))
    if max(rs) > 70 and r[i - 1] >= 70 > r[i] and c[i] < o[i]:
        out.append(("Tepe · RSI 70 dönüşü", -1, hi10 + 0.2 * a))
    if l[i] < lo48 and c[i] > lo48 and c[i] > o[i] and pos >= 0.5 and vr >= 1.3:
        out.append(("Dip · likidite süpürme", 1, l[i] - 0.2 * a))
    if h[i] > hi48 and c[i] < hi48 and c[i] < o[i] and pos <= 0.5 and vr >= 1.3:
        out.append(("Tepe · likidite süpürme", -1, h[i] + 0.2 * a))
    ap = x["a"][i - 1] or a
    if c[i - 1] < e20[i - 1] - 2.5 * ap and c[i] > h[i - 1]:
        out.append(("Dip · aşırı uzama dönüşü", 1, min(l[i - 1], l[i]) - 0.2 * a))
    if c[i - 1] > e20[i - 1] + 2.5 * ap and c[i] < l[i - 1]:
        out.append(("Tepe · aşırı uzama dönüşü", -1, max(h[i - 1], h[i]) + 0.2 * a))
    # ── TREND İÇİ DEVAM ──
    pl, ph = min(l[i - 5:i]), max(h[i - 5:i])
    if up and pl <= e20[i - 1] + 0.2 * a and pl > e50[i] - 0.5 * a and c[i] > max(h[i - 3:i]) and c[i] > o[i]:
        out.append(("Trend içi yükseliş · EMA20 geri çekilme", 1, min(l[i - 5:i + 1]) - 0.2 * a))
    if dn and ph >= e20[i - 1] - 0.2 * a and ph < e50[i] + 0.5 * a and c[i] < min(l[i - 3:i]) and c[i] < o[i]:
        out.append(("Trend içi düşüş · EMA20 geri çekilme", -1, max(h[i - 5:i + 1]) + 0.2 * a))
    if up and c[i] > hi48 and vr >= 1.5:
        out.append(("Trend içi yükseliş · hacimli zirve kırılımı", 1, lo10 - 0.2 * a))
    if dn and c[i] < lo48 and vr >= 1.5:
        out.append(("Trend içi düşüş · hacimli dip kırılımı", -1, hi10 + 0.2 * a))
    if up and min(r[i - 6:i]) < 42 and r[i - 1] < 50 <= r[i]:
        out.append(("Trend içi yükseliş · RSI 40→50", 1, lo10 - 0.2 * a))
    if dn and max(r[i - 6:i]) > 58 and r[i - 1] > 50 >= r[i]:
        out.append(("Trend içi düşüş · RSI 60→50", -1, hi10 + 0.2 * a))
    # ── PUMP / DUMP ──
    body = abs(c[i] - o[i])
    if vr >= 5 and c[i] > hi48 and body >= 1.5 * a and pos >= 0.75:
        out.append(("Pump · 5x hacim patlaması", 1, l[i] - 0.2 * a))
    if vr >= 5 and c[i] < lo48 and body >= 1.5 * a and pos <= 0.25:
        out.append(("Dump · 5x hacim patlaması", -1, h[i] + 0.2 * a))
    if 3 <= vr < 5 and c[i] > hi48 and body >= 1.0 * a and pos >= 0.7:
        out.append(("Pump · 3x hacim kırılımı", 1, l[i] - 0.2 * a))
    if 3 <= vr < 5 and c[i] < lo48 and body >= 1.0 * a and pos <= 0.3:
        out.append(("Dump · 3x hacim kırılımı", -1, h[i] + 0.2 * a))
    # ── KARŞILAŞTIRMA ──
    sd = x["st"]
    if sd[i] != sd[i - 1]:
        out.append(("Karşılaştırma · Supertrend (şimdiki bot, 1.5 ATR stop)", sd[i], c[i] - sd[i] * 1.5 * a))
    if x["rnd"].random() < 1 / 150:
        d = x["rnd"].choice((1, -1))
        out.append(("Karşılaştırma · RASTGELE giriş", d, lo10 - 0.2 * a if d == 1 else hi10 + 0.2 * a))
    return out


def trade(h, l, c, i, d, stop, a, H):
    e = c[i]
    risk = (e - stop) * d
    if risk < 0.5 * a:
        risk = 0.5 * a
    if risk > 3 * a:
        risk = 3 * a
    cost = COST * e / risk
    res = {}
    tp = [e + d * k * risk for k in (1, 2, 3)]
    sl = e - d * risk
    # tek hedef çıkışları
    hit = {1: None, 2: None, 3: None}
    stop_k, last = None, min(len(c) - 1, i + H)
    for k in range(i + 1, last + 1):
        if (l[k] <= sl) if d == 1 else (h[k] >= sl):
            stop_k = k
            break
        for n in (1, 2, 3):
            if hit[n] is None and ((h[k] >= tp[n - 1]) if d == 1 else (l[k] <= tp[n - 1])):
                hit[n] = k
    end_r = (c[last] - e) * d / risk
    for n in (1, 2, 3):
        res[f"R{n}"] = (n if hit[n] is not None else (-1 if stop_k is not None else end_r)) - cost
    # yönetimli: 1/3 her hedefte, TP1 sonrası stop girişe, TP2 sonrası stop TP1'e
    s, got, R, out_k = sl, 0, 0.0, last
    for k in range(i + 1, last + 1):
        if (l[k] <= s) if d == 1 else (h[k] >= s):
            R += (3 - got) / 3 * ((s - e) * d / risk)
            got, out_k = 3, k
            break
        while got < 3 and ((h[k] >= tp[got]) if d == 1 else (l[k] <= tp[got])):
            R += (got + 1) / 3
            got += 1
            s = e if got == 1 else tp[0]
        if got == 3:
            out_k = k
            break
    if got < 3 and out_k == last:
        R += (3 - got) / 3 * ((c[last] - e) * d / risk)
    res["Rm"] = R - cost
    res["tp1"] = hit[1] is not None and (stop_k is None or hit[1] < stop_k)
    res["out"] = out_k
    return res


def run(args):
    tf, sym, cs = args
    if len(cs) < 400:
        return []
    o = [x["o"] for x in cs]; h = [x["h"] for x in cs]; l = [x["l"] for x in cs]; c = [x["c"] for x in cs]
    v = [x["v"] for x in cs]
    x = {"a": ta.atr(h, l, c, 14), "e20": ta.ema(c, 20), "e50": ta.ema(c, 50), "e200": ta.ema(c, 200),
         "r": ta.rsi(c, 14), "vma": ta.sma(v, 20), "st": ta.supertrend(h, l, c, 10, 3.0)[0],
         "rnd": random.Random(hash(sym) & 0xffff)}
    H = TFS[tf][1]
    busy, out = {}, []
    for i in range(250, len(c) - 1):
        for name, d, stop in setups(o, h, l, c, v, i, x):
            if busy.get(name, -1) >= i:
                continue
            r = trade(h, l, c, i, d, stop, x["a"][i], H)
            busy[name] = r["out"]
            out.append((tf, name, d, cs[i]["t"], r))
    return out


if __name__ == "__main__":
    api = Binance()
    now = int(time.time() * 1000)
    info = api.get("/fapi/v1/exchangeInfo")
    ok = {s["symbol"] for s in info["symbols"] if s["contractType"] == "PERPETUAL" and s["quoteAsset"] == "USDT"
          and s["status"] == "TRADING"}
    tick = sorted((t for t in api.get("/fapi/v1/ticker/24hr") if t["symbol"] in ok),
                  key=lambda t: -float(t["quoteVolume"]))[:NSYM]
    jobs = []
    for tf, (days, _) in TFS.items():
        for t in tick:
            try:
                jobs.append((tf, t["symbol"], fetch(api, t["symbol"], tf, days, now)))
            except Exception as ex:  # noqa: BLE001
                print("SY| veri hatası", tf, t["symbol"], ex)
        print(f"SY| {tf} verisi alındı ({days} gün)", flush=True)
    with Pool(4) as p:
        ev = [e for part in p.map(run, jobs, chunksize=2) for e in part]

    def pf(xs):
        g = sum(x for x in xs if x > 0); b = -sum(x for x in xs if x < 0)
        return g / b if b else 99

    for tf, (days, _) in list(TFS.items()) + [("TÜMÜ", (0, 0))]:
        E = [e for e in ev if tf == "TÜMÜ" or e[0] == tf]
        if not E:
            continue
        mid = {t: (now - TFS[t][0] * 86400000 / 2) for t in TFS}
        print(f"SY| ===== {tf} =====")
        print("SY| kurulum | işlem | günde | TP1 % | yalnız TP1 R | yalnız TP2 R | yalnız TP3 R | yönetimli R | PF | 1. yarı R | 2. yarı R")
        for name in sorted({e[1] for e in E}):
            X = [e for e in E if e[1] == name]
            rm = [e[4]["Rm"] for e in X]
            h1 = [e[4]["Rm"] for e in X if e[3] < mid[e[0]]]
            h2 = [e[4]["Rm"] for e in X if e[3] >= mid[e[0]]]
            per_day = len(X) / (days if days else 1) if tf != "TÜMÜ" else 0
            print(f"SY| {name} | {len(X)} | {per_day:.1f} | {100 * sum(e[4]['tp1'] for e in X) / len(X):.0f} | "
                  f"{st.mean(e[4]['R1'] for e in X):+.3f} | {st.mean(e[4]['R2'] for e in X):+.3f} | "
                  f"{st.mean(e[4]['R3'] for e in X):+.3f} | {st.mean(rm):+.3f} | {pf(rm):.2f} | "
                  f"{(st.mean(h1) if h1 else 0):+.3f} ({len(h1)}) | {(st.mean(h2) if h2 else 0):+.3f} ({len(h2)})", flush=True)
