import sys, os, json, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as sc
from datetime import datetime, timezone
api = sc.Binance(); cfg = json.load(open("config.json"))
T = (1794704400 + 28) * 1000
meta = {"symbol": "EVAAUSDT", "type": "COIN", "precision": 4}
raw = api.get("/fapi/v1/klines", {"symbol": "EVAAUSDT", "interval": "1h", "limit": cfg["kline_limit"], "endTime": T})
cs = sc.parse_klines(raw, T)
ctx = {"leaders": {}, "funding": {}, "tickers": {}, "now_utc": datetime.now(timezone.utc)}
r = sc.analyze_symbol(meta, cs, ctx, cfg)
print("analiz:", r is not None, "mum", len(cs))
if r:
    print("short", r["short"]["triggers"], r["short"]["score"], "long", r["long"]["triggers"])
    print("decide:", sc.decide(r, cfg, {"signals": {}}, time.time()))
    print("required_ready:", sc.required_ready(r["f"]))
else:
    f = sc.compute_features(cs, cfg)
    print("required_ready:", sc.required_ready(f))
    for k, v in f.items():
        if isinstance(v, list) and v and v[-1] is None: print("  None:", k)
