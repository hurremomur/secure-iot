/*
 * 04_kiyas.ino
 * -----------------------------------------------------------
 * Soğuk Zincir Projesi — TEKNİK KIYASI + CANLI YAYIN (tek firmware).
 *
 * Bu firmware, sunumun TAMAMINI tek karttan, tek komutla besler:
 *
 *   1) AÇILIŞTA (bir kez): gerçek DHT22 verisini okur, ŞİFRESİZ halini gösterir,
 *      DÖRT teknikle (Düz/AES-GCM/ChaCha20/Ascon) şifreleyip SÜRE + BOYUT + BELLEK
 *      ölçer, tabloyu yazar ve makine-okunur "KIYAS:[...]" satırını yayınlar.
 *      → Panodaki "ESP32 — TEKNİK KIYASI" çubuk grafiğini doldurur.
 *
 *   2) SONRA (sürekli): her ölçümü AES-128-GCM ile şifreleyip "PKT:<hex>" olarak
 *      canlı akıtır (nonce = kalıcı NVS sayacı; yeniden başlatmada tekrar etmez).
 *      → Panodaki canlı sıcaklık grafiğini + olay/özet panellerini doldurur.
 *      Kıyas satırı arada bir tekrarlanır ki pano geç açılsa da yakalasın.
 *
 * Böylece PC tarafı TEK akış:   python alici.py --seri COMx   →   python pano.py
 * (alici.py hem PKT: canlıyı DB'ye, hem KIYAS: kıyası panoya yazar.)
 *
 * Teknikler:
 *   - Düz Metin         : şifreleme yok (baz çizgi)
 *   - AES-128-GCM       : mbedTLS (ESP32'de donanım AES; GCM/GHASH yazılım)
 *   - ChaCha20-Poly1305 : chacha20poly1305.h (yazılım; ESP32 mbedTLS'inde derli gelmiyor)
 *   - Ascon-128         : ascon.h (yazılım, NIST hafif kripto standardı)
 *
 * Kütüphane: "DHT sensor library" (Adafruit). AES-GCM mbedTLS (dahili);
 * Ascon ve ChaCha20-Poly1305 yanlardaki .h dosyalarında (aynı klasörde olmalı);
 * Preferences (NVS) ESP32 çekirdeğinde dahili.
 * Kart: ESP32 Dev Module | Seri: 115200
 * Bağlantı: DHT22 VCC->3V3, GND->GND, DATA->D4 (GPIO 4).
 */

#include "DHT.h"
#include "mbedtls/gcm.h"
#include "esp_timer.h"
#include "ascon.h"
#include "chacha20poly1305.h"
#include <Preferences.h>

#define DHT_PIN 4
#define DHT_TIP DHT22
DHT dht(DHT_PIN, DHT_TIP);

const float SIC_MIN = 2.0, SIC_MAX = 8.0;
const int OLCUM_TEKRAR = 500;         // kıyasta her teknik bu kadar kez çalışıp ortalanır
const uint32_t CANLI_ARALIGI = 3000;  // ms (canlı yayında ölçüm aralığı)
const int KIYAS_TEKRAR_HER = 15;      // her N canlı pakette bir KIYAS: satırını tekrar yayınla

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

// --- Sayaç: KALICI (NVS). Canlı yayında nonce = sayaç; yeniden başlatmada tekrar etmez. ---
Preferences prefs;
const uint32_t SAYAC_BLOK = 10000;    // her açılışta bir blok rezerve et (flash yıpranmasın)
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

// Kıyas satırını açılışta bir kez kurar, canlı yayında tekrar yayınlamak için saklar.
char kiyasSatiri[320] = "";

void hexYaz(const uint8_t* v, size_t n) {
  for (size_t i = 0; i < n; i++) { if (v[i] < 0x10) Serial.print('0'); Serial.print(v[i], HEX); }
}

// DHT22'yi birkaç deneme ile oku (açılışta sensör geç ısınabilir).
bool sensorOku(float& sicaklik, float& nem) {
  for (int d = 0; d < 5; d++) {
    sicaklik = dht.readTemperature();
    nem      = dht.readHumidity();
    if (!isnan(sicaklik) && !isnan(nem)) return true;
    delay(600);
  }
  return false;
}

