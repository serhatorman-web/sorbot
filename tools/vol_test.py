"""Geçici test: Supertrend (10,3) dönüş sinyallerinin sonucu, sinyal anındaki 24s USDT hacmine göre gruplanır.
Çıkış: her TP'de 1/3, TP1 sonrası stop girişe, stop 1.5 ATR, TP 1/2/3R, %0.1 maliyet."""
import os, sys
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as sc
import indicators as ta
from backtest import simulate

TFS = {"15m": (3000, 96), "1h": (2000, 72), "4h": (1000, 42)}   # mum sayısı, en uzun tutma
BUCKETS = [(0, 3e6, "<3M"), (3e6, 5e6, "3–5M"), (5e6, 10e6, "5–10M"), (10e6, 50e6, "10–50M"), (50e6, 1e18, "≥50M")]
CUM = [(3e6, "≥3M (şu an)"), (5e6, "≥5M"), (10e6, "≥10M"), (20e6, "≥20M")]
FEE = 0.10
api = sc.Binance()
now_ms = int(__import__("time").time() * 1000)


def hist(sym, tf, bars):
    out, end = [], None
    while len(out) < bars:
        p = {"symbol": sym, "interval": tf, "limit": 1000}
        if end:
            p["endTime"] = end
        raw = api.get("/fapi/v1/klines", p)
        if not raw:
            break
        out = sc.parse_klines(raw, now_ms) + out
        end = int(raw[0][0]) - 1
        if len(raw) < 1000:
            break
    seen, u = set(), []
    for c in sorted(out, key=lambda x: x["t"]):
        if c["t"] not in seen:
            seen.add(c["t"]); u.append(c)
    return u


def run(sym, tf):
    bars, hold = TFS[tf]
    try:
        cs = hist(sym, tf, bars)
    except Exception as e:  # noqa: BLE001
        return []
    if len(cs) < 300:
        return []
    h = [c["h"] for c in cs]; l = [c["l"] for c in cs]; c = [c_["c"] for c_ in cs]; v = [c_["v"] for c_ in cs]
    st, _ = ta.supertrend(h, l, c, 10, 3.0)
    atr = ta.atr(h, l, c, 14)
    f = {"h": h, "l": l, "c": c}
    bpd = {"15m": 96, "1h": 24, "4h": 6}[tf]
    out = []
    for i in range(250, len(c) - 1):
        if not st[i] or not st[i - 1] or st[i] == st[i - 1] or not atr[i]:
            continue
        s = st[i]
        qv = sum(v[i - bpd + 1:i + 1])
        r = simulate(f, i, s, 1.5 * atr[i], hold)
        if not r:
            continue
        net = r["R"] - FEE / r["risk_pct"]
        out.append({"tf": tf, "qv": qv, "R": net, "tp1": r["tp"][0], "t": cs[i]["t"], "sym": sym})
    return out


def stats(tr):
    if not tr:
        return "–"
    n = len(tr)
    w = sum(x["R"] for x in tr if x["R"] > 0); lo = -sum(x["R"] for x in tr if x["R"] < 0)
    pf = w / lo if lo else float("inf")
    tp1 = sum(x["tp1"] for x in tr) / n * 100
    return n, tp1, sum(x["R"] for x in tr) / n, pf


def halves(tr, t_mid):
    a = stats([x for x in tr if x["t"] < t_mid]); b = stats([x for x in tr if x["t"] >= t_mid])
    f = lambda s: "–" if s == "–" else f"{s[3]:.2f}"
    return f"{f(a)} / {f(b)}"


def table(title, tr, out):
    if not tr:
        return
    ts = sorted(x["t"] for x in tr); t_mid = ts[len(ts) // 2]
    out.append(f"\n### {title}\n")
    out.append("| Hacim (24s, sinyal anı) | Sinyal | TP1 % | Ort. R | PF | PF 1.yarı / 2.yarı |")
    out.append("|---|---|---|---|---|---|")
    for lo_, hi_, name in BUCKETS:
        g = [x for x in tr if lo_ <= x["qv"] < hi_]
        s = stats(g)
        if s != "–":
            out.append(f"| {name} | {s[0]} | {s[1]:.0f} | {s[2]:+.3f} | {s[3]:.2f} | {halves(g, t_mid)} |")
    out.append("| **Eşik** | | | | | |")
    for th, name in CUM:
        g = [x for x in tr if x["qv"] >= th]
        s = stats(g)
        if s != "–":
            out.append(f"| {name} | {s[0]} | {s[1]:.0f} | {s[2]:+.3f} | {s[3]:.2f} | {halves(g, t_mid)} |")


def main():
    info = api.get("/fapi/v1/exchangeInfo")
    tick = {t["symbol"]: float(t["quoteVolume"]) for t in api.get("/fapi/v1/ticker/24hr")}
    syms = [s["symbol"] for s in info["symbols"] if s.get("quoteAsset") == "USDT" and s.get("status") == "TRADING"
            and s.get("contractType") == "PERPETUAL" and s.get("underlyingType") == "COIN"
            and tick.get(s["symbol"], 0) >= 1e6]
    print(f"{len(syms)} coin (şu an 24s hacim ≥1M)")
    allt = []
    for tf in TFS:
        with ThreadPoolExecutor(6) as ex:
            for r in ex.map(lambda s: run(s, tf), syms):
                allt += r
        print(tf, "bitti", sum(1 for x in allt if x["tf"] == tf), "sinyal", flush=True)
    out = [f"## Hacim eşiği testi – Supertrend sinyalleri ({len(syms)} coin)"]
    for tf in TFS:
        table(tf, [x for x in allt if x["tf"] == tf], out)
    table("Hepsi (15m + 1h + 4h)", allt, out)
    txt = "\n".join(out)
    print(txt)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        open(os.environ["GITHUB_STEP_SUMMARY"], "a").write(txt + "\n")


main()
