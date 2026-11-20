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
MARK = "#ffffff"                                      # kırılım / retest / hedef / giriş-TP-stop (kullanıcı: beyaz)
MA_COLS = {"EMA50": "#2196f3", "EMA200": "#ffffff", "MA50": "#ffeb3b", "MA200": "#ff1744"}
PIV_COL = "#ff9800"                                  # pivot R/S seviyeleri (TradingView turuncu)


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
    pv = g.get("pivots")
    if pv:
        idx.append(max(0, pv["k0"] - 6))
    start = max(0, min(idx + [n - 60]) - 12)
    start = max(start, n - 300)                 # 1. temas noktası her zaman resimde görünsün
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
    # pivot seviyeleri (TradingView Pivots gibi: P beyaz, R/S turuncu, dönem başından itibaren)
    if pv:
        x0 = max(pv["k0"], start)
        for nm in ("R3", "R2", "R1", "P", "S1", "S2", "S3"):
            v = pv.get(nm)
            if v is None:
                continue
            colr = TXT if nm == "P" else PIV_COL
            ax.plot([x0, n + 2], [v, v], color=colr, linewidth=1.3 if nm == "P" else 1.0, zorder=3)
            ax.text(x0, v, f"{nm} ({_fmt(v, prec)}) ", color=colr, fontsize=8, va="center", ha="right", zorder=7,
                    clip_on=True, bbox=dict(facecolor=BG, edgecolor="none", pad=0.5, alpha=0.7))
    # arka planda pivot indikatörü (bilgi amaçlı): her dönemin P / R1-R3 / S1-S3 çizgileri, mumların arkasında
    bg = [sg for sg in (g.get("pivot_bg") or []) if sg["k1"] >= start]
    if g.get("pivot_current_only") and bg:     # sadece içinde bulunulan dönem (eski dönem çizgileri yok)
        bg = bg[-1:]
    x_full = end + int((end - start) * 0.22) + 4          # grafiğin sağ kenarı
    for j, sg in enumerate(bg):
        last = j == len(bg) - 1
        x0, x1 = max(sg["k0"], start), (x_full if last else sg["k1"] + 0.5)   # son dönem sağ kenara kadar
        if last and x0 - start < 12:
            # dönem resmin solundan başlıyorsa etiket yine çizginin başında, solunda dursun (kullanıcı isteği):
            # çizgi etiketin bittiği yerden başlar
            ax_px = ax.get_window_extent().width or 800
            bar_px = ax_px / max(1, x_full - start + 2)
            lab_w = max(len(f" {nm} ({_fmt(sg[nm], prec)}) ") for nm in ("R3", "R2", "R1", "P", "S1", "S2", "S3"))
            x0 = max(x0, start - 1 + lab_w * 7.5 * 0.62 * ax.figure.dpi / 72 / bar_px)
        for nm in ("R3", "R2", "R1", "P", "S1", "S2", "S3"):
            colr = PIVOT if nm == "P" else PIV_COL
            ax.plot([x0, x1], [sg[nm], sg[nm]], color=colr, linewidth=1.5 if nm == "P" else 1.2, alpha=0.95, zorder=1)
            if last:                             # etiketler (TradingView gibi) içinde bulunulan dönemin başında
                ax.text(x0, sg[nm], f" {nm} ({_fmt(sg[nm], prec)}) ", color=colr, fontsize=7.5,
                        va="center", ha="right", zorder=6, clip_on=True,
                        bbox=dict(facecolor=BG, edgecolor="none", pad=0.3, alpha=0.6))
    # hareketli ortalamalar: EMA50 mavi, EMA200 beyaz, MA50 sarı, MA200 kırmızı (kullanıcı isteği)
    mas = g.get("mas") or {}
    ma_leg = []
    for nm, colr in (("EMA50", MA_COLS["EMA50"]), ("EMA200", MA_COLS["EMA200"]), ("MA50", MA_COLS["MA50"]),
                     ("MA200", MA_COLS["MA200"])):
        ser = mas.get(nm)
        if not ser:
            continue
        pts = [(k, ser[k]) for k in range(start, end) if k < len(ser) and ser[k] is not None]
        if len(pts) < 2:
            continue
        ax.plot([p_[0] for p_ in pts], [p_[1] for p_ in pts], color=colr, linewidth=1.1, alpha=0.9, zorder=3.5)
        ma_leg.append((nm, colr))
    # Supertrend (10, 3): yükselişte yeşil çizgi mumların altında, düşüşte kırmızı çizgi üstünde + Buy / Sell
    stl = g.get("supertrend")
    if stl:
        line, dirs = stl
        rng_ = max(x["h"] for x in cs[start:end]) - min(x["l"] for x in cs[start:end])
        k = start
        while k < end:
            if line[k] is None or dirs[k] == 0:
                k += 1
                continue
            j2 = k
            while j2 + 1 < end and dirs[j2 + 1] == dirs[k] and line[j2 + 1] is not None:
                j2 += 1
            colr = UP if dirs[k] == 1 else DOWN
            xs_ = list(range(k, j2 + 1))
            ys_ = [line[q] for q in xs_]
            ax.plot(xs_, ys_, color=colr, linewidth=1.3, zorder=2)
            mid = [(cs[q]["h"] + cs[q]["l"]) / 2 for q in xs_]
            ax.fill_between(xs_, ys_, mid, color=colr, alpha=0.08, zorder=1)
            if k > start and dirs[k - 1] == -dirs[k]:        # yön değişimi
                y = line[k]
                ax.annotate("Buy" if dirs[k] == 1 else "Sell", xy=(k, y),
                            xytext=(k, y + (-0.07 if dirs[k] == 1 else 0.07) * rng_), color="white", fontsize=7,
                            ha="center", va="center", zorder=8,
                            bbox=dict(boxstyle="round,pad=0.25", facecolor=colr, edgecolor="none"))
            k = j2 + 1
    zz = [(k, p) for k, p in ciz.get("zigzag", []) if k >= start]
    if len(zz) >= 2:                              # ikili/üçlü tepe-dip, OBO/TOBO: tepeler ve diplerden geçen kırık çizgi
        ax.plot([k for k, _ in zz], [p for _, p in zz], color=LINE, linewidth=1.3, alpha=0.9, zorder=4)
    for k, p in ciz.get("noktalar", []):
        if k >= start:
            ax.plot(k, p, "o", color=PIVOT, markersize=5, markeredgecolor=LINE, zorder=5)
    # kırılım ve hedef
    d = g.get("kirilim", 0)
    kb = ciz.get("kb")
    lvl = g.get("seviye", g.get("ust") if d == 1 else g.get("alt"))
    if kb is not None and kb >= start:
        rng = max(x["h"] for x in cs[start:end]) - min(x["l"] for x in cs[start:end])
        col = MARK
        y = cs[kb]["c"]
        ax.annotate("Kırılım", xy=(kb, y), xytext=(kb - 12, y + (0.18 if d == 1 else -0.18) * rng),
                    color=col, fontsize=9, ha="center", arrowprops=dict(arrowstyle="->", color=col), zorder=6)
    rt = ciz.get("retest")
    if rt is not None and start <= rt < end:
        y = cs[rt]["l"] if d == 1 else cs[rt]["h"]
        ax.plot(rt, y, "o", markersize=11, markerfacecolor="none", markeredgecolor=MARK, markeredgewidth=1.6, zorder=6)
        ax.annotate("Retest", xy=(rt, y), xytext=(rt + 3, y + (-1 if d == 1 else 1) * (
            max(x["h"] for x in cs[start:end]) - min(x["l"] for x in cs[start:end])) * 0.12),
            color=MARK, fontsize=9, arrowprops=dict(arrowstyle="->", color=MARK), zorder=6)
    tgt = g.get("hedef")
    if tgt is not None:
        ax.axhline(tgt, color=MARK, linestyle="--", linewidth=1.2, zorder=4)
        ax.text(start + 1, tgt, f" Hedef {_fmt(tgt, prec)}", color=MARK, fontsize=9, va="bottom", zorder=7,
                bbox=dict(facecolor=BG, edgecolor="none", pad=1))     # sol başta: TP etiketleriyle çakışmasın
    if lvl is not None and not (g.get("plan") or {}).get("at_level"):     # giriş kırılımdaysa etiket "Giriş (kırılım)"
        ax.text(end + 1, lvl, f" Kırılım {_fmt(lvl, prec)}", color=MARK, fontsize=9, va="center", zorder=7,
                bbox=dict(facecolor=BG, edgecolor="none", pad=1))
    # işlem planı: giriş / TP1-2-3 / stop ve kâr (yeşil) – zarar (kırmızı) bölgeleri (kullanıcı isteği)
    plan = g.get("plan")
    x_right = end + int((end - start) * 0.22) + 4
    extra = [tgt] if tgt is not None else []
    if plan:
        e, sl, tps, pd_ = plan["entry"], plan["stop"], plan["tp"], plan["d"]
        x0, x1 = end - 1, x_right - 1
        far = max(tps, key=lambda v: abs(v - e))
        ax.add_patch(plt.Rectangle((x0, min(e, far)), x1 - x0, abs(far - e), color=UP, alpha=0.16, zorder=1))
        ax.add_patch(plt.Rectangle((x0, min(e, sl)), x1 - x0, abs(e - sl), color=DOWN, alpha=0.20, zorder=1))
        pc = lambda v: (v / e - 1) * 100 * pd_
        srm = plan.get("tp_sr") or [False] * len(tps)
        rows = [(f"TP{k}", v, MARK, "--") for k, v in enumerate(tps, 1)] + [      # destek / direnç yazısı yok (kullanıcı)
            ("Giriş (kırılım)" if plan.get("at_level") else "Giriş", e, MARK, "-"), ("Stop", sl, MARK, "-")]
        # etiketler üst üste binmesin: aralarında en az %4,5 yükseklik
        lo_y = min([cs[k]["l"] for k in xs] + [sl] + tps)
        hi_y = max([cs[k]["h"] for k in xs] + [sl] + tps)
        gap = (hi_y - lo_y) * 0.045
        ys = {}
        prev = None
        for name, v, *_ in sorted(rows, key=lambda r_: r_[1]):
            y = v if prev is None else max(v, prev + gap)
            ys[name] = prev = y
        for name, v, colr, ls in rows:
            ax.plot([x0, x1], [v, v], color=colr, linestyle=ls, linewidth=1.1, zorder=4)
            base_, _, tag_ = name.partition(" · ")
            lab = (f"{base_} {_fmt(v, prec)}" + ("" if base_.startswith("Giriş") else f" ({pc(v):+.2f}%)")
                   + (f" · {tag_}" if tag_ else ""))
            ax.text(x1, ys.get(name, v), lab + " ", color=colr, fontsize=8, va="center", ha="right", zorder=7,
                    bbox=dict(facecolor=BG, edgecolor="none", pad=0.5, alpha=0.7))
        extra += [sl, max(tps, key=lambda v: abs(v - e))]
    # eksenler
    if pv:
        extra += [pv[nm] for nm in ("P", "R1", "S1") if pv.get(nm) is not None]
    if bg and g.get("pivot_current_only"):     # P, R1-R3, S1-S3 her resimde görünsün (kullanıcı isteği)
        extra += [bg[-1][nm] for nm in ("R3", "R2", "R1", "P", "S1", "S2", "S3") if bg[-1].get(nm) is not None]
    if bg:                                     # fiyatın hemen üstündeki ve altındaki pivot da görünsün
        lv_ = [bg[-1][nm] for nm in ("R3", "R2", "R1", "P", "S1", "S2", "S3")]
        hi_p, lo_p = max(cs[k]["h"] for k in xs), min(cs[k]["l"] for k in xs)
        up_ = [v for v in lv_ if v > hi_p]
        dn_ = [v for v in lv_ if v < lo_p]
        span = hi_p - lo_p
        if up_ and min(up_) - hi_p <= span * 0.6:
            extra.append(min(up_))
        if dn_ and lo_p - max(dn_) <= span * 0.6:
            extra.append(max(dn_))
    lows = [cs[k]["l"] for k in xs] + extra
    highs = [cs[k]["h"] for k in xs] + extra
    pad = (max(highs) - min(lows)) * 0.06
    ax.set_ylim(min(lows) - pad, max(highs) + pad)
    ax.set_xlim(start - 1, x_right)
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
    for j_, (nm_, c_) in enumerate(ma_leg):          # hareketli ortalama renkleri (başlık hizasında, sağda)
        ax.text(1.0 - (len(ma_leg) - 1 - j_) * 0.085, 1.015, nm_, color=c_, fontsize=8, ha="right", va="bottom",
                transform=ax.transAxes, fontweight="bold")
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