// ============ 1) AÇILIŞ KIYASI (bir kez) ============
void kiyasOlc() {
  float sicaklik, nem;
  if (!sensorOku(sicaklik, nem)) {
    Serial.println("DHT22 okunamadi (baglantiyi kontrol et). Kiyas atlandi.");
    return;
  }

  // Şifresiz paket (JSON — PC'deki paket.py ile aynı format). Sayaç 0: ölçüm nonce'ları yayınlanmaz.
  char veri[96];
  int mlen = snprintf(veri, sizeof(veri),
      "{\"t\":%.1f,\"h\":%.1f,\"k\":0,\"ts\":0,\"n\":0}", sicaklik, nem);

  bool bozuldu = (sicaklik < SIC_MIN || sicaklik > SIC_MAX);
  uint8_t nonce12[12] = {0}, nonce16[16] = {0};
  uint8_t ct[128], tag[16];

  // --- Düz Metin (baz çizgi) ---
  int64_t t0 = esp_timer_get_time();
  for (int i = 0; i < OLCUM_TEKRAR; i++) memcpy(ct, veri, mlen);
  float sure_duz = (esp_timer_get_time() - t0) / (float)OLCUM_TEKRAR;
  uint8_t duz_prev[16]; memcpy(duz_prev, ct, 16);

  // --- AES-128-GCM --- (anahtar BİR KEZ kurulur; döngüde yalnız şifreleme ölçülür)
  mbedtls_gcm_context g; mbedtls_gcm_init(&g);
  int64_t ks0 = esp_timer_get_time();
  mbedtls_gcm_setkey(&g, MBEDTLS_CIPHER_ID_AES, ANAHTAR16, 128);
  float sure_aes_kurulum = (float)(esp_timer_get_time() - ks0);
  t0 = esp_timer_get_time();
  for (int i = 0; i < OLCUM_TEKRAR; i++)
    mbedtls_gcm_crypt_and_tag(&g, MBEDTLS_GCM_ENCRYPT, mlen,
        nonce12, 12, AAD, sizeof(AAD), (const uint8_t*)veri, ct, 16, tag);
  float sure_aes = (esp_timer_get_time() - t0) / (float)OLCUM_TEKRAR;
  mbedtls_gcm_free(&g);
  uint8_t aes_prev[16]; memcpy(aes_prev, ct, 16);

  // --- ChaCha20-Poly1305 (kendi kütüphanemiz) ---
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

  // Yaz
  Serial.println("\n======== ACILIS KIYASI (DHT22, gercek veri) ========");
  Serial.printf("Her teknik %d kez calistirilip ortalamasi alinir.\n", OLCUM_TEKRAR);
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

  // Makine-okunur satır: alici.py yakalayıp panoya (cihaz_kiyas.json) aktarır.
  // Hem sakla (canlı yayında tekrar için) hem hemen yayınla.
  snprintf(kiyasSatiri, sizeof(kiyasSatiri),
    "KIYAS:[{\"ad\":\"Duz Metin\",\"aead\":false,\"sure_us\":%.2f,\"boyut\":%d},"
    "{\"ad\":\"AES-128-GCM\",\"aead\":true,\"sure_us\":%.2f,\"boyut\":%d},"
    "{\"ad\":\"ChaCha20-Poly1305\",\"aead\":true,\"sure_us\":%.2f,\"boyut\":%d},"
    "{\"ad\":\"Ascon-128\",\"aead\":true,\"sure_us\":%.2f,\"boyut\":%d}]",
    sure_duz, mlen, sure_aes, mlen + 16, sure_cha, mlen + 16, sure_asc, mlen + 16);
  Serial.println(kiyasSatiri);

  // --- Farklı veri boyutları (THROUGHPUT) ---
  static uint8_t buyuk[1024];
  static uint8_t ctb[1056], tagb[16];
  for (int i = 0; i < 1024; i++) buyuk[i] = (uint8_t)i;

  mbedtls_gcm_context g2; mbedtls_gcm_init(&g2);
  mbedtls_gcm_setkey(&g2, MBEDTLS_CIPHER_ID_AES, ANAHTAR16, 128);
  const int boyutlar[3] = {64, 256, 1024};
  Serial.println("\n--- Farkli veri boyutlari: sifreleme suresi (us) ---");
  Serial.println("Boyut    AES-GCM   ChaCha20   Ascon-128");
  for (int bi = 0; bi < 3; bi++) {
    int L = boyutlar[bi];
    int N = (L <= 64) ? 1000 : (L <= 256 ? 400 : 150);
    int64_t tt;
    tt = esp_timer_get_time();
    for (int i = 0; i < N; i++)
      mbedtls_gcm_crypt_and_tag(&g2, MBEDTLS_GCM_ENCRYPT, L, nonce12, 12, AAD, sizeof(AAD), buyuk, ctb, 16, tagb);
    float a = (esp_timer_get_time() - tt) / (float)N;
    tt = esp_timer_get_time();
    for (int i = 0; i < N; i++)
      chacha20poly1305_encrypt(ctb, tagb, buyuk, L, AAD, sizeof(AAD), nonce12, ANAHTAR32);
    float c = (esp_timer_get_time() - tt) / (float)N;
    tt = esp_timer_get_time();
    for (int i = 0; i < N; i++)
      ascon128_encrypt(ctb, tagb, buyuk, L, AAD, sizeof(AAD), nonce16, ANAHTAR16);
    float s = (esp_timer_get_time() - tt) / (float)N;
    Serial.printf("%4dB  %9.2f  %9.2f  %10.2f\n", L, a, c, s);
  }
  mbedtls_gcm_free(&g2);
  Serial.println("(Buyuk yukte donanim AES throughput avantaji ortaya cikar — literatur.)");

  // --- Bellek: bağlam/durum boyutu (RAM ayak izi) ---
  Serial.println("\n--- Bellek (baglam/durum boyutu, RAM) ---");
  Serial.printf("AES-128-GCM baglam : %d bayt (GHASH tablolari dahil)\n", (int)sizeof(mbedtls_gcm_context));
  Serial.printf("Ascon-128 durum    : %d bayt (5x64-bit, tablo yok)\n", (int)sizeof(ascon_state_t));
  Serial.println("ChaCha20 durum     : 64 bayt (16x32-bit) + Poly1305 (tablo yok)");
  Serial.println("Duz Metin          : 0 bayt (sifreleme yok)");
  Serial.println("(Hafif sifreler tablo tutmaz -> daha az RAM; Ascon/ChaCha bu yuzden kaynak-kisitli icin uygun.)");
}

