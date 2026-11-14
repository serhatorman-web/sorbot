"""Geçici teşhis: kural testi – pencere = son 300 mumdaki en eski uç noktadan (en yüksek/en düşük) bugüne."""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vpcal2 import profile, va1, m1_range, api
def run(sym, tf, ms, shot, tgt):
    raw = api.get("/fapi/v1/klines", {"symbol": sym, "interval": tf, "endTime": shot, "limit": 400})
    bars = [(int(k[0]), float(k[2]), float(k[3]), float(k[5])) for k in raw]
    closed = [b for b in bars if b[0] + ms <= shot]; forming = [b for b in bars if b[0] + ms > shot]
    m1 = m1_range(sym, closed[-310][0], shot)
    for incl in (0, 1):
        allb = closed + (forming if incl else [])
        if incl and forming:   # oluşan mumun o anki aralığı
            fm = [x for x in m1 if x[0] >= forming[0][0]]
            allb = closed + [(forming[0][0], max(x[1] for x in fm), min(x[2] for x in fm), sum(x[4] for x in fm))]
        seg = allb[-300:]
        ih = max(range(len(seg)), key=lambda i: seg[i][1]); il = min(range(len(seg)), key=lambda i: seg[i][2])
        start = min(ih, il); n_rule = len(seg) - start
        for label, n in (("kural", n_rule), ("kural_min150", max(150, n_rule)), ("150", 150)):
            w = allb[-n:]; hi = max(x[1] for x in w); lo = min(x[2] for x in w)
            for dist in ("mum", "1dk"):
                end = shot if incl else closed[-1][0] + ms
                items = [(x[1], x[2], x[3]) for x in w] if dist == "mum" else [(x[1], x[2], x[4]) for x in m1 if w[0][0] <= x[0] < end]
                step, vol = profile(hi, lo, items); b, p, a = va1(vol)
                vals = [round(lo + (r + .5) * step, 4) for r in (b, p, a)]
                ok = sum(1 for x, t in zip(vals, tgt) if abs(x - t) / t < 0.0005)
                print(f"{sym} {tf} oluşan={incl} {label:13} n={n:3} {dist}: {vals} hedef {tgt} → {ok}/3")
NOW = int(time.time() * 1000)
run("XRPUSDT", "4h", 4 * 3600e3, NOW, (1.5134, 1.2992, 1.1653))
run("SOLUSDT", "4h", 4 * 3600e3, NOW, (110.49, 103.80, 79.26))
run("BTCUSDT", "4h", 4 * 3600e3, NOW, (85857.1, 81215.3, 76573.5))
run("ETHUSDT", "4h", 4 * 3600e3, NOW, (2556.77, 2435.55, 2233.52))
# ZRO 15dk: 14.11 19:41 TSİ (16:41 UTC) ekran görüntüsü – VAH 1.5998, POC 1.5797, VAL 1.5259
run("ZROUSDT", "15m", 900e3, 1794677580000 - 600000, (1.5998, 1.5797, 1.5259))
