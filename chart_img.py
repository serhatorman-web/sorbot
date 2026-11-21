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
CROSS_GOLD, CROSS_DEATH = "#ffd700", "#ff1744"
ICH_COLS = {"tk": "#00e5ff", "kj": "#e040fb", "ch": "#9ccc65"}   # Ichimoku: Tenkan camgöbeği, Kijun pembe-mor, Chikou açık yeşil
VP_COLS = {"VAH": "#f23645", "POC": "#ffeb3b", "VAL": "#00e676"}   # hacim profili (TradingView'deki gibi): VAH kırmızı, POC sarı, VAL yeşil
BB_COL = "#ce93d8"                                     # Bollinger bandı (açık mor)
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
    if g.get("window"):                         # ör. Golden / Death Cross resmi: son N mum
        start = max(0, n - g["window"])
    # Supertrend'in son Buy/Sell'i resimde görünsün (kullanıcı isteği): son yön değişimi pencerenin solunda
    # kalıyorsa resim o muma kadar genişletilir; 300 mumluk veride hiç yön değişimi yoksa sol kenarda yazılır
    st_old = None
    if g.get("supertrend"):
        _ln, _dr = g["supertrend"]
        kf = next((k for k in range(n - 1, 0, -1) if _dr[k] and _dr[k - 1] and _dr[k - 1] == -_dr[k]), None)
        ext_ok = False
        if kf is not None and start - 60 <= kf < start:      # yakınsa resim o muma kadar genişler…
            s0 = max(0, kf - 6)
            r_now = (max(x["h"] for x in cs[start:n]) - min(x["l"] for x in cs[start:n])) or 1e-12
            r_ext = max(x["h"] for x in cs[s0:n]) - min(x["l"] for x in cs[s0:n])
            ext_ok = r_ext <= r_now * 1.3                    # …ama fiyat aralığını %30'dan fazla büyütmüyorsa
            if ext_ok:                                       # (BULLA 4s: eski tepe mumları küçültüyordu)
                start = s0
        if ext_ok:
            pass
        elif (kf is None or kf < start) and _dr and _dr[-1]:  # uzaksa / aralığı büyütüyorsa: sol kenarda yazı
            st_old = _dr[-1]
            st_old_t = (datetime.fromtimestamp(cs[kf]["t"] / 1000, TSI).strftime("%d.%m %H:%M") if kf is not None
                        else "daha önce")
    end = n                                   # son kapanmış muma kadar
    xs = range(start, end)
    # Logaritmik ölçek (kullanıcı: BULLA 4s gibi sert düşüş/yükselişlerde son mumlar, plan ve pivot yazıları ince bir
    # şeride sıkışıyordu): resimdeki en yüksek / en düşük oranı 3'ü geçerse fiyat ekseni logaritmik olur
    # (TradingView'deki log ölçek gibi); her fiyat bölgesi orantılı yer kaplar.
    _vals = [cs[k]["h"] for k in xs] + [cs[k]["l"] for k in xs]
    _pl = g.get("plan")
    if _pl:
        _vals += [_pl["stop"]] + list(_pl["tp"])
    if g.get("hedef") is not None:
        _vals.append(g["hedef"])
    _pos = [v for v in _vals if v and v > 0]
    use_log = (g.get("log_scale", False) and bool(_pos) and min(_pos) > 0
               and max(_pos) / min(_pos) >= 3)               # kapalı (kullanıcı: SKY örneğindeki düz ölçek)
    T = (lambda v: __import__("math").log10(v) if v > 0 else -99) if use_log else (lambda v: v)
    TI = (lambda v: 10 ** v) if use_log else (lambda v: v)
    _rT = (T(max(cs[k]["h"] for k in xs)) - T(min(cs[k]["l"] for k in xs))) or 1e-12

    def OFF(y, frac):
        """y'den, mumların dikey aralığının frac katı kadar yukarı/aşağı (log ölçekte orantılı)."""
        return TI(T(y) + frac * _rT)
    rsi_s = g.get("rsi")                        # RSI paneli ve uyumsuzluklar (kullanıcı isteği)
    sr = qr = None
    qqe = (g.get("rsi_x") or {}).get("qqe") if rsi_s else None
    if rsi_s and qqe:                           # RSI, Stoch RSI ve QQE MOD panelleri (kullanıcının TradingView düzeni)
        fig, (ax, ar, sr, qr) = plt.subplots(4, 1, figsize=(11.6, 9.0), dpi=110, sharex=True,
                                             gridspec_kw={"height_ratios": [3.6, 1.0, 1.0, 1.0], "hspace": 0.05})
    elif rsi_s:                                 # altta RSI ve Stoch RSI panelleri (kullanıcının TradingView düzeni)
        fig, (ax, ar, sr) = plt.subplots(3, 1, figsize=(11.6, 7.6), dpi=110, sharex=True,
                                         gridspec_kw={"height_ratios": [3.6, 1.0, 1.0], "hspace": 0.05})
    else:
        fig, ax = plt.subplots(figsize=(11.6, 5.6), dpi=110)   # daha geniş ve yüksek: mumlar net (Telegram ~1280 px)
        ar = None
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)
    w = 0.72                                    # mum gövdesi daha geniş, fitil daha kalın (net görünüm)
    _cr = (max(cs[k]["h"] for k in xs) - min(cs[k]["l"] for k in xs)) or 1e-12
    for k in xs:
        x = cs[k]
        col = UP if x["c"] >= x["o"] else DOWN
        ax.vlines(k, x["l"], x["h"], color=col, linewidth=1.0, zorder=2)
        lo, hi = sorted((x["o"], x["c"]))
        ax.add_patch(plt.Rectangle((k - w / 2, lo), w, max(hi - lo, _cr * 0.002), color=col, zorder=3,
                                   linewidth=0))
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
    # Bollinger bandı (20, 2): üst/alt bant mor çizgi, arası hafif dolgu, orta bant kesikli (kullanıcı isteği)
    bu, bm, bl = mas.get("_bb_up"), mas.get("_bb_mid"), mas.get("_bb_lo")
    if bu and bl:
        ks = [k for k in range(start, end) if k < len(bu) and bu[k] is not None and bl[k] is not None]
        if len(ks) >= 2:
            ax.plot(ks, [bu[k] for k in ks], color=BB_COL, linewidth=1.0, alpha=0.9, zorder=3.2)
            ax.plot(ks, [bl[k] for k in ks], color=BB_COL, linewidth=1.0, alpha=0.9, zorder=3.2)
            ax.fill_between(ks, [bl[k] for k in ks], [bu[k] for k in ks], color=BB_COL, alpha=0.05, zorder=1.5)
            if bm:
                ax.plot(ks, [bm[k] for k in ks], color=BB_COL, linewidth=0.8, linestyle="--", alpha=0.7, zorder=3.2)
            ma_leg.append(("BB", BB_COL))
    # Ichimoku (9, 26, 52): sadece bulut (Senkou A > B yeşil, A < B kırmızı; sağda 26 mum ileri)
    ich = mas.get("_ich")
    if ich:
        xr_ = end + int((end - start) * 0.22) + 4
        A = {x: v for x, v in ich["sa"] if start <= x <= xr_}
        B = {x: v for x, v in ich["sb"] if start <= x <= xr_}
        ks = sorted(set(A) & set(B))
        if len(ks) >= 2:
            av, bv = [A[k] for k in ks], [B[k] for k in ks]
            ax.plot(ks, av, color="#26a69a", linewidth=0.8, alpha=0.8, zorder=1.6)
            ax.plot(ks, bv, color="#ef5350", linewidth=0.8, alpha=0.8, zorder=1.6)
            ax.fill_between(ks, av, bv, where=[a_ >= b_ for a_, b_ in zip(av, bv)], interpolate=True,
                            color="#26a69a", alpha=0.13, zorder=1.4)
            ax.fill_between(ks, av, bv, where=[a_ < b_ for a_, b_ in zip(av, bv)], interpolate=True,
                            color="#ef5350", alpha=0.13, zorder=1.4)
        if len(ks) >= 2:                          # sadece bulut (kullanıcı isteği: Tenkan / Kijun / Chikou yok)
            ma_leg.append(("Ichimoku", "#26a69a"))
    # Hacim profili (sinyaldeki VAH / POC / VAL ile aynı, kullanıcının TradingView görünümü): düz çizgiler,
    # etiket sağ kenarda çizginin üstünde "VAH (64460.9)" biçiminde
    vp_lv = mas.get("_vp")
    if vp_lv:
        xr_vp = end + int((end - start) * 0.22) + 4
        for nm, v in zip(("VAH", "POC", "VAL"), vp_lv):
            if v is None:
                continue
            ax.plot([start - 1, xr_vp], [v, v], color=VP_COLS[nm], linewidth=1.3, zorder=3.6)
            # sağdaki plan etiketleri (Giriş / Stop / TP) hemen üstündeyse yazı çizginin altına alınır
            pl_ = g.get("plan") or {}
            pys = [y_ for y_ in [pl_.get("entry"), pl_.get("stop")] + list(pl_.get("tp") or []) if y_ is not None]
            r_ = (max(x["h"] for x in cs[start:end]) - min(x["l"] for x in cs[start:end])) or 1e-12
            up_clash = any(0 <= y_ - v <= r_ * 0.08 for y_ in pys)
            ax.text(xr_vp - 0.5, v, f"{nm} ({_fmt(v, prec)})", color=VP_COLS[nm], fontsize=8.5,
                    va="top" if up_clash else "bottom", ha="right", zorder=8, clip_on=True)
    # Golden Cross (MA50 MA200'ü yukarı keser) / Death Cross (aşağı keser): işaret + yazı (kullanıcı isteği)
    cross_pts = []
    m5, m2 = mas.get("MA50"), mas.get("MA200")
    if m5 and m2 and mas.get("_marks"):         # config live_images.crosses kapalıysa işaret yok
        rng_c = (max(x["h"] for x in cs[start:end]) - min(x["l"] for x in cs[start:end])) or 1
        for k in range(max(start, 1), min(end, len(m5), len(m2))):
            if None in (m5[k - 1], m2[k - 1], m5[k], m2[k]):
                continue
            s0, s1 = m5[k - 1] - m2[k - 1], m5[k] - m2[k]
            if s0 * s1 < 0 or (s0 == 0 and s1 != 0 and k >= 2 and None not in (m5[k - 2], m2[k - 2])
                                and (m5[k - 2] - m2[k - 2]) * s1 < 0):
                gold = s1 > 0
                y = (m5[k] + m2[k]) / 2
                colr = CROSS_GOLD if gold else CROSS_DEATH
                ax.plot(k, y, marker="X", markersize=11, color=colr, markeredgecolor=BG, markeredgewidth=1.2, zorder=8)
                near_r = k > end - 25                   # sağ kenara yakınsa yazı solda (plan etiketleriyle çakışmasın)
                ax.annotate("Golden Cross" if gold else "Death Cross", xy=(k, y),
                            xytext=(k - 6 if near_r else k, OFF(y, 0.13 if gold else -0.13)), color=colr,
                            fontsize=9, fontweight="bold", ha="right" if near_r else "center", va="bottom" if gold else "top", zorder=8,
                            arrowprops=dict(arrowstyle="-", color=colr, linewidth=0.8),
                            bbox=dict(facecolor=BG, edgecolor=colr, boxstyle="round,pad=0.25", linewidth=0.8))
                cross_pts += [y, OFF(y, 0.16 if gold else -0.16)]
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
                            xytext=(k, OFF(y, -0.07 if dirs[k] == 1 else 0.07)), color="white", fontsize=7,
                            ha="center", va="center", zorder=8,
                            bbox=dict(boxstyle="round,pad=0.25", facecolor=colr, edgecolor="none"))
            k = j2 + 1
        if st_old:                                           # son Buy/Sell 300 mumdan eski: sol kenarda bilgi
            k0 = next((q for q in range(start, end) if line[q] is not None), None)
            if k0 is not None:
                ax.annotate(("Buy" if st_old == 1 else "Sell") + f" ({st_old_t})", xy=(k0, line[k0]),
                            xytext=(k0 + 2, OFF(line[k0], -0.07 if st_old == 1 else 0.07)), color="white",
                            fontsize=7, ha="left", va="center", zorder=8,
                            bbox=dict(boxstyle="round,pad=0.25", facecolor=UP if st_old == 1 else DOWN, edgecolor="none"))
    em = g.get("entry_mark")                     # girişte AL / SAT etiketi (kullanıcı isteği; Supertrend Buy/Sell ayrı)
    if em and start <= em[0] <= end:
        k_e, y_e, d_e = em
        ax.annotate("AL" if d_e == 1 else "SAT", xy=(k_e, y_e), xytext=(k_e, OFF(y_e, -0.09 if d_e == 1 else 0.09)),
                    color="white", fontsize=8, fontweight="bold", ha="center", va="center", zorder=9,
                    arrowprops=dict(arrowstyle="-|>", color="white", lw=1.0),
                    bbox=dict(boxstyle="round,pad=0.3", facecolor=UP if d_e == 1 else DOWN, edgecolor="white", lw=0.8))
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
    # "Retest" yazısı: plan alanında, stop çizgisinin ötesindeki boşlukta (grafiği kapatmasın; kullanıcı isteği).
    # "Kırılım" yazısı eski yerinde.
    lab_ys = []
    rng = max(x["h"] for x in cs[start:end]) - min(x["l"] for x in cs[start:end])
    pl_ = g.get("plan")
    box = dict(facecolor=BG, edgecolor=MARK, boxstyle="round,pad=0.3", linewidth=0.8)
    slot = [0]

    def side_label(txt, xy):
        if pl_:
            yl = OFF(pl_["stop"], -pl_["d"] * (0.13 + 0.08 * slot[0]))
            slot[0] += 1
            lab_ys.append(OFF(yl, -pl_["d"] * 0.03))
            ax.annotate(txt, xy=xy, xytext=(end + 1, yl), color=MARK, fontsize=9, fontweight="bold", ha="left",
                        va="center", bbox=box, arrowprops=dict(arrowstyle="->", color=MARK, linewidth=0.9), zorder=9)
            return True
        return False

    rt = ciz.get("retest")
    if kb is not None and kb >= start:
        y = cs[kb]["c"]
        # Kırılım yazısı: kırılım mumunun yakınında mumların olmadığı boş bir yerde, siyah zemin üzerinde
        # (grafiği kapatmasın; kullanıcı isteği)
        span_x = max(10, end - start)
        dx, dy = span_x * 0.11, _rT * 0.11          # yazının kapladığı alan + pay (T uzayında; log ölçekte de doğru)
        segs = [((a_[0], a_[1]), (b_[0], b_[1])) for a_, b_ in ciz.get("cizgiler", [])]

        def blocked(tx, ty):
            k0, k1 = max(start, int(tx - dx / 2) - 1), min(end, int(tx + dx / 2) + 2)
            ty = T(ty)
            if any(T(cs[k]["l"]) <= ty + dy / 2 and T(cs[k]["h"]) >= ty - dy / 2 for k in range(k0, k1)):
                return True
            hd_ = g.get("hedef")                         # hedef çizgisi ve yazısı da kapatılmasın
            if hd_ is not None and hd_ > 0 and abs(T(hd_) - ty) <= dy / 2:
                return True
            for sg_ in bg:                               # pivot çizgileri ve yazıları da kapatılmasın
                if tx + dx / 2 >= sg_["k0"] - 30:
                    for nm_ in ("R3", "R2", "R1", "P", "S1", "S2", "S3"):
                        v_ = sg_.get(nm_)
                        if v_ is not None and v_ > 0 and abs(T(v_) - ty) <= dy / 2:
                            return True
            for (x1, y1), (x2, y2) in segs:              # formasyon / trend çizgileri de kapatılmasın
                for xx in (tx - dx / 2, tx, tx + dx / 2):
                    if min(x1, x2) <= xx <= max(x1, x2) and x2 != x1:
                        yy = y1 + (y2 - y1) * (xx - x1) / (x2 - x1)
                        if yy > 0 and abs(T(yy) - ty) <= dy / 2:
                            return True
            return False

        best = None
        for oy in (0.30, 0.40, 0.50, 0.60, -0.30, -0.40, -0.50, -0.60, 0.22, -0.22):
            for ox in (14, 20, 26, 34, 44, 56, 70):
                tx, ty = kb - ox, OFF(y, oy if d == 1 else -oy)
                if tx - dx / 2 < start or blocked(tx, ty):
                    continue
                best = (tx, ty)
                break
            if best:
                break
        tx, ty = best or (kb - 20, OFF(y, 0.30 if d == 1 else -0.30))
        lab_ys.append(ty)
        ax.annotate("Kırılım", xy=(kb, y), xytext=(tx, ty), color=MARK, fontsize=9, fontweight="bold", ha="center",
                    va="center",                                     # zemin yok: sadece beyaz yazı (kullanıcı)
                    arrowprops=dict(arrowstyle="->", color=MARK, linewidth=0.9), zorder=9)
    if rt is not None and start <= rt < end:
        y = cs[rt]["l"] if d == 1 else cs[rt]["h"]
        ax.plot(rt, y, "o", markersize=11, markerfacecolor="none", markeredgecolor=MARK, markeredgewidth=1.6, zorder=6)
        # Retest yazısı kaldırıldı (kullanıcı isteği); retest mumu halkayla işaretli
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
    extra = ([tgt] if tgt is not None else []) + cross_pts + lab_ys
    extra += [v for v in (mas.get("_vp") or []) if v is not None]     # VAH / POC / VAL her zaman görünsün
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
        gap = (T(hi_y) - T(lo_y)) * 0.045                  # log ölçekte aralık log uzayında
        ys = {}
        prev = None
        for name, v, *_ in sorted(rows, key=lambda r_: r_[1]):
            y = T(v) if prev is None else max(T(v), prev + gap)
            prev = y
            ys[name] = TI(y)
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
    if use_log:
        extra = [v for v in extra if v is not None and v > 0]   # log eksende sıfır/negatif seviye çizilemez
    lows = [cs[k]["l"] for k in xs] + extra
    highs = [cs[k]["h"] for k in xs] + extra
    if use_log:
        from matplotlib.ticker import FuncFormatter, LogLocator, NullFormatter
        ax.set_yscale("log")
        lo_l, hi_l = T(min(lows)), T(max(highs))
        pad = (hi_l - lo_l) * 0.06
        ax.set_ylim(TI(lo_l - pad), TI(hi_l + pad))
        ax.yaxis.set_major_locator(LogLocator(base=10, subs=(1.0, 1.5, 2.0, 3.0, 5.0, 7.0)))
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: _fmt(v, prec)))
        ax.yaxis.set_minor_formatter(NullFormatter())
    else:
        pad = (max(highs) - min(lows)) * 0.06
        ax.set_ylim(min(lows) - pad, max(highs) + pad)
    ax.set_xlim(start - 1, x_right)
    # Görüntü açısı (kullanıcı isteği): pivotlar fiyattan uzaksa mumlar ince bir şeride sıkışmasın diye resim
    # dikeyde uzar; mumların kapladığı yükseklik en az ~2.6 inç kalır (pivotların hepsi yine çizgi olarak görünür).
    c_span = (T(max(cs[k]["h"] for k in xs)) - T(min(cs[k]["l"] for k in xs))) or 1e-12
    frac = c_span / (((T(max(highs)) - T(min(lows))) or 1e-12) * 1.12)
    base_h = fig.get_size_inches()[1]
    need = 3.2 / max(frac, 1e-6) + (base_h - 5.6 + 0.9)
    if need > base_h:
        fig.set_size_inches(fig.get_size_inches()[0], min(need, 13.0))
    # Çok mumlu pencerelerde (ör. 1sa'te uzun trend çizgisi) mumlar küçülmesin: resim yatayda da genişler
    nb_ = x_right - start + 1
    if nb_ > 115:
        fig.set_size_inches(min(17.0, 11.6 * nb_ / 115), fig.get_size_inches()[1])
    ticks = list(range(start, end, max(1, (end - start) // 6)))
    if ar is not None:
        _rsi_panel(ax, ar, cs, rsi_s, g.get("divs") or [], start, end, x_right, g.get("rsi_x") or {})
        if sr is not None:
            ar.tick_params(axis="x", labelbottom=False)
            _stoch_panel(sr, (g.get("rsi_x") or {}).get("k") or [], (g.get("rsi_x") or {}).get("d") or [],
                         start, end)
        if qr is not None:
            sr.tick_params(axis="x", labelbottom=False)
            _qqe_panel(qr, qqe, start, end)
    bx = qr if qr is not None else (sr if sr is not None else (ar if ar is not None else ax))
    bx.set_xticks(ticks)
    bx.set_xticklabels([datetime.fromtimestamp(cs[k]["t"] / 1000, TSI).strftime("%d.%m %H:%M") for k in ticks],
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
    if sr is not None:                          # 3-4 panelde tight_layout geniş boşluk bırakıyordu: kenarlar elle
        W_, H_ = fig.get_size_inches()
        fig.subplots_adjust(left=0.45 / W_, right=1 - 0.75 / W_, top=1 - 0.4 / H_, bottom=0.35 / H_, hspace=0.05)
    else:
        fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=BG)
    plt.close(fig)
    return buf.getvalue()


def _panel_style(a_):
    a_.set_facecolor(BG)
    a_.grid(color=GRID, linewidth=0.6)
    a_.yaxis.tick_right()
    a_.tick_params(axis="y", colors=TXT, labelsize=7)
    for sp in a_.spines.values():
        sp.set_color(GRID)


def _qqe_panel(qr, q, start, end):
    """QQE MOD (Mihkel00): gri histogram (RsiMa2 - 50), güçlü yükselişte mavi / güçlü düşüşte kırmızı sütun,
    beyaz QQE çizgisi, sıfır çizgisi (kullanıcının TradingView'i)."""
    _panel_style(qr)
    xs_ = list(range(start, end))
    hs, ln = q.get("hist") or [], q.get("line") or []
    up, dn = q.get("up") or [], q.get("dn") or []
    thr = q.get("thr", 3.0)
    get = lambda s_, k: s_[k] if k < len(s_) and s_[k] is not None else None
    for k in xs_:
        h_ = get(hs, k)
        if h_ is None:
            continue
        if k < len(up) and up[k]:
            col, al = "#00c3ff", 1.0
        elif k < len(dn) and dn[k]:
            col, al = "#ff0062", 1.0
        elif abs(h_) > thr:
            col, al = "#c0c0c0", 0.5
        else:
            continue
        qr.bar(k, h_, width=0.8, color=col, alpha=al, zorder=2, linewidth=0)
    qr.plot(xs_, [get(ln, k) if get(ln, k) is not None else float("nan") for k in xs_], color="white",
            linewidth=1.5, zorder=4)
    qr.axhline(0, color="#787b86", linestyle=":", linewidth=0.8)
    vals = [abs(v) for k in xs_ for v in (get(hs, k), get(ln, k)) if v is not None]
    m_ = (max(vals) if vals else 30) * 1.12
    qr.set_ylim(-m_, m_)
    qr.text(start, m_ * 0.94, " QQE MOD", color=TXT, fontsize=8, va="top", fontweight="bold")


def _stoch_panel(sr, k_s, d_s, start, end):
    """Stoch RSI (14, 14, 3, 3): K mavi, D turuncu, 20-80 arası hafif camgöbeği bant (kullanıcının TradingView'i)."""
    _panel_style(sr)
    xs_ = list(range(start, end))
    val = lambda s_, k: s_[k] if k < len(s_) and s_[k] is not None else float("nan")
    sr.axhspan(20, 80, color="#26c6da", alpha=0.07, zorder=0)
    for lv_, ls_ in ((20, "--"), (50, ":"), (80, "--")):
        sr.axhline(lv_, color="#787b86", linestyle=ls_, linewidth=0.8)
    sr.plot(xs_, [val(k_s, k) for k in xs_], color="#2962ff", linewidth=1.3, zorder=4)
    sr.plot(xs_, [val(d_s, k) for k in xs_], color="#ff6d00", linewidth=1.3, zorder=3)
    sr.text(start, 97, " Stoch RSI", color=TXT, fontsize=8, va="top", fontweight="bold")
    sr.set_ylim(-3, 103)
    sr.set_yticks([20, 50, 80])


def _rsi_panel(ax, ar, cs, rsi_s, divs, start, end, x_right, rx=None):
    """Alt panelde RSI (14) sarı + 14'lük ortalaması mor; 30-70 arası hafif mor zemin, 30 altı kırmızı / 70 üstü yeşil
    dolgu (kullanıcının TradingView'i). Uyumsuzluklar (açıksa) hem fiyatta hem RSI'da çizgi + yazı."""
    ax.tick_params(axis="x", labelbottom=False)
    ar.set_facecolor(BG)
    ar.grid(color=GRID, linewidth=0.6)
    ar.yaxis.tick_right()
    ar.tick_params(axis="y", colors=TXT, labelsize=7)
    for sp in ar.spines.values():
        sp.set_color(GRID)
    xs_ = list(range(start, end))
    rv = [rsi_s[k] if k < len(rsi_s) and rsi_s[k] is not None else float("nan") for k in xs_]
    ar.axhspan(30, 70, color="#7e57c2", alpha=0.08, zorder=0)
    for lv_, ls_ in ((30, "--"), (50, ":"), (70, "--")):
        ar.axhline(lv_, color="#787b86", linestyle=ls_, linewidth=0.8)
    ar.fill_between(xs_, rv, 30, where=[v == v and v < 30 for v in rv], interpolate=True, color="#f23645",
                    alpha=0.35, zorder=1)
    ar.fill_between(xs_, rv, 70, where=[v == v and v > 70 for v in rv], interpolate=True, color="#089981",
                    alpha=0.35, zorder=1)
    rma = (rx or {}).get("ma") or []
    if rma:
        ar.plot(xs_, [rma[k] if k < len(rma) and rma[k] is not None else float("nan") for k in xs_],
                color="#7e57c2", linewidth=1.2, zorder=3)
    ar.plot(xs_, rv, color="#ffeb3b", linewidth=1.1, zorder=4)
    # TradingView gibi otomatik ölçek: 0-100 yerine görünen RSI aralığı (30 / 70 hep içinde) – çizgi Stoch RSI kadar büyük
    vis = [v for v in rv if v == v]
    lo_r = min(vis + [30]) - 4 if vis else 0
    hi_r = max(vis + [70]) + 4 if vis else 100
    ar.text(start, hi_r - (hi_r - lo_r) * 0.03, " RSI", color=TXT, fontsize=8, va="top", fontweight="bold")
    ar.set_ylim(max(0, lo_r), min(100, hi_r))
    ar.set_yticks([30, 50, 70])
    for p1, p2, bull in divs:
        if p1 < start or p2 >= end or rsi_s[p1] is None or rsi_s[p2] is None:
            continue
        col = UP if bull else DOWN
        key = "l" if bull else "h"
        y1, y2 = cs[p1][key], cs[p2][key]
        ax.plot([p1, p2], [y1, y2], color=col, linewidth=1.8, zorder=6)
        ax.plot([p1, p2], [y1, y2], "o", color=col, markersize=4, zorder=6)
        ar.plot([p1, p2], [rsi_s[p1], rsi_s[p2]], color=col, linewidth=1.8, zorder=5)
        ar.plot([p1, p2], [rsi_s[p1], rsi_s[p2]], "o", color=col, markersize=4, zorder=6)
        if any(q1 == p2 and qb == bull for q1, _, qb in divs):     # zincirleme uyumsuzlukta yazı sadece sonda
            continue
        lab = "Pozitif uyumsuzluk" if bull else "Negatif uyumsuzluk"
        ax.annotate(lab, xy=(p2, y2), xytext=(0, -14 if bull else 10), textcoords="offset points", color=col,
                    fontsize=8, fontweight="bold", ha="center", va="top" if bull else "bottom", zorder=8,
                    bbox=dict(facecolor=BG, edgecolor="none", pad=0.4, alpha=0.75))
        ar.annotate("Poz." if bull else "Neg.", xy=(p2, rsi_s[p2]), xytext=(0, -10 if bull else 6),
                    textcoords="offset points", color=col, fontsize=7, ha="center", va="top" if bull else "bottom")


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
