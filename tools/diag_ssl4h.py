"""SSL stratejisi 4 saat testi: 80 coin, 3 yıl. Canlı ayarlar + seçenekler. Stop yapı (en az %1), TP 1/2/3R yönetimli,
ücret %0.12. Karşılaştırma: rastgele giriş."""
import random, sys, time, statistics as st
from multiprocessing import Pool
sys.path.insert(0, ".")
import scanner as S
import sniper as SN

COST, NSYM, DAYS, H = 0.0012, 80, 1095, 42
VARS = [("A) Şimdiki: çizgi döndüğünde giriş", {}),
        ("B) Teyitli: QQE + DynaRange gelince giriş (≤5 mum)", {"confirm_required": True}),
        ("C) Teyitli, ≤12 mum bekle", {"confirm_required": True, "confirm_bars": 12}),
        ("D) Şimdiki + Supertrend henüz ters (erken giriş)", {"supertrend_opposite": True}),
        ("E) Şimdiki, tepe/dip yakınlık şartı yok", {"near_atr": 99})]


def fetch(api, sym, now):
    out, end, need = [], now, DAYS * 6 + 300
    while len(out) < need:
        raw = api.get("/fapi/v1/klines", {"symbol": sym, "interval": "4h", "limit": 1500, "endTime": end})
        if not raw:
            break
        out = S.parse_klines(raw, now) + out
        end = int(raw[0][0]) - 1
        if len(raw) < 1500:
            break
    return out[-need:]


def trade(h, l, c, i, lv, d):
    e, risk, tp = lv["entry"], lv["risk"], lv["tp"]
    s, got, R, last = lv["stop"], 0, 0.0, min(len(c) - 1, i + H)
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
    return R - COST * e / risk, tp1, out_k


def run(args):
    sym, cs, cfg = args
    if len(cs) < 500:
        return []
    base = cfg["sniper"]["rules"]["4h"]["ssl_top"]
    f = S.compute_features(cs, cfg)
    h, l, c, o, v = f["h"], f["l"], f["c"], f["o"], f["v"]
    x = SN.features(o, h, l, c, v)
    col = SN.ssl_baseline(h, l, c, 55)[1]
    rnd = random.Random(hash(sym) & 0xffff)
    out = []
    for name, over in VARS + [("Z) Karşılaştırma: rastgele giriş", None)]:
        p = dict(base, **(over or {}))
        busy = -1
        for i in range(300, len(c) - 1):
            if i <= busy or not x["a"][i]:
                continue
            if over is None:
                if rnd.random() >= 1 / 60:
                    continue
                d = rnd.choice((1, -1))
                stop = (min(l[i - 9:i + 1]) - 0.2 * x["a"][i]) if d == 1 else (max(h[i - 9:i + 1]) + 0.2 * x["a"][i])
                sig = {"d": d, "stop": stop}
            else:
                sig = SN.ssl_system(h, l, c, f["ssl"], f["st_dir"], x["a"], col, i, p, f["qqe"], f["dyna"])
                if not sig:
                    continue
            lv = SN.levels(c[i], sig["d"], sig["stop"], x["a"][i], 1.0)
            R, tp1, k = trade(h, l, c, i, lv, sig["d"])
            busy = k
            out.append((name, sig["d"], cs[i]["t"], R, tp1))
    return out


if __name__ == "__main__":
    cfg = S.apply_tf_profile(S.load_json(S.CONFIG_PATH, None), "4h")
    api = S.Binance()
    now = int(time.time() * 1000)
    info = api.get("/fapi/v1/exchangeInfo")
    ok = {s["symbol"] for s in info["symbols"] if s["contractType"] == "PERPETUAL" and s["quoteAsset"] == "USDT"
          and s["status"] == "TRADING"}
    tick = sorted((t for t in api.get("/fapi/v1/ticker/24hr") if t["symbol"] in ok),
                  key=lambda t: -float(t["quoteVolume"]))[:NSYM]
    jobs = []
    for t in tick:
        try:
            jobs.append((t["symbol"], fetch(api, t["symbol"], now), cfg))
        except Exception:  # noqa: BLE001
            pass
    with Pool(4) as p:
        ev = [e for part in p.map(run, jobs, chunksize=2) for e in part]
    mid = now - DAYS * 86400000 / 2

    def pf(xs):
        g = sum(x for x in xs if x > 0); b = -sum(x for x in xs if x < 0)
        return g / b if b else 99

    print(f"T4| {len(jobs)} coin · 4 saat · {DAYS} gün")
    for name in sorted({e[0] for e in ev}):
        for dd, dn in ((None, "tümü"), (1, "LONG"), (-1, "SHORT")):
            X = [e for e in ev if e[0] == name and (dd is None or e[1] == dd)]
            if not X:
                continue
            r = [e[3] for e in X]
            h1 = [e[3] for e in X if e[2] < mid]; h2 = [e[3] for e in X if e[2] >= mid]
            print(f"T4| {name} · {dn} | {len(X)} işlem ({len(X) / DAYS:.1f}/gün) | TP1 %{100 * sum(e[4] for e in X) / len(X):.0f} | "
                  f"{st.mean(r):+.3f}R | PF {pf(r):.2f} | 1.yarı {(st.mean(h1) if h1 else 0):+.3f} | 2.yarı {(st.mean(h2) if h2 else 0):+.3f}",
                  flush=True)
