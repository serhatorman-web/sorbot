import urllib.request
B = "https://www.binance.com"
urls = ["https://fapi.binance.com/futures/data/openInterestHist?symbol=BTCUSDT&period=1h&limit=3",
        B + "/futures/data/openInterestHist?symbol=BTCUSDT&period=1h&limit=3",
        B + "/fapi/v1/fundingRate?symbol=BTCUSDT&limit=3",
        B + "/futures/data/globalLongShortAccountRatio?symbol=BTCUSDT&period=1h&limit=3",
        B + "/futures/data/topLongShortPositionRatio?symbol=BTCUSDT&period=1h&limit=3",
        B + "/futures/data/takerlongshortRatio?symbol=BTCUSDT&period=1h&limit=3",
        B + "/api/v3/klines?symbol=BTCUSDT&interval=1h&limit=2",
        "https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1h&limit=2",
        "https://data-api.binance.vision/api/v3/klines?symbol=BTCUSDT&interval=1h&limit=2",
        B + "/fapi/v1/klines?symbol=BTCUSDT&interval=1h&limit=2"]
for u in urls:
    try:
        r = urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"}), timeout=15)
        print("XX|", u[:95], "OK", r.read()[:160])
    except Exception as e:  # noqa: BLE001
        print("XX|", u[:95], "ERR", str(e)[:80])
