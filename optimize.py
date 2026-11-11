"""
SorBot strateji deneyleri
=========================
Veriyi bir kez indirir; olası her sinyal adayını (skor >= 60, tetikli) özellikleriyle
birlikte kaydeder ve farklı filtre / TP dizilimlerinin sonucunu karşılaştırır.

Aşırı uyumu (overfitting) önlemek için veri ikiye bölünür:
  * Ayar dönemi (IS)   : ilk kısım
  * Kontrol dönemi (OOS): son 30 gün – sadece doğrulama için

Sonuçlar işlem ücreti dahil (giriş + çıkış toplam %0.10, taker) net R olarak verilir.
Kullanım: python3 optimize.py [gün]
"""

import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import backtest as bt
import scanner as sc

HOUR_MS = sc.HOUR_MS
FEE_PCT = 0.10
OOS_DAYS = 30
LADDERS = {"1-2-3R": (1, 2, 3), "1.5-3-4.5R": (1.5, 3, 4.5), "1-2-4R": (1, 2, 4), "0.75-1.5-3R": (0.75, 1.5, 3)}


def tags(triggers):
    out = set()
    for t in triggers:
        if t.startswith("Supertrend"):
            out.add("ST")
        elif t.startswith("MACD"):
            out.add("MACD")
        elif t.startswith("EMA20"):
            out.add("EMA")
        elif t.startswith("Hacimli"):
            out.add("BRK")
        elif t.startswith("Trend içi"):
            out.add("PB")
    return out


def collect(days):
    bars = days * 24 + 320
    cfg = sc.load_json(sc.CONFIG_PATH, None)
    t0 = time.time()
    now_ms = int(time.time() * 1000)
    api = sc.Binance()
    universe, all_meta, _, _ = sc.build_universe(api, cfg)
    symbols = {m["symbol"]: m for m in universe}
    for typ, lsym in cfg["market_leaders"].items():
        if not typ.startswith("_") and lsym in all_meta and lsym not in symbols:
            symbols[lsym] = dict(all_meta[lsym], leader_only=True)
    candles = {}
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = {ex.submit(bt.fetch_history, api, s, bars, now_ms): s for s in symbols}
        for fu in as_completed(futs):
            try:
                candles[futs[fu]] = fu.result()
            except Exception:  # noqa: BLE001
                pass
    print(f"Veri: {len(candles)} sembol ({time.time()-t0:.0f}s)")

    leader_bias = {}
    for typ, lsym in cfg["market_leaders"].items():
        if typ.startswith("_") or lsym not in candles:
            continue
        lf = sc.compute_features(candles[lsym], cfg)
        leader_bias[typ] = (lsym, {lf["t"][j]: sc.trend_bias(lf, j)
                                   for j in range(len(lf["t"])) if sc.required_ready(lf, j)})

    lb = cfg["signal"]["trigger_lookback_bars"]
    recs = []
    for sym, meta in symbols.items():
        if meta.get("leader_only") or sym not in candles or len(candles[sym]) < cfg["min_candles"] + 50:
            continue
        f = sc.compute_features(candles[sym], cfg)
        n = len(f["c"])
        for i in range(300, n - 1):
            if not (sc.find_triggers(f, 1, lb, i) or sc.find_triggers(f, -1, lb, i)):
                continue
            if not sc.required_ready(f, i):
                continue
            t_close = f["t"][i] + HOUR_MS
            lead = leader_bias.get(meta["type"])
            if lead and lead[0] != sym and f["t"][i] in lead[1]:
                lbias = lead[1][f["t"][i]]
            else:
                lbias = (f["h4_ema"][i] + f["h4_st"][i]) / 2
            now_utc = datetime.fromtimestamp(t_close / 1000, timezone.utc)
            res = sc.evaluate_at(meta, f, i, lbias, "", None, sc.pct(f["c"][i], f["c"][i - 24]), now_utc, cfg)
            for key, s in (("long", 1), ("short", -1)):
                side, other = res[key], res["short" if key == "long" else "long"]
                if not side["triggers"] or side["score"] < 60:
                    continue
                risk, _ = sc.stop_distance(f, i, s, cfg["risk"], "atr")
                outs = {}
                for name, lad in LADDERS.items():
                    outs[name] = bt.simulate(f, i, s, risk, bt.MAX_HOLD, lad)
                if any(o is None for o in outs.values()):
                    continue
                atr_v = f["atr"][i]
                r = f["rsi"][i]
                recs.append({
                    "t": f["t"][i], "sym": sym, "type": meta["type"], "dir": key, "s": s,
                    "score": side["score"], "gap": side["score"] - other["score"],
                    "lead": lbias * s, "h4": (f["h4_ema"][i] + f["h4_st"][i]) * s,
                    "adx": f["adx"][i], "vr": f["v"][i] / f["vol_ma"][i] if f["vol_ma"][i] else 0,
                    "rs": r if s == 1 else 100 - r,
                    "ext": (f["c"][i] - f["ema20"][i]) * s / atr_v if atr_v else 0,
                    "stack": (f["ema20"][i] - f["ema50"][i]) * s > 0 and (f["ema50"][i] - f["ema200"][i]) * s > 0,
                    "above200": (f["c"][i] - f["ema200"][i]) * s > 0,
                    "tags": tags(side["triggers"]), "ntrig": len(side["triggers"]),
                    "session": sc.us_market_status(now_utc) if meta["type"] == "EQUITY" else "crypto",
                    "risk_pct": risk / f["c"][i] * 100, "out": outs,
                })
    print(f"Aday kayıt: {len(recs)} ({time.time()-t0:.0f}s)")
    return recs, cfg


