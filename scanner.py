"""
SorBot - Binance USDT.P Sinyal Tarayıcısı
=========================================
Binance vadelideki tüm USDT.P kontratlarını (kripto + ABD hisseleri) tarar,
16 indikatörden oluşan bir filtreyle long/short güven skoru hesaplar ve
yalnızca yüksek skorlu sinyalleri Telegram'a gönderir.

* İşlem AÇMAZ, borsa API anahtarı gerektirmez.
* Sadece Python standart kütüphanesi kullanılır.

Ortam değişkenleri:
    TELEGRAM_TOKEN, TELEGRAM_CHAT_ID  -> yoksa mesajlar sadece log'a yazılır
    DRY_RUN=1                         -> Telegram'a göndermez
    TEST_TELEGRAM=1                   -> sadece bir test mesajı gönderir
"""

import json
import os
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

import indicators as ta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
STATE_PATH = os.path.join(BASE_DIR, "state", "state_v2.json")

# GitHub Actions ABD'de çalışır; fapi.binance.com oradan engelli (HTTP 451).
# www.binance.com/fapi aynı veriyi sunar ve erişilebilir.
BINANCE = "https://www.binance.com"
TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"

TR_TZ = timezone(timedelta(hours=3))
NY_TZ = ZoneInfo("America/New_York")
HOUR_MS = 3_600_000
TF_MS = {"15m": 900_000, "30m": 1_800_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}


def tf_ms(cfg):
    """Ana zaman diliminin milisaniye karşılığı (varsayılan 1h)."""
    return TF_MS.get(cfg.get("timeframe", "1h"), HOUR_MS)


