"""
paket.py — Veri paketi ve soğuk zincir mantığı
===============================================
Cihazın ürettiği sensör/olay verisini pakete çevirir, geri çözer ve
soğuk zincir kontrolü yapar. Şifrelemeden bağımsızdır (onu kripto.py yapar).

Paket alanları:
    t  : sıcaklık (°C)
    h  : nem (%)
    k  : kapak açık mı (1/0)
    ts : zaman damgası (saniye)
    n  : sayaç (her mesajda artar — replay koruması)
"""

import json
import time

# Soğuk zincir güvenli sıcaklık aralığı (ilaç/aşı için tipik: 2–8 °C)
SICAKLIK_MIN = 2.0
SICAKLIK_MAX = 8.0


def paket_olustur(sicaklik, nem, kapak_acik, sayac, zaman=None):
    """Sensör verisini kompakt bir bayt dizisine çevirir."""
    kayit = {
        "t": round(sicaklik, 1),
        "h": round(nem, 1),
        "k": 1 if kapak_acik else 0,
        "ts": int(zaman if zaman is not None else time.time()),
        "n": sayac,
    }
    return json.dumps(kayit, separators=(",", ":")).encode("utf-8")


def paket_coz(ham_bayt):
    """Baytı geri sözlüğe çevirir."""
    return json.loads(ham_bayt.decode("utf-8"))


def nonce_uret(sayac, uzunluk):
    """Sayaçtan nonce türetir (her mesajda farklı nonce = replay koruması)."""
    return sayac.to_bytes(uzunluk, "big")


def soguk_zincir_durumu(kayit):
    """Kaydı değerlendirir, (durum_kodu, aciklama) döndürür."""
    if kayit["t"] < SICAKLIK_MIN or kayit["t"] > SICAKLIK_MAX:
        return ("BOZULDU",
                f"Sıcaklık {kayit['t']}°C — güvenli aralık {SICAKLIK_MIN}-{SICAKLIK_MAX}°C dışında")
    if kayit["k"] == 1:
        return ("UYARI", "Kapak açık")
    return ("OK", "Güvenli")
