"""🎯 Nokta Atışı sinyalleri (ayrı kanal): dipten dönüş, tepeden dönüş, trend içi yükseliş / düşüş, pump / dump.
Her sinyal: giriş (sinyal mumunun kapanışı), TP1 / TP2 / TP3 (1R / 2R / 3R) ve yapı stopu.
Hangi kuralların açık olduğu ve filtreleri config.json → "sniper" bölümünden gelir."""
from datetime import datetime

import indicators as ta

CATS = {
    "dip": ("🟢", "DİPTEN DÖNÜŞ", "LONG"),
    "tepe": ("🔴", "TEPEDEN DÖNÜŞ", "SHORT"),
    "trend_up": ("🟢", "TREND İÇİ YÜKSELİŞ", "LONG"),
    "trend_dn": ("🔴", "TREND İÇİ DÜŞÜŞ", "SHORT"),
    "pump": ("🚀", "PUMP", "LONG"),
    "dump": ("💥", "DUMP", "SHORT"),
}
# kural → (kategori, kısa ad)
RULES = {
    "dip_rsi": ("dip", "RSI 30 dönüşü"), "dip_sweep": ("dip", "Likidite süpürme"),
    "dip_stretch": ("dip", "Aşırı uzama dönüşü"),
    "top_rsi": ("tepe", "RSI 70 dönüşü"), "top_sweep": ("tepe", "Likidite süpürme"),
    "top_stretch": ("tepe", "Aşırı uzama dönüşü"),
    "up_ema20": ("trend_up", "EMA20 geri çekilme"), "up_breakout": ("trend_up", "Hacimli zirve kırılımı"),
    "up_rsi": ("trend_up", "RSI 40→50"),
    "dn_ema20": ("trend_dn", "EMA20 geri çekilme"), "dn_breakdown": ("trend_dn", "Hacimli dip kırılımı"),
    "dn_rsi": ("trend_dn", "RSI 60→50"),
    "pump5": ("pump", "5x hacim patlaması"), "pump3": ("pump", "3x hacim kırılımı"),
    "dump5": ("dump", "5x hacim patlaması"), "dump3": ("dump", "3x hacim kırılımı"),
    "ssl_top": ("tepe", "SSL Sell + çizgi kırmızı"), "ssl_bottom": ("dip", "SSL Buy + çizgi mavi"),
}


SSL_RULES = ("ssl_top", "ssl_bottom")


def ssl_baseline(h, l, c, n=55, mult=0.2):
    """SSL Hybrid baseline (HMA n) rengi: +1 mavi (kapanış üst bandın üstünde), -1 kırmızı (alt bandın altında), 0 gri.
    Bant: baseline ± EMA(true range, n) x mult (SSL Hybrid Keltner ayarı)."""
    bb = ta.hma(c, n)
    rma = ta.ema([x or 0 for x in ta.true_range(h, l, c)], n)
    col = [0] * len(c)
    for i in range(len(c)):
        if bb[i] is not None and rma[i] is not None:
            col[i] = 1 if c[i] > bb[i] + rma[i] * mult else (-1 if c[i] < bb[i] - rma[i] * mult else 0)
    return bb, col


