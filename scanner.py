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
def resample_4h(candles):
    """1 saatlik mumlardan tamamlanmış 4 saatlik mumlar üretir."""
    groups = {}
    for c in candles:
        key = c["t"] // (4 * HOUR_MS)
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
    _, f["bb_up"], f["bb_lo"], f["bb_bw"] = ta.bollinger(c, *p["bollinger"])
    f["hh20"] = ta.highest(h, cfg["pump_dump"]["breakout_lookback"])
    f["ll20"] = ta.lowest(l, cfg["pump_dump"]["breakout_lookback"])

    # 4 saatlik trend: her 1s mum için, o ana kadar TAMAMLANMIŞ son 4s mumun durumu
    # (geçmişe dönük testte geleceği görmemek için mum bazında hesaplanır)
    n = len(candles)
    f["h4_ema"], f["h4_st"] = [0] * n, [0] * n
    c4 = resample_4h(candles)
    if len(c4) >= 60:
        cc4 = [x["c"] for x in c4]
        e20, e50 = ta.ema(cc4, 20), ta.ema(cc4, 50)
        st4, _ = ta.supertrend([x["h"] for x in c4], [x["l"] for x in c4], cc4, 10, 3.0)
        k = -1
        for i in range(n):
            close_t = t[i] + HOUR_MS
            while k + 1 < len(c4) and c4[k + 1]["t"] + 4 * HOUR_MS <= close_t:
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


def evaluate_at(meta, f, i, leader_bias, leader_name, funding, chg24, now_utc, cfg):
    """i. mumda (o ana kadarki veriyle) long/short değerlendirmesi.
    Canlı taramada i = son kapanmış mum; backtest'te her geçmiş mum."""
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
    if leader is None or leader["symbol"] == sym:
        leader_bias = (f["h4_ema"][i] + f["h4_st"][i]) / 2
        leader_name = "4s trend"
    else:
        leader_bias = leader["bias"]
        leader_name = leader["symbol"].replace("USDT", "")
    funding = ctx["funding"].get(sym)
    chg24 = ctx["tickers"].get(sym, {}).get("chg", 0.0)
    return evaluate_at(meta, f, i, leader_bias, leader_name, funding, chg24, ctx["now_utc"], cfg)


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
    for key, s in (("long", 1), ("short", -1)):
        side = res[key]
        if oi_chg >= cfg_pd["oi_change_confirm"] and price_chg * s > 0:
            side["score"] = min(100, side["score"] + 4)
            side["why"].append(f"✅ Açık pozisyon artıyor (OI 4s {oi_chg*100:+.1f}%) – hareket destekli")
            if oi_chg >= cfg_pd["oi_change_strong"] and res["pd"]["vol_spike"]:
                side["score"] = min(100, side["score"] + 4)
                side["why"].append("🚀 Güçlü OI + hacim artışı" if s == 1 else "💥 Güçlü OI + hacim artışı")
        elif oi_chg <= -cfg_pd["oi_change_confirm"] and price_chg * s > 0:
            side["score"] = max(0, side["score"] - 4)
            side["why"].append(f"⚠️ OI düşüyor ({oi_chg*100:+.1f}%) – hareket pozisyon kapatmadan kaynaklı olabilir")


def decide(res, cfg, state, now):
    """Sinyal gönderilip gönderilmeyeceğine karar verir."""
    sc = cfg["signal"]
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
        if sc["block_against_leader"] and res["leader_bias"] * s <= -sc["leader_block_threshold"]:
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


