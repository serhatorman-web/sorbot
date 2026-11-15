"""Geçici test: SSL Hybrid Advanced Buy/Sell + baz çizgi rengi + DynaRange + QQE MOD teyidi."""
import os, sys, time, math
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as sc
import indicators as ta
from backtest import simulate

TFS = {"15m": (3000, 96), "1h": (2000, 72), "4h": (1000, 42)}
WAIT = 5
api = sc.Binance()
now_ms = int(time.time() * 1000)


def wma(v, n):
    out = [None] * len(v); w = n * (n + 1) / 2
    for i in range(n - 1, len(v)):
        seg = v[i - n + 1:i + 1]
        if any(x is None for x in seg): continue
        out[i] = sum(x * (k + 1) for k, x in enumerate(seg)) / w
    return out


def hma(v, n):
    a, b = wma(v, n // 2), wma(v, n)
    d = [None if x is None or y is None else 2 * x - y for x, y in zip(a, b)]
    return wma(d, round(math.sqrt(n)))


def pine_ema(v, n):
    """TradingView ta.ema: ilk değerden başlar."""
    out = [None] * len(v); k = 2 / (n + 1); prev = None
    for i, x in enumerate(v):
        if x is None:
            out[i] = prev; continue
        prev = x if prev is None else x * k + prev * (1 - k)
        out[i] = prev
    return out


def qqe_tl(rsima, factor):
    n = len(rsima)
    atr_r = [None] + [None if rsima[i] is None or rsima[i - 1] is None else abs(rsima[i - 1] - rsima[i]) for i in range(1, n)]
    dar = [None if x is None else x * factor for x in pine_ema(pine_ema(atr_r, 11), 11)]
    lb = sb = 0.0; tr = 1; tl = [None] * n; plb = psb = 0.0; pplb = ppsb = 0.0
    for i in range(n):
        r = rsima[i]
        if r is None or dar[i] is None: continue
        rp = rsima[i - 1] if i and rsima[i - 1] is not None else r
        nlb, nsb = r - dar[i], r + dar[i]
        lb = max(plb, nlb) if (rp > plb and r > plb) else nlb
        sb = min(psb, nsb) if (rp < psb and r < psb) else nsb
        d0, d1 = r - psb, rp - ppsb                       # cross(RSIndex, shortband[1])
        e0, e1 = plb - r, pplb - rp                       # cross(longband[1], RSIndex)
        if (d0 > 0) != (d1 > 0) and d0 != d1:
            tr = 1
        elif (e0 > 0) != (e1 > 0) and e0 != e1:
            tr = -1
        tl[i] = lb if tr == 1 else sb
        pplb, ppsb = plb, psb
        plb, psb = lb, sb
    return tl


def features(cs):
    o = [c["o"] for c in cs]; h = [c["h"] for c in cs]; l = [c["l"] for c in cs]; c = [x["c"] for x in cs]
    n = len(c)
    eh, el = hma(h, 15), hma(l, 15)
    ssl = [None] * n; hl = 0
    for i in range(n):
        if eh[i] is None: continue
        hl = 1 if c[i] > eh[i] else (-1 if c[i] < el[i] else hl)
        ssl[i] = eh[i] if hl < 0 else el[i]
    base = hma(c, 55)
    rng = pine_ema(ta.true_range(h, l, c), 55)
    up = [None if b is None else b + 0.2 * r for b, r in zip(base, rng)]
    lo = [None if b is None else b - 0.2 * r for b, r in zip(base, rng)]
    rsima = pine_ema(ta.rsi(c, 6), 5)
    tl = qqe_tl(rsima, 3.0)
    x = [None if t is None else t - 50 for t in tl]
    bas, sd = ta.sma(x, 50), ta.stdev(x, 50)
    qqe = [0] * n
    for i in range(n):
        if rsima[i] is None or bas[i] is None: continue
        v = rsima[i] - 50
        if v > 3 and v > bas[i] + 0.35 * sd[i]: qqe[i] = 1
        elif v < -3 and v < bas[i] - 0.35 * sd[i]: qqe[i] = -1
    dyn = ta.dynarange(o, h, l, c)
    st, _ = ta.supertrend(h, l, c, 10, 3.0)
    return {"o": o, "h": h, "l": l, "c": c, "ssl": ssl, "up": up, "lo": lo, "qqe": qqe, "dyn": dyn, "st": st,
            "atr": ta.atr(h, l, c, 14)}


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
    try:
        cs = hist(sym, tf, bars)
    except Exception:  # noqa: BLE001
        return []
    if len(cs) < 400: return []
    f = features(cs); c = f["c"]; out = []
    last = {1: -999, -1: -999}
    for i in range(300, len(c) - 1):
        a = f["atr"][i]
        if not a or f["ssl"][i] is None or f["ssl"][i - 1] is None or f["up"][i] is None: continue
        for s in (1, -1):
            # SSL Buy/Sell olayı
            if (s == 1 and c[i] > f["ssl"][i] and c[i - 1] <= f["ssl"][i - 1]) or \
               (s == -1 and c[i] < f["ssl"][i] and c[i - 1] >= f["ssl"][i - 1]):
                last[s] = i
                r = simulate(f, i, s, 1.5 * a, hold)
                if r: out.append({"k": "A", "tf": tf, "s": s, "R": r["R"] - 0.10 / r["risk_pct"], "t": cs[i]["t"]})
            ev = last[s]
            if i - ev > WAIT or ev < 0: continue
            side = (c[i] > f["up"][i]) if s == 1 else (c[i] < f["lo"][i])
            dyn = f["dyn"][i] is not None and f["dyn"][i] * s > 0
            ok = side and f["qqe"][i] == s and dyn and (c[i] - f["ssl"][i]) * s > 0
            if ok:
                last[s] = -999                               # olay başına tek sinyal
                r = simulate(f, i, s, 1.5 * a, hold)
                if not r: continue
                net = r["R"] - 0.10 / r["risk_pct"]
                st_with = f["st"][i] == s
                out.append({"k": "C", "tf": tf, "s": s, "R": net, "t": cs[i]["t"], "st": st_with})
            elif i == ev and side:
                pass
        # B: SSL olayı + baz çizgi doğru tarafta (teyitsiz)
    return out


def stats(tr):
    if not tr: return None
    W = sum(x["R"] for x in tr if x["R"] > 0); L = -sum(x["R"] for x in tr if x["R"] < 0)
    return len(tr), sum(x["R"] > 0 for x in tr) / len(tr) * 100, sum(x["R"] for x in tr) / len(tr), (W / L if L else 9)


def row(name, tr):
    s = stats(tr)
    if not s: return f"| {name} | 0 | | | | |"
    ts = sorted(x["t"] for x in tr); mid = ts[len(ts) // 2]
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
lines = ["| Grup | Sinyal | Kazanan % | Ort. R | PF | PF 1.yarı / 2.yarı |", "|---|---|---|---|---|---|"]
for tf in list(TFS) + ["Hepsi"]:
    g = [x for x in allt if tf == "Hepsi" or x["tf"] == tf]
    lines.append(f"| **{tf}** | | | | | |")
    lines.append(row("SSL Buy/Sell tek başına", [x for x in g if x["k"] == "A"]))
    C = [x for x in g if x["k"] == "C"]
    lines.append(row("SSL + baz çizgi + DynaRange + QQE", C))
    lines.append(row("  LONG", [x for x in C if x["s"] == 1]))
    lines.append(row("  SHORT", [x for x in C if x["s"] == -1]))
    lines.append(row("  Supertrend aynı yönde", [x for x in C if x["st"]]))
    lines.append(row("  Supertrend ters yönde", [x for x in C if not x["st"]]))
for l_ in lines: print("OUT " + l_)
