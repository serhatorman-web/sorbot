"""Yerel testler: python3 tests/test_scanner.py"""
import math
import os
import random
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import indicators as ta  # noqa: E402
import scanner  # noqa: E402
import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _no_sent_imgs():
    """main() grafik kanalı eşleştirmesini (SENT_IMGS) açar; testler birbirini etkilemesin."""
    scanner.SENT_IMGS, scanner.SENT_TXT = None, {}
    yield
    scanner.SENT_IMGS, scanner.SENT_TXT = None, {}


def approx(a, b, tol):
    assert abs(a - b) <= tol, f"{a} != {b} (±{tol})"


def test_rsi_known_values():
    # StockCharts'ın klasik Wilder RSI örneği
    closes = [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08, 45.89,
              46.03, 45.61, 46.28, 46.28, 46.00, 46.03, 46.41, 46.22, 45.64, 46.21]
    r = ta.rsi(closes, 14)
    for got, exp in zip(r[14:21], [70.53, 66.32, 66.55, 69.41, 66.36, 57.97, 62.93]):
        approx(got, exp, 0.15)  # StockCharts tablosu ara değerleri yuvarlıyor


def test_ema_sma():
    v = [float(i) for i in range(1, 31)]
    approx(ta.sma(v, 5)[-1], 28.0, 1e-9)
    approx(ta.ema(v, 10)[-1], 25.5, 1e-9)  # doğrusal seride EMA = son değer - (n-1)/2


def test_supertrend_and_adx_directions():
    up = [100 + i for i in range(100)]
    h, l = [x + 0.5 for x in up], [x - 0.5 for x in up]
    d, _ = ta.supertrend(h, l, up)
    assert d[-1] == 1
    a, pdi, ndi = ta.adx(h, l, up)
    assert pdi[-1] > ndi[-1] and a[-1] > 25
    down = list(reversed(up))
    d2, _ = ta.supertrend([x + 0.5 for x in down], [x - 0.5 for x in down], down)
    assert d2[-1] == -1