def ssl_system(h, l, c, ssl, st_dir, a, col, i, p, qqe=None, dyna=None):
    """Kullanıcının SSL sistemi (SHORT; LONG tersi): tepede SSL Sell (çıkış çizgisi aşağı kesilir, son 48 mumun
    zirvesine ≤ near_atr ATR) → en fazla warn_bars mum içinde fiyat baseline'ın altında kapatır, çizgi kırmızıya
    döner (önceki renk en az min_regime mum sürmüş) → 1. teyit QQE MOD pembe, 2. teyit DynaRange kırmızı (çizgi
    döndükten sonra en fazla confirm_bars mum içinde, ilk kez ikisi birlikte sağlandığı mumda) → Supertrend henüz
    AL iken SHORT. Döner: sinyal dict ya da None."""
    if i < 60 or col[i] == 0 or not a[i]:
        return None
    d = col[i]
    show = qqe is not None and dyna is not None
    conf = show and p.get("confirm_required", False)     # False: teyitler beklenmez, sadece ✅ / ❌ ile yazılır
    # çizginin bu renge döndüğü mum (j): teyitler için en fazla confirm_bars mum beklenir
    j = i
    while j > 0 and col[j - 1] == d and i - j <= p.get("confirm_bars", 5):
        j -= 1
    if col[j - 1] == d or (not conf and j != i):
        return None
    if p.get("supertrend_opposite", True) and st_dir[i] != -d:
        return None
    if conf:
        ok = lambda k: qqe[k] == d and dyna[k] is not None and dyna[k] * d > 0
        if not ok(i) or any(ok(k) for k in range(j, i)):
            return None
    k = j - 1
    while k > 0 and col[k] != d:
        k -= 1
    if next((col[q] for q in range(j - 1, k, -1) if col[q] != 0), 0) != -d or j - 1 - k < p.get("min_regime", 15):
        return None
    w = None
    for q in range(j, max(1, j - p.get("warn_bars", 10)) - 1, -1):
        if ssl[q] is None or ssl[q - 1] is None:
            break
        if (c[q] - ssl[q]) * d > 0 and (c[q - 1] - ssl[q - 1]) * d <= 0:
            w = q
            break
    if w is None or not a[w]:
        return None
    gap = ((max(h[w - 48:w + 1]) - h[w]) if d == -1 else (l[w] - min(l[w - 48:w + 1]))) / a[w]
    if gap > p.get("near_atr", 1.0):
        return None
    stop = (max(h[w:i + 1]) + 0.2 * a[i]) if d == -1 else (min(l[w:i + 1]) - 0.2 * a[i])
    why = (f"{'tepede SSL Sell' if d == -1 else 'dipte SSL Buy'} geldi ({i - w} mum önce), fiyat SSL çizgisinin "
           f"{'altında' if d == -1 else 'üstünde'} kapattı → çizgi {'kırmızı' if d == -1 else 'mavi'}; "
           + (f"Supertrend henüz {'AL' if d == -1 else 'SAT'} (erken giriş)" if st_dir[i] == -d
              else f"Supertrend de {'SAT' if d == -1 else 'AL'}"))
    if show:
        why += "\n" + "\n".join(confirm_lines(d, qqe[i], dyna[i]))
    return {"rule": "ssl_top" if d == -1 else "ssl_bottom", "d": d, "stop": stop, "warn": w, "why": why}


def confirm_lines(d, q, dy):
    """SSL sinyalinin teyitleri: uyan ✅, zıt ❌, nötr ⚪; ikisi de uymuyorsa uyarı (kullanıcı isteği)."""
    up = d == 1
    mv = "yükseliş" if up else "düşüş"
    side = "alıcılar" if up else "satıcılar"
    qc = {1: "mavi", -1: "pembe"}.get(q, "gri")
    if q == d:
        l1 = f"✅ 1. teyit: QQE MOD {qc} → {side} güçlü"
    elif q == -d:
        l1 = f"❌ 1. teyit: QQE MOD {qc} → {side} zayıf"
    else:
        l1 = "⚪ 1. teyit: QQE MOD gri → yön belirsiz"
    dv = 0 if dy is None else (1 if dy > 0 else (-1 if dy < 0 else 0))
    dc = {1: "yeşil", -1: "kırmızı"}.get(dv, "nötr")
    if dv == d:
        l2 = f"✅ 2. teyit: DynaRange {dc} → {mv} teyit edildi"
    elif dv == -d:
        l2 = f"❌ 2. teyit: DynaRange {dc} → {mv} teyit edilmedi"
    else:
        l2 = f"⚪ 2. teyit: DynaRange nötr → {mv} teyit edilmedi"
    end = ("✅ İki teyit de onaylıyor → işleme girilebilir" if q == d and dv == d
           else "⚠️ Teyitler zıt → işleme girmek riskli, bekle")
    return [l1, l2, end]


def features(o, h, l, c, v):
    return {"a": ta.atr(h, l, c, 14), "e20": ta.ema(c, 20), "e50": ta.ema(c, 50), "e200": ta.ema(c, 200),
            "r": ta.rsi(c, 14), "vma": ta.sma(v, 20)}


