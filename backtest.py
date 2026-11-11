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
METHODS = ("atr", "swing_atr", "st_line")
METHOD_NAMES = {"atr": "1.5 ATR", "swing_atr": "Swing + ATR (1–2.5)", "st_line": "Supertrend çizgisi (1–3 ATR)"}
FEE_PCT = 0.10      # giriş + çıkış toplam taker ücreti (%)
OOS_DAYS = 30
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


def simulate(f, i, s, risk, max_hold, tp_r=(1, 2, 3)):
    """i. mum kapanışında girilen işlemin sonucunu hesaplar."""
    entry = f["c"][i]
    sl = entry - s * risk
    tps = [entry + s * risk * r for r in tp_r]
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
                    level_r = tp_r[j]
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
    # Deneme için ayar üzerine yazma (canlı config değişmez)
    if os.environ.get("BT_STRATEGY"):
        cfg["strategy"] = os.environ["BT_STRATEGY"]
    if os.environ.get("BT_MIN_SCORE"):
        key = "signal_supertrend" if cfg.get("strategy") == "supertrend" else "signal"
        cfg.setdefault(key, {})["min_score"] = int(os.environ["BT_MIN_SCORE"])
    print(f"Strateji: {cfg.get('strategy', 'skor')}")
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
                                   for j in range(len(lf["t"])) if sc.required_ready(lf, j)},
                            {lf["t"][j]: lf["c"][j] / lf["c"][j - 24] - 1 for j in range(24, len(lf["t"]))})

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
            if cfg.get("strategy") == "supertrend":
                if f["st_dir"][i] is None or f["st_dir"][i - 1] is None or f["st_dir"][i] == f["st_dir"][i - 1]:
                    continue
            elif not (sc.find_triggers(f, 1, lb, i) or sc.find_triggers(f, -1, lb, i)):
                continue
            if not sc.required_ready(f, i):
                continue
            t_close = f["t"][i] + HOUR_MS
            lead = leader_bias.get(meta["type"])
            lret = None
            if lead and lead[0] != sym and f["t"][i] in lead[1]:
                lbias, lname = lead[1][f["t"][i]], lead[0].replace("USDT", "")
                lret = lead[2].get(f["t"][i])
            else:
                lbias, lname = (f["h4_ema"][i] + f["h4_st"][i]) / 2, "4s trend"
            chg24 = sc.pct(f["c"][i], f["c"][i - 24])
            now_utc = datetime.fromtimestamp(t_close / 1000, timezone.utc)
            res = sc.evaluate_at(meta, f, i, lbias, lname, None, chg24, now_utc, cfg, lret)
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
                               "score": res[d]["score"], "out": outcomes,
                               "decoupled": bool(res[d].get("decoupled"))})

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


def stats(trades, m, days=None):
    n = len(trades)
    if n == 0:
        return None
    o = [t["out"][m] for t in trades]
    rs = [x["R"] for x in o]
    net = [x["R"] - FEE_PCT / x["risk_pct"] for x in o]
    wins = sum(r for r in net if r > 0)
    losses = -sum(r for r in net if r < 0)
    b2 = sorted(x["bars_to_tp1"] for x in o if x["bars_to_tp1"] is not None)
    return {
        "n": n, "perday": n / days if days else None,
        "tp1": sum(x["tp"][0] for x in o) / n * 100,
        "tp2": sum(x["tp"][1] for x in o) / n * 100,
        "tp3": sum(x["tp"][2] for x in o) / n * 100,
        "sl": sum(x["stopped_before_tp1"] for x in o) / n * 100,
        "avgR": sum(rs) / n, "net": sum(net) / n, "totnet": sum(net),
        "pf": wins / losses if losses else float("inf"),
        "risk": sum(x["risk_pct"] for x in o) / n,
        "b2tp1": b2[len(b2) // 2] if b2 else None,
    }


def report(trades, days):
    lines = []
    def out(s=""):
        print(s)
        lines.append(s)

    if not trades:
        out("Hiç sinyal yok.")
        return
    split = max(t["t"] for t in trades) - OOS_DAYS * 24 * HOUR_MS
    periods = [("Tümü", trades, days),
               (f"İlk {days - OOS_DAYS} gün", [t for t in trades if t["t"] < split], days - OOS_DAYS),
               (f"Son {OOS_DAYS} gün", [t for t in trades if t["t"] >= split], OOS_DAYS)]

    out(f"## SorBot backtest – ~{days} gün, {len(trades)} sinyal (ücret dahil net R)")
    out("")
    out("| Dönem | Stop yöntemi | Sinyal/gün | TP1 | TP2 | TP3 | TP1'den önce stop | Ort. stop % | Net R/işlem | Toplam net R | Kâr faktörü |")
    out("|---|---|---|---|---|---|---|---|---|---|---|")
    for pname, tr, d in periods:
        for m in METHODS:
            st = stats(tr, m, d)
            if not st:
                continue
            out(f"| {pname} | {METHOD_NAMES[m]} | {st['perday']:.1f} | {st['tp1']:.0f}% | {st['tp2']:.0f}% | "
                f"{st['tp3']:.0f}% | {st['sl']:.0f}% | {st['risk']:.2f}% | {st['net']:+.3f}R | "
                f"{st['totnet']:+.1f}R | {st['pf']:.2f} |")

    def bucket(t):
        s = t["score"]
        return "90+" if s >= 90 else ("80–89" if s >= 80 else ("70–79" if s >= 70 else ("60–69" if s >= 60 else "<60")))
    groups = [
        ("Güven skoru", bucket),
        ("BTC/QQQ'dan ayrışma", lambda t: ("Ayrışan " if t["decoupled"] else "Normal ") + t["dir"].upper()),
        ("Yön", lambda t: t["dir"].upper()),
        ("Tür", lambda t: {"COIN": "Kripto", "EQUITY": "Hisse"}.get(t["type"], t["type"])),
    ]
    for title, keyf in groups:
        out("")
        out(f"### {title} kırılımı (1.5 ATR stop)")
        out("| Grup | Dönem | Sinyal/gün | TP1 | TP3 | TP1'den önce stop | Net R/işlem | Kâr faktörü |")
        out("|---|---|---|---|---|---|---|---|")
        for pname, tr, d in periods:
            buckets = {}
            for t in tr:
                buckets.setdefault(keyf(t), []).append(t)
            for g in sorted(buckets):
                st = stats(buckets[g], "atr", d)
                out(f"| {g} | {pname} | {st['perday']:.1f} | {st['tp1']:.0f}% | {st['tp3']:.0f}% | {st['sl']:.0f}% | "
                    f"{st['net']:+.3f}R | {st['pf']:.2f} |")

    out("")
    out(f"_Net R: işlem başına, %{FEE_PCT:.2f} toplam ücret düşülmüş. TP'lerde 1/3 kâr alma, TP1 sonrası stop girişe. "
        "Fonlama/OI geçmişi ve kayma dahil değil. Aynı mumda stop ve TP görülürse stop sayılır._")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
