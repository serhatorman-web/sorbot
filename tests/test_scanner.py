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
