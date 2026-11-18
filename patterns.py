"""Mum ve grafik formasyonları (Türkçe adlarla).

candle_patterns(o, h, l, c, atr)  -> son kapanmış mumda biten mum formasyonları
chart_patterns(h, l, c, atr)      -> son ~150 mumdaki grafik formasyonları (oluşan ya da yeni kırılan)

Yön: +1 yükseliş (boğa) · -1 düşüş (ayı) · 0 nötr (yön kırılıma göre)
"""

BULL, BEAR, NEUTRAL = 1, -1, 0


# ───────────────────────────── MUM FORMASYONLARI ─────────────────────────────

def candle_patterns(o, h, l, c, atr, i=None):
    """i. mumda (varsayılan: son mum) biten mum formasyonları: [(ad, yön)]."""
    n = len(c)
    i = n - 1 if i is None else i
    if i < 6:
        return []
    a = atr[i] or (h[i] - l[i]) or 1e-12
    rng = lambda k: h[k] - l[k]
    body = lambda k: abs(c[k] - o[k])
    green = lambda k: c[k] > o[k]
    red = lambda k: c[k] < o[k]
    top = lambda k: max(o[k], c[k])
    bot = lambda k: min(o[k], c[k])
    us = lambda k: h[k] - top(k)          # üst gölge
    ls = lambda k: bot(k) - l[k]          # alt gölge
    mid = lambda k: (o[k] + c[k]) / 2
    doji = lambda k: rng(k) > 0 and body(k) <= 0.1 * rng(k)

    def trend_before(k):
        """k. mumdan önceki 5 mumun yönü: +1 yükseliş, -1 düşüş, 0 yatay."""
        ch = c[k - 1] - c[k - 6]
        return 1 if ch > 0.5 * a else (-1 if ch < -0.5 * a else 0)

    out = []
    r = rng(i)
    tb = trend_before(i)

    # Tek mum (birbirini dışlayan şekiller)
    if r > 0:
        if doji(i):
            if us(i) <= 0.1 * r and ls(i) >= 0.6 * r:
                out.append(("Yusufçuk Doji", BULL))
            elif ls(i) <= 0.1 * r and us(i) >= 0.6 * r:
                out.append(("Mezartaşı Doji", BEAR))
            elif r >= 1.2 * a and us(i) >= 0.3 * r and ls(i) >= 0.3 * r:
                out.append(("Uzun Bacaklı Doji", NEUTRAL))
            else:
                out.append(("Doji", NEUTRAL))
        elif body(i) >= 0.9 * r and r >= 0.8 * a:
            out.append(("Boğa Marubozu", BULL) if green(i) else ("Ayı Marubozu", BEAR))
        elif ls(i) >= 2 * body(i) and us(i) <= 0.15 * r:
            out.append({-1: ("Çekiç", BULL), 1: ("Asılı Adam", BEAR), 0: ("Uzun Alt Gölge", BULL)}[tb])
        elif us(i) >= 2 * body(i) and ls(i) <= 0.15 * r:
            out.append({-1: ("Ters Çekiç", BULL), 1: ("Kayan Yıldız", BEAR), 0: ("Uzun Üst Gölge", BEAR)}[tb])
        elif ls(i) >= 0.6 * r and r >= a:
            out.append(("Uzun Alt Gölge", BULL))
        elif us(i) >= 0.6 * r and r >= a:
            out.append(("Uzun Üst Gölge", BEAR))
        elif body(i) <= 0.3 * r and us(i) >= 0.25 * r and ls(i) >= 0.25 * r:
            out.append(("Topaç", NEUTRAL))

    # İki mum
    p = i - 1
    if red(p) and green(i) and body(i) > body(p) and body(i) >= 0.5 * a and o[i] <= c[p] and c[i] >= o[p]:
        out.append(("Yutan Boğa", BULL))
    if green(p) and red(i) and body(i) > body(p) and body(i) >= 0.5 * a and o[i] >= c[p] and c[i] <= o[p]:
        out.append(("Yutan Ayı", BEAR))
    if red(p) and body(p) >= 0.8 * a and green(i) and top(i) <= o[p] and bot(i) >= c[p] and body(i) <= 0.5 * body(p):
        out.append(("Boğa Harami", BULL))
    if green(p) and body(p) >= 0.8 * a and red(i) and top(i) <= c[p] and bot(i) >= o[p] and body(i) <= 0.5 * body(p):
        out.append(("Ayı Harami", BEAR))
    if (red(p) and body(p) >= 0.8 * a and green(i) and o[i] <= c[p] + 0.02 * a
            and mid(p) < c[i] < o[p]):
        out.append(("Delici Mum", BULL))
    if (green(p) and body(p) >= 0.8 * a and red(i) and o[i] >= c[p] - 0.02 * a
            and o[p] < c[i] < mid(p)):
        out.append(("Kara Bulut", BEAR))
    if (red(p) and green(i) and body(p) >= 0.3 * a and body(i) >= 0.3 * a and abs(l[i] - l[p]) <= 0.1 * a
            and trend_before(p) == -1):
        out.append(("Cımbız Tabanı", BULL))
    if (green(p) and red(i) and body(p) >= 0.3 * a and body(i) >= 0.3 * a and abs(h[i] - h[p]) <= 0.1 * a
            and trend_before(p) == 1):
        out.append(("Cımbız Tavanı", BEAR))
    if red(p) and body(p) >= 0.8 * a and doji(i) and top(i) <= c[p] + 0.05 * a and trend_before(p) == -1:
        out.append(("Yıldız Doji", BULL))
    if green(p) and body(p) >= 0.8 * a and doji(i) and bot(i) >= c[p] - 0.05 * a and trend_before(p) == 1:
        out.append(("Yıldız Doji", BEAR))

    if any(ad == "Yıldız Doji" for ad, _ in out):        # düz doji satırı yıldız dojinin parçası
        out = [x for x in out if x[0] not in ("Doji", "Uzun Bacaklı Doji")]

    # Üç mum
    k0, m = i - 2, i - 1
    if (red(k0) and body(k0) >= 0.8 * a and body(m) <= 0.4 * body(k0) and top(m) <= c[k0] + 0.1 * a
            and green(i) and body(i) >= 0.5 * a and c[i] > mid(k0)):
        out.append(("Sabah Yıldızı", BULL))
    if (green(k0) and body(k0) >= 0.8 * a and body(m) <= 0.4 * body(k0) and bot(m) >= c[k0] - 0.1 * a
            and red(i) and body(i) >= 0.5 * a and c[i] < mid(k0)):
        out.append(("Akşam Yıldızı", BEAR))
    ks = (k0, m, i)
    if (all(green(k) and body(k) >= 0.5 * a and us(k) <= 0.3 * body(k) for k in ks)
            and c[k0] < c[m] < c[i] and all(o[k] >= o[k - 1] and o[k] <= c[k - 1] + 0.1 * a for k in (m, i))):
        out.append(("Üç Yeşil Asker", BULL))
    if (all(red(k) and body(k) >= 0.5 * a and ls(k) <= 0.3 * body(k) for k in ks)
            and c[k0] > c[m] > c[i] and all(o[k] <= o[k - 1] and o[k] >= c[k - 1] - 0.1 * a for k in (m, i))):
        out.append(("Üç Kara Karga", BEAR))
    if (red(k0) and body(k0) >= 0.8 * a and green(m) and top(m) <= o[k0] and bot(m) >= c[k0]
            and body(m) <= 0.5 * body(k0) and green(i) and c[i] > o[k0]):
        out.append(("İçeriden Yükseliş", BULL))
    if (green(k0) and body(k0) >= 0.8 * a and red(m) and top(m) <= c[k0] and bot(m) >= o[k0]
            and body(m) <= 0.5 * body(k0) and red(i) and c[i] < o[k0]):
        out.append(("İçeriden Düşüş", BEAR))

    # Beş mum: 3 Metot
    b0, mids = i - 4, range(i - 3, i)
    if (green(b0) and body(b0) >= a and all(body(k) <= 0.6 * body(b0) and h[k] <= h[b0] and l[k] >= l[b0] for k in mids)
            and sum(red(k) for k in mids) >= 2 and green(i) and body(i) >= 0.7 * a and c[i] > c[b0]):
        out.append(("Yükselen 3 Metot", BULL))
    if (red(b0) and body(b0) >= a and all(body(k) <= 0.6 * body(b0) and h[k] <= h[b0] and l[k] >= l[b0] for k in mids)
            and sum(green(k) for k in mids) >= 2 and red(i) and body(i) >= 0.7 * a and c[i] < c[b0]):
        out.append(("Düşen 3 Metot", BEAR))
    return out


