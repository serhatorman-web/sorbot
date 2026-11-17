import json
import scanner

cfg = json.load(open("config.json"))
api = scanner.Binance()
uni, all_meta, tickers, _ = scanner.build_universe(api, cfg)
got = {m["symbol"]: m["type"] for m in uni}
wl = cfg["universe"]["tradingview_watchlist"]
by = {}
for t in got.values():
    by[t] = by.get(t, 0) + 1
print("TARANAN", len(got), by)
print("BINANCEDA_YOK", [s for s in wl if s not in all_meta])
print("HACIM_DUSUK", [(s, all_meta[s]["type"], round(tickers.get(s, {}).get("qv", 0))) for s in wl if s in all_meta and s not in got])
print("TIPLER", sorted({(all_meta[s]["type"]) for s in wl if s in all_meta}))
print("US", scanner.us_market_status(__import__("datetime").datetime.now(__import__("datetime").timezone.utc)))
