"""
Ekonomik takvim (TradingView) – açıklanan / yaklaşan veriler ve Türkçe adlar.

Kaynak: economic-calendar.tradingview.com (gerçekleşen, beklenti, önceki değerler).
Önem: 1 = yüksek, 0 = orta, -1 = düşük.
"""

import json
import re
import urllib.request
from datetime import datetime, timezone

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
FLAGS = {"US": "🇺🇸", "TR": "🇹🇷", "EU": "🇪🇺", "CN": "🇨🇳", "GB": "🇬🇧", "JP": "🇯🇵", "DE": "🇩🇪"}
COUNTRY_NAMES = {"US": "ABD", "TR": "Türkiye", "EU": "Euro Bölgesi", "CN": "Çin", "GB": "İngiltere",
                 "JP": "Japonya", "DE": "Almanya"}


def country_label(code):
    """Bayrak + ülke adı, örn. '🇺🇸 ABD'."""
    return f"{FLAGS.get(code, '')} {COUNTRY_NAMES.get(code, code)}".strip()

# Sık açıklanan verilerin Türkçe adları (tam eşleşme, küçük harf)
TITLES = {
    "non farm payrolls": "Tarım Dışı İstihdam",
    "nonfarm payrolls": "Tarım Dışı İstihdam",
    "non farm payrolls private": "Özel Sektör Tarım Dışı İstihdam",
    "unemployment rate": "İşsizlik Oranı",
    "initial jobless claims": "İlk İşsizlik Başvuruları",
    "continuing jobless claims": "Devam Eden İşsizlik Başvuruları",
    "jobless claims 4-week average": "İşsizlik Başvuruları (4 Haftalık Ort.)",
    "adp employment change": "ADP Özel Sektör İstihdamı",
    "jolts job openings": "JOLTS Açık İş Pozisyonları",
    "average hourly earnings mom": "Ortalama Saatlik Kazanç (Aylık)",
    "average hourly earnings yoy": "Ortalama Saatlik Kazanç (Yıllık)",
    "participation rate": "İşgücüne Katılım Oranı",
    "inflation rate yoy": "Enflasyon – TÜFE (Yıllık)",
    "inflation rate mom": "Enflasyon – TÜFE (Aylık)",
    "core inflation rate yoy": "Çekirdek Enflasyon (Yıllık)",
    "core inflation rate mom": "Çekirdek Enflasyon (Aylık)",
    "cpi": "Tüketici Fiyat Endeksi (TÜFE)",
    "ppi mom": "Üretici Fiyat Endeksi – ÜFE (Aylık)",
    "ppi yoy": "Üretici Fiyat Endeksi – ÜFE (Yıllık)",
    "core ppi mom": "Çekirdek ÜFE (Aylık)",
    "core ppi yoy": "Çekirdek ÜFE (Yıllık)",
    "pce price index mom": "PCE Fiyat Endeksi (Aylık)",
    "pce price index yoy": "PCE Fiyat Endeksi (Yıllık)",
    "core pce price index mom": "Çekirdek PCE (Aylık)",
    "core pce price index yoy": "Çekirdek PCE (Yıllık)",
    "personal income mom": "Kişisel Gelir (Aylık)",
    "personal spending mom": "Kişisel Harcama (Aylık)",
    "retail sales mom": "Perakende Satışlar (Aylık)",
    "retail sales yoy": "Perakende Satışlar (Yıllık)",
    "retail sales ex autos mom": "Otomobil Hariç Perakende Satışlar (Aylık)",
    "gdp growth rate qoq": "GSYH Büyümesi (Çeyreklik)",
    "gdp growth rate qoq adv": "GSYH Büyümesi (Çeyreklik, Öncü)",
    "gdp growth rate qoq 2nd est": "GSYH Büyümesi (Çeyreklik, 2. Tahmin)",
    "gdp growth rate qoq final": "GSYH Büyümesi (Çeyreklik, Nihai)",
    "gdp growth rate yoy": "GSYH Büyümesi (Yıllık)",
    "fed interest rate decision": "Fed Faiz Kararı",
    "interest rate decision": "Faiz Kararı",
    "fomc minutes": "FOMC Toplantı Tutanakları",
    "fomc economic projections": "FOMC Ekonomik Projeksiyonları",
    "fed press conference": "Fed Basın Toplantısı",
    "fed chair powell speech": "Fed Başkanı Powell Konuşması",
    "ism manufacturing pmi": "ISM İmalat PMI",
    "ism services pmi": "ISM Hizmet PMI",
    "s&p global manufacturing pmi": "S&P Global İmalat PMI",
    "s&p global services pmi": "S&P Global Hizmet PMI",
    "s&p global composite pmi": "S&P Global Bileşik PMI",
    "chicago pmi": "Chicago PMI",
    "michigan consumer sentiment": "Michigan Tüketici Güveni",
    "michigan consumer sentiment final": "Michigan Tüketici Güveni (Nihai)",
    "michigan consumer sentiment prel": "Michigan Tüketici Güveni (Öncü)",
    "michigan inflation expectations": "Michigan Enflasyon Beklentisi",
    "michigan 5 year inflation expectations": "Michigan 5 Yıllık Enflasyon Beklentisi",
    "cb consumer confidence": "Conference Board Tüketici Güveni",
    "durable goods orders mom": "Dayanıklı Mal Siparişleri (Aylık)",
    "durable goods orders ex transportation mom": "Ulaşım Hariç Dayanıklı Mal Siparişleri (Aylık)",
    "factory orders mom": "Fabrika Siparişleri (Aylık)",
    "industrial production mom": "Sanayi Üretimi (Aylık)",
    "industrial production yoy": "Sanayi Üretimi (Yıllık)",
    "building permits": "İnşaat İzinleri",
    "housing starts": "Konut Başlangıçları",
    "existing home sales": "Mevcut Konut Satışları",
    "existing home sales mom": "Mevcut Konut Satışları (Aylık)",
    "new home sales mom": "Yeni Konut Satışları (Aylık)",
    "housing starts mom": "Konut Başlangıçları (Aylık)",
    "building permits mom": "İnşaat İzinleri (Aylık)",
    "net foreign exchange reserves": "Net Döviz Rezervleri",
    "foreign exchange reserves": "Döviz Rezervleri",
    "capacity utilization rate": "Kapasite Kullanım Oranı",
    "consumer confidence": "Tüketici Güveni",
    "economic confidence index": "Ekonomik Güven Endeksi",
    "real sector confidence": "Reel Kesim Güven Endeksi",
    "tourist arrivals yoy": "Turist Girişleri (Yıllık)",
    "unemployment rate": "İşsizlik Oranı",
    "new home sales": "Yeni Konut Satışları",
    "pending home sales mom": "Bekleyen Konut Satışları (Aylık)",
    "balance of trade": "Dış Ticaret Dengesi",
    "current account": "Cari İşlemler Dengesi",
    "philadelphia fed manufacturing index": "Philadelphia Fed İmalat Endeksi",
    "ny empire state manufacturing index": "NY Empire State İmalat Endeksi",
    "eia crude oil stocks change": "EIA Ham Petrol Stokları",
    "api crude oil stock change": "API Ham Petrol Stokları",
    "crude oil inventories": "Ham Petrol Stokları",
    "eia gasoline stocks change": "EIA Benzin Stokları",
    "eia natural gas stocks change": "EIA Doğalgaz Stokları",
    "mba mortgage applications": "MBA Konut Kredisi Başvuruları",
    "mba 30-year mortgage rate": "MBA 30 Yıllık Konut Kredisi Faizi",
    "monthly budget statement": "Aylık Bütçe Dengesi",
    "consumer credit change": "Tüketici Kredisi Değişimi",
    "nfib business optimism index": "NFIB Küçük İşletme İyimserlik Endeksi",
    "import prices mom": "İthalat Fiyatları (Aylık)",
    "export prices mom": "İhracat Fiyatları (Aylık)",
    "business inventories mom": "İşletme Stokları (Aylık)",
    "wholesale inventories mom": "Toptan Satış Stokları (Aylık)",
    "construction spending mom": "İnşaat Harcamaları (Aylık)",
    "case-shiller home price yoy": "Case-Shiller Konut Fiyatları (Yıllık)",
    "baker hughes oil rig count": "Baker Hughes Petrol Sondaj Sayısı",
    "capacity utilization": "Kapasite Kullanım Oranı",
    "manufacturing production mom": "İmalat Üretimi (Aylık)",
    "unit labour costs qoq": "Birim İşgücü Maliyetleri (Çeyreklik)",
    "nonfarm productivity qoq": "Tarım Dışı Verimlilik (Çeyreklik)",
    "employment cost index qoq": "İstihdam Maliyet Endeksi (Çeyreklik)",
    "challenger job cuts": "Challenger İşten Çıkarmalar",
    "total vehicle sales": "Toplam Araç Satışları",
    "redbook yoy": "Redbook Perakende Satışlar (Yıllık)",
    "mba purchase index": "MBA Konut Alım Endeksi",
    "mba mortgage refinance index": "MBA Konut Kredisi Yeniden Finansman Endeksi",
    "tcmb interest rate decision": "TCMB Faiz Kararı",
    "one week repo rate": "TCMB Politika Faizi (1 Hafta Repo)",
}

