# SorBot – Binance USDT.P Sinyal Tarayıcısı

Binance vadelideki USDT.P kontratlarını (kripto + ABD hisseleri: NVDA, AMD …) **saatte bir** tarar,
16 indikatörden oluşan bir filtreden geçirir ve sadece **yüksek güven skorlu** long/short
sinyallerini Telegram'a gönderir.

- ❌ İşlem açmaz, borsa hesabına bağlanmaz, API anahtarı gerekmez.
- ⏱️ Zamanlama (`loop.yml` + `runner.py`): GitHub'ın zamanlayıcısı çok geciktiği için taramalar tek bir uzun çalıştırmada,
  mum kapanışından 1 dk sonra yapılır: 15dk taraması :01/:16/:31/:46'da, 1s taraması saat başında (:01).
  Döngü ~6 saatte bir kendini yeniden başlatır; durursa yedek zamanlayıcı 20 dk içinde tekrar başlatır.
  `config.json` değişiklikleri en geç 15 dk içinde geçerli olur. Repo public olduğu için Actions dakikaları sınırsız.
- 🔁 Commit koruması (`keepalive.yml`): ayda bir otomatik commit, böylece GitHub 60 gün kuralıyla zamanlanmış görevleri durdurmaz.
- 📦 Ek paket yok, sadece Python standart kütüphanesi.

> ⚠️ **Yatırım tavsiyesi değildir.** Sinyaller teknik göstergelere dayalıdır ve kazanç garantisi yoktur.
> Vadeli işlemlerde kaldıraç kayıpları da büyütür.

---

## Kurulum (tek seferlik)

### 1. Telegram botu
1. Telegram'da **@BotFather** → `/newbot` → isim verin → size verilen **token**'ı saklayın.
2. Sinyallerin geleceği yere botu ekleyin:
   - **Kendinize:** bota bir mesaj atın.
   - **Kanal/grup:** botu ekleyip yönetici yapın, kanala bir mesaj atın.
3. Tarayıcıda `https://api.telegram.org/bot<TOKEN>/getUpdates` adresini açıp `"chat":{"id": …}` değerini bulun.
   Kanal/grup ID'leri genelde `-100…` ile başlar.

### 2. GitHub Secrets
Repo → **Settings → Secrets and variables → Actions → New repository secret**

| Ad | Değer |
|---|---|
| `TELEGRAM_TOKEN` | BotFather'dan aldığınız token |
| `TELEGRAM_CHAT_ID` | Bulduğunuz chat ID |

> Token'ı asla koda, commit'e veya sohbete yazmayın. Sızarsa BotFather'da `/revoke` ile yenileyin.

### 3. Test
Repo → **Actions → SorBot Tarama → Run workflow**
- `test_telegram` kutusunu işaretleyip çalıştırın → Telegram'a "bağlantı testi başarılı" mesajı gelmeli.
- `dry_run` kutusu işaretliyken bot tarama yapar ama mesaj göndermez, sinyalleri log'a yazar.

Secret'lar eklenene kadar bot otomatik olarak deneme modunda çalışır (sadece log).

---

## Saatlik bülten (`report.py`, `econ.py`, `config.json → report`, mode: bulletin)

Her saat başı (1s taramasından hemen sonra) Telegram'a tek, düzenli bir **📰 Saatlik Piyasa Bülteni**:
- **🌍 Piyasalar:** borsalar (Dow, S&P 500, Nasdaq 100, BIST 100, Nikkei, DAX, FTSE, CAC, Hang Seng, Şanghay, KOSPI),
  metaller/emtia (spot altın, gram altın, gümüş, platin, paladyum, Brent, WTI, doğalgaz, bakır) ve döviz (DXY, USD/TRY, EUR/TRY);
  günlük değişim 🟢 yükseliş / 🔴 düşüş, piyasa Açık/Kapalı. Spot metal fiyatları Binance emtia endeksinden, diğerleri Yahoo Finance'ten.
- **📊 Açıklanan veriler (son 1 saat):** ABD ve Türkiye'nin orta/yüksek önemli verileri – gerçekleşen, beklenti,
  önceki ve 🟢/🔴 beklentiye göre ekonomi açısından yorum (TradingView ekonomik takvim, Türkçe veri adları).
  ABD verilerinde ayrıca 💡 sebep ve **kripto / altın / faiz indirimi** için 🟢 olumlu / 🔴 olumsuz etki:
  yüksek enflasyon veya güçlü ekonomi → Fed şahin → olumsuz; düşük enflasyon, zayıf ekonomi, yüksek işsizlik → olumlu.
