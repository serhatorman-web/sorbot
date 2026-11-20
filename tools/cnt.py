import json, os, statistics as st, sys, time
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as S

base = json.load(open(S.CONFIG_PATH, encoding="utf-8"))
api = S.Binance()
u1, *_ = S.build_universe(api, base)
b2 = json.loads(json.dumps(base)); b2["universe"]["watchlist_only"] = False
u2, *_ = S.build_universe(api, b2)
s1 = {m["symbol"] for m in u1}
now_ms = int(time.time() * 1000)


def info(m):
    raw = api.get("/fapi/v1/klines", {"symbol": m["symbol"], "interval": "1d", "limit": 31})
    cs = S.parse_klines(raw, now_ms)[-30:]
    if not cs:
        return None
    rng = [(x["h"] - x["l"]) / x["o"] * 100 for x in cs if x["o"]]
    return (m["symbol"], m["type"], len(cs), st.median([x["v"] for x in cs]) / 1e6, st.median(rng),
            m["symbol"] in s1)


with ThreadPoolExecutor(max_workers=8) as ex:
    rows = [r for r in ex.map(info, u2) if r]
for r in rows:
    print("XX|", "|".join(str(round(x, 2)) if isinstance(x, float) else str(x) for x in r))