def setups(o, h, l, c, v, i, x):
    """i. mumda oluşan kurulumlar: [{rule, d, stop, why}] (sadece i ve öncesi kullanılır)."""
    a, e20, e50, e200, r, vma = x["a"][i], x["e20"], x["e50"], x["e200"], x["r"], x["vma"]
    if i < 60 or not a or e200[i] is None or vma[i - 1] is None or r[i] is None or None in r[i - 6:i]:
        return []
    out = []
    add = lambda rule, d, stop, why: out.append({"rule": rule, "d": d, "stop": stop, "why": why})
    rng = h[i] - l[i] or 1e-12
    pos = (c[i] - l[i]) / rng
    vr = v[i] / vma[i - 1] if vma[i - 1] else 0
    lo10, hi10 = min(l[i - 9:i + 1]), max(h[i - 9:i + 1])
    lo48, hi48 = min(l[i - 48:i]), max(h[i - 48:i])
    up = e50[i] > e200[i] and e50[i] > e50[i - 10]
    dn = e50[i] < e200[i] and e50[i] < e50[i - 10]
    rs = r[i - 5:i]
    # ── dipten / tepeden dönüş ──
    if min(rs) < 30 and r[i - 1] <= 30 < r[i] and c[i] > o[i]:
        add("dip_rsi", 1, lo10 - 0.2 * a, f"RSI 30 altından yukarı döndü ({r[i]:.0f}), yeşil mum")
    if max(rs) > 70 and r[i - 1] >= 70 > r[i] and c[i] < o[i]:
        add("top_rsi", -1, hi10 + 0.2 * a, f"RSI 70 üstünden aşağı döndü ({r[i]:.0f}), kırmızı mum")
    if l[i] < lo48 and c[i] > lo48 and c[i] > o[i] and pos >= 0.5 and vr >= 1.3:
        add("dip_sweep", 1, l[i] - 0.2 * a, f"son 48 mumun dibinin altına iğne attı, dibin üstünde kapattı (hacim {vr:.1f}x)")
    if h[i] > hi48 and c[i] < hi48 and c[i] < o[i] and pos <= 0.5 and vr >= 1.3:
        add("top_sweep", -1, h[i] + 0.2 * a, f"son 48 mumun tepesinin üstüne iğne attı, tepenin altında kapattı (hacim {vr:.1f}x)")
    ap = x["a"][i - 1] or a
    if c[i - 1] < e20[i - 1] - 2.5 * ap and c[i] > h[i - 1]:
        add("dip_stretch", 1, min(l[i - 1], l[i]) - 0.2 * a,
            "fiyat EMA20'nin 2.5 ATR altına uzadı, önceki mumun tepesinin üstünde kapattı")
    if c[i - 1] > e20[i - 1] + 2.5 * ap and c[i] < l[i - 1]:
        add("top_stretch", -1, max(h[i - 1], h[i]) + 0.2 * a,
            "fiyat EMA20'nin 2.5 ATR üstüne uzadı, önceki mumun dibinin altında kapattı")
    # ── trend içi devam ──
    pl, ph = min(l[i - 5:i]), max(h[i - 5:i])
    if up and pl <= e20[i - 1] + 0.2 * a and pl > e50[i] - 0.5 * a and c[i] > max(h[i - 3:i]) and c[i] > o[i]:
        add("up_ema20", 1, min(l[i - 5:i + 1]) - 0.2 * a,
            "yükseliş trendinde EMA20'ye geri çekildi, son 3 mumun tepesinin üstünde kapattı")
    if dn and ph >= e20[i - 1] - 0.2 * a and ph < e50[i] + 0.5 * a and c[i] < min(l[i - 3:i]) and c[i] < o[i]:
        add("dn_ema20", -1, max(h[i - 5:i + 1]) + 0.2 * a,
            "düşüş trendinde EMA20'ye tepki verdi, son 3 mumun dibinin altında kapattı")
    if up and c[i] > hi48 and vr >= 1.5:
        add("up_breakout", 1, lo10 - 0.2 * a, f"yükseliş trendinde son 48 mumun zirvesini hacimle ({vr:.1f}x) kırdı")
    if dn and c[i] < lo48 and vr >= 1.5:
        add("dn_breakdown", -1, hi10 + 0.2 * a, f"düşüş trendinde son 48 mumun dibini hacimle ({vr:.1f}x) kırdı")
    if up and min(r[i - 6:i]) < 42 and r[i - 1] < 50 <= r[i]:
        add("up_rsi", 1, lo10 - 0.2 * a, "yükseliş trendinde RSI 40'lardan 50'nin üstüne döndü")
    if dn and max(r[i - 6:i]) > 58 and r[i - 1] > 50 >= r[i]:
        add("dn_rsi", -1, hi10 + 0.2 * a, "düşüş trendinde RSI 60'lardan 50'nin altına döndü")
    # ── pump / dump ──
    body = abs(c[i] - o[i])
    if vr >= 5 and c[i] > hi48 and body >= 1.5 * a and pos >= 0.75:
        add("pump5", 1, l[i] - 0.2 * a, f"hacim {vr:.1f}x, 48 mum zirvesi kırıldı, büyük yeşil gövde ({body / a:.1f} ATR)")
    if vr >= 5 and c[i] < lo48 and body >= 1.5 * a and pos <= 0.25:
        add("dump5", -1, h[i] + 0.2 * a, f"hacim {vr:.1f}x, 48 mum dibi kırıldı, büyük kırmızı gövde ({body / a:.1f} ATR)")
    if 3 <= vr < 5 and c[i] > hi48 and body >= 1.0 * a and pos >= 0.7:
        add("pump3", 1, l[i] - 0.2 * a, f"hacim {vr:.1f}x, 48 mum zirvesi kırıldı, güçlü yeşil mum")
    if 3 <= vr < 5 and c[i] < lo48 and body >= 1.0 * a and pos <= 0.3:
        add("dump3", -1, h[i] + 0.2 * a, f"hacim {vr:.1f}x, 48 mum dibi kırıldı, güçlü kırmızı mum")
    return out


