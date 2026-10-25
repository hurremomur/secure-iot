/*
 * 06_kaydet_aktar.ino
 * -----------------------------------------------------------
 * Soğuk Zincir Projesi — PORTATİF PROTOTİP + KAYDET-SONRA-AKTAR.
 *
 * Senaryo (gerçek soğuk zincir): cihaz kutuyla yolculuk eder. Yolda ağ/alıcı
 * yokken ölçümleri KAYBETMEZ; şifreli olarak kendi flash belleğine (LittleFS)
 * BİRİKTİRİR. Alıcı menzile girince (Bluetooth bağlanınca) biriken TÜM paketleri
 * aktarır, sonra canlı yayına geçer.
 *
 * Donanım: ESP32 + DHT22, powerbank/pil ile beslenir (USB kablosu gerekmez).
 * Taşıma: Bluetooth Classic SPP (PC'de sanal COM portu).
 * PC tarafı DEĞİŞMEZ:  python alici.py --seri COMx   →  python pano.py
 *
 * Çalışma:
 *   - Bağlı DEĞİLKEN : her ölçüm "/tampon.txt" dosyasına eklenir (birikir).
 *   - BağlI İKEN     : önce tampondaki birikmiş paketler boşaltılır (aktarılır),
 *                      sonra her yeni ölçüm canlı gönderilir.
 *
 * NOT (ÖNEMLİ): Bluetooth + LittleFS büyük yer kaplar →
 *   Arduino → Tools → Partition Scheme → "Huge APP (3MB No OTA/1MB SPIFFS)".
 *
 * Kütüphane: "DHT sensor library" (Adafruit). BluetoothSerial, LittleFS,
 * Preferences ve mbedTLS ESP32 çekirdeğinde dahilidir.
 * Kart: ESP32 Dev Module | DHT22 DATA->GPIO 4.
 */

#include "BluetoothSerial.h"
#include "DHT.h"
#include "mbedtls/gcm.h"
#include <LittleFS.h>
#include <Preferences.h>

#if !defined(CONFIG_BT_ENABLED) || !defined(CONFIG_BLUEDROID_ENABLED)
#error "Bluetooth kapalı. ESP32 Dev Module'de varsayılan açıktır."
#endif

BluetoothSerial SerialBT;

#define DHT_PIN 4
#define DHT_TIP DHT22
DHT dht(DHT_PIN, DHT_TIP);

const char* TAMPON = "/tampon.txt";     // flash'ta birikim dosyası
const uint32_t OLCUM_ARALIGI = 3000;    // ms (3 sn'de bir ölçüm)

const uint8_t ANAHTAR[16] = {
  0x00,0x11,0x22,0x33, 0x44,0x55,0x66,0x77,
  0x88,0x99,0xAA,0xBB, 0xCC,0xDD,0xEE,0xFF
};
const uint8_t AAD[8] = { 'c','i','h','a','z','-','0','1' };  // "cihaz-01"

// --- Sayaç: KALICI (NVS), yeniden başlatmada nonce tekrarını önler ---
Preferences prefs;
const uint32_t SAYAC_BLOK = 10000;
uint32_t sayac = 0, sayac_tavan = 0;

void sayacYukle() {
  prefs.begin("sz", false);
  sayac = prefs.getUInt("sayac", 0);
  sayac_tavan = sayac + SAYAC_BLOK;
  prefs.putUInt("sayac", sayac_tavan);
}
uint32_t sonrakiSayac() {
  sayac++;
  if (sayac >= sayac_tavan) { sayac_tavan = sayac + SAYAC_BLOK; prefs.putUInt("sayac", sayac_tavan); }
  return sayac;
}

