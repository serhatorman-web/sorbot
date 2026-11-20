import json, os, sys, time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as S
import indicators as ta

base = json.load(open(S.CONFIG_PATH, encoding="utf-8"))
api = S.Binance()
u1, *_ = S.build_universe(api, base)
now_ms = int(time.time() * 1000)


def flips(m):
    raw = api.get("/fapi/v1/klines", {"symbol": m["symbol"], "interval": "15m", "limit": 499})
    cs = S.parse_klines(raw, now_ms)
    h = [x["h"] for x in cs]; l = [x["l"] for x in cs]; c = [x["c"] for x in cs]
    d, _ = ta.supertrend(h, l, c, 10, 3.0)
    return [(cs[i]["t"], m["type"]) for i in range(len(c) - 120, len(c)) if d[i] and d[i - 1] and d[i] != d[i - 1]]


by = {}
with ThreadPoolExecutor(max_workers=8) as ex:
    for r in ex.map(flips, u1):
        for t, typ in r:
            k = datetime.fromtimestamp(t / 1000 + 900, timezone.utc).strftime("%d %H")
            by.setdefault(k, {}).setdefault(typ, 0)
            by[k][typ] += 1
for k in sorted(by):
    print("XX|", k, "UTC", by[k], "toplam", sum(by[k].values()))
