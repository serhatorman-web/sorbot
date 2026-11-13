import os, sys, time
from datetime import datetime, timezone, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as sc, indicators as ta
api = sc.Binance()
now_ms = int(time.time() * 1000)
TR = timezone(timedelta(hours=3))
for sym in ["XAUUSDT", "XAGUSDT", "XPTUSDT", "XPDUSDT", "CLUSDT", "BZUSDT", "NATGASUSDT", "COPPERUSDT"]:
    out = []
    for tf in ("15m", "1h"):
        cs = sc.parse_klines(api.get("/fapi/v1/klines", {"symbol": sym, "interval": tf, "limit": 499}), now_ms)
        h = [x["h"] for x in cs]; l = [x["l"] for x in cs]; c = [x["c"] for x in cs]
        col, line = ta.trendflex(h, l, c)
        sma = ta.sma(c, 13)
        sigs = [(i, ta.trendflex_signal(c, line, sma, i)) for i in range(len(c))]
        sigs = [(datetime.fromtimestamp(cs[i]["t"] / 1000 + (900 if tf == "15m" else 3600), TR).strftime("%d %H:%M"), "AL" if v == 1 else "SAT")
                for i, v in sigs if v and cs[i]["t"] > now_ms - 48 * 3600 * 1000]
        out.append(f"{tf}: renk {'🟢' if col[-1] == 1 else '🔴'} · 48s etiket {len(sigs)} {sigs[-3:]}")
    print(f"{sym:<11} " + " | ".join(out))
