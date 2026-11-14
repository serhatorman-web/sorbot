"""Geçici teşhis: Ichimoku bölümü gerçek veriyle."""
import sys, os, time, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as sc
cfg0 = json.load(open("config.json"))
api = sc.Binance(); now = int(time.time() * 1000)
for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ZROUSDT", "QQQUSDT", "XAUUSDT"):
    for tf in ("15m", "1h", "4h"):
        cfg = dict(cfg0, timeframe=tf)
        raw = api.get("/fapi/v1/klines", {"symbol": sym, "interval": tf, "limit": 300})
        cs = sc.parse_klines(raw, now)
        f = sc.compute_features(cs, cfg); i = len(cs) - 1
        res = {"f": f, "i": i, "meta": {"symbol": sym, "precision": 1 if sym == "BTCUSDT" else 4}}
        for d in ("long", "short"):
            lines = sc.ichimoku_lines(res, d, cfg)
            print(f"=== {sym} {tf} {d.upper()} close={f['c'][i]} T={f['ichi_tenkan'][i]} K={f['ichi_kijun'][i]}")
            print("\n".join(lines[1:] if d == "short" else lines))
