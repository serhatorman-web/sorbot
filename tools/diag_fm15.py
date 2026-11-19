"""15dk canlı formasyon resimlerinin (🧩 FORMASYON TAMAMLANDI) başarı testi – live_images ile aynı kurallar."""
import sys, time, statistics as st
from multiprocessing import Pool
sys.path.insert(0, ".")
from scanner import Binance, parse_klines, follow_through
import indicators as ta
import patterns as pt

DAYS, NSYM, H = 60, 80, 96          # 60 gün, 80 sembol, sonuç 96 mum (24 saat) içinde
EXCL = {"Fincan Kulp", "Ters Fincan Kulp"}


def fetch(api, sym, now):
    out, end = [], now
    need = DAYS * 96 + 400
    while len(out) < need:
        raw = api.get("/fapi/v1/klines", {"symbol": sym, "interval": "15m", "limit": 1500, "endTime": end})
        if not raw:
            break
        out = parse_klines(raw, now) + out
        end = int(raw[0][0]) - 1
        if len(raw) < 1500:
            break
    return out


def run(args):
    sym, cs = args
    H_ = [x["h"] for x in cs]; L = [x["l"] for x in cs]; C = [x["c"] for x in cs]; V = [x["v"] for x in cs]
    vma = ta.sma(V, 20)
    atr_all = ta.atr(H_, L, C, 14)
    N = len(cs)
    ev, sent = [], {}
    for i in range(400, N - 1):
        lo = max(0, i + 1 - 300)
        h, l, c = H_[lo:i + 1], L[lo:i + 1], C[lo:i + 1]
        n = len(c)
        a = ta.atr(h, l, c, 14)
        for g in pt.chart_patterns(h, l, c, a):
            kb = (g.get("ciz") or {}).get("kb")
            if g["durum"] != "kirildi" or kb is None or n - 1 - kb > 3 or g["ad"] in EXCL:
                continue
            vr = V[lo + kb] / vma[lo + kb - 1] if vma[lo + kb - 1] else 0
            if vr < 1.5:
                if kb == n - 1 or follow_through(cs[lo:i + 1], kb, g["kirilim"], n - 1) is None:
                    continue
            key = (g["ad"], lo + kb)
            if key in sent or (g["ad"] in sent and i - sent[g["ad"]] <= 10):
                continue
            sent[key] = i; sent[g["ad"]] = i
            d = g["kirilim"]
            e = C[i]; r = 1.5 * atr_all[i]
            if not r:
                continue
            hed = g.get("hedef")
            res = {"sym": sym, "ad": g["ad"], "d": d, "ago": n - 1 - kb, "vol": vr >= 1.5}
            # 1R/2R/3R ve formasyon hedefi: stoptan önce mi? (aynı mumda ikisi → stop)
            for name, tgt in (("tp1", e + d * r), ("tp2", e + d * 2 * r), ("tp3", e + d * 3 * r),
                              ("hedef", hed if hed and (hed - e) * d > 0 else None)):
                out = None
                if tgt is None:
                    res[name] = "yok"; continue
                for k in range(i + 1, min(N, i + 1 + H)):
                    if (L[k] - (e - r)) <= 0 if d == 1 else (H_[k] - (e + r)) >= 0:
                        out = "stop"; break
                    if (H_[k] - tgt) >= 0 if d == 1 else (L[k] - tgt) <= 0:
                        out = "tp"; break
                res[name] = out or "acik"
            # hedef uzaklığı (R cinsinden)
            res["hedef_R"] = abs(hed - e) / r if hed else None
            # 4 / 16 / 96 mum sonra yön doğru mu, kaç ATR
            for m in (4, 16, 96):
                if i + m < N:
                    res[f"m{m}"] = (C[i + m] - e) * d / atr_all[i]
            ev.append(res)
    return ev


if __name__ == "__main__":
    api = Binance()
    now = int(time.time() * 1000)
    info = api.get("/fapi/v1/exchangeInfo")
    ok = {s["symbol"] for s in info["symbols"] if s["contractType"] == "PERPETUAL" and s["quoteAsset"] == "USDT"
          and s["status"] == "TRADING"}
    tick = sorted((t for t in api.get("/fapi/v1/ticker/24hr") if t["symbol"] in ok),
                  key=lambda t: -float(t["quoteVolume"]))[:NSYM]
    data = []
    for t in tick:
        try:
            data.append((t["symbol"], fetch(api, t["symbol"], now)))
        except Exception as ex:  # noqa: BLE001
            print("FM| veri hatası", t["symbol"], ex)
    with Pool(4) as p:
        ev = [e for part in p.map(run, data) for e in part]

    def rep(title, E):
        if not E:
            print(f"FM| {title}: 0 olay"); return
        line = f"FM| {title}: {len(E)} olay"
        for name, w in (("tp1", 1), ("tp2", 2), ("tp3", 3)):
            done = [e for e in E if e[name] in ("tp", "stop")]
            wins = sum(e[name] == "tp" for e in done)
            if done:
                R = (wins * w - (len(done) - wins)) / len(done)
                line += f" | {name.upper()} %{100 * wins / len(done):.0f} ({R:+.2f}R)"
        hd = [e for e in E if e["hedef"] in ("tp", "stop")]
        if hd:
            wins = [e for e in hd if e["hedef"] == "tp"]
            R = (sum(e["hedef_R"] for e in wins) - (len(hd) - len(wins))) / len(hd)
            line += f" | hedef %{100 * len(wins) / len(hd):.0f} ({R:+.2f}R, ort. hedef {st.mean(e['hedef_R'] for e in hd):.1f}R)"
        for m in (4, 16, 96):
            xs = [e[f"m{m}"] for e in E if f"m{m}" in e]
            if xs:
                line += f" | {m * 15 // 60 if m >= 4 else m}s sonra doğru yön %{100 * sum(x > 0 for x in xs) / len(xs):.0f} ort {st.mean(xs):+.2f}ATR"
        print(line, flush=True)

    print(f"FM| {len(data)} sembol, {DAYS} gün, 15dk")
    rep("TÜMÜ", ev)
    rep("YUKARI kırılım", [e for e in ev if e["d"] == 1])
    rep("AŞAĞI kırılım", [e for e in ev if e["d"] == -1])
    rep("Hacimli kırılım", [e for e in ev if e["vol"]])
    rep("Hacimsiz+devam onayı", [e for e in ev if not e["vol"]])
    for ad in sorted({e["ad"] for e in ev}):
        rep(ad, [e for e in ev if e["ad"] == ad])
