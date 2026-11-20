"""Geçici araştırma: Nokta Atışı (tüm kurallar) + Supertrend sinyalleri ve sinyal anındaki tüm veriler → CSV.
Veriler: 22 indikatör oyu, lider, 4s trend, vadeli/spot agresif alıcı-satıcı (taker) hacmi, fonlama oranı,
açık pozisyon (OI), long/short oranları (son 30 gün). Sonuç: TP'lerde 1/3 kapanış, sabit stop (R) ve TP1 sonrası
stop girişe (R_be)."""
import bisect, csv, gzip, json, os, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as S
import sniper as N

BARS = {"15m": 8000, "1h": 4000, "4h": 2000}
TFMS = {"15m": 900_000, "1h": 3_600_000, "4h": 14_400_000}
base = json.load(open(S.CONFIG_PATH, encoding="utf-8"))
api = S.Binance(max_weight=1500)
now_ms = int(time.time() * 1000)
dlock = threading.Lock()
last_d = [0.0]


def dget(path, params):
    """futures/data uçları: 5 dakikada 1000 istek sınırı → istekler arası en az 0.35 sn"""
    with dlock:
        w = 0.35 - (time.time() - last_d[0])
        if w > 0:
            time.sleep(w)
        last_d[0] = time.time()
    return api.get(path, params)


def klines(path, sym, tf, total):
    out, end = [], None
    while len(out) < total:
        p = {"symbol": sym, "interval": tf, "limit": 1500 if "fapi" in path else 1000}
        if end:
            p["endTime"] = end
        raw = api.get(path, p)
        if not raw:
            break
        out = raw + out
        end = int(raw[0][0]) - 1
        if len(raw) < p["limit"]:
            break
    res, seen = [], set()
    for k in out:
        t = int(k[0])
        if t in seen or int(k[6]) >= now_ms:
            continue
        seen.add(t)
        res.append(k)
    res.sort(key=lambda k: int(k[0]))
    return res[-total:]


def hist30(path, sym, key):
    """son 30 günün 1 saatlik verisi: [(timestamp, değer)]"""
    out = []
    st = now_ms - 29 * 86_400_000
    while st < now_ms:
        try:
            raw = dget(path, {"symbol": sym, "period": "1h", "limit": 500, "startTime": st})
        except Exception:  # noqa: BLE001
            break
        if not raw:
            break
        for r in raw:
            try:
                out.append((int(r["timestamp"]), float(r[key])))
            except (KeyError, ValueError, TypeError):
                pass
        st = int(raw[-1]["timestamp"]) + 1
        if len(raw) < 500:
            break
    return sorted(set(out))


def funding_hist(sym, start):
    out, st = [], start
    while True:
        raw = api.get("/fapi/v1/fundingRate", {"symbol": sym, "startTime": st, "limit": 1000})
        if not raw:
            break
        out += [(int(r["fundingTime"]), float(r["fundingRate"])) for r in raw]
        st = int(raw[-1]["fundingTime"]) + 1
        if len(raw) < 1000:
            break
    return out


class Ser:
    def __init__(self, pairs, tol=3 * 3_600_000):
        self.tol = tol
        self.t = [p[0] for p in pairs]
        self.v = [p[1] for p in pairs]

    def at(self, ts, back_ms=0):
        k = bisect.bisect_right(self.t, ts - back_ms) - 1
        return self.v[k] if k >= 0 and self.t and ts - back_ms - self.t[k] < self.tol else None


def sim(f, i, d, entry, stop, tps, maxb=300):
    risk = abs(entry - stop)
    n = len(f["c"])
    end = min(n - 1, i + maxb)
    if end <= i or not risk:
        return None
    hit, R, Rb, done_b, cur = 0, 0.0, 0.0, False, stop
    hit_b, res_fixed = 0, None
    for k in range(i + 1, end + 1):
        hi, lo = f["h"][k], f["l"][k]
        if res_fixed is None:
            if (lo <= stop) if d == 1 else (hi >= stop):
                res_fixed = (R - (3 - hit) / 3, hit, k)
            else:
                while hit < 3 and ((hi >= tps[hit]) if d == 1 else (lo <= tps[hit])):
                    R += (hit + 1) / 3
                    hit += 1
                if hit == 3:
                    res_fixed = (R, 3, k)
        if not done_b:
            if (lo <= cur) if d == 1 else (hi >= cur):
                Rb += (3 - hit_b) / 3 * (cur - entry) * d / risk
                done_b = True
            else:
                while hit_b < 3 and ((hi >= tps[hit_b]) if d == 1 else (lo <= tps[hit_b])):
                    Rb += (hit_b + 1) / 3
                    hit_b += 1
                    cur = entry
                if hit_b == 3:
                    done_b = True
        if res_fixed is not None and done_b:
            break
    last = f["c"][end]
    if res_fixed is None:
        res_fixed = (R + (3 - hit) / 3 * (last - entry) * d / risk, hit, end)
    if not done_b:
        Rb += (3 - hit_b) / 3 * (last - entry) * d / risk
    return {"R": res_fixed[0], "hit": res_fixed[1], "exit": res_fixed[2], "R_be": Rb}


