"""Price action formasyon testi.
A) Supertrend sinyallerinde: formasyon VAR olan sinyaller ile YOK olanların sonucu.
B) Her mumda (sinyalden bağımsız): formasyon çıkınca fiyat beklenen yöne gidiyor mu, rastgele muma göre."""
import json, sys, urllib.request, urllib.parse
sys.path.insert(0, ".")
import indicators as ta
import scanner

SYMS = ["BTC", "ETH", "XRP", "BNB", "SOL", "DOGE", "AVAX", "HYPE", "LINK", "SUI", "ADA", "ZEC", "LTC", "BCH", "NEAR", "UNI",
        "AAVE", "ARB", "OP", "INJ", "TIA", "WLD", "APT", "SEI", "ENA", "PENDLE", "TAO", "FET", "ONDO", "JUP"]
TFS = ["15m", "1h", "4h", "1d"]
KEYS = ["pa_engulf", "pa_hammer", "pa_star", "pa_inside_break", "pa_strong_close", "pa_bos", "pa_structure", "HİÇBİRİ"]
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
        if len(raw) < 1500:
            break
        end = raw[0][0] - 1
    return out[:-1]  # son (oluşan) mum hariç


A, B = {}, {}


def acc(store, key, row):
    s = store.setdefault(key, {"n": 0})
    s["n"] += 1
    for k, v in row.items():
        s[k] = s.get(k, 0) + v


for tf in TFS:
    for sym in SYMS:
        try:
            raw = get(sym, tf)
        except Exception as e:  # noqa
            print("ERR", sym, tf, e)
            continue
        o = [float(x[1]) for x in raw]; h = [float(x[2]) for x in raw]
        l = [float(x[3]) for x in raw]; c = [float(x[4]) for x in raw]
        n = len(c)
        if n < 300:
            continue
        f = {"o": o, "h": h, "l": l, "c": c, "atr": ta.atr(h, l, c, 14)}
        st, _ = ta.supertrend(h, l, c, 10, 3.0)
        # A) Supertrend sinyalleri – işlem ters sinyale kadar tutulur
        flips = [i for i in range(60, n) if st[i] is not None and st[i - 1] is not None and st[i] != st[i - 1]]
        for j, i in enumerate(flips):
            s = st[i]
            if i + 20 >= n:
                continue
            ex = flips[j + 1] if j + 1 < len(flips) else None
            if ex is None:
                continue
            trade = s * (c[ex] / c[i] - 1) * 100
            row = {**{f"w{x}": int(s * (c[i + x] - c[i]) > 0) for x in H},
                   **{f"r{x}": s * (c[i + x] / c[i] - 1) * 100 for x in H},
                   "tw": int(trade > 0), "tr": trade}
            pa = scanner.signal_price_action(f, i, s)
            hit = [k for k in KEYS[:-1] if pa.get(k)]
            acc(A, (tf, "TÜM SİNYALLER"), row)
            for k in hit:
                acc(A, (tf, k), row)
            if not hit:
                acc(A, (tf, "HİÇBİRİ"), row)
            acc(A, (tf, f"formasyon sayısı {min(len(hit), 3)}{'+' if len(hit) >= 3 else ''}"), row)
        # B) her mumda formasyon (iki yön)
        for i in range(60, n - 20):
            for s in (1, -1):
                row = {**{f"w{x}": int(s * (c[i + x] - c[i]) > 0) for x in H},
                       **{f"r{x}": s * (c[i + x] / c[i] - 1) * 100 for x in H}}
                acc(B, (tf, s, "BAZ"), row)
                pa = scanner.signal_price_action(f, i, s)
                for k in KEYS[:-1]:
                    if pa.get(k):
                        acc(B, (tf, s, k), row)


def show(title, store, keyfn):
    print("\n" + title)
    print(f"{'TF':4} {'grup':26} {'adet':>6} " + " ".join(f"{'kaz'+str(x):>6} {'ort'+str(x):>7}" for x in H)
          + (f" {'işlem kaz':>9} {'işlem ort':>9}" if store is A else ""))
    for key in sorted(store, key=keyfn):
        s = store[key]; nn = s["n"]
        name = key[1] if store is A else ("LONG " if key[1] == 1 else "SHORT ") + key[2]
        line = f"{key[0]:4} {name:26} {nn:6} " + " ".join(f"{s[f'w{x}'] / nn * 100:5.1f}% {s[f'r{x}'] / nn:+6.2f}%" for x in H)
        if store is A:
            line += f" {s['tw'] / nn * 100:8.1f}% {s['tr'] / nn:+8.2f}%"
        print(line)


show("A) SUPERTREND SİNYALLERİNDE FORMASYON (kaz = sinyal yönünde, işlem = ters sinyale kadar)", A,
     lambda k: (TFS.index(k[0]), k[1]))
show("B) HER MUMDA FORMASYON (sinyalden bağımsız)", B, lambda k: (TFS.index(k[0]), -k[1], k[2] != "BAZ", k[2]))