def make_candles(n, seed, drift=0.0, start=100.0, end_ms=None, pump_at_end=False):
    rnd = random.Random(seed)
    end_ms = end_ms or (int(time.time() * 1000) // 3_600_000) * 3_600_000
    t0 = end_ms - n * 3_600_000
    price, out = start, []
    for k in range(n):
        ret = drift + rnd.gauss(0, 0.008)
        vol = 1_000_000 * (1 + rnd.random())
        if pump_at_end and k >= n - 3:
            ret, vol = 0.03, vol * 6
        o = price
        c = price * (1 + ret)
        h, l = max(o, c) * (1 + abs(rnd.gauss(0, 0.003))), min(o, c) * (1 - abs(rnd.gauss(0, 0.003)))
        t = t0 + k * 3_600_000
        out.append([t, str(o), str(h), str(l), str(c), "0", t + 3_599_999, str(vol), 0, "0", "0", "0"])
        price = c
    # sonuna henüz kapanmamış mum ekle (atılmalı)
    out.append([end_ms, str(price), str(price), str(price), str(price), "0", end_ms + 3_599_999, "1", 0, "0", "0", "0"])
    return out


class FakeAPI:
    def __init__(self):
        self.requests = 0
        self.syms = {"BTCUSDT": ("COIN", 0.0012, 1), "ETHUSDT": ("COIN", 0.0015, 2),
                     "PUMPUSDT": ("COIN", 0.0004, 3), "DOWNUSDT": ("COIN", -0.0015, 4),
                     "NVDAUSDT": ("EQUITY", 0.001, 5), "QQQUSDT": ("EQUITY", 0.0008, 6),
                     "LOWVOLUSDT": ("COIN", 0.0, 7)}
        for i in range(40):
            self.syms[f"RND{i}USDT"] = ("COIN", random.Random(i).uniform(-0.002, 0.002), 100 + i)

    def get(self, path, params=None, retries=3):
        self.requests += 1
        if path == "/fapi/v1/exchangeInfo":
            return {"symbols": [{"symbol": s, "quoteAsset": "USDT", "status": "TRADING",
                                 "contractType": "PERPETUAL" if t == "COIN" else "TRADIFI_PERPETUAL",
                                 "underlyingType": t, "pricePrecision": 4} for s, (t, _, _) in self.syms.items()]}
        if path == "/fapi/v1/ticker/24hr":
            return [{"symbol": s, "quoteVolume": "1000" if s == "LOWVOLUSDT" else "90000000",
                     "priceChangePercent": "30" if s == "PUMPUSDT" else "1.5"} for s in self.syms]
        if path == "/fapi/v1/premiumIndex":
            return [{"symbol": s, "lastFundingRate": "0.0001"} for s in self.syms]
        if path == "/fapi/v1/klines":
            t, drift, seed = self.syms[params["symbol"]]
            return make_candles(498, seed, drift, pump_at_end=params["symbol"] == "PUMPUSDT")
        if path == "/futures/data/openInterestHist":
            return [{"sumOpenInterestValue": str(1e6 * (1 + 0.02 * k))} for k in range(5)]
        raise AssertionError(path)


def test_full_pipeline_dry_run():
    os.environ["DRY_RUN"] = "1"
    os.environ["SORBOT_SAVE_DRY_STATE"] = "1"
    scanner.STATE_PATH = os.path.join("/tmp", "sorbot_test_state", "state.json")
    if os.path.exists(scanner.STATE_PATH):
        os.remove(scanner.STATE_PATH)
    scanner.Binance = FakeAPI
    cfg = scanner.load_json(scanner.CONFIG_PATH, None)
    # Test için eşiği düşürerek mesaj üretimini de deneyelim
    cfg["signal"]["min_score"] = 55
    cfg["signal"]["min_score_gap"] = 10
    orig = scanner.load_json
    scanner.load_json = lambda p, d: cfg if p == scanner.CONFIG_PATH else orig(p, d)
    try:
        assert scanner.main() == 0
        state = orig(scanner.STATE_PATH, {})
        assert "signals" in state
        # İkinci çalıştırmada cooldown nedeniyle aynı sinyaller tekrar gelmemeli
        first = set(state["signals"])
        assert scanner.main() == 0
        assert set(orig(scanner.STATE_PATH, {})["signals"]) == first
    finally:
        scanner.load_json = orig


def test_backtest_simulation():
    import backtest

    def series(path):
        # her eleman (yüksek, düşük, kapanış); ilk mum giriş mumu
        f = {"h": [100], "l": [100], "c": [100]}
        for h, l, c in path:
            f["h"].append(h); f["l"].append(l); f["c"].append(c)
        return f
    # Long, risk=2: SL 98, TP 102/104/106
    r = backtest.simulate(series([(101, 99, 100.5), (103, 100, 102.5), (107, 102, 106)]), 0, 1, 2.0, 72)
    assert r["tp"] == [True, True, True] and abs(r["R"] - 2.0) < 1e-9
    r = backtest.simulate(series([(97, 97.5, 97.8)] + [(97, 96, 96.5)]), 0, 1, 2.0, 72)
    assert r["stopped_before_tp1"] and abs(r["R"] + 1.0) < 1e-9
    # TP1 sonrası girişe dönüş: 1/3 × 1R = +0.333R
    r = backtest.simulate(series([(102.5, 100.5, 102), (101, 99.5, 99.8), (99, 97, 97.5)]), 0, 1, 2.0, 72)
    assert r["tp"][0] and not r["tp"][1] and abs(r["R"] - 1 / 3) < 1e-9
    # Short, risk=2: SL 102, TP 98/96/94
    r = backtest.simulate(series([(100.5, 97.5, 98), (98.5, 93.5, 94)]), 0, -1, 2.0, 72)
    assert r["tp"] == [True, True, True] and abs(r["R"] - 2.0) < 1e-9
    # Aynı mumda stop ve TP: kötümser -> stop
    r = backtest.simulate(series([(103, 97, 100), (100, 99, 99.5)]), 0, 1, 2.0, 72)
    assert r["stopped_before_tp1"] and abs(r["R"] + 1.0) < 1e-9


def test_decoupling():
    cfg = scanner.load_json(scanner.CONFIG_PATH, None)
    n = 30
    f = {"c": [100.0] * 5 + [100 + i * 0.5 for i in range(n - 5)], "v": [1.0] * (n - 1) + [2.0],
         "vol_ma": [1.0] * n, "h4_ema": [1] * n, "h4_st": [0] * n}
    i = n - 1   # coin 24 saatte ~ +11.5%
    d = scanner.decoupling(f, i, 1, -0.03, cfg)          # BTC -3%
    assert d and d["rel"] > 0.1
    assert scanner.decoupling(f, i, 1, 0.09, cfg) is None   # BTC de yükselmiş: ayrışma yok
    f["v"][-1] = 1.0
    assert scanner.decoupling(f, i, 1, -0.03, cfg) is None  # hacim yok: ayrışma sayılmaz


def test_tf_trend_table():
    up = [{"c": 100 + k, "h": 100.5 + k, "l": 99.5 + k} for k in range(100)]
    down = [{"c": 200 - k, "h": 200.5 - k, "l": 199.5 - k} for k in range(100)]
    assert scanner.tf_trend(up) == 1
    assert scanner.tf_trend(down) == -1
    assert scanner.tf_trend(up[:30]) is None
    html = scanner.tf_table_html({"tf": {"15m": 1, "1h": -1, "4h": 0, "1d": None}})
    for word in ("15dk", "1 saat", "4 saat", "1 gün", "Yükseliş", "Düşüş", "Yatay", "Veri yok"):
        assert word in html
    assert "<blockquote>" not in html and "Düşüşte" in html and "Yükselişte" in html and "────" in html


def test_report_parsers_and_messages():
    import report
    from datetime import datetime, timezone

    farside = """<table class="etf"><tr><th></th><th>IBIT</th><th>FBTC</th><th>Total</th></tr>
      <tr><td>Fee</td><td>0.25%</td><td>0.25%</td><td></td></tr>
      <tr><td><span>09 Nov 2026</span></td><td>(213.2)</td><td>0.0</td><td>(213.2)</td></tr>
      <tr><td><span>10 Nov 2026</span></td><td>(78.2)</td><td>12.5</td><td>(65.7)</td></tr>
      <tr><td><span>11 Nov 2026</span></td><td>-</td><td>-</td><td>0.0</td></tr>
      <tr><td>Total</td><td>64,810</td><td>10,238</td><td>75,048</td></tr></table>"""
    rss = """<?xml version="1.0"?><rss><channel><item><title>Fed &amp; faiz</title>
      <link>https://ex.com/a</link><pubDate>Wed, 11 Nov 2026 16:00:00 GMT</pubDate></item></channel></rss>"""
    atom = """<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><entry><title>AI model</title>
      <link href="https://ex.com/b"/><published>2026-11-11T16:30:00Z</published></entry></feed>"""
    orig = report.get
    report.get = lambda url, timeout=20, as_json=True: (
        farside.encode() if "farside" in url else rss.encode() if url.endswith("rss") else atom.encode())
    try:
        e = report.etf_flows("btc")
        assert e["date"] == "10 Nov 2026" and abs(e["total"] + 65.7) < 1e-9 and e["top"][0][0] == "IBIT"
        assert abs(e["sum5"] + 278.9) < 1e-9
        a = report.parse_feed("X", "https://ex.com/rss")
        assert a[0]["title"] == "Fed & faiz" and a[0]["dt"].year == 2026
        b = report.parse_feed("Y", "https://ex.com/atom")
        assert b[0]["link"] == "https://ex.com/b"
    finally:
        report.get = orig

    now_tr = datetime(2026, 11, 11, 19, 5, tzinfo=report.TR_TZ)
    d = {"price": 74000, "chg24": -1.2, "funding": 0.0001, "next_funding": 1794412800000,
         "oi_usd": 7.3e9, "oi_btc": 100000, "oi_1h": 0.01, "oi_24h": -0.02,
         "ls_acc": (0.73, 0.27, 2.7), "ls_top": (0.68, 0.32, 2.2), "fut_buy": 5000, "fut_sell": 4000}
    spot = {"buy_usd": 3e7, "sell_usd": 2.5e7, "price_chg_1h": 0.3}
    ev = [{"dt": datetime(2026, 11, 11, 21, 0, tzinfo=report.TR_TZ), "title": "Fed Chair Speaks", "country": "USD",
           "impact": "High", "forecast": "", "previous": ""}]
    m = report.market_message(now_tr, d, spot, {"^GSPC": {"price": 6000.5, "chg": 0.4}},
                              {"BTC": e, "ETH": None}, ev, {})
    for word in ("Fonlama", "Açık pozisyon", "Long/Short", "Vadeli", "Spot", "S&amp;P 500", "ETF", "Fed Chair"):
        assert word in m, word
    assert "Fed Chair" in report.calendar_message(ev, now_tr.date(), {})
    assert "Pozitif" in m and "IBIT" not in m and "Spot ETF Giriş / Çıkış" in m and "🔴 Çıkış <b>65.7 mn $</b>" in m and "10 Kasım" in m
    d["funding"] = -0.0002
    assert "Negatif" in report.market_message(now_tr, d, spot, {}, {}, None, {})
    ai = lambda t: report.keep_item({"title": t, "link": "https://x.com/a"}, "ai")
    assert ai("OpenAI yeni modelini tanıttı") and ai("Yapay zeka çiplerinde yeni dönem") and ai("Nvidia rekor kırdı")
    assert not ai("Yeni elektrikli araba fiyatları") and not ai("Ailelere müjde")   # 'AI' kelime içi eşleşmesin
    assert not report.keep_item({"title": "x", "link": "https://tr.investing.com/news/transcripts/a"}, None)
    keep = lambda t: report.keep_item({"title": t, "link": "https://x.com/a"}, None)
    assert not keep("Bank of the James yöneticisi Lewis Addison 1.943 dolar hisse aldı")
    assert not keep("William Blair, AST Spacemobile hissesi için Market Perform görüşünü korudu")
    assert keep("Fed faiz kararını açıkladı") and keep("Altın ons başına 4.000 doları aştı")
    w = {"btc": [{"hash": "ab" * 32, "amount": 355.2, "usd": 26.4e6, "time": 1794418403, "height": 1}],
         "eth": [],
         "ob_BTC": {"Vadeli": {"mid": 74450, "bid_usd": 30e6, "ask_usd": 12e6, "bid_wall": (74400, 6e6),
                               "ask_wall": (74500, 3e6), "range": (74300, 74600)}}}
    wl = "\n".join(report.whale_lines(w, {}))
    assert "355 BTC" in wl and "büyük transfer yok" in wl and "alıcılar" in wl and "mempool.space/tx/" in wl
    st = {}
    big = {"date": "12 Nov 2026", "total": -411.9, "funds": [("IBIT", -403.0), ("FBTC", 42.8), ("GBTC", -11.1)],
           "sum5": -900.0, "n5": 5, "top": []}
    al = report.etf_alert_messages({"BTC": big, "ETH": None}, st, {})
    assert len(al) == 1 and "BÜYÜK BTC SPOT ETF ÇIKIŞI" in al[0][2] and "IBIT" in al[0][2] and "GBTC" not in al[0][2]
    st["etf_alert"] = {"BTC": {"date": "12 Nov 2026", "total": -411.9}}
    assert report.etf_alert_messages({"BTC": big}, st, {}) == []          # aynı gün tekrar uyarma
    small = dict(big, total=-60.0)
    assert report.etf_alert_messages({"BTC": dict(small, date="13 Nov 2026")}, {}, {}) == []   # eşik altı
    imp = report.importance
    assert imp("Fed faiz kararını açıkladı: politika faizi sabit") >= 5
    assert imp("ABD'de enflasyon beklentileri aştı") >= 3
    assert imp("SEC, yeni Bitcoin ETF başvurusunu onayladı") >= 3
    assert imp("Uluslararası Enerji Ekonomisi Birliği sempozyumu başladı") < 2
    assert imp("Yeni telefon modeli tanıtıldı") < 2
    sig = report.title_signature
    a = sig("Hissedarlar onayladı: Apollo, easyJet'i 5,7 milyar sterline satın alıyor")
    assert report.similar(a, sig("ABD'li Apollo, EasyJet'i 5,7 milyar sterline satın alacak"))
    assert report.similar(a, sig("EasyJet hissedarları, Apollo'nun 5,7 milyar sterlinlik satın alma teklifini onayladı"))
    assert not report.similar(a, sig("Von der Leyen, COP31'de temiz enerjiye geçişin hızlandırılması çağrısında bulundu"))


def test_15m_profile():
    cfg = scanner.load_json(scanner.CONFIG_PATH, None)
    c15 = scanner.apply_tf_profile(cfg, "15m")
    assert c15["timeframe"] == "15m" and c15["state_file"] == "state_15m.json"
    assert c15["pump_radar"]["enabled"] is False and c15["signal_supertrend"]["cooldown_hours"] == 0.25 and c15["signal_supertrend"]["min_score"] == 0
    assert c15["signal"]["min_score"] == cfg["signal"]["min_score"]          # diğer ayarlar korunur
    assert scanner.bars_per_day(c15) == 96 and scanner.tf_ms(c15) == 900_000
    # 15dk mumlardan üst zaman dilimi (1s) hesaplanır
    t0 = 1_790_000_000_000 // 3_600_000 * 3_600_000
    cs = [{"t": t0 + k * 900_000, "o": 100 + k, "h": 101 + k, "l": 99 + k, "c": 100.5 + k, "v": 1.0} for k in range(400)]
    f = scanner.compute_features(cs, c15)
    assert f["h4_ema"][-1] == 1 and f["h4_st"][-1] == 1
    # canlı akış 15dk profiliyle çalışır ve ayrı durum dosyası kullanır
    os.environ["SORBOT_TF"] = "15m"
    os.environ["DRY_RUN"] = "1"
    scanner.Binance = FakeAPI
    try:
        assert scanner.main() == 0
    finally:
        del os.environ["SORBOT_TF"]
        p15 = os.path.join(scanner.BASE_DIR, "state", "state_15m.json")
        if os.path.exists(p15):
            os.remove(p15)


def test_btc_eth_profiles():
    cfg = scanner.load_json(scanner.CONFIG_PATH, None)
    for tf, ms in (("5m", 300_000), ("4h", 14_400_000)):
        c = scanner.apply_tf_profile(cfg, tf)
        assert c.get("symbols_only") == (["BTCUSDT", "ETHUSDT"] if tf == "5m" else None) and scanner.tf_ms(c) == ms
        t0 = 1_790_000_000_000 // 86_400_000 * 86_400_000
        cs = [{"t": t0 + k * ms, "o": 100 + k, "h": 101 + k, "l": 99 + k, "c": 100.5 + k, "v": 1.0} for k in range(400)]
        f = scanner.compute_features(cs, c)
        assert f["h4_st"][-1] == 1
        os.environ["SORBOT_TF"] = tf
        os.environ["DRY_RUN"] = "1"
        scanner.Binance = FakeAPI
        try:
            assert scanner.main() == 0
        finally:
            del os.environ["SORBOT_TF"]
            pth = os.path.join(scanner.BASE_DIR, "state", c["state_file"])
            if os.path.exists(pth):
                os.remove(pth)
    b = scanner.banner_lines({"symbol": "BTCUSDT"}, {"timeframe": "5m"})
    assert b[0] == "🟧" * 10 and "BTC SİNYALİ" in b[1] and "5dk" in b[1]
    assert scanner.banner_lines({"symbol": "ETHUSDT"}, {"timeframe": "4h"})[0] == "🟦" * 10
    assert scanner.banner_lines({"symbol": "SOLUSDT"}, {"timeframe": "1h"})[0] == "🟪" * 10
    assert scanner.banner_lines({"symbol": "ARBUSDT"}, {"timeframe": "1h"}) == []


def test_rsi_divergence():
    c, p = [], 100.0
    for k in range(40): p -= 0.8; c.append(p)
    for k in range(15): p += 0.6; c.append(p)
    for k in range(25): p -= 0.45; c.append(p)
    for k in range(8): p += 0.5; c.append(p)
    hi, lo = [x + 0.2 for x in c], [x - 0.2 for x in c]
    assert ta.rsi_divergence(hi, lo, c) == (True, False)
    c2 = [300 - x for x in c]
    assert ta.rsi_divergence([x + 0.2 for x in c2], [x - 0.2 for x in c2], c2) == (False, True)
    assert scanner.divergence_lines({"div": {"pos": ["4 saat"], "neg": []}}) == ["〽️ <b>RSI UYUMSUZLUK</b>", "🟢 Pozitif uyumsuzluk: 4 saat → yükseliş başlayabilir, dönüş için onay bekle"]
    assert scanner.divergence_lines({"div": {"pos": [], "neg": []}}) == []


def test_volume_profile():
    h = [102] * 50 + [110] * 5 + [95.5] * 5
    l = [100] * 50 + [108] * 5 + [94] * 5
    v = [100] * 50 + [5] * 5 + [5] * 5
    vah, poc, val = ta.volume_profile(h, l, v)
    assert 100 <= poc <= 102 and 99.9 <= val <= 100.5 and 101.5 <= vah <= 102.1 and val <= poc < vah   # satır orta noktaları


def test_volume_lines():
    cfg = scanner.load_json(scanner.CONFIG_PATH, None)
    n = 30
    f = {"o": [100.0] * n, "c": [100.5] * n, "v": [1.0] * n, "vol_ma": [1.0] * n, "atr": [1.0] * n}
    f["c"][-1], f["v"][-1] = 103.0, 4.2
    out = scanner.volume_lines({"f": f, "i": n - 1}, cfg)
    assert out[0] == "🔊 <b>HACİM</b>" and out[1].startswith("🟢 Hacim yüksek") and any("Büyük yükseliş" in x for x in out) and any("patlaması" in x for x in out)
    f["c"][-1], f["v"][-1] = 100.2, 0.6
    out = scanner.volume_lines({"f": f, "i": n - 1}, cfg)
    assert out[1].startswith("🔴 Hacim düşük") and len(out) == 2


def test_technical_rating():
    v = lambda b, s_, z=0: [("x", 1)] * b + [("x", -1)] * s_ + [("x", 0)] * z
    r = lambda *a: scanner.technical_rating(v(*a))[0]
    assert r(17, 5) == "GÜÇLÜ AL" and r(22, 0) == "GÜÇLÜ AL"        # %77+
    assert r(16, 6) == "AL" and r(15, 7) == "AL"                    # %73 / %68
    assert r(14, 8) == "NÖTR" and r(11, 11) == "NÖTR" and r(8, 14) == "NÖTR"
    assert r(7, 15) == "SAT" and r(6, 16) == "SAT"
    assert r(5, 17) == "GÜÇLÜ SAT"
    assert r(14, 2, 6) == "NÖTR"                                    # AL %64 → nötr
    assert r(13, 10, 1) == "NÖTR"                                   # AL %54 / SAT %42 → nötr
    assert r(13, 7) == "AL" and r(12, 8) == "NÖTR"                  # 20 oyda %65 / %60


def test_trend_alignment():
    t = lambda a, b, c, d: {"tf": {"15m": a, "1h": b, "4h": c, "1d": d}}
    al = scanner.trend_alignment_line
    assert al(t(-1, -1, -1, -1), "long") == "🔴 <b>Uyarı: Bu işlem trend tablosu ile uyumsuz</b>"
    assert al(t(1, 1, 1, 1), "long") == "✅ <b>Bu işlem trend tablosu ile uyumlu</b>"
    assert al(t(-1, -1, -1, -1), "short") == "✅ <b>Bu işlem trend tablosu ile uyumlu</b>"
    assert al(t(1, 1, 1, 1), "short") == "🔴 <b>Uyarı: Bu işlem trend tablosu ile uyumsuz</b>"
    assert al(t(1, -1, -1, -1), "long") is None
    assert al(t(-1, -1, -1, None), "long") is not None
    assert al({}, "long") is None


def test_own_tf_alignment():
    o = scanner.own_tf_alignment_line
    c15 = {"timeframe": "15m"}
    assert o({"tf": {"15m": 0}}, "long", c15) == "⚪ İşlem kendi zaman diliminde (15dk) yatay"
    assert o({"tf": {"15m": 1}}, "long", c15) == "✅ İşlem kendi zaman dilimiyle (15dk) uyumlu"
    assert o({"tf": {"15m": -1}}, "short", c15) == "✅ İşlem kendi zaman dilimiyle (15dk) uyumlu"
    assert o({"tf": {"15m": -1}}, "long", c15).startswith("🔴 <b>Uyarı")
    assert o({"tf": {"15m": 1}}, "short", c15).startswith("🔴 <b>Uyarı")
    assert o({}, "long", {"timeframe": "1h"}) is None
    up = o({"tf": {"15m": 1, "1h": -1, "4h": -1, "1d": 1}}, "long", c15)
    assert up == ("🔴 <b>Uyarı: İşlem kendi zaman dilimiyle (15dk) uyumlu ama üst zaman dilimleriyle "
                  "(1 saat, 4 saat) uyumsuz</b>")
    assert o({"tf": {"15m": 1, "1h": 1, "4h": 0, "1d": 1}}, "long", c15).startswith("✅ İşlem kendi")
    assert "1 gün" in o({"tf": {"1h": -1, "4h": -1, "1d": 1}}, "short", {"timeframe": "1h"})


def test_econ_bulletin():
    import econ
    import report
    from datetime import datetime, timezone, timedelta
    assert econ.tr_title("Non Farm Payrolls") == "Tarım Dışı İstihdam"
    assert econ.tr_title("Fed Bowman Speech") == "Fed Üyesi Bowman Konuşması"
    assert "(Aylık)" in econ.tr_title("Wholesale Prices MoM") and "Toptan" in econ.tr_title("Wholesale Prices MoM")
    e = {"title": "Initial Jobless Claims", "actual": 200, "forecast": 195, "unit": "", "scale": "K"}
    assert econ.verdict(e)[0] == "🔴" and econ.fmt_val(e, "actual") == "200K"
    e = {"title": "Retail Sales MoM", "actual": 0.6, "forecast": 0.3, "unit": "%", "scale": ""}
    assert econ.verdict(e)[0] == "🟢"
    e = {"title": "EIA Crude Oil Stocks Change", "actual": 3.0, "forecast": -1.0, "unit": "", "scale": "M"}
    assert econ.verdict(e)[0] == "⚪"
    assert report.tr_upper("Ekonomi & Finans") == "EKONOMİ & FİNANS" and report.tr_upper("Kripto") == "KRİPTO"
    now = datetime(2026, 11, 12, 15, 0, tzinfo=report.TR_TZ)
    rel = [{"dt": now - timedelta(minutes=30), "tr": "İlk İşsizlik Başvuruları", "title": "Initial Jobless Claims",
            "country": "US", "importance": 0, "actual": 200, "forecast": 195, "previous": 191, "unit": "", "scale": "K"}]
    m = report.bulletin_message(now, rel, [], {"💵 Ekonomi & Finans": []}, {})
    assert "SAATLİK PİYASA BÜLTENİ" in m and "Gerçekleşen: <b>200K</b>" in m and "ekonomi için olumsuz" in m
    assert "🇺🇸 ABD · 14:30" in m
    assert report.bulletin_message(now, [], [], {"💵 Ekonomi & Finans": []}, {}) is None


def test_markets_block():
    import report
    assert report.tr_num(52680.84) == "52.680,84"
    out = "\n".join(report.markets_block({"^DJI": {"price": 52680.84, "chg": 0.13, "open": True},
                                           "XU100.IS": {"price": 11811.19, "chg": -0.5, "open": False}}))
    assert "🟢 Dow Jones: <b>52.680,84</b> · 🟢▲ %0,13 · <i>Açık</i>" in out
    assert "🔴 BIST 100" in out and "🔴▼ %0,50" in out and "Kapalı" in out


def test_asset_impact():
    import econ
    us = lambda t, a, f: {"country": "US", "title": t, "actual": a, "forecast": f}
    i = econ.asset_impact(us("Inflation Rate YoY", 3.4, 3.1))
    assert i["hawkish"] and i["items"][0] == ("🔴", "Kripto için olumsuz")
    assert not econ.asset_impact(us("Non Farm Payrolls", 95, 150))["hawkish"]
    assert not econ.asset_impact(us("Initial Jobless Claims", 200, 195))["hawkish"]
    assert econ.asset_impact(us("Initial Jobless Claims", 180, 195))["hawkish"]
    assert econ.asset_impact(us("Fed Interest Rate Decision", 4.5, 4.25))["hawkish"]
    assert econ.asset_impact(us("EIA Crude Oil Stocks Change", 3, -1)) is None
    assert i["items"][3] == ("🟢", "Dolar için olumlu")              # ABD enflasyonu yüksek → dolar güçlenir
    tr = econ.asset_impact(dict(us("Inflation Rate YoY", 3.4, 3.1), country="TR"))
    assert tr["items"] == [("🔴", "Faiz indirimi (TCMB) için olumsuz"), ("🔴", "TL için olumsuz")]
    tr = econ.asset_impact(dict(us("Interest Rate Decision", 40, 38), country="TR"))
    assert tr["items"][1] == ("🟢", "TL için olumlu")                 # faiz beklentiden yüksek → TL olumlu
    eu = econ.asset_impact(dict(us("Inflation Rate YoY", 2.6, 2.2), country="EU"))
    assert ("🟢", "Euro için olumlu") in eu["items"] and ("🔴", "Dolar için olumsuz") in eu["items"]
    cn = econ.asset_impact(dict(us("GDP Growth Rate YoY", 5.4, 5.0), country="CN"))
    assert cn["items"][0] == ("🟢", "Kripto için olumlu")
    assert econ.asset_impact(dict(us("Inflation Rate YoY", 1, 0.5), country="CN")) is None
    sv = econ.asset_impact({"country": "TR", "title": "CBRT Survey Year-End CPI Expectation",
                            "actual": 30.04, "forecast": None, "previous": 29.63})
    assert sv["items"] == [("🔴", "Faiz indirimi (TCMB) için olumsuz"), ("🔴", "TL için olumsuz")]
    ca = econ.asset_impact({"country": "TR", "title": "Current Account", "actual": 2.72, "forecast": 2.4})
    assert ca["items"] == [("🟢", "TL için olumlu")]
    import report
    msg = report.release_alert_message([dict(us("Inflation Rate YoY", 3.4, 3.1), id="x", tr="TÜFE (Yıllık)",
        importance=1, previous=3.0, unit="%", scale="", dt=__import__("datetime").datetime(2026, 11, 13, 13, 30,
        tzinfo=__import__("datetime").timezone.utc))])
    assert "VERİ AÇIKLANDI" in msg and "Dolar için olumlu" in msg and "16:30" in msg
    assert econ.asset_impact(us("Retail Sales MoM", 0.3, 0.3)) is None


def test_market_status():
    from datetime import datetime, timezone
    assert scanner.us_market_status(datetime(2026, 11, 14, 15, 0, tzinfo=timezone.utc)) == "weekend"
    assert scanner.us_market_status(datetime(2026, 11, 11, 15, 0, tzinfo=timezone.utc)) == "open"
    assert scanner.us_market_status(datetime(2026, 11, 11, 23, 0, tzinfo=timezone.utc)) == "closed"



def test_dynarange():
    up = [float(x) for x in range(100, 200)]
    d = ta.dynarange(up, [x + 1 for x in up], [x - 1 for x in up], up)
    assert d[-1] > 0 and d[0] is None      # yükselişte 0 üstü
    dn = list(reversed(up))
    d = ta.dynarange(dn, [x + 1 for x in dn], [x - 1 for x in dn], dn)
    assert d[-1] < 0                       # düşüşte 0 altı


def test_trendflex():
    up = [100 + x * 0.5 for x in range(200)]
    t, _ = ta.trendflex([x + 1 for x in up], [x - 1 for x in up], up)
    assert t[-1] == 1 and t[5] is None     # yükselişte yeşil
    dn = list(reversed(up))
    t, _ = ta.trendflex([x + 1 for x in dn], [x - 1 for x in dn], dn)
    assert t[-1] == -1                     # düşüşte kırmızı
    # _BUY etiketi: düşüşten sonra sert yükseliş
    c = dn[:150] + [dn[149] + x * 3 for x in range(1, 40)]
    col, line = ta.trendflex([x + 1 for x in c], [x - 1 for x in c], c)
    sma = ta.sma(c, 13)
    sig = [ta.trendflex_signal(c, line, sma, i) for i in range(len(c))]
    assert 1 in sig and sig.count(1) == 1


def test_trendline_break():
    import math
    # yükselen kanal (dalgalı), sonra sert düşüş → yükselen çizgi kırıldı, retest yok
    c = [100 + k * 0.5 + 3 * math.sin(k / 3) for k in range(120)] + [150 - k * 2 for k in range(1, 9)]
    h = [x + 1 for x in c]; l = [x - 1 for x in c]
    ev = ta.trendline_break(h, l, c)
    assert any(e["type"] == "rising" and e["retest"] == "away" for e in ev), ev      # sert düşüş, retest yok → uzaklaştı
    c = [100 + k * 0.5 + 3 * math.sin(k / 3) for k in range(120)] + [158.0, 156.5]
    h = [x + 1 for x in c]; l = [x - 1 for x in c]
    ev = ta.trendline_break(h, l, c)
    assert any(e["type"] == "rising" and e["retest"] == "none" for e in ev), ev      # çizginin hemen altı → bekle
    # sahte kırılım: kır, dokun, çizginin üstüne geri kapan, tekrar kır → en son kırılım esas alınır
    Lf = lambda k: 100 + 0.5 * (k - 10)
    c = [Lf(k) + 1.5 + 0.4 * min(abs(k - 10) if k < 20 else abs(k - 30), 10) for k in range(50)]
    c += [Lf(50) - 1.3, Lf(51) - 1.2, Lf(52) + 1, Lf(53) + 1.5, Lf(54) - 1.8, Lf(55) - 2.0]
    h = [x + 0.6 for x in c]; l = [x - 0.6 for x in c]
    l[10] = 99.0; l[30] = 109.0; l[55] = 117.5
    ev = ta.trendline_break(h, l, c)
    assert ev and ev[0]["type"] == "rising" and ev[0]["bars_ago"] == 1, ev
    # düşen kanal, yukarı kırılım, geri çekilip çizgiye dokunma (retest), tekrar yukarı
    c = [200 - k * 0.5 + 3 * math.sin(k / 3) for k in range(120)]
    c += [c[-1] + 6, c[-1] + 9, c[-1] + 4, c[-1] + 3.5, c[-1] + 8, c[-1] + 11]
    h = [x + 1 for x in c]; l = [x - 1 for x in c]
    ev = ta.trendline_break(h, l, c)
    assert any(e["type"] == "falling" for e in ev), ev
    lines = scanner.trendline_lines({"meta": {"precision": 2}, "tline": [
        {"type": "falling", "state": "active", "touches": 3, "level": 101.0, "price": 100.0, "bars_ago": 0, "retest": None, "tf": "15m"},
        {"type": "rising", "state": "active", "touches": 2, "level": 90.0, "price": 100.0, "bars_ago": 0, "retest": None, "tf": "15m"},
        {"type": "falling", "state": "broken", "touches": 2, "level": 98.0, "price": 100.0, "bars_ago": 3, "retest": "confirmed", "tf": "4h"}]})
    assert lines == ["📐 <b>TREND ÇİZGİSİ</b>",
                     "🟢 4 saat: Düşen trend çizgisi kırıldı · ✅ Retest yapıldı → yükseliş başlayabilir"], lines


def test_trendlines_close():
    import math
    c = [100 - k * 0.1 + 4 * math.sin(k / 8) for k in range(220)]
    h = [x + 0.5 for x in c]; l = [x - 0.5 for x in c]
    ev = ta.trendlines_close(h, l, c)
    f = [e for e in ev if e["type"] == "falling"]
    assert f and f[0]["state"] == "active" and f[0]["touches"] >= 2
    A, B = f[0]["a"], f[0]["b"]
    slope = (c[B] - c[A]) / (B - A)
    a14 = ta.atr(h, l, c, 14)
    assert all(c[k] <= c[B] + slope * (k - B) + 0.1 * a14[k] + 1e-9 for k in range(A, len(c)))   # kapanışlar çizginin altında
    c2 = c + [c[-1] + k * 0.9 for k in range(1, 8)]
    ev2 = ta.trendlines_close([x + 0.5 for x in c2], [x - 0.5 for x in c2], c2)
    assert any(e["type"] == "falling" and e["state"] == "broken" for e in ev2), ev2


def test_volume_profile_retest():
    def mk(c, o=None):
        o = o or ([c[0]] + c[:-1])
        h = [max(a, b) + 0.4 for a, b in zip(c, o)]; l = [min(a, b) - 0.4 for a, b in zip(c, o)]
        return h, l, c, o
    base = [100.0 + (k % 3) * 0.3 for k in range(40)]
    # tepki: alttan 110'a iğneyle dokunuş, sonra dokunan mumun dibinin altında kapanış → direnç tuttu, düşüş
    h, l, c, o = mk(base + [104, 106, 108, 109.4, 108.2, 107.5])
    h[-3] = 110.2
    ev = ta.level_retest(h, l, c, 110.0, open_=o, near_atr=10)
    assert ev and ev["kind"] == "hold" and ev["dir"] == "down" and ev["state"] == "confirmed", ev
    # kırılım: 105'i aşağı kırdı, geri gelmedi → retest yok
    h, l, c, o = mk(base + [108, 107, 104, 103, 102.5])
    ev = ta.level_retest(h, l, c, 105.0, open_=o, break_near_atr=10)
    assert ev["kind"] == "break" and ev["dir"] == "down" and ev["state"] == "none", ev
    # kırılım + geri gelip dokundu (altında kapandı) → retest yapılıyor
    h, l, c, o = mk(base + [108, 107, 104, 103, 104.6])
    h[-1] = 105.1
    ev = ta.level_retest(h, l, c, 105.0, open_=o, break_near_atr=10)
    assert ev["state"] == "touch", ev
    # + sonra dokunan mumun dibinin altında kapanış → retest yapıldı
    h, l, c, o = mk(base + [108, 107, 104, 103, 104.6, 102.0])
    h[-2] = 105.1
    ev = ta.level_retest(h, l, c, 105.0, open_=o, break_near_atr=10)
    assert ev["state"] == "confirmed", ev
    # retest yapıldıktan sonra fiyat çok uzaklaştı → yazılmaz
    assert ta.level_retest(h, l, c, 105.0, open_=o, break_near_atr=0.1) is None
    # retest gelmeden fiyat çok uzaklaştı → away
    h, l, c, o = mk(base + [108, 107, 104, 101, 97, 93])
    ev = ta.level_retest(h, l, c, 105.0, open_=o, break_near_atr=1.0)
    assert ev["kind"] == "break" and ev["dir"] == "down" and ev["state"] == "away", ev
    # fiyat seviyeden uzak → yok
    assert ta.level_retest(h, l, c, 150.0, open_=o) is None
    mk_res = lambda evs, p=None: {"meta": {"precision": 4}, "vp_ev": evs,
                                  **({"f": {"c": [p]}, "i": 0} if p else {})}
    L = lambda evs, p=None: scanner.volume_profile_lines(mk_res(evs, p), {"timeframe": "15m"})
    assert L({"POC": {"kind": "break", "dir": "down", "state": "none", "level": 2.2481}})[1] == \
        "⏳ POC - fiyat 2.2481 seviyesini aşağı kırdı. Retest yapılmadı, bekle."
    assert L({"POC": {"kind": "break", "dir": "down", "state": "touch", "level": 2.2481}})[1] == \
        "🔄 POC - fiyat 2.2481 seviyesini aşağı kırdı. Kırılım sonrası retest yapılıyor, düşüş teyidi bekleniyor."
    assert L({"VAH": {"kind": "break", "dir": "up", "state": "confirmed", "level": 71350.0}})[1] == \
        "✅ VAH - fiyat 71,350.0000 seviyesini yukarı kırdı. Kırılım sonrası retest yapıldı, yükselişin devamı bekleniyor."
    assert L({"VAL": {"kind": "break", "dir": "down", "state": "away", "level": 1.5259}})[1] == \
        "⬇️ VAL - fiyat 1.5259 seviyesini aşağı kırdı. Retest yapılmadan düşüş devam etti, fiyat seviyeden uzaklaştı (geç giriş riski)."
    assert L({"VAH": {"kind": "break", "dir": "up", "state": "away", "level": 1.5998}})[1] == \
        "⬆️ VAH - fiyat 1.5998 seviyesini yukarı kırdı. Retest yapılmadan yükseliş devam etti, fiyat seviyeden uzaklaştı (geç giriş riski)."
    assert L({"VAL": {"kind": "hold", "dir": "up", "state": "confirmed", "level": 0.9794}})[1] == \
        "🟢 VAL - fiyat 0.9794 seviyesine ulaştı. Retest yapıldı, yükseliş bekleniyor."
    assert L({"VAL": {"kind": "hold", "dir": "up", "state": "touch", "level": 0.9794}})[1].startswith("⚪ VAL")
    two = L({"VAH": {"kind": "hold", "dir": "down", "state": "touch", "level": 110.0},
             "VAL": {"kind": "hold", "dir": "up", "state": "touch", "level": 90.0}}, 91.0)
    assert len(two) == 2 and "VAL" in two[1]
    assert scanner.volume_profile_lines({"meta": {}}, {}) == []

def test_ichimoku_band_retest():
    line = [100.0] * 60
    c = [95 + (k % 3) * 0.3 for k in range(50)] + [101, 103, 100.6, 104, 106, 107, 108, 109, 110, 111]
    h = [x + 0.8 for x in c]; l = [x - 0.8 for x in c]
    assert ta.band_retest(h, l, c, line, line)["state"] == "confirmed"          # kır, dokun, devam
    assert ta.band_retest(h[:53], l[:53], c[:53], line[:53], line[:53])["state"] == "touch"
    assert ta.band_retest(h[:51], l[:51], c[:51], line[:51], line[:51])["state"] == "none"
    c4 = [105 + (k % 3) * 0.3 for k in range(55)] + [101.0, 103, 106]
    h4 = [x + 0.8 for x in c4]; l4 = [x - 0.8 for x in c4]; ln = [100.0] * len(c4)
    ev = ta.band_retest(h4, l4, c4, ln, ln)
    assert ev["kind"] == "hold" and ev["dir"] == "up" and ev["state"] == "confirmed", ev   # destekten döndü
    assert ta.band_retest(h4, l4, c4, [110.0] * len(c4), [100.0] * len(c4))["kind"] == "inside"
    # mesaj bölümü
    n = 120
    c = [100 + k * 0.3 for k in range(n)]
    f = {"h": [x + 0.5 for x in c], "l": [x - 0.5 for x in c], "c": c,
         "ichi_tenkan": [x - 1 for x in c], "ichi_kijun": [x - 3 for x in c],
         "ichi_top": [x - 6 for x in c], "ichi_bot": [x - 8 for x in c]}
    res = {"f": f, "i": n - 1, "meta": {"precision": 2}}
    cfg = {"timeframe": "1h", "indicators": {"ichimoku": [9, 26, 52, 26]}}
    out = scanner.ichimoku_lines(res, "long", cfg)
    assert out[0] == "☁️ <b>ICHIMOKU</b> · 1 saat", out
    assert out[1].startswith("🟢 Bulut (yeşil) ") and "fiyat üstünde (destek)" in out[1], out
    assert out[4].startswith("🟢 İleri bulut (26 mum sonrası): yeşil · ") and out[4].endswith("→ yükseliş trendi bekleniyor"), out
    assert out[5] == "🟢 Tenkan Kijun'un üstünde → kısa vadede yükseliş eğilimi", out
    assert out[6] == "✅ Ichimoku sinyalle uyumlu (4/4)", out
    assert scanner.ichimoku_lines(res, "short", cfg)[6] == "⚠️ Ichimoku sinyalle uyumsuz (0/4)"
    # ileri bulut incelmiş → renk dönüşü uyarısı
    f2 = dict(f, atr=[100.0] * n)
    out2 = scanner.ichimoku_lines(dict(res, f=f2), "long", cfg)
    assert out2[4].endswith(" · ⚠️ bulut incelmiş, renk dönüşü yakın"), out2
    assert scanner.ichimoku_lines(res, "long", dict(cfg, ichimoku_info={"enabled": False})) == []


def test_retest_requires_detach():
    """Fiyat çizgiden/seviyeden önce (kapanışla) 0.5 ATR uzaklaşmadan gelen dokunuş retest sayılmaz."""
    # band (Kijun / Tenkan): yukarı kırılım, fiyat çizginin hemen üstünde sürünüyor → retest yok
    c = [95 + (k % 3) * 0.3 for k in range(50)] + [100.2, 100.3, 100.25, 100.2]
    h = [x + 0.8 for x in c]; l = [x - 0.8 for x in c]; ln = [100.0] * len(c)
    assert ta.band_retest(h, l, c, ln, ln)["state"] == "none"
    # aynı, ama önce uzaklaşıp geri geliyor → retest
    c = [95 + (k % 3) * 0.3 for k in range(50)] + [100.2, 102.5, 100.4]
    h = [x + 0.8 for x in c]; l = [x - 0.8 for x in c]; ln = [100.0] * len(c)
    assert ta.band_retest(h, l, c, ln, ln)["state"] == "touch"
    # hacim profili seviyesi: aşağı kırılım, seviyenin hemen altında sürünme → retest yok
    o = [110.0] * 40 + [100.4, 99.8, 99.75]
    c = [110.0] * 40 + [99.8, 99.75, 99.8]
    h = [max(a, b) + 0.6 for a, b in zip(o, c)]; l = [min(a, b) - 0.6 for a, b in zip(o, c)]
    ev = ta.level_retest(h, l, c, 100.0, open_=o, break_near_atr=10)
    assert ev["kind"] == "break" and ev["state"] == "none", ev
    # trend çizgisi: kırılım sonrası çizginin hemen altında sürünme → retest yok
    Lf = lambda k: 100 + 0.5 * (k - 10)
    c = [Lf(k) + 1.5 + 0.4 * min(abs(k - 10) if k < 20 else abs(k - 30), 10) for k in range(50)]
    c += [Lf(50) - 1.2, Lf(51) - 1.15, Lf(52) - 1.2]
    h = [x + 0.6 for x in c]; l = [x - 0.6 for x in c]
    l[10] = 99.0; l[30] = 109.0
    ev = ta.trendline_break(h, l, c)
    assert ev and ev[0]["type"] == "rising" and ev[0]["retest"] == "none", ev


def test_swing_anchor():
    # düşüş: en yüksek tepe 5. mumda, en düşük dip son mumda → pencere 5. mumdan başlar
    h = [10, 11, 12, 13, 14, 20, 15, 13, 12, 11]
    l = [9, 10, 11, 12, 13, 18, 14, 12, 11, 8]
    assert ta.swing_anchor(h, l, 300) == 5
    # yükseliş: en düşük dip daha eski → oradan başlar
    h = [10, 9, 12, 14, 16, 18, 21]
    l = [8, 5, 10, 12, 14, 16, 19]
    assert ta.swing_anchor(h, l, 300) == 1
    # arama sadece son `lookback` mumda
    assert ta.swing_anchor([50] + h, [1] + l, 7) == 2


def test_flux_order_blocks():
    # yükseliş: swing tepe (k=12) sonra düşüş, dip mum (k=20), sonra tepe kapanışla geçilir → boğa OB = dip mumu
    h = [100 + k for k in range(13)] + [111, 109, 107, 105, 103, 101, 100, 99.5, 101, 104, 108, 112.5, 113, 114, 115]
    n = len(h)
    l = [x - 1 for x in h]; c = [x - 0.5 for x in h]
    l[20] = 97.0
    v = [100.0] * n; v[24] = 300.0; v[23] = 200.0; v[22] = 50.0
    obs = ta.flux_order_blocks(h, l, c, v)
    bull = [x for x in obs if x["type"] == 1]
    assert bull and bull[0]["bottom"] == 97.0 and bull[0]["top"] == 99.5 and not bull[0]["breaker"], obs
    ob = bull[0]
    assert ob["vol"] == v[ob["i"]] + v[ob["i"] - 1] + v[ob["i"] - 2] if "i" in ob else True
    assert 0 <= ob["pct"] <= 100
    l2 = list(l) + [96.0]; h2 = list(h) + [110.0]; c2 = list(c) + [100.0]; v2 = list(v) + [100.0]
    obs2 = ta.flux_order_blocks(h2, l2, c2, v2)
    assert [x for x in obs2 if x["type"] == 1][0]["breaker"] is True          # iğne bölgenin altına indi → bozuldu


def test_fmt_volume():
    assert ta.fmt_volume(14155.125) == "14.155K" and ta.fmt_volume(6262.718) == "6.263K"
    assert ta.fmt_volume(1355126.586) == "1.355M" and ta.fmt_volume(950) == "950"


def test_order_block_lines():
    n = 30
    f = {"o": [100.0] * n, "h": [100.5] * n, "l": [99.5] * n, "c": [100.0] * n, "atr": [1.0] * n}
    obs = [{"type": 1, "top": 98.0, "bottom": 97.0, "vol": 14155.125, "pct": 9, "breaker": False},
           {"type": -1, "top": 105.0, "bottom": 104.0, "vol": 6262.718, "pct": 7, "breaker": False},
           {"type": -1, "top": 110.0, "bottom": 109.0, "vol": 1.0, "pct": 1, "breaker": True}]
    out = scanner.order_block_lines({"f": f, "i": n - 1, "meta": {"precision": 2}, "obs": obs}, {"timeframe": "15m"})
    assert out[0] == "🧱 <b>ORDER BLOCK</b> · 15dk", out
    assert out[1] == "🔴 Ayı OB 104.00 – 105.00 · 6.263K (%7) · fiyatın %4.0 üstünde (direnç) → yükselişte ilk direnç, buradan satış beklenir → Sonuç: bu bölgeden düşüş gelebilir", out
    assert out[2] == "🟢 Boğa OB 97.00 – 98.00 · 14.155K (%9) · fiyatın %2.0 altında (destek) → düşüşte ilk destek, buradan tepki beklenir → Sonuç: bu bölgeden yükseliş gelebilir", out
    assert len(out) == 3, out                                       # bozulmuş bölge yazılmaz


def test_signal_price_action():
    n = 40
    o = [100.0] * n; c = [100.0] * n; h = [100.5] * n; l = [99.5] * n
    h[30] = 102.0                                        # pivot tepe
    o[38], c[38], h[38], l[38] = 101.0, 100.0, 101.1, 99.9   # kırmızı
    o[39], c[39], h[39], l[39] = 99.9, 102.6, 102.7, 99.8    # yutan, güçlü kapanış, tepeyi kırdı
    f = {"o": o, "h": h, "l": l, "c": c, "atr": [1.0] * n}
    pa = scanner.signal_price_action(f, n - 1, 1)
    assert pa["pa_engulf"] and pa["pa_strong_close"] and pa["pa_bos"], pa
    out = scanner.price_action_lines({"f": f, "i": n - 1, "meta": {"precision": 2}}, "long", {"timeframe": "1h"})
    assert out[0] == "🕯️ <b>PRICE ACTION</b> · 1 saat" and any(x.startswith("✅ Yapı kırılımı (BOS): son tepe 100.50") or x.startswith("✅ Karakter değişimi (CHoCH)") for x in out), out


def test_choch_label():
    n = 40
    o = [100.0] * n; c = [100.0] * n; h = [100.5] * n; l = [99.5] * n
    h[25] = 104.0; h[33] = 102.0                          # alçalan tepeler (LH)
    o[39], c[39], h[39], l[39] = 100.0, 102.6, 102.7, 99.9  # son alçalan tepe kırıldı → CHoCH
    f = {"o": o, "h": h, "l": l, "c": c, "atr": [1.0] * n}
    out = scanner.price_action_lines({"f": f, "i": n - 1, "meta": {"precision": 2}}, "long", {"timeframe": "1h"})
    assert any(x.startswith("✅ Karakter değişimi (CHoCH): son alçalan tepe (LH)") and "→ trend yukarı döndü, yükseliş teyit edildi" in x
               for x in out), out


def test_qqe_ssl_basic():
    n = 300
    rnd = random.Random(3)
    c = [100.0]
    for k in range(1, n):
        c.append(c[-1] + (0.6 if k < 150 else -0.6) + rnd.uniform(-0.8, 0.8))
    q = ta.qqe_mod(c)
    h = [x + 0.3 for x in c]; l = [x - 0.3 for x in c]
    assert 1 in q[60:150] and -1 in q[200:], (q[60:150], q[200:])
    ssl = ta.ssl_exit(h, l, c, 15)
    assert sum(ssl[k] < c[k] for k in range(100, 150)) > 30 and sum(ssl[k] > c[k] for k in range(250, 300)) > 20


def test_ssl_signal():
    n = 30
    c = [100.0] * n
    ssl = [101.0] * n
    qqe = [0] * n
    dyn = [-1.0] * n
    for k in range(22, n): c[k] = 102.0         # 22: SSL Buy (fiyat çizgiyi yukarı kesti)
    qqe[24] = qqe[25] = 1                       # 24: 1. teyit QQE MOD mavi
    for k in range(25, n): dyn[k] = 1.0         # 25: 2. teyit DynaRange yeşil → sinyal
    f = {"c": c, "ssl": ssl, "qqe": qqe, "dyna": dyn}
    assert scanner.ssl_signal(f, 24, 1) is None          # DynaRange henüz kırmızı
    assert scanner.ssl_signal(f, 25, 1) == 22            # sinyal SSL Buy mumunu döndürür
    assert scanner.ssl_signal(f, 26, 1) is None          # aynı Buy için ikinci sinyal yok
    assert scanner.ssl_signal(f, 25, -1) is None
    q2 = [0] * n; q2[20] = 1                             # QQE Buy'dan ÖNCE mavi → sayılmaz
    assert scanner.ssl_signal(dict(f, qqe=q2), 25, 1) is None
    d2 = [-1.0] * n; d2[27] = d2[28] = 1.0
    assert scanner.ssl_signal(dict(f, dyna=d2), 27, 1) == 22             # Buy'dan 5 mum sonra: geçerli
    assert scanner.ssl_signal(dict(f, dyna=d2), 27, 1, wait=4) is None   # bekleme aşıldı → yok

def test_ssl_info_lines():
    n = 30
    c = [100.0] * 25 + [102.0] * 5
    f = {"c": c, "ssl": [101.0] * n, "qqe": [0] * 29 + [1], "dyna": [1.0] * n}
    out = scanner.ssl_info_lines({"f": f, "i": n - 1}, "long")
    assert out == ["🔷 SSL Hybrid: 🟢 <b>AL</b> (4 mum önce)", "✅ 1. teyit: QQE MOD mavi",
                   "✅ 2. teyit: DynaRange yeşil", "✅ SSL stratejisi sinyali onaylıyor → işleme girebilirsin"], out
    out = scanner.ssl_info_lines({"f": f, "i": n - 1}, "short")
    assert out[1] == "❌ 1. teyit: QQE MOD mavi" and out[-1] == "⚠️ SSL stratejisi sinyali onaylamıyor → işleme girmek riskli, bekle", out


def test_pivot_lines():
    pv = dict(scanner.pivot_levels(939.77, 800.67, 863.38), tf="1d", start=1000)
    assert round(pv["P"], 2) == 867.94 and round(pv["R1"], 2) == 921.08 and round(pv["R2"], 2) == 953.90
    assert round(pv["R3"], 2) == 1007.04 and round(pv["S1"], 2) == 814.80
    n = 10
    c = [860.0] * 7 + [870.0, 880.0, 890.0]          # 7. mumda P (867.94) yukarı kesildi
    f = {"c": c, "t": [1000 + k for k in range(n)], "st_dir": [1] * n, "dyna": [5.0] * n, "qqe": [1] * n}
    res = {"f": f, "i": n - 1, "meta": {"precision": 2}, "pivot": pv}
    out = scanner.pivot_lines(res, "long", {"timeframe": "15m"})
    assert out[0] == "📍 <b>PIVOTS</b> · 15dk", out
    assert out[1] == "Pivot 867.94 · fiyat üstünde kapanış (2 mum önce kapanış yaptı)", out
    assert out[2] == "✅ Pivot üstünde kapanış · ✅ Supertrend AL · ✅ DynaRange yeşil · ✅ QQE MOD mavi", out
    assert out[3] == "✅ Pivot stratejisi onaylandı → LONG girilebilir", out
    assert out[4] == "Giriş: Pivot 867.94" and out[5] == "TP1: R1 921.08 (+6.12%)", out
    assert out[8] == "Stop: S1 814.80 (-6.12%)", out
    f["c"] = c[:-1] + [925.0]                        # fiyat R1'i (921.08) geçti → geç kalındı
    out = scanner.pivot_lines(res, "long", {"timeframe": "15m"})
    assert out[-1] == "⚠️ Pivot stratejisi onaylandı ama fiyat R1'i geçmiş → geç kalındı, bekle", out
    assert not any(x.startswith("TP") for x in out), out
    f["c"] = c
    f["qqe"] = [0] * n
    out = scanner.pivot_lines(res, "long", {})
    assert out[2].endswith("❌ QQE MOD gri") and out[-1] == "⚠️ Pivot stratejisi onaylamıyor → işleme girmek riskli, bekle", out
    out = scanner.pivot_lines(res, "short", {})
    assert out[2].startswith("❌ Pivot altında kapanış") and out[-1].startswith("⚠️"), out


def test_pivot_retest_line():
    P, n = 100.0, 60
    cases = [([95.0] * 40 + [101, 103, 104, 105, 104, 102, 100.5, 101.5, 103, 105] + [106.0] * 10,
              "✅ Retest: pivot test edildi ve onaylandı → yükseliş teyit edildi"),
             ([95.0] * 40 + [101 + 3 * k for k in range(20)], "⬆️ Retest yapmadan yükseliş devam etti → geç giriş riski"),
             ([95.0] * 55 + [101, 102, 102.5, 103, 103], "⏳ Retest: pivota geri gelmedi, retest yapılmadı → bekle"),
             ([95.0] * 40 + [101, 103, 104, 105, 104, 102, 100.4] + [100.6] * 13,
              "🔄 Retest: pivota geri geldi, test ediliyor → yükseliş teyidi bekleniyor")]
    for c, want in cases:
        h = [x + 0.5 for x in c]; l = [x - 0.5 for x in c]
        f = {"c": c, "h": h, "l": l, "o": [c[0]] + c[:-1], "t": list(range(n)), "atr": ta.atr(h, l, c, 14)}
        assert scanner.pivot_retest_line(f, n - 1, P, 0) == want, (scanner.pivot_retest_line(f, n - 1, P, 0), want)


def test_pivot_signal():
    D = 86_400_000
    n = 200                                  # 15dk: dün 96 mum + bugün
    t0 = 10 * D - 96 * 900_000 - 8 * 900_000
    t = [t0 + k * 900_000 for k in range(n)]
    c = [100.0] * n; h = [101.0] * n; l = [99.0] * n
    for k in range(n):
        if t[k] < 10 * D - 96 * 900_000:
            c[k], h[k], l[k] = 95.0, 96.0, 94.0
        elif t[k] < 10 * D:
            c[k], h[k], l[k] = 100.0, 110.0, 90.0        # dün: H 110, L 90, C 100 → P 100
        else:
            c[k], h[k], l[k] = 98.0, 99.0, 97.0
    c[-1], h[-1] = 102.0, 102.5                           # son mum pivotun üstünde kapandı
    f = {"t": t, "c": c, "h": h, "l": l, "st_dir": [1] * n, "dyna": [1.0] * n, "qqe": [1] * n}
    pv = scanner.pivot_from_bars(f, n - 1, "15m")
    assert pv and round(pv["P"], 2) == 100.0 and pv["tf"] == "1d" and pv["start"] == 10 * D, pv
    sig = scanner.pivot_signal(f, n - 1, 1, pv)
    assert sig["dir"] == "long" and [x[0] for x in sig["tps"]] == ["R1", "R2", "R3"] and sig["stop_name"] == "S1", sig
    assert round(sig["tps"][0][1], 2) == 107.64 and round(sig["stop"], 2) == 92.36
    assert scanner.pivot_signal(f, n - 1, -1, pv) is None
    f["qqe"] = [1] * (n - 1) + [0]
    assert scanner.pivot_signal(f, n - 1, 1, pv) is None          # QQE MOD onayı yok
    # haftalık dönem başlangıcı pazartesi 00:00 UTC
    mon = scanner.pivot_period_start(1794700800000, 7 * D)       # 15.11.2026 pazar → 09.11.2026 pazartesi
    assert mon == 1794182400000, mon


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("OK", name)


def test_tv_rating():
    import math
    n = 400
    c = [100 + 10 * math.sin(k / 15) + k * 0.05 for k in range(n)]
    h = [x + 1 for x in c]
    l = [x - 1 for x in c]
    v = [1000.0] * n
    o = ta.tv_technical_rating(h, l, c, v)
    last = o[-1]
    assert len(last["votes"]) == 26 and last["ma_n"] == 15 and last["osc_n"] == 11
    assert -1 <= last["all"] <= 1
    assert ta.tv_technical_rating(h, l, c, v, last_only=True)[-1]["all"] == last["all"]
    assert scanner.rating_label(0.6)[0] == "GÜÇLÜ AL" and scanner.rating_label(0.5)[0] == "AL"
    assert scanner.rating_label(0.1)[0] == "NÖTR" and scanner.rating_label(-0.1)[0] == "NÖTR"
    assert scanner.rating_label(-0.5)[0] == "SAT" and scanner.rating_label(-0.51)[0] == "GÜÇLÜ SAT"
    f = {"h": h, "l": l, "c": c, "v": v, "bv": v}
    r = scanner.tv_rating({"f": f, "i": n - 1})
    assert r and r[0] in ("GÜÇLÜ AL", "AL", "NÖTR", "SAT", "GÜÇLÜ SAT")
    line = scanner.technical_rating_line([], r)
    assert line.startswith("<b>İŞLEM SKORU :</b>") and "AL 🟢▲ %" in line and "SAT 🔴▼ %" in line


def test_rating_votes():
    f = {"c": [100.0], "st_dir": [-1], "ssl": [99.0]}
    res = {"f": f, "i": 0, "votes": [("RSI", 1), ("TrendFlex", 1)], "pivot": {"P": 101.0}}
    v = dict(scanner.rating_votes(res))
    assert v == {"RSI": 1, "TrendFlex": 1, "Supertrend": -1}
    res["votes"].append(("Supertrend", -1))
    assert [n for n, _ in scanner.rating_votes(res)].count("Supertrend") == 1


def test_market_rows():
    from datetime import datetime, timezone
    mkt = {"BTC": {"last": 78500.0, "chg": -1.4}, "ETH": {"last": 2650.5, "chg": 0.8}, "QQQ": {"last": 612.4, "chg": 0.85}}
    res = {"meta": {"symbol": "SOLUSDT", "type": "COIN"}, "leader_name": "BTC", "leader_bias": -1.0,
           "eth_bias": 1.0, "mkt": mkt, "qv24": 4_235_000}
    lb = scanner.leader_block(res)
    assert lb[0] == "🔴▼ BTC yönü · Trend: Düşüşte · 24s: 78,500.00 🔴▼ %1.40", lb
    assert lb[1] == "🟢▲ ETH yönü · Trend: Yükselişte · 24s: 2,650.50 🟢▲ %0.80", lb
    now = datetime(2026, 11, 16, 16, 0, tzinfo=timezone.utc)          # Pazartesi, seans açık
    ml = scanner.market_lines(res, {}, now)
    assert ml[0] == "🟢▲ ABD borsası · Açık · Yükselişte · 24s: Nasdaq QQQ 612.40 🟢▲ %0.85", ml
    assert ml[1] == "🔴 Likidite · Düşük (24s hacim 4.2M $ · yüksek eşiği 50M $)", ml
    res["meta"] = {"symbol": "ETHUSDT", "type": "COIN"}
    assert len(scanner.leader_block(res)) == 1


def test_market_rows_equity():
    from datetime import datetime, timezone
    mkt = {"QQQ": {"last": 665.62, "chg": -0.92}}
    res = {"meta": {"symbol": "TSMUSDT", "type": "EQUITY"}, "leader_name": "QQQ", "leader_bias": -1.0,
           "mkt": mkt, "qv24": 25_200_000}
    assert scanner.leader_block(res) == ["🔴▼ QQQ yönü · Trend: Düşüşte · 24s: 665.62 🔴▼ %0.92"]
    ml = scanner.market_lines(res, {}, datetime(2026, 11, 16, 16, 0, tzinfo=timezone.utc))
    assert ml == ["🔴▼ ABD borsası · Açık · Düşüşte · 24s: Nasdaq QQQ 665.62 🔴▼ %0.92",
                  "🟢 Likidite · Yüksek (24s hacim 25.2M $ · yüksek eşiği 5M $)"], ml


def test_send_telegram_retries(monkeypatch):
    import io
    import urllib.error
    calls = {"n": 0}

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=0):
        calls["n"] += 1
        if calls["n"] < 3:
            raise urllib.error.URLError(ConnectionResetError(104, "Connection reset by peer"))
        return Resp(b'{"ok": true}')
    monkeypatch.setattr(scanner.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(scanner.time, "sleep", lambda s: None)
    assert scanner.send_telegram("x", "t", "c") is True and calls["n"] == 3

    calls["n"] = -100                                   # hiç düzelmez → 6 denemeden sonra hata
    try:
        scanner.send_telegram("x", "t", "c")
        assert False, "hata bekleniyordu"
    except RuntimeError as e:
        assert "6 deneme" in str(e)


def test_dominance_line():
    base = {"meta": {"symbol": "SOLUSDT", "type": "COIN"}, "mkt": {"BTC": {"last": 1, "chg": 1.2}}}
    up = scanner.dominance_line(dict(base, btc_dom={"dom": 57.3, "chg": 0.42}))
    assert up == ("🟢▲ BTC Dominance · Yükselişte · %57.30 (▲ 0.42 puan) → para BTC'ye akıyor, BTC altcoinlerden güçlü → altcoinler "
                  "geride kalabilir → Sonuç: altcoin LONG'larında temkinli ol, BTC daha güçlü")
    dn = scanner.dominance_line(dict(base, btc_dom={"dom": 56.1, "chg": -0.35}))
    assert dn.startswith("🔴▼ BTC Dominance · Düşüşte · %56.10 (▼ 0.35 puan) → para altcoinlere akıyor")
    base["mkt"]["BTC"]["chg"] = -2.0
    assert "riskten kaçış" not in scanner.dominance_line(dict(base, btc_dom={"dom": 57.3, "chg": 0.42}))
    assert "altcoinler BTC'den daha sert düşüyor →" in scanner.dominance_line(dict(base, btc_dom={"dom": 57.3, "chg": 0.42}))
    assert "BTC altcoinlerden daha sert düşüyor → altcoinler daha güçlü" in scanner.dominance_line(dict(base, btc_dom={"dom": 56.1, "chg": -0.35}))
    assert "yatay" in scanner.dominance_line(dict(base, btc_dom={"dom": 56.1, "chg": 0.01}))
    assert scanner.dominance_line(base) is None


def test_bias_tf_label():
    assert scanner.bias_tf_label({"timeframe": "15m"}) == "15dk + 1s"
    assert scanner.bias_tf_label({"timeframe": "1h"}) == "1s + 4s"
    assert scanner.bias_tf_label({"timeframe": "4h"}) == "4s + 1g"
    res = {"meta": {"symbol": "BEATUSDT", "type": "COIN"}, "leader_name": "BTC", "leader_bias": 0.8,
           "mkt": {"BTC": {"last": 64760.4, "chg": -0.32}}}
    assert scanner.leader_block(res, {"timeframe": "15m"})[0] == \
        "🟢▲ BTC yönü (15dk + 1s) · Trend: Yükselişte · 24s: 64,760.40 🔴▼ %0.32"


def test_upper_resample():
    H = scanner.HOUR_MS
    c4h = [{"t": k * 4 * H, "o": 1, "h": 2, "l": 0.5, "c": 1 + k, "v": 1} for k in range(13)]
    d = scanner.resample_4h(c4h, 4 * H)               # 4s → 1 gün (6 mum)
    assert len(d) == 2 and d[0]["t"] == 0 and d[0]["c"] == 6 and d[1]["c"] == 12
    c15 = [{"t": k * 15 * 60_000, "o": 1, "h": 2, "l": 0.5, "c": k, "v": 1} for k in range(9)]
    assert [x["c"] for x in scanner.resample_4h(c15, 15 * 60_000)] == [3, 7]   # 15dk → 1s


def test_with_header_line():
    b = ["📍 <b>PIVOTS</b> · 4 saat", "Pivot 1"]
    assert scanner.with_header_line(b) == ["📍 <b>PIVOTS</b> · 4 saat", scanner.SEP, "Pivot 1"]
    b = ["📍 <b>PIVOTS</b> · 4 saat", "Pivot 1", "✅ onay", "Giriş: Pivot 1", "TP1: R1", "TP2: R2", "Stop: S1"]
    assert scanner.with_header_line(b)[2:] == ["Pivot 1", scanner.THIN, "✅ onay", scanner.THIN, "Giriş: Pivot 1",
                                               "TP1: R1", "TP2: R2", "Stop: S1"]
    assert scanner.with_header_line(["🔊 Hacim: x"]) == ["🔊 Hacim: x"]


def test_section():
    assert scanner.section(["📍 <b>PIVOTS</b> · 4 saat", "x", "y"]) == ["", "📍 <b>PIVOTS</b> · 4 saat", scanner.SEP, "x", scanner.THIN, "y"]
    assert scanner.section(["🔊 Hacim"]) == ["", scanner.SEP, "🔊 Hacim"]


def test_market_section():
    assert scanner.market_section(["a"], ["b"]) == ["", "🌍 <b>PİYASA DURUMU</b>", scanner.SEP, "a", scanner.THIN, "b"]
    assert scanner.market_section([], []) == []


def test_market_rows_ndx():
    from datetime import datetime, timezone
    res = {"meta": {"symbol": "SOLUSDT", "type": "COIN"}, "ndx": {"last": 27277.73, "chg": -2.38},
           "mkt": {"QQQ": {"last": 665.62, "chg": -0.92}}, "qv24": None}
    ml = scanner.market_lines(res, {}, datetime(2026, 11, 16, 16, 0, tzinfo=timezone.utc))
    assert ml == ["🔴▼ ABD borsası · Açık · Düşüşte · Günlük: Nasdaq 100 27,277.73 🔴▼ %2.38"], ml


def test_arr():
    assert scanner.arr(1.284) == "🟢▲ %1.28" and scanner.arr(-2.5) == "🔴▼ %2.50" and scanner.arr(0) == "⚪▶ %0.00"
    assert scanner.arr(-11.73, 1) == "🔴▼ %11.7" and scanner.arr(None) == "–"


def test_dir_arrow_sections():
    b = ["☁️ <b>ICHIMOKU</b> · 15dk", "🟢 Kijun 1: yukarı kırıldı", "🔴 Tenkan 2: aşağı kırıldı", "⚪ Ichimoku kararsız (2/4)"]
    out = scanner.with_header_line(b)
    assert out[2] == "🟢▲ Kijun 1: yukarı kırıldı" and out[4] == "🔴▼ Tenkan 2: aşağı kırıldı" and out[6].startswith("⚪ ")
    p = scanner.with_header_line(["📍 <b>PIVOTS</b> · 15dk", "🟢 x"])
    assert p[2] == "🟢 x"


def test_coin_base():
    assert scanner.coin_base("1000PEPEUSDT") == "PEPE" and scanner.coin_base("1MBABYDOGEUSDT") == "BABYDOGE"
    assert scanner.coin_base("BTCUSDT") == "BTC" and scanner.coin_base("1INCHUSDT") == "1INCH"


def test_notifier_major_channel(monkeypatch):
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "-100main")
    monkeypatch.delenv("TELEGRAM_CHAT_ID_MAJOR", raising=False)
    n = scanner.Notifier()
    assert n.chat_for("BTCUSDT") == "-1003824728969"
    assert n.chat_for("ETHUSDT") == "-1003824728969"
    assert n.chat_for("SOLUSDT") == "-1003824728969"
    assert n.chat_for("ARBUSDT") == "-100main"
    assert n.chat_for(None) == "-100main"
    assert n.chat_for("NVDAUSDT", "EQUITY") == "-1003365238459"
    assert n.chat_for("SAMSUNGUSDT", "KR_EQUITY") == "-1003365238459"
    assert n.chat_for("XAUUSDT", "COMMODITY") == "-1004440589259"
    assert n.chat_for("ARBUSDT", "COIN") == "-100main"
    assert n.chat_for("HYPEUSDT", "COIN") == "-1003824728969"
    assert n.chat_for(None, "BULLETIN") == "-1003810871076"
    assert n.chat_for("BTCUSDT", "COIN") == "-1003824728969"