def bars_per_day(cfg):
    return max(1, 86_400_000 // tf_ms(cfg))


def apply_tf_profile(cfg, tf):
    """config.json -> tf_profiles[tf] ayarlarını ana ayarların üzerine yazar (1 seviye derin)."""
    prof = cfg.get("tf_profiles", {}).get(tf)
    if not prof:
        return cfg
    out = dict(cfg)
    for k, v in prof.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = {**out[k], **v}
        else:
            out[k] = v
    return out

TYPE_LABEL = {"COIN": "Kripto", "EQUITY": "Hisse", "COMMODITY": "Emtia",
              "HK_EQUITY": "HK Hisse", "KR_EQUITY": "KR Hisse", "FX": "Döviz"}


# --------------------------------------------------------------------------- #
# Binance istemcisi (istek limiti korumalı)
# --------------------------------------------------------------------------- #
class Binance:
    def __init__(self, max_weight=1800):
        self.max_weight = max_weight
        self.lock = threading.Lock()
        self.used_weight = 0
        self.requests = 0

    def get(self, path, params=None, retries=3):
        url = BINANCE + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        for attempt in range(retries):
            with self.lock:
                if self.used_weight > self.max_weight:
                    wait = 61 - datetime.now(timezone.utc).second
                    print(f"  istek limiti yaklaşıyor ({self.used_weight}), {wait}s bekleniyor")
                    time.sleep(wait)
                    self.used_weight = 0
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (SorBot)"})
            try:
                with urllib.request.urlopen(req, timeout=20) as r:
                    w = r.headers.get("x-mbx-used-weight-1m")
                    with self.lock:
                        self.requests += 1
                        if w:
                            self.used_weight = int(w)
                    return json.loads(r.read().decode())
            except urllib.error.HTTPError as e:
                if e.code in (418, 429):
                    wait = int(e.headers.get("Retry-After", "30"))
                    print(f"  Binance limit uyarısı ({e.code}), {wait}s bekleniyor")
                    time.sleep(min(wait, 90))
                    continue
                if e.code >= 500 and attempt < retries - 1:
                    time.sleep(2 * (attempt + 1))
                    continue
                raise
            except (urllib.error.URLError, TimeoutError):
                if attempt < retries - 1:
                    time.sleep(2 * (attempt + 1))
                    continue
                raise
        raise RuntimeError(f"İstek başarısız: {path}")


# --------------------------------------------------------------------------- #
# Yardımcılar
# --------------------------------------------------------------------------- #
def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


def fmt_price(p, precision=None):
    if precision is not None:
        return f"{p:,.{max(2, min(precision, 8))}f}"
    if p >= 1000:
        return f"{p:,.2f}"
    if p >= 1:
        return f"{p:,.4f}"
    return f"{p:.8f}".rstrip("0")


def pct(a, b):
    return 0.0 if b == 0 else (a / b - 1) * 100


def us_market_status(now_utc):
    """ABD borsası normal seans durumu (tatiller hariç)."""
    ny = now_utc.astimezone(NY_TZ)
    if ny.weekday() >= 5:
        return "weekend"
    minutes = ny.hour * 60 + ny.minute
    if 9 * 60 + 30 <= minutes < 16 * 60:
        return "open"
    return "closed"


# --------------------------------------------------------------------------- #
# Özellik (indikatör) hesaplama
# --------------------------------------------------------------------------- #
def resample_4h(candles, base_ms=HOUR_MS):
    """1 saatlik mumlardan tamamlanmış 4 saatlik mumlar üretir."""
    groups = {}
    for c in candles:
        key = c["t"] // (4 * base_ms)
        groups.setdefault(key, []).append(c)
    out = []
    for key in sorted(groups):
        g = groups[key]
        if len(g) != 4:
            continue
        out.append({"t": g[0]["t"], "o": g[0]["o"], "h": max(x["h"] for x in g),
                    "l": min(x["l"] for x in g), "c": g[-1]["c"], "v": sum(x["v"] for x in g)})
    return out


def compute_features(candles, cfg):
    p = cfg["indicators"]
    t = [c["t"] for c in candles]
    o = [c["o"] for c in candles]
    h = [c["h"] for c in candles]
    l = [c["l"] for c in candles]
    c = [c_["c"] for c_ in candles]
    v = [c_["v"] for c_ in candles]

    f = {"t": t, "o": o, "h": h, "l": l, "c": c, "v": v}
    f["rsi"] = ta.rsi(c, p["rsi"])
    f["srsi_k"], f["srsi_d"] = ta.stoch_rsi(c, *p["stoch_rsi"])
    f["macd"], f["macd_sig"], f["macd_hist"] = ta.macd(c, *p["macd"])
    f["st_dir"], f["st_line"] = ta.supertrend(h, l, c, *p["supertrend"])
    f["mom"] = ta.momentum(c, p["momentum"])
    e1, e2, e3 = p["ema"]
    f["ema20"], f["ema50"], f["ema200"] = ta.ema(c, e1), ta.ema(c, e2), ta.ema(c, e3)
    m1, m2 = p["ma"]
    f["ma50"], f["ma200"] = ta.sma(c, m1), ta.sma(c, m2)
    f["atr"] = ta.atr(h, l, c, p["atr"])
    f["adx"], f["pdi"], f["ndi"] = ta.adx(h, l, c, p["adx"])
    f["obv"] = ta.obv(c, v)
    f["obv_ema"] = ta.ema(f["obv"], 20)
    f["cci"] = ta.cci(h, l, c, p["cci"])
    f["vol_ma"] = ta.sma(v, p["volume_ma"])
    f["vwap"] = ta.vwap_daily(t, h, l, c, v)
    f["bb_mid"], f["bb_up"], f["bb_lo"], f["bb_bw"] = ta.bollinger(c, *p["bollinger"])
    f["ichi_tenkan"], f["ichi_kijun"], f["ichi_top"], f["ichi_bot"] = ta.ichimoku(h, l, *p.get("ichimoku", [9, 26, 52, 26]))
    f["cmf"] = ta.cmf(h, l, c, v, p.get("cmf", 20))
    f["ewo"] = ta.ewo(c, *p.get("ewo", [5, 35]))
    f["wt1"], f["wt2"] = ta.wavetrend(h, l, c, *p.get("wavetrend", [10, 21]))
    f["hh20"] = ta.highest(h, cfg["pump_dump"]["breakout_lookback"])
    f["ll20"] = ta.lowest(l, cfg["pump_dump"]["breakout_lookback"])

    # 4 saatlik trend: her 1s mum için, o ana kadar TAMAMLANMIŞ son 4s mumun durumu
    # (geçmişe dönük testte geleceği görmemek için mum bazında hesaplanır)
    n = len(candles)
    f["h4_ema"], f["h4_st"] = [0] * n, [0] * n
    base_ms = tf_ms(cfg)
    c4 = resample_4h(candles, base_ms)
    if len(c4) >= 60:
        cc4 = [x["c"] for x in c4]
        e20, e50 = ta.ema(cc4, 20), ta.ema(cc4, 50)
        st4, _ = ta.supertrend([x["h"] for x in c4], [x["l"] for x in c4], cc4, 10, 3.0)
        k = -1
        for i in range(n):
            close_t = t[i] + base_ms
            while k + 1 < len(c4) and c4[k + 1]["t"] + 4 * base_ms <= close_t:
                k += 1
            if k >= 0 and e50[k] is not None:
                f["h4_ema"][i] = 1 if e20[k] > e50[k] else -1
                f["h4_st"][i] = st4[k] or 0
    return f


def trend_bias(f, i=None):
    """-1 (güçlü düşüş) ile +1 (güçlü yükseliş) arasında yön eğilimi."""
    i = len(f["c"]) - 1 if i is None else i
    votes = [
        1 if f["c"][i] > f["ema50"][i] else -1,
        1 if f["ema20"][i] > f["ema50"][i] else -1,
        f["st_dir"][i] or 0,
        f["h4_ema"][i],
        f["h4_st"][i],
    ]
    return sum(votes) / len(votes)


# --------------------------------------------------------------------------- #
# Tetikleyiciler ve skor
# --------------------------------------------------------------------------- #
STRONG_TRIGGERS = ("Supertrend", "MACD", "EMA20/EMA50", "Hacimli")


def find_triggers(f, s, lookback, last=None):
    """Son 'lookback' mum içinde yeni oluşan sinyal tetikleyicileri.

    Zayıf tetikleyiciler (StochRSI dönüşü) tek başına sinyal üretmez;
    ancak trend yönünde EMA20'ye geri çekilme sonrası dönüşte geçerlidir.
    """
    n = (len(f["c"]) - 1 if last is None else last) + 1
    found = []
    for i in range(n - lookback, n):
        up = s == 1
        if f["st_dir"][i] is not None and f["st_dir"][i - 1] is not None and f["st_dir"][i] == s != f["st_dir"][i - 1]:
            found.append("Supertrend " + ("yukarı" if up else "aşağı") + " döndü")
        if (ta.crossed_above if up else ta.crossed_below)(f["macd"], f["macd_sig"], i):
            found.append("MACD " + ("yukarı" if up else "aşağı") + " kesişim")
        if (ta.crossed_above if up else ta.crossed_below)(f["ema20"], f["ema50"], i):
            found.append("EMA20/EMA50 " + ("yukarı" if up else "aşağı") + " kesişim")
        k, d = f["srsi_k"], f["srsi_d"]
        if k[i - 1] is not None and d[i - 1] is not None:
            if up and ta.crossed_above(k, d, i) and min(k[i - 1], d[i - 1]) < 20:
                found.append("StochRSI dipten dönüş")
            if not up and ta.crossed_below(k, d, i) and max(k[i - 1], d[i - 1]) > 80:
                found.append("StochRSI tepeden dönüş")
        vr = f["v"][i] / f["vol_ma"][i] if f["vol_ma"][i] else 0
        if up and f["hh20"][i - 1] is not None and f["c"][i] > f["hh20"][i - 1] and vr >= 1.5:
            found.append("Hacimli direnç kırılımı")
        if not up and f["ll20"][i - 1] is not None and f["c"][i] < f["ll20"][i - 1] and vr >= 1.5:
            found.append("Hacimli destek kırılımı")
    found = list(dict.fromkeys(found))   # tekrarları at
    if found and not any(t.startswith(STRONG_TRIGGERS) for t in found):
        # Sadece StochRSI dönüşü var: trend içi geri çekilme mi?
        i = n - 1
        in_trend = (f["ema20"][i] - f["ema50"][i]) * s > 0 and (f["ema50"][i] - f["ema200"][i]) * s > 0
        near_ema = f["atr"][i] and abs(f["c"][i] - f["ema20"][i]) <= 1.0 * f["atr"][i]
        if in_trend and near_ema:
            return ["Trend içi geri çekilmeden dönüş (StochRSI)"]
        return []
    return found


def pump_dump_analysis(f, cfg, chg24, i=None):
    """Pump/dump olasılığı ve 'geç kalınmış' durumlarını analiz eder."""
    pd_cfg = cfg["pump_dump"]
    i = len(f["c"]) - 1 if i is None else i
    c, bw = f["c"], f["bb_bw"]
    res = {"long_bonus": 0, "short_bonus": 0, "long_pen": 0, "short_pen": 0, "notes": []}

    # Sıkışma (Bollinger bant daralması)
    lb = pd_cfg["squeeze_lookback"]
    hist_bw = sorted(x for x in bw[i - lb:i] if x is not None)
    squeeze = False
    if len(hist_bw) > 20:
        thr = hist_bw[int(len(hist_bw) * pd_cfg["squeeze_percentile"])]
        squeeze = min(x for x in bw[i - 6:i] if x is not None) <= thr

    vr = f["v"][i] / f["vol_ma"][i] if f["vol_ma"][i] else 0
    vr3 = sum(f["v"][i - 2:i + 1]) / 3 / f["vol_ma"][i] if f["vol_ma"][i] else 0
    vol_spike = vr >= pd_cfg["volume_spike_ratio"] or vr3 >= pd_cfg["volume_spike_ratio"] * 0.66
    brk_up = f["hh20"][i - 1] is not None and c[i] > f["hh20"][i - 1]
    brk_dn = f["ll20"][i - 1] is not None and c[i] < f["ll20"][i - 1]

    # Birikim / dağıtım: fiyat yatayken OBV yön değiştiriyor mu?
    price_flat = abs(pct(c[i], c[i - 24])) < 2.0
    obv_chg = f["obv"][i] - f["obv"][i - 24]
    vol24 = sum(f["v"][i - 23:i + 1]) or 1
    accumulation = price_flat and obv_chg / vol24 > 0.25
    distribution = price_flat and obv_chg / vol24 < -0.25

    res.update({"brk_up": brk_up, "brk_dn": brk_dn, "accumulation": accumulation,
                "distribution": distribution, "chg3": pct(c[i], c[i - 3]) / 100})
    if squeeze and brk_up and vol_spike:
        res["long_bonus"] += 10
        res["notes"].append(("long", "🚀 Pump potansiyeli: sıkışmadan hacimli kırılım"))
    elif accumulation and squeeze:
        res["long_bonus"] += 6
        res["notes"].append(("long", "🚀 Pump potansiyeli: sıkışmada birikim (OBV↑)"))
    elif vol_spike and brk_up:
        res["long_bonus"] += 4

    if squeeze and brk_dn and vol_spike:
        res["short_bonus"] += 10
        res["notes"].append(("short", "💥 Dump potansiyeli: sıkışmadan hacimli kırılım"))
    elif distribution and squeeze:
        res["short_bonus"] += 6
        res["notes"].append(("short", "💥 Dump potansiyeli: sıkışmada dağıtım (OBV↓)"))
    elif vol_spike and brk_dn:
        res["short_bonus"] += 4

    # Zaten pump/dump olmuş mu? (geç kalma koruması)
    chg3 = pct(c[i], c[i - 3]) / 100
    if chg3 >= pd_cfg["already_pumped_3h"] or chg24 / 100 >= pd_cfg["already_pumped_24h"]:
        res["long_pen"] += 10
        res["notes"].append(("long", f"⚠️ Pump sonrası (3s {chg3*100:+.1f}%, 24s {chg24:+.1f}%) – geç kalınmış olabilir"))
        # Negatif uyumsuzluk: fiyat yeni tepe, RSI daha düşük tepe
        r = f["rsi"]
        if None not in r[i - 30:i + 1]:
            if max(c[i - 10:i + 1]) >= max(c[i - 30:i - 10]) and max(r[i - 10:i + 1]) < max(r[i - 30:i - 10]):
                res["short_bonus"] += 8
                res["notes"].append(("short", "💥 Dump riski: pump sonrası negatif RSI uyumsuzluğu"))
    if chg3 <= -pd_cfg["already_pumped_3h"] or chg24 / 100 <= -pd_cfg["already_pumped_24h"]:
        res["short_pen"] += 10
        res["notes"].append(("short", f"⚠️ Dump sonrası (3s {chg3*100:+.1f}%, 24s {chg24:+.1f}%) – geç kalınmış olabilir"))
        r = f["rsi"]
        if None not in r[i - 30:i + 1]:
            if min(c[i - 10:i + 1]) <= min(c[i - 30:i - 10]) and min(r[i - 10:i + 1]) > min(r[i - 30:i - 10]):
                res["long_bonus"] += 8
                res["notes"].append(("long", "🚀 Tepki potansiyeli: dump sonrası pozitif RSI uyumsuzluğu"))

    res["squeeze"], res["vol_ratio"], res["vol_spike"] = squeeze, vr, vol_spike
    return res


def pump_radar(f, i, pdres, chg24, cfg, oi_chg=None, funding=None):
    """Pump/Dump radarı: Supertrend'den bağımsız, hareket başlangıcını yakalamaya çalışır.

    Döner: [{dir, kind, score, reasons}] (boş liste = sinyal yok)
      kind="start" : sıkışmadan hacimli kırılım (pump/dump başlıyor) -> giriş/TP/stop ile
      kind="early" : sıkışmada birikim/dağıtım + OI artışı (henüz kırılım yok) -> izleme uyarısı
    """
    rc = cfg.get("pump_radar", {})
    if not rc.get("enabled", True):
        return []
    pd_cfg = cfg["pump_dump"]
    out = []
    vr = pdres["vol_ratio"]
    for key, s in (("long", 1), ("short", -1)):
        brk = pdres["brk_up"] if s == 1 else pdres["brk_dn"]
        accum = pdres["accumulation"] if s == 1 else pdres["distribution"]
        late = pdres["chg3"] * s >= pd_cfg["already_pumped_3h"] or chg24 / 100 * s >= pd_cfg["already_pumped_24h"]
        h4_ok = (f["h4_ema"][i] + f["h4_st"][i]) * s >= 0
        score, why = 0, []
        if pdres["squeeze"]:
            score += 25
            why.append("Bollinger sıkışması (düşük oynaklık)")
        if vr >= pd_cfg["volume_spike_ratio"]:
            score += 25
            why.append(f"Hacim patlaması ({vr:.1f}x)")
        elif vr >= 2.0:
            score += 15
            why.append(f"Hacim artışı ({vr:.1f}x)")
        if brk:
            score += 20
            why.append("20 mumluk " + ("direnç" if s == 1 else "destek") + " kırıldı")
        if accum:
            score += 10
            why.append("OBV " + ("birikim" if s == 1 else "dağıtım") + " (fiyat yatayken)")
        if (f["obv"][i] - f["obv_ema"][i]) * s > 0:
            score += 5
        if h4_ok:
            score += 10
        if oi_chg is not None and oi_chg >= pd_cfg["oi_change_confirm"]:
            score += 10 if oi_chg >= 0.05 else 5
            why.append(f"Açık pozisyon artıyor (OI 4s {oi_chg*100:+.1f}%)")
        if funding is not None and ((s == 1 and funding >= cfg["funding"]["crowded_long"])
                                    or (s == -1 and funding <= cfg["funding"]["crowded_short"])):
            score -= 10   # fonlama aşırı kalabalıksa skor düşer (mesajda gösterilmez)
        score = max(0, min(100, score))

        if brk and pdres["vol_spike"] and pdres["squeeze"] and not late:
            if score >= rc.get("min_score", 70):
                out.append({"dir": key, "kind": "start", "score": score, "reasons": why})
        elif (rc.get("early_alerts", True) and accum and pdres["squeeze"] and not brk and not late
              and oi_chg is not None and oi_chg >= 0.05):
            if score >= rc.get("min_score_early", 55):
                out.append({"dir": key, "kind": "early", "score": score, "reasons": why})
    return out


def score_direction(f, s, leader_bias, funding, pdres, cfg, i=None):
    """s=+1 long, s=-1 short için 0-100 güven skoru ve gerekçeler."""
    i = len(f["c"]) - 1 if i is None else i
    c = f["c"][i]
    pts = 0.0
    why = []

    # ---- Trend (30) ----
    t = 0
    if (c - f["ema200"][i]) * s > 0:
        t += 6
    if (f["ema20"][i] - f["ema50"][i]) * s > 0:
        t += 5
    if (f["ema50"][i] - f["ema200"][i]) * s > 0:
        t += 4
    if (f["ma50"][i] - f["ma200"][i]) * s > 0:
        t += 3
    if f["st_dir"][i] == s:
        t += 6
    if f["h4_ema"][i] == s:
        t += 3
    if f["h4_st"][i] == s:
        t += 3
    pts += t

    # ---- Momentum (25) ----
    m = 0
    r = f["rsi"][i]
    rs = r if s == 1 else 100 - r            # short için aynalanmış RSI
    rising = (f["rsi"][i] - f["rsi"][i - 1]) * s > 0
    if 50 < rs <= 70:
        m += 6
    elif 40 <= rs <= 50 and rising:
        m += 3
    elif 70 < rs <= 75:
        m += 3
    k, d = f["srsi_k"][i], f["srsi_d"][i]
    ks, ds = (k, d) if s == 1 else (100 - k, 100 - d)
    if ks > ds and ks < 80:
        m += 4
    if min(ks, ds) < 30 and ks > ds:
        m += 2
    hist, hist_prev = f["macd_hist"][i], f["macd_hist"][i - 1]
    if hist * s > 0:
        m += 3
    if (hist - hist_prev) * s > 0:
        m += 2
    if f["macd"][i] * s > 0:
        m += 1
    if f["mom"][i] * s > 0:
        m += 3
    cc = f["cci"][i] * s
    if 0 < cc < 200:
        m += 4
    elif cc >= 200:
        m += 1
    pts += min(m, 25)

    # ---- Trend gücü / ADX (10) ----
    a, pdi, ndi = f["adx"][i], f["pdi"][i], f["ndi"][i]
    di_ok = (pdi - ndi) * s > 0
    if di_ok and a >= 25:
        pts += 10
    elif di_ok and a >= 20:
        pts += 6
    elif di_ok:
        pts += 2

    # ---- Hacim (15) ----
    vr = pdres["vol_ratio"]
    if vr >= 1.5:
        pts += 6
    elif vr >= 1.2:
        pts += 4
    elif vr >= 1.0:
        pts += 2
    if (f["obv"][i] - f["obv_ema"][i]) * s > 0:
        pts += 5
    if (c - f["vwap"][i]) * s > 0:
        pts += 4

    # ---- Piyasa lideri / BTC yönü (20) ----
    pts += 20 * (leader_bias * s + 1) / 2

    # ---- Cezalar ----
    atr_v = f["atr"][i] or 0
    if atr_v and (c - f["ema20"][i]) * s > 2.0 * atr_v:
        pts -= 10
        why.append("⚠️ Fiyat EMA20'den çok uzak (aşırı uzama)")
    if rs > 80:
        pts -= 8
        why.append("⚠️ RSI aşırı " + ("alım" if s == 1 else "satım") + " bölgesinde")
    elif rs > 68 and ks > 95:
        pts -= 6
        why.append("⚠️ Geç giriş riski (RSI ve StochRSI uç seviyede)")
    if funding is not None:
        fc = cfg["funding"]
        if s == 1 and funding >= fc["crowded_long"]:
            pts -= 5
            why.append(f"⚠️ Fonlama yüksek ({funding*100:.3f}%) – long kalabalık")
        if s == -1 and funding <= fc["crowded_short"]:
            pts -= 5
            why.append(f"⚠️ Fonlama negatif ({funding*100:.3f}%) – short kalabalık")
        if (s == 1 and funding < 0) or (s == -1 and funding > fc["crowded_long"]):
            pts += 2   # ters kalabalık: sıkışma (squeeze) ihtimali

    # ---- Pump/dump analizi ----
    if s == 1:
        pts += pdres["long_bonus"] - pdres["long_pen"]
    else:
        pts += pdres["short_bonus"] - pdres["short_pen"]

    return max(0, min(100, round(pts))), why


def required_ready(f, i=None):
    i = len(f["c"]) - 1 if i is None else i
    keys = ["rsi", "srsi_k", "srsi_d", "macd", "macd_hist", "st_dir", "mom", "ema20", "ema50",
            "ema200", "ma50", "ma200", "atr", "adx", "pdi", "ndi", "obv_ema", "cci", "vol_ma", "bb_bw"]
    return all(f[k][i] is not None and f[k][i - 1] is not None for k in keys)


# --------------------------------------------------------------------------- #
# Analiz
# --------------------------------------------------------------------------- #
def parse_klines(raw, now_ms):
    return [{"t": int(k[0]), "o": float(k[1]), "h": float(k[2]), "l": float(k[3]),
             "c": float(k[4]), "v": float(k[7])}           # v = USDT cinsinden hacim
            for k in raw if int(k[6]) < now_ms]


def ichimoku_vote(f, i):
    top, bot = f["ichi_top"][i], f["ichi_bot"][i]
    if top is None or bot is None:
        return 0
    c = f["c"][i]
    return 1 if c > top else (-1 if c < bot else 0)


def indicator_votes(f, i, leader_bias, leader_name):
    """Her indikatörün i. mumdaki AL (+1) / SAT (-1) / nötr (0) durumu."""
    c = f["c"][i]
    sgn = lambda x: 1 if x > 0 else (-1 if x < 0 else 0)
    vr = f["v"][i] / f["vol_ma"][i] if f["vol_ma"][i] else 0
    candle = sgn(f["c"][i] - f["o"][i])
    votes = [
        ("RSI", sgn(f["rsi"][i] - 50)),
        ("StochRSI", sgn(f["srsi_k"][i] - f["srsi_d"][i])),
        ("MACD", sgn(f["macd"][i] - f["macd_sig"][i])),
        ("Momentum", sgn(f["mom"][i])),
        ("EMA20", sgn(c - f["ema20"][i])),
        ("EMA50", sgn(c - f["ema50"][i])),
        ("EMA200", sgn(c - f["ema200"][i])),
        ("MA50", sgn(c - f["ma50"][i])),
        ("MA200", sgn(c - f["ma200"][i])),
        ("ADX/DI", sgn(f["pdi"][i] - f["ndi"][i])),
        ("OBV", sgn(f["obv"][i] - f["obv_ema"][i])),
        ("CCI", sgn(f["cci"][i])),
        ("VWAP", sgn(c - f["vwap"][i])),
        ("Hacim", candle if vr >= 1.0 else 0),     # ortalama üstü hacimde mumun yönü
        ("Bollinger", sgn(c - f["bb_mid"][i]) if f["bb_mid"][i] is not None else 0),   # orta bandın üstü/altı
        ("Ichimoku", ichimoku_vote(f, i)),          # bulutun üstü / altı / içi
        ("CMF", sgn(f["cmf"][i]) if f["cmf"][i] is not None else 0),   # para girişi / çıkışı
        ("EWO", sgn(f["ewo"][i]) if f["ewo"][i] is not None else 0),   # SMA5 - SMA35
        ("WaveTrend", sgn(f["wt1"][i] - f["wt2"][i]) if None not in (f["wt1"][i], f["wt2"][i]) else 0),  # WT1/WT2
    ]
    if leader_name != "4s trend":
        votes.append((leader_name or "Lider", sgn(leader_bias)))
    return votes


def decoupling(f, i, s, leader_ret24, cfg):
    """Coin, piyasa liderinden (BTC/QQQ) s yönünde ayrışıyor mu?
    Örn. BTC düşerken hacimle yükselen coin (s=+1) veya BTC yükselirken çöken coin (s=-1)."""
    dc = cfg.get("decoupling", {})
    n = bars_per_day(cfg)
    if not dc.get("enabled", True) or leader_ret24 is None or i < n:
        return None
    own = f["c"][i] / f["c"][i - n] - 1
    rel = (own - leader_ret24) * s
    vr = f["v"][i] / f["vol_ma"][i] if f["vol_ma"][i] else 0
    h4 = (f["h4_ema"][i] + f["h4_st"][i]) * s
    if rel >= dc.get("min_rel_return_24h", 0.05) and own * s > 0 and vr >= dc.get("min_volume_ratio", 1.5) and h4 >= 0:
        return {"own": own, "leader": leader_ret24, "rel": rel, "vr": vr}
    return None


def evaluate_supertrend(meta, f, i, leader_bias, leader_name, funding, chg24, now_utc, cfg, leader_ret24=None):
    """1s mum kapanışında Supertrend dönüşü + diğer indikatörlerin AL/SAT teyidi.
    Güven skoru = Supertrend ile aynı yönü gösteren indikatörlerin yüzdesi.
    Lidere (BTC/QQQ) ters ama ondan güçlü şekilde ayrışan semboller için lider oyu sayılmaz."""
    pdres = pump_dump_analysis(f, cfg, chg24, i)
    votes = indicator_votes(f, i, leader_bias, leader_name)
    flip = 0
    st = f["st_dir"]
    if st[i] is not None and st[i - 1] is not None and st[i] != st[i - 1]:
        flip = st[i]
    out = {"meta": meta, "f": f, "i": i, "leader_bias": leader_bias, "leader_name": leader_name,
           "funding": funding, "chg24": chg24, "pd": pdres, "votes": votes}
    lead_label = leader_name or "Lider"
    for key, s in (("long", 1), ("short", -1)):
        dec = decoupling(f, i, s, leader_ret24, cfg) if flip == s and leader_bias * s < 0 else None
        used = [(n, v) for n, v in votes if not (dec and n == lead_label)]
        agree = sum(1 for _, v in used if v == s)
        score = round(agree / len(used) * 100)
        trig = [f"Supertrend {'AL' if s == 1 else 'SAT'}'a döndü"] if flip == s else []
        why = []
        if dec:
            icon = "🚀" if s == 1 else "💥"
            why.append(f"{icon} {lead_label}'den ayrışıyor: 24s {dec['own']*100:+.1f}% "
                       f"({lead_label} {dec['leader']*100:+.1f}%), hacim {dec['vr']:.1f}x")
        out[key] = {"score": score, "why": why, "triggers": trig,
                    "agree": agree, "total": len(used), "decoupled": bool(dec)}
    return out


def evaluate_at(meta, f, i, leader_bias, leader_name, funding, chg24, now_utc, cfg, leader_ret24=None):
    """i. mumda (o ana kadarki veriyle) long/short değerlendirmesi.
    Canlı taramada i = son kapanmış mum; backtest'te her geçmiş mum."""
    if cfg.get("strategy") == "supertrend":
        return evaluate_supertrend(meta, f, i, leader_bias, leader_name, funding, chg24, now_utc, cfg,
                                   leader_ret24)
    pdres = pump_dump_analysis(f, cfg, chg24, i)
    lb = cfg["signal"]["trigger_lookback_bars"]
    session_pen = 0
    if meta["type"] == "EQUITY":
        ms = us_market_status(now_utc)
        session_pen = 8 if ms == "weekend" else (5 if ms == "closed" else 0)
    out = {"meta": meta, "f": f, "i": i, "leader_bias": leader_bias, "leader_name": leader_name,
           "funding": funding, "chg24": chg24, "pd": pdres}
    for key, s in (("long", 1), ("short", -1)):
        score, why = score_direction(f, s, leader_bias, funding, pdres, cfg, i)
        trig = find_triggers(f, s, lb, i)
        if len(trig) >= 2:
            score = min(100, score + 3)        # birden fazla tetik = daha güçlü teyit
        score = max(0, score - session_pen)
        # Sert filtreler: 1s Supertrend ve 4s trend sinyalle çelişmemeli
        h4 = f["h4_ema"][i] + f["h4_st"][i]
        if f["st_dir"][i] != s or h4 == -2 * s:
            trig = []
        out[key] = {"score": score, "why": why, "triggers": trig}
    return out


def analyze_symbol(meta, candles, ctx, cfg):
    if len(candles) < cfg["min_candles"]:
        return None
    f = compute_features(candles, cfg)
    if not required_ready(f):
        return None
    sym = meta["symbol"]
    i = len(f["c"]) - 1
    leader = ctx["leaders"].get(meta["type"])
    leader_ret24 = None
    if leader is None or leader["symbol"] == sym:
        leader_bias = (f["h4_ema"][i] + f["h4_st"][i]) / 2
        leader_name = "4s trend"
    else:
        leader_bias = leader["bias"]
        leader_name = leader["symbol"].replace("USDT", "")
        leader_ret24 = leader.get("ret24")
    funding = ctx["funding"].get(sym)
    chg24 = ctx["tickers"].get(sym, {}).get("chg", 0.0)
    out = evaluate_at(meta, f, i, leader_bias, leader_name, funding, chg24, ctx["now_utc"], cfg, leader_ret24)
    out["qv24"] = ctx["tickers"].get(sym, {}).get("qv")
    return out


def apply_open_interest(res, oi_hist):
    """OI verisiyle skoru günceller (sadece adaylar için çekilir)."""
    if not oi_hist or len(oi_hist) < 2:
        return
    oi_first = float(oi_hist[0]["sumOpenInterestValue"])
    oi_last = float(oi_hist[-1]["sumOpenInterestValue"])
    if oi_first <= 0:
        return
    oi_chg = oi_last / oi_first - 1
    res["oi_chg"] = oi_chg
    f = res["f"]
    price_chg = f["c"][-1] / f["c"][-5] - 1
    cfg_pd = res["cfg_pd"]
    if res.get("votes"):
        return      # Supertrend stratejisi: OI skoru etkilemez ve mesajda not olarak gösterilmez
    adj = 4
    for key, s in (("long", 1), ("short", -1)):
        side = res[key]
        if oi_chg >= cfg_pd["oi_change_confirm"] and price_chg * s > 0:
            side["score"] = min(100, side["score"] + adj)
            side["why"].append(f"✅ Açık pozisyon artıyor (OI 4s {oi_chg*100:+.1f}%) – hareket destekli")
            if oi_chg >= cfg_pd["oi_change_strong"] and res["pd"]["vol_spike"]:
                side["score"] = min(100, side["score"] + adj)
                side["why"].append("🚀 Güçlü OI + hacim artışı" if s == 1 else "💥 Güçlü OI + hacim artışı")
        elif oi_chg <= -cfg_pd["oi_change_confirm"] and price_chg * s > 0:
            side["score"] = max(0, side["score"] - adj)
            side["why"].append(f"⚠️ OI düşüyor ({oi_chg*100:+.1f}%) – hareket pozisyon kapatmadan kaynaklı olabilir")


def decide(res, cfg, state, now):
    """Sinyal gönderilip gönderilmeyeceğine karar verir."""
    sc = dict(cfg["signal"])
    if cfg.get("strategy") == "supertrend":
        sc.update(cfg.get("signal_supertrend", {}))
    sym = res["meta"]["symbol"]
    best = None
    for key, s in (("long", 1), ("short", -1)):
        side, other = res[key], res["short" if key == "long" else "long"]
        if not side["triggers"]:
            continue
        if side["score"] < sc["min_score"]:
            continue
        if side["score"] - other["score"] < sc["min_score_gap"]:
            continue
        if (sc["block_against_leader"] and res["leader_bias"] * s <= -sc["leader_block_threshold"]
                and not side.get("decoupled")):     # lidere ters ama ondan ayrışıyorsa izin ver
            continue
        last = state.get("signals", {}).get(f"{sym}|{key}")
        if last and now - last < sc["cooldown_hours"] * 3600:
            continue
        if best is None or side["score"] > res[best]["score"]:
            best = key
    return best


def stop_distance(f, i, s, risk_cfg, method=None):
    """Stop mesafesini (fiyat cinsinden) ve kullanılan yöntemin adını döndürür.

    atr       : giriş ± sl_atr_mult × ATR
    swing_atr : son N mumun dibi/tepesi ötesi (+ tampon), [min, max] ATR aralığında sınırlı
    """
    method = method or risk_cfg.get("sl_method", "atr")
    entry, atr_v = f["c"][i], f["atr"][i]
    if method == "st_line":
        # Stop Supertrend çizgisinin biraz ötesinde (çizgi kırılırsa sinyal bozulmuş demektir)
        dist = abs(entry - f["st_line"][i]) + 0.1 * atr_v
        lo, hi = risk_cfg.get("min_atr", 1.0) * atr_v, 3.0 * atr_v
        if dist < lo:
            return lo, "ATR alt sınırı"
        if dist > hi:
            return hi, "3 ATR üst sınırı"
        return dist, "Supertrend çizgisi"
    if method == "swing_atr":
        n = risk_cfg.get("swing_lookback", 10)
        buf = risk_cfg.get("swing_buffer_atr", 0.3) * atr_v
        if s == 1:
            dist = entry - (min(f["l"][i - n + 1:i + 1]) - buf)
        else:
            dist = (max(f["h"][i - n + 1:i + 1]) + buf) - entry
        lo, hi = risk_cfg.get("min_atr", 1.0) * atr_v, risk_cfg.get("max_atr", 2.5) * atr_v
        if dist < lo:
            return lo, "ATR alt sınırı"
        if dist > hi:
            return hi, "ATR üst sınırı"
        return dist, "swing " + ("dibi" if s == 1 else "tepesi")
    return risk_cfg["sl_atr_mult"] * atr_v, f"{risk_cfg['sl_atr_mult']} ATR"


def levels(res, direction, cfg, method=None):
    f, i = res["f"], res["i"]
    entry = f["c"][i]
    s = 1 if direction == "long" else -1
    risk, label = stop_distance(f, i, s, cfg["risk"], method)
    sl = entry - s * risk
    tps = [entry + s * risk * r for r in cfg["risk"]["tp_r_multiples"]]
    return entry, sl, tps, label


def confidence_label(score):
    if score >= 90:
        return "Çok yüksek"
    if score >= 82:
        return "Yüksek"
    return "İyi"


TREND_LABEL = {1: "🟢 Yükseliş", -1: "🔴 Düşüş", 0: "⚪ Nötr", None: "– Veri yok"}
TF_ROWS = (("15m", "15dk"), ("1h", "1 saat"), ("4h", "4 saat"), ("1d", "1 gün"))


def tf_trend(candles):
    """Bir zaman dilimindeki trend: +1 yükseliş, -1 düşüş, 0 nötr, None veri yetersiz.
    4 oy: fiyat/EMA50, EMA20/EMA50, Supertrend yönü, MACD histogramı.
    En az 3 oy aynı yöndeyse ve karşı yönde en fazla 1 oy varsa trend o yöndedir."""
    if len(candles) < 60:
        return None
    c = [x["c"] for x in candles]
    h = [x["h"] for x in candles]
    l = [x["l"] for x in candles]
    e20, e50 = ta.ema(c, 20), ta.ema(c, 50)
    st, _ = ta.supertrend(h, l, c, 10, 3.0)
    _, _, hist = ta.macd(c)
    sgn = lambda x: 1 if x > 0 else (-1 if x < 0 else 0)
    votes = [sgn(c[-1] - e50[-1]), sgn(e20[-1] - e50[-1]), st[-1] or 0, sgn(hist[-1] or 0)]
    up, dn = votes.count(1), votes.count(-1)
    if up >= 3:
        return 1
    if dn >= 3:
        return -1
    return 0


TF_NAMES = {"15m": "15dk", "1h": "1 saat", "4h": "4 saat", "1d": "1 gün", "1w": "1 hafta"}
DIV_TFS = ("15m", "1h", "4h", "1d", "1w")


def fetch_tf_trends(api, res, now_ms, base_tf="1h"):
    """Mesaj gönderilecek sembol için diğer zaman dilimlerini çeker:
    trend tablosu (15dk / 1s / 4s / 1g) ve RSI uyumsuzluğu (15dk / 1s / 4s / 1g / 1h)."""
    sym = res["meta"]["symbol"]
    f, i = res["f"], res["i"]
    candles = {base_tf: [{"c": f["c"][k], "h": f["h"][k], "l": f["l"][k]} for k in range(i + 1)]}
    for tf in dict.fromkeys([x for x, _ in TF_ROWS] + list(DIV_TFS)):
        if tf in candles:
            continue
        try:
            raw = api.get("/fapi/v1/klines", {"symbol": sym, "interval": tf, "limit": 150})
            candles[tf] = parse_klines(raw, now_ms)
        except Exception:  # noqa: BLE001
            candles[tf] = []
    res["tf"] = {tf: tf_trend(candles.get(tf, [])) for tf, _ in TF_ROWS}
    pos, neg = [], []
    for tf in DIV_TFS:
        cs = candles.get(tf, [])
        if len(cs) < 40:
            continue
        p_, n_ = ta.rsi_divergence([x["h"] for x in cs], [x["l"] for x in cs], [x["c"] for x in cs])
        if p_:
            pos.append(TF_NAMES[tf])
        if n_:
            neg.append(TF_NAMES[tf])
    res["div"] = {"pos": pos, "neg": neg}


def compute_volume_profile(res, cfg):
    """Sinyal zaman diliminin son N mumundan hacim profili (VAH / POC / VAL)."""
    vp = cfg.get("volume_profile", {})
    if not vp.get("enabled", True):
        return
    f, i = res["f"], res["i"]
    n = vp.get("lookback_bars", {}).get(cfg.get("timeframe", "1h"), 96)
    a = max(0, i - n + 1)
    out = ta.volume_profile(f["h"][a:i + 1], f["l"][a:i + 1], f["v"][a:i + 1],
                            vp.get("rows", 24), vp.get("value_area", 0.70))
    res["vp"] = out


def volume_lines(res, cfg):
    """Hacim durumu (yüksek/düşük), son mumlardaki büyük yükseliş/düşüş ve hacim patlaması."""
    vc = cfg.get("volume_info", {})
    f, i = res["f"], res["i"]
    if f["vol_ma"][i] in (None, 0):
        return []
    ratio = lambda k: f["v"][k] / f["vol_ma"][k] if f["vol_ma"][k] else 0
    vr = ratio(i)
    out = ["🔊 Hacim: " + ("🟢 Yüksek" if vr >= vc.get("high_ratio", 1.0) else "🔴 Düşük")
           + f" ({vr:.1f}x ortalama)"]
    # Son N mumdaki en büyük gövdeli hareket (ATR'ye göre)
    big = None
    for k in range(max(1, i - vc.get("big_move_lookback", 3) + 1), i + 1):
        atr_k = f["atr"][k]
        body = f["c"][k] - f["o"][k]
        if atr_k and abs(body) >= vc.get("big_move_atr", 1.5) * atr_k:
            if big is None or abs(body) / atr_k > abs(big[1]) / f["atr"][big[0]]:
                big = (k, body)
    if big:
        k, body = big
        chg = (f["c"][k] / f["o"][k] - 1) * 100
        when = "sinyal mumu" if k == i else f"{i - k} mum önce"
        if body > 0:
            out.append(f"📈 Büyük yükseliş: {chg:+.2f}% · hacim {ratio(k):.1f}x ({when})")
        else:
            out.append(f"📉 Büyük düşüş: {chg:+.2f}% · hacim {ratio(k):.1f}x ({when})")
    peak = max(range(max(0, i - 2), i + 1), key=ratio)
    if ratio(peak) >= vc.get("spike_ratio", 3.0):
        when = "sinyal mumu" if peak == i else f"{i - peak} mum önce"
        out.append(f"💥 Hacim patlaması: {ratio(peak):.1f}x ortalama ({when})")
    return out


def volume_profile_lines(res, cfg):
    vp = res.get("vp")
    if not vp:
        return []
    vah, poc, val = vp
    f, i = res["f"], res["i"]
    price = f["c"][i]
    prec = res["meta"].get("precision")
    span = TF_NAMES.get(cfg.get("timeframe", "1h"), cfg.get("timeframe", ""))
    return [f"📊 Hacim profili · {span}",
            f"🔴 VAH: <code>{fmt_price(vah, prec)}</code> ({pct(vah, price):+.2f}%)",
            f"🟡 POC: <code>{fmt_price(poc, prec)}</code> ({pct(poc, price):+.2f}%)",
            f"🟢 VAL: <code>{fmt_price(val, prec)}</code> ({pct(val, price):+.2f}%)"]


def divergence_lines(res):
    d = res.get("div") or {}
    out = []
    if d.get("pos"):
        out.append("🟢 RSI pozitif uyumsuzluk: " + ", ".join(d["pos"]))
    if d.get("neg"):
        out.append("🔴 RSI negatif uyumsuzluk: " + ", ".join(d["neg"]))
    return out


def leader_line(res):
    """Piyasa lideri yönü (kripto: BTC, hisse: QQQ) – aynı hesap ve format."""
    lb_ = res["leader_bias"]
    return f"{res['leader_name']} yönü: " + TREND_LABEL[1 if lb_ >= 0.5 else (-1 if lb_ <= -0.5 else 0)]


def market_lines(res, cfg, now_utc):
    """ABD borsası açık/kapalı (hisseler) ve likidite yüksek/düşük satırları."""
    meta = res["meta"]
    out = []
    ms = us_market_status(now_utc) if meta["type"] == "EQUITY" else None
    if ms:
        out.append("🏛 ABD borsası: " + {"open": "🟢 Açık", "closed": "🔴 Kapalı (seans dışı)",
                                        "weekend": "🔴 Kapalı (hafta sonu)"}[ms])
    lq = cfg.get("liquidity", {}).get("high_volume_usd", {"COIN": 50_000_000, "EQUITY": 5_000_000})
    qv = res.get("qv24")
    if qv is not None:
        high = qv >= lq.get(meta["type"], lq.get("COIN", 50_000_000)) and ms in (None, "open")
        out.append("💧 Likidite: " + ("🟢 Yüksek" if high else "🔴 Düşük"))
    return out


def tf_table_html(res):
    tf = res.get("tf")
    if not tf:
        return ""
    rows = [f"{name:<7}│ {TREND_LABEL[tf.get(key)]}" for key, name in TF_ROWS]
    return "<pre>Zaman  │ Trend\n───────┼──────────\n" + "\n".join(rows) + "</pre>"


def technical_rating(votes):
    """TradingView teknik özet mantığı: net = (AL - SAT) / toplam.
    Döner: (etiket, ikon, AL %, SAT %, net %)"""
    n = len(votes) or 1
    buy = sum(1 for _, v in votes if v == 1) / n
    sell = sum(1 for _, v in votes if v == -1) / n
    net = buy - sell
    if net >= 0.5:
        label, icon = "GÜÇLÜ AL", "🟢🟢"
    elif net >= 0.1:
        label, icon = "AL", "🟢"
    elif net > -0.1:
        label, icon = "NÖTR", "⚪"
    elif net > -0.5:
        label, icon = "SAT", "🔴"
    else:
        label, icon = "GÜÇLÜ SAT", "🔴🔴"
    return label, icon, buy * 100, sell * 100, net * 100


def technical_rating_line(votes):
    label, icon, buy, sell, net = technical_rating(votes)
    return f"Teknik görünüm: {icon} <b>{label}</b> · AL %{buy:.0f} · SAT %{sell:.0f} · net {net:+.0f}%"


def indicator_list_lines(res, direction):
    """İndikatörlerin 🟢 AL / 🔴 SAT / ⚪ Nötr listesi (sinyal yönüne göre sıralı)."""
    s = 1 if direction == "long" else -1
    same = [n for n, v in res["votes"] if v == s]
    opp = [n for n, v in res["votes"] if v == -s]
    neu = [n for n, v in res["votes"] if v == 0]
    word, oword = ("AL", "SAT") if s == 1 else ("SAT", "AL")
    icon = {"AL": "🟢", "SAT": "🔴"}
    out = [f"{icon[word]} {word} ({len(same)}/{len(res['votes'])}): " + ", ".join(same)]
    if opp:
        out.append(f"{icon[oword]} {oword}: " + ", ".join(opp))
    if neu:
        out.append("⚪ Nötr: " + ", ".join(neu))
    return out


def build_message(res, direction, cfg, now_utc):
    meta, f, i = res["meta"], res["f"], res["i"]
    side = res[direction]
    other = res["short" if direction == "long" else "long"]
    entry, sl, tps, sl_label = levels(res, direction, cfg)
    prec = meta.get("precision")
    arrow = lambda x: "↑" if x > 0 else ("↓" if x < 0 else "→")

    head = "🟢 <b>LONG</b>" if direction == "long" else "🔴 <b>SHORT</b>"
    if res.get("votes"):
        score_line = (technical_rating_line(res["votes"]) + "\n"
                      + f"Güven skoru: <b>%{side['score']}</b> ({side['agree']}/{side['total']} indikatör aynı yönde)")
    else:
        score_line = (f"Güven skoru: <b>{side['score']}/100</b> ({confidence_label(side['score'])}) · "
                      f"{'Short' if direction == 'long' else 'Long'}: {other['score']}")
    lines = [
        f"{head} · <b>{meta['symbol']}</b> · {TYPE_LABEL.get(meta['type'], meta['type'])} · {cfg['timeframe']}",
        score_line,
        "",
        f"Giriş: <code>{fmt_price(entry, prec)}</code>",
        f"Stop: <code>{fmt_price(sl, prec)}</code> ({pct(sl, entry):+.2f}%) · {sl_label}",
    ]
    for n, tp in enumerate(tps, 1):
        r = cfg["risk"]["tp_r_multiples"][n - 1]
        lines.append(f"TP{n}: <code>{fmt_price(tp, prec)}</code> ({pct(tp, entry):+.2f}%) · {r:g}R")
    if cfg["risk"].get("show_breakeven_note", True):
        lines.append("<i>TP1 sonrası stop girişe çekilebilir.</i>")

    trend_line = tf_table_html(res)
    if res["leader_name"] != "4s trend":
        trend_line += "\n" + leader_line(res)
    vr = res["pd"]["vol_ratio"]
    ind_line = (f"RSI {f['rsi'][i]:.0f} · StochRSI {f['srsi_k'][i]:.0f} · ADX {f['adx'][i]:.0f} · "
                f"CCI {f['cci'][i]:.0f} · Hacim {vr:.1f}x")
    extra = []
    if res.get("oi_chg") is not None:
        extra.append(f"OI 4s {res['oi_chg']*100:+.1f}%")
    extra.append(f"24s {res['chg24']:+.1f}%")

    if res.get("votes"):
        st_word = "AL" if direction == "long" else "SAT"
        lines += ["", f"📌 Supertrend: {'🟢' if st_word == 'AL' else '🔴'} <b>{st_word}</b>"]
    else:
        lines += ["", "📌 Tetik: " + ", ".join(side["triggers"])]
    if res.get("votes"):
        lines += indicator_list_lines(res, direction)
        div = divergence_lines(res)
        if div:
            lines += [""] + div
        vol = volume_lines(res, cfg)
        if vol:
            lines += [""] + vol
        vpl = volume_profile_lines(res, cfg)
        if vpl:
            lines += [""] + vpl
    lines += ["", trend_line] + market_lines(res, cfg, now_utc)
    if not res.get("votes"):      # eski 'score' stratejisinde indikatör değerleri gösterilir
        lines += ["", ind_line, " · ".join(extra)]

    notes = [n for d, n in res["pd"]["notes"] if d == direction] + side["why"]
    if notes:
        lines += [""] + notes

    t_close = datetime.fromtimestamp((f["t"][i] + tf_ms(cfg)) / 1000, TR_TZ).strftime("%d.%m.%Y %H:%M")
    lines += ["", f"🕒 {t_close} TSİ mum kapanışı", "<i>Yatırım tavsiyesi değildir.</i>"]
    return "\n".join(lines)


def build_radar_message(res, rd, cfg, now_utc):
    """Pump/Dump radarı mesajı: Supertrend sinyalleriyle aynı düzen,
    radar skoru ve kırılım sebebi en üstte."""
    meta, f, i = res["meta"], res["f"], res["i"]
    prec = meta.get("precision")
    direction = rd["dir"]
    long_ = direction == "long"
    if rd["kind"] == "start":
        head = "🚀 <b>PUMP BAŞLIYOR</b>" if long_ else "💥 <b>DUMP BAŞLIYOR</b>"
    else:
        head = "👀 <b>PUMP ERKEN UYARI</b>" if long_ else "👀 <b>DUMP ERKEN UYARI</b>"
    lines = [f"{head} · <b>{meta['symbol']}</b> · {TYPE_LABEL.get(meta['type'], meta['type'])} · {cfg['timeframe']}",
             f"Radar skoru: <b>{rd['score']}/100</b> · Yön: {'🟢 LONG' if long_ else '🔴 SHORT'}",
             "📌 Kırılım sebebi: " + " · ".join(rd["reasons"])]
    if res.get("votes"):
        side = res[direction]
        lines += ["", technical_rating_line(res["votes"]),
                  f"Güven skoru: <b>%{side['score']}</b> ({side['agree']}/{side['total']} indikatör aynı yönde)"]
    lines.append("")
    if rd["kind"] == "start":
        entry, sl, tps, sl_label = levels(res, direction, cfg)
        lines += [f"Giriş: <code>{fmt_price(entry, prec)}</code>",
                  f"Stop: <code>{fmt_price(sl, prec)}</code> ({pct(sl, entry):+.2f}%) · {sl_label}"]
        for n, tp in enumerate(tps, 1):
            r = cfg["risk"]["tp_r_multiples"][n - 1]
            lines.append(f"TP{n}: <code>{fmt_price(tp, prec)}</code> ({pct(tp, entry):+.2f}%) · {r:g}R")
        if cfg["risk"].get("show_breakeven_note", True):
            lines.append("<i>TP1 sonrası stop girişe çekilebilir.</i>")
    else:
        lvl = f["hh20"][i] if long_ else f["ll20"][i]
        lines += [f"Fiyat: <code>{fmt_price(f['c'][i], prec)}</code>",
                  f"Kırılım seviyesi: <code>{fmt_price(lvl, prec)}</code> ({pct(lvl, f['c'][i]):+.2f}%)",
                  "<i>Henüz kırılım yok – izlemeye alın, seviye hacimle kırılırsa hareket başlayabilir.</i>"]
    if res.get("votes"):
        st = f["st_dir"][i]
        st_txt = "🟢 <b>AL</b>" if st == 1 else ("🔴 <b>SAT</b>" if st == -1 else "⚪ <b>—</b>")
        lines += ["", f"📌 Supertrend: {st_txt}"] + indicator_list_lines(res, direction)
    for block in (divergence_lines(res), volume_lines(res, cfg), volume_profile_lines(res, cfg)):
        if block:
            lines += [""] + block
    trend = tf_table_html(res)
    if trend:
        lines += ["", trend]
    if res.get("leader_name") and res["leader_name"] != "4s trend":
        lines.append(leader_line(res))
    lines += market_lines(res, cfg, now_utc)
    t_close = datetime.fromtimestamp((f["t"][i] + tf_ms(cfg)) / 1000, TR_TZ).strftime("%d.%m.%Y %H:%M")
    lines += ["", f"🕒 {t_close} TSİ mum kapanışı", "<i>Pump/dump hareketleri çok oynaktır. Yatırım tavsiyesi değildir.</i>"]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Telegram
# --------------------------------------------------------------------------- #
def send_telegram(text, token, chat_id):
    for attempt in range(6):
        data = urllib.parse.urlencode({"chat_id": chat_id, "text": text[:4096], "parse_mode": "HTML",
                                       "disable_web_page_preview": "true"}).encode()
        req = urllib.request.Request(TELEGRAM_API.format(token=token), data=data)
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                if json.loads(r.read().decode()).get("ok"):
                    return True
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="ignore")[:300]
            if e.code == 429:
                # Telegram hız sınırı: önerilen süre kadar bekle ve tekrar dene
                try:
                    wait = int(json.loads(body).get("parameters", {}).get("retry_after", 5))
                except (ValueError, AttributeError):
                    wait = 5
                time.sleep(min(wait + 1, 60))
                continue
            raise RuntimeError(f"Telegram hatası {e.code}: {body}") from None
        time.sleep(2)
    return False


