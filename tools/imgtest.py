"""Gerçek veride kırılan formasyonların resimleri (geçici test)."""
import json, os, sys, time, urllib.request, urllib.parse
sys.path.insert(0, ".")
import scanner
SYMS = ["BTC", "ETH", "XRP", "BNB", "SOL", "DOGE", "AVAX", "HYPE", "LINK", "SUI", "ADA", "ZEC", "LTC", "BCH", "NEAR", "UNI",
        "AAVE", "ARB", "OP", "INJ", "TIA", "WLD", "APT", "SEI", "ENA", "PENDLE", "TAO", "FET", "ONDO", "JUP"]
os.makedirs("out", exist_ok=True)
now = int(time.time() * 1000)
n = 0
for sym in SYMS:
    forms = {}
    for tf in ("15m", "1h", "4h", "1d"):
        u = "https://www.binance.com/fapi/v1/klines?" + urllib.parse.urlencode({"symbol": sym + "USDT", "interval": tf, "limit": 300})
        raw = json.load(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "x"}), timeout=30))
        forms[tf] = scanner.tf_formations(scanner.parse_klines(raw, now))
    res = {"meta": {"symbol": sym + "USDT", "type": "COIN", "precision": None}, "forms": forms}
    for png, cap in scanner.pattern_images(res, {"formations": {"enabled": True, "images_max": 9}}):
        n += 1
        open(f"out/{n:02d}_{sym}.png", "wb").write(png)
        print(n, cap)
print("toplam", n)
import base64, glob
for p in sorted(glob.glob("out/*.png")):
    print("B64", os.path.basename(p), base64.b64encode(open(p, "rb").read()).decode())