def test_time_under_new_banners():
    for sym in ("BTCUSDT", "XRPUSDT", "BNBUSDT", "SOLUSDT", "DOGEUSDT", "AVAXUSDT"):
        L = scanner.banner_lines({"symbol": sym}, {"timeframe": "15m"}) + ["🔴 SHORT"]
        scanner.put_time_top(L, "17.11.2026 18:45")
        assert L[3] == "🕒 17.11.2026 18:45 Mum Kapanışı", sym
    L = ["🔴 SHORT · X"]
    scanner.put_time_top(L, "t")
    assert L[0] == "🕒 t Mum Kapanışı"


def test_major_banner_direction():
    b = scanner.banner_lines({"symbol": "AVAXUSDT"}, {"timeframe": "15m"}, "short")
    assert b[0] == b[2] == "🟥" * 10
    assert b[1] == "🔺 <b>AVAX</b> · 📉 <b>SHORT SİNYALİ</b> · 15dk"
    b = scanner.banner_lines({"symbol": "BTCUSDT"}, {"timeframe": "1h"}, "long")
    assert b[0] == "🟩" * 10 and b[1] == "₿ <b>BTC</b> · 📈 <b>LONG SİNYALİ</b> · 1s"


def test_banner_name():
    assert scanner.banner_name({"symbol": "NVDAUSDT", "type": "EQUITY"}) == "🇺🇸 <b>NVDA</b>"
    assert scanner.banner_name({"symbol": "SAMSUNGUSDT", "type": "KR_EQUITY"}) == "🇰🇷 <b>SAMSUNG</b>"
    assert scanner.banner_name({"symbol": "SUIUSDT", "type": "COIN"}) == "🪙 <b>SUI</b>"
    assert scanner.banner_name({"symbol": "XAUUSDT", "type": "COMMODITY"}) == "🥇 <b>ALTIN</b>"
    assert scanner.banner_name({"symbol": "NATGASUSDT", "type": "COMMODITY"}) == "🔥 <b>DOĞAL GAZ</b>"


