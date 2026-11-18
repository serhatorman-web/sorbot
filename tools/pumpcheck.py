"""PIEVERSE: bugün (18.11 TSİ) her 1 saatlik taramada pump radarı ne görürdü? (geçici)"""
import json, sys, urllib.request, urllib.parse
from datetime import datetime, timedelta, timezone
sys.path.insert(0, ".")
import scanner

SYM = "PIEVERSEUSDT"
cfg = json.load(open("config.json", encoding="utf-8"))
get = lambda path, p: json.load(urllib.request.urlopen(urllib.request.Request(
    "https://www.binance.com" + path + "?" + urllib.parse.urlencode(p), headers={"User-Agent": "x"}), timeout=30))
raw = get("/fapi/v1/klines", {"symbol": SYM, "interval": "1h", "limit": 1000})
oi = get("/futures/data/openInterestHist", {"symbol": SYM, "period": "1h", "limit": 60})
oi_map = {int(x["timestamp"]): float(x["sumOpenInterest"]) for x in oi}
pd_cfg = cfg["pump_dump"]
start = int(datetime(2026, 11, 17, 21, 0, tzinfo=timezone.utc).timestamp() * 1000)   # 18.11 00:00 TSİ
tsi = lambda ms: (datetime.fromtimestamp(ms / 1000, timezone.utc) + timedelta(hours=3)).strftime("%d.%m %H:%M")
for j in range(len(raw)):
    close_ms = int(raw[j][6]) + 1
    if close_ms <= start:
        continue
    cs = scanner.parse_klines(raw[max(0, j - cfg["kline_limit"] + 1):j + 1], close_ms + 1)
    if len(cs) < cfg["min_candles"]:
        continue
    f = scanner.compute_features(cs, cfg)
    i = len(cs) - 1
    c = f["c"]
    chg24 = (c[i] / c[i - 24] - 1) * 100
    pdres = scanner.pump_dump_analysis(f, cfg, chg24, i)
    oc = None
    t_last = cs[i]["t"]
    if t_last in oi_map and t_last - 4 * 3600000 in oi_map:
        oc = oi_map[t_last] / oi_map[t_last - 4 * 3600000] - 1
    rd = scanner.pump_radar(f, i, pdres, chg24, cfg, oc, None)
    late = pdres["chg3"] >= pd_cfg["already_pumped_3h"] or chg24 / 100 >= pd_cfg["already_pumped_24h"]
    print(f"{tsi(close_ms)} tarama | kapanış {c[i]:.4f} | 3s %{pdres['chg3']*100:+.1f} 24s %{chg24:+.1f} | "
          f"sıkışma {'✓' if pdres['squeeze'] else '✗'} | hacim {pdres['vol_ratio']:.1f}x{' patlama' if pdres['vol_spike'] else ''} | "
          f"20 mum kırılım {'✓' if pdres['brk_up'] else '✗'} | geç kalındı {'EVET' if late else 'hayır'} | "
          f"OI4s {('%' + format(oc * 100, '+.1f')) if oc is not None else '-'} | radar: "
          + (", ".join(f"{x['kind']} {x['dir']} {x['score']}" for x in rd) or "yok"))
