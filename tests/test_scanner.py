"""Yerel testler: python3 tests/test_scanner.py"""
import math
import os
import random
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import indicators as ta  # noqa: E402
import scanner  # noqa: E402


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
    for word in ("15dk", "1 saat", "4 saat", "1 gün", "Yükseliş", "Düşüş", "Nötr", "Veri yok"):
        assert word in html


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
    assert scanner.divergence_lines({"div": {"pos": ["4 saat"], "neg": []}}) == ["🟢 RSI pozitif uyumsuzluk: 4 saat"]
    assert scanner.divergence_lines({"div": {"pos": [], "neg": []}}) == []


def test_volume_profile():
    h = [102] * 50 + [110] * 5 + [95.5] * 5
    l = [100] * 50 + [108] * 5 + [94] * 5
    v = [100] * 50 + [5] * 5 + [5] * 5
    vah, poc, val = ta.volume_profile(h, l, v)
    assert 100 <= poc <= 102 and val <= 100.01 and vah >= 101.99 and val < poc < vah


def test_volume_lines():
    cfg = scanner.load_json(scanner.CONFIG_PATH, None)
    n = 30
    f = {"o": [100.0] * n, "c": [100.5] * n, "v": [1.0] * n, "vol_ma": [1.0] * n, "atr": [1.0] * n}
    f["c"][-1], f["v"][-1] = 103.0, 4.2
    out = scanner.volume_lines({"f": f, "i": n - 1}, cfg)
    assert "Yüksek" in out[0] and any("Büyük yükseliş" in x for x in out) and any("patlaması" in x for x in out)
    f["c"][-1], f["v"][-1] = 100.2, 0.6
    out = scanner.volume_lines({"f": f, "i": n - 1}, cfg)
    assert "Düşük" in out[0] and len(out) == 1


def test_technical_rating():
    v = lambda b, s_, z: [("x", 1)] * b + [("x", -1)] * s_ + [("x", 0)] * z
    assert scanner.technical_rating(v(15, 1, 1))[0] == "GÜÇLÜ AL"
    assert scanner.technical_rating(v(10, 5, 2))[0] == "AL"
    assert scanner.technical_rating(v(8, 8, 1))[0] == "NÖTR"
    assert scanner.technical_rating(v(5, 10, 2))[0] == "SAT"
    assert scanner.technical_rating(v(1, 15, 1))[0] == "GÜÇLÜ SAT"


def test_cmf_ewo():
    h = [101 + k for k in range(60)]; l = [99 + k for k in range(60)]; c = [100.9 + k for k in range(60)]
    assert ta.cmf(h, l, c, [10] * 60)[-1] > 0.5 and ta.ewo(c)[-1] > 0
    c2 = [99.1 + k for k in range(60)]
    assert ta.cmf(h, l, c2, [10] * 60)[-1] < -0.5


def test_wavetrend():
    import math
    c = [100 + 10 * math.sin(k / 8) for k in range(200)]
    h, l = [x + 0.5 for x in c], [x - 0.5 for x in c]
    wt1, wt2 = ta.wavetrend(h, l, c)
    # yükselen bölümde WT1 > WT2, düşen bölümde WT1 < WT2 olmalı (çoğunlukla)
    rising = [k for k in range(80, 200) if c[k] > c[k - 1] and c[k - 1] > c[k - 2]]
    agree = sum(1 for k in rising if wt1[k] > wt2[k]) / len(rising)
    assert agree > 0.7, agree
    assert all(-150 < x < 150 for x in wt1[60:])


def test_market_status():
    from datetime import datetime, timezone
    assert scanner.us_market_status(datetime(2026, 11, 14, 15, 0, tzinfo=timezone.utc)) == "weekend"
    assert scanner.us_market_status(datetime(2026, 11, 11, 15, 0, tzinfo=timezone.utc)) == "open"
    assert scanner.us_market_status(datetime(2026, 11, 11, 23, 0, tzinfo=timezone.utc)) == "closed"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("OK", name)
