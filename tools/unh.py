"""Geçici teşhis: UNHUSDT 15dk SHORT – hacim profili bölümü."""
import sys, os, json, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as sc, indicators as ta
api = sc.Binance(); cfg = dict(json.load(open("config.json")), timeframe="15m")
info = {s["symbol"]: s for s in api.get("/fapi/v1/exchangeInfo")["symbols"]}
prec = sc.tick_decimals(info["UNHUSDT"])
raw = api.get("/fapi/v1/klines", {"symbol": "UNHUSDT", "interval": "15m", "limit": 499})
allc = sc.parse_klines(raw, 10**15)
for end_utc in ("20:15", "20:30", "20:45", "21:00", "21:15"):
    hh, mm = map(int, end_utc.split(":"))
    end = int(dt.datetime(2026, 11, 14, hh, mm, tzinfo=dt.timezone.utc).timestamp() * 1000)
    cs = [c for c in allc if c["t"] + 900000 <= end]
    if not cs: continue
    f = sc.compute_features(cs, cfg); i = len(cs) - 1
    res = {"f": f, "i": i, "meta": {"symbol": "UNHUSDT", "precision": prec}}
    sc.compute_volume_profile(res, cfg)
    vah, poc, val = res["vp"]
    a = f["atr"][i]
    print(f"\n=== mum kapanışı {end_utc} UTC ({hh+3:02d}:{mm:02d} TSİ)  VAH {vah:.4f} POC {poc:.4f} VAL {val:.4f}  ATR {a:.4f}  st_dir {f['st_dir'][i]}")
    print("   olaylar:", {k: {kk: vv for kk, vv in v.items() if kk != 'level'} for k, v in res["vp_ev"].items()})
    print("   mesaj:", sc.volume_profile_lines(res, cfg))
    for k in range(i - 11, i + 1):
        c = cs[k]; t = dt.datetime.utcfromtimestamp(c["t"] / 1000).strftime("%H:%M")
        print(f"   {t}  o {c['o']:.2f} h {c['h']:.2f} l {c['l']:.2f} c {c['c']:.2f}  VAH'a uzaklık(kapanış) {(vah - c['c'])/a:+.2f} ATR {'← iğne VAH' if c['h'] >= vah - 0.25*a else ''}")
    # retest kontrolü ayrıntı
    ev = ta.level_retest(f["h"][:i+1], f["l"][:i+1], f["c"][:i+1], vah, 10, open_=f["o"][:i+1], detach_atr=0)
    print("   detach olmadan VAH olayı:", ev, " uzaklık şart:", abs(f["c"][i] - vah) / a, "ATR (≤1.5 olmalı)")
