"""SSL Hybrid baseline (HMA 55 + Keltner 0.2) rengi + SSL çıkış etiketleri: SKY/BTC 1s olay listesi ve 80 coin testi.
Sinyal: baseline rengi döner (kırmızı → SHORT, mavi → LONG); 'uyarılı' = son N mumda aynı yönde SSL çıkış etiketi.
Çıkış A: TP 1/2/3R yönetimli · Çıkış B: çizgi ters renge dönene kadar tut (ilk stop aynı)."""
import sys, time, statistics as st
from multiprocessing import Pool
sys.path.insert(0, ".")
import scanner as S
import indicators as ta

COST, NSYM = 0.0012, 80
TFS = {"15m": (90, 400), "1h": (365, 300)}
TF_MS = {"15m": 900000, "1h": 3600000, "4h": 14400000}


def baseline(h, l, c, n=55, mult=0.2):
    bb = ta.hma(c, n)
    tr = ta.true_range(h, l, c)
    rma = ta.ema([x or 0 for x in tr], n)
    col = [0] * len(c)
    for i in range(len(c)):
        if bb[i] is None or rma[i] is None:
            continue
        up, lo = bb[i] + rma[i] * mult, bb[i] - rma[i] * mult
        col[i] = 1 if c[i] > up else (-1 if c[i] < lo else 0)
    return bb, col


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


def tp_trade(h, l, c, i, d, risk, H):
    e = c[i]
    tp = [e + d * k * risk for k in (1, 2, 3)]
    s, got, R, last = e - d * risk, 0, 0.0, min(len(c) - 1, i + H)
    out_k = last
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
    return R - COST * e / risk, out_k


def hold_trade(h, l, c, col, i, d, risk, H):
    e, s = c[i], c[i] - d * risk
    last = min(len(c) - 1, i + H)
    for k in range(i + 1, last + 1):
        if (l[k] <= s) if d == 1 else (h[k] >= s):
            return -1 - COST * e / risk, k
        if col[k] == -d:
            return (c[k] - e) * d / risk - COST * e / risk, k
    return (c[last] - e) * d / risk - COST * e / risk, last


def events(f, col, i, lookback=10):
    """i. mumda baseline rengi döndüyse [(ad, yön)]"""
    if col[i] == 0 or col[i] == col[i - 1]:
        return []
    d = col[i]
    # önceki renk ters miydi (gri geçişli de olabilir): son 'renkli' mum
    prev = next((col[k] for k in range(i - 1, max(0, i - 50), -1) if col[k] != 0), 0)
    if prev != -d:
        return []
    ssl, c = f["ssl"], f["c"]
    warn = None
    for k in range(i, max(1, i - lookback) - 1, -1):
        if ssl[k] is None or ssl[k - 1] is None:
            break
        if (c[k] - ssl[k]) * d > 0 and (c[k - 1] - ssl[k - 1]) * d <= 0:
            warn = i - k
            break
    out = []
    if warn is None or f["st_dir"][i] != -d:
        return out
    # önceki rejim kaç mum sürdü (ters renk + gri)
    k = i - 1
    while k > 0 and col[k] != d:
        k -= 1
    reg = i - 1 - k
    h, l, a = f["h"], f["l"], f["atr"]
    w = i - warn
    near = ((max(h[w - 48:w + 1]) - h[w]) / a[w] <= 1.0) if d == -1 else ((l[w] - min(l[w - 48:w + 1])) / a[w] <= 1.0)
    out.append(("3) Uyarı + çizgi döndü + Supertrend ters", d))
    for m in (15, 30):
        if reg >= m:
            out.append((f"4) 3 + önceki trend ≥{m} mum", d))
            if near:
                out.append((f"5) 3 + önceki trend ≥{m} mum + uyarı tepede/dipte (48 mum ucu ≤1 ATR)", d))
    if near:
        out.append(("6) 3 + uyarı tepede/dipte", d))
    return out


