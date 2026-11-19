"""Teyitli SSL Hybrid sinyali örneği: son mumlardaki en yeni sinyal, canlı mesaj formatıyla (build_sniper_message)."""
import sys, time
sys.path.insert(0, ".")
import scanner as S
import sniper as SN

base = S.load_json(S.CONFIG_PATH, None)
api = S.Binance()
now_ms = int(time.time() * 1000)
funding = {}
tickers = {}
for tf, look in (("1h", 24), ("15m", 64)):
    cfg = S.apply_tf_profile(base, tf) if tf != "1h" else base
    rc_all = cfg["sniper"]["rules"][tf]
    uni, *_ = S.build_universe(api, cfg)
    uni = [m for m in uni if m["type"] in cfg["sniper"]["types"]]
    cands = {}
    for m in uni:
        try:
            cands[m["symbol"]] = S.parse_klines(api.get("/fapi/v1/klines", {"symbol": m["symbol"], "interval": tf,
                                                                           "limit": cfg["kline_limit"]}), now_ms)
        except Exception:  # noqa: BLE001
            pass
    leaders = {}
    for typ, lsym in cfg["market_leaders"].items():
        if typ.startswith("_") or lsym not in cands:
            continue
        lf = S.compute_features(cands[lsym], cfg)
        leaders[typ] = {"symbol": lsym, "bias": S.trend_bias(lf), "ret24": lf["c"][-1] / lf["c"][-1 - S.bars_per_day(cfg)] - 1}
    eth = S.trend_bias(S.compute_features(cands["ETHUSDT"], cfg)) if "ETHUSDT" in cands else None
    found = []
    for m in uni:
        cs = cands.get(m["symbol"])
        if not cs or len(cs) < 300:
            continue
        f = S.compute_features(cs, cfg)
        h, l, c, o, v = f["h"], f["l"], f["c"], f["o"], f["v"]
        x = SN.features(o, h, l, c, v)
        col = SN.ssl_baseline(h, l, c, 55)[1]
        for i in range(len(c) - look, len(c)):
            sig = SN.ssl_system(h, l, c, f["ssl"], f["st_dir"], x["a"], col, i, rc_all["ssl_top"], f["qqe"], f["dyna"])
            if sig:
                found.append((cs[i]["t"], m, i, sig))
    print(f"MX| ===== {tf}: son {look} mumda {len(found)} teyitli SSL sinyali =====")
    if not found:
        continue
    t, m, i, sig = max(found, key=lambda z: z[0])
    cs = cands[m["symbol"]][:i + 1]
    ctx = {"leaders": leaders, "funding": funding, "tickers": tickers,
           "now_utc": S.datetime.fromtimestamp((t + S.TF_MS[tf]) / 1000, S.timezone.utc), "eth_bias": eth,
           "btc_dom": S.btc_dominance(None), "ndx": S.nasdaq_index()}
    r = S.analyze_symbol(m, cs, ctx, cfg)
    a = r["f"]["atr"][r["i"]]
    rc = rc_all[sig["rule"]]
    lv = SN.levels(r["f"]["c"][r["i"]], sig["d"], sig["stop"], SN.features(*(r["f"][k] for k in ("o", "h", "l", "c", "v")))["a"][r["i"]],
                   rc.get("min_stop_pct", 0))
    msg = S.build_sniper_message(api, r, sig, lv, rc, cfg, ctx["now_utc"], t + S.TF_MS[tf])
    full = cands[m["symbol"]]
    best, stp = 0, False
    for k in range(i + 1, len(full)):
        if (full[k]["l"] <= lv["stop"]) if sig["d"] == 1 else (full[k]["h"] >= lv["stop"]):
            stp = True
            break
        best = max(best, sum(1 for tp in lv["tp"] if ((full[k]["h"] >= tp) if sig["d"] == 1 else (full[k]["l"] <= tp))))
    print(f"MX| (sonrası: {'TP' + str(best) + ' oldu' if best else ''}{' sonra stop' if stp and best else 'stop' if stp else ''}"
          f"{'henüz açık' if not best and not stp else ''})")
    for ln in msg.splitlines():
        print("MX| " + ln)
