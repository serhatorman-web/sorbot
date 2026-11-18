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
import re
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
TF_MS = {"5m": 300_000, "15m": 900_000, "30m": 1_800_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}


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

PRECIOUS_METALS = {"XAUUSDT": "Altın", "XAGUSDT": "Gümüş", "XPTUSDT": "Platin", "XPDUSDT": "Paladyum"}
COMMODITY_NAMES = {**PRECIOUS_METALS, "CLUSDT": "WTI Petrol", "BZUSDT": "Brent Petrol",
                   "NATGASUSDT": "Doğal Gaz", "COPPERUSDT": "Bakır"}


# BTC ve ETH sinyalleri renkli bantla ayrışır (Telegram'da arka plan rengi değiştirilemiyor)
BANNERS = {"BTCUSDT": ("🟧", "₿ <b>BTC SİNYALİ</b>"), "ETHUSDT": ("🟦", "Ξ <b>ETH SİNYALİ</b>"),
           # kırmızı/yeşil LONG-SHORT'a ayrıldığı için diğer renkler kullanıldı
           "XRPUSDT": ("⬛", "✕ <b>XRP SİNYALİ</b>"), "BNBUSDT": ("🟨", "🔶 <b>BNB SİNYALİ</b>"),
           "SOLUSDT": ("🟪", "◎ <b>SOL SİNYALİ</b>"), "DOGEUSDT": ("🟫", "🐕 <b>DOGE SİNYALİ</b>"),
           "AVAXUSDT": ("♦️", "🔺 <b>AVAX SİNYALİ</b>"),
           "HYPEUSDT": ("🟦", "⚡ <b>HYPE SİNYALİ</b>"), "LINKUSDT": ("🟦", "🔗 <b>LINK SİNYALİ</b>"),
           "SUIUSDT": ("🟦", "💧 <b>SUI SİNYALİ</b>"), "ADAUSDT": ("🟦", "₳ <b>ADA SİNYALİ</b>"),
           "ZECUSDT": ("🟨", "ⓩ <b>ZEC SİNYALİ</b>"),
           "LTCUSDT": ("⬜", "Ł <b>LTC SİNYALİ</b>"), "BCHUSDT": ("🟩", "Ƀ <b>BCH SİNYALİ</b>"),
           "NEARUSDT": ("⬛", "Ⓝ <b>NEAR SİNYALİ</b>"), "UNIUSDT": ("🟪", "🦄 <b>UNI SİNYALİ</b>")}
TF_SHORT = {"5m": "5dk", "15m": "15dk", "1h": "1s", "4h": "4s", "1d": "1g"}


IND_HEADER = "📋 <b>İNDİKATÖRLER</b>"
HEADERS = ("📍 <b>PIVOTS", "🕯️ <b>PRICE ACTION", "📐 <b>TREND ÇİZGİSİ", "☁️ <b>ICHIMOKU", "📊 <b>HACİM PROFİLİ",
           "🧱 <b>ORDER BLOCK", "〽️ <b>RSI UYUMSUZLUK", "🔊 <b>HACİM</b>")


DIR_SECTIONS = ("📐 <b>TREND ÇİZGİSİ", "☁️ <b>ICHIMOKU", "〽️ <b>RSI UYUMSUZLUK")


def dir_arrow(r):
    """Yön satırının başındaki 🟢 / 🔴 ikonuna ok ekler (🟢▲ / 🔴▼)."""
    if r.startswith("🟢 "):
        return "🟢▲ " + r[2:]
    if r.startswith("🔴 "):
        return "🔴▼ " + r[2:]
    return r


def with_header_line(block):
    """Bölüm başlığının (PIVOTS, ICHIMOKU …) altına kalın yatay çizgi (TREND TABLOSU gibi)."""
    if block and block[0].startswith(HEADERS):
        body = []
        arrows = block[0].startswith(DIR_SECTIONS)
        for r in block[1:]:
            if arrows:
                r = dir_arrow(r)
            # satırlar arasında ince çizgi; pivot hedef grubu (Giriş/TP/Stop) bir arada kalır
            if body and not r.startswith(("TP", "Stop:")):
                body.append(THIN)
            body.append(r)
        return [block[0], SEP] + body
    return block


def arr(x, dec=2):
    """Yüzde değişim renkli okla: +1.28 → '🟢▲ %1.28', -2.5 → '🔴▼ %2.50' (PİYASA DURUMU ile aynı)."""
    if x is None:
        return "–"
    a = "🟢▲" if x > 0 else ("🔴▼" if x < 0 else "⚪▶")
    return f"{a} %{abs(x):.{dec}f}"


def put_st_line(lines, gi, st_line):
    """SUPERTREND satırı Giriş bölümünün çizgisinin üstüne (başlık gibi: satır, altında çizgi, Giriş)."""
    if gi > 0 and lines[gi - 1] == SEP:
        lines[gi - 1:gi - 1] = [st_line]
    else:
        lines[gi:gi] = [st_line, SEP]


MARKET_HEADER = "🌍 <b>PİYASA DURUMU</b>"
THIN = "────────────────"


def market_section(lb, ml):
    """🌍 PİYASA DURUMU: BTC / ETH yönü, BTC Dominance, ABD borsası, likidite."""
    rows = list(lb or []) + list(ml or [])
    if not rows:
        return []
    body = []
    for k, r in enumerate(rows):                 # satırlar arasında ince çizgi (trend tablosu gibi)
        body += ([THIN] if k else []) + [r]
    return ["", MARKET_HEADER, SEP] + body


def section(block):
    """Başlıklı bölüm: üstünde çizgi yok, başlığın altında kalın çizgi. Başlıksız blok: üstünde çizgi."""
    if block and block[0].startswith(HEADERS):
        return [""] + with_header_line(block)
    return ["", SEP] + block


def put_time_top(lines, t_close):
    """Mum kapanış tarihi ve saati bandın hemen altına yazılır (bant yoksa en üste)."""
    tag = f"🕒 {t_close} Mum Kapanışı"
    # bant: aynı renkli simge satırı üstte ve altta (🟩🟥🟧🟦⬛🟨🟪🟫♦️ …)
    if len(lines) >= 3 and lines[0] and lines[2] == lines[0] and not any(ch.isalnum() for ch in lines[0]):
        lines.insert(3, tag)
    else:
        lines.insert(0, tag)


EQUITY_FLAGS = {"EQUITY": "🇺🇸", "KR_EQUITY": "🇰🇷", "HK_EQUITY": "🇭🇰"}
COMMODITY_ICONS = {"XAUUSDT": "🥇", "XAGUSDT": "🥈", "XPTUSDT": "⚪", "XPDUSDT": "⚪", "CLUSDT": "🛢️",
                   "BZUSDT": "🛢️", "NATGASUSDT": "🔥", "COPPERUSDT": "🟤"}


def tr_up(t):
    return t.replace("i", "İ").replace("ı", "I").upper()


def display_name(meta):
    """Banner'daki ad: majörlerde kendi simgesiyle (⚡ HYPE), diğerlerinde 🪙 SUI / 🇺🇸 NVDA / 🥇 ALTIN."""
    b = BANNERS.get(meta["symbol"])
    if b:
        return b[1].replace(" SİNYALİ</b>", "</b>")
    return banner_name(meta)


def banner_name(meta):
    """Banner başlığındaki ad: 🇺🇸 NVDA / 🪙 SUI / 🥇 ALTIN."""
    sym, typ = meta["symbol"], meta.get("type")
    if typ in EQUITY_FLAGS:
        return f"{EQUITY_FLAGS[typ]} <b>{sym.removesuffix('USDT')}</b>"
    if typ == "COMMODITY":
        return f"{COMMODITY_ICONS.get(sym, '🛢️')} <b>{tr_up(COMMODITY_NAMES.get(sym, sym.removesuffix('USDT')))}</b>"
    if typ == "COIN":
        return f"🪙 <b>{sym.removesuffix('USDT')}</b>"
    return None


def banner_lines(meta, cfg, direction=None):
    """Majör coin bandı. Yön verilirse bant yöne göre 🟩 LONG / 🟥 SHORT olur, coin adı başlıkta kalır:
    🟥… / 🔺 AVAX · 📉 SHORT SİNYALİ · 15dk / 🟥…"""
    b = BANNERS.get(meta["symbol"])
    if not b:
        return []
    tf = TF_SHORT.get(cfg.get('timeframe', '1h'), cfg.get('timeframe', ''))
    if direction in ("long", "short"):
        bar = ("🟩" if direction == "long" else "🟥") * 10
        name = b[1].replace(" SİNYALİ</b>", "</b>")
        dtitle = "📈 <b>LONG SİNYALİ</b>" if direction == "long" else "📉 <b>SHORT SİNYALİ</b>"
        return [bar, f"{name} · {dtitle} · {tf}", bar, ""]
    bar = b[0] * 10
    return [bar, f"{b[1]} · {tf}", bar, ""]


# Hisselerin işlem gördüğü borsa (mesajda "Hisse" yerine yazılır). Listede olmayan ABD hissesi: "ABD Borsası".
NYSE_STOCKS = {"BABA", "BE", "BMNR", "COHR", "CRCL", "DELL", "GLW", "IBM", "LLY", "NOW", "ORCL", "TSM", "SPY",
               "BRKB", "JPM", "V", "WMT", "XOM", "UNH", "HD", "ABBV", "BAC", "KO", "MRK", "GEV", "CAT", "ACN",
               "MCD", "DIS", "GS", "SHOP", "UBER", "ANET", "CRM", "NVO", "PFE", "CEG", "BX", "SONY", "USAR"}
NASDAQ_STOCKS = {"AAOI", "AAPL", "ADBE", "AMAT", "AMD", "AMZN", "APP", "ARM", "ASML", "AVGO", "AXTI", "BNC", "CBRS",
                 "COIN", "COST", "CRWV", "FLNC", "GOOGL", "HOOD", "INTC", "IREN", "LITE", "META", "MRNA", "MRVL",
                 "MSFT", "MSTR", "MU", "MUU", "NBIS", "NFLX", "NVDA", "PLTR", "QCOM", "QQQ", "RKLB", "SKHY", "SMCI",
                 "SNDK", "SPCX", "TSLA", "WDC", "PDD", "MELI", "TXN", "KLAC", "LRCX", "CSCO", "PANW", "CRWD",
                 "AMGN", "CRDO", "ASTS", "ALAB"}


def exchange_label(meta):
    sym, typ = meta["symbol"].removesuffix("USDT"), meta.get("type")
    if typ == "KR_EQUITY":
        return "KOSPI"
    if typ == "HK_EQUITY":
        return "HKEX"
    if sym in NASDAQ_STOCKS:
        return "NASDAQ"
    if sym in NYSE_STOCKS:
        return "NYSE"
    return "ABD Borsası"


def type_label(meta):
    """Mesaj başlığındaki tür: Kripto / NASDAQ · NYSE · KOSPI (hisseler) / Değerli Metal (Altın) / Emtia (Brent Petrol)."""
    sym, typ = meta["symbol"], meta["type"]
    if typ in ("EQUITY", "KR_EQUITY", "HK_EQUITY"):
        return exchange_label(meta)
    if typ == "COMMODITY":
        kind = "Değerli Metal" if sym in PRECIOUS_METALS else "Emtia"
        name = COMMODITY_NAMES.get(sym)
        return tr_up(f"{kind} ({name})" if name else kind)
    return TYPE_LABEL.get(typ, typ)


TYPE_LABEL = {"COIN": "KRİPTO", "EQUITY": "NASDAQ", "COMMODITY": "Emtia",
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
# Bir üst zaman dilimi: sinyalin zaman dilimi kaç katı (5dk→15dk, 15dk→1s, 1s→4s, 4s→1g)
UPPER_FACTOR = {5 * 60_000: 3, 15 * 60_000: 4, HOUR_MS: 4, 4 * HOUR_MS: 6, 24 * HOUR_MS: 7}   # 1g → 1 hafta
WEEK_SHIFT = 4 * 24 * HOUR_MS   # Binance haftalık mumu pazartesi 00:00 UTC başlar (1970-01-01 perşembe)


def upper_factor(base_ms):
    return UPPER_FACTOR.get(base_ms, 4)


def resample_4h(candles, base_ms=HOUR_MS):
    """Tamamlanmış bir üst zaman dilimi mumları üretir (ad tarihsel: 1s → 4s; 15dk → 1s; 4s → 1g)."""
    k_ = upper_factor(base_ms)
    shift = WEEK_SHIFT if k_ * base_ms == 7 * 24 * HOUR_MS else 0
    groups = {}
    for c in candles:
        key = (c["t"] - shift) // (k_ * base_ms)
        groups.setdefault(key, []).append(c)
    out = []
    for key in sorted(groups):
        g = groups[key]
        if len(g) != k_:
            continue
        out.append({"t": g[0]["t"], "o": g[0]["o"], "h": max(x["h"] for x in g),
                    "l": min(x["l"] for x in g), "c": g[-1]["c"], "v": sum(x["v"] for x in g),
                    "bv": sum(x.get("bv", 0.0) for x in g)})
    return out


def compute_features(candles, cfg):
    p = cfg["indicators"]
    t = [c["t"] for c in candles]
    o = [c["o"] for c in candles]
    h = [c["h"] for c in candles]
    l = [c["l"] for c in candles]
    c = [c_["c"] for c_ in candles]
    v = [c_["v"] for c_ in candles]

    f = {"t": t, "o": o, "h": h, "l": l, "c": c, "v": v, "bv": [c_.get("bv", c_["v"]) for c_ in candles]}
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
    f["dyna"] = ta.dynarange(f["o"], h, l, c, *p.get("dynarange", [10, 18]))
    f["tflex"], f["tflex_line"] = ta.trendflex(h, l, c, *p.get("trendflex", [4.0, 11]))
    f["sma13"] = ta.sma(c, 13)
    f["ssl"] = ta.ssl_exit(h, l, c, 15)          # SSL Hybrid Advanced çıkış çizgisi (Buy/Sell)
    f["qqe"] = ta.qqe_mod(c)                     # QQE MOD çubuk rengi: +1 mavi, -1 pembe, 0 gri
    f["hh20"] = ta.highest(h, cfg["pump_dump"]["breakout_lookback"])
    f["ll20"] = ta.lowest(l, cfg["pump_dump"]["breakout_lookback"])

    # bir üst zaman dilimi trendi (15dk→1s, 1s→4s, 4s→1g): o ana kadar TAMAMLANMIŞ son üst mumun durumu
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
            while k + 1 < len(c4) and c4[k + 1]["t"] + upper_factor(base_ms) * base_ms <= close_t:
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
        res["notes"].append(("long", f"⚠️ Pump sonrası (3s {arr(chg3*100, 1)}, 24s {arr(chg24, 1)}) – geç kalınmış olabilir"))
        # Negatif uyumsuzluk: fiyat yeni tepe, RSI daha düşük tepe
        r = f["rsi"]
        if None not in r[i - 30:i + 1]:
            if max(c[i - 10:i + 1]) >= max(c[i - 30:i - 10]) and max(r[i - 10:i + 1]) < max(r[i - 30:i - 10]):
                res["short_bonus"] += 8
                res["notes"].append(("short", "💥 Dump riski: pump sonrası negatif RSI uyumsuzluğu"))
    if chg3 <= -pd_cfg["already_pumped_3h"] or chg24 / 100 <= -pd_cfg["already_pumped_24h"]:
        res["short_pen"] += 10
        res["notes"].append(("short", f"⚠️ Dump sonrası (3s {arr(chg3*100, 1)}, 24s {arr(chg24, 1)}) – geç kalınmış olabilir"))
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
            why.append(f"Açık pozisyon artıyor (OI 4s {arr(oi_chg*100, 1)})")
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
             "c": float(k[4]), "v": float(k[7]),            # v = USDT cinsinden hacim
             "bv": float(k[5])}                                # bv = adet (coin/hisse) cinsinden hacim (TradingView ile aynı)
            for k in raw if int(k[6]) < now_ms]


