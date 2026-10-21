"""
alici.py — Alıcı uygulaması (çöz + doğrula + soğuk zincir + kayıt)
==================================================================
Cihazdan gelen şifreli paketleri alır, çözer, bütünlüğünü doğrular,
soğuk zincir durumunu belirler ve SQLite'a kaydeder.

Üç çalışma modu:
    - Simülasyon (varsayılan): cihaz yokken test için sahte şifreli paket üretir.
      Hemen çalışır, donanım gerekmez.
          python alici.py
    - MQTT (önerilen, WiFi ile canlı): cihaz paketi brokere yayınlar, alıcı dinler.
          python alici.py --mqtt
          python alici.py --mqtt --broker 192.168.1.50 --konu soguk-zincir/cihaz-01/veri
      (paho-mqtt gerekir: python -m pip install paho-mqtt)
    - Seri (cihaz USB ile bağlıyken): ESP32'den seri üzerinden paket okur.
          python alici.py --seri COM3
      (pyserial gerekir: python -m pip install pyserial)

Taşıma katmanı (MQTT/seri) yalnız bayt taşır; şifreleme bunun ÜSTÜNDE,
uygulama katmanındadır. Brokere giden payload zaten şifrelidir ([nonce][şifreli
veri][tag]) — broker bile veriyi göremez (uçtan uca).

Şifreleme tekniği buradan seçilir (cihazla AYNI olmalı):
    SECILEN_TEKNIK = "AES-128-GCM"
"""

import os
import sys
import time
import sqlite3

from kripto import TEKNIK_HARITA, DogrulamaHatasi
from paket import paket_olustur, paket_coz, nonce_uret, soguk_zincir_durumu

# --- Ayarlar (cihaz ile aynı olmalı) ---
SECILEN_TEKNIK = "AES-128-GCM"
# Önceden paylaşılmış sabit anahtar (demo). Gerçekte güvenli saklanır / ECDH ile üretilir.
ANAHTAR = bytes.fromhex("00112233445566778899aabbccddeeff")
ILISKILI = b"cihaz-01"
VERITABANI = "soguk_zincir.db"

# MQTT ayarları (cihazla aynı broker/konu olmalı)
MQTT_BROKER = "localhost"          # broker IP/adı (cihazın bağlandığı PC'nin IP'si)
MQTT_PORT = 1883                   # TLS yok; şifreleme zaten uygulama katmanında
MQTT_KONU = "soguk-zincir/cihaz-01/veri"


def veritabani_hazirla():
    db = sqlite3.connect(VERITABANI)
    db.execute("""CREATE TABLE IF NOT EXISTS olcumler(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        zaman INTEGER, sicaklik REAL, nem REAL, kapak INTEGER,
        sayac INTEGER, durum TEXT)""")
    db.execute("""CREATE TABLE IF NOT EXISTS olaylar(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        zaman INTEGER, tur TEXT, aciklama TEXT)""")
    db.commit()
    return db


def paket_isle(db, teknik, nonce, blob, gorulen_sayaclar):
    """Bir şifreli paketi çöz + doğrula + kaydet. Sonucu ekrana yazar."""
    # 1) Çöz + bütünlük doğrula
    try:
        ham = teknik.coz(ANAHTAR, nonce, blob, ILISKILI)
    except DogrulamaHatasi:
        print("  [RED] Paket reddedildi: bütünlük doğrulanamadı (sahte/bozuk).")
        db.execute("INSERT INTO olaylar(zaman,tur,aciklama) VALUES(?,?,?)",
                   (int(time.time()), "manipulasyon", "Doğrulama başarısız"))
        db.commit()
        return

    kayit = paket_coz(ham)

    # 2) Replay kontrolü (sayaç)
    if kayit["n"] in gorulen_sayaclar:
        print(f"  [RED] Replay: n={kayit['n']} daha önce görüldü.")
        db.execute("INSERT INTO olaylar(zaman,tur,aciklama) VALUES(?,?,?)",
                   (int(time.time()), "replay", f"Tekrar eden sayaç {kayit['n']}"))
        db.commit()
        return
    gorulen_sayaclar.add(kayit["n"])

    # 3) Soğuk zincir durumu
    durum, aciklama = soguk_zincir_durumu(kayit)
    isaret = {"OK": "OK ", "UYARI": "!! ", "BOZULDU": "XX "}.get(durum, "")
    print(f"  {isaret}n={kayit['n']} {kayit['t']}°C %{kayit['h']} kapak={kayit['k']} -> {durum}: {aciklama}")

    # 4) Kaydet
    db.execute("INSERT INTO olcumler(zaman,sicaklik,nem,kapak,sayac,durum) VALUES(?,?,?,?,?,?)",
               (kayit["ts"], kayit["t"], kayit["h"], kayit["k"], kayit["n"], durum))
    if durum != "OK":
        db.execute("INSERT INTO olaylar(zaman,tur,aciklama) VALUES(?,?,?)",
                   (kayit["ts"], durum.lower(), aciklama))
    db.commit()


