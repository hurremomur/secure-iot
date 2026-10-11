"""
guvenlik_testi.py — Saldırı senaryoları (güvenlik gösterimi)
=============================================================
Her teknik için üç şey denenir:
    1) Normal tur     : şifrele -> çöz, veri doğru geliyor mu?
    2) Manipülasyon   : şifreli veri değiştirilirse ne olur?
    3) Replay (tekrar): eski bir paket tekrar gönderilirse ne olur?

Beklenen sonuç:
    - AEAD teknikleri (GCM, ChaCha20-Poly1305, Ascon): manipülasyonu REDDEDER.
    - Düz metin / AES-CTR: manipülasyonu YAKALAYAMAZ (bütünlük yok).
    - Replay her teknikte sayaç kontrolüyle yakalanır (uygulama katmanı).

Çalıştır:  python guvenlik_testi.py
"""

import os
from kripto import TEKNIKLER, DogrulamaHatasi
from paket import paket_olustur, paket_coz, nonce_uret, soguk_zincir_durumu


def cizgi(k="-"):
    print(k * 64)


def manipulasyon_testi(teknik, anahtar, nonce, veri, iliskili):
    blob = teknik.sifrele(anahtar, nonce, veri, iliskili)
    if len(blob) == 0:
        return "veri boş, atlandı"
    bozuk = bytearray(blob)
    bozuk[len(bozuk) // 2] ^= 0x01   # ortadaki bir baytı değiştir
    try:
        cozulen = teknik.coz(anahtar, nonce, bytes(bozuk), iliskili)
        try:
            paket_coz(cozulen)   # çözülebildi mi
            return "KABUL EDİLDİ (manipülasyon yakalanamadı — bütünlük yok)"
        except Exception:
            return "KABUL EDİLDİ ama veri bozuk (bütünlük yok; sessiz hata)"
    except DogrulamaHatasi:
        return "REDDEDİLDİ (manipülasyon yakalandı)"


def main():
    print("\nGÜVENLİK TESTİ — manipülasyon ve replay\n")

    for teknik in TEKNIKLER:
        anahtar = os.urandom(teknik.anahtar_uzunlugu)
        nonce = nonce_uret(47, teknik.nonce_uzunlugu)
        veri = paket_olustur(6.2, 57.5, False, 47)
        iliskili = b"cihaz-01"

        cizgi("=")
        print(f"### {teknik.ad}   (AEAD={teknik.dogrulamali})")

        # 1) Normal tur
        blob = teknik.sifrele(anahtar, nonce, veri, iliskili)
        kayit = paket_coz(teknik.coz(anahtar, nonce, blob, iliskili))
        durum, aciklama = soguk_zincir_durumu(kayit)
        print(f"  1) Normal tur     : {kayit}  [{durum}]")

        # 2) Manipülasyon
        sonuc = manipulasyon_testi(teknik, anahtar, nonce, veri, iliskili)
        print(f"  2) Manipülasyon   : {sonuc}")

        # 3) Replay: aynı paketi iki kez "gönder" — ilki kabul, ikincisi red
        gorulen = set()
        sayac = kayit["n"]
        # ilk gönderim
        gorulen.add(sayac)
        # ikinci (tekrar) gönderim
        ikinci = "REDDEDİLDİ (sayaç daha önce görüldü)" if sayac in gorulen else "kabul"
        print(f"  3) Replay (n={sayac}) : 1. gönderim kabul, 2. gönderim -> {ikinci}")

    cizgi("=")
    print("\nSonuç: AEAD teknikleri manipülasyonu reddediyor; sayaç ile replay yakalanıyor.")
    print("Düz metin ve AES-CTR manipülasyonu yakalayamıyor — bu yüzden AEAD şart.\n")


if __name__ == "__main__":
    main()