def levels(entry, d, stop, a, min_stop_pct=0.0):
    """Risk 0.5–3 ATR arasında, en az min_stop_pct (%); TP1/2/3 = 1R/2R/3R."""
    risk = (entry - stop) * d
    risk = min(max(risk, 0.5 * a), 3 * a)
    risk = max(risk, entry * min_stop_pct / 100)
    return {"entry": entry, "stop": entry - d * risk, "tp": [entry + d * k * risk for k in (1, 2, 3)], "risk": risk}


def htf_trend(cs4):
    """Son kapanmış muma göre trend (4 saat / 1 saat): +1 yükseliş, -1 düşüş, 0 belirsiz (EMA50 / EMA200)."""
    c = [x["c"] for x in cs4]
    if len(c) < 210:
        return 0
    e50, e200 = ta.ema(c, 50), ta.ema(c, 200)
    if c[-1] > e200[-1] and e50[-1] > e200[-1]:
        return 1
    if c[-1] < e200[-1] and e50[-1] < e200[-1]:
        return -1
    return 0


def message(name, tf_name, sig, lv, fmt, t_close, htf, cfg_rule, h1=None, m15=None):
    cat, short = RULES[sig["rule"]]
    icon, title, side = CATS[cat]
    d = sig["d"]
    p = lambda x: (x / lv["entry"] - 1) * 100 * d      # işlem yönüne göre: TP'ler kâr (+), stop zarar (−)
    tr_txt = {1: "🟢 yükseliş", -1: "🔴 düşüş", 0: "⚪ yatay"}
    lines = [f"{icon} <b>{title} · {side}</b> · {tf_name}",
             f"{name} · {short}",
             "━━━━━━━━━━━━━━━━",
             f"📍 <b>Giriş:</b> {fmt(lv['entry'])}"]
    for k, tp in enumerate(lv["tp"], 1):
        lines.append(f"🎯 <b>TP{k}:</b> {fmt(tp)} ({p(tp):+.2f}%)")
    lines += [f"🛑 <b>Stop:</b> {fmt(lv['stop'])} ({p(lv['stop']):+.2f}%)",
              "━━━━━━━━━━━━━━━━",
              f"📝 {sig['why'][0].upper() + sig['why'][1:]}",
              *([f"🧭 15dk trend: {tr_txt[m15]}"] if m15 is not None else []),     # her sinyalde 15dk / 1s / 4s
              *([f"🧭 1 saatlik trend: {tr_txt[h1]}"] if h1 is not None else []),     # (kullanıcı isteği)
              f"🧭 4 saatlik trend: {tr_txt[htf]}",
              *([f"📊 Geçmiş test: TP1 %{cfg_rule['test_tp1']} · ortalama {cfg_rule['test_r']:+.2f}R "
                 f"(işlem başına, ücret düşülmüş)"] if "test_r" in cfg_rule else []),
              "⚖️ TP1'de stop girişe, TP2'de stop TP1'e çekilir",
              f"🕒 {t_close} mum kapanışı"]
    return "\n".join(lines)


