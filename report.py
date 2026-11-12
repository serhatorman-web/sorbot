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
import whales
import econ

TR_TZ = sc.TR_TZ
STATE_PATH = os.path.join(sc.BASE_DIR, "state", "report_state.json")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
SPOT = "https://data-api.binance.vision"

MARKETS = [
    ("S&P 500", "^GSPC"), ("Nasdaq", "^IXIC"), ("Dow Jones", "^DJI"), ("Nasdaq vadeli", "NQ=F"),
    ("VIX", "^VIX"), ("Dolar endeksi", "DX-Y.NYB"), ("ABD 10Y faiz", "^TNX"),
    ("Altın", "GC=F"), ("Brent petrol", "BZ=F"), ("Petrol (WTI)", "CL=F"),
]

# Sadece Türkçe kaynaklar. Üçüncü alan bir filtre: "ai" = sadece yapay zeka ile ilgili başlıklar.
DEFAULT_FEEDS = {
    "💵 Ekonomi & Finans": [
        ("Investing TR", "https://tr.investing.com/rss/news_14.rss", None),
        ("Bloomberg HT", "https://www.bloomberght.com/rss", None),
        ("AA Ekonomi", "https://www.aa.com.tr/tr/rss/default?cat=ekonomi", None),
        ("Dünya", "https://www.dunya.com/rss", None),
    ],
    "🪙 Kripto": [
        ("Investing TR Kripto", "https://tr.investing.com/rss/news_301.rss", None),
        ("BTCHaber", "https://www.btchaber.com/feed/", None),
    ],
    "🤖 Yapay Zeka": [
        ("Webtekno", "https://www.webtekno.com/rss.xml", "ai"),
        ("ShiftDelete", "https://shiftdelete.net/feed", "ai"),
        ("DonanımHaber", "https://www.donanimhaber.com/rss/tum/", "ai"),
        ("LOG", "https://www.log.com.tr/feed/", "ai"),
        ("Teknoblog", "https://www.teknoblog.com/feed/", "ai"),
    ],
}

AI_PATTERN = re.compile(
    r"yapay ?zek[aâ]|\bAI\b|\bA\.I\.|OpenAI|ChatGPT|\bGPT|Gemini|Claude|Anthropic|Copilot|\bLLM|"
    r"Nvidia|DeepSeek|Grok|xAI|Llama|Mistral|Midjourney|\bSora\b|makine öğren|derin öğren|yapay sinir",
    re.IGNORECASE)
SKIP_LINK = ("/transcripts/",)   # Investing'in şirket konferans dökümleri
# Önemsiz şirket haberleri: içeriden alım/satım, analist notu, atama vb.
SKIP_TITLE = re.compile(
    r"hisse (aldı|sattı|satın aldı)|hissesi? için .*görüş|görüşünü (korudu|yineledi)|hedef fiyat|"
    r"not(unu|u) (yükseltti|düşürdü)|tavsiyesini|direktörlüğüne|terfi|yönetim kuruluna|atadı|atandı|"
    r"temettü ilan|konferans(ı|ında)|kazanç çağrısı|bahis|casino",
    re.IGNORECASE)
PER_SOURCE_MAX = 2


# Önem puanı: piyasayı etkileyen konular. (desen, puan)
IMPORTANCE = [
    # Merkez bankaları ve para politikası
    (r"\bFed\b|FOMC|Powell|Merkez Bankas|TCMB|\bECB\b|\bAMB\b|Lagarde|BoJ|BoE|faiz (karar|indirim|artır|art[ıi]ş)", 3),
    (r"faiz|para politikas|parasal", 2),
    # Makro veriler
    (r"enflasyon|TÜFE|ÜFE|\bCPI\b|\bPPI\b|PCE|tarım dışı|istihdam|işsizlik|GSYH|büyüme verisi|resesyon|durgunluk", 3),
    (r"perakende satış|(imalat|hizmet|bileşik) PMI|PMI (verisi|endeksi)|cari açık|bütçe açığı|kredi notu|Moody|Fitch|S&P Global", 2),
    # Jeopolitik ve politika
    (r"savaş|saldırı|füze|ateşkes|yaptırım|gümrük|tarife|ambargo|seçim|darbe|Hürmüz", 3),
    (r"Trump|Beyaz Saray|Kongre|Hazine|Putin|Şi Cinping|Xi Jinping|NATO|AB Komisyon|OPEC", 2),
    # Piyasa hareketleri
    (r"rekor|çöktü|çöküş|sert (düş|yüksel)|tarihi (zirve|dip)|panik|kriz|iflas|temerrüt|batı[şy]", 3),
    (r"Borsa İstanbul|\bBIST|dolar/TL|dolar/TL|\bTL\b|Türk lirası", 2),
    (r"Wall Street|Nasdaq|S&P 500|\bDow\b|dolar endeksi|euro/dolar|altın|petrol|Brent|\bons\b", 1),
    (r"aştı|zirve|en yüksek|en düşük|geriledi|değer kaybı|değer kazan", 1),
    (r"bilanço|kâr açıkla|gelir beklenti|halka arz|satın al|birleşme|milyar dolar", 1),
    # Kripto
    (r"Bitcoin|BTC|Ethereum|\bETH\b|kripto", 1),
    (r"\bETF\b|\bSEC\b|regülasyon|düzenleme|yasa tasarı|Binance|Coinbase|BlackRock|hack|saldırgan|stablecoin|GENIUS", 2),
    # Yapay zeka
    (r"OpenAI|Nvidia|Anthropic|Google|Microsoft|\bMeta\b|\bApple\b|çip|yarı iletken|regülasyon|yasa", 1),
    (r"yeni model|GPT-?\d|Gemini \d|Claude|yatırım|milyar|ihracat kısıtlama|yasak", 1),
]
IMPORTANCE = [(re.compile(p, re.IGNORECASE), w) for p, w in IMPORTANCE]


