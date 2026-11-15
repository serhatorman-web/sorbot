"""Geçici test: Supertrend dönüşünde SSL onayı yoksa, onay kaç mum sonra geliyor ve o anda girilen işlem nasıl sonuçlanıyor."""
import os, sys, time, json
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as sc
from backtest import simulate

TFS = {"15m": (3000, 96), "1h": (2000, 72), "4h": (1000, 42)}
MAXD = 20
api = sc.Binance()
now_ms = int(time.time() * 1000)
BASE = json.load(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json")))


def hist(sym, tf, bars):
    out, end = [], None
    while len(out) < bars:
        p = {"symbol": sym, "interval": tf, "limit": 1000}
        if end: p["endTime"] = end
        raw = api.get("/fapi/v1/klines", p)
        if not raw: break
        out = sc.parse_klines(raw, now_ms) + out
        end = int(raw[0][0]) - 1
        if len(raw) < 1000: break
    d = {c["t"]: c for c in out}
    return [d[k] for k in sorted(d)]


def ok(f, k, s):
    return (f["ssl"][k] is not None and (f["c"][k] - f["ssl"][k]) * s > 0 and f["qqe"][k] == s
            and f["dyna"][k] is not None and f["dyna"][k] * s > 0)


def run(args):
    sym, tf = args
    bars, hold = TFS[tf]
    cfg = sc.apply_tf_profile(BASE, tf); cfg["timeframe"] = tf
    try:
        cs = hist(sym, tf, bars)
        if len(cs) < 400: return []
        f = sc.compute_features(cs, cfg)
    except Exception:  # noqa: BLE001
        return []
    out, n, st = [], len(f["c"]), f["st_dir"]
    for i in range(300, n - MAXD - 2):
        a = f["atr"][i]
        if not a: continue
        for s in (1, -1):
            if not (st[i] == s and st[i - 1] == -s): continue
            r0 = simulate(f, i, s, 1.5 * a, hold)
            if not r0: continue
            base = r0["R"] - 0.10 / r0["risk_pct"]
            if ok(f, i, s):
                out.append({"tf": tf, "g": "0", "R": base, "t": cs[i]["t"]}); continue
            sl = f["c"][i] - s * 1.5 * a
            d = None
            for k in range(i + 1, i + MAXD + 1):
                if st[k] != s or (f["l"][k] <= sl if s == 1 else f["h"][k] >= sl):
                    break
                if ok(f, k, s):
                    d = k; break
            if d is None:
                out.append({"tf": tf, "g": "yok", "R": base, "t": cs[i]["t"]}); continue
            ak = f["atr"][d] or a
            r = simulate(f, d, s, 1.5 * ak, hold)
            if not r: continue
            out.append({"tf": tf, "g": "gec", "d": d - i, "R": r["R"] - 0.10 / r["risk_pct"], "R0": base, "t": cs[i]["t"]})
    return out


def stats(tr, key="R"):
    if not tr: return None
    W = sum(x[key] for x in tr if x[key] > 0); L = -sum(x[key] for x in tr if x[key] < 0)
    return len(tr), sum(x[key] > 0 for x in tr) / len(tr) * 100, sum(x[key] for x in tr) / len(tr), (W / L if L else 9)


def row(name, tr, mid, key="R"):
    s = stats(tr, key)
    if not s: return f"| {name} | 0 | | | | |"
    a = stats([x for x in tr if x["t"] < mid], key); b = stats([x for x in tr if x["t"] >= mid], key)
    return f"| {name} | {s[0]} | {s[1]:.0f} | {s[2]:+.3f} | {s[3]:.2f} | {a[3] if a else 0:.2f} / {b[3] if b else 0:.2f} |"


info = api.get("/fapi/v1/exchangeInfo")
tick = {t["symbol"]: float(t["quoteVolume"]) for t in api.get("/fapi/v1/ticker/24hr")}
syms = [s["symbol"] for s in info["symbols"] if s.get("quoteAsset") == "USDT" and s.get("status") == "TRADING"
        and s.get("contractType") == "PERPETUAL" and s.get("underlyingType") == "COIN" and tick.get(s["symbol"], 0) >= 3e6]
print(len(syms), "coin", flush=True)
allt = []
with ThreadPoolExecutor(6) as ex:
    for r in ex.map(run, [(s, tf) for tf in TFS for s in syms]):
        allt += r
B = [(1, 2), (3, 5), (6, 10), (11, 20)]
lines = ["| Grup | Sinyal | Kazanan % | Ort. R | PF | PF 1.yarı / 2.yarı |", "|---|---|---|---|---|---|"]
for tf in list(TFS) + ["Hepsi"]:
    g = [x for x in allt if tf == "Hepsi" or x["tf"] == tf]
    if not g: continue
    ts = sorted(x["t"] for x in g); mid = ts[len(ts) // 2]
    G = [x for x in g if x["g"] == "gec"]
    lines.append(f"| **{tf}** | | | | | |")
    lines.append(row("Tüm Supertrend sinyalleri (girişte)", g, mid))
    lines.append(row("SSL sinyal anında onaylıyor", [x for x in g if x["g"] == "0"], mid))
    lines.append(row("Bekle dedi, onay hiç gelmedi (sinyalde girilseydi)", [x for x in g if x["g"] == "yok"], mid))
    lines.append(row("Bekle dedi, onay sonradan geldi – sinyalde girilseydi", G, mid, "R0"))
    for lo, hi in B:
        lines.append(row(f"  onay {lo}-{hi} mum sonra geldi, o anda girildi", [x for x in G if lo <= x["d"] <= hi], mid))
    for m in (3, 5, 10, 20):
        lines.append(row(f"  takip süresi {m} mum (onay gelince giriş)", [x for x in G if x["d"] <= m], mid))
for l_ in lines: print("OUT " + l_)