- **🗓 Yaklaşan veriler (3 saat)**
- **💵 Ekonomi & Finans** ve **🪙 Kripto**: sadece önemli, Türkçe haberler (başlık + link)
Bölümlerin hepsi boşsa o saat bülten gönderilmez. Her sabah 09:00'dan sonraki ilk saat başında **🗓 Günün Ekonomik Takvimi**.

> Eski piyasa raporu bölümleri (BTC türev verileri, balina, ETF) `mode` değeri `bulletin` dışındayken çalışır.

Her taramadan sonra Telegram'a:

**📊 Saatlik Piyasa Raporu**
- **BTC:** fiyat, fonlama oranı (ve sonraki ödeme saati), açık pozisyon (1s / 24s değişim),
  long/short oranı (tüm hesaplar + büyük trader pozisyonları), son 1 saatte **vadeli** ve **spot** alış/satış hacmi
- **ABD piyasaları:** S&P 500, Nasdaq, Dow, Nasdaq vadeli, VIX, dolar endeksi, ABD 10Y faiz, altın, Brent ve WTI petrol (Yahoo Finance)
- **Spot ETF akışları:** sadece BTC ve ETH toplam net giriş/çıkış, son açıklanan gün + son 5 gün (Farside – veri günde bir güncellenir)
- **🐋 Balina hareketleri (BTC ve ETH):**
  - Zincir üstü büyük transferler (son çalıştırmadan beri yeni bloklar): BTC ≥ $10 mn (blockchain.info),
    ETH ≥ $5 mn (herkese açık Ethereum RPC; ERC-20/WETH dahil değil). Aynı coin'lerin zincirleme taşınması tek sayılır.
  - Binance vadeli ve spot emir defteri: fiyatın ±%0.5'i içindeki alış/satış likiditesi ve en büyük duvarlar
  - Not: transfer = alış/satış değildir; Binance kimin büyük işlem yaptığını herkese açık vermez.
- **Önümüzdeki 3 saatin** orta/yüksek önemli ekonomik verileri

**🏛 Büyük ETF akışı uyarısı** – BTC ETF'lerinde günlük net akış ≥ $100 mn veya ETH'de ≥ $50 mn olduğunda ayrı mesaj
(en büyük fon hareketleriyle; aynı gün için önemli güncelleme olmadıkça tekrar gönderilmez).

**📰 Son Haberler** – son çalıştırmadan beri yayınlanan **önemli** yeni başlıklar, sadece Türkçe kaynaklar (link ile). Her başlık piyasa etkisine göre puanlanır (Fed/faiz, enflasyon, istihdam, savaş/yaptırım, tarifeler, OPEC, ETF/SEC, rekor/çöküş…); `news_min_importance` altındakiler gönderilmez, en önemliler 🔥 ile işaretlenir:
- Ekonomi & Finans: Investing TR (ekonomi), Bloomberg HT, AA Ekonomi, Dünya – önemsiz şirket haberleri (analist notu, içeriden alım/satım, atama) elenir, kaynak başına en fazla 2 haber
- Kripto: Investing TR Kripto, BTCHaber
- Yapay Zeka: Webtekno, ShiftDelete, DonanımHaber, LOG, Teknoblog (sadece yapay zeka ile ilgili başlıklar)

**🗓 Günün Ekonomik Takvimi** – her sabah 09:00'dan sonraki ilk taramada (ForexFactory; USD, EUR, CNY, GBP, JPY,
orta/yüksek önem, beklenti ve önceki değerle). Not: bu kaynak açıklanan "gerçekleşen" değeri vermez.

## Aktif strateji: Supertrend + indikatör teyidi (`"strategy": "supertrend"`)

1. Her saat, kapanan 1 saatlik mumda **Supertrend AL'a veya SAT'a döndü mü** diye bakılır. Dönüş yoksa sinyal yoktur.
2. Dönüş varsa diğer indikatörlerin AL/SAT durumu oylanır:
   RSI (50 üstü/altı), StochRSI (K/D), MACD (sinyal çizgisi), Momentum, fiyatın EMA20/50/200 ve MA50/200'e göre konumu,
   ADX (+DI/−DI), OBV (ortalamasına göre), CCI (0), VWAP, Hacim (ortalama üstü hacimde mumun yönü),
   Bollinger (orta bandın üstü/altı), Ichimoku (bulutun üstü/altı, içindeyse nötr), CMF (20; 0 üstü para girişi),
   EWO (SMA5 − SMA35; 0 üstü/altı), WaveTrend (LazyBear 10/21; WT1 > WT2 AL), BTC/QQQ yönü.