def importance(title):
    return sum(w for rx, w in IMPORTANCE if rx.search(title))


def title_signature(title):
    """Başlığın kaba kök kümesi (Türkçe ekleri tolere etmek için kelimelerin ilk 5 harfi)."""
    words = re.findall(r"\w+", title.lower())
    return {w[:5] for w in words if len(w) >= 4}


def similar(a, b, threshold=0.45):
    if not a or not b:
        return False
    return len(a & b) / len(a | b) >= threshold


def keep_item(item, flt):
    if any(s in item["link"] for s in SKIP_LINK) or SKIP_TITLE.search(item["title"]):
        return False
    if flt == "ai":
        return bool(AI_PATTERN.search(item["title"]))
    return True

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


TR_MONTHS = {"Jan": "Ocak", "Feb": "Şubat", "Mar": "Mart", "Apr": "Nisan", "May": "Mayıs", "Jun": "Haziran",
             "Jul": "Temmuz", "Aug": "Ağustos", "Sep": "Eylül", "Oct": "Ekim", "Nov": "Kasım", "Dec": "Aralık"}


def tr_date(s):
    """'10 Nov 2026' -> '10 Kasım'"""
    parts = s.split()
    return f"{int(parts[0])} {TR_MONTHS.get(parts[1], parts[1])}" if len(parts) == 3 else s


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
    return {"date": last[0], "total": num(last[-1]) or 0.0, "top": funds[:3], "funds": funds,
            "sum5": sum(week), "n5": len(week)}


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
def market_message(now_tr, d, spot, quotes, etf, events, rcfg, whale=None):
    L = [f"📊 <b>Saatlik Piyasa Raporu</b> · {now_tr:%d.%m.%Y %H:%M} TSİ", ""]

    if d:
        L.append(f"<b>₿ BTC</b> <code>${d['price']:,.0f}</code> · 24s {arrow(d['chg24'])} {d['chg24']:+.2f}%"
                 + (f" · 1s {spot['price_chg_1h']:+.2f}%" if spot else ""))
        nf = datetime.fromtimestamp(d["next_funding"] / 1000, TR_TZ)
        fr = d["funding"] * 100
        if fr > 0:
            fr_note = "🟢 <b>Pozitif</b> – long'lar short'lara ödüyor"
        elif fr < 0:
            fr_note = "🔴 <b>Negatif</b> – short'lar long'lara ödüyor"
        else:
            fr_note = "⚪ <b>Nötr</b>"
        L.append(f"💰 Fonlama: <b>{fr:+.4f}%</b> · {fr_note} · sonraki {nf:%H:%M}")
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

    if whale:
        L += [""] + whale_lines(whale, rcfg)

    if etf:
        L += ["", "<b>🏛 Spot ETF Giriş / Çıkış</b> (Farside)"]

        def flow(v):
            if v > 0:
                return f"🟢 Giriş <b>{v:,.1f} mn $</b>"
            if v < 0:
                return f"🔴 Çıkış <b>{abs(v):,.1f} mn $</b>"
            return "⚪ Giriş/çıkış yok"

        for asset, e in etf.items():
            if not e:
                continue
            L.append(f"{asset} spot ETF ({tr_date(e['date'])}): {flow(e['total'])}")
            L.append(f"   son {e['n5']} gün toplam: {flow(e['sum5'])}")

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