def ichimoku_vote(f, i):
    top, bot = f["ichi_top"][i], f["ichi_bot"][i]
    if top is None or bot is None:
        return 0
    c = f["c"][i]
    return 1 if c > top else (-1 if c < bot else 0)


def uses_trendflex(cfg):
    """Sinyal tetiği TrendFlex mi (yoksa Supertrend 10/3 mü)? config: signal_trigger"""
    return (cfg or {}).get("signal_trigger", "trendflex") == "trendflex"


def trigger_name(cfg):
    return "TrendFlex" if uses_trendflex(cfg) else "Supertrend"


def indicator_votes(f, i, leader_bias, leader_name, trigger="trendflex"):
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
        ("DynaRange", sgn(f["dyna"][i]) if f["dyna"][i] is not None else 0),   # EMA10(ohlc4) - EMA18(ohlc4)
        ("QQE MOD", (f.get("qqe") or [0] * (i + 1))[i]),   # QQE MOD çubuğu: mavi AL, pembe SAT, gri nötr
        # tetik olmayan gösterge listede oy verir: tetik TrendFlex ise Supertrend, Supertrend ise TrendFlex
        (("Supertrend", f["st_dir"][i] or 0) if trigger == "trendflex"
         else ("TrendFlex", (f.get("tflex") or [0] * (i + 1))[i] or 0)),
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
    votes = indicator_votes(f, i, leader_bias, leader_name, cfg.get("signal_trigger", "trendflex"))
    flip = 0
    if uses_trendflex(cfg):
        # TrendFlex_Algo _BUY / SELL etiketi
        flip = ta.trendflex_signal(f["c"], f["tflex_line"], f["sma13"], i)
    else:
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
        trig = [f"{trigger_name(cfg)} {'AL' if s == 1 else 'SAT'} verdi"] if flip == s else []
        why = []
        if dec:
            icon = "🚀" if s == 1 else "💥"
            why.append(f"{icon} {lead_label}'den ayrışıyor: 24s {arr(dec['own']*100, 1)} "
                       f"({lead_label} {arr(dec['leader']*100, 1)}), hacim {dec['vr']:.1f}x")
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
    # piyasa satırları için anlık fiyat / 24s değişim (BTC, ETH, QQQ)
    out["mkt"] = {k: ctx["tickers"].get(k + "USDT") for k in ("BTC", "ETH", "QQQ")}
    out["eth_bias"] = ctx.get("eth_bias")
    out["btc_dom"] = ctx.get("btc_dom")
    out["ndx"] = ctx.get("ndx")
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
            side["why"].append(f"✅ Açık pozisyon artıyor (OI 4s {arr(oi_chg*100, 1)}) – hareket destekli")
            if oi_chg >= cfg_pd["oi_change_strong"] and res["pd"]["vol_spike"]:
                side["score"] = min(100, side["score"] + adj)
                side["why"].append("🚀 Güçlü OI + hacim artışı" if s == 1 else "💥 Güçlü OI + hacim artışı")
        elif oi_chg <= -cfg_pd["oi_change_confirm"] and price_chg * s > 0:
            side["score"] = max(0, side["score"] - adj)
            side["why"].append(f"⚠️ OI düşüyor ({arr(oi_chg*100, 1)}) – hareket pozisyon kapatmadan kaynaklı olabilir")


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
    ps = res.get("pivot_sig")
    if ps and ps.get("dir") == direction:
        return entry, ps["stop"], [v for _, v in ps["tps"]], f"{ps['stop_name']} (pivot)"
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


SEP = "━━━━━━━━━━━━━━━━"   # bölümler arası yatay çizgi

TREND_LABEL = {1: "🟢▲ Yükselişte", -1: "🔴▼ Düşüşte", 0: "⚪▶ Yatay", None: "⚫ Veri yok"}


def icon_row(label, value):
    """Tablo satırı: ikon en başta (tüm ikonlar alt alta aynı hizada), sonra etiket ve değer.
    value '🟢 Yükseliş' gibi ikonlu metin olmalı."""
    icon, word = value.split(" ", 1)
    return f"{icon} {label} · {word}"
TF_ROWS = (("15m", "15dk"), ("1h", "1 saat"), ("4h", "4 saat"), ("1d", "1 gün"), ("1w", "1 hafta"))


def tf_trend(candles):
    """Bir zaman dilimindeki trend: +1 yükseliş, -1 düşüş, 0 nötr, None veri yetersiz.
    4 oy: fiyat/EMA50, EMA20/EMA50, Supertrend yönü, MACD histogramı.
    En az 3 oy aynı yöndeyse ve karşı yönde en fazla 1 oy varsa trend o yöndedir.
    Geçmişi kısa olanlarda (ör. yeni listelenen sembolde haftalık, 35–59 mum) EMA10/EMA20 kullanılır."""
    if len(candles) < 35:
        return None
    c = [x["c"] for x in candles]
    h = [x["h"] for x in candles]
    l = [x["l"] for x in candles]
    fast, slow = (20, 50) if len(candles) >= 60 else (10, 20)
    e20, e50 = ta.ema(c, fast), ta.ema(c, slow)
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


TF_NAMES = {"5m": "5dk", "15m": "15dk", "1h": "1 saat", "4h": "4 saat", "1d": "1 gün", "1w": "1 hafta"}
DIV_TFS = ("15m", "1h", "4h", "1d", "1w")


def fetch_tf_trends(api, res, now_ms, base_tf="1h", order_blocks=True):
    """Mesaj gönderilecek sembol için diğer zaman dilimlerini çeker:
    trend tablosu (15dk / 1s / 4s / 1g) ve RSI uyumsuzluğu (15dk / 1s / 4s / 1g / 1h)."""
    sym = res["meta"]["symbol"]
    f, i = res["f"], res["i"]
    candles = {base_tf: [{"c": f["c"][k], "h": f["h"][k], "l": f["l"][k]} for k in range(i + 1)]}
    for tf in dict.fromkeys([base_tf] + [x for x, _ in TF_ROWS] + list(DIV_TFS)):
        if tf in candles:
            continue
        try:
            raw = api.get("/fapi/v1/klines", {"symbol": sym, "interval": tf, "limit": 300})   # trend çizgisi için ~200 mum
            candles[tf] = parse_klines(raw, now_ms)
        except Exception:  # noqa: BLE001
            candles[tf] = []
    rows = TF_ROWS if any(k == base_tf for k, _ in TF_ROWS) else ((base_tf, TF_NAMES.get(base_tf, base_tf)),) + TF_ROWS
    res["tf_rows"] = rows
    res["tf"] = {tf: tf_trend(candles.get(tf, [])) for tf, _ in rows}
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
    # trend çizgisi kırılımı + retest (RSI uyumsuzluğu ile aynı zaman dilimleri)
    # Kapanış (çizgi grafik) üzerinden, en az 2 temaslı trend çizgileri: sinyal zaman dilimi ve üstü (1 güne kadar)
    tl = []
    base_ms = TF_MS.get(base_tf, HOUR_MS)
    for tf in ("15m", "1h", "4h", "1d"):
        cs = candles.get(tf, [])
        if TF_MS.get(tf, 0) < base_ms or len(cs) < 40:
            continue
        for ev in ta.trendlines_close([x["h"] for x in cs], [x["l"] for x in cs], [x["c"] for x in cs]):
            tl.append(dict(ev, tf=tf, price=cs[-1]["c"]))
    res["tline"] = tl
    # Pivot noktaları (TradingView "Pivot Points Standard", Fibonacci, Auto: 15dk ve altı günlük, üstü haftalık)
    ptf = "1d" if TF_MS.get(base_tf, HOUR_MS) <= 15 * 60 * 1000 else "1w"
    pc = candles.get(ptf) or []
    if pc:
        last = pc[-1]                      # son kapanmış gün / hafta → içinde bulunulan dönemin pivotları
        res["pivot"] = dict(pivot_levels(last["h"], last["l"], last["c"]), tf=ptf,
                            start=last["t"] + (86_400_000 if ptf == "1d" else 7 * 86_400_000))
    # Order block'lar: TradingView'deki "Volumized Order Blocks | Flux Charts" son 1750 mumu kullanır;
    # tarama 499 mumla yapıldığı için mesaj gönderilecek sembolde uzun geçmiş ayrıca çekilir.
    if not order_blocks:
        return
    try:
        hist = fetch_long_history(api, sym, base_tf, now_ms, OB_HISTORY)
        if len(hist) > i:
            res["obs"] = ta.flux_order_blocks([x["h"] for x in hist], [x["l"] for x in hist],
                                              [x["c"] for x in hist], [x.get("bv", x["v"]) for x in hist],
                                              open_=[x["o"] for x in hist], max_dist=1749)
            # TradingView'de son (oluşan) mum da sayıldığı için kapanmış mumlardan 1749 tanesi işlenir
    except Exception:  # noqa: BLE001
        res.pop("obs", None)


OB_HISTORY = 1760


def fetch_long_history(api, sym, tf, now_ms, bars):
    """Son `bars` kapanmış mum (Binance tek istekte en fazla 1500 verir, gerekirse geriye sayfalanır)."""
    out, end = [], None
    while len(out) < bars:
        p = {"symbol": sym, "interval": tf, "limit": min(1500, bars - len(out) + 1)}
        if end:
            p["endTime"] = end
        raw = api.get("/fapi/v1/klines", p)
        if not raw:
            break
        out = parse_klines(raw, now_ms) + out
        end = int(raw[0][0]) - 1
        if len(raw) < p["limit"]:
            break
    seen, uniq = set(), []
    for c in sorted(out, key=lambda x: x["t"]):
        if c["t"] not in seen:
            seen.add(c["t"])
            uniq.append(c)
    return uniq[-bars:]


def compute_volume_profile(res, cfg):
    """Sinyal zaman diliminden hacim profili (VAH / POC / VAL) – Teometric Demand Model V3 ile aynı pencere:
    son `anchor_lookback` (300) mumdaki en yüksek tepe ve en düşük dipten hangisi daha eskiyse oradan bugüne
    (yani son büyük salınımın tamamı). Hacim adet cinsinden (TradingView gibi).
    window = "fixed" seçilirse eski davranış: son `lookback_bars` mum."""
    vp = cfg.get("volume_profile", {})
    if not vp.get("enabled", True):
        return
    f, i = res["f"], res["i"]
    vol = f.get("bv") or f["v"]
    # Hiç işlem olmayan mumlar TradingView grafiğinde yoktur (ör. hafta sonu hisseler); mum sayımında atlanır.
    idx = [k for k in range(i + 1) if vol[k] > 0] or list(range(i + 1))
    hh, ll, vv = [f["h"][k] for k in idx], [f["l"][k] for k in idx], [vol[k] for k in idx]
    if vp.get("window", "swing") == "swing":
        a = ta.swing_anchor(hh, ll, vp.get("anchor_lookback", 300))
    else:
        a = max(0, len(idx) - vp.get("lookback_bars", {}).get(cfg.get("timeframe", "1h"), 150))
    out = ta.volume_profile(hh[a:], ll[a:], vv[a:], vp.get("rows", 24), vp.get("value_area", 0.70))
    res["vp"] = out
    res["vp_ev"] = {}
    if out:
        hh, ll, cc = f["h"][:i + 1], f["l"][:i + 1], f["c"][:i + 1]
        oo = f["o"][:i + 1] if f.get("o") else None
        for name, lvl in zip(("VAH", "POC", "VAL"), out):
            ev = ta.level_retest(hh, ll, cc, lvl, vp.get("retest_window", 10), open_=oo)
            if ev:
                res["vp_ev"][name] = dict(ev, level=lvl)


def volume_lines(res, cfg):
    """Hacim durumu (yüksek/düşük), son mumlardaki büyük yükseliş/düşüş ve hacim patlaması."""
    vc = cfg.get("volume_info", {})
    f, i = res["f"], res["i"]
    if f["vol_ma"][i] in (None, 0):
        return []
    ratio = lambda k: f["v"][k] / f["vol_ma"][k] if f["vol_ma"][k] else 0
    vr = ratio(i)
    high = vr >= vc.get("high_ratio", 1.0)
    out = [("🟢 Hacim yüksek" if high else "🔴 Hacim düşük") + f" ({vr:.1f}x ortalama) → "
           + ("hareket hacimle destekleniyor" if high else "hareket zayıf, teyit için hacim artışı beklenmeli")]
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
            out.append(f"📈 Büyük yükseliş: {arr(chg)} · hacim {ratio(k):.1f}x ({when}) → alıcılar güçlü")
        else:
            out.append(f"📉 Büyük düşüş: {arr(chg)} · hacim {ratio(k):.1f}x ({when}) → satıcılar güçlü")
    peak = max(range(max(0, i - 2), i + 1), key=ratio)
    if ratio(peak) >= vc.get("spike_ratio", 3.0):
        when = "sinyal mumu" if peak == i else f"{i - peak} mum önce"
        pk_up = f["c"][peak] >= f["o"][peak]
        out.append(f"💥 Hacim patlaması: {ratio(peak):.1f}x ortalama ({when}) → "
                   + ("güçlü alım, yükseliş ilgisi" if pk_up else "güçlü satış, düşüş baskısı"))
    return ["🔊 <b>HACİM</b>"] + out


VP_EXPECT = {("VAH", "down"): "düşüş", ("VAH", "up"): "yükselişin devamı",
             ("POC", "down"): "düşüş", ("POC", "up"): "yükseliş",
             ("VAL", "down"): "düşüşün devamı", ("VAL", "up"): "yükseliş"}


