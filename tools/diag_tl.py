import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as sc, indicators as ta
api = sc.Binance(); now_ms = int(time.time() * 1000)
syms = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT", "DOGEUSDT", "ADAUSDT", "LINKUSDT", "AVAXUSDT", "SUIUSDT",
        "XAUUSDT", "NVDAUSDT", "TSLAUSDT", "AAPLUSDT", "CRWDUSDT"]
tot = 0
for s in syms:
    row = []
    for tf in sc.DIV_TFS:
        cs = sc.parse_klines(api.get("/fapi/v1/klines", {"symbol": s, "interval": tf, "limit": 150}), now_ms)
        ev = ta.trendline_break([x["h"] for x in cs], [x["l"] for x in cs], [x["c"] for x in cs])
        for e in ev:
            tot += 1
            row.append(f"{tf}:{'YÜK' if e['type']=='rising' else 'DÜŞ'}-kırıldı({e['bars_ago']} mum önce, retest {'var' if e['retest'] else 'yok'})")
    print(f"{s:<10} " + (" | ".join(row) or "-"))
print("toplam olay:", tot, "/", len(syms) * len(sc.DIV_TFS))
