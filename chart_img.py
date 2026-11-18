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
    rt = ciz.get("retest")
    if rt is not None and start <= rt < end:
        y = cs[rt]["l"] if d == 1 else cs[rt]["h"]
        ax.plot(rt, y, "o", markersize=11, markerfacecolor="none", markeredgecolor=TARGET, markeredgewidth=1.6, zorder=6)
        ax.annotate("Retest", xy=(rt, y), xytext=(rt + 3, y + (-1 if d == 1 else 1) * (
            max(x["h"] for x in cs[start:end]) - min(x["l"] for x in cs[start:end])) * 0.12),
            color=TARGET, fontsize=9, arrowprops=dict(arrowstyle="->", color=TARGET), zorder=6)
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


def render_divergence(cs, rsi, pts, bullish, title, prec=None):
    """RSI uyumsuzluğu: üstte mumlar ve iki fiyat dibi/tepesi arasında çizgi, altta RSI ve aynı iki noktanın çizgisi."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:  # noqa: BLE001
        return None
    p1, p2 = pts
    n = len(cs)
    start = max(0, min(p1 - 25, n - 90))
    end = n
    xs = range(start, end)
    col = UP if bullish else DOWN
    fig, (ax, ar) = plt.subplots(2, 1, figsize=(9, 6), dpi=110, sharex=True,
                                 gridspec_kw={"height_ratios": [3, 1.5], "hspace": 0.05})
    fig.patch.set_facecolor(BG)
    for a_ in (ax, ar):
        a_.set_facecolor(BG)
        a_.grid(color=GRID, linewidth=0.6)
        a_.yaxis.tick_right()
        a_.tick_params(axis="y", colors=TXT, labelsize=8)
        for sp in a_.spines.values():
            sp.set_color(GRID)
    w = 0.6
    for k in xs:
        x = cs[k]
        cc = UP if x["c"] >= x["o"] else DOWN
        ax.vlines(k, x["l"], x["h"], color=cc, linewidth=0.8, zorder=2)
        lo, hi = sorted((x["o"], x["c"]))
        ax.add_patch(plt.Rectangle((k - w / 2, lo), w, max(hi - lo, 1e-12), color=cc, zorder=3))
    key = "l" if bullish else "h"
    y1, y2 = cs[p1][key], cs[p2][key]
    ax.plot([p1, p2], [y1, y2], color=col, linewidth=2, zorder=5)
    ax.plot([p1, p2], [y1, y2], "o", color=PIVOT, markeredgecolor=col, markersize=6, zorder=6)
    lows = [cs[k]["l"] for k in xs]
    highs = [cs[k]["h"] for k in xs]
    pad = (max(highs) - min(lows)) * 0.06
    ax.set_ylim(min(lows) - pad, max(highs) + pad)
    ax.text(p2 + 1, y2, (" Fiyat: daha düşük dip" if bullish else " Fiyat: daha yüksek tepe"), color=col, fontsize=9,
            va="top" if bullish else "bottom", zorder=7)
    rv = [rsi[k] if rsi[k] is not None else float("nan") for k in xs]
    ar.plot(list(xs), rv, color="#b39ddb", linewidth=1.2, zorder=3)
    for lvl in (30, 70):
        ar.axhline(lvl, color=GRID, linestyle="--", linewidth=0.9)
    ar.plot([p1, p2], [rsi[p1], rsi[p2]], color=col, linewidth=2, zorder=5)
    ar.plot([p1, p2], [rsi[p1], rsi[p2]], "o", color=PIVOT, markeredgecolor=col, markersize=6, zorder=6)
    ar.text(p2 + 1, rsi[p2], (" RSI: daha yüksek dip" if bullish else " RSI: daha düşük tepe"), color=col, fontsize=9,
            va="top" if bullish else "bottom", zorder=7)
    ar.set_ylim(min(15, min(v for v in rv if v == v) - 3), max(85, max(v for v in rv if v == v) + 3))
    ar.set_xlim(start - 1, end + int((end - start) * 0.22) + 4)
    ticks = list(range(start, end, max(1, (end - start) // 6)))
    ar.set_xticks(ticks)
    ar.set_xticklabels([datetime.fromtimestamp(cs[k]["t"] / 1000, TSI).strftime("%d.%m %H:%M") for k in ticks],
                       color=TXT, fontsize=8)
    ax.set_title(title, color=TXT, fontsize=11, loc="left")
    fig.subplots_adjust(left=0.03, right=0.92, top=0.93, bottom=0.07)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=BG)
    plt.close(fig)
    return buf.getvalue()
