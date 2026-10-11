/*
 * 01_aes_olcum.ino
 * -----------------------------------------------------------
 * Soğuk Zincir Projesi — ESP32 üzerinde İLK şifreleme + ölçüm.
 *
 * Ne yapar:
 *   - Sahte bir sensör verisi alır ("sicaklik=6.2;kapak=kapali").
 *   - Bu veriyi AES-128-GCM ile ESP32'nin KENDİSİNDE şifreler.
 *   - Şifreleme süresini (mikrosaniye) ölçer.
 *   - Sonucu USB/Seri porttan bilgisayara yazar.
 *
 * Neden önemli: Bu ölçüm artık PC'de değil, GERÇEK cihazda.
 * Sensör/lehim gerekmez — sadece ESP32'yi USB ile tak, yükle, Seri Ekranı aç.
 *
 * Kütüphane: mbedTLS (ESP32 Arduino çekirdeğinde HAZIR gelir, indirme yok).
 * Kart seçimi (Arduino IDE): "ESP32 Dev Module".
 * Seri hız: 115200.
 */

#include "mbedtls/gcm.h"   // AES-GCM (authenticated encryption) için
#include "esp_timer.h"     // mikrosaniye hassas zaman ölçümü için

// --- Sabitler ---
const uint8_t ANAHTAR[16] = {  // 128-bit gizli anahtar (şimdilik sabit; sonra ECDH)
  0x00,0x11,0x22,0x33, 0x44,0x55,0x66,0x77,
  0x88,0x99,0xAA,0xBB, 0xCC,0xDD,0xEE,0xFF
};
const uint8_t NONCE[12] = {    // her mesajda farklı olmalı; demoda sabit
  0x01,0x02,0x03,0x04, 0x05,0x06,0x07,0x08, 0x09,0x0A,0x0B,0x0C
};
const int OLCUM_TEKRAR = 1000; // ortalama için kaç kez çalıştıralım

// Baytları okunur onaltılık (hex) metne çeviren yardımcı
void hexYaz(const uint8_t* veri, size_t uzunluk) {
  for (size_t i = 0; i < uzunluk; i++) {
    if (veri[i] < 0x10) Serial.print('0');
    Serial.print(veri[i], HEX);
  }
  Serial.println();
}

void setup() {
  Serial.begin(115200);
  delay(1500);  // seri port otursun
  Serial.println("\n=== ESP32 AES-128-GCM Olcum ===");

  // 1) Sahte sensör verisi (sensör gelince burayi gercek okuma ile degistirecegiz)
  const char* duzMetin = "sicaklik=6.2;nem=57.5;kapak=kapali;sayac=47";
  size_t veriLen = strlen(duzMetin);
  Serial.print("Duz metin: ");
  Serial.println(duzMetin);
  Serial.print("Veri boyutu: ");
  Serial.print(veriLen);
  Serial.println(" bayt");

  // Çıktı tamponları
  uint8_t sifreli[128];
  uint8_t tag[16];      // GCM dogrulama etiketi (butunluk icin)

  // 2) Serbest bellegi olcum oncesi oku (RAM maliyeti icin)
  uint32_t ramOnce = esp_get_free_heap_size();

  // 3) ŞİFRELEME SÜRESİ ÖLÇÜMÜ — OLCUM_TEKRAR kez calistir, ortalama al
  int64_t t0 = esp_timer_get_time();   // baslangic (mikrosaniye)
  int ret = 0;
  for (int i = 0; i < OLCUM_TEKRAR; i++) {
    mbedtls_gcm_context gcm;
    mbedtls_gcm_init(&gcm);
    mbedtls_gcm_setkey(&gcm, MBEDTLS_CIPHER_ID_AES, ANAHTAR, 128);
    ret = mbedtls_gcm_crypt_and_tag(
      &gcm, MBEDTLS_GCM_ENCRYPT, veriLen,
      NONCE, sizeof(NONCE),
      NULL, 0,                       // ek iliskili veri (AAD) - simdilik yok
      (const uint8_t*)duzMetin, sifreli,
      sizeof(tag), tag);
    mbedtls_gcm_free(&gcm);
  }
  int64_t t1 = esp_timer_get_time();   // bitis

  uint32_t ramSonra = esp_get_free_heap_size();

  if (ret != 0) {
    Serial.print("HATA: sifreleme basarisiz, kod=");
    Serial.println(ret);
    return;
  }

  // 4) Sonuçları yaz
  float ortalamaUs = (float)(t1 - t0) / OLCUM_TEKRAR;

  Serial.print("Sifreli veri (hex): ");
  hexYaz(sifreli, veriLen);
  Serial.print("Dogrulama etiketi (tag): ");
  hexYaz(tag, sizeof(tag));

  Serial.println("\n--- OLCUM SONUCU ---");
  Serial.print("Teknik           : AES-128-GCM (authenticated)\n");
  Serial.print("Sifreleme suresi : ");
  Serial.print(ortalamaUs, 3);
  Serial.println(" mikrosaniye (ortalama)");
  Serial.print("Sifreli boyut    : ");
  Serial.print(veriLen + sizeof(tag));
  Serial.println(" bayt (veri + 16 bayt tag)");
  Serial.print("RAM kullanimi    : ~");
  Serial.print(ramOnce - ramSonra);
  Serial.println(" bayt (kaba)");
  Serial.println("--------------------");
}

void loop() {
  // Tek seferlik olcum; tekrar gormek icin karti RESET'leyin.
}
