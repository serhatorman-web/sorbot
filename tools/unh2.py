"""Geçici teşhis: UNH – hacmi sıfır mumlar (TradingView'de yok) çıkarılınca hacim profili."""
import sys, os, json, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as sc, indicators as ta
api = sc.Binance()
for shot_min in (1, 2, 3, 4, 5):
    shot = 1794690000000 + shot_min * 60000          # 21:0x UTC
    raw = api.get("/fapi/v1/klines", {"symbol": "UNHUSDT", "interval": "15m", "endTime": shot, "limit": 1000})
    cs = [{"t": int(k[0]), "h": float(k[2]), "l": float(k[3]), "bv": float(k[5])} for k in raw]
    m1 = api.get("/fapi/v1/klines", {"symbol": "UNHUSDT", "interval": "1m", "startTime": cs[-1]["t"], "endTime": shot - 1})
    if m1:
        cs[-1] = {"t": cs[-1]["t"], "h": max(float(k[2]) for k in m1), "l": min(float(k[3]) for k in m1), "bv": sum(float(k[5]) for k in m1)}
    zero = sum(1 for c in cs[-300:] if c["bv"] == 0)
    for label, arr in (("tümü", cs), ("hacimsiz mumlar çıkarıldı", [c for c in cs if c["bv"] > 0])):
        h = [c["h"] for c in arr]; l = [c["l"] for c in arr]; v = [c["bv"] for c in arr]
        a = ta.swing_anchor(h, l, 300)
        r = ta.volume_profile(h[a:], l[a:], v[a:], 24, 0.7)
        print(f"21:0{shot_min} UTC {label:28} n={len(arr)-a:3} (son 300'de hacimsiz {zero}) → VAH {r[0]:.2f} POC {r[1]:.2f} VAL {r[2]:.2f}   gösterge VAH 407.52 POC 405.57")
