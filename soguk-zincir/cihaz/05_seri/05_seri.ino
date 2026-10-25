/*
 * 05_seri.ino
 * -----------------------------------------------------------
 * Soğuk Zincir Projesi — WiFi'SİZ canlı izleme (USB/seri üzerinden).
 *
 * Gerçek DHT22 verisini okur, AES-128-GCM ile şifreler ve şifreli paketi
 * USB/seri porttan PC'ye gönderir. WiFi/MQTT gerekmez — sadece USB kablosu.
 *
 * PC tarafı:  python alici.py --seri COM5   (sonra python pano.py)
 * ÖNEMLİ: alici.py seri portu kullanırken Arduino'daki Serial Monitor KAPALI
 * olmalı (port aynı anda tek programda açılabilir).
 *
 * Her ölçüm tek satır olarak gönderilir:
 *     PKT:<hex>      hex = [nonce(12)][şifreli veri][tag(16)]
 * (PC bu satırı çözer; PC ile uyum için JSON formatı paket.py ile aynıdır,
 *  AAD "cihaz-01"dir, nonce hat üzerinde gönderilir.)
 *
 * Kütüphane: "DHT sensor library" (Adafruit). mbedTLS dahili.
 * Kart: ESP32 Dev Module | Seri: 115200 | DHT22 DATA->GPIO 4.
 */

#include "DHT.h"
#include "mbedtls/gcm.h"
#include <Preferences.h>

#define DHT_PIN 4
#define DHT_TIP DHT22
DHT dht(DHT_PIN, DHT_TIP);

const uint8_t ANAHTAR[16] = {
  0x00,0x11,0x22,0x33, 0x44,0x55,0x66,0x77,
  0x88,0x99,0xAA,0xBB, 0xCC,0xDD,0xEE,0xFF
};
const uint8_t AAD[8] = { 'c','i','h','a','z','-','0','1' };  // "cihaz-01"

// Sayaç KALICI saklanır (NVS). Böylece cihaz yeniden başlasa bile sayaç geri
// sarmaz → aynı nonce + aynı anahtar bir daha kullanılmaz (AES-GCM nonce
// tekrarı, gizliliği/bütünlüğü çökertir). Her açılışta bir "blok" ayırırız:
// flash'a sürekli yazmadan (ömrü uzun) hem de tekrar garantisi olur.
Preferences prefs;
const uint32_t SAYAC_BLOK = 10000;
uint32_t sayac = 0;
uint32_t sayac_tavan = 0;

void sayacYukle() {
  prefs.begin("sz", false);
  sayac = prefs.getUInt("sayac", 0);     // en son ayrılan değer
  sayac_tavan = sayac + SAYAC_BLOK;
  prefs.putUInt("sayac", sayac_tavan);   // bu bloğu rezerve et (açılışta tekrar olmaz)
}
uint32_t sonrakiSayac() {
  sayac++;
  if (sayac >= sayac_tavan) {             // blok bitti → yeni blok ayır
    sayac_tavan = sayac + SAYAC_BLOK;
    prefs.putUInt("sayac", sayac_tavan);
  }
  return sayac;
}

void setup() {
  Serial.begin(115200);
  delay(1500);
  dht.begin();
  sayacYukle();
  Serial.printf("# 05_seri hazir (DHT22 + AES-128-GCM, seri). Sayac=%lu\n",
                (unsigned long)sayac);
}

void loop() {
  float sicaklik = dht.readTemperature();
  float nem      = dht.readHumidity();
  if (isnan(sicaklik) || isnan(nem)) {
    Serial.println("# DHT22 okunamadi");
    delay(2000);
    return;
  }

  // 1) JSON paket (paket.py ile aynı format)
  sayac = sonrakiSayac();               // kalıcı, geri sarmayan sayaç
  uint32_t ts = (uint32_t)(millis() / 1000);
  char veri[80];
  int mlen = snprintf(veri, sizeof(veri),
      "{\"t\":%.1f,\"h\":%.1f,\"k\":0,\"ts\":%lu,\"n\":%lu}",
      sicaklik, nem, (unsigned long)ts, (unsigned long)sayac);

  // 2) Nonce (sayaçtan; her mesajda farklı)
  uint8_t nonce[12] = {0};
  nonce[0] = (sayac >> 24) & 0xFF; nonce[1] = (sayac >> 16) & 0xFF;
  nonce[2] = (sayac >> 8)  & 0xFF; nonce[3] =  sayac        & 0xFF;

  // 3) AES-128-GCM şifrele (AAD = "cihaz-01")
  uint8_t sifreli[96], tag[16];
  mbedtls_gcm_context gcm;
  mbedtls_gcm_init(&gcm);
  mbedtls_gcm_setkey(&gcm, MBEDTLS_CIPHER_ID_AES, ANAHTAR, 128);
  int ret = mbedtls_gcm_crypt_and_tag(&gcm, MBEDTLS_GCM_ENCRYPT, mlen,
      nonce, sizeof(nonce), AAD, sizeof(AAD),
      (const uint8_t*)veri, sifreli, sizeof(tag), tag);
  mbedtls_gcm_free(&gcm);
  if (ret != 0) { Serial.printf("# sifreleme hatasi %d\n", ret); delay(2000); return; }

  // 4) Hat formatı [nonce][şifreli][tag] -> tek satır "PKT:<hex>"
  Serial.print("PKT:");
  for (int i = 0; i < 12;   i++) { if (nonce[i]   < 16) Serial.print('0'); Serial.print(nonce[i],   HEX); }
  for (int i = 0; i < mlen; i++) { if (sifreli[i] < 16) Serial.print('0'); Serial.print(sifreli[i], HEX); }
  for (int i = 0; i < 16;   i++) { if (tag[i]     < 16) Serial.print('0'); Serial.print(tag[i],     HEX); }
  Serial.println();

  delay(3000);  // 3 saniyede bir
}
