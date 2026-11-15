"""Geçici test: botun ssl_signal kuralı (SSL Buy/Sell → QQE MOD → DynaRange) + indikatör oy filtresi."""
import os, sys, time, json
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as sc
from backtest import simulate

TFS = {"15m": (3000, 96), "1h": (2000, 72), "4h": (1000, 42)}
VOTE_TH = [0, 11, 13, 15, 17]
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
    out = []
    n = len(f["c"])
    for i in range(300, n - 1):
        a = f["atr"][i]
        if not a: continue
        for s in (1, -1):
            kind = None
            if sc.ssl_signal(f, i, s) is not None:
                kind = "SSL"
            elif f["st_dir"][i] == s and f["st_dir"][i - 1] == -s:
                kind = "ST"
            if not kind: continue
            r = simulate(f, i, s, 1.5 * a, hold)
            if not r: continue
            try:
                v = sc.indicator_votes(f, i, 0, "4s trend", "supertrend")
                same = sum(1 for _, x in v if x == s)
            except Exception:  # noqa: BLE001
                same = 0
            out.append({"k": kind, "tf": tf, "s": s, "R": r["R"] - 0.10 / r["risk_pct"], "t": cs[i]["t"],
                        "st": f["st_dir"][i] == s, "v": same})
    return out


def stats(tr):
    if not tr: return None
    W = sum(x["R"] for x in tr if x["R"] > 0); L = -sum(x["R"] for x in tr if x["R"] < 0)
    return len(tr), sum(x["R"] > 0 for x in tr) / len(tr) * 100, sum(x["R"] for x in tr) / len(tr), (W / L if L else 9)


def row(name, tr, mid):
    s = stats(tr)
    if not s: return f"| {name} | 0 | | | | |"
    a = stats([x for x in tr if x["t"] < mid]); b = stats([x for x in tr if x["t"] >= mid])
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
print("toplam", len(allt), flush=True)
lines = ["| Grup | Sinyal | Kazanan % | Ort. R | PF | PF 1.yarı / 2.yarı |", "|---|---|---|---|---|---|"]
for tf in list(TFS) + ["Hepsi"]:
    g = [x for x in allt if tf == "Hepsi" or x["tf"] == tf]
    if not g: continue
    ts = sorted(x["t"] for x in g); mid = ts[len(ts) // 2]
    S = [x for x in g if x["k"] == "SSL"]
    lines.append(f"| **{tf}** | | | | | |")
    lines.append(row("Supertrend dönüşü (karşılaştırma)", [x for x in g if x["k"] == "ST"], mid))
    lines.append(row("SSL → QQE → DynaRange", S, mid))
    lines.append(row("  LONG", [x for x in S if x["s"] == 1], mid))
    lines.append(row("  SHORT", [x for x in S if x["s"] == -1], mid))
    lines.append(row("  Supertrend aynı yönde", [x for x in S if x["st"]], mid))
    lines.append(row("  Supertrend ters (henüz dönmedi)", [x for x in S if not x["st"]], mid))
    for th in VOTE_TH[1:]:
        lines.append(row(f"  + en az {th}/21 indikatör aynı yönde", [x for x in S if x["v"] >= th], mid))
for l_ in lines: print("OUT " + l_)
