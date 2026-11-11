"""
SorBot Backtest
===============
Canlı tarayıcıyla AYNI kuralları geçmiş 1 saatlik mumlara uygular ve iki stop
yöntemini aynı sinyaller üzerinde karşılaştırır:

    atr       : giriş ± 1.5 × ATR
    swing_atr : son swing dibi/tepesi ötesi, 1–2.5 ATR aralığında

TP1/TP2/TP3 = stop mesafesinin 1R / 2R / 3R katı.

İki sonuç türü raporlanır:
  * Sabit stop    : fiyat stop'a gelmeden TP1/TP2/TP3'e ulaştı mı?
  * Yönetilen     : her TP'de pozisyonun 1/3'ü kapanır, TP1 sonrası stop girişe çekilir.
                    Sonuç R cinsinden (1R = stop mesafesi kadar kâr/zarar).

Notlar / sınırlamalar:
  * Fonlama oranı ve OI geçmişi kullanılmaz (bu bonus/cezalar backtest'te yok).
  * Aynı mum içinde hem stop hem TP görülürse kötümser davranılır: önce stop sayılır.
  * İşlem ücreti ve kayma (slippage) dahil değildir.

Kullanım:  python3 backtest.py [gün_sayısı]   (varsayılan 80)
"""

import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import scanner as sc

HOUR_MS = sc.HOUR_MS
METHODS = ("atr", "swing_atr")
MAX_HOLD = 72          # en fazla 72 saat (3 gün) pozisyonda kalınır


def fetch_history(api, sym, bars, now_ms):
    out, end = [], None
    while len(out) < bars:
        params = {"symbol": sym, "interval": "1h", "limit": 1000}
        if end:
            params["endTime"] = end
        raw = api.get("/fapi/v1/klines", params)
        if not raw:
            break
        page = sc.parse_klines(raw, now_ms)
        out = page + out if end else page
        end = int(raw[0][0]) - 1
        if len(raw) < 1000:
            break
    # tekrarları at, sırala
    seen, uniq = set(), []
    for c in sorted(out, key=lambda x: x["t"]):
        if c["t"] not in seen:
            seen.add(c["t"])
            uniq.append(c)
    return uniq[-bars:]


def simulate(f, i, s, risk, max_hold):
    """i. mum kapanışında girilen işlemin sonucunu hesaplar."""
    entry = f["c"][i]
    sl = entry - s * risk
    tps = [entry + s * risk * r for r in (1, 2, 3)]
    n = len(f["c"])
    hit = [False, False, False]
    fixed_stopped = False
    # yönetilen pozisyon
    remaining, realized, cur_sl = 1.0, 0.0, sl
    managed_done = False
    bars_to_tp1 = None
    end = min(n - 1, i + max_hold)
    if end <= i:
        return None
    for k in range(i + 1, end + 1):
        hi, lo = f["h"][k], f["l"][k]
        adverse = lo if s == 1 else hi
        favor = hi if s == 1 else lo
        # --- sabit stop sonucu ---
        if not fixed_stopped:
            if (adverse - sl) * s <= 0:
                fixed_stopped = True
            else:
                for j, tp in enumerate(tps):
                    if not hit[j] and (favor - tp) * s >= 0:
                        hit[j] = True
                        if j == 0 and bars_to_tp1 is None:
                            bars_to_tp1 = k - i
        # --- yönetilen sonuç ---
        if not managed_done:
            if (adverse - cur_sl) * s <= 0:
                realized += remaining * (cur_sl - entry) * s / risk
                remaining, managed_done = 0.0, True
            else:
                for j, tp in enumerate(tps):
                    part = 1 / 3
                    level_r = j + 1
                    taken = 1 - remaining
                    if (favor - tp) * s >= 0 and taken < part * (j + 1) - 1e-9:
                        realized += part * level_r
                        remaining -= part
                        if j == 0:
                            cur_sl = entry          # TP1 sonrası stop girişe
                if remaining <= 1e-9:
                    managed_done = True
        if fixed_stopped and managed_done:
            break
    resolved = fixed_stopped or hit[2] or end == i + max_hold
    if not resolved:
        return None    # veri bitti, sonuç belirsiz
    if not managed_done:
        realized += remaining * (f["c"][end] - entry) * s / risk   # süre doldu, piyasadan kapat
    return {"tp": hit, "stopped_before_tp1": fixed_stopped and not hit[0],
            "R": realized, "bars_to_tp1": bars_to_tp1,
            "timeout": not fixed_stopped and not hit[2] and not managed_done,
            "risk_pct": risk / entry * 100}