3. **Teknik görünüm** (TradingView teknik özet mantığı): net = AL% − SAT%; ≥+50 🟢🟢 GÜÇLÜ AL, +30…+50 🟢 AL,
   −30…+30 ⚪ NÖTR, −50…−30 🔴 SAT, ≤−50 🔴🔴 GÜÇLÜ SAT (nötr gösterge yokken AL %65+ = AL, %75+ = GÜÇLÜ AL).
   **Güven skoru** = Supertrend ile aynı yöndeki indikatörlerin yüzdesi.
   **Trend uyumu:** trend tablosundaki 15dk/1s/4s/1g'nin hepsi sinyal yönündeyse "Bu işlem trend ile uyumlu",
   hepsi ters yöndeyse "Uyarı: Bu işlem trend ile uyumlu değil"; karışıksa satır yok. Ayrıca sinyalin kendi
   zaman dilimindeki trend: uyumlu / uyumlu değil / nötr (ikon trend tablosundaki gibi: 🟢 yükseliş, 🔴 düşüş, ⚪ nötr).
   "Bu işlem trend ile uyumlu" satırında ikon işlem yönündedir (LONG 🟢, SHORT 🔴); tüm "Uyarı: … uyumlu değil" satırları 🔴. **%90 ve üzeri** gönderilir (`signal_supertrend.min_score`).
4. BTC (kripto) / QQQ (hisse) güçlü ters yöndeyse sinyal gönderilmez. Aynı sembol + yön için 12 saat tekrar yok.
5. Stop 1.5 ATR, TP1/TP2/TP3 = 1R/2R/3R. Mesajda AL/SAT veren indikatörlerin listesi yer alır.
6. **RSI uyumsuzluğu** (bilgi): 15 dakika, 1 saat, 4 saat, 1 gün ve 1 hafta grafiklerinde TradingView mantığıyla (pivot 5/5, 5–60 mum)
   aranır; bulunursa 🟢 pozitif / 🔴 negatif olarak hangi zaman dilimlerinde olduğu yazılır.
7. **Hacim** (bilgi): 🔊 sinyal mumu hacmi 🟢 Yüksek / 🔴 Düşük (20 mum ortalamasına oran), son 3 mumda gövdesi
   1.5 ATR'yi aşan 📈 büyük yükseliş / 📉 büyük düşüş (yüzde ve hacim oranı), 💥 hacim patlaması (≥3x).
8. **Hacim profili** (şu an KAPALI, `volume_profile.enabled`): sinyalin kendi zaman diliminin grafiğinden (15dk sinyalde 15dk, 1s sinyalde 1s)
   🔴 VAH, 🟡 POC, 🟢 VAL seviyeleri ve girişe uzaklıkları (24 satır, %70 değer alanı, son 96 mum).

**BTC'den ayrışan coinler:** BTC güçlü ters yöndeyken bile, son 24 saatte BTC'den en az %5 ayrışan, dönüş mumunda hacmi
≥1.5x olan ve kendi 4s trendi ters olmayan semboller için sinyal gelir (mesajda "🚀 BTC'den ayrışıyor" notu, `decoupling`).

**Pump/Dump radarı (kripto + hisse, `pump_radar.types`):** Supertrend'den bağımsız ayrı mesajlar:
- 🚀/💥 **PUMP/DUMP BAŞLIYOR:** Bollinger sıkışmasından hacim patlamasıyla 20 mumluk direnç/destek kırılımı (giriş/TP/stop ile).
  Zaten %10 (3s) / %25 (24s) hareket etmiş coinler "geç kalınmış" sayılıp elenir.
- 👀 **ERKEN UYARI:** Sıkışmada birikim/dağıtım (OBV) + açık pozisyon (OI) ≥ %5 artış, henüz kırılım yok (izleme uyarısı).

**15 dakikalık Supertrend sinyalleri (`scan15.yml`, `tf_profiles.15m`):** Aynı strateji 15 dakikalık mumlarda çalışır;
üst zaman dilimi olarak 1 saatlik trend kullanılır. Aynı sembol+yön için 3 saat tekrar yok, taramada en fazla 5 mesaj,
Pump/Dump radarı sadece 1 saatlikte. Mesaj başlığında zaman dilimi `15m` olarak yazar.

Eski ağırlıklı puan stratejisine dönmek için `config.json`'da `"strategy": "score"` yazmanız yeterli.

## Nasıl çalışır? (genel akış ve "score" stratejisi)

1. Binance'ten tüm USDT.P kontratları, 24s hacim, fonlama oranları alınır.
2. Hisselerde sadece büyük şirketler taranır (`universe.equity_whitelist`, ~100 milyar $ üstü 61 şirket);
   günlük hacmi düşük semboller elenir (kripto < 5M USDT, hisse < 1M USDT).
