"""
Teknik indikatörler (saf Python, ek paket gerektirmez).

Tüm fonksiyonlar girdi listesiyle aynı uzunlukta liste döndürür.
Yeterli veri olmayan başlangıç noktaları None olur.
Hesaplamalar TradingView'daki varsayılan formüllerle uyumludur
(RSI/ATR/ADX için Wilder RMA, Supertrend için RMA tabanlı ATR vb.).
"""

from math import sqrt


# --------------------------------------------------------------------------- #
# Temel yardımcılar
# --------------------------------------------------------------------------- #
def _first_run(values, n):
    """Arka arkaya n adet None olmayan değerin başladığı ilk indeksi bulur."""
    run = 0
    for i, v in enumerate(values):
        run = run + 1 if v is not None else 0
        if run == n:
            return i - n + 1
    return None


def sma(values, n):
    out = [None] * len(values)
    start = _first_run(values, n)
    if start is None:
        return out
    s = sum(values[start:start + n])
    out[start + n - 1] = s / n
    for i in range(start + n, len(values)):
        if values[i] is None or values[i - n] is None:
            continue
        s += values[i] - values[i - n]
        out[i] = s / n
    return out


def ema(values, n):
    out = [None] * len(values)
    start = _first_run(values, n)
    if start is None:
        return out
    k = 2 / (n + 1)
    prev = sum(values[start:start + n]) / n
    out[start + n - 1] = prev
    for i in range(start + n, len(values)):
        if values[i] is None:
            out[i] = prev
            continue
        prev = values[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def rma(values, n):
    """Wilder hareketli ortalaması (TradingView ta.rma)."""
    out = [None] * len(values)
    start = _first_run(values, n)
    if start is None:
        return out
    prev = sum(values[start:start + n]) / n
    out[start + n - 1] = prev
    for i in range(start + n, len(values)):
        if values[i] is None:
            out[i] = prev
            continue
        prev = (prev * (n - 1) + values[i]) / n
        out[i] = prev
    return out


def _window_apply(values, n, fn):
    out = [None] * len(values)
    for i in range(n - 1, len(values)):
        w = values[i - n + 1:i + 1]
        if any(x is None for x in w):
            continue
        out[i] = fn(w)
    return out


def highest(values, n):
    return _window_apply(values, n, max)


def lowest(values, n):
    return _window_apply(values, n, min)


def stdev(values, n):
    """Popülasyon standart sapması (TradingView ta.stdev)."""
    def f(w):
        m = sum(w) / len(w)
        return sqrt(sum((x - m) ** 2 for x in w) / len(w))
    return _window_apply(values, n, f)


# --------------------------------------------------------------------------- #
# İndikatörler
# --------------------------------------------------------------------------- #
def rsi(close, n=14):
    gains, losses = [None], [None]
    for i in range(1, len(close)):
        d = close[i] - close[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    ag, al = rma(gains, n), rma(losses, n)
    out = [None] * len(close)
    for i in range(len(close)):
        if ag[i] is None or al[i] is None:
            continue
        if al[i] == 0:
            out[i] = 100.0 if ag[i] > 0 else 50.0
        else:
            out[i] = 100 - 100 / (1 + ag[i] / al[i])
    return out


def stoch_rsi(close, rsi_len=14, stoch_len=14, k_len=3, d_len=3):
    r = rsi(close, rsi_len)
    lo, hi = lowest(r, stoch_len), highest(r, stoch_len)
    raw = [None] * len(close)
    for i in range(len(close)):
        if r[i] is None or lo[i] is None or hi[i] is None:
            continue
        rng = hi[i] - lo[i]
        raw[i] = 50.0 if rng == 0 else (r[i] - lo[i]) / rng * 100
    k = sma(raw, k_len)
    d = sma(k, d_len)
    return k, d


def macd(close, fast=12, slow=26, signal=9):
    ef, es = ema(close, fast), ema(close, slow)
    line = [None if a is None or b is None else a - b for a, b in zip(ef, es)]
    sig = ema(line, signal)
    hist = [None if a is None or b is None else a - b for a, b in zip(line, sig)]
    return line, sig, hist


def true_range(high, low, close):
    tr = [high[0] - low[0]]
    for i in range(1, len(close)):
        tr.append(max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1])))
    return tr


def atr(high, low, close, n=14):
    return rma(true_range(high, low, close), n)


