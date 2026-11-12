"""Teşhis: hisselerde son 24 saatte Supertrend dönüşleri (15m ve 1h)."""
import os, sys, time
from datetime import datetime, timezone
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as sc
import indicators as ta

cfg = sc.load_json(sc.CONFIG_PATH, {})
api = sc.Binance()
universe, all_meta, tickers, funding = sc.build_universe(api, cfg)
eqs = [m for m in universe if m["type"] == "EQUITY"]
now_ms = int(time.time() * 1000)
print(f"Hisse sayısı: {len(eqs)}")
tot = {"15m": 0, "1h": 0}
for m in eqs:
    out = []
    for tf in ("15m", "1h"):
        raw = api.get("/fapi/v1/klines", {"symbol": m["symbol"], "interval": tf, "limit": 300})
        cs = sc.parse_klines(raw, now_ms)
        h = [x["h"] for x in cs]; l = [x["l"] for x in cs]; c = [x["c"] for x in cs]
        st, _ = ta.supertrend(h, l, c, 10, 3.0)
        flips = [i for i in range(1, len(st)) if st[i] and st[i - 1] and st[i] != st[i - 1]
                 and cs[i]["t"] > now_ms - 24 * 3600 * 1000]
        tot[tf] += len(flips)
        last = datetime.fromtimestamp(cs[flips[-1]]["t"] / 1000, timezone.utc).strftime("%d %H:%M") if flips else "-"
        vol = sum(x["v"] for x in cs[-4:])
        out.append(f"{tf}: {len(flips)} dönüş (son {last} UTC), son mum {datetime.fromtimestamp(cs[-1]['t']/1000, timezone.utc):%d %H:%M}, son4 hacim {vol:.0f}")
    print(f"{m['symbol']:<12} " + " | ".join(out))
print("Toplam 24s dönüş:", tot)