def test_daily_weekly_upper():
    day = 86_400_000
    mon = 1763337600000            # 2025-11-17 pazartesi 00:00 UTC
    cs = [{"t": mon + k * day, "o": 1, "h": 2, "l": 0.5, "c": 1 + k, "v": 1} for k in range(14)]
    w = scanner.resample_4h(cs, day)
    assert len(w) == 2 and w[0]["t"] == mon and w[0]["c"] == 7
    assert scanner.bias_tf_label({"timeframe": "1d"}) == "1g + 1 hafta"


def test_display_name():
    assert scanner.display_name({"symbol": "HYPEUSDT", "type": "COIN"}) == "⚡ <b>HYPE</b>"
    assert scanner.display_name({"symbol": "STXUSDT", "type": "COIN"}) == "🪙 <b>STX</b>"
    assert scanner.display_name({"symbol": "NVDAUSDT", "type": "EQUITY"}) == "🇺🇸 <b>NVDA</b>"


def test_news_organize():
    import report
    from datetime import datetime, timezone
    now = datetime(2026, 11, 18, 9, 0, tzinfo=timezone.utc)
    it = lambda t, imp, src="X": {"title": t, "imp": imp, "source": src, "link": t, "dt": now}
    news = {"💵 Ekonomi & Finans": [it("Altın 3.800 doların altına düştü", 2), it("ABD'de enflasyon beklentiyi aştı", 3),
                                   it("Borsa İstanbul güne yükselişle başladı", 2),
                                   it("Fed'in Williams'ı daha fazla faiz artırımı gerekebileceğini söyledi", 8)],
            "🌍 Gündem": [it("İran Kuveyt'e saldırdı, Hürmüz gerginliği sürüyor", 3, "AA")],
            "🪙 Kripto": [it("Bitcoin 64 bin dolara geriledi", 2, "K")]}
    o = report.organize_news(news)
    assert [x["title"][:5] for x in o["🚨 Önemli Haberler"]] == ["Fed'i", "İran "]
    assert [x["title"][:5] for x in o["🛢️ Emtia"]] == ["Altın"]
    assert [x["title"][:5] for x in o["📊 Ekonomi"]] == ["ABD'd"]
    assert [x["title"][:5] for x in o["🏦 Finans"]] == ["Borsa"]
    assert list(o) == report.NEWS_ORDER


