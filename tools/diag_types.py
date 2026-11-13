import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as sc
api = sc.Binance()
info = api.get("/fapi/v1/exchangeInfo")
tk = {t["symbol"]: float(t["quoteVolume"]) for t in api.get("/fapi/v1/ticker/24hr")}
from collections import Counter
print(Counter(s.get("underlyingType") for s in info["symbols"] if s.get("status") == "TRADING"))
for s in info["symbols"]:
    if s.get("underlyingType") not in ("COIN", "EQUITY") and s.get("status") == "TRADING":
        print(s["symbol"], s.get("underlyingType"), s.get("contractType"), s.get("underlyingSubType"), f"{tk.get(s['symbol'],0)/1e6:.1f}M")
