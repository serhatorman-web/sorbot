"""Kullanıcının işaretlediği SSL sinyal türleri:
 T) Trend içi geri çekilme: Supertrend yönünde, fiyat Supertrend bandına yaklaşmış (son 6 mumda ≤ prox ATR), SSL o yönde kesiyor.
 R) Tükeniş dönüşü: son 12 mumda fiyat EMA20'den ≥ ext ATR uzaklaşmış + hacimli (≥2x) mum, SSL ters yönde kesiyor (dip Buy / tepe Sell).
BTC 1s'te işaretli sinyaller kontrol edilir, sonra 80 coin test (ücret %0.12, stop yapı en az %1, TP 1/2/3R yönetimli)."""
import sys, time, statistics as st
from multiprocessing import Pool
sys.path.insert(0, ".")
import scanner as S
import indicators as ta

COST, NSYM = 0.0012, 80
TFS = {"15m": (90, 96), "1h": (365, 72)}
TF_MS = {"15m": 900000, "1h": 3600000, "4h": 14400000}
VARS_T = (0.5, 1.0, 1.5)
VARS_R = (2.0, 2.5, 3.0)


def fetch(api, sym, tf, days, now):
    out, end, need = [], now, days * 86400000 // TF_MS[tf] + 300
    while len(out) < need:
        raw = api.get("/fapi/v1/klines", {"symbol": sym, "interval": tf, "limit": 1500, "endTime": end})
        if not raw:
            break
        out = S.parse_klines(raw, now) + out
        end = int(raw[0][0]) - 1
        if len(raw) < 1500:
            break
    return out[-need:]


def trade(h, l, c, i, d, stop, a, H, floor=0.01):
    e = c[i]
    risk = min(max((e - stop) * d, 0.5 * a), 3 * a)
    risk = max(risk, floor * e)
    cost = COST * e / risk
    tp = [e + d * k * risk for k in (1, 2, 3)]
    s, got, R, last = e - d * risk, 0, 0.0, min(len(c) - 1, i + H)
    out_k, tp1 = last, False
    for k in range(i + 1, last + 1):
        if (l[k] <= s) if d == 1 else (h[k] >= s):
            R += (3 - got) / 3 * ((s - e) * d / risk)
            got, out_k = 3, k
            break
        while got < 3 and ((h[k] >= tp[got]) if d == 1 else (l[k] <= tp[got])):
            R += (got + 1) / 3
            got += 1
            tp1 = True
            s = e if got == 1 else tp[0]
        if got == 3:
            out_k = k
            break
    if got < 3 and out_k == last:
        R += (3 - got) / 3 * ((c[last] - e) * d / risk)
    return R - cost, tp1, out_k


def signals(f, i):
    """[(tür, yön, stop, ayrıntı)] – i. mumda SSL kesişimi varsa."""
    o, h, l, c, v, ssl, a = f["o"], f["h"], f["l"], f["c"], f["v"], f["ssl"], f["atr"]
    if ssl[i] is None or ssl[i - 1] is None or not a[i] or f["ema20"][i] is None:
        return []
    d = 1 if c[i] > ssl[i] and c[i - 1] <= ssl[i - 1] else (-1 if c[i] < ssl[i] and c[i - 1] >= ssl[i - 1] else 0)
    if not d:
        return []
    out = []
    stl, std = f["st_line"], f["st_dir"]
    # T: trend içi geri çekilme (Supertrend yönünde)
    if std[i] == d and all(std[k] == d for k in range(i - 6, i + 1)):
        if d == -1:
            gap = min((stl[k] - h[k]) / a[k] for k in range(i - 6, i + 1) if a[k])
        else:
            gap = min((l[k] - stl[k]) / a[k] for k in range(i - 6, i + 1) if a[k])
        stop = (max(h[i - 6:i + 1]) + 0.2 * a[i]) if d == -1 else (min(l[i - 6:i + 1]) - 0.2 * a[i])
        for p in VARS_T:
            if gap <= p:
                out.append((f"T) Trend içi geri çekilme · banda ≤{p:g} ATR", d, stop, f"banda {gap:.2f} ATR"))
    # R: tükeniş dönüşü (SSL ters yönde: dipte Buy, tepede Sell)
    e20 = f["ema20"]
    ext = max(((e20[k] - l[k]) if d == 1 else (h[k] - e20[k])) / a[k] for k in range(i - 12, i + 1) if a[k] and e20[k])
    vmax = max(v[k] / f["vol_ma"][k - 1] for k in range(i - 12, i + 1) if f["vol_ma"][k - 1])
    stop = (min(l[i - 12:i + 1]) - 0.2 * a[i]) if d == 1 else (max(h[i - 12:i + 1]) + 0.2 * a[i])
    for x in VARS_R:
        if ext >= x and vmax >= 2.0:
            out.append((f"R) Tükeniş dönüşü · EMA20'den ≥{x:g} ATR + hacim ≥2x", d, stop,
                        f"uzaklık {ext:.1f} ATR, hacim {vmax:.1f}x"))
    if not out:
        out.append(("—) diğer SSL", d, stop, ""))
    return out


