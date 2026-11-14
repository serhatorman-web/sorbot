"""Geçici teşhis: gönderilmiş sinyallerde trend çizgisi sonuçlarını bağımsız kontrolle doğrula."""
import sys, os, json, base64, io, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as sc, indicators as ta

TFMS = {"15m": 900e3, "1h": 3600e3, "4h": 14400e3, "1d": 86400e3, "1w": 604800e3}
api = sc.Binance()

def fetch(sym, tf, ts):
    raw = api.get("/fapi/v1/klines", {"symbol": sym, "interval": tf, "limit": 150, "endTime": ts})
    return sc.parse_klines(raw, ts)

def ref_check(h, l, c, ev_list):
    """Bağımsız yeniden hesap (aynı kurallar, ayrı kod) + ayrıntı."""
    n = len(c); a = ta.atr(h, l, c, 14); res = {}
    for kind in ("rising", "falling"):
        src = l if kind == "rising" else h
        piv = []
        for j in range(5, n - 5):
            w = src[j-5:j+6]
            if src[j] == (min(w) if kind == "rising" else max(w)) and (not piv or j - piv[-1] > 5):
                piv.append(j)
        if len(piv) < 2: continue
        p1, p2 = piv[-2:]
        if (kind == "rising") != (src[p2] > src[p1]) or src[p2] == src[p1]: continue
        L = lambda k: src[p1] + (src[p2] - src[p1]) * (k - p1) / (p2 - p1)
        side = (lambda k: c[k] < L(k)) if kind == "rising" else (lambda k: c[k] > L(k))
        if any(side(k) for k in range(p1 + 1, p2)): continue
        brk = next((k for k in range(p2 + 1, n) if side(k)), None)
        if brk is None or n - 1 - brk > 20 or not side(n - 1): continue
        st, tch = "none", None
        for k in range(brk + 1, n):
            tol = (a[k] or 0) * 0.25
            if tch is None:
                if (kind == "rising" and h[k] >= L(k) - tol and c[k] < L(k)) or (kind == "falling" and l[k] <= L(k) + tol and c[k] > L(k)):
                    tch, st = k, "touch"
            elif (kind == "rising" and c[k] < l[tch]) or (kind == "falling" and c[k] > h[tch]):
                st = "confirmed"; break
        # yeniden kırılım (çizginin üstüne geri dönüp sonra tekrar kırma) var mı?
        reclaim = [k for k in range(brk + 1, n) if not side(k)]
        res[kind] = dict(p1=p1, p2=p2, brk=brk, state=st, touch=tch, reclaim=len(reclaim),
                         far_atr=round(abs(c[-1] - L(n-1)) / (a[-1] or 1), 2), span=p2 - p1, age=n-1-p2)
    return res

def plot(cs, kind, d, title):
    import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
    h=[x["h"] for x in cs]; l=[x["l"] for x in cs]; c=[x["c"] for x in cs]; o=[x["o"] for x in cs]
    n=len(c); s0=max(0, d["p1"]-10)
    fig, ax = plt.subplots(figsize=(7, 3.2), dpi=70)
    for k in range(s0, n):
        col = "g" if c[k] >= o[k] else "r"
        ax.vlines(k, l[k], h[k], color=col, lw=0.7); ax.vlines(k, min(o[k],c[k]), max(o[k],c[k]), color=col, lw=2.5)
    src = l if kind == "rising" else h
    xs=[d["p1"], n-1]; ys=[src[d["p1"]] + (src[d["p2"]]-src[d["p1"]])*(x-d["p1"])/(d["p2"]-d["p1"]) for x in xs]
    ax.plot(xs, ys, "b-", lw=1); ax.plot([d["p1"], d["p2"]], [src[d["p1"]], src[d["p2"]]], "bo", ms=4)
    ax.axvline(d["brk"], color="orange", ls="--", lw=0.8)
    if d["touch"] is not None: ax.axvline(d["touch"], color="purple", ls=":", lw=0.9)
    ax.set_title(title, fontsize=8); fig.tight_layout()
    b = io.BytesIO(); fig.savefig(b, format="png"); plt.close(fig)
    return base64.b64encode(b.getvalue()).decode()

sigs = [ln.split() for ln in open(os.path.join(os.path.dirname(__file__), "tl_sigs.txt"))]
mism = tot = 0; plots = []; seen = set()
for t, sym, side, typ, tf0 in sigs:
    ts = int(dt.datetime.strptime(t, "%Y-%m-%dT%H:%M").replace(tzinfo=dt.timezone.utc).timestamp() * 1000) - 30000
    for tf in sc.DIV_TFS:
        try: cs = fetch(sym, tf, ts)
        except Exception as e: print("ERR", sym, tf, e); continue
        if len(cs) < 40: continue
        h=[x["h"] for x in cs]; l=[x["l"] for x in cs]; c=[x["c"] for x in cs]
        bot = {e["type"]: e for e in ta.trendline_break(h, l, c)}
        ref = ref_check(h, l, c, bot)
        tot += 1
        same = set(bot) == set(ref) and all(bot[k]["retest"] == ref[k]["state"] for k in bot)
        if not same: mism += 1
        for k, d in ref.items():
            T = lambda j: dt.datetime.utcfromtimestamp(cs[j]["t"]/1000).strftime("%m-%d %H:%M")
            print(f"{'OK ' if same else 'XX '}{t} {sym} {side} sig{tf0} | {tf} {k} state={d['state']} bot={bot.get(k,{}).get('retest')} "
                  f"p1={T(d['p1'])} p2={T(d['p2'])} span={d['span']} age={d['age']} brk={T(d['brk'])}({len(c)-1-d['brk']}b) "
                  f"touch={T(d['touch']) if d['touch'] is not None else '-'} reclaim={d['reclaim']} far={d['far_atr']}ATR")
            key = (d["state"], tf in ("15m","1h"))
            if len(plots) < 8 and (key not in seen or len(plots) < 8 and d["reclaim"]):
                seen.add(key); plots.append((f"{sym} {tf} {k} {d['state']} @{t}", plot(cs, k, d, f"{sym} {tf} {k} {d['state']} @{t}")))
        if not same and not ref:
            print("XX", t, sym, tf, "bot:", bot)
print(f"\nTOPLAM {tot} grafik, uyuşmazlık {mism}")
for name, b in plots:
    print("IMG", name.replace(" ", "_"), b)