def test_econ_category():
    import report
    assert report.econ_category("Nvidia Çin pazarından çekiliyor: gelir risk altında") != "🛢️ Emtia"
    assert report.econ_category("Bitcoin doların altına düştü") != "🛢️ Emtia"
    assert report.econ_category("Altın yeni faiz beklentisiyle düştü") == "🛢️ Emtia"
    assert report.econ_category("Gram altın rekor kırdı") == "🛢️ Emtia"
    assert report.econ_category("Panoro Energy rekor üretim açıkladı", "fin") == "🏦 Finans"
    assert report.econ_category("İran ablukasının ABD'ye faturası 1 milyar dolar") == "📊 Ekonomi"
    assert report.econ_category("Bitcoin 64.474 dolara geriledi, faiz artışı beklentisi sürüyor") == "🪙 Kripto"


def test_inline_release_impact():
    import econ
    e = dict(title="Inflation Rate YoY", country="GB", actual=3.6, forecast=3.6, previous=3.5)
    assert econ.verdict(e) == ("⚪", "Beklentiyle aynı · önceki döneme göre ▲ yükseldi")
    imp = econ.asset_impact(e)
    assert "biraz azalır" in imp["reason"] and ("🟢", "Sterlin için hafif olumlu") in imp["items"]
    flat = econ.asset_impact(dict(title="CPI YoY", country="US", actual=3.0, forecast=3.0, previous=3.0))
    assert flat["items"] == [("⚪", "Piyasalar için nötr")]