def build_message(res, direction, cfg, now_utc):
    meta, f, i = res["meta"], res["f"], res["i"]
    side = res[direction]
    other = res["short" if direction == "long" else "long"]
    entry, sl, tps, sl_label = levels(res, direction, cfg)
    prec = meta.get("precision")
    arrow = lambda x: "↑" if x > 0 else ("↓" if x < 0 else "→")

    head = "🟢 <b>LONG</b>" if direction == "long" else "🔴 <b>SHORT</b>"
    lines = [
        f"{head} · <b>{meta['symbol']}</b> · {TYPE_LABEL.get(meta['type'], meta['type'])} · {cfg['timeframe']}",
        f"Güven skoru: <b>{side['score']}/100</b> ({confidence_label(side['score'])}) · "
        f"{'Short' if direction == 'long' else 'Long'}: {other['score']}",
        "",
        f"Giriş: <code>{fmt_price(entry, prec)}</code>",
        f"Stop: <code>{fmt_price(sl, prec)}</code> ({pct(sl, entry):+.2f}%) · {sl_label}",
    ]
    for n, tp in enumerate(tps, 1):
        r = cfg["risk"]["tp_r_multiples"][n - 1]
        lines.append(f"TP{n}: <code>{fmt_price(tp, prec)}</code> ({pct(tp, entry):+.2f}%) · {r:g}R")
    if cfg["risk"].get("show_breakeven_note", True):
        lines.append("<i>TP1 sonrası stop girişe çekilebilir.</i>")

    st_dir = f["st_dir"][i]
    trend_line = f"Trend: 1s {arrow(st_dir)} · 4s {arrow(f['h4_ema'][i] + f['h4_st'][i])}"
    if res["leader_name"] != "4s trend":
        trend_line += f" · {res['leader_name']} {arrow(res['leader_bias'])}"
    vr = res["pd"]["vol_ratio"]
    ind_line = (f"RSI {f['rsi'][i]:.0f} · StochRSI {f['srsi_k'][i]:.0f} · ADX {f['adx'][i]:.0f} · "
                f"CCI {f['cci'][i]:.0f} · Hacim {vr:.1f}x")
    extra = []
    if res.get("funding") is not None:
        extra.append(f"Fonlama {res['funding']*100:.3f}%")
    if res.get("oi_chg") is not None:
        extra.append(f"OI 4s {res['oi_chg']*100:+.1f}%")
    extra.append(f"24s {res['chg24']:+.1f}%")

    lines += ["", "📌 Tetik: " + ", ".join(side["triggers"]), trend_line, ind_line, " · ".join(extra)]

    notes = [n for d, n in res["pd"]["notes"] if d == direction] + side["why"]
    if meta["type"] == "EQUITY":
        ms = us_market_status(now_utc)
        if ms == "weekend":
            notes.append("⚠️ ABD borsası hafta sonu kapalı – likidite düşük, pazartesi açılışta fark (gap) olabilir")
        elif ms == "closed":
            notes.append("⚠️ ABD borsası seans dışı – likidite düşük")
    if notes:
        lines += [""] + notes

    t_close = datetime.fromtimestamp((f["t"][i] + HOUR_MS) / 1000, TR_TZ).strftime("%d.%m.%Y %H:%M")
    lines += ["", f"🕒 {t_close} TSİ mum kapanışı", "<i>Yatırım tavsiyesi değildir.</i>"]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Telegram
# --------------------------------------------------------------------------- #
def send_telegram(text, token, chat_id):
    for attempt in range(3):
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
                time.sleep(5)
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
        qv = tickers.get(s["symbol"], {}).get("qv", 0)
        if qv < min_qv.get(typ, min_qv["default"]):
            continue
        universe.append(meta)
    return universe, all_meta, tickers, funding


def main():
    cfg = load_json(CONFIG_PATH, None)
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
    state = load_json(STATE_PATH, {"signals": {}, "alerts": {}})
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
            save_json(STATE_PATH, state)
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
        leaders[typ] = {"symbol": lsym, "bias": trend_bias(lf)}
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
             or (r["short"]["triggers"] and r["short"]["score"] >= min_s - 10)]
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

    maxn = cfg["signal"]["max_signals_per_run"]
    sent = 0
    for score, d, r in picks[:maxn]:
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
        for score, d, r in rest[:10]:
            lines.append(f"{'🟢' if d == 'long' else '🔴'} {r['meta']['symbol']} – {d.upper()} {score}")
            state["signals"][f"{r['meta']['symbol']}|{d}"] = now
        try:
            notifier.send("\n".join(lines))
        except Exception as e:  # noqa: BLE001
            print(f"  Telegram hatası: {e}", file=sys.stderr)

    # Eski kayıtları temizle. Deneme modunda kayıt tutulmaz (gerçek sinyalleri engellemesin).
    cutoff = now - 7 * 86400
    state["signals"] = {k: v for k, v in state["signals"].items() if v >= cutoff}
    if not notifier.dry or os.environ.get("SORBOT_SAVE_DRY_STATE") == "1":
        save_json(STATE_PATH, state)

    print(f"\nBitti: {len(picks)} sinyal ({sent} detaylı mesaj), {api.requests} istek, "
          f"{time.time()-started:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
