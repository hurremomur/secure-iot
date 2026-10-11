"""
kripto.py — Şifreleme çekirdeği
================================
Projede karşılaştırılacak tüm şifreleme teknikleri, tek bir ortak arayüz altında.

Her teknik aynı iki metodu sağlar:
    sifrele(anahtar, nonce, veri, iliskili=b"")  -> şifreli bayt dizisi
    coz(anahtar, nonce, blob, iliskili=b"")       -> düz veri (bayt)

AEAD tekniklerinde (GCM, ChaCha20-Poly1305, Ascon) veri değiştirilmişse
`coz` bir DogrulamaHatasi fırlatır — yani bütünlük bozulursa veri reddedilir.

Teknikler:
    DuzMetin          : şifreleme yok (karşılaştırma baz çizgisi)
    AES128CTR         : AES-128-CTR, yalnız gizlilik (bütünlük YOK)
    AES128GCM         : AES-128-GCM, AEAD (gizlilik + bütünlük + kimlik)
    ChaCha20P1305     : ChaCha20-Poly1305, AEAD
    Ascon128          : Ascon-128, NIST hafif kriptografi standardı, AEAD
"""

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM, ChaCha20Poly1305
from cryptography.exceptions import InvalidTag
import ascon


class DogrulamaHatasi(Exception):
    """Bütünlük/kimlik doğrulaması başarısız: veri değiştirilmiş ya da sahte."""


class Teknik:
    """Tüm şifreleme tekniklerinin temel sınıfı."""
    ad = "temel"
    anahtar_uzunlugu = 16   # bayt (128-bit)
    nonce_uzunlugu = 12     # bayt
    dogrulamali = False     # AEAD mı (bütünlük sağlıyor mu)

    def sifrele(self, anahtar, nonce, veri, iliskili=b""):
        raise NotImplementedError

    def coz(self, anahtar, nonce, blob, iliskili=b""):
        raise NotImplementedError


class DuzMetin(Teknik):
    ad = "Düz Metin"
    dogrulamali = False

    def sifrele(self, anahtar, nonce, veri, iliskili=b""):
        return veri

    def coz(self, anahtar, nonce, blob, iliskili=b""):
        return blob


class AES128CTR(Teknik):
    ad = "AES-128-CTR"
    dogrulamali = False   # DİKKAT: bütünlük yok; manipülasyonu yakalayamaz

    def sifrele(self, anahtar, nonce, veri, iliskili=b""):
        sayac = nonce.ljust(16, b"\x00")
        sifreleyici = Cipher(algorithms.AES(anahtar), modes.CTR(sayac)).encryptor()
        return sifreleyici.update(veri) + sifreleyici.finalize()

    def coz(self, anahtar, nonce, blob, iliskili=b""):
        sayac = nonce.ljust(16, b"\x00")
        cozucu = Cipher(algorithms.AES(anahtar), modes.CTR(sayac)).decryptor()
        return cozucu.update(blob) + cozucu.finalize()


class AES128GCM(Teknik):
    ad = "AES-128-GCM"
    dogrulamali = True

    def sifrele(self, anahtar, nonce, veri, iliskili=b""):
        return AESGCM(anahtar).encrypt(nonce, veri, iliskili)

    def coz(self, anahtar, nonce, blob, iliskili=b""):
        try:
            return AESGCM(anahtar).decrypt(nonce, blob, iliskili)
        except InvalidTag:
            raise DogrulamaHatasi("AES-GCM etiketi tutmadı: veri değiştirilmiş/sahte.")


class ChaCha20P1305(Teknik):
    ad = "ChaCha20-Poly1305"
    anahtar_uzunlugu = 32   # 256-bit anahtar
    dogrulamali = True

    def sifrele(self, anahtar, nonce, veri, iliskili=b""):
        return ChaCha20Poly1305(anahtar).encrypt(nonce, veri, iliskili)

    def coz(self, anahtar, nonce, blob, iliskili=b""):
        try:
            return ChaCha20Poly1305(anahtar).decrypt(nonce, blob, iliskili)
        except InvalidTag:
            raise DogrulamaHatasi("ChaCha20-Poly1305 etiketi tutmadı: veri değiştirilmiş/sahte.")


class Ascon128(Teknik):
    ad = "Ascon-128"
    anahtar_uzunlugu = 16
    nonce_uzunlugu = 16     # Ascon 128-bit nonce ister
    dogrulamali = True

    def sifrele(self, anahtar, nonce, veri, iliskili=b""):
        return ascon.encrypt(anahtar, nonce, iliskili, veri, variant="Ascon-128")

    def coz(self, anahtar, nonce, blob, iliskili=b""):
        veri = ascon.decrypt(anahtar, nonce, iliskili, blob, variant="Ascon-128")
        if veri is None:
            raise DogrulamaHatasi("Ascon etiketi tutmadı: veri değiştirilmiş/sahte.")
        return veri


# Projede karşılaştırılacak teknik listesi (sıra önemli)
TEKNIKLER = [DuzMetin(), AES128CTR(), AES128GCM(), ChaCha20P1305(), Ascon128()]

# Ada göre erişim için sözlük
TEKNIK_HARITA = {t.ad: t for t in TEKNIKLER}