def main():
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 80
    bars = days * 24 + 320
    cfg = sc.load_json(sc.CONFIG_PATH, None)
    t0 = time.time()
    now_ms = int(time.time() * 1000)
    api = sc.Binance()
    universe, all_meta, tickers, funding = sc.build_universe(api, cfg)
    symbols = {m["symbol"]: m for m in universe}
    for typ, lsym in cfg["market_leaders"].items():
        if not typ.startswith("_") and lsym in all_meta and lsym not in symbols:
            symbols[lsym] = dict(all_meta[lsym], leader_only=True)
    print(f"Backtest: {len(universe)} sembol, ~{days} gün, 1s mum")

    candles = {}
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = {ex.submit(fetch_history, api, s, bars, now_ms): s for s in symbols}
        for fu in as_completed(futs):
            try:
                candles[futs[fu]] = fu.result()
            except Exception as e:  # noqa: BLE001
                print(f"  {futs[fu]} veri hatası: {e}")
    print(f"Veri indirildi: {len(candles)} sembol, {api.requests} istek ({time.time()-t0:.0f}s)")

    # Lider eğilimleri (zaman damgasına göre)
    leader_bias = {}
    for typ, lsym in cfg["market_leaders"].items():
        if typ.startswith("_") or lsym not in candles:
            continue
        lf = sc.compute_features(candles[lsym], cfg)
        leader_bias[typ] = (lsym, {lf["t"][j]: sc.trend_bias(lf, j)
                                   for j in range(len(lf["t"])) if sc.required_ready(lf, j)})

    sig_cfg = cfg["signal"]
    lb = sig_cfg["trigger_lookback_bars"]
    candidates = []
    for sym, meta in symbols.items():
        if meta.get("leader_only") or sym not in candles or len(candles[sym]) < cfg["min_candles"] + 50:
            continue
        f = sc.compute_features(candles[sym], cfg)
        n = len(f["c"])
        state = {"signals": {}}
        for i in range(300, n - 1):
            # hızlı ön eleme: tetik yoksa skor hesaplama
            if not (sc.find_triggers(f, 1, lb, i) or sc.find_triggers(f, -1, lb, i)):
                continue
            if not sc.required_ready(f, i):
                continue
            t_close = f["t"][i] + HOUR_MS
            lead = leader_bias.get(meta["type"])
            if lead and lead[0] != sym and f["t"][i] in lead[1]:
                lbias, lname = lead[1][f["t"][i]], lead[0]
            else:
                lbias, lname = (f["h4_ema"][i] + f["h4_st"][i]) / 2, "4s trend"
            chg24 = sc.pct(f["c"][i], f["c"][i - 24])
            now_utc = datetime.fromtimestamp(t_close / 1000, timezone.utc)
            res = sc.evaluate_at(meta, f, i, lbias, lname, None, chg24, now_utc, cfg)
            d = sc.decide(res, cfg, state, t_close / 1000)
            if not d:
                continue
            state["signals"][f"{sym}|{d}"] = t_close / 1000
            s = 1 if d == "long" else -1
            outcomes = {}
            for m in METHODS:
                risk, _ = sc.stop_distance(f, i, s, cfg["risk"], m)
                outcomes[m] = simulate(f, i, s, risk, MAX_HOLD)
            if any(o is None for o in outcomes.values()):
                continue
            candidates.append({"t": f["t"][i], "sym": sym, "type": meta["type"], "dir": d,
                               "score": res[d]["score"], "out": outcomes})

    # Saatte en fazla N sinyal (canlıdaki gibi en yüksek skorlular)
    by_hour = {}
    for c in candidates:
        by_hour.setdefault(c["t"], []).append(c)
    trades = []
    for t in sorted(by_hour):
        trades += sorted(by_hour[t], key=lambda x: -x["score"])[:sig_cfg["max_signals_per_run"]]
    print(f"Sinyal adayı: {len(candidates)}, saatlik limit sonrası işlem: {len(trades)} "
          f"({time.time()-t0:.0f}s)\n")
    report(trades, days)


