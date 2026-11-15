import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as sc
api = sc.Binance()
now = int(time.time() * 1000)
for sym in ("BTCUSDT", "ETHUSDT"):
    for tf in ("15m", "1h", "4h"):
        cs = sc.parse_klines(api.get("/fapi/v1/klines", {"symbol": sym, "interval": tf, "limit": 499}), now)
        f = {k: [x[k] for x in cs] for k in ("h", "l", "c", "v", "bv")}
        r = sc.tv_rating({"f": f, "i": len(cs) - 1})
        print("ROW", sym, tf, cs[-1]["t"] // 1000, round(r[4], 4), sc.technical_rating_line([], r))
