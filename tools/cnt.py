import json, os, sys, time
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as S
import indicators as ta

base = json.load(open(S.CONFIG_PATH, encoding="utf-8"))
api = S.Binance()
u1, all_meta, tick, _ = S.build_universe(api, base)
b2 = json.loads(json.dumps(base)); b2["universe"]["watchlist_only"] = False
u2, *_ = S.build_universe(api, b2)
print("XX| evren: liste", len(u1), {t: sum(1 for m in u1 if m["type"] == t) for t in ("COIN", "EQUITY", "COMMODITY")},
      "| tüm (hacim>=3M)", len(u2), {t: sum(1 for m in u2 if m["type"] == t) for t in ("COIN", "EQUITY", "COMMODITY")})
wl = base["universe"]["tradingview_watchlist"]
missing = [s for s in wl if s not in {m["symbol"] for m in u1}]
print("XX| listede olup taranmayan:", len(missing), " ".join(missing))
now_ms = int(time.time() * 1000)
DAYS = 3


def flips(sym, tf, per_day):
    raw = api.get("/fapi/v1/klines", {"symbol": sym, "interval": tf, "limit": min(1500, per_day * DAYS + 300)})
    cs = S.parse_klines(raw, now_ms)
    h = [x["h"] for x in cs]; l = [x["l"] for x in cs]; c = [x["c"] for x in cs]
    out = {}
    for p in ((10, 3), (10, 2), (7, 2)):
        d, _ = ta.supertrend(h, l, c, *p)
        lo = len(c) - per_day * DAYS
        out[p] = sum(1 for i in range(lo, len(c)) if d[i] and d[i - 1] and d[i] != d[i - 1])
    return out


for tf, pd in (("15m", 96), ("30m", 48), ("1h", 24), ("4h", 6)):
    for nm, uni in (("liste", u1), ("tüm", u2)):
        tot = {}
        with ThreadPoolExecutor(max_workers=8) as ex:
            for r in ex.map(lambda m: flips(m["symbol"], tf, pd), uni):
                for k, v in r.items():
                    tot[k] = tot.get(k, 0) + v
        print("XX|", tf, nm, "günlük dönüş:", {f"ST{k[0]}/{k[1]}": round(v / DAYS) for k, v in tot.items()})
