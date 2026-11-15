import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as sc
api = sc.Binance()
info = api.get("/fapi/v1/exchangeInfo")
tick = {t["symbol"]: float(t["quoteVolume"]) for t in api.get("/fapi/v1/ticker/24hr")}
eq = sorted(((tick.get(s["symbol"], 0), s["symbol"]) for s in info["symbols"]
             if s.get("quoteAsset") == "USDT" and s.get("status") == "TRADING"
             and s.get("contractType") in ("PERPETUAL", "TRADIFI_PERPETUAL") and s.get("underlyingType") == "EQUITY"), reverse=True)
print("TOPLAM", len(eq))
for th in (100e3, 1e6, 3e6, 5e6, 10e6):
    print(f"ESIK {th/1e6:g}M {sum(1 for v, _ in eq if v >= th)}")
for v, s in eq:
    print(f"SYM {s} {v/1e6:.2f}")