def whale_lines(w, rcfg):
    L = ["<b>🐋 Balina Hareketleri</b>"]
    for asset, key, url, unit in (("BTC", "btc", "https://mempool.space/tx/", "BTC"),
                                  ("ETH", "eth", "https://etherscan.io/tx/", "ETH")):
        tr = w.get(key)
        if tr is None:
            L.append(f"{asset} zincir üstü: veri alınamadı")
            continue
        mn = rcfg.get(f"whale_{key}_min_usd", 10_000_000 if key == "btc" else 5_000_000)
        if not tr:
            L.append(f"🔗 {asset} zincir üstü (≥{fmt_usd(mn)}): son saatte büyük transfer yok")
            continue
        tot = sum(x["usd"] for x in tr)
        L.append(f"🔗 {asset} zincir üstü (≥{fmt_usd(mn)}): <b>{len(tr)} transfer</b>, toplam {fmt_usd(tot)}")
        for x in tr[:3]:
            t = datetime.fromtimestamp(x["time"], TR_TZ).strftime("%H:%M")
            L.append(f"   • <a href=\"{url}{x['hash']}\">{x['amount']:,.0f} {unit}</a> ({fmt_usd(x['usd'])}) · {t}")
    for asset in ("BTC", "ETH"):
        ob = w.get("ob_" + asset)
        if not ob:
            continue
        for mkt in ("Vadeli", "Spot"):
            o = ob.get(mkt)
            if not o:
                continue
            b, a = o["bid_usd"], o["ask_usd"]
            side = "alıcılar" if b > a * 1.1 else ("satıcılar" if a > b * 1.1 else "dengeli")
            bw_p, bw_v = o["bid_wall"]
            aw_p, aw_v = o["ask_wall"]
            L.append(f"📗 {asset} {mkt} emir defteri: alış {fmt_usd(b)} / satış {fmt_usd(a)} · <b>{side}</b>")
            L.append(f"   en büyük alış duvarı {fmt_usd(bw_v)} @ {bw_p:,.0f} · satış duvarı {fmt_usd(aw_v)} @ {aw_p:,.0f}")
    L.append("<i>Transfer = alış/satış değildir; büyük oyuncuların fon hareketini gösterir.</i>")
    return L


def etf_alert_messages(etf, state, rcfg):
    """Büyük ETF giriş/çıkışı olduğunda ayrı uyarı (yeni gün veya önemli güncelleme)."""
    msgs = []
    alerts = state.setdefault("etf_alert", {})
    for asset, e in etf.items():
        if not e:
            continue
        thr = rcfg.get(f"etf_alert_{asset.lower()}_musd", 100 if asset == "BTC" else 50)
        if abs(e["total"]) < thr:
            continue
        prev = alerts.get(asset, {})
        if prev.get("date") == e["date"] and abs(prev.get("total", 0) - e["total"]) < thr / 2:
            continue
        word = "GİRİŞİ" if e["total"] > 0 else "ÇIKIŞI"
        icon = "🟢" if e["total"] > 0 else "🔴"
        L = [f"🏛 {icon} <b>BÜYÜK {asset} SPOT ETF {word}</b> · {tr_date(e['date'])}", "",
             f"Toplam net akış: <b>{e['total']:+,.1f} milyon $</b>",
             f"Son {e['n5']} gün: {e['sum5']:+,.1f} milyon $", ""]
        big = [(n, v) for n, v in e["funds"] if abs(v) >= rcfg.get("etf_alert_fund_musd", 20)]
        if big:
            L.append("Büyük fon hareketleri:")
            for n, v in big[:6]:
                L.append(f"{'🟢' if v > 0 else '🔴'} {esc(n)}: {v:+,.1f} mn $")
        L += ["", "<i>Kaynak: Farside Investors</i>"]
        msgs.append((asset, e, "\n".join(L)))
    return msgs