// --- Bir ölçümü şifreleyip "PKT:<hex>" satırına çevir ---
String paketUret() {
  float sicaklik = dht.readTemperature();
  float nem      = dht.readHumidity();
  if (isnan(sicaklik) || isnan(nem)) return "";

  uint32_t n = sonrakiSayac();
  uint32_t ts = (uint32_t)(millis() / 1000);
  char veri[80];
  int mlen = snprintf(veri, sizeof(veri),
      "{\"t\":%.1f,\"h\":%.1f,\"k\":0,\"ts\":%lu,\"n\":%lu}",
      sicaklik, nem, (unsigned long)ts, (unsigned long)n);

  uint8_t nonce[12] = {0};
  nonce[0] = (n >> 24) & 0xFF; nonce[1] = (n >> 16) & 0xFF;
  nonce[2] = (n >> 8)  & 0xFF; nonce[3] =  n        & 0xFF;

  uint8_t sifreli[96], tag[16];
  mbedtls_gcm_context gcm; mbedtls_gcm_init(&gcm);
  mbedtls_gcm_setkey(&gcm, MBEDTLS_CIPHER_ID_AES, ANAHTAR, 128);
  int ret = mbedtls_gcm_crypt_and_tag(&gcm, MBEDTLS_GCM_ENCRYPT, mlen,
      nonce, 12, AAD, sizeof(AAD), (const uint8_t*)veri, sifreli, 16, tag);
  mbedtls_gcm_free(&gcm);
  if (ret != 0) return "";

  const char* H = "0123456789ABCDEF";
  String s = "PKT:";
  uint8_t* parts[3] = { nonce, sifreli, tag };
  int lens[3] = { 12, mlen, 16 };
  for (int p = 0; p < 3; p++)
    for (int i = 0; i < lens[p]; i++) { s += H[parts[p][i] >> 4]; s += H[parts[p][i] & 0xF]; }
  return s;
}

// --- Tampona ekle (bağlı değilken) ---
void tamponaEkle(const String& pkt) {
  File f = LittleFS.open(TAMPON, FILE_APPEND);
  if (!f) return;
  f.println(pkt);
  f.close();
}

// --- Tampondaki birikmiş paketleri aktar, sonra dosyayı sil ---
int tamponuBosalt() {
  if (!LittleFS.exists(TAMPON)) return 0;
  File f = LittleFS.open(TAMPON, FILE_READ);
  if (!f) return 0;
  int adet = 0;
  while (f.available()) {
    String satir = f.readStringUntil('\n');
    satir.trim();
    if (satir.length()) { SerialBT.println(satir); adet++; delay(20); }
  }
  f.close();
  SerialBT.flush();           // Bluetooth tamponunu gönder
  LittleFS.remove(TAMPON);    // aktarıldı → birikimi temizle
  return adet;
}

int tampondakiAdet() {
  if (!LittleFS.exists(TAMPON)) return 0;
  File f = LittleFS.open(TAMPON, FILE_READ);
  if (!f) return 0;
  int adet = 0;
  while (f.available()) { if (f.readStringUntil('\n').length()) adet++; }
  f.close();
  return adet;
}

bool oncekiBagli = false;

void setup() {
  Serial.begin(115200);
  delay(1000);
  dht.begin();
  sayacYukle();
  if (!LittleFS.begin(true)) Serial.println("# LittleFS baslatilamadi!");
  SerialBT.begin("SogukZincir");
  Serial.printf("# 06_kaydet_aktar hazir. Bluetooth: SogukZincir | Tamponda: %d kayit\n",
                tampondakiAdet());
}

void loop() {
  bool bagli = SerialBT.hasClient();

  // Bağlantı YENİ kurulduysa: önce birikmiş tamponu boşalt
  if (bagli && !oncekiBagli) {
    int aktarilan = tamponuBosalt();
    Serial.printf("# Baglandi → tampondan %d kayit aktarildi\n", aktarilan);
  }
  oncekiBagli = bagli;

  // Yeni ölçüm
  String pkt = paketUret();
  if (pkt.length()) {
    if (bagli) {
      SerialBT.println(pkt);                 // canlı gönder
      Serial.println("# canli gonderildi");
    } else {
      tamponaEkle(pkt);                      // biriktir
      Serial.printf("# baglanti yok → biriktirildi (tamponda %d)\n", tampondakiAdet());
    }
  }

  delay(OLCUM_ARALIGI);
}
