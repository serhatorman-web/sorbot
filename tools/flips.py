import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DRY_RUN"] = "1"
import scanner as sc
T = 1794704400 + 28
orig = sc.Binance.get
def get(self, path, params=None, retries=3):
    p = dict(params or {})
    if path == "/fapi/v1/klines" and "endTime" not in p and "startTime" not in p:
        p["endTime"] = T * 1000
    return orig(self, path, p, retries)
sc.Binance.get = get
_t = time.time
sc.time.time = lambda: T
import builtins
sc.main()
