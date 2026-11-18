"""Formasyon testi: (1) güncel mesaj örnekleri, (2) mum formasyonları ve kırılan grafik formasyonlarının sonucu."""
import json, sys, time, urllib.request, urllib.parse
sys.path.insert(0, ".")
import indicators as ta
import patterns as pt
import scanner

MAJ = ["BTC", "ETH", "XRP", "BNB", "SOL", "DOGE", "AVAX", "HYPE", "LINK", "SUI", "ADA", "ZEC", "LTC", "BCH", "NEAR", "UNI"]
ALT = ["AAVE", "ARB", "OP", "INJ", "TIA", "WLD", "APT", "SEI", "ENA", "PENDLE", "TAO", "FET", "ONDO", "JUP"]


def get(sym, tf, pages=1):
    out, end = [], None
    for _ in range(pages):
        p = {"symbol": sym + "USDT", "interval": tf, "limit": 1500}
        if end:
            p["endTime"] = end
        u = "https://www.binance.com/fapi/v1/klines?" + urllib.parse.urlencode(p)
        raw = json.load(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "x"}), timeout=30))
        if not raw:
            break
        out = raw + out
        end = raw[0][0] - 1
    now = int(time.time() * 1000)
    return [{"t": int(k[0]), "o": float(k[1]), "h": float(k[2]), "l": float(k[3]), "c": float(k[4])}
            for k in out if int(k[6]) < now]


# (1) Güncel örnek: 15dk sinyali gibi – 15m, 1h, 4h, 1d son 300 mum
print("=== GÜNCEL ÖRNEKLER (15dk sinyali varsayımı) ===")
counts = []
for sym in MAJ + ALT:
    forms = {}
    for tf in ("15m", "1h", "4h", "1d"):
        try:
            cs = get(sym, tf)[-300:]
            forms[tf] = scanner.tf_formations(cs)
        except Exception as e:  # noqa
            print("ERR", sym, tf, e)
    lines = scanner.formation_lines({"forms": forms, "meta": {}})
    counts.append(len(lines) - 1 if lines else 0)
    print(f"\n--- {sym} ({len(lines) - 1 if lines else 0} satır)")
    for x in lines:
        print(x)
print("\nsatır sayısı dağılımı:", sorted(counts), "ortalama", sum(counts) / len(counts))

# (2) Geçmiş test
print("\n=== GEÇMİŞ TEST ===")
H = (5, 10, 20)
C, G, B = {}, {}, {}


def acc(st, key, row):
    s = st.setdefault(key, {"n": 0})
    s["n"] += 1
    for k, v in row.items():
        s[k] = s.get(k, 0) + v


for tf in ("15m", "1h", "4h"):
    for sym in MAJ:
        try:
            cs = get(sym, tf, pages=1)
        except Exception as e:  # noqa
            print("ERR", sym, tf, e)
            continue
        o = [x["o"] for x in cs]; h = [x["h"] for x in cs]; l = [x["l"] for x in cs]; c = [x["c"] for x in cs]
        a = ta.atr(h, l, c, 14)
        n = len(c)
        seen = set()
        for i in range(150, n - 30):
            for s in (1, -1):
                acc(B, (tf, s), {f"w{x}": int(s * (c[i + x] - c[i]) > 0) for x in H})
            for ad, yon in pt.candle_patterns(o, h, l, c, a, i):
                if yon == 0:
                    continue
                acc(C, (tf, ad), {f"w{x}": int(yon * (c[i + x] - c[i]) > 0) for x in H})
            lo = max(0, i - 299)
            for g in pt.chart_patterns(h[lo:i + 1], l[lo:i + 1], c[lo:i + 1], a[lo:i + 1]):
                if g["durum"] != "kirildi":
                    continue
                key = (g["ad"], round(g.get("seviye", g.get("ust", 0)), 6))
                if any(k[0] == key[0] and abs(k[1] - key[1]) <= a[i] and i - k[2] < 40 for k in seen):
                    continue
                seen.add((key[0], key[1], i))
                d = g["kirilim"]
                tgt = g.get("hedef")
                hit = int(tgt is not None and any((d == 1 and h[k] >= tgt) or (d == -1 and l[k] <= tgt) for k in range(i + 1, i + 31)))
                row = {**{f"w{x}": int(d * (c[i + x] - c[i]) > 0) for x in H}, "hit": hit, "tg": int(tgt is not None)}
                acc(G, (tf, g["ad"] + (" ↑" if d == 1 else " ↓")), row)
                acc(G, (tf, "TÜM GRAFİK"), row)


def show(title, st, extra=False):
    print("\n" + title)
    for key in sorted(st):
        s = st[key]; nn = s["n"]
        line = f"{key[0]:4} {str(key[1]):24} {nn:6} " + " ".join(f"{s[f'w{x}'] / nn * 100:5.1f}%" for x in H)
        if extra and s.get("tg"):
            line += f"   hedefe ulaştı (30 mum): {s['hit'] / s['tg'] * 100:5.1f}%"
        print(line)


show("BAZ (rastgele mum, 1=long -1=short)  kaz5 kaz10 kaz20", B)
show("MUM FORMASYONLARI (beklenen yönde)  kaz5 kaz10 kaz20", C)
show("GRAFİK FORMASYONU KIRILIMLARI (kırılım yönünde)  kaz5 kaz10 kaz20", G, True)