def test_fvg():
    # 0-2: boğa FVG (mum2 low 105 > mum0 high 100), 3-5: ayı FVG yukarıda yok; fiyat 110
    h = [100, 106, 110, 112, 111, 111]
    l = [95, 99, 105, 107, 108, 108]
    c = [98, 105, 109, 110, 110, 110]
    f = {"h": h, "l": l, "c": c, "o": c, "atr": [2] * 6}
    g = scanner.find_fvgs(f, 5)
    assert g and g[0]["dir"] == 1 and g[0]["lo"] == 100 and g[0]["hi"] == 105
    lines = scanner.fvg_lines(f, 5, 1, 0)                 # en yakın açık boğa FVG: 106 – 107
    assert any(x.startswith("🟢 Boğa FVG (destek): 106.00 – 107.00") for x in lines), lines
    f2 = dict(f, l=[95, 99, 105, 107, 99, 108])          # 4. mum boşluğu doldurdu
    assert not [x for x in scanner.find_fvgs(f2, 5) if x["k"] == 2]


def test_exchange_label():
    assert scanner.type_label({"symbol": "COSTUSDT", "type": "EQUITY"}) == "NASDAQ"
    assert scanner.type_label({"symbol": "ORCLUSDT", "type": "EQUITY"}) == "NYSE"
    assert scanner.type_label({"symbol": "SAMSUNGUSDT", "type": "KR_EQUITY"}) == "KOSPI"
    assert scanner.type_label({"symbol": "ZZZUSDT", "type": "EQUITY"}) == "ABD Borsası"
    assert scanner.type_label({"symbol": "SUIUSDT", "type": "COIN"}) == "KRİPTO"


def _candles_after(trend, bars):
    o, h, l, c = [], [], [], []
    p = 100.0
    for _ in range(30):
        q = p + trend
        o.append(p); c.append(q); h.append(max(p, q) + 0.5); l.append(min(p, q) - 0.5)
        p = q
    for do, dh, dl, dc in bars:
        o.append(p + do); h.append(p + dh); l.append(p + dl); c.append(p + dc)
    return o, h, l, c


