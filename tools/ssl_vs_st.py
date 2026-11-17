"""SSL Hybrid (SSL + QQE MOD + DynaRange teyitli) ile Supertrend dönüş sinyallerinin karşılaştırması.
Aynı giriş / stop / TP kuralı: giriş = sinyal mumu kapanışı, stop = 1.5 ATR, TP1/2/3 = 1R/2R/3R.
Aynı mumda hem stop hem TP görülürse stop sayılır (kötümser)."""
import json, sys, time
from concurrent.futures import ThreadPoolExecutor
import scanner as sc

TF = sys.argv[1]
DAYS = int(sys.argv[2])
HORIZON = {"15m": 192, "1h": 120}[TF]       # 2 gün / 5 gün
LEAD_WIN = 40
cfg = sc.apply_tf_profile(json.load(open("config.json")), TF) if TF != "1h" else json.load(open("config.json"))
cfg["timeframe"] = TF
wl = cfg["universe"]["tradingview_watchlist"]
api = sc.Binance()
now_ms = int(time.time() * 1000)
bars = DAYS * 86_400_000 // sc.TF_MS[TF] + 300


def outcome(f, i, s):
    e, a = f["c"][i], f["atr"][i]
    if not a:
        return None
    risk = 1.5 * a
    n = len(f["c"])
    end = min(n - 1, i + HORIZON)
    fav = lambda j: (f["h"][j] - e) * s / risk if s == 1 else (e - f["l"][j]) / risk      # en iyi R
    adv = lambda j: (e - f["l"][j]) / risk if s == 1 else (f["h"][j] - e) / risk          # en kötü (zarar) R
    mtm = (f["c"][end] - e) * s / risk
    # 1) TP'ler stoptan önce mi? (aynı mumda ikisi de varsa stop)
    tp = [False, False, False]
    stopped = False
    for j in range(i + 1, end + 1):
        if adv(j) >= 1:
            stopped = True
            break
        for k in range(3):
            if fav(j) >= k + 1:
                tp[k] = True
    # 2) Tek hedef: 2R kâr al / 1R stop
    r2 = mtm
    for j in range(i + 1, end + 1):
        if adv(j) >= 1:
            r2 = -1.0
            break
        if fav(j) >= 2:
            r2 = 2.0
            break
    # 3) Mesajdaki plan: 1/3 TP1, 1/3 TP2, 1/3 TP3; TP1 sonrası stop girişe
    rbe, left, stop_r, got = 0.0, 1.0, -1.0, 0
    for j in range(i + 1, end + 1):
        if adv(j) >= -stop_r:
            rbe += left * stop_r
            left = 0
            break
        while got < 3 and fav(j) >= got + 1:
            got += 1
            rbe += (got) / 3
            left -= 1 / 3
            stop_r = 0.0
        if got == 3:
            left = 0
            break
    if left > 1e-9:
        rbe += left * mtm
    return {"tp": tp, "r2": r2, "rbe": rbe}


def one(sym):
    try:
        cs = sc.fetch_long_history(api, sym, TF, now_ms, bars)
        if len(cs) < 400:
            return None
        f = sc.compute_features(cs, cfg)
    except Exception as e:  # noqa: BLE001
        return {"sym": sym, "err": str(e)[:80]}
    st, n = f["st_dir"], len(cs)
    start = max(300, n - DAYS * 86_400_000 // sc.TF_MS[TF])
    res = {"sym": sym, "st": [], "ssl": [], "lead": []}
    for i in range(start, n - 1):
        if st[i] is not None and st[i - 1] is not None and st[i] != st[i - 1]:
            o = outcome(f, i, st[i])
            if o:
                res["st"].append(o)
        for s in (1, -1):
            ev = sc.ssl_signal(f, i, s, 5)
            if ev is None:
                continue
            o = outcome(f, i, s)
            if o:
                res["ssl"].append(o)
            # Supertrend aynı yöne ne zaman döndü?
            prev = None
            for j in range(i, max(1, i - LEAD_WIN), -1):
                if st[j] == s and st[j - 1] == -s:
                    prev = i - j
                    break
            nxt = None
            if prev is None and st[i] != s:
                for j in range(i + 1, min(n, i + LEAD_WIN)):
                    if st[j] == s and st[j - 1] == -s:
                        nxt = j - i
                        break
            res["lead"].append(("st_once", prev) if prev is not None else (("ssl_once", nxt) if nxt is not None else ("yok", None)))
    return res


with ThreadPoolExecutor(6) as ex:
    rows = [r for r in ex.map(one, wl) if r]


def summ(lst):
    if not lst:
        return {}
    k = len(lst)
    return {"n": k, "tp1": round(100 * sum(o["tp"][0] for o in lst) / k, 1),
            "tp2": round(100 * sum(o["tp"][1] for o in lst) / k, 1),
            "tp3": round(100 * sum(o["tp"][2] for o in lst) / k, 1),
            "r2": round(sum(o["r2"] for o in lst) / k, 3), "rbe": round(sum(o["rbe"] for o in lst) / k, 3)}


st_all = [o for r in rows if "st" in r for o in r["st"]]
ssl_all = [o for r in rows if "ssl" in r for o in r["ssl"]]
leads = [x for r in rows if "lead" in r for x in r["lead"]]
cnt = {}
for kind, v in leads:
    cnt[kind] = cnt.get(kind, 0) + 1
ssl_first = sorted(v for k, v in leads if k == "ssl_once")
st_first = sorted(v for k, v in leads if k == "st_once")
med = lambda a: a[len(a) // 2] if a else None
print("SONUC", json.dumps({"tf": TF, "days": DAYS, "symbols": len(rows),
                            "errors": [r for r in rows if "err" in r][:5],
                            "supertrend": summ(st_all), "ssl": summ(ssl_all), "lead_counts": cnt,
                            "ssl_first_median_bars": med(ssl_first), "st_first_median_bars": med(st_first)},
                           ensure_ascii=False))