def sym_data(meta, tf):
    sym = meta["symbol"]
    raw = klines("/fapi/v1/klines", sym, tf, BARS[tf])
    if len(raw) < 600:
        return None
    cs = [{"t": int(k[0]), "o": float(k[1]), "h": float(k[2]), "l": float(k[3]), "c": float(k[4]),
           "v": float(k[7]), "bv": float(k[5])} for k in raw]
    tbq = [float(k[10]) for k in raw]
    spot = {}
    if meta.get("type") == "COIN":
        ss = sym[4:] if sym.startswith("1000") else sym
        try:
            sr = klines("/api/v3/klines", ss, tf, BARS[tf])
            spot = {int(k[0]): (float(k[7]), float(k[10])) for k in sr}
        except Exception:  # noqa: BLE001
            spot = {}
    return cs, tbq, spot


CACHE = {}


def extras(sym):
    if sym in CACHE:
        return CACHE[sym]
    start = now_ms - 340 * 86_400_000
    try:
        fr = funding_hist(sym, start)
    except Exception:  # noqa: BLE001
        fr = []
    e = {"fund": Ser(fr, 9 * 3_600_000),
         "oi": Ser(hist30("/futures/data/openInterestHist", sym, "sumOpenInterestValue")),
         "ls": Ser(hist30("/futures/data/globalLongShortAccountRatio", sym, "longShortRatio")),
         "top": Ser(hist30("/futures/data/topLongShortPositionRatio", sym, "longShortRatio")),
         "tk": Ser(hist30("/futures/data/takerlongshortRatio", sym, "buySellRatio"))}
    CACHE[sym] = e
    return e


def window_delta(vol, tb, i, n):
    q = sum(vol[i - n + 1:i + 1])
    return (2 * sum(tb[i - n + 1:i + 1]) / q - 1) if q else 0.0


def rows_for(meta, tf, cfg, lead, D):
    sym, typ = meta["symbol"], meta.get("type", "COIN")
    cs, tbq, spot = D
    f = S.compute_features(cs, cfg)
    n = len(f["c"])
    vol = f["v"]
    sv = [spot.get(t, (0.0, 0.0)) for t in f["t"]]
    svol = [x[0] for x in sv]
    stb = [x[1] for x in sv]
    ex = extras(sym)
    out = []
    o, h, l, c, v = (f[k] for k in ("o", "h", "l", "c", "v"))
    x = N.features(o, h, l, c, v)
    day = {"15m": 96, "1h": 24, "4h": 6}[tf]
    st_state = {"signals": {}}

    def feat(i, d):
        t_close = f["t"][i] + TFMS[tf]
        ld = lead.get(typ)
        lb, lname, lret = 0, "4s trend", None
        if ld and ld[0] != sym and f["t"][i] in ld[1]:
            lb, lname, lret = ld[1][f["t"][i]], ld[0].replace("USDT", ""), ld[2].get(f["t"][i])
        votes = S.indicator_votes(f, i, lb, lname, "supertrend")
        r = {"sym": sym, "type": typ, "tf": tf, "t": f["t"][i], "d": d, "i": i}
        for nm, vv in votes:
            r["v_" + ("Lider" if nm == lname and lname != "4s trend" else nm)] = (vv or 0) * d
        r["agree"] = sum(1 for _, vv in votes if vv == d)
        r["against"] = sum(1 for _, vv in votes if vv == -d)
        r["lead_bias"] = lb * d
        r["lead_ret24"] = (lret * d) if lret is not None else None
        r["h4"] = (f["h4_ema"][i] + f["h4_st"][i]) * d
        a = f["atr"][i] or 0
        r["atr_pct"] = a / c[i] * 100
        r["rsi"] = f["rsi"][i]
        r["vr"] = vol[i] / f["vol_ma"][i - 1] if f["vol_ma"][i - 1] else None
        r["ema20_dist"] = ((c[i] - f["ema20"][i]) / a * d) if a else None
        r["chg_day"] = (c[i] / c[i - day] - 1) * 100 * d
        r["chg_4"] = (c[i] / c[i - 4] - 1) * 100 * d
        r["chg_12"] = (c[i] / c[i - 12] - 1) * 100 * d
        for nb in (1, 4, 12, day):
            r[f"fd{nb}"] = window_delta(vol, tbq, i, nb) * d
            r[f"sd{nb}"] = (window_delta(svol, stb, i, nb) * d) if sum(svol[i - nb + 1:i + 1]) else None
        sq, fq = sum(svol[i - day + 1:i + 1]), sum(vol[i - day + 1:i + 1])
        r["spot_share"] = sq / (sq + fq) if (sq + fq) and sq else None
        fr = ex["fund"].at(t_close)
        r["fund"] = fr * 100 if fr is not None else None
        r["fund_d"] = (fr * 100 * d) if fr is not None else None
        oi_now = ex["oi"].at(t_close)
        for hh in (1, 4, 24):
            p = ex["oi"].at(t_close, hh * 3_600_000)
            r[f"oi_chg{hh}"] = ((oi_now / p - 1) * 100) if (oi_now and p) else None
        for k_ in ("ls", "top", "tk"):
            now_ = ex[k_].at(t_close)
            prev = ex[k_].at(t_close, 24 * 3_600_000)
            r[k_] = now_
            r[k_ + "_chg24"] = (now_ - prev) if (now_ is not None and prev is not None) else None
        r["hour"] = datetime.fromtimestamp(t_close / 1000, timezone.utc).hour
        r["wd"] = datetime.fromtimestamp(t_close / 1000, timezone.utc).weekday()
        return r, lb, lname, lret

    for i in range(300, n - 1):
        # Nokta Atışı: tüm kurallar
        for sg in N.setups(o, h, l, c, v, i, x):
            if sg["rule"] in N.SSL_RULES:
                continue
            lv = N.levels(c[i], sg["d"], sg["stop"], x["a"][i], 1.0)
            res = sim(f, i, sg["d"], lv["entry"], lv["stop"], lv["tp"])
            if not res:
                continue
            r, *_ = feat(i, sg["d"])
            r.update(sys_="nokta", rule=sg["rule"], risk_pct=lv["risk"] / c[i] * 100, **res)
            out.append(r)
        # Supertrend (canlıdaki kurallar)
        if f["st_dir"][i] is None or f["st_dir"][i - 1] is None or f["st_dir"][i] == f["st_dir"][i - 1]:
            continue
        if not S.required_ready(f, i):
            continue
        r0, lb, lname, lret = feat(i, f["st_dir"][i])
        t_close = f["t"][i] + TFMS[tf]
        res_ = S.evaluate_at(meta, f, i, lb, lname, None, S.pct(c[i], c[i - 24]),
                             datetime.fromtimestamp(t_close / 1000, timezone.utc), cfg, lret)
        dd = S.decide(res_, cfg, st_state, t_close / 1000)
        if not dd:
            continue
        st_state["signals"][f"{sym}|{dd}"] = t_close / 1000
        s = 1 if dd == "long" else -1
        e, sl, tps, _ = S.levels(res_, dd, cfg)
        res = sim(f, i, s, e, sl, tps)
        if not res:
            continue
        r, *_ = feat(i, s)
        r.update(sys_="supertrend", rule="st", risk_pct=abs(e - sl) / e * 100, **res)
        out.append(r)
    return out


