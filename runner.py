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
OFFSET = int(os.environ.get("SORBOT_OFFSET_SEC", "60"))           # mum kapanışından sonra bekleme
LOOP_MINUTES = int(os.environ.get("SORBOT_LOOP_MINUTES", "340"))  # GitHub iş sınırı 360 dk
SCAN_TIMEOUT = 600
BASE = os.path.dirname(os.path.abspath(__file__))


def log(msg):
    print(f"[{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S} UTC] {msg}", flush=True)


def git_pull():
    try:
        r = subprocess.run(["git", "pull", "--ff-only", "-q"], cwd=BASE, capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            log(f"git pull başarısız: {r.stderr.strip()[:200]}")
    except Exception as e:  # noqa: BLE001
        log(f"git pull hatası: {e}")


def scan(tf):
    env = dict(os.environ)
    if tf == "15m":
        env["SORBOT_TF"] = "15m"
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


def main():
    deadline = time.time() + LOOP_MINUTES * 60
    log(f"Döngü başladı, {LOOP_MINUTES} dk sürecek")
    # Döngü bir mum kapanışından hemen sonra (2 dk içinde) başladıysa o kapanışı da tara
    now = time.time()
    cur = (int(now) // QUARTER) * QUARTER + OFFSET
    nxt = now if cur <= now < cur + 120 else (int(now) // QUARTER + 1) * QUARTER + OFFSET
    while nxt <= deadline:
        wait = nxt - time.time()
        if wait > 0:
            time.sleep(wait)
        boundary = int(time.time() - OFFSET) // QUARTER * QUARTER
        minute = datetime.fromtimestamp(boundary, timezone.utc).minute
        git_pull()
        scan("15m")
        if minute == 0:
            scan("1h")
            report()
        nxt = (int(time.time()) // QUARTER + 1) * QUARTER + OFFSET
    log("Süre doldu, döngü bitiyor (workflow yeniden başlatacak)")


if __name__ == "__main__":
    main()
