import sys, os, json, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as sc
api = sc.Binance(); cfg = json.load(open("config.json"))
u, allm, tickers, funding = sc.build_universe(api, cfg)
print("EVAA evrende mi:", any(m["symbol"] == "EVAAUSDT" for m in u), "hacim", tickers.get("EVAAUSDT"))
now = 1795136400000 + 28000   # 01:00:28 UTC
for sym in ("EVAAUSDT", "KOMAUSDT"):
    raw = api.get("/fapi/v1/klines", {"symbol": sym, "interval": "1h", "limit": 499, "endTime": now})
    cs = sc.parse_klines(raw, now)
    f = sc.compute_features(cs, cfg); i = len(cs) - 1
    import datetime as dt
    print(sym, len(cs), "son mum", dt.datetime.utcfromtimestamp(cs[-1]["t"]/1000), "st", f["st_dir"][i-1], f["st_dir"][i], "min_candles", cfg["min_candles"])