def test_candle_patterns_turkish_names():
    import patterns as pt
    import indicators as ta
    cases = [("Çekiç", 1, -1, [(0, 0.1, -3, 0.4)]), ("Asılı Adam", -1, 1, [(0, 0.1, -3, 0.4)]),
             ("Kayan Yıldız", -1, 1, [(0, 3, -0.1, 0.4)]), ("Ters Çekiç", 1, -1, [(0, 3, -0.1, 0.4)]),
             ("Yutan Boğa", 1, -1, [(0, 0.2, -2.2, -2), (-2.1, 0.6, -2.2, 0.5)]),
             ("Boğa Harami", 1, -1, [(0, 0.2, -2.7, -2.5), (-2, -0.6, -2.1, -1)]),
             ("Kara Bulut", -1, 1, [(0, 2.7, -0.2, 2.5), (2.5, 2.8, 0.6, 0.8)]),
             ("Sabah Yıldızı", 1, -1, [(0, 0.2, -2.7, -2.5), (-2.6, -2.2, -3.2, -2.8), (-2.7, -0.5, -2.8, -0.7)]),
             ("Üç Kara Karga", -1, 1, [(0, 0.1, -1.6, -1.5), (-1.0, -0.9, -3.1, -3.0), (-2.5, -2.4, -4.6, -4.5)]),
             ("Doji", 0, -1, [(0, 0.5, -0.5, 0.02)])]
    for name, yon, trend, bars in cases:
        o, h, l, c = _candles_after(trend, bars)
        got = pt.candle_patterns(o, h, l, c, ta.atr(h, l, c, 14))
        assert (name, yon) in got, (name, got)


def _zigzag(points):
    c = []
    for (k0, p0), (k1, p1) in zip(points, points[1:]):
        for k in range(k0, k1):
            c.append(p0 + (p1 - p0) * (k - k0) / (k1 - k0) + (0.18 if k % 2 else -0.18))
    c.append(points[-1][1])
    o = [c[0]] + c[:-1]
    return o, [max(a, b) + 0.6 for a, b in zip(o, c)], [min(a, b) - 0.6 for a, b in zip(o, c)], c


def test_chart_patterns_detected():
    import patterns as pt
    import indicators as ta
    cases = [("İkili Tepe", "kirildi", [(0, 80), (40, 100), (55, 90), (70, 100), (82, 87)]),
             ("İkili Dip", "kirildi", [(0, 120), (40, 100), (55, 110), (70, 100), (82, 113)]),
             ("OBO", "kirildi", [(0, 80), (30, 100), (42, 92), (56, 108), (70, 92), (82, 100), (95, 88)]),
             ("TOBO", "kirildi", [(0, 120), (30, 100), (42, 108), (56, 92), (70, 108), (82, 100), (95, 112)]),
             ("Simetrik Üçgen", "olusuyor", [(0, 80), (20, 110), (32, 90), (44, 106), (56, 94), (66, 102), (74, 98)]),
             ("Yükselen Üçgen", "olusuyor", [(0, 80), (20, 100), (30, 90), (40, 100), (50, 94), (60, 100), (68, 97)]),
             ("Dikdörtgen", "olusuyor", [(0, 80), (20, 110), (32, 100), (44, 110), (56, 100), (68, 110), (78, 104)]),
             ("Yükselen Kama", "kirildi", [(0, 80), (20, 100), (32, 96), (44, 108), (56, 106), (68, 114), (76, 112)]),
             ("Yükselen Bayrak", "kirildi", [(0, 90), (50, 92), (58, 115), (66, 111), (68, 113), (72, 110), (75, 118)]),
             ("Fincan Kulp", "olusuyor", [(0, 80), (20, 110), (35, 97), (45, 92), (55, 97), (70, 110), (76, 105), (80, 108)])]
    for name, durum, pts in cases:
        o, h, l, c = _zigzag(pts)
        got = pt.chart_patterns(h, l, c, ta.atr(h, l, c, 14))
        assert any(g["ad"] == name and g["durum"] == durum for g in got), (name, got)


def test_formation_lines_text():
    res = {"meta": {"precision": 2}, "forms": {
        "15m": {"mum": [("Yutan Boğa", 1), ("Doji", 0)], "grafik": [
            {"ad": "İkili Tepe", "yon": -1, "durum": "kirildi", "kirilim": -1, "seviye": 90.0, "hedef": 80.0}], "price": 89},
        "4h": {"mum": [], "grafik": [
            {"ad": "Simetrik Üçgen", "yon": 0, "durum": "olusuyor", "kirilim": 0, "ust": 105.0, "alt": 95.0, "hedef": None}],
            "price": 100}}}
    assert scanner.formation_lines(res) == [
        "🧩 <b>FORMASYONLAR</b>",
        "🟢 15dk · Yutan Boğa (mum) → yükseliş işareti",
        "🔴 15dk · İkili Tepe → 90.00 aşağı kırıldı, düşüş beklenebilir · hedef 80.00"]


def test_triangle_not_from_single_spike():
    """PENDLE 4s (18.11.2026): düz dipler (1.4033 / 1.4010) + tek eski iğne (1.3288) yükselen üçgen sayılmaz."""
    import json, os
    import patterns as pt
    import indicators as ta
    d = json.load(open(os.path.join(os.path.dirname(__file__), "data", "pendle_4h.json")))
    got = pt.chart_patterns(d["h"], d["l"], d["c"], ta.atr(d["h"], d["l"], d["c"], 14))
    assert not any(g["ad"] == "Yükselen Üçgen" for g in got), got


def test_pattern_images_render():
    """Kırılan grafik formasyonu için PNG üretilir; oluşmakta olan için üretilmez."""
    import patterns as pt
    import indicators as ta
    o, h, l, c = _zigzag([(0, 80), (40, 100), (55, 90), (70, 100), (82, 87)])
    cs = [{"t": 1795000000000 + k * 900000, "o": o[k], "h": h[k], "l": l[k], "c": c[k]} for k in range(len(c))]
    fm = scanner.tf_formations(cs)
    res = {"meta": {"symbol": "BTCUSDT", "type": "COIN", "precision": 2}, "forms": {"15m": fm}}
    imgs = scanner.pattern_images(res, {"formations": {"enabled": True}})
    assert len(imgs) == 1 and imgs[0][0][:8] == b"\x89PNG\r\n\x1a\n"
    assert imgs[0][1].startswith("🔴 ₿ <b>BTC</b> · 15dk · İkili Tepe → ") and "aşağı kırıldı · hedef" in imgs[0][1]
    o, h, l, c = _zigzag([(0, 80), (40, 100), (55, 90), (70, 100), (80, 93)])        # kırılmamış
    cs = [{"t": 1795000000000 + k * 900000, "o": o[k], "h": h[k], "l": l[k], "c": c[k]} for k in range(len(c))]
    res["forms"] = {"15m": scanner.tf_formations(cs)}
    assert scanner.pattern_images(res, {"formations": {"enabled": True}}) == []


def test_failed_breakout_not_reported():
    """Boyun kırıldıktan sonra fiyat tekrar boyun üstüne dönerse ikili tepe yazılmaz (başarısız kırılım)."""
    import patterns as pt
    import indicators as ta
    o, h, l, c = _zigzag([(0, 80), (40, 100), (55, 90), (70, 100), (80, 87), (84, 93)])
    got = pt.chart_patterns(h, l, c, ta.atr(h, l, c, 14))
    assert not any(g["ad"] == "İkili Tepe" and g["durum"] == "kirildi" for g in got), got


def test_trendline_images_render():
    """Kırılan trend çizgisi için PNG ve mesajdaki satırla aynı açıklama üretilir."""
    import math
    c = [100 - k * 0.1 + 4 * math.sin(k / 8) for k in range(220)] + [80 + k * 0.9 for k in range(1, 9)]
    o = [c[0]] + c[:-1]
    h = [x + 0.5 for x in c]; l = [x - 0.5 for x in c]
    cs = [{"t": 1795000000000 + k * 900000, "o": o[k], "h": h[k], "l": l[k], "c": c[k]} for k in range(len(c))]
    tl = [dict(ev, tf="15m", price=c[-1]) for ev in ta.trendlines_close(h, l, c)]
    assert any(e["state"] == "broken" for e in tl), tl
    res = {"meta": {"symbol": "BTCUSDT", "type": "COIN", "precision": 2}, "tline": tl, "tl_cs": {"15m": cs}}
    imgs = scanner.trendline_images(res, {})
    assert len(imgs) == 1 and imgs[0][0][:8] == b"\x89PNG\r\n\x1a\n"
    assert imgs[0][1].startswith("🟢 ₿ <b>BTC</b> · 15dk: Düşen trend çizgisi kırıldı · "), imgs[0][1]


def test_trendline_rebreak_is_retest():
    """PENDLE 4s (18.11.2026): yükselen çizgi 293. mumda kırıldı, 295'te kapanışla geri döndü (retest),
    296'da tekrar kırdı. Kırılım ilk kırılım mumu olmalı ve retest yapılmış sayılmalı."""
    import json, os
    d = json.load(open(os.path.join(os.path.dirname(__file__), "data", "pendle_4h.json")))
    ev = [e for e in ta.trendlines_close(d["h"], d["l"], d["c"]) if e["type"] == "rising"]
    assert ev and ev[0]["state"] == "broken", ev
    assert ev[0]["bars_ago"] == 6 and ev[0]["retest"] == "confirmed" and ev[0]["rt"] == 295, ev


def test_divergence_images_render():
    """RSI uyumsuzluğu için PNG ve mesajdaki satırla aynı açıklama üretilir."""
    import json, os
    d = json.load(open(os.path.join(os.path.dirname(__file__), "data", "pendle_4h.json")))
    h, l, c = d["h"], d["l"], d["c"]
    cs = [{"t": 1795000000000 + k * 14400000, "o": (c[k - 1] if k else c[0]), "h": h[k], "l": l[k], "c": c[k]}
          for k in range(len(c))]
    r = ta.rsi(c, 14)
    lows = [k for k in range(5, len(c) - 5) if r[k] is not None and None not in r[k - 5:k + 6] and r[k] == min(r[k - 5:k + 6])]
    pair = next((a, b) for a, b in zip(lows, lows[1:]) if 5 <= b - a <= 60)
    res = {"meta": {"symbol": "PENDLEUSDT", "type": "COIN", "precision": 4},
           "div_d": {"4h": {"pos": pair, "neg": None, "rsi": r, "cs": cs}}}
    imgs = scanner.divergence_images(res, {})
    assert len(imgs) == 1 and imgs[0][0][:8] == b"\x89PNG\r\n\x1a\n"
    assert imgs[0][1] == "🟢 🪙 <b>PENDLE</b> · 4 saat · Pozitif uyumsuzluk → yükseliş başlayabilir, dönüş için onay bekle"


def test_momentum_radar():
    """Trend içinde hızlanma: hacim ≥5x + 48 mumluk zirve kırılımı + büyük gövde + tepeye yakın kapanış → ⚡ PUMP HAREKETİ."""
    n = 80
    o = [100 + k * 0.05 for k in range(n)]
    c = [x + 0.1 for x in o]
    h = [x + 0.3 for x in c]; l = [x - 0.3 for x in o]
    v = [1000.0] * n
    o[-1], c[-1], h[-1], l[-1], v[-1] = c[-2], c[-2] + 4.0, c[-2] + 4.3, c[-2] - 0.1, 8000.0
    f = {"o": o, "h": h, "l": l, "c": c, "v": v, "vol_ma": ta.sma(v, 20), "atr": ta.atr(h, l, c, 14)}
    cfg = {"timeframe": "1h", "pump_radar": {"momentum": {}}}
    out = scanner.momentum_radar(f, n - 1, cfg)
    assert len(out) == 1 and out[0]["dir"] == "long" and out[0]["kind"] == "momentum", out
    assert out[0]["reasons"][1] == "2 günlük zirve kırıldı", out
    v[-1] = 3000.0                                        # hacim yetersiz → uyarı yok
    f["vol_ma"] = ta.sma(v, 20)
    assert scanner.momentum_radar(f, n - 1, cfg) == []


def test_reversal_radar():
    """Pump sonrası dönüş: %25+ yükseliş, zirveden %8+ geri çekilme, 12 mum EMA20 üstü sonrası hacimli kırmızı mumla altına."""
    base = [100.0] * 60 + [100 + k * 3 for k in range(1, 15)] + [142 - k * 0.6 for k in range(1, 14)]
    c = base[:]
    o = [c[0]] + c[:-1]
    h = [max(a, b) + 0.5 for a, b in zip(o, c)]; l = [min(a, b) - 0.5 for a, b in zip(o, c)]
    v = [1000.0] * len(c)
    o.append(c[-1]); c.append(c[-1] - 6); h.append(o[-1] + 0.2); l.append(c[-1] - 0.3); v.append(3000.0)
    f = {"o": o, "h": h, "l": l, "c": c, "v": v, "vol_ma": ta.sma(v, 20), "atr": ta.atr(h, l, c, 14), "ema20": ta.ema(c, 20)}
    i = len(c) - 1
    cfg = {"timeframe": "1h", "pump_radar": {"reversal": {}}}
    assert all(c[k] > f["ema20"][k] for k in range(i - 12, i - 1)) and c[i] < f["ema20"][i]
    out = scanner.reversal_radar(f, i, cfg)
    assert len(out) == 1 and out[0]["dir"] == "short" and out[0]["kind"] == "reversal", out
    v[-1] = 1200.0                                       # hacim yetersiz → uyarı yok
    f["vol_ma"] = ta.sma(v, 20)
    assert scanner.reversal_radar(f, i, cfg) == []


def test_momentum_radar_dump():
    """Dump hareketi: hacim ≥5x + 48 mumluk dip kırılımı + büyük kırmızı gövde + dibe yakın kapanış."""
    n = 80
    o = [100 - k * 0.05 for k in range(n)]
    c = [x - 0.1 for x in o]
    h = [x + 0.3 for x in o]; l = [x - 0.3 for x in c]
    v = [1000.0] * n
    o[-1], c[-1], h[-1], l[-1], v[-1] = c[-2], c[-2] - 4.0, c[-2] + 0.1, c[-2] - 4.3, 8000.0
    f = {"o": o, "h": h, "l": l, "c": c, "v": v, "vol_ma": ta.sma(v, 20), "atr": ta.atr(h, l, c, 14)}
    out = scanner.momentum_radar(f, n - 1, {"timeframe": "1h", "pump_radar": {"momentum": {"directions": ["long", "short"]}}})
    assert len(out) == 1 and out[0]["dir"] == "short" and out[0]["reasons"][1] == "2 günlük dip kırıldı", out


