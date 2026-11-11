"""
SorBot Saatlik Piyasa Raporu
============================
Her saat Telegram'a iki mesaj gönderir:

1) 📊 Piyasa raporu
   - BTC: fiyat, fonlama oranı, açık pozisyon (OI), long/short oranları,
     son 1 saatte vadeli ve spot alış/satış hacmi
   - ABD borsaları ve makro: S&P 500, Nasdaq, Dow, Nasdaq vadeli, VIX, DXY, ABD 10Y, altın, petrol
   - BTC / ETH spot ETF giriş-çıkışları (son açıklanan gün, Farside)
   - Önümüzdeki saatlerin önemli ekonomik verileri (ForexFactory takvimi)
2) 📰 Haberler: son çalıştırmadan beri çıkan yeni ekonomi/finans, kripto ve yapay zeka haberleri

Ayrıca her sabah (varsayılan 09:00 TSİ) günün ekonomik takvimi gönderilir.
Sadece Python standart kütüphanesi kullanılır.
"""

import html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import scanner as sc

TR_TZ = sc.TR_TZ
STATE_PATH = os.path.join(sc.BASE_DIR, "state", "report_state.json")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
SPOT = "https://data-api.binance.vision"

MARKETS = [
    ("S&P 500", "^GSPC"), ("Nasdaq", "^IXIC"), ("Dow Jones", "^DJI"), ("Nasdaq vadeli", "NQ=F"),
    ("VIX", "^VIX"), ("Dolar endeksi", "DX-Y.NYB"), ("ABD 10Y faiz", "^TNX"),
    ("Altın", "GC=F"), ("Petrol (WTI)", "CL=F"),
]

DEFAULT_FEEDS = {
    "💵 Ekonomi & Finans": [
        ("Investing TR", "https://tr.investing.com/rss/news.rss"),
        ("Bloomberg HT", "https://www.bloomberght.com/rss"),
        ("CNBC", "https://www.cnbc.com/id/100003114/device/rss/rss.html"),
        ("MarketWatch", "https://feeds.content.dowjones.io/public/rss/mw_topstories"),
    ],
    "🪙 Kripto": [
        ("Investing TR Kripto", "https://tr.investing.com/rss/news_301.rss"),
        ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
        ("Cointelegraph", "https://cointelegraph.com/rss"),
    ],
    "🤖 Yapay Zeka": [
        ("TechCrunch AI", "https://techcrunch.com/category/artificial-intelligence/feed/"),
        ("The Verge AI", "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml"),
    ],
}

COUNTRY_FLAG = {"USD": "🇺🇸", "EUR": "🇪🇺", "GBP": "🇬🇧", "JPY": "🇯🇵", "CNY": "🇨🇳", "CHF": "🇨🇭",
                "CAD": "🇨🇦", "AUD": "🇦🇺", "NZD": "🇳🇿", "ALL": "🌍"}
IMPACT_ICON = {"High": "🔴", "Medium": "🟠", "Low": "🟡", "Holiday": "🏖"}
IMPACT_RANK = {"Low": 1, "Medium": 2, "High": 3, "Holiday": 0}


# --------------------------------------------------------------------------- #
# Yardımcılar
# --------------------------------------------------------------------------- #
def get(url, timeout=20, as_json=True):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
    return json.loads(data) if as_json else data


def esc(s):
    return html.escape(str(s), quote=False)


def fmt_usd(x):
    a = abs(x)
    if a >= 1e9:
        return f"${x/1e9:,.2f} mlr"
    if a >= 1e6:
        return f"${x/1e6:,.1f} mn"
    if a >= 1e3:
        return f"${x/1e3:,.1f} bin"
    return f"${x:,.0f}"


def arrow(x):
    return "🟢" if x > 0 else ("🔴" if x < 0 else "⚪")


def safe(fn, *a):
    try:
        return fn(*a)
    except Exception as e:  # noqa: BLE001
        print(f"  [uyarı] {fn.__name__}: {str(e)[:120]}")
        return None


