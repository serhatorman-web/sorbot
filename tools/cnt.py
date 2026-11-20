import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as S
q = S.nasdaq_index()
print("XX|", q, "gecikme sn:", int(time.time() - q["ts"]) if q and q.get("ts") else None)
