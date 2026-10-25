"""
kiyas_oku.py — 04_kiyas'ın cihaz ölçümünü panoya aktar
=======================================================
04_kiyas firmware'i çalışırken seri porttan bir "KIYAS:[...]" satırı gönderir
(cihazda ölçülen teknik süreleri/boyutları). Bu betik o satırı yakalar ve
cihaz_kiyas.json dosyasına yazar; pano.py onu çubuk grafik olarak gösterir.

Kullanım:
    1) ESP32'ye 04_kiyas yükle.
    2) Arduino Serial Monitor'ı KAPAT (port çakışmasın).
    3) python kiyas_oku.py COM5
    4) "Kaydedildi" deyince kapanır; pano'yu açarsan grafikte görünür.

pyserial gerekir:  python -m pip install pyserial
"""

import sys
import json

# Cihazdaki ASCII adları panoda düzgün Türkçe göster
AD_DUZELT = {"Duz Metin": "Düz Metin"}

CIKTI = "cihaz_kiyas.json"


def main():
    if len(sys.argv) < 2:
        print("Kullanım: python kiyas_oku.py COM5")
        return
    port = sys.argv[1]
    try:
        import serial
    except ImportError:
        print("pyserial kurulu değil. Kur:  python -m pip install pyserial")
        return
    try:
        ser = serial.Serial(port, 115200, timeout=1)
    except Exception as e:
        print(f"Seri port açılamadı ({port}): {e}")
        print("İpucu: Arduino Serial Monitor'ı KAPAT.")
        return

    print(f"{port} dinleniyor, cihazdan KIYAS satırı bekleniyor... (Ctrl+C ile çık)")
    try:
        while True:
            satir = ser.readline().decode("ascii", errors="ignore").strip()
            if not satir.startswith("KIYAS:"):
                continue
            try:
                veri = json.loads(satir[len("KIYAS:"):])
            except json.JSONDecodeError:
                continue
            for r in veri:
                r["ad"] = AD_DUZELT.get(r.get("ad", ""), r.get("ad", ""))
            with open(CIKTI, "w", encoding="utf-8") as f:
                json.dump(veri, f, ensure_ascii=False, indent=2)
            print(f"Kaydedildi -> {CIKTI}")
            for r in veri:
                print(f"  {r['ad']:<20} {r['sure_us']:>8.2f} µs   {r['boyut']} bayt")
            print("\nPano açıksa birkaç saniye içinde grafikte görünür.")
            return
    except KeyboardInterrupt:
        print("\nİptal edildi.")
    finally:
        ser.close()


if __name__ == "__main__":
    main()
