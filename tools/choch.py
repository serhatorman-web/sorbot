"""Geçici test: erken dönüş sinyallerinde hangi ek kriterler sonucu iyileştiriyor?"""
import sys, os, json, time, itertools
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as sc, indicators as ta
api = sc.Binance(); cfg0 = json.load(open("config.json"))
TFMS = {"15m": 900_000, "1h": 3_600_000, "4h": 14_400_000}
NBARS = {"15m": 2900, "1h": 2900, "4h": 1490}
MAXB = {"15m": 96, "1h": 72, "4h": 42}
COST = 0.0010
ER = cfg0["early_reversal"]
tick = api.get("/fapi/v1/ticker/24hr")
info = {s["symbol"]: s for s in api.get("/fapi/v1/exchangeInfo")["symbols"]}
syms = [t["symbol"] for t in sorted(tick, key=lambda t: -float(t["quoteVolume"]))
        if t["symbol"] in info and info[t["symbol"]].get("underlyingType") == "COIN"
        and info[t["symbol"]].get("status") == "TRADING" and float(t["quoteVolume"]) >= 5e6][:150]
if "BTCUSDT" not in syms: syms.append("BTCUSDT")

def fetch(sym, tf):
    out, end = [], None
    while len(out) < NBARS[tf]:
        p = {"symbol": sym, "interval": tf, "limit": 1500}
        if end: p["endTime"] = end
        raw = api.get("/fapi/v1/klines", p)
        if not raw: break
        out = raw + out; end = int(raw[0][0]) - 1
        if len(raw) < 1500: break
    now = int(time.time() * 1000); seen = set(); cs = []
    for k in out:
        if int(k[0]) in seen or int(k[6]) >= now: continue
        seen.add(int(k[0]))
        cs.append({"t": int(k[0]), "o": float(k[1]), "h": float(k[2]), "l": float(k[3]), "c": float(k[4]),
                   "v": float(k[7]), "bv": float(k[5])})
    return cs[-NBARS[tf]:]

def outcome(f, i, s, entry, sl, tf):
    risk = abs(entry - sl)
    tps = [entry + s * risk * r for r in (1, 2, 3)]
    best, stop = 0, sl; n = len(f["c"])
    if n - 1 - i < MAXB[tf]: return None
    for k in range(i + 1, i + 1 + MAXB[tf]):
        h, l = f["h"][k], f["l"][k]
        hit = (l <= stop) if s == 1 else (h >= stop)
        reach = max([m for m, tp in enumerate(tps, 1) if ((h >= tp) if s == 1 else (l <= tp))], default=0)
        if hit:
            return (-1 if best == 0 else sum(range(1, best + 1)) / 3) - COST * entry / risk, best
        if reach > best:
            best = reach; stop = entry
            if best == 3: return 2.0 - COST * entry / risk, 3
    end = i + MAXB[tf]
    r = sum(range(1, best + 1)) / 3 if best else (f["c"][end] - entry) * s / risk
    return r - COST * entry / risk, best

def features(f, i, s, ev, btc):
    j, cap, ext = ev["ext_i"], ev["cap"], ev["ext"]
    a = f["atr"][i]; aj = f["atr"][j] or a
    F = {}
    # BTC (aynı zaman dilimi, aynı mum zamanı)
    if btc is not None:
        bi = btc["idx"].get(f["t"][i])
        if bi is not None and bi >= 3:
            F["btc_mom"] = (btc["c"][bi] - btc["c"][bi - 3]) * s > 0
            F["btc_st"] = btc["st_dir"][bi] == s
            F["btc_not_against"] = btc["st_dir"][bi] != -s or (btc["c"][bi] - btc["c"][bi - 3]) * s > 0
    # RSI uyumsuzluğu: önceki 40 mumdaki uç noktaya göre
    lo, hi = max(0, j - 40), max(0, cap - 1)
    if hi > lo:
        prev = min(range(lo, hi), key=lambda k: f["l"][k]) if s == 1 else max(range(lo, hi), key=lambda k: f["h"][k])
        pr, rj = f["rsi"][prev], min(x for x in f["rsi"][cap:i + 1] if x is not None) if s == 1 else max(x for x in f["rsi"][cap:i + 1] if x is not None)
        pe = f["l"][prev] if s == 1 else f["h"][prev]
        if pr is not None:
            F["rsi_div"] = (ext < pe and rj > pr) if s == 1 else (ext > pe and rj < pr)
    # Likidite süpürme: son 100 mumun ucunu geçti
    w = range(max(0, cap - 100), cap)
    if len(w) > 20:
        F["sweep"] = ext < min(f["l"][k] for k in w) if s == 1 else ext > max(f["h"][k] for k in w)
    # Bollinger dışı
    b = f["bb_lo"][j] if s == 1 else f["bb_up"][j]
    if b is not None: F["bb_out"] = ext < b if s == 1 else ext > b
    # Hacim profili seviyesine yakın (salınım penceresi, cap'e kadar)
    hh, ll, vv = f["h"][:cap + 1], f["l"][:cap + 1], f["bv"][:cap + 1]
    an = ta.swing_anchor(hh, ll, 300)
    vp = ta.volume_profile(hh[an:], ll[an:], vv[an:], 24, 0.7)
    if vp: F["vp_level"] = min(abs(ext - x) for x in vp) <= 0.5 * aj
    # İğne (dip/tepe mumunda uzun gölge)
    rng = f["h"][j] - f["l"][j]
    if rng > 0:
        F["wick"] = ((min(f["o"][j], f["c"][j]) - f["l"][j]) if s == 1 else (f["h"][j] - max(f["o"][j], f["c"][j]))) >= 0.5 * rng
    # Tetik mumu hacmi ortalamanın üstünde
    if f["vol_ma"][i]: F["trig_vol"] = f["v"][i] >= f["vol_ma"][i]
    # Aşırı uzama: dipte EMA20'den ≥3 ATR uzak
    if f["ema20"][j]: F["stretch"] = ((f["ema20"][j] - ext) if s == 1 else (ext - f["ema20"][j])) >= 3 * aj
    # Üst zaman dilimi (4x) trendi sinyal yönünde / ters değil
    F["htf_with"] = f["h4_st"][i] == s
    F["htf_not_against"] = f["h4_st"][i] != -s
    # Büyük resim: EMA200 tarafı
    if f["ema200"][i]: F["ema200_side"] = (f["c"][i] - f["ema200"][i]) * s > 0
    return F

