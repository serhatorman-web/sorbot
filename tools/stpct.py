import sys, os, json, time
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as sc
api = sc.Binance(); base = json.load(open("config.json"))
u, *_ = sc.build_universe(api, base)
now = int(time.time() * 1000)
for tf in ("15m", "1h", "4h"):
    cfg = sc.apply_tf_profile(base, tf) if tf != "1h" else dict(base)
    def one(m):
        cs = sc.parse_klines(api.get("/fapi/v1/klines", {"symbol": m["symbol"], "interval": tf, "limit": 100}), now)
        if len(cs) < 30: return None
        import indicators as ta
        a = ta.atr([x["h"] for x in cs], [x["l"] for x in cs], [x["c"] for x in cs], 14)[-1]
        return (m["symbol"], 1.5 * a / cs[-1]["c"] * 100) if a else None
    with ThreadPoolExecutor(6) as ex:
        vals = sorted([v for v in ex.map(one, u) if v], key=lambda x: x[1])
    p = [v for _, v in vals]; n = len(p)
    q = lambda x: p[min(n - 1, int(x * n))]
    print(f"{tf}: {n} sembol · medyan %{q(0.5):.2f} · %25 {q(0.25):.2f} · %75 {q(0.75):.2f} · %90 {q(0.9):.2f} · en yüksek %{p[-1]:.2f} ({vals[-1][0]}) · %5 üstü {sum(1 for x in p if x > 5)} · BTC %{dict(vals).get('BTCUSDT', 0):.2f} · ETH %{dict(vals).get('ETHUSDT', 0):.2f}", flush=True)
