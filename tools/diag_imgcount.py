"""Sorbot Grafikler kanalına günde kaç resim gider? live_images'ı geçmiş mumlarda mum mum çalıştırır."""
import os, sys, time
from collections import Counter, defaultdict
from multiprocessing import Pool
sys.path.insert(0, ".")
import scanner as S
import indicators as ta

S.chart_img.render_pattern = lambda *a, **k: b"x"      # resim çizmeye gerek yok, sadece sayıyoruz
DAYS = {"15m": 7, "1h": 7, "4h": 30, "1d": 90}


def kind(cap):
    if "RETEST" in cap:
        return "retest"
    if "FORMASYON" in cap:
        return "formasyon"
    return "trend"


def run(args):
    tf, meta, cs, cfg, first_t = args
    t = [x["t"] for x in cs]; v = [x["v"] for x in cs]
    f = {"t": t, "o": [x["o"] for x in cs], "h": [x["h"] for x in cs], "l": [x["l"] for x in cs],
         "c": [x["c"] for x in cs], "v": v, "vol_ma": ta.sma(v, cfg.get("params", {}).get("volume_ma", 20))}
    state, out = {"img": {}}, []
    step = S.tf_ms(cfg)
    for i in range(60, len(cs)):
        if t[i] < first_t:
            continue
        now = (t[i] + step) / 1000
        for prio, _, cap, sym, key in S.live_images([{"meta": meta, "f": f, "i": i}], cfg, state, now):
            state["img"][key] = now
            out.append((t[i], prio, kind(cap)))
    return tf, out


if __name__ == "__main__":
    base = S.load_json(S.CONFIG_PATH, None)
    api = S.Binance()
    now = int(time.time() * 1000)
    jobs = []
    for tf in DAYS:
        cfg = S.apply_tf_profile(base, tf) if tf != "1h" else base
        uni, *_ = S.build_universe(api, cfg)
        if cfg.get("symbols_only"):
            uni = [m for m in uni if m["symbol"] in cfg["symbols_only"]]
        first_t = now - DAYS[tf] * 86400000
        lim = min(1500, DAYS[tf] * 86400000 // S.tf_ms(cfg) + 300)
        for m in uni:
            try:
                cs = S.parse_klines(api.get("/fapi/v1/klines", {"symbol": m["symbol"], "interval": tf, "limit": lim}), now)
            except Exception:  # noqa: BLE001
                continue
            jobs.append((tf, m, cs, cfg, first_t))
        print(f"IC| {tf}: {len(uni)} sembol, {DAYS[tf]} gün", flush=True)
    with Pool(4) as p:
        res = p.map(run, jobs, chunksize=4)
    by_tf = defaultdict(list)
    for tf, out in res:
        by_tf[tf] += out
    cap = base.get("live_images", {}).get("max_per_scan", 15)
    tot_day = 0
    for tf in DAYS:
        ev = by_tf[tf]
        scans = defaultdict(list)
        for t_, prio, k in ev:
            scans[t_].append((prio, k))
        sent = Counter()
        busy = 0
        for t_, lst in scans.items():
            lst.sort()
            if len(lst) > cap:
                busy += 1
            for _, k in lst[:cap]:
                sent[k] += 1
        d = DAYS[tf]
        tot = sum(sent.values())
        tot_day += tot / d
        print(f"IC| {tf}: günde ~{tot / d:.0f} resim (trend kırılımı {sent['trend'] / d:.0f}, retest {sent['retest'] / d:.0f}, "
              f"formasyon {sent['formasyon'] / d:.0f}) · 15 sınırına takılan tarama: {busy}/{len(scans)} · "
              f"en yoğun taramada {max((len(x) for x in scans.values()), default=0)} olay")
    print(f"IC| TOPLAM: günde ~{tot_day:.0f} resim")