def supertrend(high, low, close, period=10, mult=3.0):
    """Döner: (yön listesi [+1 yükseliş / -1 düşüş], çizgi listesi)."""
    a = atr(high, low, close, period)
    size = len(close)
    direction, line = [None] * size, [None] * size
    up_prev = dn_prev = None
    trend = 1
    for i in range(size):
        if a[i] is None:
            continue
        hl2 = (high[i] + low[i]) / 2
        up, dn = hl2 - mult * a[i], hl2 + mult * a[i]
        if up_prev is not None:
            up = max(up, up_prev) if close[i - 1] > up_prev else up
            dn = min(dn, dn_prev) if close[i - 1] < dn_prev else dn
            if trend == -1 and close[i] > dn_prev:
                trend = 1
            elif trend == 1 and close[i] < up_prev:
                trend = -1
        direction[i] = trend
        line[i] = up if trend == 1 else dn
        up_prev, dn_prev = up, dn
    return direction, line


def momentum(close, n=10):
    return [None if i < n else close[i] - close[i - n] for i in range(len(close))]


def adx(high, low, close, n=14):
    """Döner: (adx, +DI, -DI)."""
    size = len(close)
    pdm, ndm = [None], [None]
    for i in range(1, size):
        up, down = high[i] - high[i - 1], low[i - 1] - low[i]
        pdm.append(up if up > down and up > 0 else 0.0)
        ndm.append(down if down > up and down > 0 else 0.0)
    tr = [None] + true_range(high, low, close)[1:]
    str_, spdm, sndm = rma(tr, n), rma(pdm, n), rma(ndm, n)
    pdi, ndi, dx = [None] * size, [None] * size, [None] * size
    for i in range(size):
        if str_[i] in (None, 0) or spdm[i] is None or sndm[i] is None:
            continue
        pdi[i] = 100 * spdm[i] / str_[i]
        ndi[i] = 100 * sndm[i] / str_[i]
        s = pdi[i] + ndi[i]
        dx[i] = 0.0 if s == 0 else 100 * abs(pdi[i] - ndi[i]) / s
    return rma(dx, n), pdi, ndi


def obv(close, volume):
    out = [0.0]
    for i in range(1, len(close)):
        if close[i] > close[i - 1]:
            out.append(out[-1] + volume[i])
        elif close[i] < close[i - 1]:
            out.append(out[-1] - volume[i])
        else:
            out.append(out[-1])
    return out


def cci(high, low, close, n=20):
    tp = [(h + l + c) / 3 for h, l, c in zip(high, low, close)]
    m = sma(tp, n)
    out = [None] * len(close)
    for i in range(n - 1, len(close)):
        w = tp[i - n + 1:i + 1]
        md = sum(abs(x - m[i]) for x in w) / n
        out[i] = 0.0 if md == 0 else (tp[i] - m[i]) / (0.015 * md)
    return out


def vwap_daily(open_times_ms, high, low, close, volume):
    """Her UTC gün başında sıfırlanan VWAP (TradingView varsayılanı)."""
    out = []
    day = None
    pv = vv = 0.0
    for t, h, l, c, v in zip(open_times_ms, high, low, close, volume):
        d = t // 86_400_000
        if d != day:
            day, pv, vv = d, 0.0, 0.0
        tp = (h + l + c) / 3
        pv += tp * v
        vv += v
        out.append(tp if vv == 0 else pv / vv)
    return out


def bollinger(close, n=20, k=2.0):
    """Döner: (orta, üst, alt, bant genişliği oranı)."""
    mid, sd = sma(close, n), stdev(close, n)
    upper, lower, bw = [None] * len(close), [None] * len(close), [None] * len(close)
    for i in range(len(close)):
        if mid[i] is None or sd[i] is None:
            continue
        upper[i] = mid[i] + k * sd[i]
        lower[i] = mid[i] - k * sd[i]
        bw[i] = 0.0 if mid[i] == 0 else (upper[i] - lower[i]) / mid[i]
    return mid, upper, lower, bw


def ichimoku(high, low, tenkan_n=9, kijun_n=26, senkou_b_n=52, shift=26):
    """Ichimoku. Döner: (tenkan, kijun, bulut_üst, bulut_alt).
    Bulut değerleri i. mum için geçerli olanlardır (26 mum önce hesaplanıp ileri kaydırılmış)."""
    def mid(n):
        hh, ll = highest(high, n), lowest(low, n)
        return [None if a is None or b is None else (a + b) / 2 for a, b in zip(hh, ll)]
    tenkan, kijun, sb = mid(tenkan_n), mid(kijun_n), mid(senkou_b_n)
    sa = [None if a is None or b is None else (a + b) / 2 for a, b in zip(tenkan, kijun)]
    size = len(high)
    top, bottom = [None] * size, [None] * size
    for i in range(shift, size):
        a, b = sa[i - shift], sb[i - shift]
        if a is not None and b is not None:
            top[i], bottom[i] = max(a, b), min(a, b)
    return tenkan, kijun, top, bottom


