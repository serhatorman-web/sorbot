"""Geçici teşhis: bugünkü değişikliklerin canlı veriyle kontrolü."""
import sys, os, time, json, traceback, collections
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as sc, indicators as ta
cfg0 = json.load(open("config.json"))
api = sc.Binance(); now = int(time.time() * 1000)
info = api.get("/fapi/v1/exchangeInfo")
syms = {s["symbol"]: s for s in info["symbols"] if s.get("contractType") == "PERPETUAL" and s["symbol"].endswith("USDT") and s.get("status") == "TRADING"}
tick = api.get("/fapi/v1/ticker/24hr")
top = [t["symbol"] for t in sorted(tick, key=lambda t: -float(t["quoteVolume"])) if t["symbol"] in syms][:40]
err = collections.Counter(); stats = collections.Counter(); bad = []
for sym in top:
    for tf in ("15m", "1h", "4h"):
        try:
            cfg = dict(cfg0, timeframe=tf)
            cs = sc.parse_klines(api.get("/fapi/v1/klines", {"symbol": sym, "interval": tf, "limit": 300}), now)
            f = sc.compute_features(cs, cfg); i = len(cs) - 1
            prec = sc.tick_decimals(syms[sym])
            res = {"f": f, "i": i, "meta": {"symbol": sym, "precision": prec}}
            h, l, c = f["h"], f["l"], f["c"]; a = ta.atr(h, l, c, 14)
            # --- Ichimoku: bulut rengi bağımsız hesap
            mid = lambda k, n: (max(h[k-n+1:k+1]) + min(l[k-n+1:k+1])) / 2
            j = i - 26
            sa_j = (mid(j, 9) + mid(j, 26)) / 2; sb_j = mid(j, 52)
            sa_n = (mid(i, 9) + mid(i, 26)) / 2; sb_n = mid(i, 52)
            lines = sc.ichimoku_lines(res, "long", cfg)
            exp_now = "(yeşil)" if sa_j > sb_j else "(kırmızı)"
            exp_fut = "yeşil" if sa_n > sb_n else "kırmızı"
            if abs(min(sa_j, sb_j) - f["ichi_bot"][i]) > 1e-9 or exp_now not in lines[1]:
                bad.append(("bulut", sym, tf, lines[1], sa_j, sb_j))
            fl = [x for x in lines if "İleri bulut" in x][0]
            if f": {exp_fut} ·" not in fl:
                bad.append(("ileri", sym, tf, fl, sa_n, sb_n))
            if abs(f["ichi_tenkan"][i] - mid(i, 9)) > 1e-9 or abs(f["ichi_kijun"][i] - mid(i, 26)) > 1e-9:
                bad.append(("tk", sym, tf))
            for x in lines[1:4]:
                stats["ichi " + x.split(":")[1].split("·")[-1].strip()[:28]] += 1
            # --- Trend çizgisi: yeni kurallar
            for ev in ta.trendline_break(h[:i+1], l[:i+1], c[:i+1]):
                stats["tl " + ev["retest"]] += 1
                brk = i - ev["bars_ago"]
                kind = ev["type"]
                # kırılımdan sonra tüm kapanışlar kırılım tarafında olmalı (en son kırılım)
                piv = ta._pivots(l if kind == "rising" else h, 5, 5, "low" if kind == "rising" else "high")
                src = l if kind == "rising" else h; p1, p2 = piv[-2], piv[-1]
                L = lambda k: src[p2] + (src[p2] - src[p1]) / (p2 - p1) * (k - p2)
                side = lambda k: c[k] < L(k) if kind == "rising" else c[k] > L(k)
                if not all(side(k) for k in range(brk, i + 1)) or side(brk - 1):
                    bad.append(("tl-brk", sym, tf, ev))
                if ev["retest"] == "away" and abs(c[i] - L(i)) <= 2.5 * a[i]:
                    bad.append(("tl-away", sym, tf, ev))
            # --- Hacim profili
            sc.compute_volume_profile(res, cfg)
            for name, ev in (res.get("vp_ev") or {}).items():
                stats[f"vp {ev['kind']}-{ev['state']}"] += 1
                if ev["state"] == "away" and abs(c[i] - ev["level"]) <= 2.5 * a[i]:
                    bad.append(("vp-away", sym, tf, name, ev))
            vl = sc.volume_profile_lines(res, cfg)
            for x in vl[1:]:
                lv = x.split("fiyat ")[1].split(" ")[0]
                if "." in lv and len(lv.split(".")[1]) != max(2, min(prec, 8)):
                    bad.append(("ondalık", sym, tf, x, prec))
        except Exception:
            err[sym + " " + tf] += 1; traceback.print_exc()
print("SEMBOL", len(top), "HATA", dict(err))
print("DURUMLAR", json.dumps(dict(sorted(stats.items())), ensure_ascii=False))
print("SORUNLAR", len(bad))
for b in bad[:30]: print("BAD", b)
