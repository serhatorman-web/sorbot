"""RKLB 15dk Alçalan Üçgen: kırılım mumunda mum içi kontrol neden resim göndermedi? Kırılım mumu dakika dakika
yeniden oluşturulup mum içi tarama (live_images intrabar=True) çalıştırılır."""
import json, os, sys, time
from datetime import datetime, timezone, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as S
import patterns as pt
import indicators as ta

SYM = sys.argv[1] if len(sys.argv) > 1 else "RKLBUSDT"
TF = "15m"
TR = timezone(timedelta(hours=3))
cfg = S.apply_tf_profile(json.load(open(S.CONFIG_PATH, encoding="utf-8")), TF)
api = S.Binance()
now_ms = int(time.time() * 1000)
allc = S.parse_klines(api.get("/fapi/v1/klines", {"symbol": SYM, "interval": TF, "limit": 499}), now_ms)
meta = {"symbol": SYM, "type": "EQUITY", "precision": 2}
# kapanmış mumlarda kırılımı bul (son 30 mum)
kb_t = None
for cut in range(len(allc) - 12, len(allc)):
    cs = allc[:cut + 1]
    h = [x["h"] for x in cs[-300:]]; l = [x["l"] for x in cs[-300:]]; c = [x["c"] for x in cs[-300:]]
    a = ta.atr(h, l, c, 14)
    for g in pt.chart_patterns(h, l, c, a):
        kb = (g.get("ciz") or {}).get("kb")
        if g["durum"] == "kirildi" and kb == len(c) - 1:
            print("XX| kapanışta kırılım", g["ad"], datetime.fromtimestamp(cs[-1]["t"] / 1000, TR).strftime("%d %H:%M"))
            kb_t = cs[-1]["t"]
if not kb_t:
    print("XX| kırılım bulunamadı"); sys.exit()
k = next(j for j, x in enumerate(allc) if x["t"] == kb_t)
prev = allc[:k]
m1 = S.parse_klines(api.get("/fapi/v1/klines", {"symbol": SYM, "interval": "1m", "startTime": kb_t, "limit": 15}),
                    10 ** 15)
print("XX| kırılım mumu", datetime.fromtimestamp(kb_t / 1000, TR).strftime("%d %H:%M"), "1dk mum:", len(m1))
for j in range(len(m1)):
    part = m1[:j + 1]
    form = {"t": kb_t, "o": part[0]["o"], "h": max(x["h"] for x in part), "l": min(x["l"] for x in part),
            "c": part[-1]["c"], "v": sum(x["v"] for x in part)}
    cs = prev + [form]
    f = S.compute_features(cs, cfg)
    S.IB_PENDING.clear()
    out = S.live_images([{"meta": meta, "f": f, "i": len(cs) - 1}], cfg, {}, time.time(), intrabar=True)
    h = [x["h"] for x in cs[-300:]]; l = [x["l"] for x in cs[-300:]]; c = [x["c"] for x in cs[-300:]]
    a = ta.atr(h, l, c, 14)
    pats = [(g["ad"], g["durum"], (g.get("ciz") or {}).get("kb") == len(c) - 1) for g in pt.chart_patterns(h, l, c, a)]
    print("XX| dk", j + 1, "fiyat", form["c"], "resim:", [o[2].split("\n")[0] for o in out], "formasyonlar:", pats)
