"""Grafik kanalına test resmi (geçici). Token yazdırılmaz."""
import os, sys
sys.path.insert(0, ".")
sys.path.insert(0, "tests")
import scanner
from test_scanner import _zigzag
o, h, l, c = _zigzag([(0, 80), (40, 100), (55, 90), (70, 100), (82, 87)])
cs = [{"t": 1795000000000 + k * 900000, "o": o[k], "h": h[k], "l": l[k], "c": c[k]} for k in range(len(c))]
res = {"meta": {"symbol": "TESTUSDT", "type": "COIN", "precision": 2}, "forms": {"15m": scanner.tf_formations(cs)}}
imgs = scanner.pattern_images(res, {})
print("resim", len(imgs))
n = scanner.Notifier()
print("grafik kanalı", n.charts_chat)
for png, cap in imgs:
    print("gönderildi", n.send_photo(png, "<b>✅ Sorbot Grafikler kanal testi</b> (gerçek sinyal değil)\n" + cap))
