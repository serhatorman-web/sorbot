"""Geçici: son günlerde gerçekleşmiş bir erken dönüş anını bulup botun mesajını o anki verilerle oluştur."""
import sys, os, json, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as sc, indicators as ta
api = sc.Binance()
base = json.load(open("config.json"))
found = {}
tick = api.get("/fapi/v1/ticker/24hr")
info = {s["symbol"]: s for s in api.get("/fapi/v1/exchangeInfo")["symbols"]}
syms = [t["symbol"] for t in sorted(tick, key=lambda t: -float(t["quoteVolume"])) if t["symbol"] in info
        and info[t["symbol"]].get("underlyingType") == "COIN" and float(t["quoteVolume"]) >= 5e6][:80]
now = int(time.time() * 1000)
for tf in ("1h", "15m"):
    cfg = sc.apply_tf_profile(base, tf) if tf != "1h" else dict(base)
    rules = cfg["early_reversal"]["rules"][tf]
    for sym in syms:
        if (tf, "long") in found and (tf, "short") in found: break
        cs = sc.parse_klines(api.get("/fapi/v1/klines", {"symbol": sym, "interval": tf, "limit": 499}), now)
        f = sc.compute_features(cs, cfg)
        for i in range(len(cs) - 1, len(cs) - 60, -1):
            for d, s_ in (("long", 1), ("short", -1)):
                if (tf, d) in found: continue
                r = rules[d]
                ev = ta.early_reversal(f["o"][:i+1], f["h"][:i+1], f["l"][:i+1], f["c"][:i+1], f["v"][:i+1], f["atr"][:i+1],
                                       f["vol_ma"][:i+1], f["rsi"][:i+1], s_, 8, r["body_atr"], r["vol_x"], r["rsi_th"])
                if ev:
                    found[(tf, d)] = (sym, i, cs[:i+1], ev)
for (tf, d), (sym, i, cs, ev) in found.items():
    cfg = sc.apply_tf_profile(base, tf) if tf != "1h" else dict(base)
    meta = {"symbol": sym, "type": "COIN", "precision": sc.tick_decimals(info[sym])}
    ctx = {"leaders": {}, "funding": {}, "tickers": {}, "now_utc": sc.datetime.now(sc.timezone.utc)}
    r = sc.analyze_symbol(meta, cs, ctx, cfg)
    r["early"] = dict(ev, dir=d)
    t_end = cs[-1]["t"] + sc.tf_ms(cfg) + 1
    sc.fetch_tf_trends(api, r, t_end, tf)
    sc.compute_volume_profile(r, cfg)
    print("\n" + "=" * 60 + f"\n{tf} {d}")
    print(sc.build_message(r, d, cfg, ctx["now_utc"]))