// ============ 2) CANLI PAKET (AES-128-GCM) ============
// Bir ölçümü şifreleyip "PKT:<hex>" satırı üret. Boş string = sensör okunamadı.
String canliPaket() {
  float sicaklik, nem;
  if (!sensorOku(sicaklik, nem)) return "";

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
  mbedtls_gcm_setkey(&gcm, MBEDTLS_CIPHER_ID_AES, ANAHTAR16, 128);
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

void setup() {
  Serial.begin(115200);
  delay(1500);
  dht.begin();
  sayacYukle();
  kiyasOlc();   // 1) açılış kıyası — bir kez
  Serial.println("\n# Canli yayin basliyor (PKT: satirlari).");
  Serial.println("# PC: python alici.py --seri COMx   ->   python pano.py");
}

void loop() {
  static int sayici = 0;
  String pkt = canliPaket();
  if (pkt.length()) {
    Serial.println(pkt);                 // 2) canlı şifreli ölçüm
    sayici++;
    // Pano geç açılsa da kıyası yakalasın: arada bir KIYAS: satırını tekrar yayınla.
    if (kiyasSatiri[0] && (sayici % KIYAS_TEKRAR_HER == 0))
      Serial.println(kiyasSatiri);
  } else {
    Serial.println("# DHT22 okunamadi");
  }
  delay(CANLI_ARALIGI);
}
