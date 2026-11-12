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

import os
import subprocess
import sys
import time
from datetime import datetime, timezone

QUARTER = 900
STEP = 300          # 5 dakikalık mum
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


def scan(tf):
    env = dict(os.environ)
    if tf in ("5m", "15m"):
        env["SORBOT_TF"] = tf
    else:
        env.pop("SORBOT_TF", None)
    t0 = time.time()
    try:
        r = subprocess.run([sys.executable, "scanner.py"], cwd=BASE, env=env, timeout=SCAN_TIMEOUT)
        log(f"{tf} taraması bitti (kod {r.returncode}, {time.time() - t0:.0f}s)")
    except subprocess.TimeoutExpired:
        log(f"{tf} taraması zaman aşımına uğradı")


def report():
    """Saat başı bülten (haberler + ekonomik veriler); config.json -> report ayarları."""
    t0 = time.time()
    try:
        r = subprocess.run([sys.executable, "report.py"], cwd=BASE, env=dict(os.environ), timeout=300)
        log(f"bülten bitti (kod {r.returncode}, {time.time() - t0:.0f}s)")
    except subprocess.TimeoutExpired:
        log("bülten zaman aşımına uğradı")


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
    if bulletin_due():
        report()      # kaçırılmış saatlik bülten varsa hemen gönder
    log(f"Döngü başladı, bitiş {datetime.fromtimestamp(deadline, timezone.utc):%H:%M} UTC")
    # Döngü bir mum kapanışından hemen sonra (2 dk içinde) başladıysa o kapanışı da tara
    now = time.time()
    cur = (int(now) // STEP) * STEP + OFFSET
    nxt = now if cur <= now < cur + 120 else (int(now) // STEP + 1) * STEP + OFFSET
    while nxt <= deadline:
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
            report()
        scan("5m")              # her 5 dakikada (TrendFlex)
        nxt = (int(time.time()) // STEP + 1) * STEP + OFFSET
    log("Süre doldu, döngü bitiyor (workflow yeniden başlatacak)")


if __name__ == "__main__":
    main()