class Notifier:
    def __init__(self):
        self.token = os.environ.get("TELEGRAM_TOKEN", "").strip()
        self.chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
        self.dry = os.environ.get("DRY_RUN") == "1" or not (self.token and self.chat_id)
        if self.dry:
            why = "DRY_RUN açık" if os.environ.get("DRY_RUN") == "1" else "Telegram secret'ları tanımlı değil"
            print(f"ℹ️  Mesajlar sadece log'a yazılacak ({why}).")

    def send(self, text):
        if self.dry:
            print("\n----- TELEGRAM MESAJI (gönderilmedi) -----\n" + text + "\n" + "-" * 42)
            return True
        ok = send_telegram(text, self.token, self.chat_id)
        time.sleep(1.1)   # Telegram grup limiti: ~20 mesaj/dk
        return ok


# --------------------------------------------------------------------------- #
# Ana akış
# --------------------------------------------------------------------------- #
def build_universe(api, cfg):
    info = api.get("/fapi/v1/exchangeInfo")
    ucfg = cfg["universe"]
    include, exclude = set(ucfg["include_types"]), set(ucfg["exclude_symbols"])
    tickers = {}
    for t in api.get("/fapi/v1/ticker/24hr"):
        tickers[t["symbol"]] = {"qv": float(t["quoteVolume"]), "chg": float(t["priceChangePercent"])}
    funding = {}
    for p in api.get("/fapi/v1/premiumIndex"):
        try:
            funding[p["symbol"]] = float(p["lastFundingRate"])
        except (KeyError, ValueError, TypeError):
            pass

    all_meta, universe = {}, []
    min_qv = ucfg["min_quote_volume_24h"]
    for s in info["symbols"]:
        if s.get("quoteAsset") != "USDT" or s.get("status") != "TRADING":
            continue
        if s.get("contractType") not in ("PERPETUAL", "TRADIFI_PERPETUAL"):
            continue
        typ = s.get("underlyingType")
        meta = {"symbol": s["symbol"], "type": typ, "precision": s.get("pricePrecision")}
        all_meta[s["symbol"]] = meta
        if typ not in include or s["symbol"] in exclude:
            continue
        wl = ucfg.get("equity_whitelist")
        if typ == "EQUITY" and wl and s["symbol"].removesuffix("USDT") not in wl:
            continue
        qv = tickers.get(s["symbol"], {}).get("qv", 0)
        if qv < min_qv.get(typ, min_qv["default"]):
            continue
        universe.append(meta)
    return universe, all_meta, tickers, funding


