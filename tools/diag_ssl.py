"""SSL Hybrid Buy/Sell (kullanıcının TradingView'daki etiketleri) → giriş/TP1-3/stop testi.
1) BTC 1s son 80 mumdaki Buy/Sell etiketleri (TradingView ile karşılaştırma)
2) 80 coin · 15dk 90 gün · 1s 365 gün: farklı filtrelerle sonuç (ücret %0.12 düşülmüş)."""
import sys, time, statistics as st
from multiprocessing import Pool
sys.path.insert(0, ".")
import scanner as S
import indicators as ta

COST, NSYM = 0.0012, 80
TFS = {"15m": (90, 96), "1h": (365, 72)}
TF_MS = {"15m": 900000, "1h": 3600000}


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


def trade(h, l, c, i, d, stop, a, H, floor):
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
    o, h, l, c, ssl, a, st_ = f["o"], f["h"], f["l"], f["c"], f["ssl"], f["atr"], f["st_dir"]
    htf = htf_map(cs4, [x["t"] + TF_MS[tf] for x in cs])
    H = TFS[tf][1]
    busy, out = {}, []
    for i in range(300, len(c) - 1):
        if ssl[i] is None or ssl[i - 1] is None or not a[i]:
            continue
        d = 1 if c[i] > ssl[i] and c[i - 1] <= ssl[i - 1] else (-1 if c[i] < ssl[i] and c[i - 1] >= ssl[i - 1] else 0)
        conf = {}
        for s_ in (1, -1):
            conf[s_] = S.ssl_signal(f, i, s_, 5) is not None
        for dd in (1, -1):
            if not (d == dd or conf[dd]):
                continue
            stop = (min(l[i - 9:i + 1]) - 0.2 * a[i]) if dd == 1 else (max(h[i - 9:i + 1]) + 0.2 * a[i])
            tags = []
            if d == dd:
                tags.append("a) SSL Buy/Sell (tümü)")
                if st_[i] == -dd:
                    tags.append("b) SSL · Supertrend TERS yönde (resimdeki gibi)")
                if st_[i] == dd:
                    tags.append("c) SSL · Supertrend AYNI yönde")
                if htf[i] == dd:
                    tags.append("d) SSL · 4s trend yönünde")
                if st_[i] == -dd and htf[i] == dd:
                    tags.append("e) SSL · Supertrend ters + 4s trend yönünde")
            if conf[dd]:
                tags.append("f) SSL + QQE MOD + DynaRange teyidi")
                if htf[i] == dd:
                    tags.append("g) SSL + QQE + DynaRange + 4s trend")
            for tg in tags:
                for floor, sn in ((0.0, "stop yapı"), (0.01, "stop yapı, en az %1")):
                    nm = f"{tg} | {sn}"
                    if busy.get(nm, -1) >= i:
                        continue
                    R, tp1, ok = trade(h, l, c, i, dd, stop, a[i], H, floor)
                    busy[nm] = ok
                    out.append((tf, nm, cs[i]["t"], R, tp1))
    return out


if __name__ == "__main__":
    base = S.load_json(S.CONFIG_PATH, None)
    api = S.Binance()
    now = int(time.time() * 1000)
    # 1) BTC 1s etiketleri
    cs = S.parse_klines(api.get("/fapi/v1/klines", {"symbol": "BTCUSDT", "interval": "1h", "limit": 499}), now)
    f = S.compute_features(cs, base)
    lab = []
    for i in range(len(cs) - 80, len(cs)):
        s0, s1 = f["ssl"][i - 1], f["ssl"][i]
        if s0 is None or s1 is None:
            continue
        c0, c1 = f["c"][i - 1], f["c"][i]
        t = S.datetime.fromtimestamp((cs[i]["t"]) / 1000, S.TR_TZ).strftime("%d.%m %H:%M")
        if c1 > s1 and c0 <= s0:
            lab.append(f"{t} Buy {c1:.0f} (Supertrend {'AL' if f['st_dir'][i] == 1 else 'SAT'})")
        if c1 < s1 and c0 >= s0:
            lab.append(f"{t} Sell {c1:.0f} (Supertrend {'AL' if f['st_dir'][i] == 1 else 'SAT'})")
    for x in lab:
        print("BT| " + x)
    # 2) test
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
