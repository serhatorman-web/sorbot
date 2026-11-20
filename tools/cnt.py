import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as S

base = json.load(open(S.CONFIG_PATH, encoding="utf-8"))
api = S.Binance()
u1, *_ = S.build_universe(api, base)
b2 = json.loads(json.dumps(base)); b2["universe"]["watchlist_only"] = False
u2, *_ = S.build_universe(api, b2)
qv = {t["symbol"]: float(t["quoteVolume"]) for t in api.get("/fapi/v1/ticker/24hr")}
s1 = {m["symbol"] for m in u1}
extra = sorted((m for m in u2 if m["symbol"] not in s1), key=lambda m: -qv.get(m["symbol"], 0))
print("XX| toplam", len(extra))
for m in extra:
    print("XX|", m["symbol"], m["type"], round(qv.get(m["symbol"], 0) / 1e6, 1))
