"""Kırılan grafik formasyonunun resmi (Telegram'a sinyalle birlikte gönderilir).

render_pattern(cs, g, title, prec) -> PNG bytes (matplotlib yoksa None)
cs: kapanmış mumlar [{"t","o","h","l","c"}], g: patterns.chart_patterns sonucu (ciz bilgisiyle)
"""
import io
from datetime import datetime, timedelta, timezone

TSI = timezone(timedelta(hours=3))
BG, GRID, TXT = "#131722", "#2a2e39", "#d1d4dc"
UP, DOWN = "#26a69a", "#ef5350"
LINE, TARGET, PIVOT = "#f5c542", "#42a5f5", "#ffffff"


def _fmt(p, prec):
    if prec is not None:
        return f"{p:,.{max(2, min(prec, 8))}f}"
    return f"{p:,.4f}" if p < 1000 else f"{p:,.2f}"


def render_pattern(cs, g, title, prec=None, tf_ms=None):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:  # noqa: BLE001
        return None
    ciz = g.get("ciz") or {}
    n = len(cs)
    idx = [k for (k, _) in ciz.get("noktalar", [])] + [k for seg in ciz.get("cizgiler", []) for (k, _) in seg]
    start = max(0, min(idx + [n - 60]) - 12)
    start = max(start, n - 160)
    end = n                                   # son kapanmış muma kadar
    xs = range(start, end)
    fig, ax = plt.subplots(figsize=(9, 4.8), dpi=110)
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)
    w = 0.6
    for k in xs:
        x = cs[k]
        col = UP if x["c"] >= x["o"] else DOWN
        ax.vlines(k, x["l"], x["h"], color=col, linewidth=0.8, zorder=2)
        lo, hi = sorted((x["o"], x["c"]))
        ax.add_patch(plt.Rectangle((k - w / 2, lo), w, max(hi - lo, 1e-12), color=col, zorder=3))
    # formasyon çizgileri
    for (k1, p1), (k2, p2) in ciz.get("cizgiler", []):
        m = (p2 - p1) / (k2 - k1) if k2 != k1 else 0.0
        a0 = max(k1, start)
        ext = 3 if k2 >= n - 1 else 0             # sona kadar uzanan çizgiler biraz ileri uzatılır (direk uzatılmaz)
        ax.plot([a0, k2 + ext], [p1 + m * (a0 - k1), p2 + m * ext], color=LINE, linewidth=1.6, zorder=4)
    for k, p in ciz.get("noktalar", []):
        if k >= start:
            ax.plot(k, p, "o", color=PIVOT, markersize=5, markeredgecolor=LINE, zorder=5)
    # kırılım ve hedef
    d = g.get("kirilim", 0)
    kb = ciz.get("kb")
    lvl = g.get("seviye", g.get("ust") if d == 1 else g.get("alt"))
    if kb is not None and kb >= start:
        rng = max(x["h"] for x in cs[start:end]) - min(x["l"] for x in cs[start:end])
        col = UP if d == 1 else DOWN
        y = cs[kb]["c"]
        ax.annotate("Kırılım", xy=(kb, y), xytext=(kb - 6, y + (0.18 if d == 1 else -0.18) * rng),
                    color=col, fontsize=9, ha="center", arrowprops=dict(arrowstyle="->", color=col), zorder=6)
    tgt = g.get("hedef")
    if tgt is not None:
        ax.axhline(tgt, color=TARGET, linestyle="--", linewidth=1.2, zorder=4)
        ax.text(end + 1, tgt, f" Hedef {_fmt(tgt, prec)}", color=TARGET, fontsize=9, va="center", zorder=7,
                bbox=dict(facecolor=BG, edgecolor="none", pad=1))
    if lvl is not None:
        ax.text(end + 1, lvl, f" Kırılım {_fmt(lvl, prec)}", color=LINE, fontsize=9, va="center", zorder=7,
                bbox=dict(facecolor=BG, edgecolor="none", pad=1))
    # eksenler
    lows = [cs[k]["l"] for k in xs] + ([tgt] if tgt is not None else [])
    highs = [cs[k]["h"] for k in xs] + ([tgt] if tgt is not None else [])
    pad = (max(highs) - min(lows)) * 0.06
    ax.set_ylim(min(lows) - pad, max(highs) + pad)
    ax.set_xlim(start - 1, end + int((end - start) * 0.22) + 4)
    ticks = list(range(start, end, max(1, (end - start) // 6)))
    ax.set_xticks(ticks)
    ax.set_xticklabels([datetime.fromtimestamp(cs[k]["t"] / 1000, TSI).strftime("%d.%m %H:%M") for k in ticks],
                       color=TXT, fontsize=8)
    ax.yaxis.tick_right()
    ax.tick_params(axis="y", colors=TXT, labelsize=8)
    ax.grid(color=GRID, linewidth=0.6)
    for sp in ax.spines.values():
        sp.set_color(GRID)
    ax.set_title(title, color=TXT, fontsize=11, loc="left")
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=BG)
    plt.close(fig)
    return buf.getvalue()
