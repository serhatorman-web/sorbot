"""Sinyal karnesi: gönderilen her sinyalin sonucunu takip eder ve haftalık özet gönderir.

Kayıt   : scanner.py sinyali Telegram'a gönderince record_signal() çağırır → state/perf.json
Takip   : python3 perf.py update   (runner.py her saat başı çalıştırır)
          Sinyal mumundan sonraki mumlarda fiyat önce TP1'e mi stopa mı gitti?
          TP1'den sonra stop girişe çekilmiş sayılır; TP2 / TP3 girişe dönmeden görüldüyse işaretlenir.
          Aynı mumda hem stop hem TP1 görülürse (sıra bilinemez) temkinli olarak stop sayılır.
          Süre dolarsa (ör. 15dk için 1 gün) "zaman aşımı".
Özet    : python3 perf.py weekly   (runner.py pazar 21:00 TSİ) – son 7 günde sonuçlanan sinyaller
"""
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

BASE = os.path.dirname(os.path.abspath(__file__))
PERF_PATH = os.path.join(BASE, "state", "perf.json")
TR_TZ = timezone(timedelta(hours=3))
TF_MS = {"5m": 300_000, "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000}
MAX_BARS = {"5m": 288, "15m": 96, "1h": 72, "4h": 42}      # 1 gün / 1 gün / 3 gün / 7 gün
TF_NAMES = {"5m": "5dk", "15m": "15dk", "1h": "1 saat", "4h": "4 saat"}
CHECK_NAMES = (("htf", "Üst zaman dilimi uyumlu"), ("ichi", "Ichimoku ≥3/4"),
               ("retest", "Retest teyidi"), ("leader", "BTC/QQQ aynı yönde"))
KEEP_DAYS = 60


def load():
    try:
        with open(PERF_PATH, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {"signals": [], "last_weekly": None}


def save(d):
    os.makedirs(os.path.dirname(PERF_PATH), exist_ok=True)
    cutoff = (time.time() - KEEP_DAYS * 86400) * 1000
    d["signals"] = [x for x in d["signals"] if x["t"] >= cutoff or x["status"] == "open"]
    tmp = PERF_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(d, fh, ensure_ascii=False)
    os.replace(tmp, PERF_PATH)


def record_signal(symbol, typ, tf, direction, bar_close_ms, entry, sl, tps, grade, checks, kind="supertrend"):
    d = load()
    sid = f"{symbol}|{tf}|{direction}|{bar_close_ms}|{kind}"
    if any(x["id"] == sid for x in d["signals"]):
        return
    d["signals"].append({"id": sid, "symbol": symbol, "type": typ, "tf": tf, "dir": direction,
                         "t": bar_close_ms, "entry": entry, "sl": sl, "tps": list(tps),
                         "grade": grade, "checks": checks, "kind": kind, "status": "open", "best": 0})
    save(d)


def evaluate(sig, candles):
    """candles: sinyal mumundan SONRAKİ kapanmış mumlar [{h, l}] (eskiden yeniye).
    Döner: (status, best) – status: open | stop | tp1 | tp2 | tp3 | timeout ; best: ulaşılan en yüksek TP (0–3)"""
    s = 1 if sig["dir"] == "long" else -1
    entry, sl, tps = sig["entry"], sig["sl"], sig["tps"]
    best, stop = 0, sl
    for c in candles:
        hit_stop = (c["l"] <= stop) if s == 1 else (c["h"] >= stop)
        reach = 0
        for n, tp in enumerate(tps, 1):
            if (c["h"] >= tp) if s == 1 else (c["l"] <= tp):
                reach = n
        if hit_stop:
            # aynı mumda hem stop hem yeni TP: sıra bilinemez → temkinli: stop önce
            if best == 0:
                return "stop", 0
            return f"tp{best}", best             # TP1 sonrası stop girişte → kazançla kapandı
        if reach > best:
            best = reach
            stop = entry                          # TP1 sonrası stop girişe
            if best == len(tps):
                return f"tp{best}", best
    if len(candles) >= MAX_BARS.get(sig["tf"], 72):
        return (f"tp{best}" if best else "timeout"), best
    return "open", best


def update():
    sys.path.insert(0, BASE)
    import scanner as sc
    d = load()
    open_sigs = [x for x in d["signals"] if x["status"] == "open"]
    if not open_sigs:
        print("Açık sinyal yok")
        return
    api = sc.Binance()
    now = int(time.time() * 1000)
    changed = 0
    for sig in open_sigs:
        ms = TF_MS.get(sig["tf"], 3_600_000)
        try:
            raw = api.get("/fapi/v1/klines", {"symbol": sig["symbol"], "interval": sig["tf"],
                                              "startTime": sig["t"], "limit": MAX_BARS.get(sig["tf"], 72) + 2})
        except Exception as e:  # noqa: BLE001
            print(f"{sig['symbol']}: veri alınamadı ({e})")
            continue
        cs = [{"h": float(k[2]), "l": float(k[3])} for k in raw
              if int(k[0]) >= sig["t"] and int(k[0]) + ms <= now]
        status, best = evaluate(sig, cs[:MAX_BARS.get(sig["tf"], 72)])
        sig["best"] = best
        if status != "open":
            sig["status"] = status
            sig["closed_at"] = now
            changed += 1
    save(d)
    print(f"Karne güncellendi: {len(open_sigs)} açık sinyal kontrol edildi, {changed} sonuçlandı")


def _row(label, items):
    n = len(items)
    if not n:
        return None
    tp1 = sum(1 for x in items if x["best"] >= 1)
    stop = sum(1 for x in items if x["status"] == "stop")
    to = n - tp1 - stop
    return f"{label}: {n} sinyal · TP1 %{round(tp1 * 100 / n)} · Stop %{round(stop * 100 / n)}" + \
           (f" · Sonuçsuz %{round(to * 100 / n)}" if to else "")


def weekly_message(d, now=None):
    now = now or time.time()
    since = (now - 7 * 86400) * 1000
    done = [x for x in d["signals"] if x["status"] != "open" and x["t"] >= since]
    pending = sum(1 for x in d["signals"] if x["status"] == "open")
    start = datetime.fromtimestamp(now - 7 * 86400, TR_TZ).strftime("%d.%m")
    end = datetime.fromtimestamp(now, TR_TZ).strftime("%d.%m")
    lines = [f"📈 <b>HAFTALIK SİNYAL KARNESİ</b> · {start}–{end}", "━━━━━━━━━━━━━━━━"]
    if not done:
        lines.append("Bu hafta sonuçlanan sinyal yok.")
        if pending:
            lines.append(f"⏳ Sonuç bekleyen: {pending}")
        return "\n".join(lines)
    tp2 = sum(1 for x in done if x["best"] >= 2)
    tp3 = sum(1 for x in done if x["best"] >= 3)
    lines += [_row("<b>Toplam</b>", done),
              f"TP2 %{round(tp2 * 100 / len(done))} · TP3 %{round(tp3 * 100 / len(done))}"
              + (f" · ⏳ Sonuç bekleyen: {pending}" if pending else ""),
              "", "━━━━━━━━━━━━━━━━", "<b>Zaman dilimi</b>"]
    for tf in ("15m", "1h", "4h", "5m"):
        r = _row(TF_NAMES[tf], [x for x in done if x["tf"] == tf])
        if r:
            lines.append(r)
    lines += ["", "━━━━━━━━━━━━━━━━", "<b>Sinyal türü</b>"]
    for kind, name in (("supertrend", "📌 Supertrend"), ("early", "⚡ Erken dönüş")):
        for tf in ("15m", "1h", "4h"):
            for d, dn in (("long", "LONG"), ("short", "SHORT")):
                r = _row(f"{name} {TF_NAMES[tf]} {dn}", [x for x in done if x.get("kind", "supertrend") == kind
                                                         and x["tf"] == tf and x["dir"] == d])
                if r:
                    lines.append(r)
    lines += ["", "━━━━━━━━━━━━━━━━", "<b>Kalite notu</b>"]
    for g, badge in (("A", "🅰️"), ("B", "🅱️"), ("C", "Ⓒ")):
        r = _row(f"{badge} {g}", [x for x in done if x.get("grade") == g])
        if r:
            lines.append(r)
    lines += ["", "━━━━━━━━━━━━━━━━", "<b>Koşullar</b> (koşul sağlanan / sağlanmayan sinyallerde TP1 oranı)"]
    for key, name in CHECK_NAMES:
        yes = [x for x in done if (x.get("checks") or {}).get(key) is True]
        no = [x for x in done if (x.get("checks") or {}).get(key) is False]
        if yes or no:
            rate = lambda xs: f"%{round(sum(1 for x in xs if x['best'] >= 1) * 100 / len(xs))} ({len(xs)})" if xs else "–"
            lines.append(f"{name}: ✅ {rate(yes)} · ❌ {rate(no)}")
    lines += ["", "━━━━━━━━━━━━━━━━", "<b>Tür</b>"]
    for typ, name in (("COIN", "Kripto"), ("EQUITY", "Hisse"), ("COMMODITY", "Metal/emtia")):
        r = _row(name, [x for x in done if x.get("type") == typ])
        if r:
            lines.append(r)
    lines += ["", "<i>TP1: fiyat stoptan önce TP1'e ulaştı. Aynı mumda ikisi birden görülürse stop sayılır.</i>"]
    return "\n".join(lines)


def weekly(force=False):
    """Pazar 21:00 TSİ'den sonra, haftada bir kez gönderir (force=True: hemen)."""
    d = load()
    now_tr = datetime.now(TR_TZ)
    week_key = now_tr.strftime("%G-W%V")
    if not force and (now_tr.weekday() != 6 or now_tr.hour < 21 or d.get("last_weekly") == week_key):
        return
    sys.path.insert(0, BASE)
    import scanner as sc
    msg = weekly_message(d)
    if sc.Notifier().send(msg):
        d["last_weekly"] = week_key
        save(d)
        print("Haftalık karne gönderildi")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "update"
    if cmd == "update":
        update()
    elif cmd == "weekly":
        weekly(force=os.environ.get("PERF_FORCE") == "1")
    elif cmd == "print":
        print(weekly_message(load()))
