# Soğuk Zincir Güvenli İzleme Sistemi

Kaynağı kısıtlı bir IoT cihazı (ESP32) üzerinde soğuk zincir ürünlerinin sıcaklığını
**uçtan uca güvenli** biçimde izleyen ve farklı şifreleme tekniklerini kaynağı kısıtlı
cihaz üzerinde **karşılaştıran** bir bitirme projesi.

Veri uçtan uca şifrelenir (gizlilik), bütünlüğü doğrulanır (değiştirilen/sahte veri
reddedilir) ve soğuk zincir kırılırsa uyarı verilir. Aynı sistem üzerinde AES-128,
AES-128-GCM, ChaCha20-Poly1305 ve Ascon teknikleri hız, bellek ve boyut açısından ölçülür.

**Ekip:** Hürrem Ömür, Serdar Siyam
**Bölüm:** Trakya Üniversitesi, Bilgisayar Mühendisliği — Bitirme Projesi

**İş bölümü:** Hürrem — kriptografi ve yazılım (şifreleme teknikleri, cihazda teknik
kıyası, güvenli izleme/alıcı, pano, anahtar değişimi). Serdar — elektronik/donanım
(devre, sensör, powerbank ile portatif güç).

---

## 1. Problem ve amaç

Soğuk zincir gerektiren ürünler (ilaç, aşı, bazı gıdalar) belirli bir sıcaklık
aralığının (tipik olarak **2–8 °C**) dışına çıktığında bozulur; ancak bu durum çıplak
gözle anlaşılamaz. Mevcut basit sıcaklık kaydediciler veriyi çoğu zaman güvenlik önlemi
olmadan iletir. Bu da iki soruna yol açar:

- Veri **dinlenebilir** (gizlilik yok).
- Veri **sonradan değiştirilebilir**: bozulmuş bir ürünün sıcaklık kaydı "hep uygundu"
  diye sahtelenebilir (bütünlük yok).

Projenin amacı, sıcaklığı yalnızca ölçmek değil; kaydın **gizli, değiştirilemez ve
güvenilir** olmasını sağlamaktır. Ayrıca kaynağı kısıtlı bir cihazda farklı şifreleme
tekniklerinin güvenlik ile performans (hız/bellek/enerji) dengesini karşılaştırıp, bu tür
bir ürün için en uygun tekniği deneysel olarak belirlemektir.

---

## 2. Sistem mimarisi

```
   [ DHT22 sensörü ]
          │ sıcaklık, nem, kapak olayı
          ▼
   [ ESP32 (cihaz) ] --- oku → ŞİFRELE (AEAD) → ilet
          │ şifreli paket (nonce + şifreli veri + doğrulama etiketi)
          ▼ taşıma: Seri/USB · WiFi/MQTT · Bluetooth
   [ Bilgisayar (alıcı) ] --- al → ÇÖZ + DOĞRULA → soğuk zincir kontrol → kaydet → panoda göster
```

- **Cihaz (ESP32, C):** sensörü okur, veriyi şifreler, süresini/belleğini ölçer, iletir.
- **Alıcı (PC, Python):** veriyi çözer, bütünlüğünü doğrular, soğuk zincir durumunu
  belirler, SQLite'a kaydeder; reddedilen (sahte/manipüle) paketleri olay olarak işaretler.
- **Taşıma katmanı yalnız bayt taşır; şifreleme bunun üstündedir (uygulama katmanı).**
  Aynı şifreli paket Seri/USB, WiFi/MQTT veya Bluetooth üzerinden değişmeden gider;
  bilinçli olarak TLS kullanılmaz (payload zaten AEAD ile şifreli → uçtan uca; ayrıca
  teknikleri kıyaslayabilmek için).
- **Portatiflik:** cihaz powerbank'le beslenip Bluetooth (veya WiFi) ile veri gönderir;
  PC'ye kablo gerekmez.
- **Kaydet-sonra-aktar (planlı):** cihaz yolda (ağ yokken) ölçümleri şifreli belleğe yazar;
  varışta biriken paketleri topluca aktarır.

---

## 3. Güvenlik modeli

Her paket bir **AEAD** (Authenticated Encryption with Associated Data) tekniğiyle korunur:

| Güvenlik özelliği | Nasıl sağlanır | Soğuk zincirde anlamı |
|-------------------|----------------|------------------------|
| **Gizlilik** | Şifreleme | Veri dinlense bile okunamaz |
| **Bütünlük** | Doğrulama etiketi (tag) | Değiştirilen veri reddedilir → sahte "uygun" kaydı üretilemez |
| **Tazelik** | Artan sayaç (nonce) | Eski bir paket tekrar gönderilemez (replay koruması) |
| **Kaynak doğrulama** | İlişkili veri (AAD) + ortak anahtar | Yetkisiz cihaz geçerli paket üretemez |

**Alınan önlemler (doğruluk):**
- **Nonce tekrarı engellenir:** sayaç cihazda kalıcı (NVS) saklanır; yeniden başlatmada
  geri sarmaz, böylece aynı nonce + anahtar bir daha kullanılmaz (AES-GCM için kritik).
- **Zaman damgası:** cihazın gerçek saati olmayabileceğinden, kaydın zamanını alıcı (PC)
  "paketin alındığı an" olarak damgalar.

### Anahtar yönetimi

İki mod desteklenir:

- **Önceden paylaşılmış sabit anahtar** (varsayılan): aynı 16 baytlık anahtar iki tarafta
  da gömülüdür. Basit; prototip için yeterli ama güvenli saklama/yenileme sağlamaz.
- **ECDH anahtar değişimi (`--ecdh`):** taraflar **X25519** ile yalnızca açık anahtarlarını
  değiş tokuş edip ortak bir oturum anahtarını türetir; gizli anahtar hatta hiç gönderilmez,
  her oturumda taze anahtar üretilir (forward secrecy). Türetilen anahtar HKDF-SHA256 ile
  16 bayta indirgenir ve AES-128-GCM'de kullanılır. PC tarafında (`anahtar_degisimi.py`
  + `alici.py --mqtt --ecdh` + `cihaz_taklit.py --ecdh`) çalışır ve test edilmiştir;
  cihaz tarafına (mbedTLS X25519) taşınması planlıdır.

---

## 4. Karşılaştırılan şifreleme teknikleri

| Teknik | Tür | Doğrulamalı (AEAD) | Rol |
|--------|-----|:---:|-----|
| Düz Metin | — | Hayır | Baz çizgi (şifreleme maliyetini "sıfır"la kıyas) |
| AES-128-CTR | Simetrik | Hayır | "Yalnız gizlilik, bütünlük yok" örneği |
| AES-128-GCM | Simetrik AEAD | Evet | Klasik authenticated standart |
| ChaCha20-Poly1305 | Akış AEAD | Evet | Modern AEAD |
| Ascon-128 | Hafif AEAD | Evet | NIST hafif kriptografi standardı (2023) |

---

## 5. Klasör yapısı

```
soguk-zincir/
├── alici/                  # Bilgisayar tarafı (Python)
│   ├── kripto.py           # 5 şifreleme tekniği, ortak arayüz
│   ├── paket.py            # veri paketi + soğuk zincir mantığı
│   ├── alici.py            # alıcı: çöz + doğrula + kaydet (sim / seri / MQTT / ECDH)
│   ├── anahtar_degisimi.py # ECDH (X25519) ile oturum anahtarı türetme
│   ├── benchmark.py        # teknik karşılaştırması — PC referansı (süre/boyut)
│   ├── guvenlik_testi.py   # saldırı senaryoları (manipülasyon/replay)
│   ├── cihaz_taklit.py     # ESP32 öykünücüsü (MQTT, donanımsız demo/test; --ecdh)
│   ├── pano.py             # web panosu (canlı izleme + cihaz teknik kıyası grafiği)
│   ├── kiyas_oku.py        # 04_kiyas'ın cihaz ölçümünü panoya aktarır
│   ├── cihaz_kiyas.json    # cihazda ölçülen teknik kıyası (pano gösterir)
│   └── gereksinimler.txt   # Python bağımlılıkları
├── cihaz/                  # ESP32 tarafı (C / Arduino)
│   ├── 01_aes_olcum/       # cihazda AES ölçümü (sahte veri, sensörsüz test)
│   ├── 02_dht_aes/         # gerçek DHT22 verisi + AES + soğuk zincir uyarısı (seri)
│   ├── 03_mqtt/            # DHT22 + AES-GCM + WiFi/MQTT yayını
│   ├── 04_kiyas/           # TEKNİK KIYASI: 4 teknik cihazda (ascon.h + chacha20poly1305.h)
│   ├── 05_seri/            # DHT22 + AES-GCM, USB/seri ile gönderim (WiFi'siz)
│   └── 06_kaydet_aktar/    # PORTATİF PROTOTİP: Bluetooth + kaydet-sonra-aktar (flash tampon)
├── belgeler/
│   └── protokol.md         # paket formatı, güvenlik kuralları, taşıma katmanları
└── README.md
```