def select(recs, pred, cooldown_h=12, per_hour=5):
    """Filtre + 12s cooldown + saatlik limit (canlı botla aynı mantık)."""
    chosen, last = [], {}
    for r in sorted(recs, key=lambda x: (x["t"], -x["score"])):
        if not pred(r):
            continue
        k = (r["sym"], r["dir"])
        if k in last and r["t"] - last[k] < cooldown_h * HOUR_MS:
            continue
        last[k] = r["t"]
        chosen.append(r)
    by_h = {}
    for r in chosen:
        by_h.setdefault(r["t"], []).append(r)
    out = []
    for t in sorted(by_h):
        out += sorted(by_h[t], key=lambda x: -x["score"])[:per_hour]
    return out


def stats(rs, ladder, days):
    if not rs:
        return None
    o = [r["out"][ladder] for r in rs]
    net = [x["R"] - FEE_PCT / r["risk_pct"] for x, r in zip(o, rs)]
    win = sum(x for x in net if x > 0)
    loss = -sum(x for x in net if x < 0)
    return {"n": len(rs), "perday": len(rs) / days, "tp1": sum(x["tp"][0] for x in o) / len(o) * 100,
            "tp3": sum(x["tp"][2] for x in o) / len(o) * 100,
            "net": sum(net) / len(net), "pf": win / loss if loss else 99.0}


def fmt(st):
    if not st:
        return "– | – | – | – | –"
    return f"{st['perday']:.1f} | {st['tp1']:.0f}% | {st['tp3']:.0f}% | {st['net']:+.3f}R | {st['pf']:.2f}"


