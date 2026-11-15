import sys, os, json, time, datetime as dt
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as sc
api = sc.Binance(); base = json.load(open("config.json"))
u, *_ = sc.build_universe(api, base); now = int(time.time() * 1000)
for tf in ("15m", "1h", "4h"):
    cfg = sc.apply_tf_profile(base, tf) if tf != "1h" else dict(base)
    def one(m):
        cs = sc.parse_klines(api.get("/fapi/v1/klines", {"symbol": m["symbol"], "interval": tf, "limit": 300}), now)
        if len(cs) < 250: return []
        f = sc.compute_features(cs, cfg); n = len(cs)
        return [(cs[k]["t"], m["symbol"], f["st_dir"][k]) for k in range(n - 12, n) if f["st_dir"][k] and f["st_dir"][k - 1] and f["st_dir"][k] != f["st_dir"][k - 1]]
    with ThreadPoolExecutor(6) as ex:
        res = [x for r in ex.map(one, u) for x in r]
    by = {}
    for t, s, d in res: by.setdefault(t, []).append(f"{s.replace('USDT','')}{'↑' if d == 1 else '↓'}")
    print(f"=== {tf}: son 12 mumdaki Supertrend dönüşleri (mum açılışı TSİ)")
    for t in sorted(by):
        print("  ", dt.datetime.fromtimestamp(t / 1000 + 3 * 3600, dt.timezone.utc).strftime("%d.%m %H:%M"), len(by[t]), " ".join(by[t][:12]))
