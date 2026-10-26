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
import json
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

# Cihazın açılışta yayınladığı "KIYAS:[...]" satırı buraya yazılır; pano.py okur.
KIYAS_CIKTI = "cihaz_kiyas.json"
# Cihazdaki ASCII adları panoda düzgün Türkçe göster
KIYAS_AD_DUZELT = {"Duz Metin": "Düz Metin"}

# MQTT ayarları (cihazla aynı broker/konu olmalı)
# Demo için halka açık broker (kurulum gerektirmez). Yerel kullanım için
# MQTT_BROKER = "localhost" yap ve bir Mosquitto broker çalıştır.
MQTT_BROKER = "broker.hivemq.com"  # halka açık test brokeri
MQTT_PORT = 1883                   # TLS yok; şifreleme zaten uygulama katmanında (uçtan uca)
MQTT_KONU = "soguk-zincir/ho7k2m/veri"   # benzersiz konu (başkasının verisine karışmasın)


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


def paket_isle(db, teknik, nonce, blob, gorulen_sayaclar, anahtar=ANAHTAR):
    """Bir şifreli paketi çöz + doğrula + kaydet. Sonucu ekrana yazar.
    anahtar: önceden paylaşılmış ANAHTAR (varsayılan) ya da ECDH ile türetilen oturum anahtarı."""
    # 1) Çöz + bütünlük doğrula
    try:
        ham = teknik.coz(anahtar, nonce, blob, ILISKILI)
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
    # Zaman damgası: cihazın gerçek saati olmayabilir (NTP yoksa ts = açılıştan beri
    # geçen saniye). Bu yüzden kaydın saatini ALICI (PC) damgalar — "paketin alındığı an".
    simdi = int(time.time())
    db.execute("INSERT INTO olcumler(zaman,sicaklik,nem,kapak,sayac,durum) VALUES(?,?,?,?,?,?)",
               (simdi, kayit["t"], kayit["h"], kayit["k"], kayit["n"], durum))
    if durum != "OK":
        db.execute("INSERT INTO olaylar(zaman,tur,aciklama) VALUES(?,?,?)",
                   (simdi, durum.lower(), aciklama))
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


def kiyas_yaz(satir):
    """Cihazdan gelen 'KIYAS:[...]' satırını cihaz_kiyas.json'a yaz (pano çubuk grafiği)."""
    try:
        veri = json.loads(satir[len("KIYAS:"):])
    except json.JSONDecodeError:
        return
    for r in veri:
        r["ad"] = KIYAS_AD_DUZELT.get(r.get("ad", ""), r.get("ad", ""))
    with open(KIYAS_CIKTI, "w", encoding="utf-8") as f:
        json.dump(veri, f, ensure_ascii=False, indent=2)
    en_hizli = min((r for r in veri if r.get("aead")), key=lambda r: r["sure_us"], default=None)
    ek = f" (en hızlı AEAD: {en_hizli['ad']})" if en_hizli else ""
    print(f"  [KIYAS] cihaz teknik kıyası panoya yazıldı -> {KIYAS_CIKTI}{ek}")


def wire_ayikla(teknik, payload):
    """Hattan gelen ham baytı protokole göre ayır: [nonce][şifreli veri][tag].
    Döndürür: (nonce, blob) — blob = şifreli veri + tag."""
    n = teknik.nonce_uzunlugu
    if len(payload) < n:
        return None, None
    return payload[:n], payload[n:]


