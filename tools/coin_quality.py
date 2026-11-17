import json, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
import scanner

cfg = json.load(open("config.json"))
wl = set(cfg["universe"]["tradingview_watchlist"])
api = scanner.Binance()
info = api.get("/fapi/v1/exchangeInfo")
tk = {t["symbol"]: t for t in api.get("/fapi/v1/ticker/24hr")}
bt = {t["symbol"]: t for t in api.get("/fapi/v1/ticker/bookTicker")}
try:
    spot = {x["baseAsset"] for x in api.get("/api/v3/exchangeInfo")["symbols"]
            if x.get("status") == "TRADING" and x.get("quoteAsset") == "USDT"}
except Exception as e:
    spot = None
    print("spot err", e)
coins = [(s["symbol"], s.get("onboardDate"), s.get("baseAsset")) for s in info["symbols"]
         if s["symbol"] in wl and s.get("underlyingType") == "COIN"]


def one(c):
    sym, ob, base = c
    t = tk.get(sym, {})
    last = float(t.get("lastPrice") or 0)
    d = {"s": sym, "base": base, "age": round((time.time() * 1000 - (ob or 0)) / 864e5),
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
        trs = []
        for i in range(1, len(k)):
            h, l, pc = float(k[i][2]), float(k[i][3]), float(k[i - 1][4])
            trs.append(max(h - l, abs(h - pc), abs(l - pc)) / pc * 100)
        d["atr"] = round(sum(trs[-14:]) / len(trs[-14:]), 2) if trs else None
    except Exception:
        d["qv30"], d["atr"] = 0, None
    try:
        m = api.get("/fapi/v1/klines", {"symbol": sym, "interval": "15m", "limit": 96})
        d["empty15"] = sum(1 for x in m if float(x[2]) == float(x[3])) / len(m)
    except Exception:
        d["empty15"] = None
    b2 = base.removeprefix("1000000").removeprefix("1000")
    d["spot"] = None if spot is None else (base in spot or b2 in spot)
    return d


with ThreadPoolExecutor(6) as ex:
    rows = list(ex.map(one, coins))
cg = {}
try:
    for page in (1, 2):
        url = ("https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd"
               f"&order=market_cap_desc&per_page=250&page={page}")
        req = urllib.request.Request(url, headers={"User-Agent": "sorbot"})
        for x in json.load(urllib.request.urlopen(req, timeout=30)):
            cg.setdefault(x["symbol"].upper(), (x["market_cap_rank"], x["name"]))
        time.sleep(2)
except Exception as e:
    print("cg err", e)
for d in rows:
    b = d["base"].removeprefix("1000000").removeprefix("1000")
    d["rank"], d["name"] = cg.get(b, (None, None))
print("JSONOUT" + json.dumps(rows))
