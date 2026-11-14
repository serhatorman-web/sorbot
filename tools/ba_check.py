"""Geçici teşhis: retest kuralı önce/sonra karşılaştırması."""
import sys, os, time, json, collections
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scanner as sc, indicators as new, indicators_old as old
cfg0 = json.load(open("config.json")); api = sc.Binance(); now = int(time.time() * 1000)
tick = api.get("/fapi/v1/ticker/24hr")
top = [t["symbol"] for t in sorted(tick, key=lambda t: -float(t["quoteVolume"])) if t["symbol"].endswith("USDT")][:40]
cnt = {"eski": collections.Counter(), "yeni": collections.Counter()}
changes = collections.Counter(); errs = 0
for sym in top:
    for tf in ("15m", "1h", "4h"):
        try:
            cfg = dict(cfg0, timeframe=tf)
            cs = sc.parse_klines(api.get("/fapi/v1/klines", {"symbol": sym, "interval": tf, "limit": 300}), now)
            f = sc.compute_features(cs, cfg); i = len(cs) - 1
            h, l, c, o = f["h"], f["l"], f["c"], f["o"]
            vp = new.volume_profile(h[-150:], l[-150:], f["v"][-150:], 24, 0.7)
            for tag, m in (("eski", old), ("yeni", new)):
                r = {}
                for nm, key in (("Kijun", "ichi_kijun"), ("Tenkan", "ichi_tenkan")):
                    ev = m.band_retest(h, l, c, f[key], f[key]); r[nm] = ev and f"{ev['kind']}-{ev['state']}"
                ev = m.band_retest(h, l, c, f["ichi_top"], f["ichi_bot"]); r["Bulut"] = ev and f"{ev['kind']}-{ev['state']}"
                for ev in m.trendline_break(h, l, c): r["Trend-" + ev["type"]] = "break-" + ev["retest"]
                if vp:
                    for nm, lv in zip(("VAH", "POC", "VAL"), vp):
                        ev = m.level_retest(h, l, c, lv, 10, open_=o); r["HP-" + nm] = ev and f"{ev['kind']}-{ev['state']}"
                for k, v in r.items():
                    grp = k.split("-")[0]
                    cnt[tag][f"{grp} {v}"] += 1
                if tag == "eski": ro = r
            for k in ro:
                if ro[k] != r.get(k): changes[f"{k.split('-')[0]}: {ro[k]} → {r.get(k)}"] += 1
        except Exception as e:
            errs += 1; print("ERR", sym, tf, e)
print("HATA", errs)
for g in ("Kijun", "Tenkan", "Bulut", "Trend", "HP"):
    for tag in ("eski", "yeni"):
        items = {k.split(" ", 1)[1]: v for k, v in cnt[tag].items() if k.startswith(g + " ") and "None" not in k}
        print(f"{g:7} {tag}: " + ", ".join(f"{k}={v}" for k, v in sorted(items.items())))
print("DEĞİŞENLER")
for k, v in changes.most_common(): print(f"  {v:3} {k}")
