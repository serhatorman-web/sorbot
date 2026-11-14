"""Geçici test: ERKEN DÖNÜŞ sinyali (kapitülasyon → dengelenme → tetik) vs Supertrend, geçmiş veride."""
import sys, os, json, time
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as sc
api = sc.Binance(); cfg0 = json.load(open("config.json"))
TFMS = {"15m": 900_000, "1h": 3_600_000, "4h": 14_400_000}
NBARS = {"15m": 2900, "1h": 1490, "4h": 1490}
MAXB = {"15m": 96, "1h": 72, "4h": 42}
COST = 0.0010      # gidiş-dönüş komisyon + kayma (%0.1)

tick = api.get("/fapi/v1/ticker/24hr")
info = {s["symbol"]: s for s in api.get("/fapi/v1/exchangeInfo")["symbols"]}
syms = [t["symbol"] for t in sorted(tick, key=lambda t: -float(t["quoteVolume"]))
        if t["symbol"] in info and info[t["symbol"]].get("underlyingType") == "COIN"
        and info[t["symbol"]].get("status") == "TRADING" and t["symbol"].endswith("USDT")
        and float(t["quoteVolume"]) >= 5e6][:120]

def fetch(sym, tf):
    out, end = [], None
    while len(out) < NBARS[tf]:
        p = {"symbol": sym, "interval": tf, "limit": 1500}
        if end: p["endTime"] = end
        raw = api.get("/fapi/v1/klines", p)
        if not raw: break
        out = raw + out
        end = int(raw[0][0]) - 1
        if len(raw) < 1500: break
    now = int(time.time() * 1000)
    seen, cs = set(), []
    for k in out:
        if int(k[0]) in seen or int(k[6]) >= now: continue
        seen.add(int(k[0]))
        cs.append({"t": int(k[0]), "o": float(k[1]), "h": float(k[2]), "l": float(k[3]), "c": float(k[4]),
                   "v": float(k[7]), "bv": float(k[5])})
    return cs[-NBARS[tf]:]

def outcome(f, i, s, entry, sl, tf):
    """1/3 TP1, 1/3 TP2, 1/3 TP3; TP1 sonrası stop girişe. Döner (R, best, status)."""
    risk = abs(entry - sl)
    if risk <= 0: return None
    tps = [entry + s * risk * r for r in (1, 2, 3)]
    best, stop = 0, sl
    n = len(f["c"])
    for k in range(i + 1, min(n, i + 1 + MAXB[tf])):
        h, l = f["h"][k], f["l"][k]
        hit = (l <= stop) if s == 1 else (h >= stop)
        reach = max([m for m, tp in enumerate(tps, 1) if ((h >= tp) if s == 1 else (l <= tp))], default=0)
        if hit:
            if best == 0: return -1 - COST * entry / risk, 0, "stop"
            return sum(range(1, best + 1)) / 3 - COST * entry / risk, best, "tp"
        if reach > best:
            best = reach; stop = entry
            if best == 3: return 2.0 - COST * entry / risk, 3, "tp"
    end = min(n - 1, i + MAXB[tf])
    if end <= i: return None
    if end < i + MAXB[tf] and best < 3 and n - 1 - i < MAXB[tf]:
        return None   # henüz sonuçlanmadı
    open_r = (f["c"][end] - entry) * s / risk if best == 0 else 0
    return sum(range(1, best + 1)) / 3 + (open_r / 3 * (3 - best) if best == 0 else 0) - COST * entry / risk, best, "timeout"

