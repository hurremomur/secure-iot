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
  Nonce'un kendisi **hat üzerinde gönderilir**; alıcı onu baştan okur (ilk 12/16 bayt).
- **tag:** AEAD doğrulama etiketi (16 bayt). Şifreli verinin **sonuna** eklenir
  (Python `cryptography` kütüphanesi de tag'i sona koyar; cihaz da aynısını yapar).
- **ilişkili veri (AAD):** `cihaz-01` (şifrelenmez ama doğrulanır — kimlik).

## Taşıma katmanı (MQTT / seri)

Taşıma katmanı yalnız **bayt taşır**; şifreleme bunun ÜSTÜNDEdir. Yukarıdaki
şifreli paket, taşıyıcıdan bağımsızdır — aynı baytlar hem seri hem MQTT ile gider.

- **MQTT (WiFi, canlı):** cihaz şifreli paketi bir **konuya** yayınlar, alıcı abone olur.
  - Konu: `soguk-zincir/cihaz-01/veri`
  - Broker: yerel Mosquitto (varsayılan port **1883**, TLS yok).
  - TLS gerekmez: gizlilik/bütünlük zaten payload'un içindedir (**uçtan uca**).
    Broker bile veriyi göremez.
- **Seri (USB, offline/demo):** aynı paket USB seri porttan `PKT:<hex>` satırı olarak gider.
- **Bluetooth (portatif):** aynı `PKT:<hex>` satırı Bluetooth SPP ile gider; PC'de sanal
  bir COM portu olarak görünür, alıcı onu seri port gibi okur (kod değişmez).

Alıcı her modda da paketi aynı şekilde işler: `[nonce]` baştan ayrılır,
kalanı (şifreli veri + tag) çözülüp doğrulanır.

## Güvenlik kuralları

1. **Gizlilik:** veri AEAD ile şifrelenir (AES-128-GCM / ChaCha20-Poly1305 / Ascon-128).
2. **Bütünlük:** alıcı tag'i doğrular; tutmazsa paketi REDDEDER, "manipülasyon" olayı kaydeder.
3. **Tazelik (replay):** sayaç `n` artan olmalı. Daha önce görülen bir `n` gelirse REDDEDİLİR.
4. **Anahtar:** iki mod — (a) önceden paylaşılmış sabit anahtar, (b) ECDH ile oturum anahtarı.

## Anahtar değişimi (ECDH)

`--ecdh` modunda sabit anahtar kullanılmaz; oturum anahtarı el sıkışmayla türetilir:

1. Her taraf bir **X25519** özel/açık anahtar çifti üretir.
2. Açık anahtarlar (32 bayt) ayrı konularda değiş tokuş edilir:
   - cihaz → `.../pub/cihaz`, alıcı → `.../pub/alici`
3. Her taraf "kendi özel + karşının açık" anahtarıyla aynı paylaşılan sırrı hesaplar (ECDH).
4. Sır **HKDF-SHA256** ile 16 baytlık AES-128 oturum anahtarına indirgenir.
5. Bundan sonra veri bu oturum anahtarıyla şifrelenir.

Açık anahtarlar hatta görünse bile, özel anahtarlar olmadan oturum anahtarı hesaplanamaz
(gizli anahtar hiç gönderilmez; her oturumda taze anahtar → forward secrecy).

## Soğuk zincir kuralı

- Güvenli aralık: **2–8 °C**. Dışına çıkarsa `BOZULDU`.
- Kapak açıksa (`k=1`) `UYARI`.
- İkisi de yoksa `OK`.

## Kaydet-sonra-aktar

Cihaz yolda (WiFi yokken) ölçümleri **şifreli** olarak belleğe yazar; varışta
(hedef ağ menzile girince) biriken paketleri topluca aktarır.
