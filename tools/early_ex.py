"""Geçici: son günlerde gerçekleşmiş erken dönüş anlarının (1s LONG ve SHORT) mesajını o anki verilerle oluştur."""
import sys, os, json, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as sc, indicators as ta
api = sc.Binance()
cfg = json.load(open("config.json")); tf = "1h"
er = cfg["early_reversal"]; rules = er["rules"][tf]
tick = {t["symbol"]: t for t in api.get("/fapi/v1/ticker/24hr")}
info = {s["symbol"]: s for s in api.get("/fapi/v1/exchangeInfo")["symbols"]}
syms = [s for s, t in sorted(tick.items(), key=lambda kv: -float(kv[1]["quoteVolume"]))
        if s in info and info[s].get("underlyingType") == "COIN" and float(tick[s]["quoteVolume"]) >= 5e6][:150]
now = int(time.time() * 1000)
found = {}
btc = sc.parse_klines(api.get("/fapi/v1/klines", {"symbol": "BTCUSDT", "interval": tf, "limit": 499}), now)
for sym in syms:
    if len(found) == 2: break
    cs = sc.parse_klines(api.get("/fapi/v1/klines", {"symbol": sym, "interval": tf, "limit": 499}), now)
    if len(cs) < 400: continue
    f = sc.compute_features(cs, cfg)
    for i in range(len(cs) - 1, len(cs) - 72, -1):
        for d, s_ in (("long", 1), ("short", -1)):
            if d in found: continue
            r = rules[d]
            ev = ta.early_reversal(f["o"][:i+1], f["h"][:i+1], f["l"][:i+1], f["c"][:i+1], f["v"][:i+1], f["atr"][:i+1],
                                   f["vol_ma"][:i+1], f["rsi"][:i+1], s_, er["window"], r["body_atr"], r["vol_x"], r["rsi_th"])
            if ev and abs(f["c"][i] - ev["ext"]) + 0.2 * f["atr"][i] <= er["max_risk_atr"] * f["atr"][i]:
                found[d] = (sym, cs[:i+1], ev)
orig_get = sc.Binance.get
for d, (sym, cs, ev) in found.items():
    t_end = cs[-1]["t"] + sc.tf_ms(cfg)
    def get(self, path, params=None, retries=3, _t=t_end):
        p = dict(params or {})
        if path == "/fapi/v1/klines" and "endTime" not in p and "startTime" not in p:
            p["endTime"] = _t - 1
        return orig_get(self, path, p, retries)
    sc.Binance.get = get
    bc = [c for c in btc if c["t"] + sc.tf_ms(cfg) <= t_end]
    bf = sc.compute_features(bc, cfg)
    leaders = {"COIN": {"symbol": "BTCUSDT", "bias": sc.trend_bias(bf), "ret24": 0}}
    ctx = {"leaders": leaders, "funding": {}, "tickers": {sym: {"qv": float(tick[sym]["quoteVolume"]), "chg": 0}},
           "now_utc": sc.datetime.fromtimestamp(t_end / 1000, sc.timezone.utc)}
    meta = {"symbol": sym, "type": "COIN", "precision": sc.tick_decimals(info[sym])}
    r = sc.analyze_symbol(meta, cs, ctx, cfg)
    r["early"] = dict(ev, dir=d)
    sc.fetch_tf_trends(api, r, t_end, tf)
    sc.compute_volume_profile(r, cfg)
    print("\n" + "=" * 60 + f"\n{d}")
    print(sc.build_message(r, d, cfg, ctx["now_utc"]))
    sc.Binance.get = orig_get
