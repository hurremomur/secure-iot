/*
 * 03_mqtt.ino
 * -----------------------------------------------------------
 * Soğuk Zincir Projesi — GERÇEK DHT22 verisini ESP32'de AES-128-GCM ile
 * şifreleyip WiFi üzerinden MQTT brokerine YAYINLAR.
 *
 * Akış:
 *   1) DHT22'den gerçek sıcaklık + nem oku.
 *   2) Veriyi JSON'a paketle  (PC'deki paket.py ile BİREBİR aynı format).
 *   3) AES-128-GCM ile şifrele (AAD = "cihaz-01").
 *   4) Hat formatını kur:  [nonce(12)] [şifreli veri] [tag(16)]
 *   5) MQTT ile konuya yayınla. Her 5 saniyede bir tekrar.
 *
 * PC tarafı:  python alici.py --mqtt --broker <bu PC'nin IP'si>
 * Sonra pano: python pano.py  ->  http://localhost:8000
 *
 * ÖNEMLİ — PC ile uyum için üç kural (yoksa paket REDDEDİLİR):
 *   a) JSON formatı paket.py ile aynı olmalı: {"t":..,"h":..,"k":..,"ts":..,"n":..}
 *   b) AAD "cihaz-01" olmalı (alici.py'deki ILISKILI ile aynı).
 *   c) Kullanılan nonce hat üzerinde GÖNDERİLİR; PC onu oradan okur.
 *      (Nonce'un her mesajda farklı olması yeter; sayaçtan türetiyoruz.)
 *
 * Kütüphaneler (Arduino Library Manager):
 *   - "DHT sensor library" (Adafruit) + "Adafruit Unified Sensor"
 *   - "PubSubClient" (Nick O'Leary)
 * mbedTLS ve WiFi, ESP32 çekirdeğinde zaten var.
 *
 * DONANIM: DHT22 VCC->3V3, GND->GND, DATA->GPIO 4.
 * Kart: "ESP32 Dev Module" | Seri: 115200
 */

#include <WiFi.h>
#include <PubSubClient.h>
#include "DHT.h"
#include "mbedtls/gcm.h"
#include <time.h>

// ====== AYARLAR (kendine göre doldur) ======
const char* WIFI_SSID = "WIFI_ADI";
const char* WIFI_PASS = "WIFI_SIFRESI";

const char* MQTT_BROKER = "192.168.1.50";   // broker'ın (alici.py'nin olduğu PC) IP'si
const int   MQTT_PORT   = 1883;             // TLS yok; şifreleme uygulama katmanında
const char* MQTT_KONU   = "soguk-zincir/cihaz-01/veri";
const char* MQTT_ID     = "cihaz-01";

// ====== KRİPTO SABİTLERİ (alici.py ile AYNI) ======
const uint8_t ANAHTAR[16] = {
  0x00,0x11,0x22,0x33, 0x44,0x55,0x66,0x77,
  0x88,0x99,0xAA,0xBB, 0xCC,0xDD,0xEE,0xFF
};
const uint8_t AAD[8] = { 'c','i','h','a','z','-','0','1' };   // "cihaz-01"

// ====== DHT22 ======
#define DHT_PIN 4
#define DHT_TIP DHT22
DHT dht(DHT_PIN, DHT_TIP);

// ====== MQTT istemcisi ======
WiFiClient wifi;
PubSubClient mqtt(wifi);

uint32_t sayac = 0;

// Sayaçtan 12 baytlık nonce türet (her mesajda farklı -> replay koruması).
// Düzeni önemli değil; aynı nonce hat üzerinde gönderildiği için PC onu okur.
void nonceUret(uint8_t* nonce, uint32_t s) {
  memset(nonce, 0, 12);
  nonce[0] = (s >> 24) & 0xFF;
  nonce[1] = (s >> 16) & 0xFF;
  nonce[2] = (s >> 8)  & 0xFF;
  nonce[3] =  s        & 0xFF;
}

