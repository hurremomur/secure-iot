/*
 * 04_kiyas.ino
 * -----------------------------------------------------------
 * Soğuk Zincir Projesi — TEKNİK KIYASI (asıl araştırma bulgusu).
 *
 * Gerçek DHT22 verisini okur, ŞİFRESİZ halini gösterir, sonra DÖRT teknikle
 * şifreler ve her biri için SÜRE + BOYUT ölçüp tek tabloda karşılaştırır.
 * Bu, projenin kalbidir: "kaynağı kısıtlı cihazda hangi teknik daha uygun?"
 *
 * Teknikler:
 *   - Düz Metin         : şifreleme yok (baz çizgi)
 *   - AES-128-GCM       : mbedTLS (ESP32'de donanım hızlandırmalı)
 *   - ChaCha20-Poly1305 : chacha20poly1305.h (yazılım; ESP32 mbedTLS'inde derli gelmiyor)
 *   - Ascon-128         : ascon.h (yazılım, NIST hafif kripto standardı)
 *
 * NOT: AES, ESP32'de donanım AES motorunu kullanır; ChaCha20 ve Ascon
 * yazılımda çalışır. Kıyasın asıl anlamı budur (hoca makaleleriyle örtüşür).
 *
 * Kütüphane: "DHT sensor library" (Adafruit). AES-GCM mbedTLS (dahili);
 * Ascon ve ChaCha20-Poly1305 yanlardaki .h dosyalarında (aynı klasörde olmalı).
 * Kart: ESP32 Dev Module | Seri: 115200
 * Bağlantı: DHT22 VCC->3V3, GND->GND, DATA->D4 (GPIO 4).
 */

#include "DHT.h"
#include "mbedtls/gcm.h"
#include "esp_timer.h"
#include "ascon.h"
#include "chacha20poly1305.h"

#define DHT_PIN 4
#define DHT_TIP DHT22
DHT dht(DHT_PIN, DHT_TIP);

const float SIC_MIN = 2.0, SIC_MAX = 8.0;
const int OLCUM_TEKRAR = 500;   // her teknik bu kadar kez çalışıp ortalaması alınır

// Anahtarlar (demo). AES/Ascon 16 bayt; ChaCha20 32 bayt.
const uint8_t ANAHTAR16[16] = {
  0x00,0x11,0x22,0x33, 0x44,0x55,0x66,0x77,
  0x88,0x99,0xAA,0xBB, 0xCC,0xDD,0xEE,0xFF
};
const uint8_t ANAHTAR32[32] = {
  0x00,0x11,0x22,0x33, 0x44,0x55,0x66,0x77,
  0x88,0x99,0xAA,0xBB, 0xCC,0xDD,0xEE,0xFF,
  0x01,0x12,0x23,0x34, 0x45,0x56,0x67,0x78,
  0x89,0x9A,0xAB,0xBC, 0xCD,0xDE,0xEF,0xF0
};
const uint8_t AAD[8] = { 'c','i','h','a','z','-','0','1' };  // "cihaz-01"

uint32_t sayac = 0;

void hexYaz(const uint8_t* v, size_t n) {
  for (size_t i = 0; i < n; i++) { if (v[i] < 0x10) Serial.print('0'); Serial.print(v[i], HEX); }
}

void setup() {
  Serial.begin(115200);
  delay(1500);
  dht.begin();
  Serial.println("\n=== TEKNIK KIYASI (DHT22, gercek veri) ===");
  Serial.printf("Her teknik %d kez calistirilip ortalamasi alinir.\n", OLCUM_TEKRAR);
}

