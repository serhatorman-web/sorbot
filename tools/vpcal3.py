"""Geçici teşhis: pencere başlangıcı yapısal bir noktaya mı bağlı?"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scanner as sc
from vpcal2 import profile, va1, TARGET, m1_range, H4, api
import datetime as dt
SHOT = int(time.time() * 1000)
for sym, tgt in TARGET.items():
    raw = api.get("/fapi/v1/klines", {"symbol": sym, "interval": "4h", "endTime": SHOT, "limit": 1000})
    bars = [(int(k[0]), float(k[2]), float(k[3]), float(k[5])) for k in raw]
    closed = bars[:-1]
    oks = []
    for n in range(100, 900):
        w = closed[-n:]
        hi = max(x[1] for x in w); lo = min(x[2] for x in w)
        step, vol = profile(hi, lo, [(x[1], x[2], x[3]) for x in w])
        b, p, a = va1(vol)
        vals = [lo + (r + 0.5) * step for r in (b, p, a)]
        ok = sum(1 for x, t in zip(vals, tgt) if abs(x - t) / t < 0.002)
        if ok >= 2: oks.append((n, ok, [round(x, 4) for x in vals]))
    print(sym, "eşleşen n:", [(n, ok) for n, ok, _ in oks][:30])
    if oks: print("   ör.", oks[0])
    T = lambda i: dt.datetime.utcfromtimestamp(closed[i][0] / 1000).strftime("%Y-%m-%d %H:%M")
    for L in (300, 500, 900):
        seg = closed[-L:]
        ih = max(range(len(seg)), key=lambda i: seg[i][1]); il = min(range(len(seg)), key=lambda i: seg[i][2])
        print(f"   son {L}: en yüksek {seg[ih][1]} {len(seg)-ih} mum önce ({T(len(closed)-len(seg)+ih)}), en düşük {seg[il][2]} {len(seg)-il} mum önce")
