"""BABA 1s: son 20 mumda SSL sistemi adım adım (çizgi rengi, SSL kesişimi, Supertrend, QQE, DynaRange, sinyal)."""
import sys, time
sys.path.insert(0, ".")
import scanner as S
import sniper as SN

cfg = S.load_json(S.CONFIG_PATH, None)
p = cfg["sniper"]["rules"]["1h"]["ssl_top"]
api = S.Binance()
now = int(time.time() * 1000)
for sym in sys.argv[1:] or ["BABAUSDT"]:
    cs = S.parse_klines(api.get("/fapi/v1/klines", {"symbol": sym, "interval": "1h", "limit": 499}), now)
    f = S.compute_features(cs, cfg)
    h, l, c, o, v = f["h"], f["l"], f["c"], f["o"], f["v"]
    x = SN.features(o, h, l, c, v)
    bb, col = SN.ssl_baseline(h, l, c, p.get("hma", 55))
    print(f"BB| ===== {sym} 1s · ayarlar {p} =====")
    for i in range(len(c) - 22, len(c)):
        t = S.datetime.fromtimestamp(cs[i]["t"] / 1000, S.TR_TZ).strftime("%d.%m %H:%M")
        cr = ""
        if f["ssl"][i] and f["ssl"][i - 1]:
            if c[i] > f["ssl"][i] and c[i - 1] <= f["ssl"][i - 1]:
                cr = "SSL Buy"
            if c[i] < f["ssl"][i] and c[i - 1] >= f["ssl"][i - 1]:
                cr = "SSL Sell"
        sig = SN.ssl_system(h, l, c, f["ssl"], f["st_dir"], x["a"], col, i, p, f["qqe"], f["dyna"])
        p2 = dict(p, confirm_required=False)
        sig2 = SN.ssl_system(h, l, c, f["ssl"], f["st_dir"], x["a"], col, i, p2, f["qqe"], f["dyna"])
        print(f"BB| {t} k={c[i]:.2f} baseline={bb[i]:.2f} renk={ {1: 'MAVİ', -1: 'KIRMIZI', 0: 'gri'}[col[i]] } {cr:8} "
              f"ST={'AL' if f['st_dir'][i] == 1 else 'SAT'} QQE={f['qqe'][i]} Dyna={f['dyna'][i]:+.3f} "
              f"teyitli={'SİNYAL ' + ('LONG' if sig['d'] == 1 else 'SHORT') if sig else '-'} "
              f"teyitsiz={'SİNYAL' if sig2 else '-'}")