def order_block_lines(res, cfg):
    """Order block (sinyal zaman dilimi) – TradingView "Volumized Order Blocks | Flux Charts" ile birebir:
    grafikte görünen bozulmamış boğa (destek) ve ayı (direnç) bölgeleri, hacim ve yüzdeyle.
    Hacim: bölgeyi oluşturan kırılımdaki 3 mumun hacmi; yüzde: bu hacmin iki tarafının oranı (küçük / büyük).
    Fiyat bölgedeyse 'test ediliyor', son 5 mumda bölgeye dokunup 0.5 ATR uzaklaştıysa 'tepki geldi'."""
    oc = cfg.get("order_blocks", {})
    if not oc.get("enabled", True):
        return []
    f, i = res["f"], res["i"]
    a = f["atr"][i]
    if not a:
        return []
    obs = res.get("obs")
    if obs is None and not (f.get("bv") or f.get("v")):
        return []
    if obs is None:      # uzun geçmiş yoksa taramadaki mumlarla
        obs = ta.flux_order_blocks(f["h"][:i + 1], f["l"][:i + 1], f["c"][:i + 1],
                                   (f.get("bv") or f["v"])[:i + 1], open_=f["o"][:i + 1])
    price = f["c"][i]
    prec = res["meta"].get("precision")
    span = TF_NAMES.get(cfg.get("timeframe", "1h"), cfg.get("timeframe", ""))
    out = []
    live = [x for x in obs if not x["breaker"]]
    # fiyata en yakın destek / direnç "ilk" olarak yazılır
    near = {1: max((x["top"] for x in live if x["type"] == 1 and x["top"] < price), default=None),
            -1: min((x["bottom"] for x in live if x["type"] == -1 and x["bottom"] > price), default=None)}
    for ob in sorted(live, key=lambda x: -x["top"]):
        s = ob["type"]
        lo, hi = ob["bottom"], ob["top"]
        dist = (price - hi) if s == 1 else (lo - price)
        zone = f"{fmt_price(lo, prec)} – {fmt_price(hi, prec)}"
        name = "🟢 Boğa OB" if s == 1 else "🔴 Ayı OB"
        vol = f"{ta.fmt_volume(ob['vol'])} (%{ob['pct']})"
        role = "destek" if s == 1 else "direnç"
        touched = any((f["l"][k] <= hi) if s == 1 else (f["h"][k] >= lo) for k in range(max(0, i - 4), i + 1))
        mv, other = ("yükseliş", "düşüş") if s == 1 else ("düşüş", "yükseliş")
        if dist <= 0:
            st = (f"fiyat bölgede, {role} test ediliyor → tutarsa {mv}, kapanışla "
                  f"{'altına inerse' if s == 1 else 'üstüne çıkarsa'} {other} bekleniyor")
        elif touched and dist >= 0.5 * a:
            st = f"✅ bölgeden tepki geldi ({role} çalıştı) → {mv} bekleniyor"
        else:
            pct_ = dist / price * 100
            first = (hi == near[1]) if s == 1 else (lo == near[-1])
            ilk = "ilk " if first else ""
            st = (f"fiyatın %{pct_:.1f} {'altında' if s == 1 else 'üstünde'} ({role}) → "
                  f"{f'düşüşte {ilk}destek, buradan tepki beklenir' if s == 1 else f'yükselişte {ilk}direnç, buradan satış beklenir'}"
                  f" → Sonuç: bu bölgeden {mv} gelebilir")
        out.append(f"{name} {zone} · {vol} · {st}")
    return ([f"🧱 <b>ORDER BLOCK</b> · {span}"] + out) if out else []


def volume_profile_lines(res, cfg):
    """Hacim profili (VAH / POC / VAL): sadece fiyatın şu an bulunduğu seviye yazılır.
    Kırılım: ⏳ retest yok · 🔄 retest yapılıyor · ✅ retest yapıldı.  Tepki: ⚪ bekleniyor · 🟢/🔴 retest yapıldı."""
    evs = res.get("vp_ev") or {}
    if not evs:
        return []
    prec = res["meta"].get("precision")
    span = TF_NAMES.get(cfg.get("timeframe", "1h"), cfg.get("timeframe", ""))
    out = [f"📊 <b>HACİM PROFİLİ</b> · {span}"]
    f, i = res.get("f"), res.get("i")
    price = f["c"][i] if f else None
    names = [n for n in ("VAH", "POC", "VAL") if n in evs]
    if price is not None:
        names = [min(names, key=lambda n: abs(evs[n]["level"] - price))]
    for name in names:
        ev = evs[name]
        lv = fmt_price(ev["level"], prec)
        d = ev.get("dir", ev.get("state"))
        exp = VP_EXPECT.get((name, d), "hareket")
        if ev.get("kind") == "break":
            yon = "aşağı" if d == "down" else "yukarı"
            head = f"{name} - fiyat {lv} seviyesini {yon} kırdı."
            if ev["state"] == "away":
                hareket = "düşüş" if d == "down" else "yükseliş"
                out.append(f"{'⬇️' if d == 'down' else '⬆️'} {head} Retest yapılmadan {hareket} devam etti, "
                           f"fiyat seviyeden uzaklaştı (geç giriş riski).")
            elif ev["state"] == "confirmed":
                out.append(f"✅ {head} Kırılım sonrası retest yapıldı, {exp} bekleniyor.")
            elif ev["state"] == "touch":
                out.append(f"🔄 {head} Kırılım sonrası retest yapılıyor, {exp} teyidi bekleniyor.")
            else:
                out.append(f"⏳ {head} Retest yapılmadı, bekle.")
        else:
            head = f"{name} - fiyat {lv} seviyesine ulaştı."
            if ev["state"] == "confirmed":
                out.append(f"{'🟢' if d == 'up' else '🔴'} {head} Retest yapıldı, {exp} bekleniyor.")
            else:
                out.append(f"⚪ {head} Retest yapılıyor, tepki bekleniyor.")
    return out


def ichimoku_lines(res, direction, cfg):
    """Ichimoku (sinyal zaman dilimi): Bulut, Kijun ve Tenkan için kırılım / retest durumu, Tenkan-Kijun ve ileri bulut,
    sinyal yönüyle uyum (4 koşul) ve retest teyitleri."""
    if not cfg.get("ichimoku_info", {}).get("enabled", True):
        return []
    f, i = res["f"], res["i"]
    ten, kij, top, bot = f.get("ichi_tenkan"), f.get("ichi_kijun"), f.get("ichi_top"), f.get("ichi_bot")
    if not ten or None in (ten[i], kij[i], top[i], bot[i]):
        return []
    prec = res["meta"].get("precision")
    p = fmt_price
    h, l, c = f["h"][:i + 1], f["l"][:i + 1], f["c"][:i + 1]
    nb = (cfg.get("indicators", {}).get("ichimoku") or [9, 26, 52, 26])[2]
    if i + 1 < nb:
        return []
    sb_now = (max(f["h"][i - nb + 1:i + 1]) + min(f["l"][i - nb + 1:i + 1])) / 2
    sa_now = (ten[i] + kij[i]) / 2
    sig = 1 if direction == "long" else -1
    span = TF_NAMES.get(cfg.get("timeframe", "1h"), cfg.get("timeframe", ""))
    out = [f"☁️ <b>ICHIMOKU</b> · {span}"]
    confirmed = {1: [], -1: []}
    # bugünkü bulutun rengi: 26 mum önce hesaplanan Senkou A / B (A > B → yeşil)
    shift = (cfg.get("indicators", {}).get("ichimoku") or [9, 26, 52, 26])[3]
    j = i - shift
    now_col = ""
    if j - nb + 1 >= 0 and ten[j] is not None and kij[j] is not None:
        sa_j = (ten[j] + kij[j]) / 2
        sb_j = (max(f["h"][j - nb + 1:j + 1]) + min(f["l"][j - nb + 1:j + 1])) / 2
        now_col = " (yeşil)" if sa_j > sb_j else (" (kırmızı)" if sa_j < sb_j else "")
    items = (("Bulut", f"Bulut{now_col} {p(bot[i], prec)} – {p(top[i], prec)}", top[:i + 1], bot[:i + 1]),
             ("Kijun", f"Kijun {p(kij[i], prec)}", kij[:i + 1], kij[:i + 1]),
             ("Tenkan", f"Tenkan {p(ten[i], prec)}", ten[:i + 1], ten[:i + 1]))
    for name, label, up, lo in items:
        ev = ta.band_retest(h, l, c, up, lo)
        if not ev:
            continue
        if ev["kind"] == "inside":
            out.append(f"⚪ {label}: fiyat bulutun içinde, kararsız → yön için bulut kırılımı beklenmeli")
            continue
        s_ = 1 if ev["dir"] == "up" else -1
        icon = "🟢" if s_ == 1 else "🔴"
        move = "yükseliş" if s_ == 1 else "düşüş"
        where = "üstünde" if s_ == 1 else "altında"
        sr = "destek" if s_ == 1 else "direnç"
        if ev["kind"] == "break":
            yon = "yukarı" if s_ == 1 else "aşağı"
            tail = {"none": "⏳ Retest yapılmadı, bekle",
                    "touch": f"🔄 Retest yapılıyor, {move} teyidi bekleniyor",
                    "confirmed": f"✅ Retest yapıldı, {move} teyit edildi",
                    "away": f"{'⬆️' if s_ == 1 else '⬇️'} Retest yapılmadan {move} devam etti (geç giriş riski)"}[ev["state"]]
            out.append(f"{icon} {label}: {yon} kırıldı · {tail}")
        elif ev["kind"] == "hold":
            if ev["state"] == "confirmed":
                out.append(f"{icon} {label}: fiyat {where} · ✅ {sr.capitalize()}ten döndü (retest), {move} teyit edildi")
            else:
                out.append(f"{icon} {label}: fiyat {where} · 🔄 {sr.capitalize()} test ediliyor, tepki bekleniyor")
        else:
            out.append(f"{icon} {label}: fiyat {where} ({sr}) → {move} yönü korunuyor")
        if ev["state"] == "confirmed":
            confirmed[s_].append(name)
    tk = 1 if ten[i] > kij[i] else (-1 if ten[i] < kij[i] else 0)
    fut = 1 if sa_now > sb_now else (-1 if sa_now < sb_now else 0)
    tk_txt = {1: "Tenkan Kijun'un üstünde", -1: "Tenkan Kijun'un altında", 0: "Tenkan = Kijun"}[tk]
    fut_txt = {1: "ileri bulut yeşil", -1: "ileri bulut kırmızı", 0: "ileri bulut nötr"}[fut]
    fut_word = {1: "yeşil", -1: "kırmızı", 0: "nötr"}[fut]
    fut_exp = {1: "yükseliş trendi bekleniyor", -1: "düşüş trendi bekleniyor", 0: "yön belirsiz"}[fut]
    fut_line = (f"{'🟢' if fut == 1 else ('🔴' if fut == -1 else '⚪')} İleri bulut ({shift} mum sonrası): {fut_word} · "
                f"{p(min(sa_now, sb_now), prec)} – {p(max(sa_now, sb_now), prec)} → {fut_exp}")
    atr_i = f.get("atr", [None] * (i + 1))[i]
    if fut != 0 and atr_i and abs(sa_now - sb_now) < 0.25 * atr_i:
        fut_line += " · ⚠️ bulut incelmiş, renk dönüşü yakın"
    out.append(fut_line)
    tk_res = {1: " → kısa vadede yükseliş eğilimi", -1: " → kısa vadede düşüş eğilimi", 0: " → kısa vadede kararsız"}[tk]
    out.append(f"{'🟢' if tk == 1 else ('🔴' if tk == -1 else '⚪')} {tk_txt}{tk_res}")
    cloud = 1 if c[-1] > top[i] else (-1 if c[-1] < bot[i] else 0)
    vs_kij = 1 if c[-1] > kij[i] else (-1 if c[-1] < kij[i] else 0)
    n_ok = sum(1 for v in (cloud, tk, vs_kij, fut) if v == sig)
    if n_ok >= 3:
        out.append(f"✅ Ichimoku sinyalle uyumlu ({n_ok}/4)")
    elif n_ok == 2:
        out.append(f"⚪ Ichimoku kararsız ({n_ok}/4)")
    else:
        out.append(f"⚠️ Ichimoku sinyalle uyumsuz ({n_ok}/4)")
    res["_ichi"] = {"n_ok": n_ok, "confirmed": list(confirmed[sig]), "against": list(confirmed[-sig])}
    if confirmed[sig]:
        out.append("✅ Retest teyidi: " + ", ".join(confirmed[sig]))
    if confirmed[-sig]:
        out.append("⚠️ Ters yönde retest teyidi: " + ", ".join(confirmed[-sig]))
    return out


def ssl_signal(f, i, s, wait=5):
    """SSL Hybrid sinyali (kullanıcının kuralı, LONG için; SHORT'ta tersi), sırayla:
    1) Fiyat SSL çıkış çizgisini aşağıdan yukarı keser (SSL Buy) ve üstünde kalır,
    2) 1. teyit: Buy mumunda ya da sonrasında QQE MOD maviye döner,
    3) 2. teyit: QQE'den sonra (ya da aynı mumda) DynaRange yeşil olur.
    Hepsi Buy'dan en fazla `wait` mum içinde; sıra ilk kez tamamlandığı mumda sinyal.
    Döner: SSL Buy/Sell mumunun indeksi ya da None."""
    c, ssl, qqe, dyn = f["c"], f.get("ssl"), f.get("qqe"), f.get("dyna")
    if not ssl or not qqe or not dyn:
        return None

    def cross(j, d):
        if j < 1 or ssl[j] is None or ssl[j - 1] is None:
            return False
        return (c[j] - ssl[j]) * d > 0 and (c[j - 1] - ssl[j - 1]) * d <= 0

    def cond(k):
        if k < 1 or ssl[k] is None or dyn[k] is None:
            return None
        ev = None
        for j in range(k, max(1, k - wait) - 1, -1):
            if cross(j, s):
                ev = j
                break
            if cross(j, -s):
                return None
        if ev is None or (c[k] - ssl[k]) * s <= 0 or dyn[k] * s <= 0 or qqe[k] == -s:
            return None
        if not any(qqe[j] == s for j in range(ev, k + 1)):     # 1. teyit: Buy'dan sonra QQE MOD
            return None
        return ev

    ev = cond(i)
    if ev is None or cond(i - 1) == ev:
        return None
    return ev


def ssl_info_lines(res, direction, lookback=50):
    """Supertrend sinyalinin altında SSL Hybrid stratejisinin durumu (bilgi amaçlı):
    SSL çizgisinin tarafı ve son kesişim, 1. teyit QQE MOD rengi, 2. teyit DynaRange rengi."""
    f, i = res["f"], res["i"]
    ssl, qqe, dyn, c = f.get("ssl"), f.get("qqe"), f.get("dyna"), f["c"]
    if not ssl or ssl[i] is None or not qqe or dyn is None or dyn[i] is None:
        return []
    s = 1 if direction == "long" else -1
    side = 1 if c[i] > ssl[i] else -1
    ago = None
    for j in range(i, max(1, i - lookback) - 1, -1):
        if ssl[j] is None or ssl[j - 1] is None:
            break
        if (c[j] - ssl[j]) * side > 0 and (c[j - 1] - ssl[j - 1]) * side <= 0:
            ago = i - j
            break
    when = "" if ago is None else (" (bu mumda)" if ago == 0 else f" ({ago} mum önce)")
    mark = lambda v: "✅" if v == s else ("❌" if v == -s else "⚪")
    q = qqe[i]
    d = 1 if dyn[i] > 0 else (-1 if dyn[i] < 0 else 0)
    out = [f"🔷 SSL Hybrid: {'🟢 <b>AL</b>' if side == 1 else '🔴 <b>SAT</b>'}{when}",
           f"{mark(q)} 1. teyit: QQE MOD {'mavi' if q == 1 else 'pembe' if q == -1 else 'gri'}",
           f"{mark(d)} 2. teyit: DynaRange {'yeşil' if d == 1 else 'kırmızı' if d == -1 else 'nötr'}"]
    out.append("✅ SSL stratejisi sinyali onaylıyor → işleme girebilirsin" if side == s and q == s and d == s
               else "⚠️ SSL stratejisi sinyali onaylamıyor → işleme girmek riskli, bekle")
    return out


