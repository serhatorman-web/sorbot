"""Geçici: TradingView Technical Ratings osilatör kurallarını varyantlarla TV değerlerine eşleme."""
import sys, os, json, itertools
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as sc, indicators as ta
api = sc.Binance()
ref = json.load(open(os.path.join(os.path.dirname(__file__), "tv_ref.json")))
data = []
for sym, r in ref.items():
    vals = r["v"][:-1]                                   # son değer oluşan mum
    last = r["t0"] + (len(vals) - 1) * r["step"]
    raw = api.get("/fapi/v1/klines", {"symbol": sym, "interval": r["tf"], "limit": 1000, "endTime": last * 1000 + 1})
    cs = sc.parse_klines(raw, (last + r["step"]) * 1000 + 5)
    assert cs[-1]["t"] // 1000 == last, (cs[-1]["t"], last)
    data.append((sym, cs, vals))

def variants(h, l, c, v):
    n = len(c)
    r = ta.rsi(c, 14)
    hh, ll = ta.highest(h, 14), ta.lowest(l, 14)
    raw = [None if hh[i] is None else (0.0 if hh[i] == ll[i] else 100 * (c[i] - ll[i]) / (hh[i] - ll[i])) for i in range(n)]
    sk = ta.sma(raw, 3); sd = ta.sma(sk, 3)
    cc = ta.cci(h, l, c, 20)
    ax, pdi, ndi = ta.adx(h, l, c, 14)
    hl2 = [(a + b) / 2 for a, b in zip(h, l)]
    ao = [None if a is None or b is None else a - b for a, b in zip(ta.sma(hl2, 5), ta.sma(hl2, 34))]
    mom = ta.momentum(c, 10)
    ml, ms, _ = ta.macd(c)
    srk, srd = ta.stoch_rsi(c, 14, 14, 3, 3)
    wpr = [None if hh[i] is None else (0.0 if hh[i] == ll[i] else 100 * (c[i] - hh[i]) / (hh[i] - ll[i])) for i in range(n)]
    e13 = ta.ema_tv(c, 13)
    bull = [a - e for a, e in zip(h, e13)]; bear = [a - e for a, e in zip(l, e13)]
    bp = [None] + [c[i] - min(l[i], c[i - 1]) for i in range(1, n)]
    tr = [None] + [max(h[i], c[i - 1]) - min(l[i], c[i - 1]) for i in range(1, n)]
    def uo(i):
        def a(k):
            s = sum(tr[i - k + 1:i + 1]); return sum(bp[i - k + 1:i + 1]) / s
        return 100 * (4 * a(7) + 2 * a(14) + a(28)) / 7
    tr_e = ta.ema_tv(c, 50); tr_s = ta.sma(c, 50)
    s = lambda b, x: 1 if b else (-1 if x else 0)
    V = {}
    rng = range(n - 300, n)
    V["rsi"] = {"std": [s(r[i] < 30 and r[i] > r[i-1], r[i] > 70 and r[i] < r[i-1]) for i in rng],
                "lvl": [s(r[i] < 30, r[i] > 70) for i in rng]}
    V["sto"] = {"std": [s(sk[i] < 20 and sd[i] < 20 and sk[i] > sd[i], sk[i] > 80 and sd[i] > 80 and sk[i] < sd[i]) for i in rng],
                "lvl": [s(sk[i] < 20 and sd[i] < 20, sk[i] > 80 and sd[i] > 80) for i in rng],
                "k": [s(sk[i] < 20 and sk[i] > sd[i], sk[i] > 80 and sk[i] < sd[i]) for i in rng]}
    V["cci"] = {"std": [s(cc[i] < -100 and cc[i] > cc[i-1], cc[i] > 100 and cc[i] < cc[i-1]) for i in rng],
                "lvl": [s(cc[i] < -100, cc[i] > 100) for i in rng]}
    V["adx"] = {"rise": [s(pdi[i] > ndi[i] and ax[i] > 20 and ax[i] > ax[i-1], pdi[i] < ndi[i] and ax[i] > 20 and ax[i] > ax[i-1]) for i in rng],
                "help": [s(pdi[i] > ndi[i] and ax[i] > 20 and ax[i] > ax[i-1], pdi[i] < ndi[i] and ax[i] > 20 and ax[i] < ax[i-1]) for i in rng],
                "lvl": [s(pdi[i] > ndi[i] and ax[i] > 20, pdi[i] < ndi[i] and ax[i] > 20) for i in rng]}
    def ao_std(i):
        b = (ao[i] > 0 and ao[i-1] <= 0) or (ao[i] > 0 and ao[i-1] > 0 and ao[i] > ao[i-1] and ao[i-2] > ao[i-1])
        x = (ao[i] < 0 and ao[i-1] >= 0) or (ao[i] < 0 and ao[i-1] < 0 and ao[i] < ao[i-1] and ao[i-2] < ao[i-1])
        return s(b, x)
    def ao_any(i):
        b = (ao[i] > 0 and ao[i-1] <= 0) or (ao[i] > 0 and ao[i-1] > 0 and ao[i] > ao[i-1] and ao[i-2] > ao[i-1]) or (ao[i] > ao[i-1] and ao[i-1] < 0 and False)
        x = (ao[i] < 0 and ao[i-1] >= 0) or (ao[i] < 0 and ao[i-1] < 0 and ao[i] < ao[i-1] and ao[i-2] < ao[i-1])
        return s(b, x)
    V["ao"] = {"std": [ao_std(i) for i in rng],
               "rise": [s(ao[i] > ao[i-1], ao[i] < ao[i-1]) for i in rng],
               "sgnrise": [s(ao[i] > 0 and ao[i] > ao[i-1], ao[i] < 0 and ao[i] < ao[i-1]) for i in rng],
               "cross": [s(ao[i] > 0 and ao[i-1] <= 0, ao[i] < 0 and ao[i-1] >= 0) for i in rng],
               "saucer2": [s((ao[i] > 0 and ao[i-1] <= 0) or (ao[i] > 0 and ao[i] > ao[i-1] and ao[i-1] < ao[i-2]),
                             (ao[i] < 0 and ao[i-1] >= 0) or (ao[i] < 0 and ao[i] < ao[i-1] and ao[i-1] > ao[i-2])) for i in rng]}
    V["mom"] = {"std": [s(mom[i] > mom[i-1], mom[i] < mom[i-1]) for i in rng]}
    V["macd"] = {"std": [s(ml[i] > ms[i], ml[i] < ms[i]) for i in rng]}
    for tn, tm in (("e", tr_e), ("s", tr_s), ("n", None)):
        up = lambda i: True if tm is None else c[i] > tm[i]
        dn = lambda i: True if tm is None else c[i] < tm[i]
        V.setdefault("srsi", {})[tn] = [s(dn(i) and srk[i] < 20 and srd[i] < 20 and srk[i] > srd[i], up(i) and srk[i] > 80 and srd[i] > 80 and srk[i] < srd[i]) for i in rng]
        V.setdefault("bbp", {})[tn] = [s(up(i) and bear[i] < 0 and bear[i] > bear[i-1], dn(i) and bull[i] > 0 and bull[i] < bull[i-1]) for i in rng]
    V["bbp"]["sum"] = [s(bull[i] + bear[i] > 0 and (bull[i] + bear[i]) > (bull[i-1] + bear[i-1]), bull[i] + bear[i] < 0 and (bull[i] + bear[i]) < (bull[i-1] + bear[i-1])) for i in rng]
    V["bbp"]["sign"] = [s(bull[i] + bear[i] > 0, bull[i] + bear[i] < 0) for i in rng]
    V["wpr"] = {"std": [s(wpr[i] < -80 and wpr[i] > wpr[i-1], wpr[i] > -20 and wpr[i] < wpr[i-1]) for i in rng],
                "lvl": [s(wpr[i] < -80, wpr[i] > -20) for i in rng]}
    V["uo"] = {"std": [s(uo(i) > 70, uo(i) < 30) for i in rng],
               "50": [s(uo(i) > 50, uo(i) < 50) for i in rng],
               "inv": [s(uo(i) < 30, uo(i) > 70) for i in rng]}
    return V

allV = []
for sym, cs, vals in data:
    V = variants([x["h"] for x in cs], [x["l"] for x in cs], [x["c"] for x in cs], [x["v"] for x in cs])
    tvv = vals[-249:]
    allV.append((sym, V, tvv))
keys = list(allV[0][1].keys())
choice = {k: list(allV[0][1][k].keys())[0] for k in keys}
def score(ch):
    bad = 0
    for sym, V, tvv in allV:
        m = len(tvv)
        for j in range(m):
            tot = sum(V[k][ch[k]][300 - m + j] for k in keys)
            bad += tot != tvv[j]
    return bad
best = score(choice)
for _ in range(4):
    for k in keys:
        for opt in allV[0][1][k]:
            ch = dict(choice, **{k: opt})
            sc_ = score(ch)
            if sc_ < best:
                best, choice = sc_, ch
print("RESULT", best, "uyuşmaz /", sum(len(t) for _, _, t in allV), choice)
for k in keys:
    for opt in allV[0][1][k]:
        print("TRY", k, opt, score(dict(choice, **{k: opt})))
