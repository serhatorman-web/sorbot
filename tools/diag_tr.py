import os, sys
from datetime import datetime, timezone, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import econ, report, scanner as sc
cfg = sc.load_json(sc.CONFIG_PATH, {}); r = cfg["report"]
now = datetime.now(timezone.utc)
ev = econ.fetch_events(now - timedelta(hours=10), now + timedelta(hours=1), ("TR",))
for e in ev:
    print(f"{e['dt']:%d %H:%M}Z id={e['id']} imp={e['importance']} min={report.min_importance(r, e['country'])} | {e['title']} -> {e['tr']} | a={e['actual']} f={e['forecast']} p={e['previous']}")
