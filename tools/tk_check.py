"""Geçici teşhis: Kijun / Tenkan retest kontrolü."""
import sys, os, time, json, io, base64, collections
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as sc, indicators as ta
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
cfg0 = json.load(open("config.json")); api = sc.Binance(); now = int(time.time() * 1000)
tick = api.get("/fapi/v1/ticker/24hr")
top = [t["symbol"] for t in sorted(tick, key=lambda t: -float(t["quoteVolume"])) if t["symbol"].endswith("USDT")][:25]
rows = []; plots = []; seen = collections.Counter()
def detail(h, l, c, line, ev):
    n = len(c); a = ta.atr(h, l, c, 14); last = n - 1; s = 1 if ev["dir"] == "up" else -1
    tol = lambda k: (a[k] or 0) * 0.25
    hit = lambda k: (l[k] <= line[k] + tol(k)) if s == 1 else (h[k] >= line[k] - tol(k))
    if ev["kind"] == "break":
        brk = last - ev["bars_ago"]
        t = next((k for k in range(brk + 1, n) if hit(k)), None)
    else:
        brk = None; t = last - ev["bars_ago"]
    if t is None: return brk, None, None, None
    start = brk if brk is not None else t - 1
    # touch öncesi fiyat çizgiden ne kadar uzaklaşmıştı (ATR)
    away = max((abs((l[k] - line[k]) if s == 1 else (line[k] - h[k])) / (a[k] or 1) for k in range(start, t)), default=0)
    # dokunuşa çizgi mi geldi fiyat mı: çizginin hareketi vs fiyat ekstremi hareketi
    lmove = abs(line[t] - line[start]) / (a[t] or 1)
    return brk, t, round(away, 2), round(lmove, 2)
for sym in top:
    for tf in ("15m", "1h", "4h"):
        cfg = dict(cfg0, timeframe=tf)
        cs = sc.parse_klines(api.get("/fapi/v1/klines", {"symbol": sym, "interval": tf, "limit": 300}), now)
        f = sc.compute_features(cs, cfg); i = len(cs) - 1
        h, l, c, o = f["h"], f["l"], f["c"], f["o"]
        for name, key in (("Tenkan", "ichi_tenkan"), ("Kijun", "ichi_kijun")):
            line = f[key]
            ev = ta.band_retest(h, l, c, line, line)
            if not ev or ev["kind"] in ("trend", "inside"): 
                rows.append((name, ev and ev["kind"], None)); continue
            brk, t, away, lmove = detail(h, l, c, line, ev)
            rows.append((name, ev["kind"] + "-" + str(ev["state"]), (brk is not None and t is not None and t - brk, away, lmove)))
            print(f"{sym:12} {tf:3} {name:6} {ev['kind']:5} {ev['dir']:4} {str(ev['state']):9} bars_ago={ev['bars_ago']:2} "
                  f"brk->touch={(t - brk) if (brk is not None and t is not None) else '-'} uzaklaşma={away}ATR çizgi_hareketi={lmove}ATR")
            k = (name, ev["kind"], ev["state"])
            if seen[k] < 2 and len(plots) < 12:
                seen[k] += 1
                s0 = max(0, i - 45)
                fig, ax = plt.subplots(figsize=(7, 3.2), dpi=70)
                for x in range(s0, i + 1):
                    col = "g" if c[x] >= o[x] else "r"
                    ax.vlines(x, l[x], h[x], color=col, lw=0.7); ax.vlines(x, min(o[x], c[x]), max(o[x], c[x]), color=col, lw=2.5)
                ax.step(range(s0, i + 1), line[s0:i + 1], where="mid", color="b", lw=1)
                if brk is not None: ax.axvline(brk, color="orange", ls="--", lw=0.8)
                if t is not None: ax.axvline(t, color="purple", ls=":", lw=1)
                ttl = f"{sym} {tf} {name} {ev['kind']} {ev['dir']} {ev['state']}"
                ax.set_title(ttl, fontsize=8); fig.tight_layout()
                b = io.BytesIO(); fig.savefig(b, format="png"); plt.close(fig)
                plots.append((ttl.replace(" ", "_"), base64.b64encode(b.getvalue()).decode()))
cnt = collections.Counter((r[0], r[1]) for r in rows)
print("DAĞILIM", json.dumps({f"{a} {b}": v for (a, b), v in sorted(cnt.items(), key=str)}, ensure_ascii=False))
for nm in ("Tenkan", "Kijun"):
    br = [r[2] for r in rows if r[0] == nm and r[2] and r[2][0] is not False and r[2][0] is not None]
    if br:
        print(nm, "kırılım→dokunuş mum:", collections.Counter(min(x[0], 5) for x in br),
              "dokunuştan önce 0.5 ATR'den az uzaklaşan:", sum(1 for x in br if x[1] < 0.5), "/", len(br))
for nm, b in plots: print("IMG", nm, b)