def stats(trades, m):
    n = len(trades)
    if n == 0:
        return None
    o = [t["out"][m] for t in trades]
    rs = [x["R"] for x in o]
    wins = sum(r for r in rs if r > 0)
    losses = -sum(r for r in rs if r < 0)
    b2 = sorted(x["bars_to_tp1"] for x in o if x["bars_to_tp1"] is not None)
    return {
        "n": n,
        "tp1": sum(x["tp"][0] for x in o) / n * 100,
        "tp2": sum(x["tp"][1] for x in o) / n * 100,
        "tp3": sum(x["tp"][2] for x in o) / n * 100,
        "sl": sum(x["stopped_before_tp1"] for x in o) / n * 100,
        "avgR": sum(rs) / n,
        "totR": sum(rs),
        "pf": wins / losses if losses else float("inf"),
        "risk": sum(x["risk_pct"] for x in o) / n,
        "b2tp1": b2[len(b2) // 2] if b2 else None,
    }


def report(trades, days):
    lines = []
    def out(s=""):
        print(s)
        lines.append(s)

    out(f"## SorBot backtest – son ~{days} gün, {len(trades)} sinyal")
    out("")
    out("| Yöntem | Sinyal | TP1 | TP2 | TP3 | TP1'den önce stop | Ort. stop % | Ort. R (yönetilen) | Toplam R | Kâr faktörü | TP1'e medyan süre |")
    out("|---|---|---|---|---|---|---|---|---|---|---|")
    for m in METHODS:
        st = stats(trades, m)
        if not st:
            continue
        name = "1.5 ATR" if m == "atr" else "Swing + ATR (1–2.5)"
        out(f"| {name} | {st['n']} | {st['tp1']:.0f}% | {st['tp2']:.0f}% | {st['tp3']:.0f}% | {st['sl']:.0f}% | "
            f"{st['risk']:.2f}% | {st['avgR']:+.2f}R | {st['totR']:+.1f}R | {st['pf']:.2f} | "
            f"{st['b2tp1'] if st['b2tp1'] is not None else '-'} saat |")

    groups = [
        ("Yön", lambda t: t["dir"].upper()),
        ("Tür", lambda t: {"COIN": "Kripto", "EQUITY": "Hisse"}.get(t["type"], t["type"])),
        ("Skor", lambda t: "90+" if t["score"] >= 90 else ("85–89" if t["score"] >= 85
                                                         else ("80–84" if t["score"] >= 80 else "<80"))),
    ]
    for title, keyf in groups:
        out("")
        out(f"### {title} kırılımı")
        out("| Grup | Sinyal | Yöntem | TP1 | TP2 | TP3 | TP1'den önce stop | Ort. R |")
        out("|---|---|---|---|---|---|---|---|")
        buckets = {}
        for t in trades:
            buckets.setdefault(keyf(t), []).append(t)
        for g in sorted(buckets):
            for m in METHODS:
                st = stats(buckets[g], m)
                name = "ATR" if m == "atr" else "Swing"
                out(f"| {g} | {st['n']} | {name} | {st['tp1']:.0f}% | {st['tp2']:.0f}% | {st['tp3']:.0f}% | "
                    f"{st['sl']:.0f}% | {st['avgR']:+.2f}R |")

    out("")
    out("_Fonlama/OI geçmişi, işlem ücreti ve kayma dahil değildir. Aynı mumda stop ve TP görülürse stop sayılır._")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
