"""Nokta atışı kuralları (canlı kod + config) · stop 1.5 ATR, TP 1/2/3R (Supertrend ile aynı) · 80 coin geçmiş test.
Çıktı: kural başına TP1 % ve ortalama R (yönetimli, ücret %0.12) → config test_tp1 / test_r güncellenir."""
import sys, time, statistics as st
from multiprocessing import Pool
sys.path.insert(0, ".")
import scanner as S
import sniper as SN
import indicators as ta

COST, NSYM = 0.0012, 80
TFS = {"15m": (90, 96), "1h": (365, 72)}
TF_MS = {"15m": 900000, "1h": 3600000, "4h": 14400000}


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


def trade(h, l, c, i, lv, d, H):
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
    tf, sym, cs, cs4, cfg = args
    if len(cs) < 500:
        return []
    rules = {k: v for k, v in cfg["sniper"]["rules"][tf].items() if v.get("enabled")}
    f = S.compute_features(cs, cfg)
    o, h, l, c, v = f["o"], f["h"], f["l"], f["c"], f["v"]
    x = SN.features(o, h, l, c, v)
    sp = rules.get("ssl_top")
    col = SN.ssl_baseline(h, l, c, sp.get("hma", 55))[1] if sp else None
    htf = htf_map(cs4, [q["t"] + TF_MS[tf] for q in cs])
    H = TFS[tf][1]
    busy, out = {}, []
    for i in range(300, len(c) - 1):
        sigs = SN.setups(o, h, l, c, v, i, x)
        if sp:
            ss = SN.ssl_system(h, l, c, f["ssl"], f["st_dir"], x["a"], col, i, sp)
            if ss:
                sigs.append(ss)
        for sig in sigs:
            rc = rules.get(sig["rule"])
            if not rc or (rc.get("htf") and htf[i] != sig["d"]):
                continue
            if busy.get(sig["rule"], -1) >= i or not x["a"][i]:
                continue
            lv = SN.levels_atr(c[i], sig["d"], x["a"][i], cfg["risk"])
            R, tp1, k = trade(h, l, c, i, lv, sig["d"], H)
            busy[sig["rule"]] = k
            out.append((tf, sig["rule"], cs[i]["t"], R, tp1))
    return out


if __name__ == "__main__":
    base = S.load_json(S.CONFIG_PATH, None)
    api = S.Binance()
    now = int(time.time() * 1000)
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
    for tf, (days, _) in TFS.items():
        mid = now - days * 86400000 / 2
        print(f"SN| ===== {tf} =====")
        for rule in sorted({e[1] for e in ev if e[0] == tf}):
            X = [e for e in ev if e[0] == tf and e[1] == rule]
            r = [e[3] for e in X]
            h1 = [e[3] for e in X if e[2] < mid]; h2 = [e[3] for e in X if e[2] >= mid]
            print(f"SN| {tf} {rule} | {len(X)} | {len(X) / days:.1f}/gün | TP1 %{100 * sum(e[4] for e in X) / len(X):.0f} | "
                  f"{st.mean(r):+.3f}R | 1.yarı {(st.mean(h1) if h1 else 0):+.3f} | 2.yarı {(st.mean(h2) if h2 else 0):+.3f}",
                  flush=True)
