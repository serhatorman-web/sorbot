import report as r

URLS = [
    ("Investing TR 11", "https://tr.investing.com/rss/news_11.rss"),
    ("Investing TR 25", "https://tr.investing.com/rss/news_25.rss"),
    ("Investing TR 1", "https://tr.investing.com/rss/news_1.rss"),
    ("Investing TR 95", "https://tr.investing.com/rss/news_95.rss"),
    ("AA Dünya", "https://www.aa.com.tr/tr/rss/default?cat=dunya"),
    ("AA Gündem", "https://www.aa.com.tr/tr/rss/default?cat=guncel"),
    ("AA Ekonomi", "https://www.aa.com.tr/tr/rss/default?cat=ekonomi"),
    ("Bloomberg HT", "https://www.bloomberght.com/rss"),
    ("Dünya", "https://www.dunya.com/rss"),
    ("Investing TR 14", "https://tr.investing.com/rss/news_14.rss"),
    ("Investing TR 301", "https://tr.investing.com/rss/news_301.rss"),
    ("BTCHaber", "https://www.btchaber.com/feed/"),
    ("Koin Bülteni", "https://koinbulteni.com/feed"),
    ("Cointelegraph TR", "https://tr.cointelegraph.com/rss"),
    ("Webtekno", "https://www.webtekno.com/rss.xml"),
]
for name, url in URLS:
    try:
        items = r.parse_feed(name, url)
        print("FEED", name, len(items))
        for it in items[:6]:
            print("   -", it["dt"].strftime("%d %H:%M") if it["dt"] else "--", r.importance(it["title"]), it["title"][:110])
    except Exception as e:  # noqa: BLE001
        print("FEED", name, "HATA", str(e)[:100])
