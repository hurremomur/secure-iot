"""
anahtar_degisimi.py — ECDH (X25519) ile oturum anahtarı türetme
================================================================
Sabit, önceden paylaşılmış anahtar yerine; iki taraf açık kanal üzerinden
anahtarı HİÇ göndermeden ortak bir gizli oturum anahtarı üretir.

Nasıl çalışır (Diffie-Hellman mantığı):
    1) Her taraf bir özel + açık anahtar çifti üretir (X25519).
    2) Taraflar yalnızca AÇIK anahtarlarını değiş tokuş eder (gizli kalmaz, sorun değil).
    3) Her taraf "kendi özel anahtarı + karşının açık anahtarı" ile aynı
       paylaşılan sırrı hesaplar (ECDH'nin matematiksel özelliği).
    4) Bu sır bir KDF'den (HKDF-SHA256) geçirilip 16 baytlık AES anahtarına
       dönüştürülür. İki tarafta da AYNI anahtar çıkar.

Açık anahtarlar hatta görünse bile, özel anahtarlar olmadan oturum anahtarı
hesaplanamaz. Böylece gömülü sabit anahtara gerek kalmaz (forward secrecy).

Gerektirir: cryptography (zaten projede var).
"""

from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey, X25519PublicKey)
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes

ANAHTAR_UZUNLUGU = 16          # AES-128 için 16 bayt oturum anahtarı
BILGI = b"soguk-zincir-oturum-v1"   # HKDF info (iki tarafta aynı olmalı)


def yeni_cift():
    """Yeni bir X25519 özel/açık anahtar çifti üretir.
    Döndürür: (ozel_anahtar_nesnesi, acik_anahtar_baytlari[32])."""
    ozel = X25519PrivateKey.generate()
    acik = ozel.public_key().public_bytes_raw()   # 32 bayt, hatta gönderilecek
    return ozel, acik


def oturum_anahtari(ozel, karsi_acik_bayt):
    """Kendi özel anahtarı + karşının açık anahtarı -> ortak 16 baytlık AES anahtarı."""
    karsi_acik = X25519PublicKey.from_public_bytes(karsi_acik_bayt)
    paylasilan_sir = ozel.exchange(karsi_acik)     # 32 bayt ham ECDH sırrı
    # Ham sırrı doğrudan anahtar olarak kullanmayız; KDF'den geçiririz.
    return HKDF(algorithm=hashes.SHA256(), length=ANAHTAR_UZUNLUGU,
                salt=None, info=BILGI).derive(paylasilan_sir)


# Kendi başına çalıştırılırsa: iki tarafın aynı anahtarı türettiğini göster
if __name__ == "__main__":
    # Cihaz ve alıcı birer çift üretir
    cihaz_ozel, cihaz_acik = yeni_cift()
    alici_ozel, alici_acik = yeni_cift()

    # Açık anahtarları "değiş tokuş" edip her iki taraf anahtarı hesaplar
    cihaz_anahtar = oturum_anahtari(cihaz_ozel, alici_acik)
    alici_anahtar = oturum_anahtari(alici_ozel, cihaz_acik)

    print("Cihazın açık anahtarı :", cihaz_acik.hex())
    print("Alıcının açık anahtarı:", alici_acik.hex())
    print("Cihaz oturum anahtarı :", cihaz_anahtar.hex())
    print("Alıcı oturum anahtarı :", alici_anahtar.hex())
    print("AYNI MI? ->", "EVET ✓" if cihaz_anahtar == alici_anahtar else "HAYIR ✗")