def early_signals(f, W=8, body_atr=1.5, vol_x=2.0, rsi_th=30, need_bb=False):
    out = []
    n = len(f["c"]); used = set()
    for i in range(60, n):
        for s in (1, -1):
            # kapitülasyon mumu
            cap = None
            for k in range(i - 1, max(0, i - W) - 1, -1):
                a, vm = f["atr"][k], f["vol_ma"][k]
                if not a or not vm: continue
                body = (f["o"][k] - f["c"][k]) * s
                rng = f["h"][k] - f["l"][k]
                if (body >= body_atr * a or (body > 0 and rng >= 2 * body_atr * a)) and f["v"][k] >= vol_x * vm:
                    cap = k; break
            if cap is None: continue
            seg = range(cap, i)
            j = min(seg, key=lambda k: f["l"][k]) if s == 1 else max(seg, key=lambda k: f["h"][k])
            if (s, j) in used: continue
            after = list(range(j + 1, i))
            if len(after) < 1: continue
            ext = f["l"][j] if s == 1 else f["h"][j]
            if any((f["l"][k] <= ext) if s == 1 else (f["h"][k] >= ext) for k in after + [i]): continue
            if rsi_th is not None:
                rs = [f["rsi"][k] for k in range(cap, i + 1) if f["rsi"][k] is not None]
                if not rs or ((min(rs) > rsi_th) if s == 1 else (max(rs) < 100 - rsi_th)): continue
            if need_bb:
                b = f["bb_lo"][j] if s == 1 else f["bb_up"][j]
                if b is None or ((ext > b) if s == 1 else (ext < b)): continue
            top = max(f["h"][k] for k in after) if s == 1 else min(f["l"][k] for k in after)
            if not (((f["c"][i] > top) if s == 1 else (f["c"][i] < top)) and (f["c"][i] - f["o"][i]) * s > 0): continue
            used.add((s, j))
            a = f["atr"][i]
            out.append((i, s, f["c"][i], ext - s * 0.2 * a))
    return out

def st_signals(f):
    out = []
    for i in range(60, len(f["c"])):
        d, p = f["st_dir"][i], f["st_dir"][i - 1]
        if d and p and d != p:
            out.append((i, d, f["c"][i], f["c"][i] - d * 1.5 * f["atr"][i]))
    return out

VARIANTS = {"temel (gövde 1.5 ATR, hacim 2x, RSI≤30)": {},
            "RSI şartı yok": {"rsi_th": None},
            "hacim 1.5x": {"vol_x": 1.5},
            "+ alt Bollinger dışında dip": {"need_bb": True},
            "sıkı (gövde 2 ATR, hacim 3x, RSI≤25)": {"body_atr": 2.0, "vol_x": 3.0, "rsi_th": 25},
            "orta (gövde 2 ATR, hacim 2x, RSI≤30)": {"body_atr": 2.0, "vol_x": 2.0, "rsi_th": 30}}

def stats(rs):
    rs = [r for r in rs if r]
    if not rs: return "0 sinyal"
    n = len(rs); tp1 = sum(1 for r in rs if r[1] >= 1); stop = sum(1 for r in rs if r[2] == "stop")
    win = sum(r[0] for r in rs if r[0] > 0); loss = -sum(r[0] for r in rs if r[0] < 0)
    pf = win / loss if loss else float("inf")
    return f"{n:4} sinyal · TP1 %{tp1*100/n:4.1f} · Stop %{stop*100/n:4.1f} · ort {sum(r[0] for r in rs)/n:+.2f}R · PF {pf:.2f} · toplam {sum(r[0] for r in rs):+.0f}R"

for tf in ("4h",):
    cfg = dict(cfg0, timeframe=tf)
    with ThreadPoolExecutor(6) as ex:
        data = dict(zip(syms, ex.map(lambda s: fetch(s, tf), syms)))
    feats = {s: sc.compute_features(cs, cfg) for s, cs in data.items() if len(cs) > 300}
    days = NBARS[tf] * TFMS[tf] / 86400000
    print(f"\n===== {tf} · {len(feats)} coin · ~{days:.0f} gün =====")
    st_res = []; st_idx = {}
    for s, f in feats.items():
        sg = st_signals(f); st_idx[s] = sg
        st_res += [outcome(f, i, d, e, sl, tf) for i, d, e, sl in sg]
    print(f"{'Supertrend (şimdiki)':42} {stats(st_res)}")
    for name, kw in VARIANTS.items():
        res_all, adv = [], []
        res_dir = {1: [], -1: []}
        for s, f in feats.items():
            for i, d, e, sl in early_signals(f, **kw):
                o = outcome(f, i, d, e, sl, tf)
                res_all.append(o); res_dir[d].append(o)
                nxt = [x for x in st_idx[s] if x[1] == d and i <= x[0] <= i + 40]
                if nxt: adv.append((nxt[0][2] - e) / e * d * 100)
        print(f"{name:42} {stats(res_all)}")
        print(f"{'   LONG':42} {stats(res_dir[1])}")
        print(f"{'   SHORT':42} {stats(res_dir[-1])}")
        if adv:
            adv.sort()
            print(f"{'   Supertrend girişine göre avantaj':42} ort %{sum(adv)/len(adv):+.2f} · medyan %{adv[len(adv)//2]:+.2f} ({len(adv)} sinyalde ST sonra aynı yöne döndü)")
    sys.stdout.flush()