# Bilinmeyen adlar için kelime çevirisi
WORDS = [
    (r"\bMoM\b", "(Aylık)"), (r"\bYoY\b", "(Yıllık)"), (r"\bQoQ\b", "(Çeyreklik)"),
    (r"\bPrel\b", "(Öncü)"), (r"\bFinal\b", "(Nihai)"), (r"\bAdv\b", "(Öncü)"),
    (r"\b(\d+)-Year Note Auction\b", r"\1 Yıllık Tahvil İhalesi"),
    (r"\b(\d+)-Year Bond Auction\b", r"\1 Yıllık Tahvil İhalesi"),
    (r"\b(\d+)-Week Bill Auction\b", r"\1 Haftalık Bono İhalesi"),
    (r"\b(\d+)-Month Bill Auction\b", r"\1 Aylık Bono İhalesi"),
    (r"\bFed (\w+) Speech\b", r"Fed Üyesi \1 Konuşması"),
    (r"\bSpeech\b", "Konuşması"), (r"\bInflation Rate\b", "Enflasyon"), (r"\bInflation\b", "Enflasyon"),
    (r"\bUnemployment\b", "İşsizlik"), (r"\bEmployment\b", "İstihdam"), (r"\bInterest Rate\b", "Faiz"),
    (r"\bManufacturing\b", "İmalat"), (r"\bServices\b", "Hizmet"), (r"\bConsumer\b", "Tüketici"),
    (r"\bConfidence\b", "Güveni"), (r"\bSentiment\b", "Güveni"), (r"\bIndex\b", "Endeksi"),
    (r"\bSales\b", "Satışları"), (r"\bOrders\b", "Siparişleri"), (r"\bPrices\b", "Fiyatları"),
    (r"\bPrice\b", "Fiyat"), (r"\bProduction\b", "Üretimi"), (r"\bGrowth Rate\b", "Büyümesi"),
    (r"\bHome\b", "Konut"), (r"\bHousing\b", "Konut"), (r"\bBudget\b", "Bütçe"), (r"\bTrade\b", "Ticaret"),
    (r"\bBalance\b", "Dengesi"), (r"\bStocks\b", "Stokları"), (r"\bChange\b", "Değişimi"),
    (r"\bEarnings\b", "Kazanç"), (r"\bWages\b", "Ücretler"), (r"\bClaims\b", "Başvuruları"),
    (r"\bExisting\b", "Mevcut"), (r"\bForeign Exchange\b", "Döviz"), (r"\bNet\b", "Net"),
    (r"\bWholesale\b", "Toptan Satış"), (r"\bRetail\b", "Perakende"), (r"\bMortgage\b", "Konut Kredisi"),
    (r"\bCore\b", "Çekirdek"), (r"\bRate\b", "Oranı"), (r"\bDecision\b", "Kararı"),
    (r"\bMinutes\b", "Tutanakları"), (r"\bAuction\b", "İhalesi"), (r"\bOutlook\b", "Görünümü"),
    (r"\bSurvey\b", "Anketi"), (r"\bExpectations\b", "Beklentileri"), (r"\bSpending\b", "Harcaması"),
    (r"\bIncome\b", "Gelir"), (r"\bCrude Oil\b", "Ham Petrol"), (r"\bGasoline\b", "Benzin"),
    (r"\bNatural Gas\b", "Doğalgaz"), (r"\bInventories\b", "Stokları"), (r"\bPermits\b", "İzinleri"),
    (r"\bStarts\b", "Başlangıçları"), (r"\bIndustrial\b", "Sanayi"), (r"\bBusiness\b", "İş"),
    (r"\bOptimism\b", "İyimserlik"), (r"\bCurrent Account\b", "Cari Denge"), (r"\bExports\b", "İhracat"),
    (r"\bImports\b", "İthalat"), (r"\bReserves\b", "Rezervler"), (r"\bCapacity Utilization\b", "Kapasite Kullanımı"),
]