def _pa_basic(f, i, s):
    """Sinyal mumu formasyonları (LONG için; SHORT'ta tersi): pa_engulf yutan mum (sinyal ya da önceki mum),
    pa_inside_break iç mum kırılımı, pa_strong_close güçlü kapanış."""
    o_, h_, l_, c_ = f["o"], f["h"], f["l"], f["c"]
    body = lambda k: abs(c_[k] - o_[k])
    up = lambda k: (c_[k] - o_[k]) * s > 0
    out = {}
    out["pa_engulf"] = any(up(k) and not up(k - 1) and body(k) >= body(k - 1) and
                           ((c_[k] >= o_[k - 1] and o_[k] <= c_[k - 1]) if s == 1
                            else (c_[k] <= o_[k - 1] and o_[k] >= c_[k - 1]))
                           for k in (i, i - 1) if k >= 1)
    out["pa_inside_break"] = (i >= 2 and h_[i - 1] <= h_[i - 2] and l_[i - 1] >= l_[i - 2]
                              and ((c_[i] > h_[i - 1]) if s == 1 else (c_[i] < l_[i - 1])))
    r = h_[i] - l_[i]
    out["pa_strong_close"] = r > 0 and body(i) >= 0.6 * r and up(i) and (
        ((c_[i] - l_[i]) / r >= 0.75) if s == 1 else ((h_[i] - c_[i]) / r >= 0.75))
    return out


def signal_price_action(f, i, s):
    """Supertrend sinyallerinde sinyal mumu ve son mumlardaki price action (LONG için; SHORT'ta tersi).
    pa_engulf (sinyal ya da önceki mum) · pa_hammer pin bar/çekiç (sinyal ya da önceki mum) · pa_star yıldız ·
    pa_inside_break · pa_strong_close · pa_bos: son pivot tepe (2/2, 30 mum) kapanışla kırıldı ·
    pa_structure: son iki pivot dip yükseliyor (SHORT: son iki pivot tepe alçalıyor)"""
    o_, h_, l_, c_ = f["o"], f["h"], f["l"], f["c"]
    a = f["atr"][i] or (h_[i] - l_[i]) or 1e-12
    out = _pa_basic(f, i, s)
    body = lambda k: abs(c_[k] - o_[k])
    up = lambda k: (c_[k] - o_[k]) * s > 0

    def pin(k):
        r = h_[k] - l_[k]
        if r <= 0:
            return False
        wick = (min(o_[k], c_[k]) - l_[k]) if s == 1 else (h_[k] - max(o_[k], c_[k]))
        pos = (c_[k] - l_[k]) / r if s == 1 else (h_[k] - c_[k]) / r
        return wick >= 2 * max(body(k), 1e-12) and pos >= 2 / 3
    out["pa_hammer"] = any(pin(k) for k in (i, i - 1) if k >= 0)
    out["pa_star"] = any(k >= 2 and not up(k - 2) and body(k - 2) >= 0.5 * a and body(k - 1) <= 0.3 * a and up(k)
                         and body(k) >= 0.5 * a
                         and ((c_[k] > (o_[k - 2] + c_[k - 2]) / 2) if s == 1 else (c_[k] < (o_[k - 2] + c_[k - 2]) / 2))
                         for k in (i, i - 1))
    piv_hi = [k for k in range(i - 2, max(1, i - 30), -1) if h_[k] == max(h_[k - 2:k + 3])]
    piv_lo = [k for k in range(i - 2, max(1, i - 30), -1) if l_[k] == min(l_[k - 2:k + 3])]
    ref = piv_hi if s == 1 else piv_lo
    out["pa_bos"] = bool(ref) and ((c_[i] > h_[ref[0]]) if s == 1 else (c_[i] < l_[ref[0]]))
    out["_bos_level"] = (h_[ref[0]] if s == 1 else l_[ref[0]]) if ref else None
    # kırılımdan önceki yapı tersse (LONG: alçalan tepeler, SHORT: yükselen dipler) bu bir karakter değişimi (CHoCH)
    out["_choch"] = len(ref) >= 2 and ((h_[ref[0]] < h_[ref[1]]) if s == 1 else (l_[ref[0]] > l_[ref[1]]))
    two = piv_lo[:2] if s == 1 else piv_hi[:2]
    out["pa_structure"] = len(two) == 2 and ((l_[two[0]] > l_[two[1]]) if s == 1 else (h_[two[0]] < h_[two[1]]))
    return out


def pivot_levels(h, l, c):
    """Fibonacci pivot (TradingView Pivot Points Standard, Type: Fibonacci)."""
    p = (h + l + c) / 3
    r = h - l
    return {"P": p, "R1": p + 0.382 * r, "R2": p + 0.618 * r, "R3": p + r,
            "S1": p - 0.382 * r, "S2": p - 0.618 * r, "S3": p - r}


PIVOT_WEEK_OFFSET = 4 * 86_400_000          # 1970-01-01 perşembe; Binance haftası pazartesi 00:00 UTC başlar


def pivot_period_start(t, period_ms):
    if period_ms == 86_400_000:
        return t // period_ms * period_ms
    return (t - PIVOT_WEEK_OFFSET) // period_ms * period_ms + PIVOT_WEEK_OFFSET


def pivot_from_bars(f, i, tf):
    """Taramadaki mumlardan içinde bulunulan dönemin pivotları (önceki günün / haftanın H-L-C'si).
    TradingView Auto: 15dk ve altı günlük, üstü haftalık. Önceki dönemin tamamı yoksa None."""
    per = 86_400_000 if TF_MS.get(tf, HOUR_MS) <= 15 * 60 * 1000 else 7 * 86_400_000
    start = pivot_period_start(f["t"][i], per)
    prev = start - per
    ks = [k for k in range(i + 1) if prev <= f["t"][k] < start]
    if not ks or f["t"][ks[0]] > prev + TF_MS.get(tf, HOUR_MS) * 2:
        return None
    h = max(f["h"][k] for k in ks)
    l = min(f["l"][k] for k in ks)
    c = f["c"][ks[-1]]
    return dict(pivot_levels(h, l, c), tf="1d" if per == 86_400_000 else "1w", start=start)


def pivot_signal(f, i, s, pv):
    """Pivot stratejisi sinyali: mum pivotun üstünde (SHORT: altında) kapanır + Supertrend + DynaRange + QQE MOD
    aynı yönde; dört şart bu dönemde bu mumda ilk kez birlikte sağlanır. Hedef / stop: R1-R2-R3 / S1
    (SHORT: S1-S2-S3 / R1). Döner: {dir, tps, stop, stop_name} ya da None."""
    if not pv or i < 1:
        return None
    qqe = f.get("qqe") or [0] * (i + 1)

    def ok(k):
        d = f["dyna"][k]
        return ((f["c"][k] - pv["P"]) * s > 0 and f["st_dir"][k] == s and d is not None and d * s > 0
                and qqe[k] == s)
    if not ok(i) or (f["t"][i - 1] >= pv["start"] and ok(i - 1)):
        return None
    price = f["c"][i]
    names = ("R1", "R2", "R3") if s == 1 else ("S1", "S2", "S3")
    stop_name = "S1" if s == 1 else "R1"
    tps = [(n, pv[n]) for n in names if (pv[n] - price) * s > 0]
    stop = pv[stop_name]
    if not tps or (price - stop) * s <= 0:
        return None
    return {"dir": "long" if s == 1 else "short", "tps": tps, "stop": stop, "stop_name": stop_name}


def pivot_retest_line(f, i, P, start):
    """P seviyesinde retest kontrolü (bu dönemin mumları): kapanışla kesildikten sonra gerçekten geri gelip test
    edildi mi, yoksa retest yapmadan mı gitti."""
    if "h" not in f or "l" not in f:
        return None
    since = sum(1 for k in range(i + 1) if f["t"][k] >= start)
    hh, ll, cc = f["h"][:i + 1], f["l"][:i + 1], f["c"][:i + 1]
    oo = f["o"][:i + 1] if f.get("o") else None
    ev = ta.level_retest(hh, ll, cc, P, 10, open_=oo, break_window=max(2, min(since, 200, i - 17)),
                         break_near_atr=1e9)          # retest sonrası fiyat uzaklaşsa da sonucu göster
    a = f["atr"][i] if f.get("atr") else None
    if ev and ev["kind"] == "break" and ev["state"] == "none" and a and abs(cc[-1] - P) > 2.5 * a:
        ev = dict(ev, state="away")                   # retest gelmeden fiyat P'den uzaklaştı
    if not ev:
        return "⚪ Retest: fiyat pivottan uzak, pivota geri gelmedi"
    up = ev["dir"] == "up"
    mv = "yükseliş" if up else "düşüş"
    if ev["kind"] == "break":
        return {"none": "⏳ Retest: pivota geri gelmedi, retest yapılmadı → bekle",
                "touch": f"🔄 Retest: pivota geri geldi, test ediliyor → {mv} teyidi bekleniyor",
                "confirmed": f"✅ Retest: pivot test edildi ve onaylandı → {mv} teyit edildi",
                "away": f"{'⬆️' if up else '⬇️'} Retest yapmadan {mv} devam etti → geç giriş riski"}[ev["state"]]
    role = "destek" if up else "direnç"
    return {"touch": f"🔄 Retest: pivota dokundu, {role} test ediliyor → tepki bekleniyor",
            "confirmed": f"✅ Retest: pivottan tepki geldi ({role} çalıştı) → {mv} teyit edildi"}[ev["state"]]


def pivot_lines(res, direction, cfg):
    """📍 Pivots: kullanıcının stratejisi. LONG: mum beyaz P'nin üstünde kapanır + Supertrend AL + DynaRange yeşil +
    QQE MOD mavi → TP1-2-3 = R1-R2-R3, stop = S1. SHORT tersi (TP S1-S2-S3, stop R1)."""
    if not cfg.get("pivots", {}).get("enabled", True):
        return []
    pv = res.get("pivot")
    f, i = res["f"], res["i"]
    if not pv:
        return []
    up = direction == "long"
    s = 1 if up else -1
    prec = res["meta"].get("precision")
    price = f["c"][i]
    P = pv["P"]
    fp = lambda x: fmt_price(x, prec)
    side = 1 if price > P else -1
    ago = None
    for k in range(i, 0, -1):
        if f["t"][k] < pv["start"]:
            break
        if (f["c"][k] - P) * side > 0 and (f["c"][k - 1] - P) * side <= 0:
            ago = i - k
            break
    when = ("bu mumda kapanış yaptı" if ago == 0 else f"{ago} mum önce kapanış yaptı") if ago is not None else "dönem başından beri"
    out = [f"📍 <b>PIVOTS</b> · {TF_NAMES.get(cfg.get('timeframe', '1h'), cfg.get('timeframe', ''))}"]
    out.append(f"Pivot {fp(P)} · fiyat {'üstünde' if side == 1 else 'altında'} kapanış ({when})")
    rt = pivot_retest_line(f, i, P, pv["start"])
    if rt:
        out.append(rt)
    st = f["st_dir"][i]
    d = f["dyna"][i] or 0
    q = (f.get("qqe") or [0] * (i + 1))[i]
    mark = lambda ok: "✅" if ok else "❌"
    checks = [(side == s, f"Pivot {'üstünde' if up else 'altında'} kapanış"),
              (st == s, f"Supertrend {'AL' if st == 1 else 'SAT' if st == -1 else '—'}"),
              (d * s > 0, f"DynaRange {'yeşil' if d > 0 else 'kırmızı' if d < 0 else 'nötr'}"),
              (q == s, f"QQE MOD {'mavi' if q == 1 else 'pembe' if q == -1 else 'gri'}")]
    out.append(" · ".join(f"{mark(ok)} {txt}" for ok, txt in checks))
    if all(ok for ok, _ in checks):
        tps = [("R1", "R2", "R3") if up else ("S1", "S2", "S3")][0]
        stop_n = "S1" if up else "R1"
        tgt = [(n, pv[n]) for n in tps if (pv[n] - price) * s > 0]
        stop = pv[stop_n]
        if (price - pv[tps[0]]) * s >= 0:            # fiyat ilk hedefi (S1 / R1) geçmiş → hareket kaçmış
            out.append(f"⚠️ Pivot stratejisi onaylandı ama fiyat {tps[0]}'i geçmiş → geç kalındı, bekle")
        elif (price - stop) * s <= 0:
            out.append(f"⚠️ Pivot stratejisi onaylandı ama fiyat {stop_n} stop seviyesinin ötesinde → bekle")
        else:
            out.append(f"✅ Pivot stratejisi onaylandı → {'LONG' if up else 'SHORT'} girilebilir")
            out.append(f"Giriş: Pivot {fp(P)}")
            for k, (n, v) in enumerate(tgt, 1):
                out.append(f"TP{k}: {n} {fp(v)} ({pct(v, P):+.2f}%)")
            out.append(f"Stop: {stop_n} {fp(stop)} ({pct(stop, P):+.2f}%)")
    else:
        out.append("⚠️ Pivot stratejisi onaylamıyor → işleme girmek riskli, bekle")
    return out


def price_action_lines(res, direction, cfg):
    """Supertrend sinyallerinde 🕯️ Price action bölümü."""
    f, i = res["f"], res["i"]
    s = 1 if direction == "long" else -1
    pa = signal_price_action(f, i, s)
    up = direction == "long"
    names = pa_names(direction)
    lvl = pa.get("_bos_level")
    lvl_txt = f" {fmt_price(lvl, res['meta'].get('precision'))}" if lvl is not None else ""
    choch = pa.get("_choch")
    if choch:
        bos_name = (f"Karakter değişimi (CHoCH): son {'alçalan tepe (LH)' if up else 'yükselen dip (HL)'}{lvl_txt} "
                    f"kapanışla kırıldı")
    else:
        bos_name = f"Yapı kırılımı (BOS): son {'tepe' if up else 'dip'}{lvl_txt} kapanışla kırıldı"
    names.update({"pa_hammer": "Pin bar / çekiç (uzun alt iğne)" if up else "Pin bar / ters çekiç (uzun üst iğne)",
                  "pa_bos": bos_name,
                  "pa_structure": "Yükselen dipler (HL)" if up else "Alçalan tepeler (LH)"})
    order = ("pa_bos", "pa_structure", "pa_engulf", "pa_hammer", "pa_star", "pa_inside_break", "pa_strong_close")
    res_txt = pa_result_texts(direction)
    mv = "yükseliş" if up else "düşüş"
    res_txt["pa_bos"] = (f"trend {'yukarı' if up else 'aşağı'} döndü, {mv} teyit edildi" if choch
                         else f"{mv} trendi devam ediyor")
    ok = [f"{names[k]} → {res_txt[k]}" for k in order if pa.get(k)]
    span = TF_NAMES.get(cfg.get("timeframe", "1h"), cfg.get("timeframe", ""))
    fvg = fvg_lines(f, i, s, res["meta"].get("precision"))
    ob = order_block_lines(res, cfg)[1:]          # order block'lar FVG'nin altında (başlıksız)
    return ([f"🕯️ <b>PRICE ACTION</b> · {span}"] + ([f"✅ {x}" for x in ok] or ["⚪ Sinyal mumunda belirgin formasyon yok"])
            + fvg + ob)


