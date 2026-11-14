"""Teşhis: botun trend çizgilerini grafik olarak çizer (PNG)."""
import os, sys, time
from datetime import datetime, timezone, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import scanner as sc, indicators as ta

api = sc.Binance(); now_ms = int(time.time() * 1000)
TR = timezone(timedelta(hours=3))
os.makedirs("out", exist_ok=True)
for sym, tf in [("BTCUSDT", "15m"), ("ETHUSDT", "1h"), ("XAUUSDT", "1h"), ("SOLUSDT", "4h")]:
    cs = sc.parse_klines(api.get("/fapi/v1/klines", {"symbol": sym, "interval": tf, "limit": 150}), now_ms)
    h = [x["h"] for x in cs]; l = [x["l"] for x in cs]; c = [x["c"] for x in cs]; o = [x["o"] for x in cs]
    ev = ta.trendline_break(h, l, c)
    fig, ax = plt.subplots(figsize=(13, 6))
    for k in range(len(c)):
        col = "#26a69a" if c[k] >= o[k] else "#ef5350"
        ax.plot([k, k], [l[k], h[k]], color=col, lw=0.8)
        ax.plot([k, k], [o[k], c[k]], color=col, lw=3)
    title = []
    for kind, src, color in (("rising", l, "green"), ("falling", h, "red")):
        piv = ta._pivots(src, 5, 5, "low" if kind == "rising" else "high")
        ax.scatter(piv, [src[p] for p in piv], color=color, s=18, zorder=3)
        if len(piv) >= 2:
            p1, p2 = piv[-2], piv[-1]
            ok = src[p2] > src[p1] if kind == "rising" else src[p2] < src[p1]
            slope = (src[p2] - src[p1]) / (p2 - p1)
            xs = [p1, len(c) - 1]
            ax.plot(xs, [src[p1] + slope * (x - p1) for x in xs], color=color, lw=1.5,
                    ls="-" if ok else ":", label=f"{'Yükselen' if kind=='rising' else 'Düşen'} çizgi" + ("" if ok else " (geçersiz)"))
    for e in ev:
        title.append(f"{'Yükselen' if e['type']=='rising' else 'Düşen'} kırıldı {e['bars_ago']} mum önce · retest: {e['retest']}")
    ax.set_title(f"{sym} {tf} · " + (" | ".join(title) or "kırılım yok"))
    ax.legend(loc="upper left"); ax.grid(alpha=0.2)
    fig.tight_layout(); fig.savefig(f"out/{sym}_{tf}.png", dpi=90)
    print(sym, tf, ev)
