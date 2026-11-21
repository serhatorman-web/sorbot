import base64, json, os, re, sys, time
from datetime import datetime, timezone, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as S
TR = timezone(timedelta(hours=3))
api = S.Binance()
now_ms = int(time.time() * 1000)
cfg = S.apply_tf_profile(json.load(open(S.CONFIG_PATH, encoding="utf-8")), "15m")
sb = cfg["pump_radar"]["squeeze_break"]
universe, all_meta, tickers, funding = S.build_universe(api, cfg)
meta_by = {m["symbol"]: m for m in universe}
coins = [m["symbol"] for m in universe if m["type"] == "COIN"]
found = {"long": [], "short": []}
for sy in coins:
    try:
        cs = S.parse_klines(api.get("/fapi/v1/klines", {"symbol": sy, "interval": "15m", "limit": 1000}), now_ms)
        f = S.compute_features(cs, cfg)
    except Exception:
        continue
    for k in range(300, len(cs) - 16):          # sonucu görmek için en az 8 mum sonrası olsun
        for d, s in (("long", 1), ("short", -1)):
            if S.squeeze_break(f, k, s, sb):
                found[d].append((cs[k]["t"], sy, k))
for d in found:
    found[d].sort(reverse=True)
picks = found["long"][:4] + found["short"][:4]
print("XX| bulunan: long", len(found["long"]), "short", len(found["short"]))
out = []
for t, sy, k in picks:
    cs = S.parse_klines(api.get("/fapi/v1/klines", {"symbol": sy, "interval": "15m", "limit": 1000}), now_ms)
    k = next(j for j in range(len(cs)) if cs[j]["t"] == t)
    cut = cs[:k + 1]
    meta = meta_by[sy]
    ctx = {"leaders": {}, "funding": funding, "tickers": tickers, "now_utc": datetime.fromtimestamp((t + 900000) / 1000, timezone.utc),
           "eth_bias": None, "btc_dom": None, "ndx": None}
    r = S.analyze_symbol(meta, cut, ctx, cfg)
    f = r["f"]
    s = 1 if f["c"][k] > f["o"][k] else -1
    d = "long" if s == 1 else "short"
    why = S.squeeze_break(f, k, s, sb)
    S.fetch_tf_trends(api, r, t + 900000, "15m", True)
    S.compute_volume_profile(r, cfg)
    rd = {"dir": d, "kind": "start", "score": 80, "reasons": why}
    msg = S.build_radar_message(r, rd, cfg, ctx["now_utc"]).replace("Mum Kapanışı", "Mum içi · mum kapanmadı")
    msg = msg.replace("📌 Kırılım sebebi:", "⏱ Anlık sinyal (mum kapanmadı)\n📌 Kırılım sebebi:", 1)
    e, sl, tps, _, _ = S.radar_levels(r, rd, cfg)
    # sonra ne oldu (gerçek): 32 mum içinde TP / stop
    res_ = "32 mumda TP1'e de stop'a da değmedi"
    hit = []
    for j in range(k + 1, min(len(cs), k + 33)):
        hi_, lo_ = cs[j]["h"], cs[j]["l"]
        if (lo_ if s == 1 else hi_) * s <= sl * s:
            res_ = f"STOP ({datetime.fromtimestamp(cs[j]['t']/1000, TR).strftime('%H:%M')})"; break
        for n, tp in enumerate(tps, 1):
            if (hi_ if s == 1 else lo_) * s >= tp * s and n not in hit:
                hit.append(n)
        if len(hit) == 3:
            break
    if hit and not res_.startswith("STOP"):
        res_ = "TP" + "/".join(map(str, hit)) + " görüldü"
    elif hit:
        res_ = "TP" + "/".join(map(str, hit)) + " sonra " + res_
    mfe = max(((cs[j]["h"] if s == 1 else cs[j]["l"]) / cs[k]["c"] - 1) * s * 100 for j in range(k + 1, min(len(cs), k + 17)))
    res_ += f" · 4 saatte en fazla %{mfe:.1f} {'yükseliş' if s == 1 else 'düşüş'}"
    name = f"{sy.replace('USDT','')}_{'PUMP' if s == 1 else 'DUMP'}_{datetime.fromtimestamp(t/1000, TR).strftime('%d%m_%H%M')}"
    print("XX|", name, "sonuç:", res_)
    out.append(f"==================== {name} · SONUÇ: {res_} ====================\n" + re.sub(r"<[^>]+>", "", msg))
    png = S.signal_chart_image(r, cfg, d, kind_title=("PUMP SİNYALİ" if s == 1 else "DUMP SİNYALİ"), lv=(e, sl, tps))
    if not png:
        print("XX|", name, "resim yok"); continue
    b = base64.b64encode(png).decode()
    for j in range(0, len(b), 3000):
        print("IM|", name, j // 3000, b[j:j + 3000])
txt = "\n\n".join(out)
b = base64.b64encode(txt.encode()).decode()
for j in range(0, len(b), 3000):
    print("TX|", j // 3000, b[j:j + 3000])
