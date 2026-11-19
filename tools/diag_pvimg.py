"""Pivot kırılım resmi örnekleri (canlı live_images ile): son mumlarda tek başına pivot kırılımı ve trend/formasyonla birlikte."""
import base64, sys, time
sys.path.insert(0, ".")
import scanner as S

base = S.load_json(S.CONFIG_PATH, None)
cfg = S.apply_tf_profile(base, "15m")
api = S.Binance()
now = int(time.time() * 1000)
uni, *_ = S.build_universe(api, cfg)
uni.sort(key=lambda m: m["symbol"] != "1000SHIBUSDT")
got = {}
for m in uni:
    if len(got) >= 2:
        break
    cs = S.parse_klines(api.get("/fapi/v1/klines", {"symbol": m["symbol"], "interval": "15m", "limit": 600}), now)
    if len(cs) < 400:
        continue
    f = S.compute_features(cs, cfg)
    for k in range(len(cs) - 1, len(cs) - 97, -1):
        out = S.live_images([{"meta": m, "f": f, "i": k}], cfg, {"img": {}}, (cs[k]["t"] + 900000) / 1000)
        for prio, png, cap, sym, key, body in out:
            kind = "birlikte" if "Aynı mumda" in cap else ("tek" if "PİVOT KIRILDI" in cap else None)
            if not kind or kind in got:
                continue
            got[kind] = 1
            print(f"PI| {kind} · {sym} · {S.datetime.fromtimestamp(cs[k]['t'] / 1000, S.TR_TZ)}")
            for ln in cap.splitlines():
                print("PI| " + ln)
            b = base64.b64encode(png).decode()
            for j in range(0, len(b), 3000):
                print(f"IM| {kind} {j // 3000:04d} {b[j:j + 3000]}", flush=True)
        if len(got) >= 2:
            break
print("PI| bitti", list(got))