def find_fvgs(f, i, lookback=100, min_atr=0.1):
    """Açık (doldurulmamış) Fair Value Gap'ler – i. muma kadar olan veriyle.
    Boğa FVG: low[k] > high[k-2] (3 mumluk boşluk, bölge high[k-2] – low[k]); fiyat bölgenin altına inerse dolmuş sayılır,
    kısmen girerse kalan kısım bölge olur. Ayı FVG tersi. ATR'nin %10'undan küçük boşluklar gürültü sayılıp atlanır.
    Döner: [{"dir": +1/-1, "lo", "hi", "k"}]"""
    h_, l_, at = f["h"], f["l"], f["atr"]
    out = []
    for k in range(max(2, i - lookback + 1), i + 1):
        a = at[k] or 0
        if l_[k] > h_[k - 2] and l_[k] - h_[k - 2] >= min_atr * a:
            lo, hi, d = h_[k - 2], l_[k], 1
        elif h_[k] < l_[k - 2] and l_[k - 2] - h_[k] >= min_atr * a:
            lo, hi, d = h_[k], l_[k - 2], -1
        else:
            continue
        for j in range(k + 1, i + 1):
            if d == 1:
                if l_[j] <= lo:
                    hi = None
                    break
                hi = min(hi, l_[j])
            else:
                if h_[j] >= hi:
                    lo = None
                    break
                lo = max(lo, h_[j])
        # kısmen dolup çok incelmiş boşluklar da gürültü sayılır
        if hi is not None and lo is not None and hi - lo >= min_atr * a:
            out.append({"dir": d, "lo": lo, "hi": hi, "k": k})
    return out


def fvg_lines(f, i, s, precision=None):
    """Price action bölümüne FVG satırları: sinyal mumunun bıraktığı yeni boşluk, en yakın açık destek / direnç FVG'si."""
    gaps = find_fvgs(f, i)
    if not gaps:
        return ["⚪ Yakında açık FVG (fiyat boşluğu) yok"]
    c = f["c"][i]
    fp = lambda x: fmt_price(x, precision)
    zone = lambda g: f"{fp(g['lo'])} – {fp(g['hi'])}"
    up = s == 1
    out = []
    new = [g for g in gaps if g["k"] >= i - 1 and g["dir"] == s]
    if new:
        g = new[-1]
        out.append(f"✅ Yeni {'boğa' if up else 'ayı'} FVG: {zone(g)} → güçlü {'alış' if up else 'satış'} momentumu, "
                   f"geri çekilmede {'destek' if up else 'direnç'} olur → Sonuç: "
                   f"{'yükseliş' if up else 'düşüş'} devam edebilir")
    inside = [g for g in gaps if g["lo"] <= c <= g["hi"]]
    if inside:
        g = inside[-1]
        out.append(f"{'🟢' if g['dir'] == 1 else '🔴'} Fiyat açık bir {'boğa' if g['dir'] == 1 else 'ayı'} FVG içinde ({zone(g)}) → bu bölgede tepki gelebilir"
                   f" → Sonuç: buradan {'yükseliş' if g['dir'] == 1 else 'düşüş'} gelebilir")
    below = [g for g in gaps if g["dir"] == 1 and g["hi"] < c and g not in new]
    above = [g for g in gaps if g["dir"] == -1 and g["lo"] > c and g not in new]
    if below:
        g = max(below, key=lambda x: x["hi"])
        pct = (c - g["hi"]) / c * 100
        what = "geri çekilmede alım bölgesi" if up else "TP bölgesi, burada tepki alımı gelebilir"
        out.append(f"🟢 Boğa FVG (destek): {zone(g)} · %{pct:.2f} aşağıda → {what} → Sonuç: bu bölgeden yükseliş gelebilir")
    if above:
        g = min(above, key=lambda x: x["lo"])
        pct = (g["lo"] - c) / c * 100
        what = "TP bölgesi, burada satış baskısı gelebilir" if up else "geri çekilmede satış bölgesi"
        out.append(f"🔴 Ayı FVG (direnç): {zone(g)} · %{pct:.2f} yukarıda → {what} → Sonuç: bu bölgeden düşüş gelebilir")
    return out or ["⚪ Yakında açık FVG (fiyat boşluğu) yok"]


def pa_result_texts(direction):
    """Price action formasyonlarının sinyal yönündeki anlamı / beklenen sonuç."""
    up = direction == "long"
    mv = "yükseliş" if up else "düşüş"
    side = "alıcılar" if up else "satıcılar"
    return {"pa_bos": f"{mv} trendi teyit edildi",
            "pa_structure": f"{side} baskın, {mv} yapısı sürüyor",
            "pa_engulf": f"{side} kontrolü aldı, {mv} bekleniyor",
            "pa_hammer": f"{'dipte' if up else 'tepede'} güçlü ret, {mv} bekleniyor",
            "pa_star": f"{'dip' if up else 'tepe'} dönüş formasyonu, {mv} bekleniyor",
            "pa_inside_break": f"sıkışma {'yukarı' if up else 'aşağı'} kırıldı, {mv} bekleniyor",
            "pa_strong_close": f"{'alış' if up else 'satış'} baskısı güçlü, {'yükselişin' if up else 'düşüşün'} devamı bekleniyor"}


def pa_names(direction):
    up = direction == "long"
    return {"pa_engulf": f"Yutan {'boğa' if up else 'ayı'} mumu",
            "pa_star": "Sabah yıldızı" if up else "Akşam yıldızı",
            "pa_inside_break": f"İç mum {'yukarı' if up else 'aşağı'} kırıldı",
            "pa_strong_close": f"Güçlü kapanış (mum {'tepesine' if up else 'dibine'} yakın)"}


TL_MAX_DIST = {"15m": 3, "1h": 5, "4h": 10, "1d": 15}     # aktif trend çizgisi en fazla bu % uzaklıktaysa yazılır


def trendline_lines(res):
    """Trend çizgileri (kapanış/çizgi grafik, en az 2 temas). Her zaman dilimi için tek satır:
    son kırılım varsa o, yoksa fiyata en yakın aktif çizgi. Veri yoksa bölüm çıkmaz."""
    prec = res.get("meta", {}).get("precision")
    by_tf = {}
    for ev in res.get("tline") or []:
        by_tf.setdefault(ev["tf"], []).append(ev)
    out = []
    for tf in ("15m", "1h", "4h", "1d"):
        evs = by_tf.get(tf)
        if not evs:
            continue
        brk = [e for e in evs if e["state"] == "broken"]
        # aktif çizgi ancak fiyata yakınsa anlamlı (çok uzaktaki çizgi yazılmaz)
        near = [e for e in evs if e["state"] == "active"
                and abs(e["price"] - e["level"]) / e["price"] * 100 <= TL_MAX_DIST.get(tf, 5)]
        if brk:
            ev = min(brk, key=lambda e: e["bars_ago"])
        elif near:
            ev = min(near, key=lambda e: abs(e["price"] - e["level"]) / e["price"])
        else:
            continue
        name = TF_NAMES.get(tf, tf)
        lvl = fmt_price(ev["level"], prec)
        t = f"{ev['touches']} temas"
        if ev["state"] == "active":
            pct = abs(ev["price"] - ev["level"]) / ev["price"] * 100
            if ev["type"] == "falling":
                out.append(f"🔴 {name}: Düşen trend çizgisi (direnç)"
                           f" → kırılmadıkça düşüş trendi sürüyor, kapanışla üstüne çıkarsa yükseliş gelebilir")
            else:
                out.append(f"🟢 {name}: Yükselen trend çizgisi (destek)"
                           f" → kırılmadıkça yükseliş trendi sürüyor, kapanışla altına inerse düşüş gelebilir")
            continue
        move = "yükseliş" if ev["type"] == "falling" else "düşüş"
        head = (f"🟢 {name}: Düşen trend çizgisi kırıldı" if ev["type"] == "falling"
                else f"🔴 {name}: Yükselen trend çizgisi kırıldı")
        ago = f"{ev['bars_ago']} mum önce" if ev["bars_ago"] else "son mumda"
        tail = {"confirmed": f"✅ Retest yapıldı → {move} başlayabilir",
                "touch": "🔄 Retest ediliyor",
                "away": f"Retest beklemeden güçlü kırılım → {move} sürüyor"}.get(ev["retest"], "⏳ Retest yapılmadı, bekle")
        out.append(f"{head} · {tail}")
    return (["📐 <b>TREND ÇİZGİSİ</b>"] + out) if out else []


def divergence_lines(res):
    d = res.get("div") or {}
    out = []
    if d.get("pos"):
        out.append("🟢 Pozitif uyumsuzluk: " + ", ".join(d["pos"]) + " → düşüşün gücü azalıyor, dönüş için onay bekle")
    if d.get("neg"):
        out.append("🔴 Negatif uyumsuzluk: " + ", ".join(d["neg"]) + " → yükselişin gücü azalıyor, dönüş için onay bekle")
    return (["〽️ <b>RSI UYUMSUZLUK</b>"] + out) if out else []


def fmt_usd(v):
    """4_235_000 -> '4.2M $', 1_250_000_000 -> '1.25B $'."""
    t = lambda x, d: f"{x:.{d}f}".rstrip("0").rstrip(".")
    if v >= 1e9:
        return f"{t(v / 1e9, 2)}B $"
    if v >= 1e6:
        return f"{t(v / 1e6, 1)}M $"
    return f"{v / 1e3:.0f}K $"


def price_tag(t):
    """'(Fiyat 78,500.00 🔴▼ %1.40)' – 24 saatlik değişim; yükselişte 🟢▲."""
    if not t or not t.get("last"):
        return ""
    chg = t.get("chg", 0.0)
    arrow = "🟢▲" if chg > 0 else ("🔴▼" if chg < 0 else "⚪▶")
    return f" (Fiyat {fmt_price(t['last'], 2)} {arrow} %{abs(chg):.2f})"


def bias_tf_label(cfg):
    """Yön hesabının baktığı grafikler: sinyalin zaman dilimi + bir üstü (15dk+1s, 1s+4s, 4s+1g)."""
    base = tf_ms(cfg) if cfg else HOUR_MS
    names = {5 * 60_000: "5dk", 15 * 60_000: "15dk", HOUR_MS: "1s", 4 * HOUR_MS: "4s", 24 * HOUR_MS: "1g",
             7 * 24 * HOUR_MS: "1 hafta"}
    return f"{names.get(base, '?')} + {names.get(upper_factor(base) * base, '?')}"


def leader_line(res, name=None, bias=None, cfg=None):
    """Piyasa lideri yönü (kripto: BTC, hisse: QQQ) + anlık fiyat ve 24s değişim."""
    name = name or res["leader_name"]
    lb_ = res["leader_bias"] if bias is None else bias
    lbl = {1: "🟢▲ Yükselişte", -1: "🔴▼ Düşüşte", 0: "⚪▶ Yatay"}       # BTC / ETH / QQQ yönü
    icon, word = lbl[1 if lb_ >= 0.5 else (-1 if lb_ <= -0.5 else 0)].split(" ", 1)
    # baştaki ikon trendi gösterir; 24s kısmı fiyat değişimi (ayrı ayrı etiketli)
    row = f"{icon} {name} yönü ({bias_tf_label(cfg)}) · Trend: {word}" if cfg else f"{icon} {name} yönü · Trend: {word}"
    t = (res.get("mkt") or {}).get(name)
    if t and t.get("last"):
        chg = t.get("chg", 0.0)
        arrow = "🟢▲" if chg > 0 else ("🔴▼" if chg < 0 else "⚪▶")
        row += f" · 24s: {fmt_price(t['last'], 2)} {arrow} %{abs(chg):.2f}"
    return row


def nasdaq_index():
    """Nasdaq 100 endeksi (Yahoo ^NDX): {'last', 'chg'} – günlük değişim (önceki kapanışa göre). Hata → None."""
    try:
        req = urllib.request.Request("https://query1.finance.yahoo.com/v8/finance/chart/%5ENDX?interval=1d&range=1d",
                                     headers={"User-Agent": "Mozilla/5.0 (SorBot)"})
        with urllib.request.urlopen(req, timeout=15) as r:
            m = json.loads(r.read().decode())["chart"]["result"][0]["meta"]
        price, prev = m.get("regularMarketPrice"), m.get("chartPreviousClose") or m.get("previousClose")
        if not price or not prev:
            return None
        return {"last": float(price), "chg": (price / prev - 1) * 100}
    except Exception as e:  # noqa: BLE001
        print(f"  [uyarı] Nasdaq 100 alınamadı: {e}")
        return None


