# Cihaz Tarafı — ESP32 Firmware

ESP32 üzerinde çalışan C/Arduino kodları. Bu dosyalar bilgisayarda çalışmaz;
Arduino IDE ile derlenip USB üzerinden karta yüklenir.

## Firmware'ler

| Klasör | Ne yapar | Taşıma | Gereken kütüphane |
|--------|----------|--------|-------------------|
| `01_aes_olcum/` | Sahte veriyi AES-128-GCM ile şifreler, süresini ölçer (sensörsüz) | — | yok (mbedTLS dahili) |
| `02_dht_aes/`   | Gerçek DHT22 + AES-GCM + soğuk zincir uyarısı | Seri (ekran) | DHT sensor library (Adafruit) |
| `03_mqtt/`      | DHT22 + AES-GCM, brokere yayın | WiFi/MQTT | DHT + PubSubClient |
| `04_kiyas/`     | **4 tekniği cihazda kıyaslar** (Düz/AES/ChaCha20/Ascon) | Seri (ekran) | DHT (+ ascon.h, chacha20poly1305.h aynı klasörde) |
| `05_seri/`      | DHT22 + AES-GCM, PC'ye gönderim | USB/seri | DHT |
| `06_kaydet_aktar/` | **Portatif prototip**: ağ yokken flash'a biriktir, bağlanınca aktar | Bluetooth | DHT |

Önerilen sıra: `01` (kripto izole) → `02` (sensör) → `04` (kıyas = ana bulgu) →
`05` (canlı izleme, USB) → `06` (kaydet-sonra-aktar prototip, Bluetooth) → `03` (WiFi, uzaktan).

`06_kaydet_aktar` için: **Tools → Partition Scheme → "Huge APP"**
(Bluetooth + LittleFS yer kaplar).

Notlar:
- `04_kiyas/` içindeki `ascon.h` ve `chacha20poly1305.h`, `.ino` ile **aynı klasörde** olmalı.
- `alici.py --seri COMx` çalışırken Arduino Serial Monitor **kapalı** olmalı (port çakışır).

## Arduino IDE kurulumu

1. Arduino IDE: https://www.arduino.cc/en/software
2. ESP32 kart desteği — **File → Preferences → Additional boards manager URLs**:
   ```
   https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json
   ```
   Sonra **Boards Manager → "esp32" → Install**.
3. `02` için **Library Manager → "DHT sensor library" (Adafruit) → Install** (bağımlılıklarıyla).

## Yükleme

1. `.ino` dosyasını Arduino IDE'de aç (kendi klasörünün içinde olmalı).
2. ESP32'yi USB ile tak.
3. **Tools → Board → ESP32 Dev Module**, **Tools → Port → COMx**.
4. **Upload (→)**. "Done uploading" sonrası **Serial Monitor** (115200) aç.
   - Bağlanamazsa yükleme başlarken **BOOT** düğmesini basılı tut.
   - Port görünmezse CP2102 / CH340 USB sürücüsünü kur.

## Donanım bağlantısı (DHT22)

| DHT22 | ESP32 |
|-------|-------|
| VCC   | 3V3   |
| GND   | GND   |
| DATA  | GPIO 4 (kodda `DHT_PIN`) |

Lehim gerekmez; breadboard + jumper kablo yeterlidir. 3 pinli DHT22 modüllerinde
pull-up direnci dahilidir; 4 pinli sensörlerde DATA ile VCC arasına 10k direnç.
