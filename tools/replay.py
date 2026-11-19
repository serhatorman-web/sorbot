"""NATGAS 4s ve ACT 15dk: geçmiş mumlarda anlık resim ne zaman gelirdi? (geçici)"""
import json, sys, time, urllib.request, urllib.parse
from datetime import datetime, timedelta, timezone
sys.path.insert(0, ".")
import scanner
base = json.load(open("config.json", encoding="utf-8"))
BASE = "https://www.binance.com"
get = lambda path, p: json.load(urllib.request.urlopen(urllib.request.Request(BASE + path + "?" + urllib.parse.urlencode(p), headers={"User-Agent": "x"}), timeout=30))
TSI = timezone(timedelta(hours=3))
now = int(time.time() * 1000)
for sym, tf, back in (("NATGASUSDT", "4h", 60), ("ACTUSDT", "15m", 80), ("BTCUSDT", "15m", 96), ("ETHUSDT", "1h", 72)):
    cfg = json.loads(json.dumps(base)); cfg["timeframe"] = tf
    cs = scanner.parse_klines(get("/fapi/v1/klines", {"symbol": sym, "interval": tf, "limit": 499}), now)
    meta = {"symbol": sym, "type": "COMMODITY" if sym == "NATGASUSDT" else "COIN", "precision": None}
    state = {}
    print(f"\n=== {sym} {tf}")
    for end in range(len(cs) - back, len(cs)):
        f = scanner.compute_features(cs[:end + 1], cfg)
        for _, png, cap, s_, key in scanner.live_images([{"meta": meta, "f": f, "i": end}], cfg, state, 0):
            state.setdefault("img", {})[key] = 0
            t = datetime.fromtimestamp(cs[end]["t"] / 1000, TSI) + timedelta(milliseconds=scanner.tf_ms(cfg))
            later = max(x["h"] for x in cs[end + 1:]) if end + 1 < len(cs) else None
            lowl = min(x["l"] for x in cs[end + 1:]) if end + 1 < len(cs) else None
            print(f"  {t:%d.%m %H:%M} kapanış {cs[end]['c']} | sonra en yüksek {later} en düşük {lowl}")
            print("    " + cap.replace("\n", " | "))