def mqtt_dinle(db, teknik, broker, port, konu, ecdh=False):
    """MQTT brokerine abone ol; gelen her şifreli paketi çöz + doğrula + kaydet.
    ecdh=True ise önce X25519 ile anahtar değişimi yapılır (sabit anahtar kullanılmaz)."""
    try:
        import paho.mqtt.client as mqtt
    except ImportError:
        print("paho-mqtt kurulu değil. Kur:  python -m pip install paho-mqtt")
        return

    gorulen = set()
    base = konu.rsplit("/", 1)[0]          # "soguk-zincir/ho7k2m"
    pub_cihaz = base + "/pub/cihaz"        # cihazın açık anahtarı
    pub_alici = base + "/pub/alici"        # alıcının açık anahtarı
    durum = {"anahtar": None if ecdh else ANAHTAR, "ozel": None, "acik": None}

    if ecdh:
        from anahtar_degisimi import yeni_cift, oturum_anahtari
        durum["ozel"], durum["acik"] = yeni_cift()

    def on_connect(client, userdata, flags, reason_code, properties=None):
        if reason_code != 0:
            print(f"Bağlantı reddedildi (kod {reason_code}).")
            return
        print(f"Brokere bağlandı ({broker}:{port}). Konu: {konu}")
        client.subscribe(konu)
        if ecdh:
            client.subscribe(pub_cihaz)
            # Açık anahtarı retained yayınla (sıra önemsiz olsun diye)
            client.publish(pub_alici, durum["acik"], retain=True)
            print("ECDH: açık anahtar yayınlandı, cihazın anahtarı bekleniyor...")
        else:
            print("Paket bekleniyor... (Ctrl+C ile çık)\n")

    def on_message(client, userdata, msg):
        if ecdh and msg.topic == pub_cihaz:
            if len(msg.payload) == 32:
                # Cihaz açık anahtarını aldık: kendi açık anahtarımızı geri yolla
                client.publish(pub_alici, durum["acik"], retain=True)
                if durum["anahtar"] is None:
                    durum["anahtar"] = oturum_anahtari(durum["ozel"], msg.payload)
                    print(f"ECDH tamam ✓ Oturum anahtarı türetildi: {durum['anahtar'].hex()}")
                    print("Paket bekleniyor... (Ctrl+C ile çık)\n")
            return
        if msg.topic != konu:
            return
        if durum["anahtar"] is None:
            return  # anahtar henüz hazır değil, erken paketi atla
        nonce, blob = wire_ayikla(teknik, msg.payload)
        if nonce is None:
            print("  [RED] Paket çok kısa (nonce eksik).")
            return
        paket_isle(db, teknik, nonce, blob, gorulen, durum["anahtar"])

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


def seri_dinle(db, teknik, port, baud=115200):
    """Cihazdan USB/seri üzerinden gelen paketleri oku + çöz + kaydet.
    Cihaz her ölçümü 'PKT:<hex>' satırı olarak gönderir; hex = [nonce][şifreli][tag]."""
    try:
        import serial  # pyserial
    except ImportError:
        print("pyserial kurulu değil. Kur:  python -m pip install pyserial")
        return
    try:
        ser = serial.Serial(port, baud, timeout=1)
    except Exception as e:
        print(f"Seri port açılamadı ({port}): {e}")
        print("İpucu: Arduino'daki Serial Monitor'ı KAPAT — port aynı anda tek "
              "programda açılabilir.")
        return

    print(f"SERİ mod: {port} @ {baud} dinleniyor... (Ctrl+C ile çık)")
    print("Canlı paket (PKT:) -> DB; açılış kıyası (KIYAS:) -> pano. İkisi de bu akıştan.\n")
    gorulen = set()
    try:
        while True:
            try:
                satir = ser.readline().decode("ascii", errors="ignore").strip()
            except Exception:
                continue
            if satir.startswith("KIYAS:"):
                kiyas_yaz(satir)   # cihazın açılış kıyası -> panoya
                continue
            if not satir.startswith("PKT:"):
                continue   # cihazın diğer (debug) satırlarını yok say
            try:
                payload = bytes.fromhex(satir[4:])
            except ValueError:
                continue
            nonce, blob = wire_ayikla(teknik, payload)
            if nonce is None:
                print("  [RED] Paket çok kısa (nonce eksik).")
                continue
            paket_isle(db, teknik, nonce, blob, gorulen)
    except KeyboardInterrupt:
        print("\nDinleme durduruldu.")
    finally:
        ser.close()


def main():
    teknik = TEKNIK_HARITA[SECILEN_TEKNIK]
    db = veritabani_hazirla()
    print(f"Alıcı başladı. Teknik: {teknik.ad} | DB: {VERITABANI}\n")

    def arg(bayrak, varsayilan):
        return sys.argv[sys.argv.index(bayrak) + 1] if bayrak in sys.argv else varsayilan

    if "--mqtt" in sys.argv:
        broker = arg("--broker", MQTT_BROKER)
        konu = arg("--konu", MQTT_KONU)
        ecdh = "--ecdh" in sys.argv
        if ecdh:
            print("ANAHTAR DEĞİŞİMİ: X25519 (ECDH) — sabit anahtar kullanılmıyor.\n")
        mqtt_dinle(db, teknik, broker, MQTT_PORT, konu, ecdh=ecdh)
    elif "--seri" in sys.argv:
        port = sys.argv[sys.argv.index("--seri") + 1]
        seri_dinle(db, teknik, port)
    else:
        simulasyon(db, teknik)

    db.close()
    print("\nBitti. Kayıtlar soguk_zincir.db içinde.")


if __name__ == "__main__":
    main()
