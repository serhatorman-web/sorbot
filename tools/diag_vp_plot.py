"""Teşhis: hacim profili retestlerini grafikle gösterir."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import scanner as sc, indicators as ta
api = sc.Binance(); now_ms = int(time.time() * 1000)
cfg0 = sc.load_json(sc.CONFIG_PATH, {})
syms = ["BTCUSDT","ETHUSDT","SOLUSDT","XRPUSDT","BNBUSDT","DOGEUSDT","ADAUSDT","LINKUSDT","AVAXUSDT","SUIUSDT","LTCUSDT","DOTUSDT",
        "XAUUSDT","XAGUSDT","NVDAUSDT","TSLAUSDT","AAPLUSDT","QQQUSDT","MSFTUSDT","CRWDUSDT","AAVEUSDT","NEARUSDT","APTUSDT","TRXUSDT"]
os.makedirs("out", exist_ok=True)
found = 0
for tf in ("15m", "1h", "4h"):
    cfg = sc.apply_tf_profile(cfg0, tf) if tf != "1h" else cfg0
    n = cfg["volume_profile"]["lookback_bars"].get(tf, 96)
    for s in syms:
        if found >= 6:
            break
        cs = sc.parse_klines(api.get("/fapi/v1/klines", {"symbol": s, "interval": tf, "limit": 300}), now_ms)
        f = {k: [x[k] for x in cs] for k in ("o", "h", "l", "c", "v")}
        i = len(cs) - 1
        res = {"f": f, "i": i, "meta": {"precision": 6}}
        sc.compute_volume_profile(res, cfg)
        lines = sc.volume_profile_lines(res, cfg)
        if not lines:
            continue
        found += 1
        vah, poc, val = res["vp"]
        name = lines[1].split(" ")[1]
        ev = res["vp_ev"][name]
        lvl = ev["level"]; k = i - ev["bars_ago"]
        a = max(0, i - 60)
        fig, ax = plt.subplots(figsize=(12, 5.5))
        for j in range(a, i + 1):
            col = "#26a69a" if f["c"][j] >= f["o"][j] else "#ef5350"
            ax.plot([j, j], [f["l"][j], f["h"][j]], color=col, lw=0.8)
            ax.plot([j, j], [f["o"][j], f["c"][j]], color=col, lw=3.5)
        for lv, nm, col in ((vah, "VAH", "#ef5350"), (poc, "POC", "#f9a825"), (val, "VAL", "#26a69a")):
            ax.axhline(lv, color=col, lw=1.6 if nm == name else 0.8, ls="-" if nm == name else "--")
            ax.text(a, lv, f" {nm} {lv:.6g}", color=col, va="bottom", fontsize=9)
        ax.axvspan(k - 0.5, k + 0.5, color="#1e88e5", alpha=0.18)
        ax.text(k, ax.get_ylim()[1], "retest mumu", ha="center", va="top", fontsize=8, color="#1e88e5")
        ax.set_title(f"{s} {tf}  |  " + lines[1][2:])
        ax.grid(alpha=0.2); fig.tight_layout()
        fn = f"out/{found}_{s}_{tf}.png"; fig.savefig(fn, dpi=85); plt.close(fig)
        print("BULUNDU", s, tf, lines[1], "| dokunan mum:", cs[k]["o"], cs[k]["h"], cs[k]["l"], cs[k]["c"], "| son kapanış:", f["c"][i])
print("toplam", found)