def band_retest(high, low, close, upper, lower, break_window=20, window=10, tol_atr=0.25, atr_len=14, away_atr=2.5,
                detach_atr=0.5):
    """Hareketli bir çizgi (Tenkan / Kijun: upper == lower) ya da bant (Ichimoku bulutu: üst / alt) için kırılım ve retest.
    Fiyatın tarafı: kapanış üstün üstünde → yukarı, altın altında → aşağı, arada → içeride.
    1) KIRILIM ("break"): fiyat son `break_window` mum içinde bu tarafa geçti (en son geçiş esas alınır).
       state: "none" retest yok · "touch" fiyat geri gelip çizgiye/banda iğneyle dokundu ve kırılım tarafında kapandı ·
              "confirmed" sonra dokunan mumun tepesi (yukarı) / dibi (aşağı) kapanışla geçildi ·
              "away" retest gelmeden fiyat away_atr x ATR'den fazla uzaklaştı.
    2) TEPKİ ("hold"): yakın zamanda kırılım yok; son `window` mumda fiyat çizgiye geri çekilip dokundu ve aynı tarafta kaldı
       (destek / direnç testi). state: "touch" / "confirmed".
    3) "trend": fiyat uzun süredir aynı tarafta, yakın zamanda dokunuş yok.   4) "inside": fiyat bulutun içinde.
    Dokunuşun retest sayılması için fiyat önce (kapanışla) çizgiden/banttan en az detach_atr x ATR uzaklaşmış olmalı.
    Döner: None | {"kind": ..., "dir": "up"|"down", "state": str, "bars_ago": int}"""
    n = len(close)
    a = atr(high, low, close, atr_len)

    def side(k):
        if upper[k] is None or lower[k] is None:
            return None
        return 1 if close[k] > upper[k] else (-1 if close[k] < lower[k] else 0)

    last = n - 1
    s = side(last)
    if s is None or a[last] is None:
        return None
    if s == 0:
        return {"kind": "inside", "dir": None, "state": None, "bars_ago": 0}
    d = "up" if s == 1 else "down"
    edge = lambda k: upper[k] if s == 1 else lower[k]          # fiyatın bulunduğu taraftaki kenar
    hits = lambda k: (low[k] <= edge(k) + (a[k] or 0) * tol_atr) if s == 1 else (high[k] >= edge(k) - (a[k] or 0) * tol_atr)
    beyond = lambda k, t: close[k] > high[t] if s == 1 else close[k] < low[t]
    far = lambda m: (a[m] is not None and edge(m) is not None
                     and ((close[m] - edge(m)) if s == 1 else (edge(m) - close[m])) >= detach_atr * a[m])   # kapanışla
    brk = last
    while brk - 1 >= 0 and side(brk - 1) == s:
        brk -= 1
    if brk > 0 and side(brk - 1) is not None and last - brk <= break_window:
        state, touch, moved = "none", None, False
        for k in range(brk + 1, n):
            moved = moved or far(k - 1)
            if touch is None:
                if moved and hits(k):
                    touch, state = k, "touch"
            elif beyond(k, touch):
                state = "confirmed"
                break
        if state == "none" and abs(close[last] - edge(last)) > away_atr * a[last]:
            state = "away"
        return {"kind": "break", "dir": d, "state": state, "bars_ago": last - brk}
    touch = next((k for k in range(last, max(brk, last - window), -1)
                  if hits(k) and any(far(m) for m in range(max(0, k - window), k))), None)
    if touch is None:
        return {"kind": "trend", "dir": d, "state": None, "bars_ago": 0}
    state = "confirmed" if any(beyond(k, touch) for k in range(touch + 1, n)) else "touch"
    return {"kind": "hold", "dir": d, "state": state, "bars_ago": last - touch}