void wifiBaglan() {
  Serial.printf("WiFi'ye bağlanılıyor: %s ", WIFI_SSID);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  while (WiFi.status() != WL_CONNECTED) { delay(500); Serial.print("."); }
  Serial.printf(" OK (IP: %s)\n", WiFi.localIP().toString().c_str());
  // Gerçek zaman damgası için NTP (ts alanı doğru olsun)
  configTime(0, 0, "pool.ntp.org", "time.nist.gov");
}

void mqttBaglan() {
  while (!mqtt.connected()) {
    Serial.print("MQTT brokerine bağlanılıyor... ");
    if (mqtt.connect(MQTT_ID)) {
      Serial.println("OK");
    } else {
      Serial.printf("hata rc=%d, 2 sn sonra tekrar\n", mqtt.state());
      delay(2000);
    }
  }
}

void setup() {
  Serial.begin(115200);
  delay(1500);
  dht.begin();
  wifiBaglan();
  mqtt.setServer(MQTT_BROKER, MQTT_PORT);
  Serial.println("\n=== DHT22 + AES-128-GCM + MQTT ===");
}

void loop() {
  if (!mqtt.connected()) mqttBaglan();
  mqtt.loop();

  // 1) Gerçek sensör okuması
  float sicaklik = dht.readTemperature();
  float nem      = dht.readHumidity();
  if (isnan(sicaklik) || isnan(nem)) {
    Serial.println("DHT22 okunamadı (bağlantıyı kontrol et).");
    delay(2000);
    return;
  }

  // 2) JSON paket (paket.py ile aynı format)
  sayac++;
  uint32_t ts = (uint32_t)time(nullptr);     // NTP sonrası epoch saniye
  char veri[80];
  int veriLen = snprintf(veri, sizeof(veri),
      "{\"t\":%.1f,\"h\":%.1f,\"k\":0,\"ts\":%lu,\"n\":%lu}",
      sicaklik, nem, (unsigned long)ts, (unsigned long)sayac);

  // 3) AES-128-GCM şifrele (AAD = "cihaz-01")
  uint8_t nonce[12];
  nonceUret(nonce, sayac);
  uint8_t sifreli[96];
  uint8_t tag[16];
  mbedtls_gcm_context gcm;
  mbedtls_gcm_init(&gcm);
  mbedtls_gcm_setkey(&gcm, MBEDTLS_CIPHER_ID_AES, ANAHTAR, 128);
  int ret = mbedtls_gcm_crypt_and_tag(
      &gcm, MBEDTLS_GCM_ENCRYPT, veriLen,
      nonce, sizeof(nonce),
      AAD, sizeof(AAD),                 // <-- AAD burada (02'de yoktu)
      (const uint8_t*)veri, sifreli, sizeof(tag), tag);
  mbedtls_gcm_free(&gcm);

  if (ret != 0) {
    Serial.printf("Şifreleme HATASI: %d\n", ret);
    delay(5000);
    return;
  }

  // 4) Hat formatı:  [nonce(12)] [şifreli veri] [tag(16)]
  //    (Python cryptography kütüphanesi tag'i şifreli verinin SONUNA ekler,
  //     o yüzden sırayı 'şifreli + tag' yapıyoruz.)
  uint8_t payload[12 + 96 + 16];
  int p = 0;
  memcpy(payload + p, nonce, 12);        p += 12;
  memcpy(payload + p, sifreli, veriLen); p += veriLen;
  memcpy(payload + p, tag, 16);          p += 16;

  // 5) MQTT yayınla
  bool ok = mqtt.publish(MQTT_KONU, payload, p);

  bool bozuldu = (sicaklik < 2.0 || sicaklik > 8.0);
  Serial.println("----------------------------------------");
  Serial.printf("Okuma : %s\n", veri);
  Serial.printf("Durum : %s\n", bozuldu ? "!! SOGUK ZINCIR BOZULDU" : "OK");
  Serial.printf("Yayin : %s (%d bayt, konu: %s)\n",
                ok ? "gonderildi" : "BASARISIZ", p, MQTT_KONU);

  delay(5000);  // 5 saniyede bir
}
