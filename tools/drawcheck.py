"""Trend çizgisi ve formasyon çizimlerinin doğruluk kontrolü (geçici).
Her kırılım için kuralları tek tek doğrular, hataları yazar ve örnek resimleri loga basar."""
import base64, json, sys, time, urllib.request, urllib.parse
sys.path.insert(0, ".")
import scanner, indicators as ta, patterns as pt

SYMS = ["BTC", "ETH", "XRP", "BNB", "SOL", "DOGE", "AVAX", "HYPE", "LINK", "SUI", "ADA", "ZEC", "LTC", "BCH", "NEAR", "UNI",
        "AAVE", "ARB", "OP", "INJ", "TIA", "WLD", "APT", "SEI", "ENA", "PENDLE", "TAO", "FET", "ONDO", "JUP"]
now = int(time.time() * 1000)
tl_n = tl_bad = fm_n = fm_bad = 0
imgs = []
for sym in SYMS:
    for tf in ("15m", "1h", "4h", "1d"):
        u = "https://www.binance.com/fapi/v1/klines?" + urllib.parse.urlencode({"symbol": sym + "USDT", "interval": tf, "limit": 300})
        cs = scanner.parse_klines(json.load(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "x"}), timeout=30)), now)
        o = [x["o"] for x in cs]; h = [x["h"] for x in cs]; l = [x["l"] for x in cs]; c = [x["c"] for x in cs]
        a = ta.atr(h, l, c, 14)
        n = len(c)
        # ── trend çizgileri ──
        for ev in ta.trendlines_close(h, l, c):
            if ev["state"] != "broken":
                continue
            tl_n += 1
            A, B = ev["a"], ev["b"]
            m = (c[B] - c[A]) / (B - A)
            ln = lambda k: c[B] + m * (k - B)
            d = 1 if ev["type"] == "falling" else -1
            kb = n - 1 - ev["bars_ago"]
            errs = []
            if (d == 1 and m >= 0) or (d == -1 and m <= 0):
                errs.append("eğim yönü yanlış")
            if abs(ln(n - 1) - ev["level"]) > 1e-9 * max(1, abs(ev["level"])):
                errs.append("resimdeki çizgi botun çizgisiyle aynı değil")
            for k in range(A + 1, B):
                if d * (c[k] - ln(k)) > 0.25 * (a[k] or 0) + 1e-12:
                    errs.append(f"iki temas arasında kapanış çizginin öbür tarafında ({k})"); break
            if not d * (c[kb] - ln(kb)) > 0.1 * a[kb]:
                errs.append("kırılım mumu çizgiyi kapanışla geçmemiş")
            if kb - 1 > B and d * (c[kb - 1] - ln(kb - 1)) > 0.1 * a[kb - 1]:
                errs.append("kırılım daha önce olmuş (ilk kırılım mumu değil)")
            # kırılımdan önceki kapanışla geçişler ancak ardından 3 mumdan uzun içeride kalındıysa (başarısız kırılım) kabul
            last_out, run, failed_ok = None, 0, True
            for k in range(B + 1, kb):
                if d * (c[k] - ln(k)) > 0.1 * a[k]:
                    last_out, run = k, 0
                else:
                    run += 1
            if last_out is not None and run <= 3:
                errs.append(f"kırılımdan önce de kapanışla geçilmiş ve içeride kısa kalmış ({last_out})")
            elif last_out is not None:
                print("TLNOT", sym, tf, ev["type"], f"önceki başarısız kırılım {last_out}, sonra {run} mum içeride")
            run = 0
            for k in range(kb + 1, n):
                run = run + 1 if d * (c[k] - ln(k)) <= 0.1 * a[k] else 0
                if run > 3:
                    errs.append("kırılımdan sonra 3 mumdan uzun süre çizginin içinde kalmış"); break
            print("TL", sym, tf, ev["type"], "kırılım", ev["bars_ago"], "mum önce", ev["retest"], "OK" if not errs else "")
            if errs:
                tl_bad += 1
                print("TLHATA", sym, tf, ev["type"], errs)
        # ── formasyonlar ──
        for g in pt.chart_patterns(h, l, c, a):
            if g["durum"] != "kirildi":
                continue
            fm_n += 1
            d = g["kirilim"]
            ciz = g["ciz"]; kb = ciz["kb"]
            errs = []
            lvl = g.get("seviye", g.get("ust") if d == 1 else g.get("alt"))
            if kb is None or not d * (c[kb] - lvl) > 0:
                errs.append("kırılım mumu seviyeyi kapanışla geçmemiş")
            if g.get("_simdi") is not None and d * (c[-1] - g["_simdi"]) < 0:
                errs.append("fiyat kırılım seviyesinin gerisine dönmüş ama yazılmış")
            if g.get("hedef") is not None and d * (g["hedef"] - lvl) <= 0:
                errs.append("hedef ters yönde")
            for (k1, p1), (k2, p2) in ciz["cizgiler"]:
                if not (0 <= k1 <= k2 < n):
                    errs.append("çizgi indeksi geçersiz")
            if g["ad"] in pt.BOXES:
                (u1, u2), (l1, l2) = ciz["cizgiler"]
                mu = (u2[1] - u1[1]) / (u2[0] - u1[0]); ml = (l2[1] - l1[1]) / (l2[0] - l1[0])
                U = lambda k: u1[1] + mu * (k - u1[0]); L = lambda k: l1[1] + ml * (k - l1[0])
                for k, p in ciz["noktalar"]:
                    if min(abs(p - U(k)), abs(p - L(k))) > 0.5 * a[-1] + 1e-12:
                        errs.append(f"pivot çizgiye uzak ({k})")
                for k in range(u1[0], kb):
                    if h[k] > U(k) + 0.75 * a[-1] or l[k] < L(k) - 0.75 * a[-1]:
                        errs.append(f"formasyon içinde fiyat çizgilerin dışına taşmış ({k})"); break
            if g["ad"] in pt.TOPS | pt.BOTTOMS:
                ps = [p for _, p in ciz["noktalar"]]
                if g["ad"] in ("İkili Tepe", "Üçlü Tepe", "İkili Dip", "Üçlü Dip") and max(ps) - min(ps) > 0.75 * a[-1] + 1e-12:
                    errs.append("tepeler/dipler aynı seviyede değil")
            print("FM", sym, tf, g["ad"], "yukarı" if d == 1 else "aşağı", "OK" if not errs else errs)
            if errs:
                fm_bad += 1
            elif len(imgs) < 8:
                imgs.append((f"{sym}_{tf}_{g['ad']}", cs, g))
for name, cs, g in imgs:
    png = __import__("chart_img").render_pattern(cs, g, name, None)
    if png:
        print("B64", name.replace(" ", "_") + ".png", base64.b64encode(png).decode())
print(f"SONUÇ trend çizgisi kırılımı: {tl_n}, hatalı: {tl_bad} | formasyon kırılımı: {fm_n}, hatalı: {fm_bad}")