def pf(rs):
    w = sum(r for r in rs if r > 0); l = -sum(r for r in rs if r < 0)
    return w / l if l else 99

def line(name, rs):
    if not rs: return f"{name:34} –"
    n = len(rs); tp1 = sum(1 for _, b in rs if b >= 1)
    R = [r for r, _ in rs]
    return f"{name:34} {n:4} · TP1 %{tp1*100/n:4.1f} · ort {sum(R)/n:+.2f}R · PF {pf(R):.2f}"

for tf in ("15m", "1h", "4h"):
    cfg = dict(cfg0, timeframe=tf)
    with ThreadPoolExecutor(6) as ex:
        data = dict(zip(syms, ex.map(lambda s: fetch(s, tf), syms)))
    feats = {s: sc.compute_features(cs, cfg) for s, cs in data.items() if len(cs) > 400}
    bf = feats.get("BTCUSDT"); btc = {"idx": {t: k for k, t in enumerate(bf["t"])}, "c": bf["c"], "st_dir": bf["st_dir"]} if bf else None
    print(f"\n========== {tf} · {len(feats)} coin · ~{NBARS[tf]*TFMS[tf]/86400000:.0f} gün ==========", flush=True)
    for d, s_ in (("long", 1), ("short", -1)):
        rule = ER["rules"][tf][d]
        rows = []
        for sym, f in feats.items():
            used = set()
            for i in range(300, len(f["c"]) - MAXB[tf]):
                ev = ta.early_reversal(f["o"][:i+1], f["h"][:i+1], f["l"][:i+1], f["c"][:i+1], f["v"][:i+1], f["atr"][:i+1],
                                       f["vol_ma"][:i+1], f["rsi"][:i+1], s_, ER["window"], rule["body_atr"], rule["vol_x"], rule["rsi_th"])
                if not ev or ev["ext_i"] in used: continue
                used.add(ev["ext_i"])
                a = f["atr"][i]
                if abs(f["c"][i] - ev["ext"]) + 0.2 * a > ER["max_risk_atr"] * a: continue
                o = outcome(f, i, s_, f["c"][i], ev["ext"] - s_ * 0.2 * a, tf)
                if o is None: continue
                bf_ = None if sym == "BTCUSDT" or btc is None else {"c": btc["c"][:btc["idx"].get(f["t"][i], -2) + 1], "st_dir": btc["st_dir"][:btc["idx"].get(f["t"][i], -2) + 1]}
                rows.append((o, sc.early_criteria(f, i, s_, ev, bf_ if bf_ and len(bf_["c"]) > 3 else None), f["t"][i]))
        REQ = cfg0["early_reversal"]["rules"][tf][d]["require"]
        rows.sort(key=lambda x: x[2]); half = rows[len(rows)//2][2] if rows else 0
        base = [x for x in rows if all(x[1].get(k) is True for k in REQ)]
        def show(nm, sel):
            h1 = [o for o, F, t in sel if t < half]; h2 = [o for o, F, t in sel if t >= half]
            ph = lambda xs: f"{pf([r for r, _ in xs]):.2f}" if xs else "–"
            print(line(nm, [o for o, _, _ in sel]) + f" · yarılar {ph(h1)}/{ph(h2)}")
        print(f"\n--- {tf} {d.upper()} · zorunlu: {' & '.join(REQ)} ---")
        show("TÜMÜ (filtresiz)", rows)
        show("Zorunlu teyitlerle (yeni)", base)
        show("  CHoCH tek başına ✓", [x for x in rows if x[1].get("pa_choch")])
        show("  CHoCH tek başına ✗", [x for x in rows if x[1].get("pa_choch") is False])
        show("  zorunlu + CHoCH", [x for x in base if x[1].get("pa_choch")])
        show("  zorunlu, CHoCH yok", [x for x in base if x[1].get("pa_choch") is False])
        sys.stdout.flush()
