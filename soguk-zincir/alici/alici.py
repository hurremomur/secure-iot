"""
alici.py — Alıcı uygulaması (çöz + doğrula + soğuk zincir + kayıt)
==================================================================
Cihazdan gelen şifreli paketleri alır, çözer, bütünlüğünü doğrular,
soğuk zincir durumunu belirler ve SQLite'a kaydeder.

İki çalışma modu:
    - Simülasyon (varsayılan): cihaz yokken test için sahte şifreli paket üretir.
      Hemen çalışır, donanım gerekmez.
          python alici.py
    - Seri (cihaz bağlıyken): ESP32'den USB/seri üzerinden paket okur.
          python alici.py --seri COM3
      (pyserial gerekir: python -m pip install pyserial)

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


def main():
    teknik = TEKNIK_HARITA[SECILEN_TEKNIK]
    db = veritabani_hazirla()
    print(f"Alıcı başladı. Teknik: {teknik.ad} | DB: {VERITABANI}\n")

    if "--seri" in sys.argv:
        port = sys.argv[sys.argv.index("--seri") + 1]
        print(f"SERİ mod: {port} dinleniyor... (Ctrl+C ile çık)")
        print("(Bu kısım cihaz paket formatı netleşince doldurulacak — iskelet hazır.)")
        # TODO: pyserial ile porttan nonce+blob oku, paket_isle(...) çağır.
    else:
        simulasyon(db, teknik)

    db.close()
    print("\nBitti. Kayıtlar soguk_zincir.db içinde.")


if __name__ == "__main__":
    main()