def htf_map(cs4, times):
    c4 = [x["c"] for x in cs4]
    e50, e200 = ta.ema(c4, 50), ta.ema(c4, 200)
    tr = [0 if e200[k] is None else (1 if c4[k] > e200[k] and e50[k] > e200[k] else
                                     (-1 if c4[k] < e200[k] and e50[k] < e200[k] else 0)) for k in range(len(c4))]
    out, j = [], -1
    for t in times:
        while j + 1 < len(cs4) and cs4[j + 1]["t"] + 14400000 <= t:
            j += 1
        out.append(tr[j] if j >= 0 else 0)
    return out


def run(args):
    tf, sym, cs, cs4, cfg = args
    if len(cs) < 500:
        return []
    f = S.compute_features(cs, cfg)
    h, l, c, a = f["h"], f["l"], f["c"], f["atr"]
    htf = htf_map(cs4, [x["t"] + TF_MS[tf] for x in cs])
    H = TFS[tf][1]
    busy, out = {}, []
    for i in range(300, len(c) - 1):
        for nm, d, stop, _ in signals(f, i):
            for flt in ("", " · 4s trend yönünde"):
                if flt and htf[i] != d:
                    continue
                key = nm + flt
                if busy.get(key, -1) >= i:
                    continue
                R, tp1, ok = trade(h, l, c, i, d, stop, a[i], H)
                busy[key] = ok
                out.append((tf, key, cs[i]["t"], R, tp1))
    return out


if __name__ == "__main__":
    base = S.load_json(S.CONFIG_PATH, None)
    api = S.Binance()
    now = int(time.time() * 1000)
    cs = S.parse_klines(api.get("/fapi/v1/klines", {"symbol": "BTCUSDT", "interval": "1h", "limit": 499}), now)
    f = S.compute_features(cs, base)
    for i in range(len(cs) - 80, len(cs)):
        sg = signals(f, i)
        if sg:
            t = S.datetime.fromtimestamp(cs[i]["t"] / 1000, S.TR_TZ).strftime("%d.%m %H:%M")
            lab = "Buy" if sg[0][1] == 1 else "Sell"
            print(f"BT| {t} {lab} {f['c'][i]:.0f} → " + " | ".join(f"{x[0]} ({x[3]})" for x in sg))
    info = api.get("/fapi/v1/exchangeInfo")
    ok = {s["symbol"] for s in info["symbols"] if s["contractType"] == "PERPETUAL" and s["quoteAsset"] == "USDT"
          and s["status"] == "TRADING"}
    tick = sorted((t for t in api.get("/fapi/v1/ticker/24hr") if t["symbol"] in ok),
                  key=lambda t: -float(t["quoteVolume"]))[:NSYM]
    jobs, c4 = [], {}
    for t in tick:
        try:
            c4[t["symbol"]] = fetch(api, t["symbol"], "4h", 420, now)
        except Exception:  # noqa: BLE001
            c4[t["symbol"]] = []
    for tf, (days, _) in TFS.items():
        cfg = S.apply_tf_profile(base, tf) if tf != "1h" else base
        for t in tick:
            try:
                jobs.append((tf, t["symbol"], fetch(api, t["symbol"], tf, days, now), c4[t["symbol"]], cfg))
            except Exception:  # noqa: BLE001
                pass
    with Pool(4) as p:
        ev = [e for part in p.map(run, jobs, chunksize=2) for e in part]

    def pf(xs):
        g = sum(x for x in xs if x > 0); b = -sum(x for x in xs if x < 0)
        return g / b if b else 99

    for tf, (days, _) in TFS.items():
        mid = now - days * 86400000 / 2
        print(f"SS| ===== {tf} ({days} gün, {NSYM} coin) =====")
        print("SS| kural | işlem | günde | TP1 % | ort. R | PF | 1. yarı | 2. yarı")
        for nm in sorted({e[1] for e in ev if e[0] == tf}):
            X = [e for e in ev if e[0] == tf and e[1] == nm]
            r = [e[3] for e in X]
            h1 = [e[3] for e in X if e[2] < mid]; h2 = [e[3] for e in X if e[2] >= mid]
            print(f"SS| {nm} | {len(X)} | {len(X) / days:.1f} | {100 * sum(e[4] for e in X) / len(X):.0f} | "
                  f"{st.mean(r):+.3f} | {pf(r):.2f} | {(st.mean(h1) if h1 else 0):+.3f} | {(st.mean(h2) if h2 else 0):+.3f}",
                  flush=True)
