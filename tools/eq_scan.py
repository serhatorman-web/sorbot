import os, sys, json, time, statistics as stt
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as sc
import indicators as ta
from backtest import simulate
api = sc.Binance()
now_ms = int(time.time() * 1000)
TFS = {"15m": (2000, 96), "1h": (2000, 72), "4h": (1000, 42)}


def hist(sym, tf, bars):
    out, end = [], None
    while len(out) < bars:
        p = {"symbol": sym, "interval": tf, "limit": 1000}
        if end: p["endTime"] = end
        raw = api.get("/fapi/v1/klines", p)
        if not raw: break
        out = sc.parse_klines(raw, now_ms) + out
        end = int(raw[0][0]) - 1
        if len(raw) < 1000: break
    d = {c["t"]: c for c in out}
    return [d[k] for k in sorted(d)]


def st_trades(cs, hold):
    h = [c["h"] for c in cs]; l = [c["l"] for c in cs]; c = [x["c"] for x in cs]
    if len(c) < 300: return []
    st, _ = ta.supertrend(h, l, c, 10, 3.0); atr = ta.atr(h, l, c, 14)
    f = {"h": h, "l": l, "c": c}; out = []
    for i in range(250, len(c) - 1):
        if st[i] and st[i - 1] and st[i] != st[i - 1] and atr[i]:
            r = simulate(f, i, st[i], 1.5 * atr[i], hold)
            if r: out.append(r["R"] - 0.10 / r["risk_pct"])
    return out


def run(sym):
    res = {"sym": sym}
    try:
        cs = hist(sym, "1h", 2000)
        days = {}
        for c in cs:
            k = c["t"] // 86_400_000
            d = days.setdefault(k, [c["h"], c["l"], c["c"], 0.0]); d[0] = max(d[0], c["h"]); d[1] = min(d[1], c["l"]); d[2] = c["c"]; d[3] += c["v"]
        dl = [days[k] for k in sorted(days)][-31:-1]
        res["days"] = len(days)
        res["vol30"] = stt.median([d[3] for d in dl]) if dl else 0
        res["rng"] = stt.mean([(d[0] - d[1]) / d[2] * 100 for d in dl if d[2]]) if dl else 0
        for tf, (bars, hold) in TFS.items():
            res[tf] = st_trades(cs if tf == "1h" else hist(sym, tf, bars), hold)
    except Exception as e:  # noqa: BLE001
        res["err"] = str(e)
    return res


info = api.get("/fapi/v1/exchangeInfo")
eq = [s for s in info["symbols"] if s.get("quoteAsset") == "USDT" and s.get("status") == "TRADING"
      and s.get("contractType") in ("PERPETUAL", "TRADIFI_PERPETUAL") and s.get("underlyingType") == "EQUITY"]
sub = {s["symbol"]: s.get("underlyingSubType") for s in eq}
with ThreadPoolExecutor(6) as ex:
    rows = list(ex.map(run, [s["symbol"] for s in eq]))
for r in rows:
    r["sub"] = sub[r["sym"]]
print("JSON " + json.dumps(rows))
