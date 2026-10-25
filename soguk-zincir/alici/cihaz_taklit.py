"""
cihaz_taklit.py — Cihaz taklidi (MQTT yayıncı / ESP32 öykünücüsü)
==================================================================
ESP32 henüz yokken (ya da demo için) cihaz gibi davranır: ölçümü üretir,
şifreler ve brokere YAYINLAR. alici.py --mqtt bunu dinleyip çözer.

Böylece donanım olmadan tüm zinciri test edebiliriz:
    cihaz_taklit (yayınla) → broker → alici.py --mqtt (çöz+DB) → pano (göster)

Yayınlanan payload, protokoldeki hat formatıdır:  [nonce][şifreli veri][tag]
(ESP32 firmware'i de tam olarak bunu gönderecek — kod değişmeden çalışır.)

Ayar (anahtar/teknik/broker/konu) alici.py'den alınır; ikisi hep aynı kalır.

Çalıştırma:
    python cihaz_taklit.py                 # demo: normal + bozulma + saldırı + replay
    python cihaz_taklit.py --broker 192.168.1.50
    python cihaz_taklit.py --sadece-normal # yalnızca normal ölçümler (sonsuz döngü)
"""

import sys
import time
import random

from kripto import TEKNIK_HARITA
from paket import paket_olustur, nonce_uret
# Ayarları alıcıyla ORTAK tut (aynı anahtar/teknik/broker)
from alici import (ANAHTAR, ILISKILI, SECILEN_TEKNIK,
                   MQTT_BROKER, MQTT_PORT, MQTT_KONU)


def yayinci(broker, port):
    try:
        import paho.mqtt.client as mqtt
    except ImportError:
        print("paho-mqtt kurulu değil. Kur:  python -m pip install paho-mqtt")
        sys.exit(1)
    try:
        c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    except AttributeError:
        c = mqtt.Client()
    try:
        c.connect(broker, port, keepalive=60)
    except OSError as e:
        print(f"Brokere ulaşılamadı ({broker}:{port}): {e}")
        sys.exit(1)
    c.loop_start()
    return c


# Aktif anahtar: varsayılan sabit ANAHTAR; --ecdh ile oturum anahtarıyla değişir
AKTIF_ANAHTAR = {"deger": ANAHTAR}


def paket_yap(teknik, sic, nem, kapak, sayac, boz_bayt=False):
    """Bir ölçümü şifreleyip hat formatına çevir: [nonce][şifreli veri][tag]."""
    veri = paket_olustur(sic, nem, kapak, sayac)
    nonce = nonce_uret(sayac, teknik.nonce_uzunlugu)
    blob = bytearray(teknik.sifrele(AKTIF_ANAHTAR["deger"], nonce, veri, ILISKILI))
    if boz_bayt and blob:
        blob[len(blob) // 2] ^= 0x01   # ortadaki baytı değiştir (manipülasyon)
    return bytes(nonce) + bytes(blob)


def main():
    def arg(bayrak, varsayilan):
        return sys.argv[sys.argv.index(bayrak) + 1] if bayrak in sys.argv else varsayilan

    broker = arg("--broker", MQTT_BROKER)
    konu = arg("--konu", MQTT_KONU)
    teknik = TEKNIK_HARITA[SECILEN_TEKNIK]

    c = yayinci(broker, port=MQTT_PORT)
    print(f"Cihaz taklidi yayında. Broker: {broker}:{MQTT_PORT} | Konu: {konu}")
    print(f"Teknik: {teknik.ad}\n")

    # --- ECDH anahtar değişimi (opsiyonel) ---
    if "--ecdh" in sys.argv:
        from anahtar_degisimi import yeni_cift, oturum_anahtari
        import threading
        base = konu.rsplit("/", 1)[0]
        pub_cihaz = base + "/pub/cihaz"
        pub_alici = base + "/pub/alici"
        ozel, acik = yeni_cift()
        hazir = threading.Event()

        def on_msg(cl, ud, msg):
            if msg.topic == pub_alici and not hazir.is_set() and len(msg.payload) == 32:
                AKTIF_ANAHTAR["deger"] = oturum_anahtari(ozel, msg.payload)
                print(f"ECDH tamam ✓ Oturum anahtarı: {AKTIF_ANAHTAR['deger'].hex()}\n")
                hazir.set()

        c.on_message = on_msg
        c.subscribe(pub_alici)
        print("ANAHTAR DEĞİŞİMİ: X25519 (ECDH). Açık anahtar yayınlanıyor, "
              "alıcının anahtarı bekleniyor...")
        for _ in range(30):                       # alıcıdan anahtar gelene kadar dene
            c.publish(pub_cihaz, acik, retain=True)
            if hazir.wait(1):
                break
        if not hazir.is_set():
            print("ECDH başarısız: alıcıdan açık anahtar gelmedi.\n"
                  "(Önce: python alici.py --mqtt --ecdh  çalışıyor mu?)")
            c.loop_stop(); c.disconnect(); return

    sayac = 0

    # Yalnız normal mod: gerçekçi, sürekli ölçüm (pano canlı dolsun)
    if "--sadece-normal" in sys.argv:
        print("Sürekli normal ölçüm yayınlanıyor (Ctrl+C ile çık)...")
        try:
            while True:
                sayac += 1
                sic = round(random.uniform(3.5, 7.5), 1)   # güvenli aralıkta gezin
                nem = round(random.uniform(45, 60), 1)
                c.publish(konu, paket_yap(teknik, sic, nem, False, sayac))
                print(f"  yayınlandı: n={sayac}  {sic}°C  %{nem}")
                time.sleep(2)
        except KeyboardInterrupt:
            print("\nDurduruldu.")
            c.loop_stop(); c.disconnect()
            return

    # Demo senaryosu: normal ölçümler → soğuk zincir kırılması → saldırı → replay
    senaryo = [
        (6.2, 57.5, False, "normal (güvenli)"),
        (7.4, 58.0, False, "normal (güvenli)"),
        (5.1, 55.0, False, "normal (güvenli)"),
        (9.8, 61.0, False, "SOĞUK ZİNCİR KIRILDI (9.8°C)"),
        (11.3, 63.0, True,  "SOĞUK ZİNCİR KIRILDI + kapak açık"),
    ]
    for sic, nem, kapak, etiket in senaryo:
        sayac += 1
        c.publish(konu, paket_yap(teknik, sic, nem, kapak, sayac))
        print(f"  n={sayac:<2} yayınlandı → {etiket}")
        time.sleep(1.2)

    # SALDIRI 1 — manipülasyon: şifreli paketin bir baytını değiştir
    if "--sadece-saldiri-yok" not in sys.argv:
        sayac += 1
        bozuk = paket_yap(teknik, 5.0, 54.0, False, sayac, boz_bayt=True)
        c.publish(konu, bozuk)
        print(f"  n={sayac:<2} yayınlandı → SALDIRI: 1 bayt değiştirildi "
              f"(AEAD reddetmeli)")
        time.sleep(1.2)

        # SALDIRI 2 — replay: daha önce gönderilen geçerli bir paketi tekrar gönder
        tekrar = paket_yap(teknik, 6.2, 57.5, False, 1)   # n=1 zaten görüldü
        c.publish(konu, tekrar)
        print(f"  n=1  yayınlandı → SALDIRI: replay (eski paket tekrar; "
              f"sayaç reddetmeli)")
        time.sleep(1.2)

    print("\nDemo bitti. alici.py --mqtt tarafında sonuçlara ve panoya bak.")
    c.loop_stop()
    c.disconnect()


if __name__ == "__main__":
    main()
