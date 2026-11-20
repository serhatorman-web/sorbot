"""Supertrend sinyalleri vs Nokta Atışı (Claude'un kuralları, SSL hariç) — aynı semboller, aynı dönem, aynı hesap.
Pozisyon: 1/3 TP1, 1/3 TP2, 1/3 TP3, stop sabit (aynı mumda stop ve TP varsa önce stop). En fazla 300 mum.
Ücret: giriş+çıkış %0.10 (net sonuçta düşülür)."""
import json, os, sys, time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as S
import sniper as N
import indicators as ta

SYMS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT", "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT",
        "LTCUSDT", "BCHUSDT", "NEARUSDT", "SUIUSDT", "APTUSDT", "ARBUSDT", "OPUSDT", "INJUSDT", "TIAUSDT", "SEIUSDT",
        "WIFUSDT", "1000PEPEUSDT", "ENAUSDT", "HYPEUSDT", "ZECUSDT", "AAVEUSDT", "UNIUSDT", "FETUSDT", "TAOUSDT",
        "RENDERUSDT", "ONDOUSDT", "JUPUSDT", "TRUMPUSDT", "FILUSDT", "ETCUSDT", "XLMUSDT", "HBARUSDT", "ATOMUSDT",
        "XAUUSDT", "XAGUSDT", "NATGASUSDT", "CLUSDT", "NVDAUSDT", "TSLAUSDT", "AAPLUSDT", "MSTRUSDT", "COINUSDT", "AMDUSDT"]
EQ = {"NVDAUSDT", "TSLAUSDT", "AAPLUSDT", "MSTRUSDT", "COINUSDT", "AMDUSDT"}
CM = {"XAUUSDT", "XAGUSDT", "NATGASUSDT", "CLUSDT"}
RULES = {"15m": {"dip_stretch": (1, 1.0), "top_sweep": (1, 1.0), "up_rsi": (1, 1.0), "dn_breakdown": (1, 1.0),
                 "pump5": (1, 1.0), "dump5": (1, 1.0)},
         "1h": {"dip_stretch": (0, 1.0), "top_sweep": (1, 1.0), "up_ema20": (1, 1.0), "dn_rsi": (1, 1.0),
                "dn_ema20": (1, 1.0), "pump5": (0, 0.0), "dump3": (1, 1.0)},
         "4h": {"dip_sweep": (0, 1.0), "top_sweep": (1, 1.0), "up_breakout": (0, 1.0), "dn_breakdown": (0, 1.0),
                "dn_ema20": (0, 1.0), "pump5": (0, 1.0), "pump3": (0, 1.0), "dump3": (1, 1.0)}}
FEE = 0.10
base = json.load(open(S.CONFIG_PATH, encoding="utf-8"))
api = S.Binance()
now_ms = int(time.time() * 1000)
BARS = {"15m": 6000, "1h": 3000, "4h": 1500}
TFMS = {"15m": 900_000, "1h": 3_600_000, "4h": 14_400_000}


def kl(sym, tf, lim):
    return S.parse_klines(api.get("/fapi/v1/klines", {"symbol": sym, "interval": tf, "limit": lim}), now_ms)


def kl_many(sym, tf, total):
    out, end = [], None
    while len(out) < total:
        p = {"symbol": sym, "interval": tf, "limit": 1500}
        if end:
            p["endTime"] = end
        raw = api.get("/fapi/v1/klines", p)
        if not raw:
            break
        out = S.parse_klines(raw, now_ms) + out
        end = int(raw[0][0]) - 1
        if len(raw) < 1500:
            break
    seen, res = set(), []
    for x in out:
        if x["t"] not in seen:
            seen.add(x["t"]); res.append(x)
    return res[-total:]


def sim(f, i, d, entry, stop, tps, maxb=300):
    hit = 0
    pnl = 0.0
    risk = abs(entry - stop)
    n = len(f["c"])
    end = min(n - 1, i + maxb)
    for k in range(i + 1, end + 1):
        hi, lo = f["h"][k], f["l"][k]
        if (lo <= stop) if d == 1 else (hi >= stop):
            return pnl + (3 - hit) / 3 * -1.0, hit, k
        while hit < 3 and ((hi >= tps[hit]) if d == 1 else (lo <= tps[hit])):
            pnl += (hit + 1) / 3          # TP1=1R, TP2=2R, TP3=3R
            hit += 1
        if hit == 3:
            return pnl, hit, k
    if end <= i:
        return None
    return pnl + (3 - hit) / 3 * (f["c"][end] - entry) * d / risk, hit, end