def rsi_divergence(high, low, close, rsi_len=14, left=5, right=5, range_min=5, range_max=60, recent=10):
    """TradingView RSI uyumsuzluk mantığı (normal uyumsuzluk):
      pozitif: RSI pivot dibi bir öncekinden YÜKSEK, fiyat dibi bir öncekinden DÜŞÜK
      negatif: RSI pivot tepesi bir öncekinden DÜŞÜK, fiyat tepesi bir öncekinden YÜKSEK
    Pivot, solunda `left` ve sağında `right` mum olan yerel dip/tepedir (sağdaki mumlar kapanınca kesinleşir).
    Sadece son pivot yeterince yeniyse (son `right + recent` mum içinde) uyumsuzluk 'var' sayılır.
    Döner: (pozitif_var, negatif_var)
    """
    r = rsi(close, rsi_len)
    n = len(close)
    lows, highs = [], []
    for p in range(left, n - right):
        w = r[p - left:p + right + 1]
        if r[p] is None or any(x is None for x in w):
            continue
        if r[p] == min(w):
            lows.append(p)
        if r[p] == max(w):
            highs.append(p)
    cutoff = n - 1 - right - recent

    def check(pivots, bullish):
        if len(pivots) < 2 or pivots[-1] < cutoff:
            return False
        p2, p1 = pivots[-1], pivots[-2]
        if not (range_min <= p2 - p1 <= range_max):
            return False
        if bullish:
            return r[p2] > r[p1] and low[p2] < low[p1]
        return r[p2] < r[p1] and high[p2] > high[p1]

    return check(lows, True), check(highs, False)


def order_blocks(open_, high, low, close, atr_, s, end, lookback=300, disp_atr=2.0, bos_lookback=10):
    """Tüketilmemiş order block'lar (end indeksine kadar; end dahil değil).
    s=1 boğa OB: son kırmızı mum; sonraki 3 mumdan birinin kapanışı o mumun kapanışından ≥ disp_atr × ATR yukarıda
        ve önceki bos_lookback mumun tepesinin üstünde (yapı kırılımı). Bölge: mumun dibi–tepesi.
        Sonradan bir kapanış bölgenin dibinin altına inerse tüketilmiş sayılır.
    s=-1 ayı OB: tersi. Döner: [(alt, üst, indeks)]"""
    start = max(bos_lookback, end - lookback)
    obs = []
    for k in range(start, end - 3):
        a = atr_[k]
        if not a or (close[k] - open_[k]) * s >= 0:
            continue
        nxt = close[k + 1:k + 4]
        ref = max(high[k - bos_lookback:k]) if s == 1 else min(low[k - bos_lookback:k])
        if s == 1:
            ok = max(nxt) - close[k] >= disp_atr * a and max(nxt) > ref
        else:
            ok = close[k] - min(nxt) >= disp_atr * a and min(nxt) < ref
        if not ok:
            continue
        lo, hi = low[k], high[k]
        if any((close[m] < lo) if s == 1 else (close[m] > hi) for m in range(k + 4, end)):
            continue                                       # tüketildi
        obs.append((lo, hi, k))
    return obs


def swing_anchor(high, low, lookback=300):
    """Son `lookback` mumdaki en yüksek tepe ile en düşük dipten daha eski olanın indeksi (son büyük salınımın başı).
    Hacim profili bu mumdan son muma kadar hesaplanır."""
    n = len(high)
    s = max(0, n - lookback)
    ih = max(range(s, n), key=lambda k: high[k])
    il = min(range(s, n), key=lambda k: low[k])
    return min(ih, il)


def volume_profile(high, low, volume, rows=24, value_area=0.70):
    """Hacim profili (TradingView Volume Profile mantığı).
    Her mumun hacmi, mumun düşük–yüksek aralığına düşen satırlara orantılı dağıtılır.
    Döner: (VAH, POC, VAL) veya veri yoksa None.
    """
    if not high:
        return None
    lo, hi = min(low), max(high)
    if hi <= lo:
        return None
    step = (hi - lo) / rows
    bins = [0.0] * rows
    for h, l, v in zip(high, low, volume):
        if v <= 0:
            continue
        if h <= l:
            k = min(rows - 1, int((h - lo) / step))
            bins[k] += v
            continue
        for k in range(max(0, int((l - lo) / step)), min(rows - 1, int((h - lo) / step)) + 1):
            b_lo, b_hi = lo + k * step, lo + (k + 1) * step
            overlap = min(h, b_hi) - max(l, b_lo)
            if overlap > 0:
                bins[k] += v * overlap / (h - l)
    total = sum(bins)
    if total <= 0:
        return None
    poc = max(range(rows), key=lambda k: bins[k])
    a = b = poc
    acc = bins[poc]
    while acc < value_area * total and (a > 0 or b < rows - 1):
        up = bins[b + 1] if b < rows - 1 else -1
        dn = bins[a - 1] if a > 0 else -1
        if up >= dn:
            b += 1
            acc += up
        else:
            a -= 1
            acc += dn
    # VAH / POC / VAL satırların orta noktası (Teometric Demand Model / TradingView etiketleriyle aynı)
    vah = lo + (b + 0.5) * step
    val = lo + (a + 0.5) * step
    poc_price = lo + (poc + 0.5) * step
    return vah, poc_price, val


