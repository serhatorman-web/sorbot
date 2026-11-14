"""Geçici teşhis: UNH – botun kodu ile."""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as sc
api = sc.Binance(); cfg = dict(json.load(open("config.json")), timeframe="15m")
info = {s["symbol"]: s for s in api.get("/fapi/v1/exchangeInfo")["symbols"]}
prec = sc.tick_decimals(info["UNHUSDT"])
allc = sc.parse_klines(api.get("/fapi/v1/klines", {"symbol": "UNHUSDT", "interval": "15m", "limit": 499}), 10**15)
for end in (1794689100000, 1794690000000):        # 20:45 UTC (sinyal) ve 21:00 UTC kapanış
    cs = [c for c in allc if c["t"] + 900000 <= end]
    f = sc.compute_features(cs, cfg); i = len(cs) - 1
    res = {"f": f, "i": i, "meta": {"symbol": "UNHUSDT", "precision": prec}}
    sc.compute_volume_profile(res, cfg)
    print(end, [round(x, 2) for x in res["vp"]], sc.volume_profile_lines(res, cfg))