def main():
    universe, all_meta, _, _ = S.build_universe(api, base)
    metas = {m["symbol"]: m for m in universe}
    if os.environ.get("SMALL"):
        metas = dict(list(metas.items())[:4])
        for k in BARS:
            BARS[k] = 900
    print("XX| sembol", len(metas), flush=True)
    rows = []
    for tf in ("4h", "1h", "15m"):
        cfg = S.apply_tf_profile(json.loads(json.dumps(base)), tf)
        cfg["timeframe"] = tf
        data = {}

        def get(m):
            try:
                return m["symbol"], sym_data(m, tf)
            except Exception as e:  # noqa: BLE001
                print("  veri hatası", m["symbol"], str(e)[:60], flush=True)
                return m["symbol"], None
        allm = list(metas.values()) + [dict(all_meta[s], symbol=s) for s in ("BTCUSDT", "QQQUSDT")
                                         if s in all_meta and s not in metas]
        with ThreadPoolExecutor(max_workers=6) as ex_:
            for s, d_ in ex_.map(get, allm):
                if d_:
                    data[s] = d_
        lead = {}
        for typ, ls in (("COIN", "BTCUSDT"), ("EQUITY", "QQQUSDT")):
            if ls in data:
                lf = S.compute_features(data[ls][0], cfg)
                lead[typ] = (ls, {lf["t"][j]: S.trend_bias(lf, j) for j in range(len(lf["t"])) if S.required_ready(lf, j)},
                             {lf["t"][j]: lf["c"][j] / lf["c"][j - {"15m": 96, "1h": 24, "4h": 6}[tf]] - 1
                              for j in range(100, len(lf["t"]))})
        # fonlama / OI / long-short (sembol başına bir kez)
        with ThreadPoolExecutor(max_workers=3) as ex_:
            list(ex_.map(extras, [s for s in metas if s in data]))
        for s, m in metas.items():
            if s not in data:
                continue
            try:
                rows += rows_for(m, tf, cfg, lead, data[s])
            except Exception as e:  # noqa: BLE001
                print("  hata", s, tf, str(e)[:80], flush=True)
        print("XX|", tf, "bitti, satır", len(rows), f"{time.time() - T0:.0f}s", flush=True)
    keys = sorted({k for r in rows for k in r})
    os.makedirs("out", exist_ok=True)
    with gzip.open("out/signals.csv.gz", "wt", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)
    print("XX| yazıldı", len(rows), flush=True)


T0 = time.time()
main()