def cmf(high, low, close, volume, n=20):
    """Chaikin Money Flow: sum(MFM × hacim, n) / sum(hacim, n); MFM = ((c-l) - (h-c)) / (h-l)."""
    mfv = []
    for h, l, c, v in zip(high, low, close, volume):
        mfm = 0.0 if h == l else ((c - l) - (h - c)) / (h - l)
        mfv.append(mfm * v)
    out = [None] * len(close)
    for i in range(n - 1, len(close)):
        vs = sum(volume[i - n + 1:i + 1])
        out[i] = 0.0 if vs == 0 else sum(mfv[i - n + 1:i + 1]) / vs
    return out


def ewo(close, fast=5, slow=35):
    """Elliott Wave Oscillator: SMA(fast) - SMA(slow)."""
    a, b = sma(close, fast), sma(close, slow)
    return [None if x is None or y is None else x - y for x, y in zip(a, b)]


def wavetrend(high, low, close, n1=10, n2=21):
    """WaveTrend Oscillator (LazyBear):
    ap = hlc3, esa = EMA(ap, n1), d = EMA(|ap - esa|, n1), ci = (ap - esa) / (0.015 × d),
    wt1 = EMA(ci, n2), wt2 = SMA(wt1, 4). Döner: (wt1, wt2)."""
    ap = [(h + l + c) / 3 for h, l, c in zip(high, low, close)]
    esa = ema(ap, n1)
    dev = [None if e is None else abs(a - e) for a, e in zip(ap, esa)]
    d = ema(dev, n1)
    ci = [None if e is None or dd is None else (0.0 if dd == 0 else (a - e) / (0.015 * dd))
          for a, e, dd in zip(ap, esa, d)]
    wt1 = ema(ci, n2)
    wt2 = sma(wt1, 4)
    return wt1, wt2


def crossed_above(a, b, i):
    """a, i. mumda b'yi yukarı kesti mi?"""
    if i < 1 or None in (a[i], b[i], a[i - 1], b[i - 1]):
        return False
    return a[i - 1] <= b[i - 1] and a[i] > b[i]


def crossed_below(a, b, i):
    if i < 1 or None in (a[i], b[i], a[i - 1], b[i - 1]):
        return False
    return a[i - 1] >= b[i - 1] and a[i] < b[i]



def dynarange(open_, high, low, close, fast=10, slow=18):
    """DynaRange Oscillator (kullanıcının TradingView göstergesi):
    diff = EMA(ohlc4, 10) - EMA(ohlc4, 18); 0 üstü yükseliş (AL), 0 altı düşüş (SAT)."""
    src = [(o + h + l + c) / 4 for o, h, l, c in zip(open_, high, low, close)]
    ef, es = ema(src, fast), ema(src, slow)
    return [a - b if a is not None and b is not None else None for a, b in zip(ef, es)]


def trendflex(high, low, close, factor=4.0, atr_len=11):
    """TrendFlex_Algo (kullanıcının TradingView göstergesi) – mum rengi.
    Kapanış fiyatı üzerinden Supertrend (çarpan 4, ATR 11); kapanış çizginin üstündeyse
    mum yeşil (+1 AL), altındaysa kırmızı (-1 SAT). Pine kodundaki supertrend() birebir.
    Döner: (renk listesi, çizgi listesi)."""
    n = len(close)
    a = atr(high, low, close, atr_len)
    out, line = [None] * n, [None] * n
    up_f = lo_f = st_prev = None
    for i in range(n):
        if a[i] is None:
            continue
        up, lo = close[i] + factor * a[i], close[i] - factor * a[i]
        p_lo = lo_f if lo_f is not None else 0.0
        p_up = up_f if up_f is not None else 0.0
        c1 = close[i - 1] if i > 0 else close[i]
        lo_new = lo if (lo > p_lo or c1 < p_lo) else p_lo
        up_new = up if (up < p_up or c1 > p_up) else p_up
        if i == 0 or a[i - 1] is None:
            d = 1
        elif st_prev == p_up:
            d = -1 if close[i] > up_new else 1
        else:
            d = 1 if close[i] < lo_new else -1
        st = lo_new if d == -1 else up_new
        out[i] = 1 if close[i] > st else -1
        line[i] = st
        up_f, lo_f, st_prev = up_new, lo_new, st
    return out, line


