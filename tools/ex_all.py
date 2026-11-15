"""Geçici: son günlerde gerçekleşmiş erken dönüş (LONG ve SHORT, şimdiki zorunlu teyitlerle) mesajları, o anki verilerle."""
import sys, os, json, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as sc, indicators as ta
api = sc.Binance()
base = json.load(open("config.json"))
er = base["early_reversal"]
tick = {t["symbol"]: t for t in api.get("/fapi/v1/ticker/24hr")}
info = {s["symbol"]: s for s in api.get("/fapi/v1/exchangeInfo")["symbols"]}
syms = [s for s, t in sorted(tick.items(), key=lambda kv: -float(kv[1]["quoteVolume"]))
        if s in info and info[s].get("underlyingType") == "COIN" and float(tick[s]["quoteVolume"]) >= 3e6][:250]
now = int(time.time() * 1000)
found = {}
for tf in ("1h", "4h", "15m"):
    cfg = sc.apply_tf_profile(base, tf) if tf != "1h" else dict(base)
    btc_all = sc.parse_klines(api.get("/fapi/v1/klines", {"symbol": "BTCUSDT", "interval": tf, "limit": 499}), now)
    bfa = sc.compute_features(btc_all, cfg)
    for sym in syms:
        if "long" in found and "short" in found: break
        cs = sc.parse_klines(api.get("/fapi/v1/klines", {"symbol": sym, "interval": tf, "limit": 499}), now)
        if len(cs) < 400: continue
        f = sc.compute_features(cs, cfg)
        for i in range(len(cs) - 1, len(cs) - 80, -1):
            for d, s_ in (("long", 1), ("short", -1)):
                if d in found: continue
                r = er["rules"][tf][d]
                ev = ta.early_reversal(f["o"][:i+1], f["h"][:i+1], f["l"][:i+1], f["c"][:i+1], f["v"][:i+1], f["atr"][:i+1],
                                       f["vol_ma"][:i+1], f["rsi"][:i+1], s_, er["window"], r["body_atr"], r["vol_x"], r["rsi_th"])
                if not ev or abs(f["c"][i] - ev["ext"]) + 0.2 * f["atr"][i] > er["max_risk_atr"] * f["atr"][i]: continue
                bi = next((k for k, t in enumerate(bfa["t"]) if t == f["t"][i]), None)
                if bi is None: continue
                bf = {"c": bfa["c"][:bi + 1], "st_dir": bfa["st_dir"][:bi + 1]}
                fi = {k: (v[:i + 1] if isinstance(v, list) else v) for k, v in f.items()}
                crit = sc.early_criteria(fi, i, s_, ev, None if sym == "BTCUSDT" else bf)
                if all(crit.get(k) is True for k in r["require"]):
                    ev["criteria"] = crit
                    found[d] = (tf, sym, cs[:i + 1], ev)
orig_get = sc.Binance.get
for d in ("long", "short"):
    if d not in found:
        print(f"\n===== {d}: son günlerde bulunamadı"); continue
    tf, sym, cs, ev = found[d]
    cfg = sc.apply_tf_profile(base, tf) if tf != "1h" else dict(base)
    t_end = cs[-1]["t"] + sc.tf_ms(cfg)
    def get(self, path, params=None, retries=3, _t=t_end):
        p = dict(params or {})
        if path == "/fapi/v1/klines" and "endTime" not in p and "startTime" not in p:
            p["endTime"] = _t - 1
        return orig_get(self, path, p, retries)
    sc.Binance.get = get
    bc = sc.parse_klines(api.get("/fapi/v1/klines", {"symbol": "BTCUSDT", "interval": tf, "limit": 499}), t_end)
    bfx = sc.compute_features(bc, cfg)
    ctx = {"leaders": {"COIN": {"symbol": "BTCUSDT", "bias": sc.trend_bias(bfx), "ret24": 0}}, "funding": {},
           "tickers": {sym: {"qv": float(tick[sym]["quoteVolume"]), "chg": 0}},
           "now_utc": sc.datetime.fromtimestamp(t_end / 1000, sc.timezone.utc)}
    meta = {"symbol": sym, "type": "COIN", "precision": sc.tick_decimals(info[sym])}
    r = sc.analyze_symbol(meta, cs, ctx, cfg)
    r["early"] = dict(ev, dir=d)
    sc.fetch_tf_trends(api, r, t_end, tf)
    sc.compute_volume_profile(r, cfg)
    print("\n===== ERKEN " + d)
    print(sc.build_message(r, d, cfg, ctx["now_utc"]))
    sc.Binance.get = orig_get
