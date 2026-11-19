"""SSL sistemi (teyitli): ayar seçeneklerine göre günde kaç sinyal (son 7 gün, Nokta Atışı'nın taradığı tüm semboller)."""
import sys, time
from multiprocessing import Pool
sys.path.insert(0, ".")
import scanner as S
import sniper as SN

DAYS = 7
VARS = {
    "15m": [("Şimdiki (önceki trend ≥30 mum, teyit ≤5 mum, Supertrend ters)", {}),
            ("Önceki trend ≥15 mum", {"min_regime": 15}),
            ("Önceki trend şartı yok", {"min_regime": 0}),
            ("Teyit ≤10 mum", {"confirm_bars": 10}),
            ("Supertrend ters şartı yok", {"supertrend_opposite": False}),
            ("Önceki trend ≥15 + teyit ≤10", {"min_regime": 15, "confirm_bars": 10}),
            ("Önceki trend yok + teyit ≤10", {"min_regime": 0, "confirm_bars": 10}),
            ("Önceki trend yok + teyit ≤10 + Supertrend şartı yok", {"min_regime": 0, "confirm_bars": 10, "supertrend_opposite": False})],
    "1h": [("Şimdiki (tepeye/dibe yakın, teyit ≤5 mum, Supertrend ters)", {}),
           ("Teyit ≤10 mum", {"confirm_bars": 10}),
           ("Supertrend ters şartı yok", {"supertrend_opposite": False}),
           ("Tepeye/dibe yakınlık şartı yok", {"near_atr": 99}),
           ("Teyit ≤10 + Supertrend şartı yok", {"confirm_bars": 10, "supertrend_opposite": False})],
}


def run(args):
    tf, m, cs, cfg = args
    if len(cs) < 400:
        return []
    base = cfg["sniper"]["rules"][tf]["ssl_top"]
    f = S.compute_features(cs, cfg)
    h, l, c, o, v = f["h"], f["l"], f["c"], f["o"], f["v"]
    x = SN.features(o, h, l, c, v)
    col = SN.ssl_baseline(h, l, c, base.get("hma", 55))[1]
    N = DAYS * (96 if tf == "15m" else 24)
    out = []
    for name, over in VARS[tf]:
        p = dict(base, **over)
        last = -99
        for i in range(len(c) - N, len(c)):
            sig = SN.ssl_system(h, l, c, f["ssl"], f["st_dir"], x["a"], col, i, p, f["qqe"], f["dyna"])
            if not sig or i - last < 8:          # canlıdaki gibi: aynı sembolde 8 mum içinde ikinci sinyal yok
                continue
            last = i
            lv = SN.levels(c[i], sig["d"], sig["stop"], x["a"][i], p.get("min_stop_pct", 1.0))
            res = None
            for k in range(i + 1, len(c)):
                if (l[k] <= lv["stop"]) if sig["d"] == 1 else (h[k] >= lv["stop"]):
                    res = "stop"; break
                if (h[k] >= lv["tp"][0]) if sig["d"] == 1 else (l[k] <= lv["tp"][0]):
                    res = "tp1"; break
            out.append((tf, name, res))
    return out


if __name__ == "__main__":
    base = S.load_json(S.CONFIG_PATH, None)
    api = S.Binance()
    now = int(time.time() * 1000)
    jobs = []
    for tf in VARS:
        cfg = S.apply_tf_profile(base, tf) if tf != "1h" else base
        uni, *_ = S.build_universe(api, cfg)
        uni = [m for m in uni if m["type"] in cfg["sniper"]["types"]]
        N = DAYS * (96 if tf == "15m" else 24)
        for m in uni:
            try:
                cs = S.parse_klines(api.get("/fapi/v1/klines", {"symbol": m["symbol"], "interval": tf, "limit": min(1500, 499 + N)}), now)
                jobs.append((tf, m, cs, cfg))
            except Exception:  # noqa: BLE001
                pass
        print(f"CN| {tf}: {len(uni)} sembol", flush=True)
    with Pool(4) as pl:
        ev = [e for part in pl.map(run, jobs) for e in part]
    for tf in VARS:
        print(f"CN| ===== {tf} (son {DAYS} gün) =====")
        for name, _ in VARS[tf]:
            X = [e for e in ev if e[0] == tf and e[1] == name]
            done = [e for e in X if e[2]]
            tp = sum(e[2] == "tp1" for e in done)
            print(f"CN| {name} | günde {len(X) / DAYS:.1f} | TP1 stoptan önce %{100 * tp / len(done) if done else 0:.0f} ({tp}/{len(done)})")