def main():
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 80
    recs, cfg = collect(days)
    split = max(r["t"] for r in recs) - OOS_DAYS * 24 * HOUR_MS
    is_days, oos_days = days - OOS_DAYS, OOS_DAYS
    IS = [r for r in recs if r["t"] < split]
    OOS = [r for r in recs if r["t"] >= split]

    base = lambda r: r["score"] >= 80 and r["gap"] >= 25 and r["lead"] > -0.6
    variants = [
        ("Mevcut (baz)", base),
        ("Skor ≥ 70", lambda r: r["score"] >= 70 and r["gap"] >= 25 and r["lead"] > -0.6),
        ("Skor ≥ 85", lambda r: base(r) and r["score"] >= 85),
        ("Lider tam uyumlu (≥0.6)", lambda r: base(r) and r["lead"] >= 0.6),
        ("Lider %100 uyumlu", lambda r: base(r) and r["lead"] >= 1.0),
        ("4s tam uyumlu", lambda r: base(r) and r["h4"] == 2),
        ("Geç giriş yok (EMA20'den ≤1 ATR)", lambda r: base(r) and r["ext"] <= 1.0),
        ("Geç giriş yok (≤1.5 ATR)", lambda r: base(r) and r["ext"] <= 1.5),
        ("RSI (yön) ≤ 65", lambda r: base(r) and r["rs"] <= 65),
        ("ADX ≥ 25", lambda r: base(r) and r["adx"] >= 25),
        ("Hacim ≥ 1.2x", lambda r: base(r) and r["vr"] >= 1.2),
        ("EMA dizilimi uyumlu", lambda r: base(r) and r["stack"]),
        ("≥2 tetik", lambda r: base(r) and r["ntrig"] >= 2),
        ("Tetik: sadece geri çekilme", lambda r: base(r) and r["tags"] == {"PB"}),
        ("Tetik: geri çekilme hariç", lambda r: base(r) and r["tags"] != {"PB"}),
        ("Tetik: Supertrend dönüşü var", lambda r: base(r) and "ST" in r["tags"]),
        ("Tetik: MACD var", lambda r: base(r) and "MACD" in r["tags"]),
        ("Tetik: kırılım var", lambda r: base(r) and "BRK" in r["tags"]),
        ("Hisse: sadece seans içi", lambda r: base(r) and r["session"] in ("crypto", "open")),
        ("Sadece kripto", lambda r: base(r) and r["type"] == "COIN"),
        ("Sadece hisse", lambda r: base(r) and r["type"] == "EQUITY"),
        ("Sadece short", lambda r: base(r) and r["dir"] == "short"),
        ("Sadece long", lambda r: base(r) and r["dir"] == "long"),
    ]

    out_lines = []
    def p(s=""):
        print(s)
        out_lines.append(s)

    p(f"## Tekli filtreler (TP 1-2-3R, 1.5 ATR stop, ücret dahil) – IS {is_days} gün / OOS son {oos_days} gün")
    p("| Varyant | IS sinyal/gün | IS TP1 | IS TP3 | IS net R | IS PF | OOS sinyal/gün | OOS TP1 | OOS TP3 | OOS net R | OOS PF |")
    p("|---|---|---|---|---|---|---|---|---|---|---|")
    for name, pred in variants:
        p(f"| {name} | {fmt(stats(select(IS, pred), '1-2-3R', is_days))} | {fmt(stats(select(OOS, pred), '1-2-3R', oos_days))} |")

    # Kombinasyonlar: tek tek bakıldığında umut veren filtrelerin birleşimleri
    F = {
        "lead": lambda r: r["lead"] >= 0.6,
        "h4": lambda r: r["h4"] == 2,
        "ext": lambda r: r["ext"] <= 1.0,
        "rs": lambda r: r["rs"] <= 65,
        "adx": lambda r: r["adx"] >= 25,
        "vol": lambda r: r["vr"] >= 1.2,
        "stack": lambda r: r["stack"],
        "sess": lambda r: r["session"] in ("crypto", "open"),
    }
    combos = [("lead", "h4"), ("lead", "ext"), ("lead", "h4", "ext"), ("lead", "h4", "ext", "rs"),
              ("lead", "h4", "ext", "sess"), ("lead", "h4", "ext", "adx"), ("lead", "h4", "ext", "vol"),
              ("lead", "h4", "ext", "stack"), ("lead", "h4", "ext", "rs", "sess", "stack"),
              ("lead", "h4", "ext", "rs", "sess", "adx"), ("h4", "ext", "rs"), ("ext", "rs")]
    p("")
    p("## Kombinasyonlar (baz filtre + aşağıdakiler)")
    p("| Kombinasyon | IS sinyal/gün | IS TP1 | IS TP3 | IS net R | IS PF | OOS sinyal/gün | OOS TP1 | OOS TP3 | OOS net R | OOS PF |")
    p("|---|---|---|---|---|---|---|---|---|---|---|")
    combo_preds = {}
    for c in combos:
        pred = (lambda cc: (lambda r: base(r) and all(F[k](r) for k in cc)))(c)
        combo_preds["+".join(c)] = pred
        p(f"| {'+'.join(c)} | {fmt(stats(select(IS, pred), '1-2-3R', is_days))} | {fmt(stats(select(OOS, pred), '1-2-3R', oos_days))} |")

    # TP dizilimleri: baz ve en iyi birkaç kombinasyon için
    p("")
    p("## TP dizilimleri")
    p("| Filtre | TP dizilimi | IS sinyal/gün | IS TP1 | IS TP3 | IS net R | IS PF | OOS sinyal/gün | OOS TP1 | OOS TP3 | OOS net R | OOS PF |")
    p("|---|---|---|---|---|---|---|---|---|---|---|---|")
    ranked = sorted(combo_preds.items(),
                    key=lambda kv: -((stats(select(IS, kv[1]), "1-2-3R", is_days) or {"net": -9})["net"]))[:3]
    for name, pred in [("Mevcut (baz)", base)] + ranked:
        s_is, s_oos = select(IS, pred), select(OOS, pred)
        for lad in LADDERS:
            p(f"| {name} | {lad} | {fmt(stats(s_is, lad, is_days))} | {fmt(stats(s_oos, lad, oos_days))} |")

    p("")
    p("_net R: işlem başına ortalama, %0.10 toplam ücret düşülmüş. PF: kâr faktörü (>1 kârlı). "
      "TP'lerde 1/3 kâr alma, TP1 sonrası stop girişe._")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write("\n".join(out_lines) + "\n")


if __name__ == "__main__":
    main()