---

## 6. Kurulum ve çalıştırma (bilgisayar tarafı)

Gereken: Python 3.10+.

```bash
cd alici
python -m pip install -r gereksinimler.txt
```

Çalıştırma:

```bash
python alici.py            # alıcı (simülasyon modu — cihaz gerekmez)
python guvenlik_testi.py   # saldırı senaryoları (manipülasyon/replay)
python benchmark.py        # teknik karşılaştırması (süre/boyut)
```

- `alici.py` örnek paketleri işler, soğuk zincir ihlalini ve sahte paketi yakalar.
- `guvenlik_testi.py` AEAD tekniklerinin manipülasyonu reddettiğini gösterir.
- `benchmark.py` teknikleri karşılaştırır ve `benchmark_sonuc.json` üretir.

Canlı izleme panosu (tarayıcıda):

```bash
python alici.py     # önce veritabanını doldur (simülasyon veya cihaz verisi)
python pano.py      # sonra panoyu başlat -> http://localhost:8000
```

`pano.py`, `alici.py`'nin yazdığı `soguk_zincir.db`'yi okuyup güncel sıcaklığı,
soğuk zincir durumunu, sıcaklık-zaman grafiğini, son olayları ve (varsa)
teknik karşılaştırmasını her 2 saniyede bir canlı gösterir. Ek kütüphane gerekmez.

### MQTT ile uçtan uca (WiFi — gerçek IoT akışı)

Cihaz şifreli paketi bir MQTT brokerine yayınlar, alıcı dinler. Donanım yoksa
`cihaz_taklit.py` ESP32 yerine yayın yapar; tüm zincir donanımsız test edilir.

1. **Broker (Mosquitto) kur ve çalıştır:**
   - Windows: https://mosquitto.org/download → kur → `net start mosquitto`
     (ya da kurulum klasöründe `mosquitto -v`).
   - Linux: `sudo apt install mosquitto` → `mosquitto -v`
   - macOS: `brew install mosquitto` → `mosquitto`
   - Broker varsayılan **1883** portunda dinler.

