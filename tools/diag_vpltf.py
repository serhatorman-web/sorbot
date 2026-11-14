import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as sc
api = sc.Binance()
raw = api.get("/fapi/v1/klines", {"symbol": "BTCUSDT", "interval": "30m", "limit": 150})
cs = [{"h": float(r[2]), "l": float(r[3]), "v": float(r[5]), "c": float(r[4]), "o": float(r[1])} for r in raw]
H = [x["h"] for x in cs]; L = [x["l"] for x in cs]; V = [x["v"] for x in cs]
rows = 24; lo, hi = min(L), max(H); step = (hi - lo) / rows
bins = [0.0] * rows
for h, l, v in zip(H, L, V):
    for k in range(max(0, int((l - lo) / step)), min(rows - 1, int((h - lo) / step)) + 1):
        b_lo, b_hi = lo + k * step, lo + (k + 1) * step
        ov = min(h, b_hi) - max(l, b_lo)
        if ov > 0 and h > l:
            bins[k] += v * ov / (h - l)
tot = sum(bins); poc = max(range(rows), key=lambda k: bins[k])
print("aralık", lo, hi, "step", step, "poc satır", poc)
print("bins %", [round(b / tot * 100, 1) for b in bins])
mid = lambda k: round(lo + (k + 0.5) * step, 1)
def greedy(stop_before=False):
    a = b = poc; acc = bins[poc]
    while acc < 0.7 * tot and (a > 0 or b < rows - 1):
        up = bins[b + 1] if b < rows - 1 else -1; dn = bins[a - 1] if a > 0 else -1
        if up >= dn: b += 1; acc += up
        else: a -= 1; acc += dn
    return a, b
def tworow():
    a = b = poc; acc = bins[poc]
    while acc < 0.7 * tot and (a > 0 or b < rows - 1):
        up = sum(bins[b + 1:b + 3]) if b < rows - 1 else -1
        dn = sum(bins[max(0, a - 2):a]) if a > 0 else -1
        if up >= dn: nb = min(rows - 1, b + 2); acc += sum(bins[b + 1:nb + 1]); b = nb
        else: na = max(0, a - 2); acc += sum(bins[na:a]); a = na
    return a, b
for name, fn in (("greedy", greedy), ("iki satır", tworow)):
    a, b = fn()
    print(name, "satır", a, b, "| orta noktalar VAL/POC/VAH:", mid(a), mid(poc), mid(b), "| sınırlar:", round(lo + a * step, 1), round(lo + (b + 1) * step, 1))
print("hedef: VAL 65242.3 POC 68891.8 VAH 70919.2")