def collect_whales(api, btc_price, eth_price, state, rcfg):
    w = {}
    with ThreadPoolExecutor(max_workers=4) as ex:
        f_btc = ex.submit(safe, whales.btc_transfers, btc_price,
                          rcfg.get("whale_btc_min_usd", 10_000_000), state.get("btc_height"))
        f_eth = ex.submit(safe, whales.eth_transfers, eth_price,
                          rcfg.get("whale_eth_min_usd", 5_000_000), state.get("eth_block"))
        f_ob = {a: ex.submit(safe, whales.orderbook, api, a + "USDT", b)
                for a, b in (("BTC", 100), ("ETH", 5))}
        b, e = f_btc.result(), f_eth.result()
        for a, fu in f_ob.items():
            w["ob_" + a] = fu.result()
    w["btc"], w["eth"] = (b[0] if b else None), (e[0] if e else None)
    w["_btc_height"], w["_eth_block"] = (b[1] if b else None), (e[1] if e else None)
    return w


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
            mark = "🔥" if it.get("imp", 0) >= 5 else "•"
            L.append(f"{mark} <a href=\"{html.escape(it['link'])}\">{esc(it['title'])}</a> <i>({esc(it['source'])})</i>")
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
# Saatlik bülten (haberler + açıklanan/yaklaşan veriler) ve sabah takvimi
# --------------------------------------------------------------------------- #
TR_DAYS = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
TR_MONTH_NAMES = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül",
                  "Ekim", "Kasım", "Aralık"]
LINE = "━━━━━━━━━━━━━━━━━━━━"
IMP_ICON = {1: "🔴", 0: "🟠", -1: "🟡"}


def tr_upper(t):
    """Türkçe büyük harf (i -> İ, ı -> I)."""
    return t.replace("i", "İ").replace("ı", "I").upper()


def tr_long_date(d):
    return f"{d.day} {TR_MONTH_NAMES[d.month - 1]} {d.year} {TR_DAYS[d.weekday()]}"


# --------------------------------------------------------------------------- #
# Piyasalar bölümü
# --------------------------------------------------------------------------- #
# (ad, Yahoo sembolü, Binance spot endeks sembolü veya None, para birimi öneki)
MARKET_GROUPS = [
    ("📈 Borsalar", [
        ("Dow Jones", "^DJI", None, ""), ("S&P 500", "^GSPC", None, ""), ("Nasdaq 100", "^NDX", None, ""),
        ("BIST 100", "XU100.IS", None, ""), ("Nikkei 225 (Japonya)", "^N225", None, ""),
        ("DAX (Almanya)", "^GDAXI", None, ""), ("FTSE 100 (İngiltere)", "^FTSE", None, ""),
        ("CAC 40 (Fransa)", "^FCHI", None, ""), ("Hang Seng (Hong Kong)", "^HSI", None, ""),
        ("Şanghay (Çin)", "000001.SS", None, ""), ("KOSPI (Kore)", "^KS11", None, ""),
    ]),
    ("🥇 Değerli Metaller & Emtia", [
        ("Spot Altın (ons)", "GC=F", "XAUUSDT", "$"), ("Gram Altın", "GRAM", None, "₺"),
        ("Gümüş (ons)", "SI=F", "XAGUSDT", "$"), ("Platin (ons)", "PL=F", "XPTUSDT", "$"),
        ("Paladyum (ons)", "PA=F", "XPDUSDT", "$"), ("Brent Petrol", "BZ=F", None, "$"),
        ("WTI Petrol", "CL=F", None, "$"), ("Doğalgaz", "NG=F", None, "$"), ("Bakır", "HG=F", None, "$"),
    ]),
    ("💵 Döviz", [
        ("Dolar Endeksi (DXY)", "DX-Y.NYB", None, ""), ("USD/TRY", "TRY=X", None, "₺"), ("EUR/TRY", "EURTRY=X", None, "₺"),
    ]),
]
GRAM_PER_OUNCE = 31.1034768


def yahoo_quote(symbol):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}?interval=1d&range=1d"
    meta = get(url)["chart"]["result"][0]["meta"]
    price = meta.get("regularMarketPrice")
    prev = meta.get("chartPreviousClose") or meta.get("previousClose")
    reg = (meta.get("currentTradingPeriod") or {}).get("regular") or {}
    now = time.time()
    return {"price": price, "chg": (price / prev - 1) * 100 if price and prev else None,
            "open": reg.get("start", 0) <= now < reg.get("end", 0)}