# --------------------------------------------------------------------------- #
# Veri toplama
# --------------------------------------------------------------------------- #
def btc_derivatives(api):
    sym = "BTCUSDT"
    out = {}
    t = api.get("/fapi/v1/ticker/24hr", {"symbol": sym})
    out["price"], out["chg24"] = float(t["lastPrice"]), float(t["priceChangePercent"])
    p = api.get("/fapi/v1/premiumIndex", {"symbol": sym})
    out["funding"] = float(p["lastFundingRate"])
    out["next_funding"] = int(p["nextFundingTime"])
    oi = api.get("/futures/data/openInterestHist", {"symbol": sym, "period": "1h", "limit": 25})
    vals = [float(x["sumOpenInterestValue"]) for x in oi]
    coins = [float(x["sumOpenInterest"]) for x in oi]
    out["oi_usd"], out["oi_btc"] = vals[-1], coins[-1]
    out["oi_1h"] = vals[-1] / vals[-2] - 1 if len(vals) > 1 else None
    out["oi_24h"] = vals[-1] / vals[0] - 1 if len(vals) > 24 else None
    g = api.get("/futures/data/globalLongShortAccountRatio", {"symbol": sym, "period": "1h", "limit": 2})
    out["ls_acc"] = (float(g[-1]["longAccount"]), float(g[-1]["shortAccount"]), float(g[-1]["longShortRatio"]))
    tp = api.get("/futures/data/topLongShortPositionRatio", {"symbol": sym, "period": "1h", "limit": 2})
    out["ls_top"] = (float(tp[-1]["longAccount"]), float(tp[-1]["shortAccount"]), float(tp[-1]["longShortRatio"]))
    tk = api.get("/futures/data/takerlongshortRatio", {"symbol": sym, "period": "1h", "limit": 2})
    last = tk[-1]
    out["fut_buy"], out["fut_sell"] = float(last["buyVol"]), float(last["sellVol"])
    return out


def btc_spot():
    """Son kapanmış 1s mumda spot piyasa alış (taker buy) / satış hacmi."""
    raw = get(f"{SPOT}/api/v3/klines?symbol=BTCUSDT&interval=1h&limit=3")
    now_ms = int(time.time() * 1000)
    closed = [k for k in raw if int(k[6]) < now_ms]
    k = closed[-1]
    total_q, buy_q = float(k[7]), float(k[10])
    total_b, buy_b = float(k[5]), float(k[9])
    return {"buy_usd": buy_q, "sell_usd": total_q - buy_q, "buy_btc": buy_b, "sell_btc": total_b - buy_b,
            "price_chg_1h": (float(k[4]) / float(k[1]) - 1) * 100, "t": int(k[0])}


def market_quote(symbol):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}?interval=1d&range=1d"
    meta = get(url)["chart"]["result"][0]["meta"]
    price = meta.get("regularMarketPrice")
    prev = meta.get("chartPreviousClose") or meta.get("previousClose")
    chg = (price / prev - 1) * 100 if price and prev else None
    return {"price": price, "chg": chg}


