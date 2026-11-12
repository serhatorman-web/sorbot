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


def crossed_above(a, b, i):
    """a, i. mumda b'yi yukarı kesti mi?"""
    if i < 1 or None in (a[i], b[i], a[i - 1], b[i - 1]):
        return False
    return a[i - 1] <= b[i - 1] and a[i] > b[i]


def crossed_below(a, b, i):
    if i < 1 or None in (a[i], b[i], a[i - 1], b[i - 1]):
        return False
    return a[i - 1] >= b[i - 1] and a[i] < b[i]
