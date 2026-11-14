"""Geçici teşhis: XRP ve genel kural testi: pencere = son L mumdaki en yüksek tepeden (veya en düşük dipten) bugüne."""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vpcal2 import profile, va1, TARGET, m1_range, H4, api
SHOT = int(time.time() * 1000)
for sym in ("XRPUSDT", "BTCUSDT"):
    tgt = TARGET[sym]
    raw = api.get("/fapi/v1/klines", {"symbol": sym, "interval": "4h", "endTime": SHOT, "limit": 1000})
    bars = [(int(k[0]), float(k[2]), float(k[3]), float(k[5])) for k in raw]; closed = bars[:-1]
    m1 = m1_range(sym, closed[-330][0], SHOT)
    for n in list(range(296, 303)) + [316, 317, 318]:
        w = closed[-n:]; hi = max(x[1] for x in w); lo = min(x[2] for x in w)
        for dist in ("mum", "1dk"):
            items = [(x[1], x[2], x[3]) for x in w] if dist == "mum" else [(x[1], x[2], x[4]) for x in m1 if x[0] >= w[0][0] and x[0] < closed[-1][0] + H4]
            step, vol = profile(hi, lo, items); b, p, a = va1(vol)
            print(sym, n, dist, [round(lo + (r + .5) * step, 4) for r in (b, p, a)], "hedef", tgt, "aralık", lo, hi)