# ───────────────────────────── GRAFİK FORMASYONLARI ─────────────────────────────

def _pivots(h, l, start, end, s=3):
    hi = [k for k in range(max(s, start), end - s) if h[k] == max(h[k - s:k + s + 1]) and h[k] > h[k - 1]]
    lo = [k for k in range(max(s, start), end - s) if l[k] == min(l[k - s:k + s + 1]) and l[k] < l[k - 1]]
    return hi, lo


def _fit(points):
    """En küçük kareler doğrusu: (eğim, kesişim)."""
    n = len(points)
    mx = sum(x for x, _ in points) / n
    my = sum(y for _, y in points) / n
    sxx = sum((x - mx) ** 2 for x, _ in points)
    m = sum((x - mx) * (y - my) for x, y in points) / sxx if sxx else 0.0
    return m, my - m * mx


def _first_break(c, start, end, upper, lower, a):
    """start..end arasında kapanışla ilk kırılım: (mum, +1 yukarı / -1 aşağı) ya da (None, 0)."""
    for k in range(start, end):
        if c[k] > upper(k) + 0.1 * a:
            return k, 1
        if c[k] < lower(k) - 0.1 * a:
            return k, -1
    return None, 0


def chart_patterns(h, l, c, atr, window=150, fresh=10):
    """Grafik formasyonları. Döner: [{ad, yon, durum ('olusuyor' | 'kirildi'), kirilim (+1/-1),
    ust, alt (tetik seviyeleri), hedef}]. Kırılımı `fresh` mumdan eski olanlar yazılmaz."""
    n = len(c)
    if n < 60:
        return []
    a = atr[-1] or 1e-12
    start = max(0, n - window)
    ph, pl = _pivots(h, l, start, n)
    tol = 0.75 * a
    found = []

    def recent(kb):
        return kb is None or kb >= n - fresh

    # ── Tepe / dip formasyonları (OBO, TOBO, üçlü, ikili) ──
    def tops(piv, sgn):
        """sgn=+1 tepeler (OBO, üçlü/ikili tepe), sgn=-1 dipler (TOBO, üçlü/ikili dip)."""
        P = (lambda k: h[k]) if sgn == 1 else (lambda k: l[k])
        Q = (lambda k: l[k]) if sgn == 1 else (lambda k: h[k])
        ext = min if sgn == 1 else max                      # boyun: aradaki en düşük dip (tepeler için)
        beyond = lambda x, y: (x - y) * sgn                  # sgn yönünde ne kadar ötede

        def after_ok(last, lim):
            """Son tepeden sonra fiyat formasyonun en uç noktasını geçmemiş olmalı."""
            seg = range(last + 1, n)
            return all(beyond(P(k), lim) <= tol for k in seg)

        def neck_break(from_k, neck_at):
            for k in range(from_k + 1, n):
                if beyond(neck_at(k), c[k]) > 0.1 * a:
                    return k
            return None

        def came_from(k0, neck):
            """Formasyondan önce fiyat boyun çizgisinin öbür tarafından gelmiş olmalı (önceki trend)."""
            seg = c[max(0, k0 - 30):k0]
            return bool(seg) and any(beyond(neck, x) > 0 for x in seg)

        # OBO / TOBO
        if len(piv) >= 3:
            p1, p2, p3 = piv[-3:]
            n1 = min(range(p1, p2 + 1), key=lambda k: Q(k) * sgn)
            n2 = min(range(p2, p3 + 1), key=lambda k: Q(k) * sgn)
            slope = (Q(n2) - Q(n1)) / (n2 - n1) if n2 != n1 else 0.0
            neck_at = lambda k: Q(n1) + slope * (k - n1)
            height = beyond(P(p2), neck_at(p2))
            sh = min(beyond(P(p1), neck_at(p1)), beyond(P(p3), neck_at(p3)))
            if (height >= 3 * a and beyond(P(p2), max(P(p1), P(p3)) if sgn == 1 else min(P(p1), P(p3))) >= a
                    and abs(P(p1) - P(p3)) <= 0.3 * height and sh >= 0.4 * height
                    and p3 - p1 >= 12 and after_ok(p3, P(p2)) and came_from(p1, neck_at(p1))):
                kb = neck_break(p3, neck_at)
                if recent(kb) and (kb is not None or beyond(c[-1], neck_at(n - 1)) > 0):
                    nk = neck_at(kb if kb is not None else n - 1)
                    found.append({"ad": "OBO" if sgn == 1 else "TOBO", "yon": -sgn,
                                  "durum": "kirildi" if kb is not None else "olusuyor", "kirilim": -sgn if kb else 0,
                                  "seviye": nk, "hedef": nk - sgn * height,
                                  "ciz": {"noktalar": [(p1, P(p1)), (n1, Q(n1)), (p2, P(p2)), (n2, Q(n2)), (p3, P(p3))],
                                          "cizgiler": [((n1, neck_at(n1)), (n - 1, neck_at(n - 1)))], "kb": kb}})
                    return
        # Üçlü tepe / dip
        if len(piv) >= 3:
            p1, p2, p3 = piv[-3:]
            vals = [P(p1), P(p2), P(p3)]
            if max(vals) - min(vals) <= tol and p3 - p1 >= 16:
                neck = ext(Q(k) for k in range(p1, p3 + 1)) if sgn == 1 else max(Q(k) for k in range(p1, p3 + 1))
                height = beyond(sum(vals) / 3, neck)
                lim = max(vals) if sgn == 1 else min(vals)
                if height >= 2.5 * a and after_ok(p3, lim) and came_from(p1, neck):
                    kb = neck_break(p3, lambda k: neck)
                    if recent(kb):
                        found.append({"ad": "Üçlü Tepe" if sgn == 1 else "Üçlü Dip", "yon": -sgn,
                                      "durum": "kirildi" if kb is not None else "olusuyor", "kirilim": -sgn if kb else 0,
                                      "seviye": neck, "hedef": neck - sgn * height,
                                      "ciz": {"noktalar": [(p1, P(p1)), (p2, P(p2)), (p3, P(p3))],
                                              "cizgiler": [((p1, neck), (n - 1, neck))], "kb": kb}})
                        return
        # İkili tepe / dip
        if len(piv) >= 2:
            p1, p2 = piv[-2:]
            if abs(P(p1) - P(p2)) <= tol and 8 <= p2 - p1 <= 100:
                neck = min(Q(k) for k in range(p1, p2 + 1)) if sgn == 1 else max(Q(k) for k in range(p1, p2 + 1))
                height = beyond((P(p1) + P(p2)) / 2, neck)
                lim = max(P(p1), P(p2)) if sgn == 1 else min(P(p1), P(p2))
                if height >= 2.5 * a and after_ok(p2, lim) and came_from(p1, neck):
                    kb = neck_break(p2, lambda k: neck)
                    if recent(kb):
                        found.append({"ad": "İkili Tepe" if sgn == 1 else "İkili Dip", "yon": -sgn,
                                      "durum": "kirildi" if kb is not None else "olusuyor", "kirilim": -sgn if kb else 0,
                                      "seviye": neck, "hedef": neck - sgn * height,
                                      "ciz": {"noktalar": [(p1, P(p1)), (p2, P(p2))],
                                              "cizgiler": [((p1, neck), (n - 1, neck))], "kb": kb}})

    tops(ph, 1)
    tops(pl, -1)

    # ── Üçgen / kama / dikdörtgen ──
    rh = [k for k in ph if k >= n - 100][-3:]
    rl = [k for k in pl if k >= n - 100][-3:]
    if len(rh) >= 2 and len(rl) >= 2:
        mu, bu = _fit([(k, h[k]) for k in rh])
        ml, bl = _fit([(k, l[k]) for k in rl])
        upper = lambda k: mu * k + bu
        lower = lambda k: ml * k + bl
        s0 = min(rh[0], rl[0])
        last_piv = max(rh[-1], rl[-1])
        span = n - 1 - s0
        fit = 0.5 * a                                    # pivotlar çizgiye bu kadar yakın olmalı
        fit_ok = (all(abs(h[k] - upper(k)) <= fit for k in rh) and all(abs(l[k] - lower(k)) <= fit for k in rl))
        # son iki pivotun yönü çizginin yönüyle aynı olmalı: tek bir eski iğne (ör. düz dipler + bir sert iğne)
        # düz bir kenarı yükselen/düşen gibi göstermesin
        cls = lambda d: 0 if abs(d) <= 1.0 else (1 if d > 0 else -1)
        span_ = max(1, n - 1 - min(rh[0], rl[0]))
        for piv, m_, val in ((rh, mu, h), (rl, ml, l)):
            if len(piv) >= 3:
                m2 = (val[piv[-1]] - val[piv[-2]]) / (piv[-1] - piv[-2])
                if cls(m2 * span_ / a) != cls(m_ * span_ / a):
                    fit_ok = False
        ws, we = upper(s0) - lower(s0), upper(n - 1) - lower(n - 1)
        kb, d = _first_break(c, last_piv + 1, n, upper, lower, a)
        inside_end = kb if kb is not None else n
        contained = all(h[k] <= upper(k) + tol and l[k] >= lower(k) - tol for k in range(s0, inside_end))
        if fit_ok and contained and span >= 15 and ws >= 2 * a and we > 0 and recent(kb):
            du, dl = mu * span / a, ml * span / a          # çizgilerin formasyon boyunca değişimi (ATR cinsinden)
            flat = 1.0
            conv = we < 0.8 * ws
            name = None
            if abs(du) <= flat and abs(dl) <= flat:
                name, bias = "Dikdörtgen", NEUTRAL
            elif abs(du) <= flat and dl > flat:
                name, bias = "Yükselen Üçgen", BULL
            elif abs(dl) <= flat and du < -flat:
                name, bias = "Alçalan Üçgen", BEAR
            elif du < -flat and dl > flat:
                name, bias = "Simetrik Üçgen", NEUTRAL
            elif du > flat and dl > flat and conv and dl > du:
                name, bias = "Yükselen Kama", BEAR
            elif du < -flat and dl < -flat and conv and du < dl:
                name, bias = "Alçalan Kama", BULL
            if name:
                found.append({"ad": name, "yon": bias, "durum": "kirildi" if kb is not None else "olusuyor",
                              "kirilim": d, "ust": upper(kb if kb is not None else n - 1),
                              "alt": lower(kb if kb is not None else n - 1),
                              "hedef": ((upper(kb) if d == 1 else lower(kb)) + d * ws) if kb is not None else None,
                              "ciz": {"noktalar": [(k, h[k]) for k in rh] + [(k, l[k]) for k in rl],
                                      "cizgiler": [((s0, upper(s0)), (n - 1, upper(n - 1))),
                                                   ((s0, lower(s0)), (n - 1, lower(n - 1)))], "kb": kb}})

    # ── Bayrak / flama ──
    best = None
    for mlen in range(5, 21):
        s = n - 1 - mlen                 # direğin son mumu
        cons = range(s + 1, n - 1)       # sıkışma (son mum hariç: kırılım mumu olabilir)
        if s < 15 or len(cons) < 4:
            continue
        hi = max(h[k] for k in cons)
        lo = min(l[k] for k in cons)
        for plen in range(3, 13):
            move = c[s] - c[s - plen]
            if abs(move) < 4 * a:
                continue
            sgn = 1 if move > 0 else -1
            pole_ext = max(h[s - plen:s + 1]) if sgn == 1 else min(l[s - plen:s + 1])
            if hi - lo > 0.5 * abs(move):
                continue
            if sgn == 1 and (lo < c[s] - 0.5 * move or hi > pole_ext + 0.2 * a):
                continue
            if sgn == -1 and (hi > c[s] - 0.5 * move or lo < pole_ext - 0.2 * a):
                continue
            last = c[n - 1]
            if (sgn == 1 and last < lo) or (sgn == -1 and last > hi):
                continue                   # ters yöne bozuldu
            score = abs(move) / a
            if best is None or score > best[0]:
                best = (score, sgn, s, plen, list(cons), hi, lo, move)
    if best:
        _, sgn, s, plen, cons, hi, lo, move = best
        mh, _ = _fit([(k, h[k]) for k in cons])
        ml_, _ = _fit([(k, l[k]) for k in cons])
        flama = mh < 0 < ml_                                     # daralan küçük üçgen (tepeler iner, dipler yükselir)
        broke = (c[n - 1] > hi + 0.1 * a) if sgn == 1 else (c[n - 1] < lo - 0.1 * a)
        name = ("Yükselen " if sgn == 1 else "Düşen ") + ("Flama" if flama else "Bayrak")
        lvl = hi if sgn == 1 else lo
        found.append({"ad": name, "yon": sgn, "durum": "kirildi" if broke else "olusuyor",
                      "kirilim": sgn if broke else 0, "seviye": lvl, "hedef": lvl + move,
                      "ciz": {"noktalar": [], "cizgiler": [((s - plen, c[s - plen]), (s, c[s])),
                                                           ((cons[0], hi), (n - 1, hi)), ((cons[0], lo), (n - 1, lo))],
                              "kb": n - 1 if broke else None}})

    # ── Fincan kulp / ters fincan kulp ──
    for piv, sgn in ((ph, 1), (pl, -1)):
        P = (lambda k: h[k]) if sgn == 1 else (lambda k: l[k])
        Q = (lambda k: l[k]) if sgn == 1 else (lambda k: h[k])
        done = False
        for j2 in range(len(piv) - 1, -1, -1):
            r2 = piv[j2]
            hl = n - 1 - r2                                   # kulp uzunluğu
            if hl < 3:
                continue
            for j1 in range(j2 - 1, -1, -1):
                r1 = piv[j1]
                span = r2 - r1
                if span < 20 or span > 120:
                    continue
                rim = (P(r1) + P(r2)) / 2
                bk = (min if sgn == 1 else max)(range(r1, r2 + 1), key=Q)
                depth = (rim - Q(bk)) * sgn
                if depth < 4 * a or abs(P(r1) - P(r2)) > max(tol, 0.15 * depth):
                    continue
                if not 0.3 <= (bk - r1) / span <= 0.7:
                    continue
                if any((P(k) - rim) * sgn > max(tol, 0.15 * depth) for k in range(r1 + 1, r2)):
                    continue
                low_zone = sum(1 for k in range(r1, r2 + 1) if (Q(k) - Q(bk)) * sgn <= depth / 3)
                if low_zone < 0.2 * span or hl > max(5, span // 3):
                    continue
                handle = range(r2 + 1, n)
                hq = (min if sgn == 1 else max)(Q(k) for k in handle)
                if (rim - hq) * sgn > 0.5 * depth:
                    continue
                broke = (c[n - 1] - rim) * sgn > 0.1 * a
                if any((c[k] - rim) * sgn > 0.1 * a for k in range(r2 + 1, n - 1)):
                    continue                                   # daha önce kırılmış (eski)
                found.append({"ad": "Fincan Kulp" if sgn == 1 else "Ters Fincan Kulp", "yon": sgn,
                              "durum": "kirildi" if broke else "olusuyor", "kirilim": sgn if broke else 0,
                              "seviye": rim, "hedef": rim + sgn * depth,
                              "ciz": {"noktalar": [(r1, P(r1)), (bk, Q(bk)), (r2, P(r2))],
                                      "cizgiler": [((r1, rim), (n - 1, rim))], "kb": n - 1 if broke else None}})
                done = True
                break
            if done or j2 < len(piv) - 1:
                break
    return _prioritize(found)


TOPS = {"İkili Tepe", "Üçlü Tepe", "OBO"}
BOTTOMS = {"İkili Dip", "Üçlü Dip", "TOBO"}
BOXES = {"Dikdörtgen", "Yükselen Üçgen", "Alçalan Üçgen", "Simetrik Üçgen", "Yükselen Kama", "Alçalan Kama"}
FLAGS = {"Yükselen Bayrak", "Yükselen Flama", "Düşen Bayrak", "Düşen Flama"}
CUPS = {"Fincan Kulp", "Ters Fincan Kulp"}


def _prioritize(found):
    """Aynı fiyat hareketini anlatan çakışan formasyonlardan daha özel olanı bırakır."""
    names = {g["ad"] for g in found}
    drop = set()
    if names & CUPS:
        drop |= TOPS | BOTTOMS | BOXES
    if "Yükselen Üçgen" in names:
        drop |= TOPS
    if "Alçalan Üçgen" in names:
        drop |= BOTTOMS
    if "Dikdörtgen" in names:      # yatay kanal: kırılmış tepe/dip daha özel, oluşan tepe/dip ise dikdörtgenin kenarı
        if any(g["ad"] in TOPS | BOTTOMS and g["durum"] == "kirildi" for g in found):
            drop.add("Dikdörtgen")
        else:
            found = [g for g in found if not (g["ad"] in TOPS | BOTTOMS and g["durum"] == "olusuyor")]
    if names & BOXES:
        drop |= FLAGS
    return [g for g in found if g["ad"] not in drop]