# Bu verilerde YÜKSEK değer ekonomi için olumsuz (işsizlik, enflasyon vb.)
HIGHER_IS_WORSE = re.compile(r"unemploy|jobless|claims|inflation|cpi|ppi|pce|price index|prices|job cuts|deficit|"
                             r"unit labo", re.IGNORECASE)
# Bu verilerde iyi/kötü yorumu yapılmaz (stoklar, ihaleler, konuşmalar, faiz kararları)
NO_VERDICT = re.compile(r"stock|inventor|auction|speech|minutes|press|decision|rig count|budget|projection",
                        re.IGNORECASE)


# Takvimi kalabalıklaştıran önemsiz kalemler (ihale alt satırları, yan stok verileri vb.)
NOISE = re.compile(r"allotted|bid-to-cover|total accepted|high yield|ethanol|cushing|distillate|refinery|"
                   r"heating oil|crude oil imports|exports change|imports change|redbook|"
                   r"\b(4|6|8|13|17|26|42|52)-week bill|money supply|fed balance sheet|"
                   r"reserve balances|treasury refunding", re.IGNORECASE)


def tr_title(title):
    t = (title or "").strip()
    key = re.sub(r"\s+", " ", t.lower())
    if key in TITLES:
        return TITLES[key]
    out = t
    for pat, rep in WORDS:
        out = re.sub(pat, rep, out)
    return out


