"""Nokta atışı SSL sistemi örnekleri: son 3 gün (SKY dahil), canlı ayarlarla."""
import sys, time
sys.path.insert(0, ".")
import scanner as S
import sniper as SN

base = S.load_json(S.CONFIG_PATH, None)
api = S.Binance()
now_ms = int(time.time() * 1000)
for tf in ("1h", "15m"):
    cfg = S.apply_tf_profile(base, tf) if tf != "1h" else base
    p = cfg["sniper"]["rules"][tf]["ssl_top"]
    rc = cfg["sniper"]["rules"][tf]
    uni, *_ = S.build_universe(api, cfg)
    uni = [m for m in uni if m["type"] in cfg["sniper"]["types"]]
    uni.sort(key=lambda m: m["symbol"] != "SKYUSDT")
    shown, n_all, shown_k, cnt = 0, 0, {}, {}
    look = 72 if tf == "1h" else 288
    for m in uni:
        cs = S.parse_klines(api.get("/fapi/v1/klines", {"symbol": m["symbol"], "interval": tf, "limit": 499 + look}), now_ms)
        if len(cs) < 400:
            continue
        f = S.compute_features(cs, cfg)
        h, l, c, v, o = f["h"], f["l"], f["c"], f["v"], f["o"]
        x = SN.features(o, h, l, c, v)
        _, col = SN.ssl_baseline(h, l, c, p.get("hma", 55))
        for i in range(len(c) - look, len(c)):
            sig = SN.ssl_system(h, l, c, f["ssl"], f["st_dir"], x["a"], col, i, p, f["qqe"], f["dyna"])
            if not sig:
                continue
            n_all += 1
            kind = "zit" if "⚠️" in sig["why"] else "uyumlu"
            cnt[kind] = cnt.get(kind, 0) + 1
            if shown_k.get(kind, 0) >= 2:
                continue
            shown_k[kind] = shown_k.get(kind, 0) + 1
            lv = SN.levels(c[i], sig["d"], sig["stop"], x["a"][i], rc[sig["rule"]].get("min_stop_pct", 0))
            tc = S.datetime.fromtimestamp((cs[i]["t"] + S.TF_MS[tf]) / 1000, S.TR_TZ).strftime("%d.%m.%Y %H:%M")
            best, stp = 0, False
            for k in range(i + 1, len(c)):
                if (l[k] <= lv["stop"]) if sig["d"] == 1 else (h[k] >= lv["stop"]):
                    stp = True
                    break
                best = max(best, sum(1 for tp in lv["tp"] if ((h[k] >= tp) if sig["d"] == 1 else (l[k] <= tp))))
                if best == 3:
                    break
            res = (f"TP{best} oldu" if best else "") + (" sonra stop" if stp and best else "stop" if stp else "") or "henüz açık"
            msg = SN.message(S.display_name(m), {"15m": "15dk", "1h": "1 saat"}[tf], sig, lv,
                             lambda q, pr=m.get("precision"): S.fmt_price(q, pr), tc, 0, rc[sig["rule"]])
            print(f"EX| --- {m['symbol']} {tf} (sonrası: {res}) ---")
            for ln in msg.splitlines():
                if "4 saatlik trend" not in ln:
                    print("EX| " + ln)
    print(f"EX| ===== {tf}: son {look} mumda {n_all} SSL sinyali ({len(uni)} sembol) · {cnt} =====")
