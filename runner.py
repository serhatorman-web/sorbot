"""
SorBot sürekli tarama döngüsü
=============================
GitHub'ın zamanlayıcısı (cron) yoğun saatlerde çok gecikebildiği için taramalar tek bir
uzun çalıştırma içinde, kendi saatimize göre yapılır:

  * Her 15 dakikalık mum kapanışından OFFSET saniye sonra  -> 15dk taraması
  * Saat başlarında (1 saatlik mum kapanışı) ek olarak       -> 1s taraması (+ radar) ve saatlik bülten

Her taramadan önce repodaki son kod/ayar çekilir (git pull), böylece config.json
değişiklikleri en geç 15 dakika içinde geçerli olur.
Süre dolunca döngü biter; workflow kendini yeniden başlatır (loop.yml).
"""

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

QUARTER = 900
ENABLE_5M = False   # 5 dakikalık tarama kapalı (testlerde zayıf sonuç; açmak için True, sadece BTC/ETH)
STEP = 300 if ENABLE_5M else QUARTER
OFFSET = int(os.environ.get("SORBOT_OFFSET_SEC", "60"))           # mum kapanışından sonra bekleme
LOOP_MINUTES = int(os.environ.get("SORBOT_LOOP_MINUTES", "340"))  # GitHub iş sınırı 360 dk
SCAN_TIMEOUT = 600
BASE = os.path.dirname(os.path.abspath(__file__))


def log(msg):
    print(f"[{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S} UTC] {msg}", flush=True)


def file_hash(path):
    try:
        import hashlib
        with open(path, "rb") as fh:
            return hashlib.sha1(fh.read()).hexdigest()
    except OSError:
        return None


