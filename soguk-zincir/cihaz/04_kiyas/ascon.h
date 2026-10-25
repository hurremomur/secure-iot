/*
 * ascon.h — Ascon-128 AEAD (tek başlık, taşınabilir C)
 * ----------------------------------------------------
 * NIST hafif kriptografi standardı (2023). ESP32'nin mbedTLS'inde yok,
 * o yüzden referans algoritmayı buraya küçük ve sade biçimde yazdık.
 *
 * Bu uygulama, Python 'ascon' kütüphanesinin "Ascon-128" çıktısıyla
 * (aynı anahtar/nonce/ilişkili-veri/veri için) BİREBİR aynı şifreli+tag
 * üretecek şekilde test edildi.
 *
 * Kullanım:
 *   uint8_t c[mlen], tag[16];
 *   ascon128_encrypt(c, tag, m, mlen, ad, adlen, nonce16, key16);
 *
 * Parametreler: anahtar 16 bayt, nonce 16 bayt, tag 16 bayt, rate 8 bayt,
 * init/final tur sayısı a=12, ara tur sayısı b=6.
 */
#ifndef ASCON_H
#define ASCON_H

#include <stdint.h>
#include <stddef.h>

typedef struct { uint64_t x[5]; } ascon_state_t;

static inline uint64_t ascon_ror(uint64_t x, int n) {
  return (x >> n) | (x << (64 - n));
}

/* n bayt (<=8) big-endian oku, yüksek baytlara yerleştir */
static inline uint64_t ascon_load_be(const uint8_t* b, size_t n) {
  uint64_t x = 0;
  for (size_t i = 0; i < n; i++) x |= (uint64_t)b[i] << (56 - 8 * i);
  return x;
}
/* x'in yüksek n baytını b'ye yaz */
static inline void ascon_store_be(uint8_t* b, uint64_t x, size_t n) {
  for (size_t i = 0; i < n; i++) b[i] = (uint8_t)(x >> (56 - 8 * i));
}

static const uint8_t ascon_rc[12] = {
  0xf0, 0xe1, 0xd2, 0xc3, 0xb4, 0xa5, 0x96, 0x87, 0x78, 0x69, 0x5a, 0x4b
};

/* Tek tur permütasyon (sabit C ile) */
static inline void ascon_round(ascon_state_t* s, uint8_t C) {
  uint64_t x0 = s->x[0], x1 = s->x[1], x2 = s->x[2], x3 = s->x[3], x4 = s->x[4];
  uint64_t t0, t1, t2, t3, t4;
  /* tur sabiti */
  x2 ^= C;
  /* S-box (bit-dilimli) */
  x0 ^= x4; x4 ^= x3; x2 ^= x1;
  t0 = x0 ^ (~x1 & x2);
  t1 = x1 ^ (~x2 & x3);
  t2 = x2 ^ (~x3 & x4);
  t3 = x3 ^ (~x4 & x0);
  t4 = x4 ^ (~x0 & x1);
  t1 ^= t0; t0 ^= t4; t3 ^= t2; t2 = ~t2;
  /* lineer difüzyon */
  s->x[0] = t0 ^ ascon_ror(t0, 19) ^ ascon_ror(t0, 28);
  s->x[1] = t1 ^ ascon_ror(t1, 61) ^ ascon_ror(t1, 39);
  s->x[2] = t2 ^ ascon_ror(t2,  1) ^ ascon_ror(t2,  6);
  s->x[3] = t3 ^ ascon_ror(t3, 10) ^ ascon_ror(t3, 17);
  s->x[4] = t4 ^ ascon_ror(t4,  7) ^ ascon_ror(t4, 41);
}

/* 'rounds' turluk permütasyon (12 veya 6) */
static inline void ascon_p(ascon_state_t* s, int rounds) {
  for (int i = 12 - rounds; i < 12; i++) ascon_round(s, ascon_rc[i]);
}

/*
 * Ascon-128 AEAD şifreleme.
 *   c   : çıktı şifreli veri (mlen bayt yer ayır)
 *   tag : çıktı 16 baytlık doğrulama etiketi
 *   m   : düz veri, mlen bayt
 *   ad  : ilişkili veri (AAD), adlen bayt
 *   npub: 16 baytlık nonce
 *   k   : 16 baytlık anahtar
 */
static inline void ascon128_encrypt(uint8_t* c, uint8_t* tag,
                                    const uint8_t* m, size_t mlen,
                                    const uint8_t* ad, size_t adlen,
                                    const uint8_t* npub, const uint8_t* k) {
  const uint64_t IV = 0x80400c0600000000ULL;
  uint64_t K0 = ascon_load_be(k, 8),     K1 = ascon_load_be(k + 8, 8);
  uint64_t N0 = ascon_load_be(npub, 8),  N1 = ascon_load_be(npub + 8, 8);

  ascon_state_t s;
  /* Başlatma */
  s.x[0] = IV; s.x[1] = K0; s.x[2] = K1; s.x[3] = N0; s.x[4] = N1;
  ascon_p(&s, 12);
  s.x[3] ^= K0; s.x[4] ^= K1;

  /* İlişkili veri */
  if (adlen) {
    while (adlen >= 8) {
      s.x[0] ^= ascon_load_be(ad, 8);
      ascon_p(&s, 6);
      ad += 8; adlen -= 8;
    }
    s.x[0] ^= ascon_load_be(ad, adlen);
    s.x[0] ^= (0x80ULL << (56 - 8 * adlen));   /* dolgu biti */
    ascon_p(&s, 6);
  }
  s.x[4] ^= 1;   /* alan ayrımı (domain separation) */

  /* Düz veri -> şifreli veri */
  while (mlen >= 8) {
    s.x[0] ^= ascon_load_be(m, 8);
    ascon_store_be(c, s.x[0], 8);
    ascon_p(&s, 6);
    m += 8; c += 8; mlen -= 8;
  }
  s.x[0] ^= ascon_load_be(m, mlen);
  ascon_store_be(c, s.x[0], mlen);
  s.x[0] ^= (0x80ULL << (56 - 8 * mlen));       /* son blok dolgusu */

  /* Sonlandırma */
  s.x[1] ^= K0; s.x[2] ^= K1;
  ascon_p(&s, 12);
  ascon_store_be(tag,     s.x[3] ^ K0, 8);
  ascon_store_be(tag + 8, s.x[4] ^ K1, 8);
}

#endif /* ASCON_H */
