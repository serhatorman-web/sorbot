"""Geçici: son günlerde gerçekleşmiş bir Pump/Dump radar sinyali (tercihen CRWDUSDT 1s) mesajı, o anki verilerle."""
import sys, os, json, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as sc
api = sc.Binance()
cfg = json.load(open("config.json"))
info = {s["symbol"]: s for s in api.get("/fapi/v1/exchangeInfo")["symbols"]}
tick = {t["symbol"]: t for t in api.get("/fapi/v1/ticker/24hr")}
now = int(time.time() * 1000)
bars_day = 24
cands = ["CRWDUSDT"] + [s for s, t in sorted(tick.items(), key=lambda kv: -float(kv[1]["quoteVolume"]))
                        if s in info and s != "CRWDUSDT"][:60]
found = None
for sym in cands:
    if sym not in info:
        continue
    cs = sc.parse_klines(api.get("/fapi/v1/klines", {"symbol": sym, "interval": "1h", "limit": 499}), now)
    if len(cs) < 400:
        continue
    f = sc.compute_features(cs, cfg)
    for i in range(len(cs) - 1, len(cs) - 120, -1):
        chg24 = (f["c"][i] / f["c"][i - bars_day] - 1) * 100
        pdres = sc.pump_dump_analysis(f, cfg, chg24, i)
        rds = sc.pump_radar(f, i, pdres, chg24, cfg)
        if rds:
            found = (sym, cs[:i + 1], rds[0], chg24)
            break
    if found:
        break
sym, cs, rd, chg24 = found
t_end = cs[-1]["t"] + 3600_000
orig = sc.Binance.get
def get(self, path, params=None, retries=3):
    p = dict(params or {})
    if path == "/fapi/v1/klines" and "endTime" not in p and "startTime" not in p:
        p["endTime"] = t_end - 1
    return orig(self, path, p, retries)
sc.Binance.get = get
bc = sc.parse_klines(api.get("/fapi/v1/klines", {"symbol": "BTCUSDT", "interval": "1h", "limit": 499}), t_end)
bfx = sc.compute_features(bc, cfg)
typ = "COIN" if info[sym].get("underlyingType") == "COIN" else "EQUITY"
ctx = {"leaders": {"COIN": {"symbol": "BTCUSDT", "bias": sc.trend_bias(bfx), "ret24": 0}}, "funding": {},
       "tickers": {sym: {"qv": float(tick[sym]["quoteVolume"]), "chg": chg24}},
       "now_utc": sc.datetime.fromtimestamp(t_end / 1000, sc.timezone.utc)}
meta = {"symbol": sym, "type": typ, "precision": sc.tick_decimals(info[sym])}
r = sc.analyze_symbol(meta, cs, ctx, cfg)
sc.fetch_tf_trends(api, r, t_end, "1h", order_blocks=False)
sc.compute_volume_profile(r, cfg)
print("===== RADAR", sym, typ, rd["kind"], rd["dir"])
print(sc.build_radar_message(r, rd, cfg, ctx["now_utc"]))
print("===== SON")