def etf_flows(asset):
    """Farside: son açıklanan günün toplam ETF akışı (milyon $) ve en büyük hareketler."""
    body = get(f"https://farside.co.uk/{asset}/", as_json=False).decode("utf-8", "ignore")
    table = max(re.findall(r"<table[^>]*>.*?</table>", body, re.S), key=len)
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", table, re.S)

    def cells(r):
        return [html.unescape(re.sub(r"<[^>]+>", "", c)).strip() for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", r, re.S)]

    def num(s):
        s = s.replace(",", "")
        if s in ("", "-"):
            return None
        neg = s.startswith("(")
        v = float(s.strip("()"))
        return -v if neg else v

    parsed = [cells(r) for r in rows]
    header = next(c for c in parsed if len(c) > 3 and c[1] and c[1].isupper() and c[1] != "Fee")
    days = [c for c in parsed if re.match(r"\d{2} \w{3} \d{4}$", c[0] or "")]
    reported = [c for c in days if any(num(x) not in (None, 0.0) for x in c[1:-1])]
    if not reported:
        return None
    last = reported[-1]
    funds = []
    for name, v in zip(header[1:-1], last[1:-1]):
        n = num(v)
        if n:
            funds.append((name, n))
    funds.sort(key=lambda x: -abs(x[1]))
    # son 5 günün toplamı
    week = [num(c[-1]) for c in reported[-5:] if num(c[-1]) is not None]
    return {"date": last[0], "total": num(last[-1]) or 0.0, "top": funds[:3], "sum5": sum(week), "n5": len(week)}


def calendar_events():
    data = get("https://nfs.faireconomy.media/ff_calendar_thisweek.json")
    out = []
    for e in data:
        try:
            dt = datetime.fromisoformat(e["date"]).astimezone(TR_TZ)
        except (KeyError, ValueError):
            continue
        out.append({"dt": dt, "title": e.get("title", ""), "country": e.get("country", ""),
                    "impact": e.get("impact", ""), "forecast": e.get("forecast", ""),
                    "previous": e.get("previous", "")})
    return out


def parse_feed(source, url):
    root = ET.fromstring(get(url, as_json=False))
    items = []
    ns = {"a": "http://www.w3.org/2005/Atom"}
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        pub = it.findtext("pubDate") or it.findtext("{http://purl.org/dc/elements/1.1/}date")
        items.append((title, link, pub))
    for it in root.findall(".//a:entry", ns):
        title = (it.findtext("a:title", default="", namespaces=ns) or "").strip()
        le = it.find("a:link", ns)
        link = le.get("href") if le is not None else ""
        pub = it.findtext("a:published", default=None, namespaces=ns) or it.findtext("a:updated", default=None, namespaces=ns)
        items.append((title, link, pub))
    out = []
    for title, link, pub in items:
        dt = None
        if pub:
            try:
                dt = parsedate_to_datetime(pub)
            except (TypeError, ValueError):
                try:
                    dt = datetime.fromisoformat(pub.replace("Z", "+00:00"))
                except ValueError:
                    dt = None
            if dt and dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        if title and link:
            out.append({"source": source, "title": html.unescape(title), "link": link, "dt": dt})
    return out


# --------------------------------------------------------------------------- #
# Mesajlar
# --------------------------------------------------------------------------- #
def market_message(now_tr, d, spot, quotes, etf, events, rcfg):
    L = [f"📊 <b>Saatlik Piyasa Raporu</b> · {now_tr:%d.%m.%Y %H:%M} TSİ", ""]

    if d:
        L.append(f"<b>₿ BTC</b> <code>${d['price']:,.0f}</code> · 24s {arrow(d['chg24'])} {d['chg24']:+.2f}%"
                 + (f" · 1s {spot['price_chg_1h']:+.2f}%" if spot else ""))
        nf = datetime.fromtimestamp(d["next_funding"] / 1000, TR_TZ)
        fr = d["funding"] * 100
        fr_note = "long'lar ödüyor" if fr > 0 else ("short'lar ödüyor" if fr < 0 else "nötr")
        L.append(f"💰 Fonlama: <b>{fr:+.4f}%</b> ({fr_note}) · sonraki {nf:%H:%M}")
        oi_line = f"📈 Açık pozisyon: <b>{fmt_usd(d['oi_usd'])}</b> ({d['oi_btc']:,.0f} BTC)"
        if d["oi_1h"] is not None:
            oi_line += f" · 1s {d['oi_1h']*100:+.2f}%"
        if d["oi_24h"] is not None:
            oi_line += f" · 24s {d['oi_24h']*100:+.2f}%"
        L.append(oi_line)
        la, sa, ra = d["ls_acc"]
        lt, st, rt = d["ls_top"]
        L.append(f"⚖️ Long/Short (tüm hesaplar): <b>%{la*100:.1f} / %{sa*100:.1f}</b> · oran {ra:.2f}")
        L.append(f"🐋 Long/Short (büyük trader pozisyon): <b>%{lt*100:.1f} / %{st*100:.1f}</b> · oran {rt:.2f}")
        fb, fs = d["fut_buy"], d["fut_sell"]
        L.append(f"🔁 Vadeli (son 1s): alış <b>{fb:,.0f}</b> / satış <b>{fs:,.0f}</b> BTC · "
                 f"{'alıcılar' if fb > fs else 'satıcılar'} baskın (oran {fb / fs if fs else 0:.2f})")
    if spot:
        L.append(f"🏦 Spot (son 1s): alış <b>{fmt_usd(spot['buy_usd'])}</b> / satış <b>{fmt_usd(spot['sell_usd'])}</b> · "
                 f"net {fmt_usd(spot['buy_usd'] - spot['sell_usd'])}")

    if quotes:
        ms = sc.us_market_status(datetime.now(timezone.utc))
        state = {"open": "🟢 açık", "closed": "🔴 seans dışı", "weekend": "🔴 hafta sonu kapalı"}[ms]
        L += ["", f"<b>🇺🇸 ABD Piyasaları</b> ({state})"]
        rows = []
        for name, sym in MARKETS:
            q = quotes.get(sym)
            if not q or q["price"] is None:
                continue
            chg = q["chg"]
            ch = f"{chg:+.2f}%" if chg is not None else "  –  "
            price = f"{q['price']:,.2f}" if q["price"] < 100000 else f"{q['price']:,.0f}"
            rows.append(f"{name:<14}{price:>11}  {ch:>7}")
        if rows:
            L.append("<pre>" + esc("\n".join(rows)) + "</pre>")

    if etf:
        L += ["", "<b>🏛 Spot ETF akışları</b> (milyon $, Farside)"]
        for asset, e in etf.items():
            if not e:
                continue
            top = ", ".join(f"{n} {v:+,.1f}" for n, v in e["top"]) or "–"
            L.append(f"{asset} {e['date']}: {arrow(e['total'])} <b>{e['total']:+,.1f}</b> · son {e['n5']} gün {e['sum5']:+,.1f}")
            L.append(f"   {esc(top)}")

    if events is not None:
        now = now_tr
        horizon = now + timedelta(hours=rcfg.get("calendar_lookahead_hours", 3))
        cur = set(rcfg.get("calendar_currencies", ["USD", "EUR", "CNY", "GBP", "JPY"]))
        min_rank = IMPACT_RANK.get(rcfg.get("calendar_min_impact_hourly", "Medium"), 2)
        upcoming = [e for e in events if now <= e["dt"] <= horizon and e["country"] in cur
                    and IMPACT_RANK.get(e["impact"], 0) >= min_rank]
        L += ["", f"<b>🗓 Önümüzdeki {rcfg.get('calendar_lookahead_hours', 3)} saat</b>"]
        if upcoming:
            for e in upcoming[:8]:
                L.append(event_line(e))
        else:
            L.append("Önemli veri yok.")

    L += ["", "<i>Yatırım tavsiyesi değildir.</i>"]
    return "\n".join(L)


def event_line(e):
    extra = []
    if e["forecast"]:
        extra.append(f"bkl: {e['forecast']}")
    if e["previous"]:
        extra.append(f"önc: {e['previous']}")
    tail = f" ({esc(', '.join(extra))})" if extra else ""
    return (f"{IMPACT_ICON.get(e['impact'], '•')} {e['dt']:%H:%M} {COUNTRY_FLAG.get(e['country'], e['country'])} "
            f"{esc(e['title'])}{tail}")


def calendar_message(events, day, rcfg):
    cur = set(rcfg.get("calendar_currencies", ["USD", "EUR", "CNY", "GBP", "JPY"]))
    min_rank = IMPACT_RANK.get(rcfg.get("calendar_min_impact_daily", "Medium"), 2)
    todays = [e for e in events if e["dt"].date() == day and e["country"] in cur
              and IMPACT_RANK.get(e["impact"], 0) >= min_rank]
    L = [f"🗓 <b>Günün Ekonomik Takvimi</b> · {day:%d.%m.%Y} (TSİ)", ""]
    if not todays:
        L.append("Bugün önemli veri yok.")
    for e in todays:
        L.append(event_line(e))
    L += ["", "🔴 yüksek · 🟠 orta önem · bkl = beklenti · önc = önceki", "<i>Kaynak: ForexFactory</i>"]
    return "\n".join(L)


def news_message(new_items, now_tr, per_cat):
    L = [f"📰 <b>Son Haberler</b> · {now_tr:%H:%M} TSİ"]
    any_item = False
    for cat, items in new_items.items():
        if not items:
            continue
        any_item = True
        L += ["", f"<b>{cat}</b>"]
        for it in items[:per_cat]:
            L.append(f"• <a href=\"{html.escape(it['link'])}\">{esc(it['title'])}</a> <i>({esc(it['source'])})</i>")
    return "\n".join(L) if any_item else None


def split_message(text, limit=4000):
    if len(text) <= limit:
        return [text]
    parts, cur = [], ""
    for block in text.split("\n\n"):
        if len(cur) + len(block) + 2 > limit and cur:
            parts.append(cur)
            cur = block
        else:
            cur = f"{cur}\n\n{block}" if cur else block
    if cur:
        parts.append(cur)
    return parts


# --------------------------------------------------------------------------- #
# Ana akış
# --------------------------------------------------------------------------- #
def main():
    cfg = sc.load_json(sc.CONFIG_PATH, {})
    rcfg = cfg.get("report", {})
    if not rcfg.get("enabled", True):
        print("Rapor kapalı.")
        return 0
    notifier = sc.Notifier()
    state = sc.load_json(STATE_PATH, {"seen": {}, "calendar_day": ""})
    state.setdefault("seen", {})
    now_utc = datetime.now(timezone.utc)
    now_tr = now_utc.astimezone(TR_TZ)
    api = sc.Binance()

    feeds = rcfg.get("feeds") or DEFAULT_FEEDS
    with ThreadPoolExecutor(max_workers=10) as ex:
        f_deriv = ex.submit(safe, btc_derivatives, api)
        f_spot = ex.submit(safe, btc_spot)
        f_quotes = {sym: ex.submit(safe, market_quote, sym) for _, sym in MARKETS}
        f_etf = {a: ex.submit(safe, etf_flows, a) for a in ("btc", "eth")}
        f_cal = ex.submit(safe, calendar_events)
        f_feeds = {(cat, src): ex.submit(safe, parse_feed, src, url)
                   for cat, lst in feeds.items() for src, url in lst}
        deriv, spot = f_deriv.result(), f_spot.result()
        quotes = {s: fu.result() for s, fu in f_quotes.items()}
        etf = {"BTC": f_etf["btc"].result(), "ETH": f_etf["eth"].result()}
        events = f_cal.result()
        feed_items = {k: fu.result() or [] for k, fu in f_feeds.items()}

    messages = []

    # Sabah ekonomik takvimi (günde bir kez)
    day_key = now_tr.strftime("%Y-%m-%d")
    if events is not None and now_tr.hour >= rcfg.get("calendar_daily_hour", 9) and state.get("calendar_day") != day_key:
        messages.append(("calendar", calendar_message(events, now_tr.date(), rcfg)))

    if rcfg.get("market_hourly", True):
        messages.append(("market", market_message(now_tr, deriv, spot, quotes, etf, events, rcfg)))

    # Haberler: sadece yeni ve son N saatte yayınlanmış olanlar
    max_age = timedelta(hours=rcfg.get("news_max_age_hours", 2))
    first_run = not state["seen"]
    new_by_cat, seen_now = {}, {}
    for (cat, src), items in feed_items.items():
        for it in items:
            seen_now[it["link"]] = time.time()
            if it["link"] in state["seen"]:
                continue
            if it["dt"] and now_utc - it["dt"] > max_age:
                continue
            new_by_cat.setdefault(cat, []).append(it)
    for cat in new_by_cat:
        new_by_cat[cat].sort(key=lambda x: x["dt"] or now_utc, reverse=True)
    per_cat = rcfg.get("news_per_category", 5) if not first_run else 3
    ordered = {cat: new_by_cat.get(cat, []) for cat in feeds}
    if rcfg.get("news_hourly", True):
        nm = news_message(ordered, now_tr, per_cat)
        if nm:
            messages.append(("news", nm))

    sent_ok = True
    for kind, text in messages:
        for part in split_message(text):
            try:
                if not notifier.send(part):
                    sent_ok = False
            except Exception as e:  # noqa: BLE001
                sent_ok = False
                print(f"  Telegram hatası ({kind}): {e}", file=sys.stderr)
        if kind == "calendar" and sent_ok:
            state["calendar_day"] = day_key

    # Durum: görülen haber linkleri (7 gün)
    if sent_ok:
        state["seen"].update(seen_now)
    cutoff = time.time() - 7 * 86400
    state["seen"] = {k: v for k, v in state["seen"].items() if v >= cutoff}
    if not notifier.dry or os.environ.get("SORBOT_SAVE_DRY_STATE") == "1":
        sc.save_json(STATE_PATH, state)
    n_news = sum(len(v[:per_cat]) for v in ordered.values())
    print(f"Rapor: {len(messages)} mesaj ({n_news} haber), {sum(len(v) for v in feed_items.values())} haber tarandı")
    return 0


if __name__ == "__main__":
    sys.exit(main())