def tr_num(x, dec=2):
    """Türkçe sayı biçimi: 52.680,84"""
    s = f"{x:,.{dec}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def collect_markets(api):
    syms = {sym for _, items in MARKET_GROUPS for _, sym, _, _ in items if sym != "GRAM"}
    spot = {bsym for _, items in MARKET_GROUPS for _, _, bsym, _ in items if bsym}
    with ThreadPoolExecutor(max_workers=10) as ex:
        fq = {s_: ex.submit(safe, yahoo_quote, s_) for s_ in syms}
        fs = {b: ex.submit(safe, lambda b=b: float(api.get("/fapi/v1/premiumIndex", {"symbol": b})["indexPrice"]))
              for b in spot}
        quotes = {s_: f_.result() for s_, f_ in fq.items()}
        spots = {b: f_.result() for b, f_ in fs.items()}
    # Spot metaller: fiyat Binance spot endeksinden, değişim ve açık/kapalı vadeli kontrattan
    for _, items in MARKET_GROUPS:
        for _, sym, bsym, _ in items:
            if bsym and spots.get(bsym) and quotes.get(sym):
                quotes[sym] = dict(quotes[sym], price=spots[bsym])
    gold, usd = quotes.get("GC=F"), quotes.get("TRY=X")
    if gold and usd and gold["price"] and usd["price"]:
        chg = None
        if gold["chg"] is not None and usd["chg"] is not None:
            chg = ((1 + gold["chg"] / 100) * (1 + usd["chg"] / 100) - 1) * 100
        quotes["GRAM"] = {"price": gold["price"] * usd["price"] / GRAM_PER_OUNCE, "chg": chg, "open": gold["open"]}
    return quotes


def pct_tr(chg):
    if chg is None:
        return "–"
    return ("+" if chg > 0 else ("-" if chg < 0 else "")) + "%" + tr_num(abs(chg))


def chg_icon(chg):
    return "🟢" if chg and chg > 0 else ("🔴" if chg and chg < 0 else "⚪")


def markets_block(quotes):
    """Piyasalar: önceki görünüm – tüm satırlar açık, gruplar arasında boş satır."""
    if not quotes or not any(quotes.values()):
        return []
    L = ["🌍 <b>PİYASALAR</b>"]
    for title, items in MARKET_GROUPS:
        rows = []
        for name, sym, _, cur in items:
            q = quotes.get(sym)
            if not q or q.get("price") is None:
                continue
            dec = 4 if sym in ("TRY=X", "EURTRY=X") else (3 if q["price"] < 10 else 2)
            status = "Açık" if q.get("open") else "Kapalı"
            rows.append(f"{chg_icon(q.get('chg'))} {name}: <b>{cur}{tr_num(q['price'], dec)}</b> · "
                        f"{pct_tr(q.get('chg'))} · <i>{status}</i>")
        if rows:
            L += ["", f"<b>{title}</b>"] + rows
    return L


def market_summary(quotes):
    """Kısa özet: yükselen/düşen sayısı ve öne çıkanlar."""
    vals = [q for q in quotes.values() if q and q.get("chg") is not None]
    if not vals:
        return None
    up = sum(1 for q in vals if q["chg"] > 0)
    dn = sum(1 for q in vals if q["chg"] < 0)
    parts = [f"🟢 {up} yükselen · 🔴 {dn} düşen"]
    for name, sym in (("Altın", "GC=F"), ("BIST", "XU100.IS"), ("Nasdaq", "^NDX"), ("Dolar/TL", "TRY=X")):
        q = quotes.get(sym)
        if q and q.get("chg") is not None:
            parts.append(f"{name} {pct_tr(q['chg'])}")
    return " · ".join(parts)


def quote(lines, expandable=False):
    """Telegram alıntı kutusu (blockquote). İçinde boş satır olmamalı."""
    body = "\n".join(x for x in lines if x != "")
    return f"<blockquote{' expandable' if expandable else ''}>{body}</blockquote>"


def released_block(events):
    L = []
    for e in events:
        t = e["dt"].astimezone(TR_TZ)
        L.append(f"{IMP_ICON.get(e['importance'], '•')} <b>{esc(e['tr'])}</b> · {econ.country_label(e['country'])} · {t:%H:%M}")
        L.append(f"      Gerçekleşen: <b>{esc(econ.fmt_val(e, 'actual'))}</b>  │  Beklenti: {esc(econ.fmt_val(e, 'forecast'))}"
                 f"  │  Önceki: {esc(econ.fmt_val(e, 'previous'))}")
        v = econ.verdict(e)
        if v:
            L.append(f"      {v[0]} {v[1]}")
        imp = econ.asset_impact(e)
        if imp:
            L.append(f"      💡 <i>{esc(imp['reason'])}</i>")
            L.append("      " + "  ·  ".join(f"{ic} {t_}" for ic, t_ in imp["items"]))
    return L


def upcoming_block(events):
    L = []
    for e in events:
        t = e["dt"].astimezone(TR_TZ)
        extra = []
        if e.get("forecast") is not None:
            extra.append(f"Bkl {econ.fmt_val(e, 'forecast')}")
        if e.get("previous") is not None:
            extra.append(f"Önc {econ.fmt_val(e, 'previous')}")
        tail = f"\n      <i>{esc(' · '.join(extra))}</i>" if extra else ""
        L.append(f"{IMP_ICON.get(e['importance'], '•')} <b>{t:%H:%M}</b> {econ.country_label(e['country'])} · {esc(e['tr'])}{tail}")
    return L


