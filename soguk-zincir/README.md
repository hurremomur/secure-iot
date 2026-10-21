# Soğuk Zincir Güvenli İzleme Sistemi

Kaynağı kısıtlı bir IoT cihazı (ESP32) üzerinde soğuk zincir ürünlerinin sıcaklığını
**uçtan uca güvenli** biçimde izleyen ve farklı şifreleme tekniklerini kaynağı kısıtlı
cihaz üzerinde **karşılaştıran** bir bitirme projesi.

Veri uçtan uca şifrelenir (gizlilik), bütünlüğü doğrulanır (değiştirilen/sahte veri
reddedilir) ve soğuk zincir kırılırsa uyarı verilir. Aynı sistem üzerinde AES-128,
AES-128-GCM, ChaCha20-Poly1305 ve Ascon teknikleri hız, bellek ve boyut açısından ölçülür.

**Ekip:** Hürrem Ömür, Serdar Siyam
**Bölüm:** Trakya Üniversitesi, Bilgisayar Mühendisliği — Bitirme Projesi

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
   [ ESP32 (cihaz) ] --- oku → ŞİFRELE (AEAD) → yerel kayıt / ilet
          │ şifreli paket (nonce + şifreli veri + doğrulama etiketi)
          ▼ (Wi-Fi / Seri)
   [ Bilgisayar (alıcı) ] --- al → ÇÖZ + DOĞRULA → soğuk zincir kontrol → kaydet/göster
```

- **Cihaz (ESP32, C):** sensörü okur, veriyi şifreler, süresini/belleğini ölçer, iletir.
- **Alıcı (PC, Python):** veriyi çözer, bütünlüğünü doğrular, soğuk zincir durumunu
  belirler, SQLite'a kaydeder; reddedilen (sahte/manipüle) paketleri olay olarak işaretler.
- **Taşıma modeli — kaydet-sonra-aktar:** cihaz yolda (Wi-Fi yokken) ölçümleri şifreli
  olarak belleğe yazar; varışta (hedef ağ menzile girince) biriken paketleri topluca aktarır.

---

## 3. Güvenlik modeli

Her paket bir **AEAD** (Authenticated Encryption with Associated Data) tekniğiyle korunur:

| Güvenlik özelliği | Nasıl sağlanır | Soğuk zincirde anlamı |
|-------------------|----------------|------------------------|
| **Gizlilik** | Şifreleme | Veri dinlense bile okunamaz |
| **Bütünlük** | Doğrulama etiketi (tag) | Değiştirilen veri reddedilir → sahte "uygun" kaydı üretilemez |
| **Tazelik** | Artan sayaç (nonce) | Eski bir paket tekrar gönderilemez (replay koruması) |
| **Kaynak doğrulama** | İlişkili veri (AAD) + ortak anahtar | Yetkisiz cihaz geçerli paket üretemez |

Anahtar başlangıçta önceden paylaşılmış sabit anahtardır; ileri aşamada cihazlar arası
güvenli anahtar değişimi (ECDH) değerlendirilecektir.

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
│   ├── alici.py            # alıcı: çöz + doğrula + kaydet (SQLite)
│   ├── benchmark.py        # teknik karşılaştırması (süre/boyut)
│   ├── guvenlik_testi.py   # saldırı senaryoları (manipülasyon/replay)
│   ├── cihaz_taklit.py     # MQTT yayıncı (ESP32 öykünücüsü, donanımsız demo/test)
│   ├── pano.py             # web panosu (canlı izleme: sıcaklık/durum/olaylar)
│   └── gereksinimler.txt   # Python bağımlılıkları
├── cihaz/                  # ESP32 tarafı (C / Arduino)
│   ├── 01_aes_olcum/       # cihazda AES ölçümü (sahte veri, sensörsüz test)
│   ├── 02_dht_aes/         # gerçek DHT22 verisi + AES + soğuk zincir uyarısı (seri)
│   └── 03_mqtt/            # DHT22 + AES-GCM + WiFi/MQTT yayını (PC ile uçtan uca)
├── belgeler/
│   └── protokol.md         # paket formatı ve güvenlik kuralları
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

> MQTT TLS'siz (1883) kullanılır; bu bilinçli bir tercihtir: gizlilik ve
> bütünlük payload'un kendisinde (AEAD) olduğundan koruma uçtan uçadır —
> broker bile veriyi göremez. Bu, farklı şifreleme tekniklerini karşılaştırmayı
> da mümkün kılar (TLS her şeyi örtseydi kıyas anlamsız olurdu).

Cihaz bağlıyken alıcıyı seri modda çalıştırmak için (ileride):
`python alici.py --seri COM3`

---

## 7. Cihaz tarafı (ESP32)

Arduino IDE ile `cihaz/` altındaki `.ino` dosyaları yüklenir. mbedTLS, ESP32
çekirdeğinde hazır gelir; `02_dht_aes` için "DHT sensor library" (Adafruit) gerekir.

1. **`01_aes_olcum`** — kriptoyu izole test eder (sahte veri, sensör gerekmez).
2. **`02_dht_aes`** — gerçek DHT22 verisini okur, şifreler, soğuk zincir uyarısı verir.

Donanım bağlantısı (DHT22): VCC→3V3, GND→GND, DATA→GPIO 4. Ayrıntılar dosya
başlarındaki açıklamalarda.

---

## 8. Durum ve yol haritası

- [x] Şifreleme çekirdeği (5 teknik, ortak arayüz)
- [x] Veri paketi + soğuk zincir mantığı
- [x] Alıcı uygulaması (çöz + doğrula + SQLite)
- [x] Güvenlik testi (manipülasyon + replay)
- [x] Karşılaştırma (PC referansı)
- [x] Cihaz ↔ PC bağlantısı — MQTT taşıma katmanı (alici.py --mqtt + 03_mqtt firmware)
- [x] Uçtan uca zincir testi (cihaz taklidi → broker → alıcı → pano) + canlı saldırı reddi
- [x] İzleme panosu (canlı grafik + durum + olaylar + teknik karşılaştırması)
- [ ] Cihazda şifreleme + ölçüm (ESP32 gerçek donanım — yarın)
- [ ] Cihazda teknik karşılaştırması (donanım AES / yazılım AES / Ascon)
- [ ] Kaydet-sonra-aktar (yolda biriktir, varışta topluca yayınla)
- [ ] Bütünleşik test, demo ve rapor

---

## 9. Not — ölçüm neden cihazda yapılır

Bilgisayardaki ölçümler teknikleri göreli sıralamak içindir. PC'de AES donanım
hızlandırmalı (AES-NI) olduğundan sonuç yanıltıcıdır; ESP32'de AES-NI yoktur ve tablo
değişebilir. Bu yüzden asıl performans ölçümü kaynağı kısıtlı cihazda yapılır —
projenin bulgusu bu farktan çıkar.

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