def run(tf):
    cfg = S.apply_tf_profile(json.loads(json.dumps(base)), tf)
    cfg["timeframe"] = tf
    data = {}
    syms = SYMS + ["QQQUSDT"]
    with ThreadPoolExecutor(max_workers=6) as ex:
        for s, cs, c4 in ex.map(lambda s: (s, *fetch(s, tf)), syms):
            if cs:
                data[s] = (cs, c4)
    lead = {}
    for typ, ls in (("COIN", "BTCUSDT"), ("EQUITY", "QQQUSDT")):
        if ls in data:
            lf = S.compute_features(data[ls][0], cfg)
            lead[typ] = (ls, {lf["t"][j]: S.trend_bias(lf, j) for j in range(len(lf["t"])) if S.required_ready(lf, j)},
                         {lf["t"][j]: lf["c"][j] / lf["c"][j - 24] - 1 for j in range(24, len(lf["t"]))})
    out = []
    for sym in SYMS:
        if sym not in data:
            continue
        cs, c4 = data[sym]
        typ = "EQUITY" if sym in EQ else ("COMMODITY" if sym in CM else "COIN")
        meta = {"symbol": sym, "type": typ}
        f = S.compute_features(cs, cfg)
        n = len(f["c"])
        # ── Supertrend ──
        state = {"signals": {}}
        for i in range(300, n - 1):
            if f["st_dir"][i] is None or f["st_dir"][i - 1] is None or f["st_dir"][i] == f["st_dir"][i - 1]:
                continue
            if not S.required_ready(f, i):
                continue
            t_close = f["t"][i] + TFMS[tf]
            ld = lead.get(typ)
            lret = None
            if ld and ld[0] != sym and f["t"][i] in ld[1]:
                lb, ln = ld[1][f["t"][i]], ld[0].replace("USDT", "")
                lret = ld[2].get(f["t"][i])
            else:
                lb, ln = (f["h4_ema"][i] + f["h4_st"][i]) / 2, "4s trend"
            chg24 = S.pct(f["c"][i], f["c"][max(0, i - 24)])
            res = S.evaluate_at(meta, f, i, lb, ln, None, chg24, datetime.fromtimestamp(t_close / 1000, timezone.utc),
                                cfg, lret)
            dd = S.decide(res, cfg, state, t_close / 1000)
            if not dd:
                continue
            state["signals"][f"{sym}|{dd}"] = t_close / 1000
            s = 1 if dd == "long" else -1
            e, sl, tps, _ = S.levels(res, dd, cfg)
            r = sim(f, i, s, e, sl, tps)
            if r:
                out.append(("Supertrend", tf, r[0], r[1], abs(e - sl) / e * 100))
        # ── Nokta Atışı ──
        o, h, l, c, v = (f[k] for k in ("o", "h", "l", "c", "v"))
        x = N.features(o, h, l, c, v)
        t4 = [q["t"] for q in c4]
        busy = {1: -1, -1: -1}
        for i in range(260, n - 1):
            done = set()
            for sg in N.setups(o, h, l, c, v, i, x):
                rc = RULES[tf].get(sg["rule"])
                if not rc or sg["d"] in done or busy[sg["d"]] >= i:
                    continue
                if rc[0]:
                    tclose = f["t"][i] + TFMS[tf]
                    k4 = max((j for j in range(len(t4)) if t4[j] + 14_400_000 <= tclose), default=None)
                    htf = N.htf_trend(c4[:k4 + 1]) if k4 is not None else 0
                    if htf != sg["d"]:
                        continue
                lv = N.levels(c[i], sg["d"], sg["stop"], x["a"][i], rc[1])
                r = sim(f, i, sg["d"], lv["entry"], lv["stop"], lv["tp"])
                if r:
                    done.add(sg["d"])
                    busy[sg["d"]] = r[2]           # açık sinyal kapanana kadar aynı yönde yenisi yok
                    out.append(("Nokta Atışı", tf, r[0], r[1], lv["risk"] / c[i] * 100))
    return out


def fetch(s, tf):
    try:
        return kl_many(s, tf, BARS[tf]), kl(s, "4h", 1500)
    except Exception:  # noqa: BLE001
        return None, None


allr = []
for tf in ("15m", "1h", "4h"):
    allr += run(tf)
    print("XX| bitti", tf, len(allr))


def rep(label, rows):
    if not rows:
        print("XX|", label, "yok"); return
    n = len(rows)
    R = sum(x[2] for x in rows) / n
    net = sum(x[2] - FEE / x[4] for x in rows) / n
    pct = sum(x[2] * x[4] for x in rows) / n
    gp = sum(x[2] for x in rows if x[2] > 0); gl = -sum(x[2] for x in rows if x[2] < 0)
    tp1 = sum(1 for x in rows if x[3] >= 1) / n * 100
    tp3 = sum(1 for x in rows if x[3] == 3) / n * 100
    rk = sum(x[4] for x in rows) / n
    print("XX|", label, f"n={n} R={R:+.3f} netR={net:+.3f} ort%={pct:+.3f} PF={gp / gl if gl else 0:.2f} "
          f"TP1={tp1:.0f}% TP3={tp3:.0f}% stop%={rk:.2f}")


for sysn in ("Supertrend", "Nokta Atışı"):
    rep(sysn + " TUMU", [x for x in allr if x[0] == sysn])
    for tf in ("15m", "1h", "4h"):
        rep(f"{sysn} {tf}", [x for x in allr if x[0] == sysn and x[1] == tf])