def trendflex_signal(close, line, sma, i):
    """TrendFlex_Algo _BUY / SELL etiketi (i. mum kapanışında):
    AL : kapanış çizgiyi yukarı keser (ta.crossover) ve kapanış >= SMA13
    SAT: kapanış çizgiyi aşağı keser (ta.crossunder) ve kapanış <= SMA13
    Döner: +1, -1 veya 0."""
    if i < 1 or None in (line[i], line[i - 1], sma[i]):
        return 0
    if close[i] > line[i] and close[i - 1] <= line[i - 1] and close[i] >= sma[i]:
        return 1
    if close[i] < line[i] and close[i - 1] >= line[i - 1] and close[i] <= sma[i]:
        return -1
    return 0


def _pivots(vals, left, right, kind):
    """Onaylanmış pivot noktaları (indeks listesi). kind='low' dip, 'high' tepe."""
    out = []
    for j in range(left, len(vals) - right):
        win = vals[j - left:j + right + 1]
        if (kind == "low" and vals[j] == min(win)) or (kind == "high" and vals[j] == max(win)):
            if not out or j - out[-1] > right:      # aynı bölgedeki tekrarları at
                out.append(j)
    return out


def trendline_break(high, low, close, left=5, right=5, recent=20, tol_atr=0.25, atr_len=14, away_atr=2.5,
                    detach_atr=0.5):
    """Yükselen / düşen trend çizgisi kırılımı ve retest.
    Yükselen çizgi: son iki dip (ikincisi daha yüksek) birleştirilir. Kapanış çizginin altına inerse KIRILDI (düşüş).
    Düşen çizgi  : son iki tepe (ikincisi daha alçak) birleştirilir. Kapanış çizginin üstüne çıkarsa KIRILDI (yükseliş).
    Kırılım son `recent` mum içinde olmalı ve son kapanış hâlâ kırılım tarafında olmalı.
    Fiyat kırılımdan sonra çizginin öbür tarafına geri kapanış yaptıysa (sahte kırılım) en son kırılım esas alınır.
    Retest gelmeden fiyat çizgiden away_atr x ATR'den fazla uzaklaştıysa retest "away" olur.
    Dokunuşun retest sayılması için fiyat önce (kapanışla) çizgiden en az detach_atr x ATR uzaklaşmış olmalı (çizgi boyunca
    sürünen fiyat retest sayılmaz).
    Retest: kırılımdan sonra fiyat çizgiye geri dönüp (tolerans tol_atr x ATR) dokunmuş ve yine kırılım tarafında kapanmış;
    ardından fiyat kırılım yönünde devam ettiyse (retest mumunun tepesi/dibi kapanışla geçildi) retest teyit edilmiştir.
    Döner: [{"type": "rising"|"falling", "retest": "none"|"touch"|"confirmed", "bars_ago": int}]"""
    n = len(close)
    if n < left + right + 20:
        return []
    a = atr(high, low, close, atr_len)
    out = []
    for kind, src in (("rising", low), ("falling", high)):
        piv = _pivots(src, left, right, "low" if kind == "rising" else "high")
        if len(piv) < 2:
            continue
        p1, p2 = piv[-2], piv[-1]
        if kind == "rising" and not src[p2] > src[p1]:
            continue
        if kind == "falling" and not src[p2] < src[p1]:
            continue
        slope = (src[p2] - src[p1]) / (p2 - p1)
        line = lambda k: src[p2] + slope * (k - p2)
        # geçerli çizgi: iki pivot arasında hiçbir mum çizginin öbür tarafında kapanmamış olmalı
        if any((kind == "rising" and close[k] < line(k)) or (kind == "falling" and close[k] > line(k))
               for k in range(p1 + 1, p2)):
            continue
        side = lambda k: (kind == "rising" and close[k] < line(k)) or (kind == "falling" and close[k] > line(k))
        last = n - 1
        if last <= p2 or not side(last):
            continue                                    # kırılım yok ya da geri alındı – yazma
        brk = last                                      # en son kırılım: son kapanışa kadar kesintisiz süren kırılımın ilk mumu
        while brk - 1 > p2 and side(brk - 1):
            brk -= 1
        if last - brk > recent:
            continue
        # Retest: kırılımdan sonra fiyat çizgiye geri gelir (tolerans tol_atr x ATR) ve mum kırılım tarafında kapanır.
        # Teyit: sonraki bir mum, retest mumunun tepesinin üstünde (düşen çizgi kırılımı → yükseliş)
        # ya da dibinin altında (yükselen çizgi kırılımı → düşüş) kapanır.
        state, touch, moved = "none", None, False
        for k in range(brk + 1, n):
            m = k - 1                                   # önceki mum çizgiden yeterince uzaklaştı mı
            far = (line(m) - close[m]) if kind == "rising" else (close[m] - line(m))      # kapanışla uzaklaşma
            if a[m] and far >= detach_atr * a[m]:
                moved = True
            tol = (a[k] or 0) * tol_atr
            if touch is None:
                if moved and kind == "rising" and high[k] >= line(k) - tol and close[k] < line(k):
                    touch = k
                if moved and kind == "falling" and low[k] <= line(k) + tol and close[k] > line(k):
                    touch = k
                if touch is not None:
                    state = "touch"
            elif (kind == "falling" and close[k] > high[touch]) or (kind == "rising" and close[k] < low[touch]):
                state = "confirmed"
                break
        if state == "none" and a[last] and abs(close[last] - line(last)) > away_atr * a[last]:
            state = "away"                              # retest gelmeden fiyat çizgiden uzaklaştı
        retest = state
        out.append({"type": kind, "retest": retest, "bars_ago": last - brk})
    return out