def btc_dominance(btc_chg24):
    """BTC Dominance (CoinGecko /global): {'dom': %, 'chg': 24s puan değişimi}. Hata olursa None.
    24s değişim: dün = bugün × (1 + toplam piyasa değeri değişimi) / (1 + BTC değişimi)."""
    try:
        req = urllib.request.Request("https://api.coingecko.com/api/v3/global",
                                     headers={"User-Agent": "Mozilla/5.0 (SorBot)", "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as r:
            g = json.loads(r.read().decode())["data"]
        dom = float(g["market_cap_percentage"]["btc"])
        tot = g.get("market_cap_change_percentage_24h_usd")
        chg = None
        if tot is not None and btc_chg24 is not None:
            prev = dom * (1 + tot / 100) / (1 + btc_chg24 / 100)
            chg = dom - prev
        return {"dom": dom, "chg": chg}
    except Exception as e:  # noqa: BLE001
        print(f"  [uyarı] BTC dominance alınamadı: {e}")
        return None


def dominance_line(res):
    """⚪ BTC Dominance · %57.30 (▲ 0.42 puan) → durum → Sonuç (BTC yönüyle birlikte yorum).
    Satır başı rengi dominance yönünü gösterir (yükselişte 🟢, düşüşte 🔴); altcoin etkisi Sonuç'ta."""
    d = res.get("btc_dom")
    if not d:
        return None
    chg = d.get("chg")
    btc = ((res.get("mkt") or {}).get("BTC") or {}).get("chg")
    if chg is None or abs(chg) < 0.05:
        return (f"⚪▶ BTC Dominance · Yatay · %{d['dom']:.2f} (▶ yatay) → BTC ve altcoinler aynı hızda hareket ediyor"
                " → Sonuç: dominance bu işlem için belirleyici değil")
    tag = f"(▲ {chg:.2f} puan)" if chg > 0 else f"(▼ {abs(chg):.2f} puan)"   # renk sadece satır başında
    up_btc = btc is not None and btc > 0
    if chg > 0:
        why = ("para BTC'ye akıyor, BTC altcoinlerden güçlü → altcoinler geride kalabilir"
               " → Sonuç: altcoin LONG'larında temkinli ol, BTC daha güçlü" if up_btc else
               "altcoinler BTC'den daha sert düşüyor"
               " → Sonuç: altcoin LONG'ları riskli, altcoin SHORT'ları öne çıkar")
        icon = "🟢▲"                # ikon dominance yönünü gösterir (yükselişte 🟢▲)
    else:
        why = ("para altcoinlere akıyor (altcoin sezonu belirtisi)"
               " → Sonuç: altcoin LONG'ları için olumlu" if up_btc else
               "BTC altcoinlerden daha sert düşüyor → altcoinler daha güçlü"
               " → Sonuç: altcoin SHORT'larında temkinli ol, altcoinler daha az düşebilir")
        icon = "🔴▼"                # düşüşte 🔴▼; altcoin etkisi Sonuç kısmında
    word = "Yükselişte" if chg > 0 else "Düşüşte"
    return f"{icon} BTC Dominance · {word} · %{d['dom']:.2f} {tag} → {why}"


def leader_block(res, cfg=None):
    """BTC (kriptoda altına ETH) / QQQ yönü satırları."""
    out = []
    if res.get("leader_name") and res["leader_name"] != "4s trend":
        out.append(leader_line(res, cfg=cfg))
    if res["meta"]["type"] == "COIN" and res["meta"]["symbol"] != "ETHUSDT" and res.get("eth_bias") is not None:
        out.append(leader_line(res, "ETH", res["eth_bias"], cfg=cfg))
    if res["meta"]["type"] == "COIN":
        out.append(dominance_line(res))
    return [x for x in out if x]


def market_lines(res, cfg, now_utc):
    """ABD borsası açık/kapalı (tüm sinyallerde) ve likidite yüksek/düşük satırları."""
    meta = res["meta"]
    out = []
    ms = us_market_status(now_utc)
    if ms:
        status = {"open": "Açık", "closed": "Kapalı (seans dışı)", "weekend": "Kapalı (hafta sonu)"}[ms]
        # baştaki ikon Nasdaq (QQQ) yönünü gösterir; açık/kapalı yazıyla, 24s değişim etiketli
        # Nasdaq 100 endeksinin kendisi (Yahoo); alınamazsa Binance QQQ fiyatı
        q, lbl = res.get("ndx"), "Günlük: Nasdaq 100"
        if not q or not q.get("last"):
            q, lbl = (res.get("mkt") or {}).get("QQQ"), "24s: Nasdaq QQQ"
        if q and q.get("last"):
            chg = q.get("chg", 0.0)
            icon, word = ("🟢▲", "Yükselişte") if chg > 0 else (("🔴▼", "Düşüşte") if chg < 0 else ("⚪▶", "Yatay"))
            arrow = "🟢▲" if chg > 0 else ("🔴▼" if chg < 0 else "⚪▶")
            out.append(f"{icon} ABD borsası · {status} · {word} · {lbl} {fmt_price(q['last'], 2)} "
                       f"{arrow} %{abs(chg):.2f}")
        else:
            out.append(f"⚪ ABD borsası · {status}")
    lq = cfg.get("liquidity", {}).get("high_volume_usd", {"COIN": 50_000_000, "EQUITY": 5_000_000})
    qv = res.get("qv24")
    if qv is not None:
        # hisselerde borsa kapalıyken likidite her zaman düşük
        high = qv >= lq.get(meta["type"], lq.get("COIN", 50_000_000)) and (meta["type"] != "EQUITY" or ms == "open")
        out.append(icon_row("Likidite", "🟢 Yüksek" if high else "🔴 Düşük")
                   + f" (24s hacim {fmt_usd(qv)} · yüksek eşiği {fmt_usd(lq.get(meta['type'], lq.get('COIN', 50_000_000)))})")
    return out


def tf_table_html(res):
    """Trend tablosu – normal yazı, kalın başlık ve zaman dilimleri, ayraç çizgili."""
    tf = res.get("tf")
    if not tf:
        return ""
    rows = [icon_row(f"<b>{name}</b>", TREND_LABEL[tf.get(key)]) for key, name in res.get("tf_rows", TF_ROWS)]
    # satırlar arasında ince yatay çizgi (tablo görünümü)
    # başlığın altında kalın çizgi
    # kutu (blockquote) yok: arka plan renksiz, alıntı işareti yok; satırlar arasında ince çizgi
    # başlığın altında bölüm aralarındaki kalın çizgi (━), satırlar arasında ince çizgi
    return "📊 <b>TREND TABLOSU</b>\n" + SEP + "\n" + ("\n" + THIN + "\n").join(rows)


def rating_label(net):
    """TradingView Technical Ratings eşikleri (net -1..+1)."""
    if net > 0.5:
        return "GÜÇLÜ AL", "🟢🟢"
    if net > 0.1:
        return "AL", "🟢"
    if net >= -0.1:
        return "NÖTR", "⚪"
    if net >= -0.5:
        return "SAT", "🔴"
    return "GÜÇLÜ SAT", "🔴🔴"


def tv_rating(res):
    """TradingView 'Technical Ratings' göstergesinin birebir hesabı (15 MA + 11 osilatör) — son mum.
    Döner: (etiket, ikon, AL %, SAT %, toplam puan) ya da None."""
    f = res["f"]
    i = res["i"]
    try:
        vol = f.get("bv") or f["v"]                   # TradingView VWMA adet cinsinden hacim kullanır
        o = ta.tv_technical_rating(f["h"][:i + 1], f["l"][:i + 1], f["c"][:i + 1], vol[:i + 1], last_only=True)[-1]
    except Exception:  # noqa: BLE001
        return None
    if not o or o["all"] is None:
        return None
    vs = [x for x in o["votes"] if x is not None]
    n = len(vs) or 1
    label, icon = rating_label(o["all"])
    return label, icon, sum(1 for x in vs if x == 1) / n * 100, sum(1 for x in vs if x == -1) / n * 100, o["all"]


def rating_votes(res):
    """Teknik görünüm için kullanılan tüm indikatörler: mesajdaki indikatör listesi + Supertrend. Listede zaten olanlar tekrar sayılmaz."""
    f, i = res["f"], res["i"]
    votes = list(res.get("votes") or [])
    names = {n for n, _ in votes}
    c = f["c"][i]
    sgn = lambda x: 1 if x > 0 else (-1 if x < 0 else 0)
    if "Supertrend" not in names and f.get("st_dir"):
        votes.append(("Supertrend", f["st_dir"][i] or 0))
    return votes


def technical_rating(votes):
    """İşlem skoru – AL % ve SAT % (nötrler toplama dahil; tam sayılarla):
      AL %75+  GÜÇLÜ AL | AL %65–74  AL | ikisi de %65 altı  NÖTR | SAT %65–74  SAT | SAT %75+  GÜÇLÜ SAT
    Döner: (etiket, ikon, AL %, SAT %, net %)"""
    n = len(votes) or 1
    b = sum(1 for _, v in votes if v == 1)
    sl = sum(1 for _, v in votes if v == -1)
    if b * 100 >= 75 * n:              # AL %75 ve üzeri
        label, icon = "GÜÇLÜ AL", "🟢🟢"
    elif sl * 100 >= 75 * n:           # SAT %75 ve üzeri
        label, icon = "GÜÇLÜ SAT", "🔴🔴"
    elif b * 100 >= 65 * n:            # AL %65–74
        label, icon = "AL", "🟢"
    elif sl * 100 >= 65 * n:           # SAT %65–74
        label, icon = "SAT", "🔴"
    else:                              # ikisi de %65'in altında
        label, icon = "NÖTR", "⚪"
    return label, icon, b / n * 100, sl / n * 100, (b - sl) * 100 / n


def trend_alignment_line(res, direction):
    """Trend tablosundaki zaman dilimlerinin (15dk/1s/4s/1g) hepsi sinyalle aynı yöndeyse 'uyumlu',
    hepsi ters yöndeyse 'uyumsuz' uyarısı; karışıksa boş. İkon işlem yönüne göre (LONG 🟢, SHORT 🔴)."""
    tf = res.get("tf") or {}
    dirs = [tf.get(k) for k, _ in res.get("tf_rows", TF_ROWS) if tf.get(k) is not None]
    if len(dirs) < 3:
        return None
    s = 1 if direction == "long" else -1
    icon = "🟢" if s == 1 else "🔴"
    if all(d == s for d in dirs):
        return "✅ <b>Bu işlem trend tablosu ile uyumlu</b>"
    if all(d == -s for d in dirs):
        return "🔴 <b>Uyarı: Bu işlem trend tablosu ile uyumsuz</b>"
    return None


def own_tf_alignment_line(res, direction, cfg):
    """Sinyalin kendi zaman dilimindeki trend sinyalle uyumlu mu?
    İkon, trend tablosundaki o zaman diliminin ikonuyla aynı (Yükseliş 🟢, Düşüş 🔴, Nötr ⚪)."""
    tf_key = cfg.get("timeframe", "1h")
    t = (res.get("tf") or {}).get(tf_key)
    if t is None:
        return None
    name = TF_NAMES.get(tf_key, tf_key)
    s = 1 if direction == "long" else -1
    icon = {1: "🟢", -1: "🔴", 0: "⚪"}[t]
    if t == s:
        # kendi zaman dilimi uyumlu; daha üst zaman dilimlerinden ters olan var mı?
        rows = [k for k, _ in res.get("tf_rows", TF_ROWS)]
        names = dict(res.get("tf_rows", TF_ROWS))
        higher = rows[rows.index(tf_key) + 1:] if tf_key in rows else []
        against = [names[k] for k in higher if (res.get("tf") or {}).get(k) == -s]
        if against:
            return (f"🔴 <b>Uyarı: İşlem kendi zaman dilimiyle ({name}) uyumlu ama üst zaman dilimleriyle "
                    f"({', '.join(against)}) uyumsuz</b>")
        return f"✅ İşlem kendi zaman dilimiyle ({name}) uyumlu"
    if t == -s:
        return f"🔴 <b>Uyarı: İşlem kendi zaman dilimiyle ({name}) uyumsuz</b>"
    return f"⚪ İşlem kendi zaman diliminde ({name}) yatay"


def technical_rating_line(votes, rating=None):
    label, icon, buy, sell, net = rating or technical_rating(votes)
    # SAT / GÜÇLÜ SAT'ta önce SAT yüzdesi, diğerlerinde önce AL yüzdesi
    b, sl = round(buy), round(sell)
    parts = [f"AL 🟢▲ %{b}", f"SAT 🔴▼ %{sl}"]
    if "SAT" in label:
        parts.reverse()
    return f"<b>İŞLEM SKORU :</b> {icon} {label} · ({parts[0]} / {parts[1]})"


def indicator_list_lines(res, direction):
    """İndikatörlerin 🟢 AL / 🔴 SAT / ⚪ Nötr listesi (sinyal yönüne göre sıralı)."""
    s = 1 if direction == "long" else -1
    same = [n for n, v in res["votes"] if v == s]
    opp = [n for n, v in res["votes"] if v == -s]
    neu = [n for n, v in res["votes"] if v == 0]
    word, oword = ("AL", "SAT") if s == 1 else ("SAT", "AL")
    icon = {"AL": "🟢▲", "SAT": "🔴▼"}
    out = [f"{icon[word]} {word} ({len(same)}): " + ", ".join(same)] if same else []
    # boş olan satır (ör. %100 AL iken SAT/Nötr) yazılmaz
    if opp:
        out += ([""] if out else []) + [f"{icon[oword]} {oword} ({len(opp)}): " + ", ".join(opp)]
    if neu:
        out += ([""] if out else []) + [f"⚪▶ Nötr ({len(neu)}): " + ", ".join(neu)]
    return out


def plain_font(text):
    """Tüm mesajı normal yazı tipinde bırakır: <i>, <code>, <pre> kaldırılır (kalın <b> ve linkler kalır)."""
    return re.sub(r"</?(i|code|pre)>", "", text)


def build_message(res, direction, cfg, now_utc):
    meta, f, i = res["meta"], res["f"], res["i"]
    side = res[direction]
    other = res["short" if direction == "long" else "long"]
    entry, sl, tps, sl_label = levels(res, direction, cfg)
    prec = meta.get("precision")
    arrow = lambda x: "↑" if x > 0 else ("↓" if x < 0 else "→")

    head = "🟢 <b>LONG</b>" if direction == "long" else "🔴 <b>SHORT</b>"
    ssl_sig = res.get("ssl_sig") if (res.get("ssl_sig") or {}).get("dir") == direction else None
    if ssl_sig:
        head = "🔷 <b>SSL</b> · " + head
    if (res.get("pivot_sig") or {}).get("dir") == direction:
        head = "📍 <b>PIVOT</b> · " + head
    # teknik görünüm (Güçlü AL / AL / Nötr / SAT / Güçlü SAT, yüzdeli) + trend uyum satırları; güven skoru yok
    align = [x for x in (trend_alignment_line(res, direction), own_tf_alignment_line(res, direction, cfg)) if x]
    if res.get("votes") and cfg.get("technical_rating", {}).get("enabled", True):
        align.insert(0, technical_rating_line(rating_votes(res)))
    top = []
    for x in align:
        top += [x, ""]
    # bant: BTC / ETH kendi bandı; diğerleri LONG 🟩 / SHORT 🟥 (PUMP / DUMP SİNYALİ gibi)
    banner = banner_lines(meta, cfg, direction)
    if not banner:
        bar = ("🟩" if direction == "long" else "🟥") * 10
        title = "📈 <b>LONG SİNYALİ</b>" if direction == "long" else "📉 <b>SHORT SİNYALİ</b>"
        tf_s = TF_SHORT.get(cfg.get('timeframe', '1h'), cfg.get('timeframe', ''))
        name = banner_name(meta)
        if name:      # 🟥… / 🇺🇸 NVDA · 📉 SHORT SİNYALİ · 15dk / 🟥…  (hisse, altcoin, emtia)
            title = f"{name} · {title}"
        banner = [bar, f"{title} · {tf_s}", bar, ""]
    lines = banner + [
        f"{head} · <b>{meta['symbol']}</b> · {type_label(meta)} · {cfg['timeframe']}",
        SEP] + top + ([SEP] if top else []) + [
        f"<b>Giriş:</b> {fmt_price(entry, prec)}",
        "",
        f"<b>Stop:</b> {fmt_price(sl, prec)} ({pct(sl, entry):+.2f}%) · {sl_label}",
    ]
    psig = res.get("pivot_sig") if (res.get("pivot_sig") or {}).get("dir") == direction else None
    for n, tp in enumerate(tps, 1):
        if psig:
            lab = psig["tps"][n - 1][0]
        else:
            lab = f"{cfg['risk']['tp_r_multiples'][n - 1]:g}R"
        lines += ["", f"<b>TP{n}:</b> {fmt_price(tp, prec)} ({pct(tp, entry):+.2f}%) · {lab}"]
    if cfg["risk"].get("show_breakeven_note", True):
        lines += ["", "<i>TP1 sonrası stop girişe çekilebilir.</i>"]

    trend_line = tf_table_html(res)
    lb = leader_block(res, cfg)
    vr = res["pd"]["vol_ratio"]
    ind_line = (f"RSI {f['rsi'][i]:.0f} · StochRSI {f['srsi_k'][i]:.0f} · ADX {f['adx'][i]:.0f} · "
                f"CCI {f['cci'][i]:.0f} · Hacim {vr:.1f}x")
    extra = []
    if res.get("oi_chg") is not None:
        extra.append(f"OI 4s {res['oi_chg']*100:+.1f}%")
    extra.append(f"24s {res['chg24']:+.1f}%")

    if ssl_sig:
        up = direction == "long"
        st = f["st_dir"][i]
        st_txt = ("🟢 <b>AL</b>" if st == 1 else "🔴 <b>SAT</b>" if st == -1 else "⚪ <b>—</b>")
        st_note = "" if st == (1 if up else -1) else f" (henüz {'AL' if up else 'SAT'} vermedi)"
        lines += ["", SEP, f"📌 Tetik: SSL Hybrid {'🟢 <b>AL</b>' if up else '🔴 <b>SAT</b>'}",
                  f"✅ 1. teyit: QQE MOD {'mavi' if up else 'pembe'} → {'alıcılar' if up else 'satıcılar'} güçlü",
                  f"✅ 2. teyit: DynaRange {'yeşil' if up else 'kırmızı'} → {'yükseliş' if up else 'düşüş'} teyit edildi",
                  "", f"📌 <b>{trigger_name(cfg).upper()}</b>: {st_txt}{st_note}"]
    elif res.get("votes"):
        st_word = "AL" if direction == "long" else "SAT"
        if psig:
            lines += ["", SEP, f"📌 Tetik: Pivot {'üstünde' if direction == 'long' else 'altında'} kapanış "
                               f"+ Supertrend, DynaRange, QQE MOD onayı"]
        st_line = f"📌 <b>{trigger_name(cfg).upper()}</b>: {'🟢▲' if st_word == 'AL' else '🔴▼'} <b>{st_word}</b>"
        if psig:
            lines += ["", st_line]
        else:
            # Supertrend satırı Giriş'in üstünde; indikatör listesi kendi çizgisiyle aşağıda
            gi = next((k for k, x in enumerate(lines) if x.startswith("<b>Giriş:</b>")), None)
            if gi is not None:
                put_st_line(lines, gi, st_line)
                lines += ["", IND_HEADER, SEP]
            else:
                lines += ["", SEP, st_line]
        si = ssl_info_lines(res, direction) if cfg.get("ssl_info", {}).get("enabled", True) else []
        if si:
            lines += [""] + si
    else:
        lines += ["", "📌 Tetik: " + ", ".join(side["triggers"])]
    if res.get("votes"):
        lines += ([] if lines and lines[-1] == SEP else [""]) + indicator_list_lines(res, direction)
        # sıra (kullanıcı isteği): İNDİKATÖRLER → TREND TABLOSU → TREND ÇİZGİSİ → HACİM → RSI UYUMSUZLUK → PRICE ACTION → PİYASA DURUMU
        # PIVOTS, ICHIMOKU, HACİM PROFİLİ, PRICE ACTION ve TREND ÇİZGİSİ kullanıcı isteğiyle kaldırıldı
        if trend_line:
            lines += ["", trend_line]
            trend_line = None
        for block in (trendline_lines(res), volume_lines(res, cfg), divergence_lines(res),     # PRICE ACTION kapalı (kullanıcı isteği)
                      (price_action_lines(res, direction, cfg) if cfg.get("price_action", {}).get("enabled") else [])):
            if block:
                lines += section(block)
    lines += (["", trend_line] if trend_line else []) + market_section(lb, market_lines(res, cfg, now_utc))
    if not res.get("votes"):      # eski 'score' stratejisinde indikatör değerleri gösterilir
        lines += ["", ind_line, " · ".join(extra)]

    notes = [n for d, n in res["pd"]["notes"] if d == direction] + side["why"]
    if notes:
        lines += [""] + notes

    t_close = datetime.fromtimestamp((f["t"][i] + tf_ms(cfg)) / 1000, TR_TZ).strftime("%d.%m.%Y %H:%M")
    put_time_top(lines, t_close)
    lines += ["", "Yatırım tavsiyesi değildir."]
    return plain_font("\n".join(lines))


def build_radar_message(res, rd, cfg, now_utc):
    """Pump/Dump radarı mesajı: Supertrend sinyalleriyle aynı düzen,
    radar skoru ve kırılım sebebi en üstte."""
    meta, f, i = res["meta"], res["f"], res["i"]
    prec = meta.get("precision")
    direction = rd["dir"]
    long_ = direction == "long"
    tf_s = TF_SHORT.get(cfg.get("timeframe", "1h"), cfg.get("timeframe", ""))
    # sinyallerdeki gibi bant: 🟩 PUMP / 🟥 DUMP (erken uyarılar dahil)
    bar = ("🟩" if long_ else "🟥") * 10
    if rd["kind"] == "start":
        title = "🚀 <b>PUMP SİNYALİ</b>" if long_ else "💥 <b>DUMP SİNYALİ</b>"
    else:
        title = "👀 <b>PUMP ERKEN UYARI</b>" if long_ else "👀 <b>DUMP ERKEN UYARI</b>"
    name = display_name(meta)      # sinyallerdeki gibi: 🟩… / ⚡ HYPE · 🚀 PUMP SİNYALİ · 1s / 🟩…
    banner = [bar, f"{name + ' · ' if name else ''}{title} · {tf_s}", bar, ""]
    head = "🟢 <b>LONG</b>" if long_ else "🔴 <b>SHORT</b>"
    score = ([technical_rating_line(rating_votes(res)), ""]
             if res.get("votes") and cfg.get("technical_rating", {}).get("enabled", True) else [])
    lines = banner + [f"{head} · <b>{meta['symbol']}</b> · {type_label(meta)} · {cfg['timeframe']}", SEP] + score + [
             f"<b>RADAR SKORU :</b> {rd['score']}/100 · Yön: {'🟢 LONG' if long_ else '🔴 SHORT'}",
             "📌 Kırılım sebebi: " + " · ".join(rd["reasons"])]
    for extra_line in (trend_alignment_line(res, direction), own_tf_alignment_line(res, direction, cfg)):
        if extra_line:
            lines += ["", extra_line]
    lines += ["", SEP]
    if rd["kind"] == "start":
        entry, sl, tps, sl_label = levels(res, direction, cfg)
        lines += [f"<b>Giriş:</b> {fmt_price(entry, prec)}", "",
                  f"<b>Stop:</b> {fmt_price(sl, prec)} ({pct(sl, entry):+.2f}%) · {sl_label}"]
        for n, tp in enumerate(tps, 1):
            r = cfg["risk"]["tp_r_multiples"][n - 1]
            lines += ["", f"<b>TP{n}:</b> {fmt_price(tp, prec)} ({pct(tp, entry):+.2f}%) · {r:g}R"]
        if cfg["risk"].get("show_breakeven_note", True):
            lines += ["", "<i>TP1 sonrası stop girişe çekilebilir.</i>"]
    else:
        lvl = f["hh20"][i] if long_ else f["ll20"][i]
        lines += [f"Fiyat: <code>{fmt_price(f['c'][i], prec)}</code>",
                  f"Kırılım seviyesi: <code>{fmt_price(lvl, prec)}</code> ({arr(pct(lvl, f['c'][i]))})",
                  "<i>Henüz kırılım yok – izlemeye alın, seviye hacimle kırılırsa hareket başlayabilir.</i>"]
    if res.get("votes"):
        st = f["tflex"][i] if uses_trendflex(cfg) else f["st_dir"][i]
        st_txt = "🟢▲ <b>AL</b>" if st == 1 else ("🔴▼ <b>SAT</b>" if st == -1 else "⚪▶ <b>—</b>")
        st_line = f"📌 <b>{trigger_name(cfg).upper()}</b>: {st_txt}"
        gi = next((k for k, x in enumerate(lines) if x.startswith("<b>Giriş:</b>")), None)
        if gi is not None:                       # Supertrend satırı Giriş'in üstünde
            put_st_line(lines, gi, st_line)
            lines += ["", IND_HEADER, SEP] + indicator_list_lines(res, direction)
        else:
            lines += ["", SEP, st_line, ""] + indicator_list_lines(res, direction)
    # sıra (kullanıcı isteği): İNDİKATÖRLER → TREND TABLOSU → TREND ÇİZGİSİ → HACİM → RSI UYUMSUZLUK → PRICE ACTION → PİYASA DURUMU
    trend = tf_table_html(res)
    if trend:
        lines += ["", trend]
    for block in (trendline_lines(res), volume_lines(res, cfg), divergence_lines(res),     # PRICE ACTION kapalı (kullanıcı isteği)
                      (price_action_lines(res, direction, cfg) if cfg.get("price_action", {}).get("enabled") else [])):
        if block:
            lines += section(block)
    lines += market_section(leader_block(res, cfg), market_lines(res, cfg, now_utc))
    t_close = datetime.fromtimestamp((f["t"][i] + tf_ms(cfg)) / 1000, TR_TZ).strftime("%d.%m.%Y %H:%M")
    put_time_top(lines, t_close)
    lines += ["", "Pump/dump hareketleri çok oynaktır. Yatırım tavsiyesi değildir."]
    return plain_font("\n".join(lines))


# --------------------------------------------------------------------------- #
# Telegram
# --------------------------------------------------------------------------- #
def send_telegram(text, token, chat_id, attempts=6):
    """Telegram'a gönderir. Hız sınırı (429), bağlantı kopması ve zaman aşımında bekleyip yeniden dener
    (2, 4, 8, 16, 30 sn). Kalıcı hatada (400 vb.) RuntimeError fırlatır."""
    last_err = None
    for attempt in range(attempts):
        data = urllib.parse.urlencode({"chat_id": chat_id, "text": text[:4096], "parse_mode": "HTML",
                                       "disable_web_page_preview": "true"}).encode()
        req = urllib.request.Request(TELEGRAM_API.format(token=token), data=data)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
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
            if e.code >= 500:                          # Telegram sunucu hatası → tekrar dene
                last_err = f"{e.code}"
                time.sleep(min(2 ** (attempt + 1), 30))
                continue
            raise RuntimeError(f"Telegram hatası {e.code}: {body}") from None
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            # bağlantı koptu / zaman aşımı → bekle ve tekrar dene
            last_err = e
            print(f"  Telegram bağlantı sorunu ({e}), {attempt + 1}. deneme – tekrar denenecek", file=sys.stderr)
            time.sleep(min(2 ** (attempt + 1), 30))
            continue
        time.sleep(2)
    if last_err is not None:
        raise RuntimeError(f"Telegram'a ulaşılamadı ({attempts} deneme): {last_err}")
    return False


class Notifier:
    def __init__(self):
        self.token = os.environ.get("TELEGRAM_TOKEN", "").strip()
        self.chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
        # Majör coin sinyalleri ayrı kanala ("Sorbot Majör Coinler"); diğer her şey ana kanala
        tg = {}
        try:
            with open(os.path.join(BASE_DIR, "config.json"), encoding="utf-8") as fh:
                tg = json.load(fh).get("telegram", {})
        except Exception:  # noqa: BLE001
            pass
        self.major_chat = (os.environ.get("TELEGRAM_CHAT_ID_MAJOR") or str(tg.get("major_chat_id") or "")).strip()
        self.major_symbols = set(tg.get("major_symbols", ["BTCUSDT", "ETHUSDT"]))
        # Hisse sinyalleri ayrı kanala ("Sorbot Nasdaq")
        self.equity_chat = (os.environ.get("TELEGRAM_CHAT_ID_EQUITY") or str(tg.get("equity_chat_id") or "")).strip()
        self.equity_types = set(tg.get("equity_types", ["EQUITY", "KR_EQUITY", "HK_EQUITY"]))
        # Emtia sinyalleri ayrı kanala ("Sorbot Emtia")
        self.commodity_chat = (os.environ.get("TELEGRAM_CHAT_ID_COMMODITY") or str(tg.get("commodity_chat_id") or "")).strip()
        # Piyasa/haber bülteni, ekonomik takvim ve anlık veriler ayrı kanala ("Sorbot Piyasa Bülteni")
        self.bulletin_chat = (os.environ.get("TELEGRAM_CHAT_ID_BULLETIN") or str(tg.get("bulletin_chat_id") or "")).strip()
        self.dry = os.environ.get("DRY_RUN") == "1" or not (self.token and self.chat_id)
        if self.dry:
            why = "DRY_RUN açık" if os.environ.get("DRY_RUN") == "1" else "Telegram secret'ları tanımlı değil"
            print(f"ℹ️  Mesajlar sadece log'a yazılacak ({why}).")

    def chat_for(self, symbol=None, typ=None):
        if symbol and self.major_chat and symbol in self.major_symbols:
            return self.major_chat
        if typ and self.equity_chat and typ in self.equity_types:
            return self.equity_chat
        if typ == "COMMODITY" and self.commodity_chat:
            return self.commodity_chat
        if typ == "BULLETIN" and self.bulletin_chat:
            return self.bulletin_chat
        return self.chat_id

    def send(self, text, symbol=None, typ=None):
        chat = self.chat_for(symbol, typ)
        if self.dry:
            where = (" → Sorbot Majör Coinler kanalı" if chat == self.major_chat else
                     " → Sorbot Nasdaq kanalı" if chat == self.equity_chat else
                     " → Sorbot Emtia kanalı" if chat == self.commodity_chat else
                     " → Sorbot Piyasa Bülteni kanalı" if chat == self.bulletin_chat else "")
            print(f"\n----- TELEGRAM MESAJI (gönderilmedi{where}) -----\n" + text + "\n" + "-" * 42)
            return True
        ok = send_telegram(text, self.token, chat)
        time.sleep(1.1)   # Telegram grup limiti: ~20 mesaj/dk
        return ok


# --------------------------------------------------------------------------- #
# Ana akış
# --------------------------------------------------------------------------- #
def tick_decimals(sym_info):
    """Fiyatın ondalık sayısı: PRICE_FILTER tickSize'a göre (ör. 0.0001 → 4); yoksa pricePrecision."""
    for flt in sym_info.get("filters", []):
        if flt.get("filterType") == "PRICE_FILTER" and flt.get("tickSize"):
            t = flt["tickSize"].rstrip("0")
            return len(t.split(".")[1]) if "." in t and t.split(".")[1] else 0
    return sym_info.get("pricePrecision")


TOP_COINS_PATH = os.path.join(BASE_DIR, "state", "top_coins.json")


def coin_base(symbol):
    """Binance kontratından coin kodu: 1000PEPEUSDT → PEPE, 1MBABYDOGEUSDT → BABYDOGE."""
    b = symbol.removesuffix("USDT")
    for pre in ("1000000", "10000", "1000", "1M"):
        if b.startswith(pre) and len(b) > len(pre):
            return b[len(pre):]
    return b


def top_coins(n, max_age_h=6):
    """CoinGecko piyasa değeri sıralamasında ilk n coinin kodları (6 saat önbellek).
    Alınamazsa önbellek; o da yoksa None (filtre uygulanmaz, tarama durmaz)."""
    cache = load_json(TOP_COINS_PATH, None)
    if cache and cache.get("n") == n and time.time() - cache.get("t", 0) < max_age_h * 3600:
        return set(cache["coins"])
    try:
        coins = []
        for page in range(1, (n - 1) // 250 + 2):
            req = urllib.request.Request(
                "https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=market_cap_desc"
                f"&per_page=250&page={page}", headers={"User-Agent": "Mozilla/5.0 (SorBot)", "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=20) as r:
                coins += [c["symbol"].upper() for c in json.loads(r.read().decode())]
        coins = coins[:n]
        os.makedirs(os.path.dirname(TOP_COINS_PATH), exist_ok=True)
        with open(TOP_COINS_PATH, "w") as fh:
            json.dump({"t": time.time(), "n": n, "coins": coins}, fh)
        return set(coins)
    except Exception as e:  # noqa: BLE001
        print(f"  [uyarı] CoinGecko sıralaması alınamadı: {e}")
        return set(cache["coins"]) if cache else None


def build_universe(api, cfg):
    info = api.get("/fapi/v1/exchangeInfo")
    ucfg = cfg["universe"]
    include, exclude = set(ucfg["include_types"]), set(ucfg["exclude_symbols"])
    tickers = {}
    for t in api.get("/fapi/v1/ticker/24hr"):
        tickers[t["symbol"]] = {"qv": float(t["quoteVolume"]), "chg": float(t["priceChangePercent"]),
                                "last": float(t.get("lastPrice") or 0)}
    funding = {}
    for p in api.get("/fapi/v1/premiumIndex"):
        try:
            funding[p["symbol"]] = float(p["lastFundingRate"])
        except (KeyError, ValueError, TypeError):
            pass

    all_meta, universe = {}, []
    min_qv = ucfg["min_quote_volume_24h"]
    # Kripto: yalnızca piyasa değeri sıralamasında ilk N'deki bilinen coinler (adı duyulmamış coinler elenir)
    top_n = ucfg.get("crypto_top_n")
    top = top_coins(top_n) if top_n else None
    # Kripto: Binance SPOT'ta da listelenmiş (Binance'in kabul ettiği) ve vadelide en az N gündür işlem gören coinler.
    # Sadece vadeliye eklenen yeni / meme coinler elenir.
    spot = None
    if ucfg.get("crypto_require_spot"):
        try:
            spot = {x["baseAsset"] for x in api.get("/api/v3/exchangeInfo")["symbols"]
                    if x.get("status") == "TRADING" and x.get("quoteAsset") == "USDT"}
        except Exception as e:  # noqa: BLE001
            print(f"  [uyarı] Binance spot listesi alınamadı, filtre atlandı: {e}")
    min_age = ucfg.get("crypto_min_age_days") or 0
    wl_syms = ucfg.get("tradingview_watchlist") if ucfg.get("watchlist_only") else None
    wset = set(wl_syms) if wl_syms else None
    now_ms = time.time() * 1000
    for s in info["symbols"]:
        if s.get("quoteAsset") != "USDT" or s.get("status") != "TRADING":
            continue
        if s.get("contractType") not in ("PERPETUAL", "TRADIFI_PERPETUAL"):
            continue
        typ = s.get("underlyingType")
        meta = {"symbol": s["symbol"], "type": typ, "precision": tick_decimals(s)}
        all_meta[s["symbol"]] = meta
        if wset is not None:                  # TradingView listesi modu: sadece listedekiler
            if s["symbol"] not in wset or s["symbol"] in exclude:
                continue
            qv = tickers.get(s["symbol"], {}).get("qv", 0)
            if typ == "EQUITY":
                need = min_qv.get("EQUITY", min_qv["default"])
                if us_market_status(datetime.now(timezone.utc)) != "open":
                    if not ucfg.get("scan_equity_when_closed", True):
                        continue
                    need = min_qv.get("EQUITY_closed", need)
                if qv < need:
                    continue
            elif typ == "COMMODITY" and qv < min_qv.get("COMMODITY", min_qv["default"]):
                continue
            universe.append(meta)                 # coinlerde hacim eşiği yok
            continue
        if typ not in include or s["symbol"] in exclude:
            continue
        wl = ucfg.get("equity_whitelist")
        if typ == "EQUITY" and wl and s["symbol"].removesuffix("USDT") not in wl:
            continue
        qv = tickers.get(s["symbol"], {}).get("qv", 0)
        need = min_qv.get(typ, min_qv["default"])
        if typ == "EQUITY" and us_market_status(datetime.now(timezone.utc)) != "open":
            # ABD borsası kapalıyken / hafta sonu hisse vadelilerinde mumlar boş ve dar → sahte sinyal.
            if not ucfg.get("scan_equity_when_closed", True):
                continue
            need = min_qv.get("EQUITY_closed", need)
        if qv < need:
            continue
        if typ == "COIN" and ucfg.get("crypto_exclude_non_ascii") and not s["symbol"].isascii():
            continue                                  # Çince vb. isimli coinler (龙虾, 牛来 …) taranmaz
        if typ == "COIN" and top is not None and coin_base(s["symbol"]) not in top:
            continue
        if typ == "COIN" and spot is not None and coin_base(s["symbol"]) not in spot \
                and s["symbol"].removesuffix("USDT") not in spot:
            continue
        if typ == "COIN" and min_age and (now_ms - s.get("onboardDate", now_ms)) / 86_400_000 < min_age:
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
        if cfg.get("symbols_only"):          # ör. 5dk ve 4s: sadece BTC ve ETH
            universe = [m for m in universe if m["symbol"] in cfg["symbols_only"]]
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

    # ETH yönü (kripto sinyallerinde BTC yönünün altında gösterilir)
    eth_bias = None
    if "ETHUSDT" in candles and len(candles["ETHUSDT"]) >= cfg["min_candles"]:
        eth_bias = trend_bias(compute_features(candles["ETHUSDT"], cfg))
    ctx = {"leaders": leaders, "funding": funding, "tickers": tickers, "now_utc": now_utc, "eth_bias": eth_bias,
           "btc_dom": btc_dominance(tickers.get("BTCUSDT", {}).get("chg")), "ndx": nasdaq_index()}
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

    # Önizleme: TrendFlex AL ve SAT örnekleri (kripto) + bir hisse; o anki verilerle, kayıt tutulmaz
    if os.environ.get("PREVIEW") == "1":
        def st_of(r):
            return r["f"]["tflex" if uses_trendflex(cfg) else "st_dir"][r["i"]]
        def best(pool, st):
            key = "long" if st == 1 else "short"
            pool = [r for r in pool if st_of(r) == st]
            return max(pool, key=lambda r: r[key]["score"]) if pool else None
        coins = [r for r in results if r["meta"]["type"] == "COIN"]
        eqs = [r for r in results if r["meta"]["type"] == "EQUITY"]
        coms = [r for r in results if r["meta"]["type"] == "COMMODITY"]
        metals = [r for r in coms if r["meta"]["symbol"] in PRECIOUS_METALS]
        others = [r for r in coms if r["meta"]["symbol"] not in PRECIOUS_METALS]
        only = os.environ.get("PREVIEW_TYPES", "").strip().upper()
        if only == "COMMODITY":
            picks_pv = [best(metals, 1) or best(metals, -1), best(others, 1) or best(others, -1)]
        else:
            picks_pv = [best(coins, 1), best(coins, -1), best(eqs, 1) or best(eqs, -1),
                        best(metals, 1) or best(metals, -1), best(others, 1) or best(others, -1)]
        psym = os.environ.get("PREVIEW_SYMBOL", "").strip().upper()
        if psym:                                  # tek sembol, istenen yönle (örnek göstermek için)
            picks_pv = [r for r in results if r["meta"]["symbol"] == psym]
        n = 0
        for r in picks_pv:
            if not r:
                continue
            d = "long" if st_of(r) == 1 else "short"
            if psym and os.environ.get("PREVIEW_DIR") in ("long", "short"):
                d = os.environ["PREVIEW_DIR"]
            fetch_tf_trends(api, r, now_ms, cfg["timeframe"], cfg.get("order_blocks", {}).get("enabled", True))
            compute_volume_profile(r, cfg)
            msg = "🧪 <b>TEST · ÖNİZLEME</b> (gerçek sinyal değil)\n\n" + build_message(r, d, cfg, now_utc)
            n += notifier.send(msg) and 1 or 0
        print(f"Önizleme: {n} örnek sinyal gönderildi.")
        return 0

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
    st_on = cfg.get("signal_supertrend", {}).get("enabled", True) or cfg.get("strategy") != "supertrend"
    for r in (results if st_on else []):     # Supertrend dönüş sinyalleri kapatılabilir (sadece SSL sinyali)
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
        fetch_tf_trends(api, r, now_ms, cfg["timeframe"], cfg.get("order_blocks", {}).get("enabled", True))
        compute_volume_profile(r, cfg)
        msg = build_message(r, d, cfg, now_utc)
        try:
            if notifier.send(msg, r["meta"]["symbol"], r["meta"]["type"]):
                sent += 1
                state["signals"][f"{r['meta']['symbol']}|{d}"] = now
                print(f"  → Gönderildi: {r['meta']['symbol']} {d.upper()} ({r['meta']['type']}, {cfg['timeframe']})")
        except Exception as e:  # noqa: BLE001
            print(f"  Telegram hatası: {e}", file=sys.stderr)

    rest = picks[maxn:]
    if rest:
        # özet liste de her sembolün kendi kanalına gider (Majör / Nasdaq / Emtia / Altcoin)
        groups = {}
        for score, d, r in rest[:40]:
            key = (r["meta"]["symbol"], r["meta"]["type"])
            chat = notifier.chat_for(*key)
            g = groups.setdefault(chat, {"key": key, "lines": ["📋 <b>Diğer sinyaller</b> (limit nedeniyle özet):"]})
            g["lines"].append(f"{'🟢' if d == 'long' else '🔴'} {r['meta']['symbol']} – {d.upper()} {score}")
            state["signals"][f"{r['meta']['symbol']}|{d}"] = now
        for g in groups.values():
            try:
                notifier.send("\n".join(g["lines"]), *g["key"])
            except Exception as e:  # noqa: BLE001
                print(f"  Telegram hatası: {e}", file=sys.stderr)

    # ---- Pivot sinyali (Supertrend'den ayrı): pivot üstünde/altında kapanış + Supertrend + DynaRange + QQE MOD ----
    pcfg = cfg.get("pivot_signal", {})
    piv_n = 0
    if pcfg.get("enabled", False):
        sent_st = {(r["meta"]["symbol"], d) for _, d, r in picks[:maxn]}
        for r in results:
            if piv_n >= pcfg.get("max_per_scan", 20):
                break
            f_, i_ = r["f"], r["i"]
            pv = pivot_from_bars(f_, i_, cfg["timeframe"])
            for d, s_ in (("long", 1), ("short", -1)):
                if (r["meta"]["symbol"], d) in sent_st:
                    continue                  # aynı mumda Supertrend sinyali gitti; Pivots bölümü onun içinde
                sig = pivot_signal(f_, i_, s_, pv)
                if not sig:
                    continue
                key = f"{r['meta']['symbol']}|pivot_{d}"
                if state["signals"].get(key + "_period") == pv["start"]:
                    continue                  # aynı pivot döneminde aynı yönde ikinci sinyal yok
                r["pivot_sig"] = sig
                fetch_tf_trends(api, r, now_ms, cfg["timeframe"], cfg.get("order_blocks", {}).get("enabled", True))
                r["pivot"] = pv               # sinyalle aynı seviyeler
                compute_volume_profile(r, cfg)
                msg = build_message(r, d, cfg, now_utc)
                try:
                    if notifier.send(msg, r["meta"]["symbol"], r["meta"]["type"]):
                        piv_n += 1
                        state["signals"][key] = now
                        state["signals"][key + "_period"] = pv["start"]
                        print(f"  → Pivot sinyali gönderildi: {r['meta']['symbol']} {d.upper()} ({cfg['timeframe']})")
                except Exception as e:  # noqa: BLE001
                    print(f"  Telegram hatası: {e}", file=sys.stderr)
                r.pop("pivot_sig", None)
                r.pop("_ichi", None)
    if piv_n:
        print(f"Pivot sinyali: {piv_n}")

    # ---- SSL Hybrid sinyali (Supertrend'den bağımsız): SSL Buy/Sell + QQE MOD + DynaRange ----
    scfg = cfg.get("ssl_signal", {})
    ssl_n = 0
    if scfg.get("enabled", False):
        picked_st = {(r["meta"]["symbol"], d) for _, d, r in picks[:maxn]}
        for r in results:
            if ssl_n >= scfg.get("max_per_scan", 20):
                break
            f_, i_ = r["f"], r["i"]
            for d, s_ in (("long", 1), ("short", -1)):
                if (r["meta"]["symbol"], d) in picked_st:
                    continue                  # aynı mumda Supertrend sinyali zaten gitti
                ev = ssl_signal(f_, i_, s_, scfg.get("wait_bars", 5))
                if ev is None:
                    continue
                key = f"{r['meta']['symbol']}|ssl_{d}"
                if state["signals"].get(key + "_ev") == f_["t"][ev]:
                    continue                  # aynı SSL Buy/Sell için ikinci sinyal yok
                r["ssl_sig"] = {"dir": d, "ev": ev}
                fetch_tf_trends(api, r, now_ms, cfg["timeframe"], cfg.get("order_blocks", {}).get("enabled", True))
                compute_volume_profile(r, cfg)
                msg = build_message(r, d, cfg, now_utc)
                try:
                    if notifier.send(msg, r["meta"]["symbol"], r["meta"]["type"]):
                        ssl_n += 1
                        state["signals"][key] = now
                        state["signals"][key + "_ev"] = f_["t"][ev]
                        print(f"  → SSL sinyali gönderildi: {r['meta']['symbol']} {d.upper()} ({cfg['timeframe']})")
                except Exception as e:  # noqa: BLE001
                    print(f"  Telegram hatası: {e}", file=sys.stderr)
                r.pop("ssl_sig", None)
                r.pop("_ichi", None)
    if ssl_n:
        print(f"SSL sinyali: {ssl_n}")

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
                fetch_tf_trends(api, r, now_ms, cfg["timeframe"], cfg.get("order_blocks", {}).get("enabled", True))
            if "vp" not in r:
                compute_volume_profile(r, cfg)
            try:
                if notifier.send(build_radar_message(r, rd, cfg, now_utc), r["meta"]["symbol"], r["meta"]["type"]):
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
