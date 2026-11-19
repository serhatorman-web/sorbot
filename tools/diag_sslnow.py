"""17:22 TSİ'den beri (teyitli SSL) hangi mumlarda SSL sinyali oluştu, aynı taramada toplam kaç Nokta Atışı adayı vardı?"""
import sys, time
from collections import defaultdict
sys.path.insert(0, ".")
import scanner as S
import sniper as SN

since = int(S.datetime(2026, 11, 19, 14, 20, tzinfo=S.timezone.utc).timestamp() * 1000)
base = S.load_json(S.CONFIG_PATH, None)
api = S.Binance()
now = int(time.time() * 1000)
for tf in ("15m", "1h"):
    cfg = S.apply_tf_profile(base, tf) if tf != "1h" else base
    sc = cfg["sniper"]; rules = {k: v for k, v in sc["rules"][tf].items() if v.get("enabled")}
    sp = rules.get("ssl_top")
    uni, *_ = S.build_universe(api, cfg)
    uni = [m for m in uni if m["type"] in sc["types"]]
    per_bar = defaultdict(lambda: [0, []])
    for m in uni:
        try:
            cs = S.parse_klines(api.get("/fapi/v1/klines", {"symbol": m["symbol"], "interval": tf, "limit": 520}), now)
        except Exception:  # noqa: BLE001
            continue
        f = S.compute_features(cs, cfg)
        h, l, c, o, v = f["h"], f["l"], f["c"], f["o"], f["v"]
        x = SN.features(o, h, l, c, v)
        col = SN.ssl_baseline(h, l, c, sp.get("hma", 55))[1]
        for i in range(len(c)):
            if cs[i]["t"] + S.TF_MS[tf] <= since:
                continue
            sigs = [s for s in SN.setups(o, h, l, c, v, i, x) if s["rule"] in rules]
            ss = SN.ssl_system(h, l, c, f["ssl"], f["st_dir"], x["a"], col, i, sp, f["qqe"], f["dyna"])
            t = S.datetime.fromtimestamp((cs[i]["t"] + S.TF_MS[tf]) / 1000, S.TR_TZ).strftime("%H:%M")
            per_bar[t][0] += len(sigs) + (1 if ss else 0)
            if ss:
                per_bar[t][1].append(f"{m['symbol']} {'SHORT' if ss['d'] == -1 else 'LONG'}")
    print(f"NW| ===== {tf} ({len(uni)} sembol) =====")
    for t in sorted(per_bar):
        tot, ssl = per_bar[t]
        print(f"NW| {t} kapanış · toplam aday {tot} · SSL: {', '.join(ssl) if ssl else '-'}")
