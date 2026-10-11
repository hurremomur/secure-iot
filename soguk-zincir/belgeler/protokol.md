# Haberleşme Protokolü

Cihaz (ESP32) ile alıcı (PC) arasındaki anlaşma. İkisi de bu kurallara uyar.

## Veri paketi (düz hali)

JSON, kompakt: `{"t":6.2,"h":57.5,"k":0,"ts":1699999999,"n":47}`

| Alan | Anlam | Örnek |
|------|-------|-------|
| `t`  | sıcaklık (°C) | 6.2 |
| `h`  | nem (%) | 57.5 |
| `k`  | kapak açık mı (1/0) | 0 |
| `ts` | zaman damgası (saniye) | 1699999999 |
| `n`  | sayaç (her mesajda +1) | 47 |

## Şifreli paket (hatta giden)

```
[ nonce ] [ şifreli veri ] [ tag (16 bayt) ]
```

- **nonce:** her mesajda farklı. Sayaçtan türetilir (`n` → nonce). Teknik 12 veya 16 baytlık nonce ister.
- **tag:** AEAD doğrulama etiketi (16 bayt). Alıcı bununla bütünlüğü kontrol eder.
- **ilişkili veri (AAD):** `cihaz-01` (şifrelenmez ama doğrulanır — kimlik).

## Güvenlik kuralları

1. **Gizlilik:** veri AEAD ile şifrelenir (AES-128-GCM / ChaCha20-Poly1305 / Ascon-128).
2. **Bütünlük:** alıcı tag'i doğrular; tutmazsa paketi REDDEDER, "manipülasyon" olayı kaydeder.
3. **Tazelik (replay):** sayaç `n` artan olmalı. Daha önce görülen bir `n` gelirse REDDEDİLİR.
4. **Anahtar:** başlangıçta önceden paylaşılmış sabit anahtar. İleri aşamada ECDH ile oturum anahtarı.

## Soğuk zincir kuralı

- Güvenli aralık: **2–8 °C**. Dışına çıkarsa `BOZULDU`.
- Kapak açıksa (`k=1`) `UYARI`.
- İkisi de yoksa `OK`.

## Kaydet-sonra-aktar

Cihaz yolda (WiFi yokken) ölçümleri **şifreli** olarak belleğe yazar; varışta
(hedef ağ menzile girince) biriken paketleri topluca aktarır.