2. **Alıcıyı MQTT modunda başlat** (broker ile aynı PC'de):
   ```bash
   python alici.py --mqtt
   python pano.py                 # ayrı terminalde
   ```

3. **Cihaz tarafı:**
   - Gerçek cihaz: `cihaz/03_mqtt` firmware'ini ESP32'ye yükle. İçindeki
     `WIFI_SSID`, `WIFI_PASS` ve `MQTT_BROKER` (PC'nin IP'si) alanlarını doldur.
   - Donanımsız demo: `python cihaz_taklit.py`
     (normal ölçümler + soğuk zincir kırılması + manipülasyon + replay yayınlar).

Akış: `cihaz → MQTT broker → alici.py --mqtt (çöz+doğrula+DB) → pano`.
Broker farklı makinedeyse: `python alici.py --mqtt --broker <broker-IP>`.
Demo için varsayılan halka açık broker (`broker.hivemq.com`) ayarlıdır (kurulum gerekmez).

> MQTT TLS'siz (1883) kullanılır; bu bilinçli bir tercihtir: gizlilik ve
> bütünlük payload'un kendisinde (AEAD) olduğundan koruma uçtan uçadır —
> broker bile veriyi göremez. Bu, farklı şifreleme tekniklerini karşılaştırmayı
> da mümkün kılar (TLS her şeyi örtseydi kıyas anlamsız olurdu).

### Seri (USB) ile — WiFi'siz

Cihaz `05_seri` (USB) veya `06_kaydet_aktar` (Bluetooth sanal COM portu) ile şifreli
paketi seri porttan gönderir; alıcı o porttan okur:

```bash
python alici.py --seri COM5     # COM5 = cihazın (USB ya da Bluetooth) portu
python pano.py                  # ayrı terminalde
```
Not: `alici.py --seri` çalışırken Arduino Serial Monitor KAPALI olmalı (port çakışır).

### ECDH anahtar değişimi ile (`--ecdh`)

Sabit anahtar yerine oturum anahtarı X25519 ile türetilir (MQTT üzerinden):

```bash
python alici.py --mqtt --ecdh          # Terminal 1
python cihaz_taklit.py --ecdh          # Terminal 2 (donanımsız demo)
python pano.py                         # Terminal 3
python anahtar_degisimi.py             # (tek başına: iki tarafın aynı anahtarı türettiğini gösterir)
```
İki tarafta da "ECDH tamam ✓ Oturum anahtarı: ..." aynı değeri yazar; sonra veri o anahtarla akar.

---

## 7. Cihaz tarafı (ESP32)

Arduino IDE ile `cihaz/` altındaki `.ino` dosyaları yüklenir. Kart: **ESP32 Dev Module**.
mbedTLS, ESP32 çekirdeğinde hazır gelir; sensörlü firmware'ler için "DHT sensor library"
(Adafruit), `03_mqtt` için "PubSubClient" (Nick O'Leary) gerekir.

| Firmware | Ne yapar | Taşıma |
|----------|----------|--------|
| `01_aes_olcum` | Kriptoyu izole test (sahte veri, sensörsüz) | — |
| `02_dht_aes` | Gerçek DHT22 + AES-GCM + soğuk zincir uyarısı | Seri (ekran) |
| `03_mqtt` | DHT22 + AES-GCM, brokere yayın | WiFi/MQTT |
| `04_kiyas` | **4 tekniği cihazda kıyaslar** (süre/boyut) | Seri (ekran) |
| `05_seri` | DHT22 + AES-GCM, PC'ye gönderim | USB/seri |
| `06_kaydet_aktar` | **Portatif prototip**: bağlantı yokken flash'a biriktirir, bağlanınca aktarır | Bluetooth |

Önerilen sıra: `01` (kripto) → `02` (sensör) → `04` (kıyas) → `05` (canlı izleme, USB) →
`06` (kaydet-sonra-aktar prototip, Bluetooth) → `03` (WiFi, uzaktan).

`04_kiyas` klasöründe `ascon.h` ve `chacha20poly1305.h` dosyaları `.ino` ile **aynı klasörde**
olmalı (bu iki tekniği mbedTLS vermediğinden kendimiz yazdık; Python referansıyla doğrulandı).
`06_kaydet_aktar` derlenmezse (Bluetooth+LittleFS yer kaplar): Tools → Partition Scheme → "Huge APP".

Donanım bağlantısı (DHT22): VCC→3V3, GND→GND, DATA→GPIO 4. Ayrıntılar dosya
başlarındaki açıklamalarda.

---

## 8. Durum ve yol haritası

- [x] Şifreleme çekirdeği (5 teknik, ortak arayüz)
- [x] Veri paketi + soğuk zincir mantığı
- [x] Alıcı uygulaması (çöz + doğrula + SQLite) — simülasyon / seri / MQTT
- [x] Güvenlik testi (manipülasyon + replay) — AEAD reddediyor
- [x] **Cihazda şifreleme + ölçüm (gerçek ESP32)** — AES-128-GCM
- [x] **Cihazda teknik karşılaştırması** (04_kiyas: Düz/AES/ChaCha20/Ascon, gerçek sensörle)
- [x] ChaCha20-Poly1305 ve Ascon-128'in cihaza entegrasyonu (kendi yazdık + doğrulandı)
- [x] Cihaz ↔ PC canlı izleme — seri (05_seri) ve MQTT (03_mqtt); panoda gerçek veri
- [x] İzleme panosu (canlı grafik + durum + olaylar + cihaz teknik kıyası grafiği)
- [x] **Anahtar değişimi (ECDH/X25519)** — PC tarafında çalışıyor ve test edildi
- [x] Nonce tekrarı önlemi (kalıcı sayaç) + zaman damgası (alıcı damgalar)
- [x] **Kaydet-sonra-aktar portatif prototipi** (06_kaydet_aktar) — Bluetooth; ağ yokken flash'a biriktir, bağlanınca aktar (PC tarafı test edildi; cihazda birlikte doğrulanacak). **Powerbank ile güç: Serdar (donanım).**
- [ ] ECDH'nin cihaza taşınması (mbedTLS X25519)
- [ ] Ara rapor sonrası: bütünleşik test ve nihai rapor

---

## 9. Teknik karşılaştırması — metodoloji ve beklenen sonuç

Karşılaştırma ESP32 üzerinde, gerçek sensör paketiyle yapılır (`04_kiyas`). Her teknik
için şifreleme süresi (µs) ve çıktı boyutu ölçülür.

**Ölçüm metodolojisi (literatür-standardı):** Şifreleme süresi, **anahtar bir kez
kurulduktan sonra** bir mesajı şifreleme maliyetidir. AES-GCM'de anahtar kurulumu
(`setkey`, GHASH tablolarının hesabı) pahalı ama **tek seferliktir**; gerçek kullanımda
anahtar (sabit ya da ECDH oturum anahtarı) bir kez kurulur, her mesajda değil. Bu yüzden
kurulum döngü dışında yapılır ve ayrıca raporlanır. (Anahtarı her mesajda yeniden kurmak
AES-GCM'i yapay olarak yavaş gösterir — ilk ölçümlerimizdeki sapmanın nedeni buydu.)

**Beklenen sonuç ve literatürle örtüşme:**
- **AES-128-GCM:** ESP32'nin donanım AES motoru sayesinde blok şifreleme hızlıdır;
  anahtar amortize edildiğinde küçük pakette rekabetçi/öndedir (donanımlı AES literatürü).
- **ChaCha20-Poly1305:** yazılımda verimlidir; donanım AES'i olmayan senaryolarda güçlüdür.
- **Ascon-128:** NIST hafif kripto standardı; özellikle **düşük bellek/kod boyutu ve
  enerji** açısından öne çıkar (hocanın makalelerindeki vurgu) — avantajı yalnız hız değil.

Boyut açısından tüm AEAD teknikleri eşittir: veri + 16 bayt doğrulama etiketi.

**Rapora eklenecek güçlendirmeler (bilimsellik):**
1. Anahtar amortize edilmiş ölçüm (yapıldı) + tek seferlik `setkey` maliyeti ayrıca.
2. Farklı veri boyutları (küçük paket vs büyük yük) — büyük yükte donanım AES'in verimi artar.
3. Donanım AES hızlandırmasının mbedTLS'te etkin olduğunun doğrulanması.
4. Bellek/kod boyutu karşılaştırması (Ascon'un asıl avantajı).

> Not: Sayısal tablo, düzeltilmiş `04_kiyas` cihazda çalıştırılıp `kiyas_oku.py` ile
> alındığında bu bölüme ve panoya işlenecektir. Metodoloji literatürle hizalı olduğundan
> sonucun da literatürle örtüşmesi beklenir.

---

## 10. Kaynaklar

1. G. Cagua, V. Gauthier-Umaña, C. Lozano-Garzón, "Implementation and Performance of
   Lightweight Authentication Encryption ASCON on IoT Devices," *IEEE Access*, vol. 13,
   pp. 16671–16682, 2025.
2. W. J. Buchanan, S. Li, R. Asif, "Lightweight cryptography methods," *Journal of Cyber
   Security Technology*, vol. 1, no. 3–4, pp. 187–201, 2017.
3. NIST, "Lightweight Cryptography Standardization: Ascon," 2023. https://ascon.iaik.tugraz.at
4. Mbed TLS Documentation. https://mbed-tls.readthedocs.io
5. Espressif Systems, ESP-IDF Programming Guide. https://docs.espressif.com
6. NIST, FIPS 197: Advanced Encryption Standard (AES), 2001.
7. Y. Nir, A. Langley, "ChaCha20 and Poly1305 for IETF Protocols," RFC 8439, 2018.
8. A. Langley, M. Hamburg, S. Turner, "Elliptic Curves for Security (X25519)," RFC 7748, 2016.
9. H. Krawczyk, P. Eronen, "HMAC-based Extract-and-Expand Key Derivation Function (HKDF)," RFC 5869, 2010.