def news_block(items, per_cat):
    L = []
    for it in items[:per_cat]:
        mark = "🔥" if it.get("imp", 0) >= 5 else "▫️"
        t = it["dt"].astimezone(TR_TZ).strftime("%H:%M") if it.get("dt") else ""
        # başlık normal yazı (link rengi/soluk alıntı yok); link kısa bir "oku" bağlantısında
        L.append(f"{mark} {esc(it['title'])}\n      {esc(it['source'])}{' · ' + t if t else ''}"
                 f" · <a href=\"{html.escape(it['link'])}\">oku</a>")
    return L


def bulletin_message(now_tr, released, upcoming, news, rcfg, markets=None):
    blocks = []
    mk = markets_block(markets) if markets else []
    if mk:
        blocks.append("\n".join(mk))
    if released:
        blocks.append("\n".join(["📊 <b>AÇIKLANAN VERİLER</b> <i>(son 1 saat)</i>", ""] + released_block(released)))
    if upcoming:
        h = rcfg.get("calendar_lookahead_hours", 3)
        blocks.append("\n".join([f"🗓 <b>YAKLAŞAN VERİLER</b> <i>(önümüzdeki {h} saat)</i>", ""] + upcoming_block(upcoming)))
    for cat, items in news.items():
        if items:
            icon, title = (cat.split(" ", 1) + [""])[:2] if " " in cat else ("", cat)
            blocks.append(f"{icon} <b>{tr_upper(title)}</b>\n"
                          + "\n".join(news_block(items, rcfg.get("news_per_category", 5))))
    if not blocks:
        return None
    header = "\n".join([LINE, "📰 <b>SAATLİK PİYASA BÜLTENİ</b>", f"🕐 {tr_long_date(now_tr)} · {now_tr:%H:%M}", LINE])
    footer = "\n".join([LINE, "🔴 yüksek önem · 🟠 orta önem · 🔥 öne çıkan haber", "<i>Yatırım tavsiyesi değildir.</i>"])
    return "\n\n".join([header] + blocks + [footer])


def morning_calendar_message(now_tr, events):
    L = [LINE, "🗓 <b>GÜNÜN EKONOMİK TAKVİMİ</b>", f"📅 {tr_long_date(now_tr)}", LINE]
    if not events:
        L += ["", "Bugün önemli veri yok."]
    by_c = {}
    for e in events:
        by_c.setdefault(e["country"], []).append(e)
    names = {"US": "ABD", "TR": "Türkiye", "EU": "Euro Bölgesi", "CN": "Çin"}
    for c in sorted(by_c, key=lambda x: (x != "US", x != "TR", x)):
        L += ["", f"{econ.FLAGS.get(c, '')} <b>{names.get(c, c)}</b>", ""] + upcoming_block(by_c[c])
    L += ["", LINE, "🔴 yüksek önem · 🟠 orta önem · Bkl = beklenti · Önc = önceki", "<i>Kaynak: TradingView ekonomik takvim</i>"]
    return "\n".join(L)


def collect_news(feeds, state, rcfg, now_utc):
    with ThreadPoolExecutor(max_workers=10) as ex:
        futs = {(cat, src, url, (rest[0] if rest else None)): ex.submit(safe, parse_feed, src, url)
                for cat, lst in feeds.items() for src, url, *rest in lst}
        feed_items = {k: fu.result() or [] for k, fu in futs.items()}
    max_age = timedelta(hours=rcfg.get("news_max_age_hours", 2))
    min_imp = rcfg.get("news_min_importance", 2)
    new_by_cat, seen_now, picked_sigs = {cat: [] for cat in feeds}, {}, []
    run_links = set()
    for (cat, src, url, flt), items in feed_items.items():
        for it in items:
            seen_now[it["link"]] = time.time()
            if it["link"] in state["seen"] or it["link"] in run_links or not keep_item(it, flt):
                continue
            if it["dt"] and now_utc - it["dt"] > max_age:
                continue
            it["imp"] = importance(it["title"])
            cat_min = rcfg.get("news_min_importance_by_category", {}).get(cat, min_imp)
            if rcfg.get("news_important_only", True) and it["imp"] < cat_min:
                continue
            run_links.add(it["link"])
            new_by_cat[cat].append(it)
    for cat in new_by_cat:
        new_by_cat[cat].sort(key=lambda x: (x["imp"], x["dt"] or now_utc), reverse=True)
        per_src, picked = {}, []
        for it in new_by_cat[cat]:
            sig = title_signature(it["title"])
            if any(similar(sig, p_) for p_ in picked_sigs):
                continue
            if per_src.get(it["source"], 0) < PER_SOURCE_MAX:
                per_src[it["source"]] = per_src.get(it["source"], 0) + 1
                picked.append(it)
                picked_sigs.append(sig)
        new_by_cat[cat] = picked
    return new_by_cat, seen_now, sum(len(v) for v in feed_items.values())