def main():
    cfg = load_json(CONFIG_PATH, None)
    tf_env = os.environ.get("SORBOT_TF", "").strip()
    if cfg and tf_env:
        cfg = apply_tf_profile(cfg, tf_env)
    state_path = STATE_PATH
    if cfg and cfg.get("state_file"):
        state_path = os.path.join(BASE_DIR, "state", cfg["state_file"])
    if not cfg:
        print("HATA: config.json okunamadı", file=sys.stderr)
        return 1
    notifier = Notifier()
    if os.environ.get("TEST_TELEGRAM") == "1":
        ok = notifier.send("✅ <b>SorBot</b> bağlantı testi başarılı. Sinyaller bu sohbete gelecek.")
        print("Test mesajı gönderildi." if ok else "Test mesajı gönderilemedi.")
        return 0 if ok else 1

    started = time.time()
    now_utc = datetime.now(timezone.utc)
    now_ms = int(now_utc.timestamp() * 1000)
    state = load_json(state_path, {"signals": {}, "alerts": {}})
    state.setdefault("signals", {})
    state.setdefault("alerts", {})
    api = Binance()

    try:
        universe, all_meta, tickers, funding = build_universe(api, cfg)
    except Exception as e:  # noqa: BLE001
        print(f"HATA: Binance'e erişilemedi: {e}", file=sys.stderr)
        last = state["alerts"].get("binance_down", 0)
        if time.time() - last > 6 * 3600:
            notifier.send(f"⚠️ <b>SorBot</b>: Binance verisine erişilemiyor.\n<code>{str(e)[:200]}</code>")
            state["alerts"]["binance_down"] = time.time()
            save_json(state_path, state)
        return 1
    by_type = {}
    for m in universe:
        by_type[m["type"]] = by_type.get(m["type"], 0) + 1
    print(f"Taranacak sembol: {len(universe)} {by_type}")

    # Piyasa liderleri (BTC, QQQ) - evrende olmasa da çekilir
    symbols = {m["symbol"]: m for m in universe}
    for typ, lsym in cfg["market_leaders"].items():
        if typ.startswith("_"):
            continue
        if lsym in all_meta and lsym not in symbols:
            symbols[lsym] = dict(all_meta[lsym], leader_only=True)

    def fetch(sym):
        raw = api.get("/fapi/v1/klines", {"symbol": sym, "interval": cfg["timeframe"], "limit": cfg["kline_limit"]})
        return sym, parse_klines(raw, now_ms)

    candles, failed = {}, []
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = [ex.submit(fetch, s) for s in symbols]
        for fu in as_completed(futs):
            try:
                sym, cs = fu.result()
                candles[sym] = cs
            except Exception as e:  # noqa: BLE001
                failed.append(str(e)[:80])
    print(f"Mum verisi: {len(candles)} başarılı, {len(failed)} hatalı ({time.time()-started:.0f}s)")

    if len(failed) > len(symbols) * 0.5:
        last = state["alerts"].get("fetch_fail", 0)
        if time.time() - last > 6 * 3600:
            notifier.send(f"⚠️ <b>SorBot</b>: Sembollerin çoğu için veri alınamadı ({len(failed)}/{len(symbols)}).")
            state["alerts"]["fetch_fail"] = time.time()

    # Lider eğilimleri
    leaders = {}
    for typ, lsym in cfg["market_leaders"].items():
        if typ.startswith("_") or lsym not in candles or len(candles[lsym]) < cfg["min_candles"]:
            continue
        lf = compute_features(candles[lsym], cfg)
        leaders[typ] = {"symbol": lsym, "bias": trend_bias(lf), "ret24": lf["c"][-1] / lf["c"][-1 - bars_per_day(cfg)] - 1}
    for typ, ld in leaders.items():
        print(f"Piyasa lideri {typ}: {ld['symbol']} eğilim {ld['bias']:+.1f}")

    ctx = {"leaders": leaders, "funding": funding, "tickers": tickers, "now_utc": now_utc}
    results = []
    for sym, meta in symbols.items():
        if meta.get("leader_only") or sym not in candles:
            continue
        try:
            r = analyze_symbol(meta, candles[sym], ctx, cfg)
        except Exception as e:  # noqa: BLE001
            print(f"  [{sym}] analiz hatası: {e}")
            continue
        if r:
            r["cfg_pd"] = cfg["pump_dump"]
            results.append(r)
    print(f"Analiz edilen: {len(results)}")

    # Adaylar için açık pozisyon (OI) verisi
    min_s = cfg["signal"]["min_score"]
    cands = [r for r in results
             if (r["long"]["triggers"] and r["long"]["score"] >= min_s - 10)
             or (r["short"]["triggers"] and r["short"]["score"] >= min_s - 10)
             or (r["pd"]["squeeze"] and (r["pd"]["brk_up"] or r["pd"]["brk_dn"]
                                         or r["pd"]["accumulation"] or r["pd"]["distribution"]))]
    def fetch_oi(r):
        try:
            oi = api.get("/futures/data/openInterestHist",
                         {"symbol": r["meta"]["symbol"], "period": "1h", "limit": 5})
            apply_open_interest(r, oi)
        except Exception:  # noqa: BLE001
            pass
    with ThreadPoolExecutor(max_workers=4) as ex:
        list(ex.map(fetch_oi, cands))
    print(f"OI kontrol edilen aday: {len(cands)}")

    # Karar
    now = time.time()
    picks = []
    for r in results:
        d = decide(r, cfg, state, now)
        if d:
            picks.append((r[d]["score"], d, r))
    picks.sort(key=lambda x: -x[0])

    # Ayar yaparken faydalı: en yüksek skorlar
    for key in ("long", "short"):
        top = sorted(results, key=lambda r: -r[key]["score"])[:8]
        print(f"En yüksek {key} skorları: " +
              ", ".join(f"{r['meta']['symbol']} {r[key]['score']}{'*' if r[key]['triggers'] else ''}" for r in top))

    sig_cfg = dict(cfg["signal"])
    if cfg.get("strategy") == "supertrend":
        sig_cfg.update(cfg.get("signal_supertrend", {}))
    maxn = sig_cfg["max_signals_per_run"]
    sent = 0
    for score, d, r in picks[:maxn]:
        fetch_tf_trends(api, r, now_ms, cfg["timeframe"])
        compute_volume_profile(r, cfg)
        msg = build_message(r, d, cfg, now_utc)
        try:
            if notifier.send(msg):
                sent += 1
                state["signals"][f"{r['meta']['symbol']}|{d}"] = now
        except Exception as e:  # noqa: BLE001
            print(f"  Telegram hatası: {e}", file=sys.stderr)

    rest = picks[maxn:]
    if rest:
        lines = ["📋 <b>Diğer sinyaller</b> (limit nedeniyle özet):"]
        for score, d, r in rest[:40]:
            lines.append(f"{'🟢' if d == 'long' else '🔴'} {r['meta']['symbol']} – {d.upper()} {score}")
            state["signals"][f"{r['meta']['symbol']}|{d}"] = now
        try:
            notifier.send("\n".join(lines))
        except Exception as e:  # noqa: BLE001
            print(f"  Telegram hatası: {e}", file=sys.stderr)

    # ---- Pump/Dump radarı (Supertrend'den bağımsız) ----
    rc = cfg.get("pump_radar", {})
    radar = []
    if rc.get("enabled", True):
        picked = {(r["meta"]["symbol"], d) for _, d, r in picks}
        radar_types = set(rc.get("types", ["COIN"]))
        for r in results:
            if r["meta"]["type"] not in radar_types:
                continue
            for rd in pump_radar(r["f"], r["i"], r["pd"], r["chg24"], cfg, r.get("oi_chg"), r.get("funding")):
                key = f"{r['meta']['symbol']}|radar_{rd['dir']}"
                last = state["signals"].get(key)
                if last and now - last < rc.get("cooldown_hours", 12) * 3600:
                    continue
                if (r["meta"]["symbol"], rd["dir"]) in picked:
                    continue
                radar.append((rd["score"], rd, r, key))
        radar.sort(key=lambda x: -x[0])
        for score, rd, r, key in radar[:rc.get("max_per_run", 3)]:
            if "tf" not in r:
                fetch_tf_trends(api, r, now_ms, cfg["timeframe"])
            if "vp" not in r:
                compute_volume_profile(r, cfg)
            try:
                if notifier.send(build_radar_message(r, rd, cfg, now_utc)):
                    sent += 1
                    state["signals"][key] = now
            except Exception as e:  # noqa: BLE001
                print(f"  Telegram hatası: {e}", file=sys.stderr)
    print(f"Pump/Dump radarı: {len(radar)} aday")

    # Eski kayıtları temizle. Deneme modunda kayıt tutulmaz (gerçek sinyalleri engellemesin).
    cutoff = now - 7 * 86400
    state["signals"] = {k: v for k, v in state["signals"].items() if v >= cutoff}
    if not notifier.dry or os.environ.get("SORBOT_SAVE_DRY_STATE") == "1":
        save_json(state_path, state)

    print(f"\nBitti: {len(picks)} sinyal ({sent} detaylı mesaj), {api.requests} istek, "
          f"{time.time()-started:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
