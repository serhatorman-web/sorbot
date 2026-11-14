import sys, os, json
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as sc
api = sc.Binance(); cfg = json.load(open("config.json"))
for label, st in (("şimdi (hafta sonu)", None), ("borsa açıkken", "open")):
    if st:
        with mock.patch.object(sc, "us_market_status", lambda now: "open"):
            u, *_ = sc.build_universe(api, cfg)
    else:
        u, *_ = sc.build_universe(api, cfg)
    by = {}
    for m in u: by[m["type"]] = by.get(m["type"], 0) + 1
    print(label, len(u), by)
old = json.loads(json.dumps(cfg)); old["universe"]["min_quote_volume_24h"].update(COIN=1e6, EQUITY=1e6); old["universe"]["scan_equity_when_closed"] = True
for label, st in (("ESKİ ayar şimdi", None), ("ESKİ ayar borsa açık", "open")):
    if st:
        with mock.patch.object(sc, "us_market_status", lambda now: "open"):
            u, *_ = sc.build_universe(api, old)
    else:
        u, *_ = sc.build_universe(api, old)
    by = {}
    for m in u: by[m["type"]] = by.get(m["type"], 0) + 1
    print(label, len(u), by)