def fetch_events(start_utc, end_utc, countries=("US",), timeout=20):
    frm = start_utc.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    to = end_utc.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    url = (f"https://economic-calendar.tradingview.com/events?from={frm}&to={to}"
           f"&countries={','.join(countries)}")
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Origin": "https://tr.tradingview.com",
                                               "Referer": "https://tr.tradingview.com/"})
    data = json.loads(urllib.request.urlopen(req, timeout=timeout).read())
    out = []
    for e in data.get("result", []):
        if NOISE.search(e.get("title", "")):
            continue
        try:
            dt = datetime.fromisoformat(e["date"].replace("Z", "+00:00"))
        except (KeyError, ValueError):
            continue
        out.append({"id": e.get("id"), "dt": dt, "title": e.get("title", ""), "tr": tr_title(e.get("title", "")),
                    "country": e.get("country", ""), "importance": e.get("importance", -1),
                    "actual": e.get("actual"), "forecast": e.get("forecast"), "previous": e.get("previous"),
                    "unit": e.get("unit") or "", "scale": e.get("scale") or ""})
    out.sort(key=lambda x: x["dt"])
    return out


def fmt_val(e, key):
    v = e.get(key)
    if v is None:
        return "–"
    if isinstance(v, (int, float)):
        s = f"{v:,.2f}".rstrip("0").rstrip(".") if abs(v) < 1000 else f"{v:,.0f}"
    else:
        s = str(v)
    return f"{s}{e['scale']}{e['unit']}"