def simulasyon(db, teknik):
    """Cihaz yokken: sahte şifreli paketler üret ve alıcıyı test et."""
    print("SİMÜLASYON modu (cihaz yok). Örnek paketler işleniyor:\n")
    gorulen = set()
    ornekler = [
        (6.2, 57.5, False, 1),   # güvenli
        (7.4, 58.0, False, 2),   # güvenli
        (11.3, 60.0, True, 3),   # bozulmuş
    ]
    for sic, nem, kapak, sayac in ornekler:
        veri = paket_olustur(sic, nem, kapak, sayac)
        nonce = nonce_uret(sayac, teknik.nonce_uzunlugu)
        blob = teknik.sifrele(ANAHTAR, nonce, veri, ILISKILI)
        paket_isle(db, teknik, nonce, blob, gorulen)
        time.sleep(0.3)

    # Bir de saldırı: manipüle edilmiş paket
    print("\nSaldırı denemesi (bir bayt değiştirilmiş paket):")
    veri = paket_olustur(5.0, 55.0, False, 4)
    nonce = nonce_uret(4, teknik.nonce_uzunlugu)
    blob = bytearray(teknik.sifrele(ANAHTAR, nonce, veri, ILISKILI))
    if blob:
        blob[len(blob)//2] ^= 0x01
    paket_isle(db, teknik, nonce, bytes(blob), gorulen)


def wire_ayikla(teknik, payload):
    """Hattan gelen ham baytı protokole göre ayır: [nonce][şifreli veri][tag].
    Döndürür: (nonce, blob) — blob = şifreli veri + tag."""
    n = teknik.nonce_uzunlugu
    if len(payload) < n:
        return None, None
    return payload[:n], payload[n:]


def mqtt_dinle(db, teknik, broker, port, konu):
    """MQTT brokerine abone ol; gelen her şifreli paketi çöz + doğrula + kaydet."""
    try:
        import paho.mqtt.client as mqtt
    except ImportError:
        print("paho-mqtt kurulu değil. Kur:  python -m pip install paho-mqtt")
        return

    gorulen = set()

    def on_connect(client, userdata, flags, reason_code, properties=None):
        if reason_code == 0:
            print(f"Brokere bağlandı ({broker}:{port}). Konu: {konu}")
            client.subscribe(konu)
            print("Paket bekleniyor... (Ctrl+C ile çık)\n")
        else:
            print(f"Bağlantı reddedildi (kod {reason_code}).")

    def on_message(client, userdata, msg):
        nonce, blob = wire_ayikla(teknik, msg.payload)
        if nonce is None:
            print("  [RED] Paket çok kısa (nonce eksik).")
            return
        # Çöz + doğrula + soğuk zincir + kaydet (simülasyonla aynı fonksiyon)
        paket_isle(db, teknik, nonce, blob, gorulen)

    # paho-mqtt v2 geriye-uyumlu; sürüm farkını yut
    try:
        istemci = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    except AttributeError:
        istemci = mqtt.Client()   # eski paho (v1)
    istemci.on_connect = on_connect
    istemci.on_message = on_message

    print(f"MQTT mod: {broker}:{port} brokerine bağlanılıyor...")
    try:
        istemci.connect(broker, port, keepalive=60)
    except OSError as e:
        print(f"Brokere ulaşılamadı: {e}\n"
              f"Broker çalışıyor mu? (ör. mosquitto) ve '{broker}' doğru mu?")
        return

    try:
        istemci.loop_forever()
    except KeyboardInterrupt:
        print("\nDinleme durduruldu.")
        istemci.disconnect()


def main():
    teknik = TEKNIK_HARITA[SECILEN_TEKNIK]
    db = veritabani_hazirla()
    print(f"Alıcı başladı. Teknik: {teknik.ad} | DB: {VERITABANI}\n")

    def arg(bayrak, varsayilan):
        return sys.argv[sys.argv.index(bayrak) + 1] if bayrak in sys.argv else varsayilan

    if "--mqtt" in sys.argv:
        broker = arg("--broker", MQTT_BROKER)
        konu = arg("--konu", MQTT_KONU)
        mqtt_dinle(db, teknik, broker, MQTT_PORT, konu)
    elif "--seri" in sys.argv:
        port = sys.argv[sys.argv.index("--seri") + 1]
        print(f"SERİ mod: {port} dinleniyor... (Ctrl+C ile çık)")
        print("(Bu kısım cihaz paket formatı netleşince doldurulacak — iskelet hazır.)")
        # TODO: pyserial ile porttan [nonce][blob] oku, wire_ayikla + paket_isle çağır.
    else:
        simulasyon(db, teknik)

    db.close()
    print("\nBitti. Kayıtlar soguk_zincir.db içinde.")


if __name__ == "__main__":
    main()