def scan(api, results, cfg, state, notifier, now, parse_klines, display_name, fmt_price, tr_tz, tf_ms, render=None):
    """Bu taramanın zaman diliminde son kapanan mumdaki Nokta Atışı sinyallerini gönderir."""
    sc = cfg.get("sniper", {})
    tf = cfg["timeframe"]
    if not sc.get("enabled") or tf not in sc.get("timeframes", []):
        return 0
    tf_name = {"15m": "15dk", "1h": "1 saat", "4h": "4 saat"}.get(tf, tf)
    rules = {k: v for k, v in sc.get("rules", {}).get(tf, {}).items() if not k.startswith("_") and v.get("enabled")}
    seen = state.setdefault("sniper", {})
    cool = sc.get("cooldown_bars", 8) * tf_ms / 1000
    cands = []
    for r in results:
        meta, f, i = r["meta"], r["f"], r["i"]
        if meta.get("type") not in sc.get("types", ["COIN"]):
            continue
        lo = max(0, i + 1 - 300)
        o, h, l, c, v = (f[k][lo:i + 1] for k in ("o", "h", "l", "c", "v"))
        n = len(c)
        if n < 260:
            continue
        x = features(o, h, l, c, v)
        sigs = setups(o, h, l, c, v, n - 1, x)
        sp = rules.get("ssl_top") or rules.get("ssl_bottom")
        if sp and f.get("ssl") and f.get("st_dir"):
            _, col = ssl_baseline(h, l, c, sp.get("hma", 55))
            ss = ssl_system(h, l, c, f["ssl"][lo:i + 1], f["st_dir"][lo:i + 1], x["a"], col, n - 1, sp,
                            (f.get("qqe") or [None] * len(f["c"]))[lo:i + 1] if f.get("qqe") else None,
                            f["dyna"][lo:i + 1] if f.get("dyna") else None)
            if ss:
                ss["time"] = f["t"][lo + ss["warn"]]
                sigs.append(ss)
        for sig in sigs:
            rc = rules.get(sig["rule"])
            if not rc:
                continue
            key = f"{meta['symbol']}|{tf}|{sig['d']}"
            if sig["rule"] not in SSL_RULES and seen.get(key, 0) >= now - cool:
                continue
            cands.append((meta, sig, rc, x["a"][n - 1], c[-1], f["t"][i], htf_trend([{"c": q} for q in c]), r))
    sent, sent_other, htf_cache = 0, 0, {}
    # SSL sistemi (kullanıcının stratejisi) önce gönderilir: taramada en fazla max_per_scan sinyal gittiği için
    # alfabetik sırada geride kalan SSL sinyalleri diğer kurallar yüzünden düşmesin
    cands.sort(key=lambda x: 0 if x[1]["rule"] in SSL_RULES else 1)
    for meta, sig, rc, a, close, t_open, own_tr, r in cands:
        is_ssl = sig["rule"] in SSL_RULES             # SSL sinyallerine sınır yok (kullanıcı isteği)
        if not is_ssl and sent_other >= sc.get("max_per_scan", 10):
            continue
        sym = meta["symbol"]
        key = f"{sym}|{tf}|{sig['d']}"
        if not is_ssl and seen.get(key, 0) >= now - cool:   # aynı sembolde aynı yönde iki kural aynı anda: tek sinyal
            continue
        if sym not in htf_cache:
            try:
                htf_cache[sym] = htf_trend(parse_klines(api.get("/fapi/v1/klines", {"symbol": sym, "interval": "4h",
                                                                                   "limit": 260}), now * 1000))
            except Exception:  # noqa: BLE001
                htf_cache[sym] = 0
        htf = htf_cache[sym]
        if rc.get("htf") and htf != sig["d"]:
            continue
        tr = {}
        for k in (() if render else ("15m", "1h")):    # Supertrend formatında trend tablosu zaten var                  # 15dk ve 1 saatlik trend (4 saatlik yukarıda)
            if k == tf:
                tr[k] = own_tr
                continue
            try:
                tr[k] = htf_trend(parse_klines(api.get("/fapi/v1/klines", {"symbol": sym, "interval": k, "limit": 260}),
                                               now * 1000))
            except Exception:  # noqa: BLE001
                tr[k] = 0
        lv = levels(close, sig["d"], sig["stop"], a, rc.get("min_stop_pct", 0.0))
        prec = meta.get("precision")
        t_close = datetime.fromtimestamp((t_open + tf_ms) / 1000, tr_tz).strftime("%d.%m.%Y %H:%M")
        if render:                                 # Supertrend sinyalleriyle aynı format (kullanıcı isteği)
            msg = render(r, sig, lv, rc)
        else:
            msg = message(display_name(meta), tf_name, sig, lv, lambda p: fmt_price(p, prec), t_close, htf, rc,
                          tr.get("1h"), tr.get("15m"))
        try:
            if notifier.send_sniper(msg, sym, meta.get("type")):
                seen[key] = now
                sent += 1
                sent_other += 0 if is_ssl else 1
                print(f"  → Nokta atışı: {sym} {RULES[sig['rule']][0]} {sig['rule']} ({tf})")
        except Exception as e:  # noqa: BLE001
            print(f"  Nokta atışı gönderilemedi ({sym}): {e}")
    state["sniper"] = {k: v for k, v in seen.items() if v >= now - 3 * 86400}
    return sent