def verdict(e):
    """Döner: (ikon, metin) – gerçekleşenin beklentiye göre ekonomi açısından yorumu."""
    a, f = e.get("actual"), e.get("forecast")
    if a is None or f is None or not isinstance(a, (int, float)) or not isinstance(f, (int, float)):
        return None
    if a == f:
        return "⚪", "Beklentiyle aynı"
    higher = a > f
    arrow = "▲ Beklentinin üstünde" if higher else "▼ Beklentinin altında"
    if NO_VERDICT.search(e["title"]):
        return "⚪", arrow
    good = (not higher) if HIGHER_IS_WORSE.search(e["title"]) else higher
    return ("🟢", arrow + " · ekonomi için olumlu") if good else ("🔴", arrow + " · ekonomi için olumsuz")


# --------------------------------------------------------------------------- #
# Kripto / altın / faiz etkisi (ABD verileri)
# --------------------------------------------------------------------------- #
# Yorum yapılmayan, yönü belirsiz veriler
NO_ANALYSIS = re.compile(r"stock|inventor|auction|speech|minutes|press|rig count|budget|balance|current account|"
                         r"projection|mortgage|refinance|purchase index", re.IGNORECASE)
RATE_DECISION = re.compile(r"interest rate decision|rate decision|fed funds", re.IGNORECASE)
INFLATION = re.compile(r"inflation|cpi|ppi|pce|price index|prices|earnings|wage|unit labo|employment cost",
                       re.IGNORECASE)
LABOR_WEAK = re.compile(r"unemploy|jobless|claims|job cuts", re.IGNORECASE)


def asset_impact(e):
    """ABD verisinin beklentiye göre sürprizini kripto, altın ve faiz indirimi açısından yorumlar.
    Döner: {"hawkish": bool, "reason": str, "items": [(ikon, metin), ...]} veya None."""
    if e.get("country") != "US":
        return None
    a, f, title = e.get("actual"), e.get("forecast"), e.get("title", "")
    if not isinstance(a, (int, float)) or not isinstance(f, (int, float)) or a == f:
        return None
    higher = a > f
    if RATE_DECISION.search(title):
        hawkish = higher
        reason = "Fed faizi beklentiden " + ("yüksek" if higher else "düşük")
    elif NO_ANALYSIS.search(title):
        return None
    elif INFLATION.search(title):
        hawkish = higher
        reason = "Enflasyon beklentiden " + ("yüksek" if higher else "düşük")
    elif LABOR_WEAK.search(title):
        hawkish = not higher
        reason = "İşgücü piyasası beklentiden " + ("zayıf" if higher else "güçlü")
    else:
        hawkish = higher
        reason = "Ekonomi beklentiden " + ("güçlü" if higher else "zayıf")
    if RATE_DECISION.search(title):
        reason += " → para politikası " + ("beklenenden sıkı" if hawkish else "beklenenden gevşek")
    else:
        reason += " → Fed'in faiz indirme ihtimali " + ("azalır" if hawkish else "artar")
    icon, word = ("🔴", "olumsuz") if hawkish else ("🟢", "olumlu")
    return {"hawkish": hawkish, "reason": reason,
            "items": [(icon, f"Kripto için {word}"), (icon, f"Altın için {word}"), (icon, f"Faiz indirimi için {word}")]}
