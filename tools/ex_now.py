"""Geçici: BTCUSDT 15dk / 1s / 4s için şu anki verilerle bot mesajı (yön = şu anki Supertrend yönü) + pivot kontrolü."""
import sys, os, json, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as sc
api = sc.Binance()
base = json.load(open("config.json"))
info = {s["symbol"]: s for s in api.get("/fapi/v1/exchangeInfo")["symbols"]}
tick = {t["symbol"]: t for t in api.get("/fapi/v1/ticker/24hr")}
now = int(time.time() * 1000)
sym = "BTCUSDT"
for tf in ("15m",):
    cfg = sc.apply_tf_profile(base, tf) if tf != "1h" else dict(base)
    cs = sc.parse_klines(api.get("/fapi/v1/klines", {"symbol": sym, "interval": tf, "limit": 499}), now)
    ctx = {"leaders": {"COIN": {"symbol": sym, "bias": 0, "ret24": 0}}, "funding": {},
           "tickers": {sym: {"qv": float(tick[sym]["quoteVolume"]), "chg": float(tick[sym]["priceChangePercent"])}},
           "now_utc": sc.datetime.fromtimestamp(now / 1000, sc.timezone.utc)}
    meta = {"symbol": sym, "type": "COIN", "precision": sc.tick_decimals(info[sym])}
    r = sc.analyze_symbol(meta, cs, ctx, cfg)
    sc.fetch_tf_trends(api, r, now, tf, order_blocks=False)
    sc.compute_volume_profile(r, cfg)
    f, i = r["f"], r["i"]
    d = "long" if f["st_dir"][i] == 1 else "short"
    k = i
    while k > 0 and f["st_dir"][k - 1] == f["st_dir"][i]:
        k -= 1
    pv = r.get("pivot")
    print(f"\n===== {tf} · son kapanmış mum {sc.datetime.fromtimestamp(f['t'][i]/1000, sc.timezone.utc)} UTC · "
          f"Supertrend {d} ({i-k} mum önce döndü) · pivot tf={pv and pv['tf']} P={pv and round(pv['P'], 2)} "
          f"R1={pv and round(pv['R1'], 2)} S1={pv and round(pv['S1'], 2)}")
    print(sc.build_message(r, d, cfg, ctx["now_utc"]))
