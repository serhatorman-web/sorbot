"""Son kapanmış 15dk mumlarında (son 4 mum) 'kırıldı' resmi çıkan olaylar: mum kapanış saati ve resmin geleceği saat."""
import base64, json, os, sys, time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner as S

TR = timezone(timedelta(hours=3))
cfg = S.apply_tf_profile(json.load(open(S.CONFIG_PATH, encoding="utf-8")), "15m")
api = S.Binance()
uni, *_ = S.build_universe(api, cfg)
now_ms = int(time.time() * 1000)


def one(meta):
    try:
        allc = S.parse_klines(api.get("/fapi/v1/klines", {"symbol": meta["symbol"], "interval": "15m", "limit": 499}), now_ms)
    except Exception:  # noqa: BLE001
        return []
    out = []
    for back in range(0, 4):
        cs = allc[:len(allc) - back]
        f = S.compute_features(cs, cfg)
        for o in S.live_images([{"meta": meta, "f": f, "i": len(cs) - 1}], cfg, {}, cs[-1]["t"] / 1000 + 900):
            if "KIRILDI" in o[2]:
                out.append((cs[-1]["t"], o))
    return out


res = []
with ThreadPoolExecutor(max_workers=8) as ex:
    for r in ex.map(one, uni):
        res += r
res.sort(key=lambda x: -x[0])
print("XX| bulunan", len(res))
for t, o in res[:2]:
    op = datetime.fromtimestamp(t / 1000, TR)
    print("XX| mum", op.strftime("%H:%M"), "-", (op + timedelta(minutes=15)).strftime("%H:%M"), "|", o[2].replace("\n", " / "))
    b = base64.b64encode(o[1]).decode()
    for k in range(0, len(b), 3000):
        print("IM|", f"{o[3]}{t}", k // 3000, b[k:k + 3000])