def git_pull():
    """Son kodu çeker; runner.py değiştiyse döngüyü aynı süre sınırıyla yeniden başlatır."""
    before = file_hash(os.path.join(BASE, "runner.py"))
    try:
        r = subprocess.run(["git", "pull", "--ff-only", "-q"], cwd=BASE, capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            log(f"git pull başarısız: {r.stderr.strip()[:200]}")
    except Exception as e:  # noqa: BLE001
        log(f"git pull hatası: {e}")
    if before and file_hash(os.path.join(BASE, "runner.py")) != before:
        log("runner.py güncellendi, döngü yeni kodla yeniden başlatılıyor")
        os.execv(sys.executable, [sys.executable, os.path.join(BASE, "runner.py")])


# --------------------------------------------------------------------------- #
# Sağlık takibi: 7/24 çalışma kontrolü, hata uyarıları, kendini onarma, günlük durum
# --------------------------------------------------------------------------- #
HEALTH_PATH = os.path.join(BASE, "state", "health.json")
TR_TZ = timezone(timedelta(hours=3))
FAIL_ALERT = 3        # üst üste bu kadar hata -> Telegram uyarısı
FAIL_RESTART = 6      # üst üste bu kadar hata -> döngü temiz bir makinede yeniden başlar
GAP_ALERT_MIN = 30    # taramalar arasında bundan uzun boşluk -> kesinti bildirimi
KIND_NAMES = {"5m": "5dk taraması (BTC/ETH)", "15m": "15dk taraması", "1h": "1 saatlik tarama",
              "4h": "4 saatlik tarama", "bülten": "Saatlik bülten"}


def load_health():
    try:
        with open(HEALTH_PATH, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def save_health(h):
    os.makedirs(os.path.dirname(HEALTH_PATH), exist_ok=True)
    with open(HEALTH_PATH, "w", encoding="utf-8") as fh:
        json.dump(h, fh, ensure_ascii=False)


def notify(text):
    """Bot durum mesajı (sinyallerle aynı kanala)."""
    try:
        sys.path.insert(0, BASE)
        import scanner
        scanner.Notifier().send(text)
    except Exception as e:  # noqa: BLE001
        log(f"durum mesajı gönderilemedi: {e}")


def record(kind, ok, signals=0, why=""):
    """Her tarama/bülten sonucunu kaydeder; üst üste hatada uyarır, düzelince bildirir."""
    h = load_health()
    now = time.time()
    day = datetime.now(TR_TZ).strftime("%Y-%m-%d")
    st = h.setdefault("days", {}).setdefault(day, {})
    k = st.setdefault(kind, {"ok": 0, "fail": 0, "signals": 0})
    k["ok" if ok else "fail"] += 1
    k["signals"] += signals
    h["days"] = {d: v for d, v in h["days"].items() if d >= (datetime.now(TR_TZ) - timedelta(days=3)).strftime("%Y-%m-%d")}
    fails = h.setdefault("fails", {})
    alerted = h.setdefault("alerted", {})
    if ok:
        if alerted.get(kind):
            notify(f"✅ <b>SorBot</b>: {KIND_NAMES.get(kind, kind)} tekrar normal çalışıyor.")
        fails[kind] = 0
        alerted[kind] = False
        if kind != "bülten":
            h["last_scan"] = now
    else:
        fails[kind] = fails.get(kind, 0) + 1
        if fails[kind] >= FAIL_ALERT and not alerted.get(kind):
            notify(f"⚠️ <b>SorBot uyarı</b>: {KIND_NAMES.get(kind, kind)} {fails[kind]} kez üst üste başarısız oldu.\n"
                   f"Sebep: {why[:200] or 'bilinmiyor'}\nBot kendini düzeltmeyi deniyor.")
            alerted[kind] = True
    save_health(h)
    return fails.get(kind, 0)


def run_scanner(tf):
    """scanner.py'yi çalıştırır; (başarılı mı, sinyal sayısı, sebep) döner."""
    env = dict(os.environ)
    if tf in ("5m", "15m", "4h"):
        env["SORBOT_TF"] = tf
    else:
        env.pop("SORBOT_TF", None)
    try:
        r = subprocess.run([sys.executable, "scanner.py"], cwd=BASE, env=env, timeout=SCAN_TIMEOUT,
                           capture_output=True, text=True)
    except subprocess.TimeoutExpired:
        return False, 0, "zaman aşımı (10 dk)"
    out = (r.stdout or "") + (r.stderr or "")
    sys.stdout.write(r.stdout or "")
    sys.stderr.write(r.stderr or "")
    m = re.search(r"Bitti: (\d+) sinyal", out)
    sig = int(m.group(1)) if m else 0
    if r.returncode != 0:
        err = re.findall(r"(HATA[^\n]*|\w+Error[^\n]*)", out)
        return False, sig, (err[-1] if err else f"çıkış kodu {r.returncode}")
    mv = re.search(r"Mum verisi: (\d+) başarılı, (\d+) hatalı", out)
    if mv and int(mv.group(2)) > int(mv.group(1)):
        return False, sig, f"mum verisi alınamadı ({mv.group(2)} hatalı)"
    return True, sig, ""


def scan(tf):
    t0 = time.time()
    ok, sig, why = run_scanner(tf)
    log(f"{tf} taraması bitti ({'tamam' if ok else 'HATA: ' + why}, {sig} sinyal, {time.time() - t0:.0f}s)")
    n = record(tf, ok, sig, why)
    if n >= FAIL_RESTART:
        log(f"{tf} {n} kez üst üste başarısız; döngü temiz bir makinede yeniden başlatılıyor")
        notify(f"🔄 <b>SorBot</b>: {KIND_NAMES.get(tf, tf)} {n} kez başarısız oldu, bot yeniden başlatılıyor.")
        h = load_health()
        h["fails"][tf] = 0
        save_health(h)
        sys.exit(3)        # loop.yml 'Döngüyü yeniden başlat' adımı yeni bir çalıştırma açar


def check_gap():
    """Döngü başlarken: son taramadan bu yana uzun boşluk varsa (GitHub kesintisi vb.) bildirir."""
    last = load_health().get("last_scan")
    if last and time.time() - last > GAP_ALERT_MIN * 60:
        mins = (time.time() - last) / 60
        t = datetime.fromtimestamp(last, TR_TZ).strftime("%d.%m %H:%M")
        notify(f"⚠️ <b>SorBot</b>: Bot {mins:.0f} dakika çalışmadı (son tarama {t} TSİ).\n"
               "Yeniden başladı, taramalar devam ediyor ✅")
        h = load_health()
        h.setdefault("gaps", []).append({"from": last, "min": round(mins)})
        h["gaps"] = h["gaps"][-50:]
        save_health(h)


def daily_status():
    """Her sabah 09:00 TSİ: son 24 saatin çalışma özeti."""
    h = load_health()
    now_tr = datetime.now(TR_TZ)
    day_key = now_tr.strftime("%Y-%m-%d")
    if h.get("status_day") == day_key or now_tr.hour != 9:
        return
    yday = (now_tr - timedelta(days=1)).strftime("%Y-%m-%d")
    names = {"5m": "5dk (BTC/ETH)", "15m": "15dk", "1h": "1 saat", "4h": "4 saat", "bülten": "Bülten"}
    tot = {}
    for d in (yday, day_key):
        for k, v in h.get("days", {}).get(d, {}).items():
            t = tot.setdefault(k, {"ok": 0, "fail": 0, "signals": 0})
            for f in t:
                t[f] += v.get(f, 0)
    lines = ["🩺 <b>SorBot günlük durum</b>", ""]
    any_fail = False
    for k in ("5m", "15m", "1h", "4h", "bülten"):
        if k in tot:
            t = tot[k]
            any_fail |= t["fail"] > 0
            sig = f" · {t['signals']} sinyal" if k != "bülten" else ""
            lines.append(f"{'🟢' if t['fail'] == 0 else '🟠'} {names[k]}: {t['ok']} başarılı"
                         + (f", {t['fail']} hatalı" if t["fail"] else "") + sig)
    gaps = [g for g in h.get("gaps", []) if g["from"] > time.time() - 86400]
    lines.append("")
    if gaps:
        lines.append(f"⚠️ Son 24 saatte {len(gaps)} kesinti, toplam {sum(g['min'] for g in gaps)} dk")
    lines.append("✅ Bot 7/24 çalışıyor" if not gaps and not any_fail else "Bot çalışıyor, sorunlar kendiliğinden düzeltildi")
    notify("\n".join(lines))
    h["status_day"] = day_key
    save_health(h)


def report():
    """Saat başı bülten (haberler + ekonomik veriler); config.json -> report ayarları."""
    t0 = time.time()
    try:
        r = subprocess.run([sys.executable, "report.py"], cwd=BASE, env=dict(os.environ), timeout=300)
        log(f"bülten bitti (kod {r.returncode}, {time.time() - t0:.0f}s)")
        record("bülten", r.returncode == 0, why=f"çıkış kodu {r.returncode}")
    except subprocess.TimeoutExpired:
        log("bülten zaman aşımına uğradı")
        record("bülten", False, why="zaman aşımı")


def release_check():
    """Açıklanan ekonomik verileri anında Telegram'a gönderir (report.py, REPORT_MODE=releases)."""
    env = dict(os.environ, REPORT_MODE="releases")
    try:
        subprocess.run([sys.executable, "report.py"], cwd=BASE, env=env, timeout=50)
    except subprocess.TimeoutExpired:
        log("anlık veri kontrolü zaman aşımına uğradı")


def bulletin_due():
    """Son bülten 55 dakikadan eskiyse (veya hiç yoksa) True."""
    try:
        import json
        with open(os.path.join(BASE, "state", "report_state.json"), encoding="utf-8") as fh:
            last = json.load(fh).get("last_bulletin", 0)
    except (OSError, ValueError):
        last = 0
    return time.time() - last >= 55 * 60


def main():
    # Yeniden başlatmada süre sınırı korunur
    deadline = float(os.environ.get("SORBOT_DEADLINE") or (time.time() + LOOP_MINUTES * 60))
    os.environ["SORBOT_DEADLINE"] = str(deadline)
    if not os.environ.get("SORBOT_REEXEC"):
        check_gap()   # uzun kesinti olduysa bildir
    os.environ["SORBOT_REEXEC"] = "1"
    if bulletin_due():
        report()      # kaçırılmış saatlik bülten varsa hemen gönder
    log(f"Döngü başladı, bitiş {datetime.fromtimestamp(deadline, timezone.utc):%H:%M} UTC")
    # Döngü bir mum kapanışından hemen sonra (2 dk içinde) başladıysa o kapanışı da tara
    now = time.time()
    cur = (int(now) // STEP) * STEP + OFFSET
    nxt = now if cur <= now < cur + 120 else (int(now) // STEP + 1) * STEP + OFFSET
    while nxt <= deadline:
        # Taramalar arasında her dakika açıklanan verileri kontrol et (dakikanın 20. saniyesinde)
        while True:
            nm = (int(time.time()) // 60 + 1) * 60 + 20
            if nm >= nxt - 5:
                break
            time.sleep(max(0, nm - time.time()))
            release_check()
        wait = nxt - time.time()
        if wait > 0:
            time.sleep(wait)
        boundary = int(time.time() - OFFSET) // STEP * STEP
        minute = datetime.fromtimestamp(boundary, timezone.utc).minute
        git_pull()
        if minute % 15 == 0:
            scan("15m")
        if minute == 0:
            scan("1h")
            hour = datetime.fromtimestamp(boundary, timezone.utc).hour
            if hour % 4 == 0:
                scan("4h")      # 4 saatlik – tüm semboller
            report()
            daily_status()
        if ENABLE_5M:
            scan("5m")          # 5 dakikalık tarama – sadece BTC ve ETH
        release_check()
        nxt = (int(time.time()) // STEP + 1) * STEP + OFFSET
    log("Süre doldu, döngü bitiyor (workflow yeniden başlatacak)")


if __name__ == "__main__":
    main()