def level_retest(high, low, close, level, window=10, tol_atr=0.25, atr_len=14, open_=None,
                 near_atr=1.5, break_window=20, break_near_atr=2.5, detach_atr=0.5):
    """Bir fiyat seviyesinde (VAH/POC/VAL) son durum. İki tür olay:
    1) KIRILIM ("break"): son `break_window` mumda bir mum seviyeyi kapanışla kesti ve fiyat hâlâ o tarafta.
       state: "none"  – fiyat kırılan seviyeye geri gelmedi (retest yok, bekle)
              "touch" – geri geldi, dokundu ve kırılım tarafında kapandı (retest yapılıyor)
              "confirmed" – sonra dokunan mumun dibi (aşağı kırılım) / tepesi (yukarı kırılım) kapanışla geçildi
              "away"  – retest gelmeden fiyat seviyeden break_near_atr x ATR'den fazla uzaklaştı
    2) TEPKİ ("hold"): kırılım yok; son `window` mumda fiyat seviyeye iğneyle dokundu (açılış ve kapanış aynı tarafta).
       state: "touch" – tepki bekleniyor; "confirmed" – sonraki mum seviyeden uzaklaşan yönde, dokunan mumun
              tepesi/dibi ötesinde kapandı.
    Fiyat seviyeye yakın değilse (near_atr / break_near_atr x ATR) None.
    Dokunuşun retest sayılması için fiyat önce (kapanışla) seviyeden en az detach_atr x ATR uzaklaşmış olmalı.
    Döner: None | {"kind": "break"|"hold", "dir": "up"|"down", "state": str, "bars_ago": int}"""
    n = len(close)
    if n < atr_len + max(window, break_window) + 2:
        return None
    a = atr(high, low, close, atr_len)
    if a[-1] is None:
        return None
    op = open_ if open_ is not None else [close[k - 1] if k else close[k] for k in range(n)]
    dist = abs(close[-1] - level)

    # 1) son kırılım mumu
    brk = None
    for k in range(n - 1, n - 1 - break_window, -1):
        prev = close[k - 1]
        if (op[k] - level) * (close[k] - level) < 0 or (prev - level) * (close[k] - level) < 0:
            brk = k
            break
    if brk is not None:
        d = "down" if close[brk] < level else "up"
        state, touch, moved = "none", None, False
        for k in range(brk + 1, n):
            m = k - 1
            far = (level - close[m]) if d == "down" else (close[m] - level)          # kapanışla uzaklaşma
            if a[m] and far >= detach_atr * a[m]:
                moved = True
            tol = (a[k] or 0) * tol_atr
            if touch is None:
                if moved and ((d == "down" and high[k] >= level - tol) or (d == "up" and low[k] <= level + tol)):
                    touch, state = k, "touch"
            elif (d == "down" and close[k] < low[touch]) or (d == "up" and close[k] > high[touch]):
                state = "confirmed"
                break
        if dist > break_near_atr * a[-1]:
            if state != "none":
                return None
            state = "away"        # retest gelmeden fiyat seviyeden uzaklaştı
        return {"kind": "break", "dir": d, "state": state, "bars_ago": n - 1 - brk}

    # 2) kırılım yok – seviyeye iğneyle dokunuş ve tepki
    if dist > near_atr * a[-1]:
        return None
    touch = None
    for k in range(n - 1, n - 1 - window, -1):
        tol = (a[k] or 0) * tol_atr
        if low[k] - tol <= level <= high[k] + tol and (op[k] - level) * (close[k] - level) >= 0:
            up_ = close[k] >= level
            if any(a[m] and ((close[m] - level) if up_ else (level - close[m])) >= detach_atr * a[m]
                   for m in range(max(0, k - window), k)):
                touch = k                                   # önce seviyeden uzaklaşmış, sonra geri gelmiş
                break
    if touch is None:
        return None
    d = "up" if close[touch] >= level else "down"     # seviyenin üstünden dokunduysa destek → yukarı tepki beklenir
    state = "touch"
    for k in range(touch + 1, n):
        if (d == "up" and close[k] > high[touch]) or (d == "down" and close[k] < low[touch]):
            state = "confirmed"
            break
    return {"kind": "hold", "dir": d, "state": state, "bars_ago": n - 1 - touch}