def run(args):
    tf, sym, cs, cfg = args
    if len(cs) < 500:
        return []
    f = S.compute_features(cs, cfg)
    h, l, c, a = f["h"], f["l"], f["c"], f["atr"]
    bb, col = baseline(h, l, c)
    H = TFS[tf][1]
    busy, out = {}, []
    for i in range(300, len(c) - 1):
        for nm, d in events(f, col, i):
            if not a[i]:
                continue
            ext = max(h[i - 10:i + 1]) if d == -1 else min(l[i - 10:i + 1])
            risk = min(max((c[i] - ext) * d + 0.2 * a[i], 0.5 * a[i]), 3 * a[i])
            risk = max(risk, 0.01 * c[i])
            for ex in ("A) TP 1/2/3R", "B) çizgi ters dönene kadar"):
                key = f"{nm} | {ex}"
                if busy.get(key, -1) >= i:
                    continue
                if ex[0] == "A":
                    R, k = tp_trade(h, l, c, i, d, risk, 96 if tf == "15m" else 72)
                else:
                    R, k = hold_trade(h, l, c, col, i, d, risk, H)
                busy[key] = k
                out.append((tf, key, cs[i]["t"], R, k - i))
    return out


def show(api, sym, now, base):
    cs = S.parse_klines(api.get("/fapi/v1/klines", {"symbol": sym, "interval": "1h", "limit": 499}), now)
    f = S.compute_features(cs, base)
    bb, col = baseline(f["h"], f["l"], f["c"])
    ssl, c, st_ = f["ssl"], f["c"], f["st_dir"]
    print(f"EV| ===== {sym} 1s (son 110 mum) =====")
    for i in range(len(cs) - 110, len(cs)):
        t = S.datetime.fromtimestamp(cs[i]["t"] / 1000, S.TR_TZ).strftime("%d.%m %H:%M")
        msg = []
        if ssl[i] and ssl[i - 1]:
            if c[i] > ssl[i] and c[i - 1] <= ssl[i - 1]:
                msg.append("SSL Buy")
            if c[i] < ssl[i] and c[i - 1] >= ssl[i - 1]:
                msg.append("SSL Sell")
        if col[i] != col[i - 1]:
            msg.append("çizgi " + {1: "MAVİ", -1: "KIRMIZI", 0: "gri"}[col[i]])
        if st_[i] != st_[i - 1]:
            msg.append("Supertrend " + ("AL" if st_[i] == 1 else "SAT"))
        sg = events(f, col, i)
        if sg:
            msg.append("→ SİNYAL: " + " / ".join(x[0] for x in sg))
        if msg:
            print(f"EV| {t} {c[i]:.5g} · " + " · ".join(msg))


if __name__ == "__main__":
    base = S.load_json(S.CONFIG_PATH, None)
    api = S.Binance()
    now = int(time.time() * 1000)
    for sym in ():
        show(api, sym, now, base)
    info = api.get("/fapi/v1/exchangeInfo")
    ok = {s["symbol"] for s in info["symbols"] if s["contractType"] == "PERPETUAL" and s["quoteAsset"] == "USDT"
          and s["status"] == "TRADING"}
    tick = sorted((t for t in api.get("/fapi/v1/ticker/24hr") if t["symbol"] in ok),
                  key=lambda t: -float(t["quoteVolume"]))[:NSYM]
    jobs = []
    for tf, (days, _) in TFS.items():
        cfg = S.apply_tf_profile(base, tf) if tf != "1h" else base
        for t in tick:
            try:
                jobs.append((tf, t["symbol"], fetch(api, t["symbol"], tf, days, now), cfg))
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
        print("SS| sinyal | çıkış | işlem | günde | kazanan % | ort. R | PF | 1. yarı | 2. yarı | ort. süre (mum)")
        for nm in sorted({e[1] for e in ev if e[0] == tf}):
            X = [e for e in ev if e[0] == tf and e[1] == nm]
            r = [e[3] for e in X]
            h1 = [e[3] for e in X if e[2] < mid]; h2 = [e[3] for e in X if e[2] >= mid]
            print(f"SS| {nm} | {len(X)} | {len(X) / days:.1f} | {100 * sum(x > 0 for x in r) / len(r):.0f} | "
                  f"{st.mean(r):+.3f} | {pf(r):.2f} | {(st.mean(h1) if h1 else 0):+.3f} | {(st.mean(h2) if h2 else 0):+.3f} | "
                  f"{st.mean(e[4] for e in X):.0f}", flush=True)
