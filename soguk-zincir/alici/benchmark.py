"""
benchmark.py — Şifreleme teknikleri performans karşılaştırması (PC referansı)
=============================================================================
Her teknik için şifreleme/çözme süresi ve çıktı boyutunu ölçer, tabloya döker.

NOT: Bu ölçüm bilgisayarda alınır ve teknikleri göreli sıralamak içindir.
Projenin ASIL performans ölçümü kaynağı kısıtlı cihazda (ESP32) yapılacaktır.
PC'de AES donanım hızlandırmalı (AES-NI) olduğu için Ascon yavaş görünebilir;
bu, cihazda farklı çıkabilir — karşılaştırmanın cihazda yapılmasının nedeni budur.

Çalıştır:  python benchmark.py
"""

import os
import time
import json
from kripto import TEKNIKLER
from paket import paket_olustur

TEKRAR = 20000   # her teknik bu kadar kez çalıştırılıp ortalaması alınır


def olc(teknik, veri, iliskili):
    anahtar = os.urandom(teknik.anahtar_uzunlugu)
    nonce = os.urandom(teknik.nonce_uzunlugu)

    # ısınma (ölçüm öncesi kararlı hale gelsin)
    for _ in range(1000):
        blob = teknik.sifrele(anahtar, nonce, veri, iliskili)
        teknik.coz(anahtar, nonce, blob, iliskili)

    t0 = time.perf_counter()
    for _ in range(TEKRAR):
        blob = teknik.sifrele(anahtar, nonce, veri, iliskili)
    sifre_us = (time.perf_counter() - t0) / TEKRAR * 1e6

    blob = teknik.sifrele(anahtar, nonce, veri, iliskili)
    t0 = time.perf_counter()
    for _ in range(TEKRAR):
        teknik.coz(anahtar, nonce, blob, iliskili)
    coz_us = (time.perf_counter() - t0) / TEKRAR * 1e6

    return {
        "ad": teknik.ad,
        "dogrulamali": teknik.dogrulamali,
        "sifre_us": round(sifre_us, 3),
        "coz_us": round(coz_us, 3),
        "boyut": len(blob),
        "ek_yuk": len(blob) - len(veri),
    }


def main():
    veri = paket_olustur(6.2, 57.5, False, 47)
    iliskili = b"cihaz-01"
    print(f"\nVeri boyutu: {len(veri)} bayt | her teknik {TEKRAR} kez çalıştırıldı\n")

    sonuclar = [olc(t, veri, iliskili) for t in TEKNIKLER]

    print(f"{'Teknik':<20}{'AEAD':<7}{'Şifre(µs)':<12}{'Çöz(µs)':<12}{'Boyut':<7}{'Ek yük'}")
    print("-" * 64)
    for s in sonuclar:
        print(f"{s['ad']:<20}{('Evet' if s['dogrulamali'] else 'Hayır'):<7}"
              f"{s['sifre_us']:<12}{s['coz_us']:<12}{s['boyut']:<7}{s['ek_yuk']}")

    with open("benchmark_sonuc.json", "w", encoding="utf-8") as f:
        json.dump(sonuclar, f, ensure_ascii=False, indent=2)
    print("\n-> Sonuçlar benchmark_sonuc.json dosyasına kaydedildi.\n")


if __name__ == "__main__":
    main()
