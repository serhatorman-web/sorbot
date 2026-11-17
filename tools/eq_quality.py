import json, time
from concurrent.futures import ThreadPoolExecutor
import scanner

cfg = json.load(open("config.json"))
wl = set(cfg["universe"]["tradingview_watchlist"])
api = scanner.Binance()
info = api.get("/fapi/v1/exchangeInfo")
tk = {t["symbol"]: t for t in api.get("/fapi/v1/ticker/24hr")}
bt = {t["symbol"]: t for t in api.get("/fapi/v1/ticker/bookTicker")}
eq = [(s["symbol"], s.get("underlyingType"), s.get("onboardDate")) for s in info["symbols"]
      if s["symbol"] in wl and s.get("underlyingType") in ("EQUITY", "KR_EQUITY", "HK_EQUITY")]


def one(c):
    sym, typ, ob = c
    t = tk.get(sym, {})
    last = float(t.get("lastPrice") or 0)
    d = {"s": sym, "typ": typ, "age": round((time.time() * 1000 - (ob or 0)) / 864e5),
         "qv": float(t.get("quoteVolume") or 0)}
    b = bt.get(sym, {})
    try:
        bid, ask = float(b["bidPrice"]), float(b["askPrice"])
        d["spr"] = round((ask - bid) / ((ask + bid) / 2) * 1e4, 2)
    except Exception:
        d["spr"] = None
    try:
        d["oi"] = float(api.get("/fapi/v1/openInterest", {"symbol": sym})["openInterest"]) * last
    except Exception:
        d["oi"] = None
    try:
        k = api.get("/fapi/v1/klines", {"symbol": sym, "interval": "1d", "limit": 31})
        qvs = [float(x[7]) for x in k[:-1]]
        d["qv30"] = sum(qvs) / len(qvs) if qvs else 0
        d["qvmin"] = min(qvs) if qvs else 0
        trs = []
        for i in range(1, len(k)):
            h, l, pc = float(k[i][2]), float(k[i][3]), float(k[i - 1][4])
            trs.append(max(h - l, abs(h - pc), abs(l - pc)) / pc * 100)
        d["atr"] = round(sum(trs[-14:]) / len(trs[-14:]), 2) if trs else None
        d["r30"] = round((float(k[-1][4]) / float(k[0][4]) - 1) * 100, 1)
        d["days"] = len(k)
    except Exception:
        d["qv30"] = d["qvmin"] = 0
        d["atr"] = d["r30"] = d["days"] = None
    try:
        m = api.get("/fapi/v1/klines", {"symbol": sym, "interval": "15m", "limit": 96})
        d["empty15"] = sum(1 for x in m if float(x[2]) == float(x[3])) / len(m)
    except Exception:
        d["empty15"] = None
    return d


with ThreadPoolExecutor(6) as ex:
    rows = list(ex.map(one, eq))
print("JSONOUT" + json.dumps(rows))
