"""Geçici: son günlerdeki Supertrend sinyallerinden pivot stratejisi onaylananlar + LONG/SHORT örnek mesaj."""
import sys, os, json, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as sc
api = sc.Binance()
base = json.load(open("config.json"))
tick = {t["symbol"]: t for t in api.get("/fapi/v1/ticker/24hr")}
info = {s["symbol"]: s for s in api.get("/fapi/v1/exchangeInfo")["symbols"]}
syms = [s for s, t in sorted(tick.items(), key=lambda kv: -float(kv[1]["quoteVolume"]))
        if s in info and info[s].get("underlyingType") == "COIN" and float(tick[s]["quoteVolume"]) >= 3e6][:120]
now = int(time.time() * 1000)
found = {}
cnt = {}
for tf in ("15m", "1h", "4h"):
    cfg = sc.apply_tf_profile(base, tf) if tf != "1h" else dict(base)
    n_sig = n_ok = 0
    for sym in syms:
        try:
            cs = sc.parse_klines(api.get("/fapi/v1/klines", {"symbol": sym, "interval": tf, "limit": 499}), now)
        except Exception:
            continue
        if len(cs) < 400: continue
        f = sc.compute_features(cs, cfg)
        lim = {"15m": 96 * 3, "1h": 24 * 7, "4h": 6 * 14}[tf]
        for i in range(len(cs) - lim, len(cs)):
            s = f["st_dir"][i]
            if not s or f["st_dir"][i - 1] == s: continue
            n_sig += 1
            pv = sc.pivot_from_bars(f, i, tf)
            if not pv: continue
            P = pv["P"]; price = f["c"][i]; d = f["dyna"][i] or 0; q = f["qqe"][i]
            if not ((price - P) * s > 0 and d * s > 0 and q == s): continue
            names = ("R1", "R2", "R3") if s == 1 else ("S1", "S2", "S3")
            stop = pv["S1" if s == 1 else "R1"]
            if not any((pv[n] - price) * s > 0 for n in names) or (price - stop) * s <= 0: continue
            n_ok += 1
            dd = "long" if s == 1 else "short"
            if dd not in found or f["t"][i] > found[dd][3]:
                found[dd] = (tf, sym, cs[:i + 1], f["t"][i])
    cnt[tf] = (n_sig, n_ok)
print("\n===== SAYIM (15dk son 3 gün, 1s son 7 gün, 4s son 14 gün, ilk 120 kripto)")
for tf, (a, b) in cnt.items():
    print(f"{tf}: Supertrend sinyali {a} · pivot stratejisi onaylanan {b}")
orig_get = sc.Binance.get
for d in ("long", "short"):
    if d not in found:
        print(f"\n===== {d}: bulunamadı"); continue
    tf, sym, cs, _ = found[d]
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
    sc.fetch_tf_trends(api, r, t_end, tf, order_blocks=False)
    sc.compute_volume_profile(r, cfg)
    sc.Binance.get = orig_get
    after = sc.parse_klines(api.get("/fapi/v1/klines", {"symbol": sym, "interval": tf, "startTime": t_end, "limit": 499}), now)
    pv = r["pivot"]; s = 1 if d == "long" else -1
    hit = []
    for n in (("R1", "R2", "R3") if s == 1 else ("S1", "S2", "S3")):
        k = next((j for j, x in enumerate(after) if (x["h"] if s == 1 else x["l"]) * s >= pv[n] * s), None)
        hit.append(f"{n}:{'-' if k is None else k + 1}")
    sn = "S1" if s == 1 else "R1"
    ks = next((j for j, x in enumerate(after) if (x["l"] if s == 1 else x["h"]) * s <= pv[sn] * s), None)
    print(f"\n===== {d} · {sym} · {tf} · sonrası (kaç mum sonra): {' '.join(hit)} stop {sn}:{'-' if ks is None else ks + 1} · şu an {after[-1]['c'] if after else '?'}")
    print(sc.build_message(r, d, cfg, ctx["now_utc"]))
