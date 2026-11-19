import base64, io, sys, time, datetime as dt
sys.path.insert(0, ".")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scanner import Binance, parse_klines
from indicators import atr, _pivots

SYMS = ["CRCLUSDT", "ETHUSDT", "SOLUSDT", "BTCUSDT", "PENDLEUSDT"]
TF = "15m"
MIN_SEP, PIV = 10, 3


def fit(close, a, A, n, tol_atr=0.25):
    pivs = [p for p in _pivots(close, PIV, PIV, "high") if p >= A + MIN_SEP and p < n - 1]
    for p in sorted(pivs, key=lambda k: (close[k] - close[A]) / (k - A), reverse=True):
        s = (close[p] - close[A]) / (p - A)
        if s >= 0:
            continue
        ln = lambda k, p=p, s=s: close[p] + s * (k - p)
        if any(close[k] > ln(k) + (a[k] or 0) * tol_atr for k in range(A + 1, p)):
            continue
        return p, ln
    return None


def anchors(close, a, n):
    lo = max(0, n - 200)
    out = {}
    out["A"] = max(range(lo, n - 1 - MIN_SEP), key=lambda k: close[k])
    j = None
    for k in range(n - 1 - 2 * MIN_SEP, lo + 12, -1):
        if a[k] and close[k - 12] - close[k] >= 3 * a[k]:
            j = k
            break
    out["B"] = max(range(j, n - 1 - MIN_SEP), key=lambda k: close[k]) if j else out["A"]
    out["C"] = max(range(n - 96, n - 1 - MIN_SEP), key=lambda k: close[k])
    return out


def ts(t):
    return dt.datetime.utcfromtimestamp(t / 1000 + 3 * 3600).strftime("%d.%m %H:%M")


api = Binance()
now = int(time.time() * 1000)
COL = {"A": "#f5c518", "B": "#00d1ff", "C": "#ff4fd8"}
NAME = {"A": "A · şimdiki (200 mumun en yükseği)", "B": "B · son sert düşüşten sonraki tepe", "C": "C · son 1 gün (96 mum)"}
for sym in SYMS:
    cs = parse_klines(api.get("/fapi/v1/klines", {"symbol": sym, "interval": TF, "limit": 300}), now)
    h = [x["h"] for x in cs]; l = [x["l"] for x in cs]; c = [x["c"] for x in cs]
    n = len(c)
    a = atr(h, l, c, 14)
    an = anchors(c, a, n)
    fig, ax = plt.subplots(figsize=(10, 5), dpi=100)
    fig.patch.set_facecolor("#131722"); ax.set_facecolor("#131722")
    start = max(0, n - 300)
    ax.plot(range(start, n), c[start:], color="#c9d1d9", linewidth=1.1)
    for key, A in an.items():
        r = fit(c, a, A, n)
        if not r:
            print(f"AN| {sym} {key} anchor {ts(cs[A]['t'])} {c[A]} -> çizgi yok")
            continue
        p, ln = r
        brk = next((k for k in range(p + 1, n) if c[k] > ln(k) + 0.1 * a[k]), None)
        print(f"AN| {sym} {key} 1.nokta {ts(cs[A]['t'])} {c[A]} 2.nokta {ts(cs[p]['t'])} {c[p]} "
              f"şimdi çizgi {ln(n-1):.4g} fiyat {c[-1]} kırılım {ts(cs[brk]['t']) if brk else 'yok'}")
        ax.plot([A, n + 3], [c[A], ln(n + 3)], color=COL[key], linewidth=1.6, label=NAME[key])
        ax.scatter([A, p], [c[A], c[p]], color=COL[key], s=30, zorder=5)
        if brk:
            ax.scatter([brk], [c[brk]], marker="^", color=COL[key], s=70, zorder=6)
    ticks = list(range(start, n, 48))
    ax.set_xticks(ticks); ax.set_xticklabels([ts(cs[k]["t"]) for k in ticks], color="#8b949e", fontsize=8)
    ax.tick_params(colors="#8b949e")
    for s in ax.spines.values():
        s.set_color("#30363d")
    ax.set_title(f"{sym} · 15dk · düşen çizgi: 3 seçenek (▲ = kırılım)", color="white")
    ax.legend(facecolor="#131722", labelcolor="white", fontsize=8, loc="lower left")
    buf = io.BytesIO(); fig.savefig(buf, format="png", facecolor=fig.get_facecolor()); plt.close(fig)
    print(f"IM| {sym} " + base64.b64encode(buf.getvalue()).decode())
