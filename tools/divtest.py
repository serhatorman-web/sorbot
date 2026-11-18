"""RSI uyumsuzluk testi: bot uyumsuzluğu gösterdiğinde sonra ne oluyor?"""
import json, sys, urllib.request, urllib.parse
sys.path.insert(0, ".")
import indicators as ta

SYMS = ["BTC", "ETH", "XRP", "BNB", "SOL", "DOGE", "AVAX", "HYPE", "LINK", "SUI", "ADA", "ZEC", "LTC", "BCH", "NEAR", "UNI",
        "AAVE", "ARB", "OP", "INJ", "TIA", "WLD", "APT", "SEI", "ENA", "PENDLE", "TAO", "FET", "ONDO", "JUP"]
TFS = ["15m", "1h", "4h"]
LEFT = RIGHT = 5
H = (5, 10, 20)


def get(sym, tf):
    out, end = [], None
    for _ in range(3):
        p = {"symbol": sym + "USDT", "interval": tf, "limit": 1500}
        if end:
            p["endTime"] = end
        u = "https://www.binance.com/fapi/v1/klines?" + urllib.parse.urlencode(p)
        raw = json.load(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "x"}), timeout=30))
        if not raw:
            break
        out = raw + out
        end = raw[0][0] - 1
    return [float(x[2]) for x in out], [float(x[3]) for x in out], [float(x[4]) for x in out]


def pivots(r, n):
    lo, hi = [], []
    for p in range(LEFT, n - RIGHT):
        w = r[p - LEFT:p + RIGHT + 1]
        if r[p] is None or any(x is None for x in w):
            continue
        if r[p] == min(w):
            lo.append(p)
        if r[p] == max(w):
            hi.append(p)
    return lo, hi


stats = {}
def add(key, d):
    s = stats.setdefault(key, {"n": 0, **{f"win{h}": 0 for h in H}, **{f"ret{h}": 0.0 for h in H}, "inval": 0, "mfe": 0.0, "mae": 0.0})
    s["n"] += 1
    for k, v in d.items():
        s[k] += v

for tf in TFS:
    for sym in SYMS:
        try:
            h, l, c = get(sym, tf)
        except Exception as e:  # noqa
            print("ERR", sym, tf, e); continue
        n = len(c)
        r = ta.rsi(c, 14)
        lo, hi = pivots(r, n)
        # baz: rastgele her mum
        for i in range(300, n - 20, 3):
            for side in (1, -1):
                add((tf, "BAZ", side), {**{f"win{x}": int(side * (c[i + x] - c[i]) > 0) for x in H},
                                         **{f"ret{x}": side * (c[i + x] / c[i] - 1) * 100 for x in H}})
        for piv, bull in ((lo, True), (hi, False)):
            for a, b in zip(piv, piv[1:]):
                if not (5 <= b - a <= 60):
                    continue
                if bull and not (r[b] > r[a] and l[b] < l[a]):
                    continue
                if not bull and not (r[b] < r[a] and h[b] > h[a]):
                    continue
                d = b + RIGHT          # uyumsuzluğun kesinleştiği (botun görebildiği ilk) mum
                if d + 20 >= n or d < 200:
                    continue
                side = 1 if bull else -1
                ext = l[b] if bull else h[b]
                # gönderim anında çoktan bozulmuş mu? (d'ye kadar fiyat pivot dibini/tepesini kapanışla geçti mi)
                broken_now = any((c[k] < ext) if bull else (c[k] > ext) for k in range(b + 1, d + 1))
                inval = int(any((c[k] < ext) if bull else (c[k] > ext) for k in range(d + 1, d + 21)))
                fut = c[d + 1:d + 21]
                mfe = max(side * (x / c[d] - 1) * 100 for x in fut)
                mae = min(side * (x / c[d] - 1) * 100 for x in fut)
                row = {**{f"win{x}": int(side * (c[d + x] - c[d]) > 0) for x in H},
                       **{f"ret{x}": side * (c[d + x] / c[d] - 1) * 100 for x in H}, "inval": inval, "mfe": mfe, "mae": mae}
                name = "POZ" if bull else "NEG"
                add((tf, name, side), row)
                add((tf, name + ("-bozuk" if broken_now else "-sağlam"), side), row)
                # trend filtresi: fiyat EMA200 altında mı (pozitif uyumsuzluk düşüş trendinde)
                e = ta.ema(c[:d + 1], 200)[-1] if hasattr(ta, "ema") else None
                if e:
                    add((tf, name + ("-trendYönünde" if (c[d] > e) == bull else "-trendTersi"), side), row)

print(f"{'TF':4} {'grup':20} {'adet':>5} " + " ".join(f"{'kaz'+str(x):>6} {'ort'+str(x):>7}" for x in H) + f" {'bozuldu':>8} {'MFE':>6} {'MAE':>6}")
for (tf, name, side), s in sorted(stats.items(), key=lambda kv: (TFS.index(kv[0][0]), kv[0][1], kv[0][2])):
    nn = s["n"]
    if name == "BAZ":
        name = "BAZ-long" if side == 1 else "BAZ-short"
    line = f"{tf:4} {name:20} {nn:5} " + " ".join(f"{s[f'win{x}'] / nn * 100:5.1f}% {s[f'ret{x}'] / nn:+6.2f}%" for x in H)
    if not name.startswith("BAZ"):
        line += f" {s['inval'] / nn * 100:7.1f}% {s['mfe'] / nn:+5.2f}% {s['mae'] / nn:+5.2f}%"
    print(line)