def run_bulletin(cfg, rcfg, notifier, state):
    now_utc = datetime.now(timezone.utc)
    now_tr = now_utc.astimezone(TR_TZ)
    countries = tuple(rcfg.get("calendar_countries", ["US", "TR"]))
    min_imp = rcfg.get("calendar_min_importance", 0)
    cats = rcfg.get("news_categories", ["💵 Ekonomi & Finans", "🪙 Kripto"])
    feeds = {c: v for c, v in (rcfg.get("feeds") or DEFAULT_FEEDS).items() if c in cats}

    day_start = now_tr.replace(hour=0, minute=0, second=0, microsecond=0)
    try:
        events = econ.fetch_events(day_start.astimezone(timezone.utc) - timedelta(hours=6),
                                   now_utc + timedelta(hours=30), countries)
    except Exception as e:  # noqa: BLE001
        print(f"  [uyarı] takvim alınamadı: {e}")
        events = None
    news, seen_now, n_scanned = collect_news(feeds, state, rcfg, now_utc)
    markets = collect_markets(sc.Binance()) if rcfg.get("markets", True) else None

    last = datetime.fromtimestamp(state.get("last_bulletin", (now_utc - timedelta(hours=1)).timestamp()), timezone.utc)
    last = max(last, now_utc - timedelta(hours=3))
    sent_ids = set(state.get("sent_events", []))
    released, upcoming = [], []
    if events is not None:
        released = [e for e in events if e["actual"] is not None and last < e["dt"] <= now_utc
                    and e["importance"] >= min_imp and e["id"] not in sent_ids]
        horizon = now_utc + timedelta(hours=rcfg.get("calendar_lookahead_hours", 3))
        upcoming = [e for e in events if now_utc < e["dt"] <= horizon and e["importance"] >= min_imp]

    messages = []
    day_key = now_tr.strftime("%Y-%m-%d")
    if events is not None and now_tr.hour >= rcfg.get("calendar_daily_hour", 9) and state.get("calendar_day") != day_key:
        todays = [e for e in events if e["dt"].astimezone(TR_TZ).date() == now_tr.date() and e["importance"] >= min_imp]
        messages.append(("calendar", morning_calendar_message(now_tr, todays)))
    b = bulletin_message(now_tr, released, upcoming, news, rcfg, markets)
    if b:
        messages.append(("bulletin", b))

    ok = True
    for kind, text in messages:
        text = sc.plain_font(text)       # tek yazı tipi: eğik / sabit genişlikli yok
        for part in split_message(text):
            try:
                ok = notifier.send(part) and ok
            except Exception as e:  # noqa: BLE001
                ok = False
                print(f"  Telegram hatası ({kind}): {e}", file=sys.stderr)
        if kind == "calendar" and ok:
            state["calendar_day"] = day_key
    if ok:
        state["seen"].update(seen_now)
        state["last_bulletin"] = now_utc.timestamp()
        state["sent_events"] = (list(sent_ids) + [e["id"] for e in released])[-300:]
    n_news = sum(len(v[:rcfg.get("news_per_category", 5)]) for v in news.values())
    print(f"Bülten: {len(messages)} mesaj · {len(released)} açıklanan veri · {len(upcoming)} yaklaşan · "
          f"{n_news} haber ({n_scanned} tarandı)")


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
    if rcfg.get("mode") == "bulletin":
        run_bulletin(cfg, rcfg, notifier, state)
        cutoff = time.time() - 7 * 86400
        state["seen"] = {k: v for k, v in state["seen"].items() if v >= cutoff}
        if not notifier.dry or os.environ.get("SORBOT_SAVE_DRY_STATE") == "1":
            sc.save_json(STATE_PATH, state)
        return 0
    now_utc = datetime.now(timezone.utc)
    now_tr = now_utc.astimezone(TR_TZ)
    api = sc.Binance()

    feeds = rcfg.get("feeds") or DEFAULT_FEEDS
    with ThreadPoolExecutor(max_workers=10) as ex:
        f_deriv = ex.submit(safe, btc_derivatives, api)
        f_eth = ex.submit(safe, lambda: float(api.get('/fapi/v1/ticker/price', {'symbol': 'ETHUSDT'})['price']))
        f_spot = ex.submit(safe, btc_spot)
        f_quotes = {sym: ex.submit(safe, market_quote, sym) for _, sym in MARKETS}
        f_etf = {a: ex.submit(safe, etf_flows, a) for a in ("btc", "eth")}
        f_cal = ex.submit(safe, calendar_events)
        f_feeds = {(cat, src, url, (rest[0] if rest else None)): ex.submit(safe, parse_feed, src, url)
                   for cat, lst in feeds.items() for src, url, *rest in lst}
        deriv, spot = f_deriv.result(), f_spot.result()
        quotes = {s: fu.result() for s, fu in f_quotes.items()}
        etf = {"BTC": f_etf["btc"].result(), "ETH": f_etf["eth"].result()}
        events = f_cal.result()
        eth_price = f_eth.result()
        feed_items = {k: fu.result() or [] for k, fu in f_feeds.items()}

    whale = None
    if rcfg.get("whales", True) and deriv and eth_price:
        whale = collect_whales(api, deriv["price"], eth_price, state, rcfg)

    messages = []
    etf_alerts = etf_alert_messages(etf, state, rcfg) if rcfg.get("etf_alerts", True) else []
    for asset, e, text in etf_alerts:
        messages.append(("etf_" + asset, text))

    # Sabah ekonomik takvimi (günde bir kez)
    day_key = now_tr.strftime("%Y-%m-%d")
    if events is not None and now_tr.hour >= rcfg.get("calendar_daily_hour", 9) and state.get("calendar_day") != day_key:
        messages.append(("calendar", calendar_message(events, now_tr.date(), rcfg)))

    if rcfg.get("market_hourly", True):
        messages.append(("market", market_message(now_tr, deriv, spot, quotes, etf, events, rcfg, whale)))

    # Haberler: sadece yeni ve son N saatte yayınlanmış olanlar
    max_age = timedelta(hours=rcfg.get("news_max_age_hours", 2))
    first_run = not state["seen"]
    new_by_cat, seen_now = {}, {}
    run_links, run_titles = set(), set()
    for (cat, src, url, flt), items in feed_items.items():
        for it in items:
            seen_now[it["link"]] = time.time()
            if it["link"] in state["seen"] or not keep_item(it, flt):
                continue
            tkey = re.sub(r"\W+", "", it["title"].lower())[:60]
            if it["link"] in run_links or tkey in run_titles:   # aynı haber farklı akışlarda
                continue
            run_links.add(it["link"])
            run_titles.add(tkey)
            if it["dt"] and now_utc - it["dt"] > max_age:
                continue
            new_by_cat.setdefault(cat, []).append(it)
    picked_sigs = []
    min_imp = rcfg.get("news_min_importance", 2)
    for cat in new_by_cat:
        for it in new_by_cat[cat]:
            it["imp"] = importance(it["title"])
        if rcfg.get("news_important_only", True):
            new_by_cat[cat] = [it for it in new_by_cat[cat] if it["imp"] >= min_imp]
        # önce önem, sonra yenilik
        new_by_cat[cat].sort(key=lambda x: (x["imp"], x["dt"] or now_utc), reverse=True)
        per_src, picked = {}, []
        for it in new_by_cat[cat]:
            sig = title_signature(it["title"])
            if any(similar(sig, p) for p in picked_sigs):   # aynı olay başka kaynaktan
                continue
            if per_src.get(it["source"], 0) < PER_SOURCE_MAX:   # kaynak başına sınır
                per_src[it["source"]] = per_src.get(it["source"], 0) + 1
                picked.append(it)
                picked_sigs.append(sig)
        new_by_cat[cat] = picked
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
        for asset, e, _ in etf_alerts:
            state.setdefault("etf_alert", {})[asset] = {"date": e["date"], "total": e["total"]}
        if whale:
            if whale.get("_btc_height"):
                state["btc_height"] = whale["_btc_height"]
            if whale.get("_eth_block"):
                state["eth_block"] = whale["_eth_block"]
    cutoff = time.time() - 7 * 86400
    state["seen"] = {k: v for k, v in state["seen"].items() if v >= cutoff}
    if not notifier.dry or os.environ.get("SORBOT_SAVE_DRY_STATE") == "1":
        sc.save_json(STATE_PATH, state)
    n_news = sum(len(v[:per_cat]) for v in ordered.values())
    print(f"Rapor: {len(messages)} mesaj ({n_news} haber), {sum(len(v) for v in feed_items.values())} haber tarandı")
    return 0


if __name__ == "__main__":
    sys.exit(main())
