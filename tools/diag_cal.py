import os, sys
from datetime import datetime, timezone, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import econ, report, scanner as sc
cfg = sc.load_json(sc.CONFIG_PATH, {}); r = cfg["report"]
now = datetime.now(timezone.utc)
ev = econ.fetch_events(now - timedelta(days=2), now + timedelta(days=2), tuple(r["calendar_countries"]))
for e in ev:
    if e["importance"] < report.min_importance(r, e["country"]):
        continue
    imp = econ.asset_impact(e)
    print(f"{e['dt']:%d %H:%M} {e['country']} imp{e['importance']} | {e['title']} -> {e['tr']} | a={e['actual']} f={e['forecast']}"
          + (" | " + imp["reason"] + " | " + ", ".join(t for _, t in imp["items"]) if imp else ""))