3. Her sembol için son ~500 adet 1 saatlik mum çekilir; 4 saatlik trend bundan hesaplanır.
4. İndikatörler hesaplanır ve **long** ve **short** için ayrı **0–100 güven skoru** çıkarılır.
5. Sadece yeni bir **tetik** oluşmuşsa ve tüm filtreler geçilirse sinyal gönderilir.

### Güven skoru (100 puan)

| Bölüm | Puan | İçerik |
|---|---|---|
| Trend | 30 | Fiyat/EMA200, EMA20>EMA50>EMA200, MA50/MA200, Supertrend, 4s EMA ve Supertrend |
| Momentum | 25 | RSI, Stochastic RSI, MACD (histogram + yön), Momentum, CCI |
| Trend gücü | 10 | ADX ve +DI/−DI |
| Hacim | 15 | Hacim/ortalama, OBV eğilimi, VWAP üstü/altı |
| Piyasa yönü | 20 | Kripto için **BTC**, hisseler için **QQQ** trendi |

**Bonus / ceza:**
- 🚀/💥 Pump/dump analizi: Bollinger sıkışması + hacimli kırılım, sıkışmada birikim/dağıtım (OBV), açık pozisyon (OI) artışı
- ⚠️ Pump/dump sonrası geç kalma, aşırı uzama (EMA20'den 2 ATR+), RSI uç seviye, geç giriş
- ⚠️ Fonlama kalabalığı (long'lar/short'lar aşırı yığılmışsa)
- ⚠️ Hisselerde ABD borsası kapalıyken (seans dışı −5, hafta sonu −8)
- ✅ Birden fazla tetik birlikte oluşmuşsa +3, OI hareketi destekliyorsa +4

### Sinyal tetikleri
Supertrend dönüşü · MACD kesişimi · EMA20/EMA50 kesişimi · Hacimli direnç/destek kırılımı ·
Trend içi geri çekilme sonrası StochRSI dönüşü

### Sert filtreler (geçmeyen sinyal gönderilmez)
- Skor ≥ **80** ve karşı yön skorundan en az **25** puan yüksek
- 1 saatlik Supertrend sinyal yönünde, 4 saatlik trend ters değil
- BTC (kripto) / QQQ (hisse) güçlü şekilde ters yöndeyse sinyal yok
- Aynı sembol + yön için **12 saat** tekrar sinyal yok
- Saatte en fazla **5** detaylı mesaj (fazlası tek bir özet mesajında)

### Giriş / Stop / TP
- **Giriş:** son kapanan mumun kapanışı
- **Stop:** giriş ± 1.5 × ATR
- **TP1/TP2/TP3:** stop mesafesinin 1, 2, 3 katı (1R / 2R / 3R)

---

## Ayarlar – `config.json`

| Ayar | Açıklama |
|---|---|
| `universe.include_types` | `COIN`, `EQUITY`; isterseniz `COMMODITY`, `HK_EQUITY`, `KR_EQUITY`, `FX` |
| `universe.min_quote_volume_24h` | Türe göre minimum 24s hacim (USDT) |
| `signal.min_score` | Gönderilecek en düşük güven skoru |
| `signal.min_score_gap` | Long ve short skoru arasındaki minimum fark |
| `signal.cooldown_hours` | Aynı sinyalin tekrar gönderilmeyeceği süre |
| `signal.max_signals_per_run` | Bir taramadaki detaylı mesaj sayısı |
| `risk.sl_atr_mult` | Stop mesafesi (ATR katı) |
| `risk.tp_r_multiples` | TP seviyeleri (stop mesafesinin katları) |
| `indicators` | Tüm indikatör periyotları |

Değişikliği commit etmeniz yeterli, bir sonraki taramada geçerli olur.

## Dosyalar

| Dosya | İçerik |
|---|---|
| `scanner.py` | Ana tarayıcı: veri, skor, karar, Telegram |
| `indicators.py` | İndikatör hesaplamaları (TradingView formülleriyle uyumlu) |
| `config.json` | Ayarlar |
| `.github/workflows/scan.yml` | Saatlik GitHub Actions görevi |
| `tests/test_scanner.py` | Yerel testler: `python3 tests/test_scanner.py` |

## Notlar
- GitHub Actions sunucuları ABD'de; Binance'in resmi `fapi.binance.com` adresi oradan engelli.
  Bot veriyi `www.binance.com/fapi` üzerinden alır. Bu yol resmi olarak belgelenmemiştir;
  kapanırsa bot Telegram'dan uyarı gönderir.
- GitHub yoğunlukta zamanlanmış görevleri birkaç dakika geciktirebilir.
- Private repoda ücretsiz kota ayda 2000 dakikadır; bot ~720 dakika kullanır.