# --------------------------------------------------------------------------- #
# SSL Hybrid (çıkış çizgisi) ve QQE MOD – kullanıcının TradingView göstergeleri
# --------------------------------------------------------------------------- #
def wma(values, n):
    out = [None] * len(values)
    w = n * (n + 1) / 2
    for i in range(n - 1, len(values)):
        seg = values[i - n + 1:i + 1]
        if any(x is None for x in seg):
            continue
        out[i] = sum(x * (k + 1) for k, x in enumerate(seg)) / w
    return out


def hma(values, n):
    """Hull hareketli ortalaması (TradingView ta.hma)."""
    a, b = wma(values, n // 2), wma(values, n)
    d = [None if x is None or y is None else 2 * x - y for x, y in zip(a, b)]
    return wma(d, max(1, round(sqrt(n))))


def ema_tv(values, n):
    """TradingView ta.ema gibi ilk değerden başlayan EMA."""
    out, k, prev = [None] * len(values), 2 / (n + 1), None
    for i, x in enumerate(values):
        if x is not None:
            prev = x if prev is None else x * k + prev * (1 - k)
        out[i] = prev
    return out


def ssl_exit(high, low, close, n=15):
    """SSL Hybrid Advanced çıkış çizgisi (EXIT: HMA 15). Fiyat çizgiyi aşağıdan yukarı keserse Buy, tersi Sell."""
    eh, el = hma(high, n), hma(low, n)
    out, hl = [None] * len(close), 0
    for i in range(len(close)):
        if eh[i] is None or el[i] is None:
            continue
        hl = 1 if close[i] > eh[i] else (-1 if close[i] < el[i] else hl)
        out[i] = eh[i] if hl < 0 else el[i]
    return out


def qqe_mod(close, rsi_len=6, smooth=5, factor=3.0, threshold=3.0, bb_len=50, bb_mult=0.35):
    """QQE MOD (Mihkel00) çubuk rengi: +1 mavi (yükseliş), -1 pembe (düşüş), 0 gri."""
    n = len(close)
    rsima = ema_tv(rsi(close, rsi_len), smooth)
    wil = rsi_len * 2 - 1
    atr_r = [None] + [None if rsima[i] is None or rsima[i - 1] is None else abs(rsima[i - 1] - rsima[i])
                      for i in range(1, n)]
    dar = [None if x is None else x * factor for x in ema_tv(ema_tv(atr_r, wil), wil)]
    tl = [None] * n
    lb = sb = plb = psb = pplb = ppsb = 0.0
    tr = 1
    for i in range(n):
        r = rsima[i]
        if r is None or dar[i] is None:
            continue
        rp = rsima[i - 1] if i and rsima[i - 1] is not None else r
        nlb, nsb = r - dar[i], r + dar[i]
        lb = max(plb, nlb) if (rp > plb and r > plb) else nlb
        sb = min(psb, nsb) if (rp < psb and r < psb) else nsb
        d0, d1 = r - psb, rp - ppsb                 # cross(RSIndex, shortband[1])
        e0, e1 = plb - r, pplb - rp                 # cross(longband[1], RSIndex)
        if (d0 > 0) != (d1 > 0) and d0 != d1:
            tr = 1
        elif (e0 > 0) != (e1 > 0) and e0 != e1:
            tr = -1
        tl[i] = lb if tr == 1 else sb
        pplb, ppsb, plb, psb = plb, psb, lb, sb
    x = [None if t is None else t - 50 for t in tl]
    bas, sd = sma(x, bb_len), stdev(x, bb_len)
    out = [0] * n
    for i in range(n):
        if rsima[i] is None or bas[i] is None or sd[i] is None:
            continue
        v = rsima[i] - 50
        if v > threshold and v > bas[i] + bb_mult * sd[i]:
            out[i] = 1
        elif v < -threshold and v < bas[i] - bb_mult * sd[i]:
            out[i] = -1
    return out