def test_signal_sections_only_sent_images():
    """Eşleştirme açıkken sinyalde sadece grafik kanalına resmi giden trend çizgisi / formasyon yazılır."""
    cs = [{"t": k * 900000, "o": 1, "h": 1, "l": 1, "c": 1} for k in range(100)]
    ev_a = {"tf": "15m", "type": "falling", "state": "broken", "bars_ago": 2, "retest": "none", "touches": 2}
    ev_b = {"tf": "1h", "type": "rising", "state": "broken", "bars_ago": 1, "retest": "none", "touches": 2}
    g = {"ad": "Alçalan Üçgen", "yon": -1, "durum": "kirildi", "kirilim": -1, "seviye": 1.0, "hedef": 0.9,
         "ciz": {"kb": 97}}
    res = {"meta": {"symbol": "XUSDT", "precision": 4}, "tline": [ev_a, ev_b], "tl_cs": {"15m": cs, "1h": cs},
           "forms": {"15m": {"mum": [("Yutan Boğa", 1)], "grafik": [g], "cs": cs}}}
    # eşleştirme kapalı: eskisi gibi hepsi
    assert len(scanner.trendline_lines(res)) == 3
    assert any("Yutan Boğa" in x for x in scanner.formation_lines(res))
    # eşleştirme açık: sadece 15dk çizgi ve formasyonun resmi gitti
    ts = 1763542800  # 19.11.2025 12:00 TSİ
    scanner.SENT_IMGS = {f"XUSDT|15m|tl|falling|{cs[97]['t']}": ts, f"XUSDT|15m|fm|Alçalan Üçgen|{cs[98]['t']}": ts}
    tl = scanner.trendline_lines(res)
    assert len(tl) == 2 and "15dk" in tl[1] and "🖼 resim kanalda (12:00)" in tl[1]
    fl = scanner.formation_lines(res)
    assert len(fl) == 3 and "Yutan Boğa (mum)" in fl[1] and "🖼" not in fl[1]
    assert "Alçalan Üçgen" in fl[2] and "🖼 resim kanalda (12:00)" in fl[2]
    # kanaldaki resim açıklamasıyla aynı ifade
    k1, k2 = f"XUSDT|15m|tl|falling|{cs[97]['t']}", f"XUSDT|15m|fm|Alçalan Üçgen|{cs[98]['t']}"
    scanner.SENT_TXT = {k1: "Düşen trend çizgisi (2 temas) 1.0000 seviyesinden 2 mum önce kırıldı; fiyat kırılım mumunun "
                            "tepesinin üstünde kapattı → retestsiz devam, yükseliş sürüyor",
                        k2: "Alçalan Üçgen → 1.0000 aşağı hacimle (1.8x) kırıldı, düşüş beklenebilir · hedef 0.9000"}
    assert scanner.trendline_lines(res)[1] == ("🟢 15dk: Düşen trend çizgisi (2 temas) 1.0000 seviyesinden 2 mum önce "
                                               "kırıldı; fiyat kırılım mumunun tepesinin üstünde kapattı → retestsiz devam, "
                                               "yükseliş sürüyor · 🖼 resim kanalda (12:00)")
    assert scanner.formation_lines(res)[2] == ("🔴 15dk · Alçalan Üçgen → 1.0000 aşağı hacimle (1.8x) kırıldı, "
                                               "düşüş beklenebilir · hedef 0.9000 · 2 mum önce · ⚠️ fiyat seviyenin içine döndü"
                                               " · 🖼 resim kanalda (12:00)")
    scanner.SENT_IMGS = {}
    assert scanner.trendline_lines(res) == []
    assert scanner.formation_lines(res) == ["🧩 <b>FORMASYONLAR</b>", "🟢 15dk · Yutan Boğa (mum) → yükseliş işareti"]


def test_sniper_pump_and_levels():
    """🎯 Nokta atışı: 5x hacimli zirve kırılımı pump5 olarak yakalanır; seviyeler 1R/2R/3R."""
    import sniper
    n = 300
    o = [100.0] * n; c = [100.0 + (0.2 if k % 2 else -0.2) for k in range(n)]
    h = [x + 0.5 for x in c]; l = [x - 0.5 for x in c]; v = [100.0] * n
    o[-1], c[-1], h[-1], l[-1], v[-1] = 100.0, 104.0, 104.2, 99.9, 900.0
    x = sniper.features(o, h, l, c, v)
    sig = [s for s in sniper.setups(o, h, l, c, v, n - 1, x) if s["rule"] == "pump5"]
    assert sig and sig[0]["d"] == 1 and "hacim 9.0x" in sig[0]["why"]
    lv = sniper.levels(104.0, 1, 103.0, 1.0)
    assert lv["stop"] == 103.0 and lv["tp"] == [105.0, 106.0, 107.0]
    lv = sniper.levels(100.0, -1, 100.2, 1.0, min_stop_pct=1.0)       # dar stop %1'e genişler
    assert abs(lv["stop"] - 101.0) < 1e-9 and abs(lv["tp"][2] - 97.0) < 1e-9
    msg = sniper.message("🪙 <b>SUI</b>", "15dk", sig[0], sniper.levels(104.0, 1, 103.0, 1.0), lambda p: f"{p:.2f}",
                         "19.11.2026 14:00", 1, {}, h1=-1, m15=0)
    assert msg.splitlines()[0] == "🚀 <b>PUMP · LONG</b> · 15dk"
    assert "🧭 15dk trend: ⚪ yatay\n🧭 1 saatlik trend: 🔴 düşüş\n🧭 4 saatlik trend: 🟢 yükseliş" in msg
    assert "📍 <b>Giriş:</b> 104.00" in msg and "🎯 <b>TP3:</b> 107.00 (+2.88%)" in msg and "🛑 <b>Stop:</b> 103.00 (-0.96%)" in msg
    short = {"rule": "top_sweep", "d": -1, "stop": 959.22, "why": "test"}
    msg = sniper.message("ZEC", "15dk", short, sniper.levels(949.72, -1, 959.22, 5.0), lambda p: f"{p:.2f}",
                         "19.11.2026 14:00", -1, {})
    assert "🎯 <b>TP1:</b> 940.22 (+1.00%)" in msg and "🎯 <b>TP3:</b> 921.22 (+3.00%)" in msg
    assert "🛑 <b>Stop:</b> 959.22 (-1.00%)" in msg


def test_pnl_short_tp_positive():
    """SHORT sinyalde TP'ler kâr (+), stop zarar (−) yazılır."""
    assert f"{scanner.pnl(940.22, 949.72, 'short'):+.2f}" == "+1.00"
    assert f"{scanner.pnl(959.22, 949.72, 'short'):+.2f}" == "-1.00"
    assert f"{scanner.pnl(105, 100, 'long'):+.2f}" == "+5.00" and f"{scanner.pnl(95, 100, 'long'):+.2f}" == "-5.00"



def test_sniper_ssl_system_short():
    """Kullanıcının SSL sistemi: tepede SSL Sell → çizgi kırmızı → Supertrend hâlâ AL iken SHORT."""
    import sniper
    n = 120
    c = [100.0 + k * 0.05 for k in range(n)]
    h = [x + 0.3 for x in c]; l = [x - 0.3 for x in c]; a = [0.5] * n
    col = [1] * n                       # uzun süre mavi
    ssl = [x - 1 for x in c]            # fiyat çizginin üstünde
    st_dir = [1] * n                    # Supertrend AL
    w, i = 114, 117
    h[w] = max(h[w - 48:w]) + 0.1       # tepede
    c[w] = ssl[w] - 0.5                 # SSL Sell (aşağı kesiş)
    for k in range(w + 1, i + 1):
        ssl[k] = c[k] + 1
    col[i - 1], col[i] = 0, -1          # gri → kırmızı
    p = {"min_regime": 15, "near_atr": 1.0, "warn_bars": 10}
    sig = sniper.ssl_system(h, l, c, ssl, st_dir, a, col, i, p)
    assert sig and sig["rule"] == "ssl_top" and sig["d"] == -1 and sig["warn"] == w
    assert sig["stop"] > max(h[w:i + 1]) and "tepede SSL Sell" in sig["why"]
    st_dir[i] = -1                      # Supertrend zaten SAT → erken giriş değil
    assert sniper.ssl_system(h, l, c, ssl, st_dir, a, col, i, p) is None
    # QQE MOD + DynaRange teyidi: çizgi döndüğü mumda yoksa, ilk kez ikisi birlikte sağlanınca (≤5 mum) sinyal
    st_dir[i] = 1
    qqe, dyna = [1] * n, [1.0] * n
    sig = sniper.ssl_system(h, l, c, ssl, st_dir, a, col, i, p, qqe, dyna)      # teyitler zıt: yine gelir, ❌ ile
    assert sig and "❌ 1. teyit: QQE MOD mavi → satıcılar zayıf" in sig["why"]
    assert "❌ 2. teyit: DynaRange yeşil → düşüş teyit edilmedi" in sig["why"] and "⏳ Teyitler henüz gelmedi" in sig["why"]
    p["confirm_required"] = True
    assert sniper.ssl_system(h, l, c, ssl, st_dir, a, col, i, p, qqe, dyna) is None      # teyit beklenirse gelmez
    for k in (i + 1, i + 2):            # çizgi kırmızı kalır, fiyat SSL altında
        col[k], c[k], ssl[k] = -1, c[i] - 0.1, c[i] + 1
    qqe[i + 1], qqe[i + 2], dyna[i + 1], dyna[i + 2] = -1, -1, 1.0, -1.0
    assert sniper.ssl_system(h, l, c, ssl, st_dir, a, col, i + 1, p, qqe, dyna) is None  # sadece QQE pembe
    sig = sniper.ssl_system(h, l, c, ssl, st_dir, a, col, i + 2, p, qqe, dyna)          # ikisi birlikte
    assert sig and sig["d"] == -1 and "✅ 1. teyit: QQE MOD pembe" in sig["why"] and "✅ 2. teyit: DynaRange kırmızı" in sig["why"]
    assert "✅ İki teyit de onaylıyor" in sig["why"]
    st_dir[i + 2] = -1                  # Supertrend de SAT: şart kapalıysa (15dk) yine gelir
    assert sniper.ssl_system(h, l, c, ssl, st_dir, a, col, i + 2, p, qqe, dyna) is None
    p["supertrend_opposite"] = False
    sig = sniper.ssl_system(h, l, c, ssl, st_dir, a, col, i + 2, p, qqe, dyna)
    assert sig and "Supertrend de SAT" in sig["why"] and "erken giriş" not in sig["why"]


def test_sniper_channel_routing():
    """Nokta Atışı kanalları Supertrend sinyalleri gibi ayrılır: majör / Nasdaq / emtia / altcoin."""
    n = scanner.Notifier.__new__(scanner.Notifier)
    n.major_symbols, n.equity_types = {"BTCUSDT"}, {"EQUITY", "KR_EQUITY", "HK_EQUITY"}
    n.sniper_chat, n.sniper_major, n.sniper_equity, n.sniper_commodity = "A", "M", "N", "E"
    n.sniper_main = False
    assert n.sniper_chat_for("BTCUSDT", "COIN")[0] == "M"
    assert n.sniper_chat_for("NVDAUSDT", "EQUITY")[0] == "N"
    assert n.sniper_chat_for("XAUUSDT", "COMMODITY")[0] == "E"
    assert n.sniper_chat_for("SUIUSDT", "COIN")[0] == "A"
    n.sniper_major, n.sniper_equity = "", ""
    assert n.sniper_chat_for("BTCUSDT", "COIN")[0] == "A"          # majör kanalı yokken eski kanal
    assert n.sniper_chat_for("NVDAUSDT", "EQUITY")[0] == ""        # Nasdaq kanalı yokken gönderilmez
    # SSL Hybrid sinyalleri Supertrend kanallarına
    n.sniper_main, n.chat_id, n.major_chat, n.equity_chat, n.commodity_chat, n.bulletin_chat = True, "ANA", "MAJ", "NAS", "EMT", "BUL"
    assert [n.sniper_chat_for(s_, t_)[0] for s_, t_ in (("BTCUSDT", "COIN"), ("NVDAUSDT", "EQUITY"), ("XAUUSDT", "COMMODITY"),
                                                         ("SUIUSDT", "COIN"))] == ["MAJ", "NAS", "EMT", "ANA"]


def test_sniper_still_open():
    """Aynı kuralın sinyali stop / TP3 olmadan tekrar gönderilmez."""
    import sniper
    f = {"t": [0, 1, 2, 3], "h": [10, 10.5, 10.6, 10.4], "l": [9.5, 9.6, 9.7, 9.8]}
    rec = {"t": 0, "d": -1, "stop": 11.0, "tp3": 8.0}            # SHORT: ne stop ne TP3
    assert sniper.still_open(rec, f, 3) is True
    f["h"][2] = 11.2                                              # stop oldu → yeni sinyal serbest
    assert sniper.still_open(rec, f, 3) is False
    rec = {"t": 0, "d": 1, "stop": 9.0, "tp3": 10.55}            # LONG: TP3'e ulaştı
    assert sniper.still_open(rec, {"t": [0, 1, 2], "h": [10, 10.5, 10.6], "l": [9.5, 9.6, 9.7]}, 2) is False
