/*
 * 02_dht_aes.ino
 * -----------------------------------------------------------
 * Soğuk Zincir Projesi — GERÇEK DHT22 verisini ESP32'de şifrele + ölç.
 *
 * Akış:
 *   1) DHT22'den gerçek sıcaklık + nem oku.
 *   2) Veriyi bir metne paketle: "t=..;h=..;k=..;n=.."
 *   3) AES-128-GCM ile ESP32'de şifrele, süresini ölç.
 *   4) Soğuk zincir kontrolü: sıcaklık 2-8C dışındaysa UYARI.
 *   5) Hepsini USB/Seri'den yaz. Her 5 saniyede bir tekrar.
 *
 * ÖNCE 01_aes_olcum.ino'yu çalıştırmış olmalısın (kripto izole test).
 *
 * Kütüphane GEREKİR (Arduino Library Manager'dan kur):
 *   - "DHT sensor library" (Adafruit)
 *   - "Adafruit Unified Sensor"
 * mbedTLS ESP32 çekirdeğinde zaten var.
 *
 * DONANIM BAĞLANTISI (lehim yok, breadboard + jumper):
 *   DHT22 VCC  -> ESP32 3V3
 *   DHT22 GND  -> ESP32 GND
 *   DHT22 DATA -> ESP32 GPIO 4   (DATA ile VCC arasina 10k pull-up; 3 pinli modullerde dahili)
 *
 * Kart: "ESP32 Dev Module" | Seri: 115200
 */

#include "DHT.h"
#include "mbedtls/gcm.h"
#include "esp_timer.h"

// --- DHT22 ayarları ---
#define DHT_PIN   4         // DATA pininin bagli oldugu GPIO
#define DHT_TIP   DHT22
DHT dht(DHT_PIN, DHT_TIP);

// --- Soğuk zincir güvenli aralığı ---
const float SIC_MIN = 2.0;
const float SIC_MAX = 8.0;

// --- Kripto sabitleri ---
const uint8_t ANAHTAR[16] = {
  0x00,0x11,0x22,0x33, 0x44,0x55,0x66,0x77,
  0x88,0x99,0xAA,0xBB, 0xCC,0xDD,0xEE,0xFF
};
uint8_t nonce[12] = {0};     // her mesajda artan sayac ile degisecek (replay korumasi)
uint32_t sayac = 0;

void hexYaz(const uint8_t* v, size_t n) {
  for (size_t i = 0; i < n; i++) { if (v[i] < 0x10) Serial.print('0'); Serial.print(v[i], HEX); }
  Serial.println();
}

// Sayaci nonce'a gom (basit replay korumasi: her mesajda farkli nonce)
void nonceGuncelle() {
  sayac++;
  nonce[0] = (sayac >> 24) & 0xFF;
  nonce[1] = (sayac >> 16) & 0xFF;
  nonce[2] = (sayac >> 8)  & 0xFF;
  nonce[3] =  sayac        & 0xFF;
}

void setup() {
  Serial.begin(115200);
  delay(1500);
  dht.begin();
  Serial.println("\n=== DHT22 + AES-128-GCM (gercek veri) ===");
}

void loop() {
  // 1) Gerçek sensör okuması
  float sicaklik = dht.readTemperature();   // Celsius
  float nem      = dht.readHumidity();       // %

  if (isnan(sicaklik) || isnan(nem)) {
    Serial.println("DHT22 okunamadi (baglantiyi kontrol et).");
    delay(2000);
    return;
  }

  // 2) Veriyi metne paketle (kapak simdilik 0; sensor gelince gercek deger)
  nonceGuncelle();
  char veri[64];
  int veriLen = snprintf(veri, sizeof(veri), "t=%.1f;h=%.1f;k=0;n=%lu",
                         sicaklik, nem, (unsigned long)sayac);

  // 3) ESP32'de şifrele + süre ölç
  uint8_t sifreli[96];
  uint8_t tag[16];
  int64_t t0 = esp_timer_get_time();
  mbedtls_gcm_context gcm;
  mbedtls_gcm_init(&gcm);
  mbedtls_gcm_setkey(&gcm, MBEDTLS_CIPHER_ID_AES, ANAHTAR, 128);
  int ret = mbedtls_gcm_crypt_and_tag(
    &gcm, MBEDTLS_GCM_ENCRYPT, veriLen,
    nonce, sizeof(nonce), NULL, 0,
    (const uint8_t*)veri, sifreli, sizeof(tag), tag);
  mbedtls_gcm_free(&gcm);
  int64_t t1 = esp_timer_get_time();

  // 4) Soğuk zincir kontrolü
  bool bozuldu = (sicaklik < SIC_MIN || sicaklik > SIC_MAX);

  // 5) Yaz
  Serial.println("----------------------------------------");
  Serial.print("Okuma   : "); Serial.println(veri);
  Serial.print("Durum   : ");
  if (bozuldu) Serial.printf("!! SOGUK ZINCIR BOZULDU (%.1fC, guvenli %.0f-%.0fC)\n", sicaklik, SIC_MIN, SIC_MAX);
  else         Serial.printf("OK (%.1fC guvenli aralikta)\n", sicaklik);

  if (ret == 0) {
    Serial.print("Sifreli : "); hexYaz(sifreli, veriLen);
    Serial.print("Tag     : "); hexYaz(tag, sizeof(tag));
    Serial.printf("Sifre suresi: %lld us | Boyut: %d bayt (+16 tag)\n",
                  (long long)(t1 - t0), veriLen);
  } else {
    Serial.printf("Sifreleme HATASI: %d\n", ret);
  }

  delay(5000);  // 5 saniyede bir
}