void loop() {
  float sicaklik = dht.readTemperature();
  float nem      = dht.readHumidity();
  if (isnan(sicaklik) || isnan(nem)) {
    Serial.println("DHT22 okunamadi (baglantiyi kontrol et).");
    delay(2000);
    return;
  }

  // 1) Şifresiz paket (JSON — PC'deki paket.py ile ayni format)
  sayac++;
  uint32_t ts = (uint32_t)(millis() / 1000);
  char veri[96];
  int mlen = snprintf(veri, sizeof(veri),
      "{\"t\":%.1f,\"h\":%.1f,\"k\":0,\"ts\":%lu,\"n\":%lu}",
      sicaklik, nem, (unsigned long)ts, (unsigned long)sayac);

  bool bozuldu = (sicaklik < SIC_MIN || sicaklik > SIC_MAX);

  // Nonce'lar (sayaçtan; her mesajda farklı)
  uint8_t nonce12[12] = {0}, nonce16[16] = {0};
  nonce12[0] = nonce16[0] = (sayac >> 24) & 0xFF;
  nonce12[1] = nonce16[1] = (sayac >> 16) & 0xFF;
  nonce12[2] = nonce16[2] = (sayac >> 8)  & 0xFF;
  nonce12[3] = nonce16[3] =  sayac        & 0xFF;

  uint8_t ct[128], tag[16];

  // --- Düz Metin (baz çizgi) ---
  int64_t t0 = esp_timer_get_time();
  for (int i = 0; i < OLCUM_TEKRAR; i++) memcpy(ct, veri, mlen);
  float sure_duz = (esp_timer_get_time() - t0) / (float)OLCUM_TEKRAR;
  uint8_t duz_prev[16]; memcpy(duz_prev, ct, 16);

  // --- AES-128-GCM ---
  // LİTERATÜR-STANDARDI ÖLÇÜM: anahtar BİR KEZ kurulur (setkey = pahalı, tek seferlik
  // GHASH tablo hesabı), döngüde yalnız ŞİFRELEME ölçülür. Gerçek kullanımda da anahtar
  // bir kez kurulur (sabit ya da ECDH oturum anahtarı), her mesajda değil.
  mbedtls_gcm_context g; mbedtls_gcm_init(&g);
  int64_t ks0 = esp_timer_get_time();
  mbedtls_gcm_setkey(&g, MBEDTLS_CIPHER_ID_AES, ANAHTAR16, 128);   // bir kez
  float sure_aes_kurulum = (float)(esp_timer_get_time() - ks0);    // tek seferlik maliyet
  t0 = esp_timer_get_time();
  for (int i = 0; i < OLCUM_TEKRAR; i++)
    mbedtls_gcm_crypt_and_tag(&g, MBEDTLS_GCM_ENCRYPT, mlen,
        nonce12, 12, AAD, sizeof(AAD), (const uint8_t*)veri, ct, 16, tag);
  float sure_aes = (esp_timer_get_time() - t0) / (float)OLCUM_TEKRAR;  // amortize edilmiş
  mbedtls_gcm_free(&g);
  uint8_t aes_prev[16]; memcpy(aes_prev, ct, 16);

  // --- ChaCha20-Poly1305 (kendi kütüphanemiz; ESP32 mbedTLS'inde derli yok) ---
  t0 = esp_timer_get_time();
  for (int i = 0; i < OLCUM_TEKRAR; i++)
    chacha20poly1305_encrypt(ct, tag, (const uint8_t*)veri, mlen, AAD, sizeof(AAD), nonce12, ANAHTAR32);
  float sure_cha = (esp_timer_get_time() - t0) / (float)OLCUM_TEKRAR;
  uint8_t cha_prev[16]; memcpy(cha_prev, ct, 16);

  // --- Ascon-128 ---
  t0 = esp_timer_get_time();
  for (int i = 0; i < OLCUM_TEKRAR; i++)
    ascon128_encrypt(ct, tag, (const uint8_t*)veri, mlen, AAD, sizeof(AAD), nonce16, ANAHTAR16);
  float sure_asc = (esp_timer_get_time() - t0) / (float)OLCUM_TEKRAR;
  uint8_t asc_prev[16]; memcpy(asc_prev, ct, 16);

  // 2) Yaz
  Serial.println("\n========================================");
  Serial.printf("Sicaklik: %.1f C | Nem: %%%.1f | Durum: %s\n",
                sicaklik, nem, bozuldu ? "!! SOGUK ZINCIR BOZULDU" : "OK (guvenli)");
  Serial.printf("Sifresiz (plaintext): %s   (%d bayt)\n", veri, mlen);
  Serial.println("----------------------------------------");
  Serial.println("Teknik             AEAD   Sure(us)  Boyut  Sifreli(ilk 12 bayt)");
  Serial.printf("Duz Metin          hayir  %7.2f   %3d    ", sure_duz, mlen);        hexYaz(duz_prev, 12); Serial.println();
  Serial.printf("AES-128-GCM        evet   %7.2f   %3d    ", sure_aes, mlen + 16);   hexYaz(aes_prev, 12); Serial.println();
  Serial.printf("ChaCha20-Poly1305  evet   %7.2f   %3d    ", sure_cha, mlen + 16);   hexYaz(cha_prev, 12); Serial.println();
  Serial.printf("Ascon-128          evet   %7.2f   %3d    ", sure_asc, mlen + 16);   hexYaz(asc_prev, 12); Serial.println();
  Serial.println("(Sure = anahtar BIR KEZ kurulduktan sonra bir mesaji sifreleme; literatur yontemi.)");
  Serial.printf("AES-128-GCM tek seferlik anahtar kurulumu (setkey): %.1f us (her mesajda DEGIL)\n",
                sure_aes_kurulum);
  Serial.println("(Boyut = veri + 16 bayt tag; Duz Metin'de tag yok)");

  // Makine-okunur satır (PC'de kiyas_oku.py yakalayıp panoya aktarır)
  Serial.printf("KIYAS:[{\"ad\":\"Duz Metin\",\"aead\":false,\"sure_us\":%.2f,\"boyut\":%d},", sure_duz, mlen);
  Serial.printf("{\"ad\":\"AES-128-GCM\",\"aead\":true,\"sure_us\":%.2f,\"boyut\":%d},", sure_aes, mlen + 16);
  Serial.printf("{\"ad\":\"ChaCha20-Poly1305\",\"aead\":true,\"sure_us\":%.2f,\"boyut\":%d},", sure_cha, mlen + 16);
  Serial.printf("{\"ad\":\"Ascon-128\",\"aead\":true,\"sure_us\":%.2f,\"boyut\":%d}]\n", sure_asc, mlen + 16);

  delay(4000);
}
