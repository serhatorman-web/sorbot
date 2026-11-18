"""Durum kaydındaki pump/dump radarı gönderimlerini listeler (geçici, sadece okur)."""
import glob, json
from datetime import datetime, timedelta, timezone
TSI = timezone(timedelta(hours=3))
rows = []
for p in sorted(glob.glob("state/*.json")):
    try:
        d = json.load(open(p, encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        print("okunamadı", p, e); continue
    sig = d.get("signals", {}) if isinstance(d, dict) else {}
    print("dosya", p, "kayıt", len(sig))
    for k, v in sig.items():
        if "|radar_" in k and isinstance(v, (int, float)):
            sym, dr = k.split("|radar_")
            rows.append((v, sym, dr, p))
for v, sym, dr, p in sorted(rows):
    print("RADAR", datetime.fromtimestamp(v, TSI).strftime("%d.%m %H:%M"), sym, "PUMP" if dr == "long" else "DUMP", p)
print("toplam", len(rows))
