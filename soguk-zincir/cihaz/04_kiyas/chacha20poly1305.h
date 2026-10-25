/*
 * chacha20poly1305.h — ChaCha20-Poly1305 AEAD (tek başlık, taşınabilir C)
 * -----------------------------------------------------------------------
 * RFC 8439. ESP32 Arduino çekirdeğinin mbedTLS'inde ChaChaPoly derlenmemiş
 * halde geldiği için (linker "undefined reference" verir), referans
 * algoritmayı buraya sade biçimde yazdık.
 *
 * Python 'cryptography' kütüphanesinin ChaCha20Poly1305 çıktısıyla
 * (aynı anahtar/nonce/AAD/veri) BİREBİR aynı şifreli+tag üretecek şekilde
 * test edildi. Poly1305 "donna" 32-bit yaklaşımıyla yazıldı (ESP32'de
 * __int128 olmadığı için 26-bitlik uzuvlar kullanılır).
 *
 * Kullanım:
 *   uint8_t c[mlen], tag[16];
 *   chacha20poly1305_encrypt(c, tag, m, mlen, ad, adlen, nonce12, key32);
 */
#ifndef CHACHA20POLY1305_H
#define CHACHA20POLY1305_H

#include <stdint.h>
#include <stddef.h>
#include <string.h>

/* ---------- yardımcılar ---------- */
static inline uint32_t cc_u8to32le(const uint8_t* p) {
  return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}
static inline void cc_u32to8le(uint8_t* p, uint32_t v) {
  p[0] = (uint8_t)v; p[1] = (uint8_t)(v >> 8); p[2] = (uint8_t)(v >> 16); p[3] = (uint8_t)(v >> 24);
}
static inline uint32_t cc_rotl(uint32_t x, int n) { return (x << n) | (x >> (32 - n)); }

/* ---------- ChaCha20 ---------- */
#define CC_QR(a,b,c,d) \
  a += b; d ^= a; d = cc_rotl(d,16); \
  c += d; b ^= c; b = cc_rotl(b,12); \
  a += b; d ^= a; d = cc_rotl(d, 8); \
  c += d; b ^= c; b = cc_rotl(b, 7);

static inline void cc_chacha20_block(uint8_t out[64], const uint8_t key[32],
                                     uint32_t counter, const uint8_t nonce[12]) {
  uint32_t s[16], x[16];
  s[0] = 0x61707865; s[1] = 0x3320646e; s[2] = 0x79622d32; s[3] = 0x6b206574;
  for (int i = 0; i < 8; i++) s[4 + i] = cc_u8to32le(key + 4 * i);
  s[12] = counter;
  s[13] = cc_u8to32le(nonce + 0);
  s[14] = cc_u8to32le(nonce + 4);
  s[15] = cc_u8to32le(nonce + 8);
  memcpy(x, s, sizeof(s));
  for (int i = 0; i < 10; i++) {
    CC_QR(x[0], x[4], x[ 8], x[12]);
    CC_QR(x[1], x[5], x[ 9], x[13]);
    CC_QR(x[2], x[6], x[10], x[14]);
    CC_QR(x[3], x[7], x[11], x[15]);
    CC_QR(x[0], x[5], x[10], x[15]);
    CC_QR(x[1], x[6], x[11], x[12]);
    CC_QR(x[2], x[7], x[ 8], x[13]);
    CC_QR(x[3], x[4], x[ 9], x[14]);
  }
  for (int i = 0; i < 16; i++) cc_u32to8le(out + 4 * i, x[i] + s[i]);
}

/* veriyi ChaCha20 akışıyla XOR'la (counter'dan başlar) */
static inline void cc_chacha20_xor(uint8_t* out, const uint8_t* in, size_t len,
                                   const uint8_t key[32], uint32_t counter, const uint8_t nonce[12]) {
  uint8_t blk[64];
  size_t off = 0;
  while (len > 0) {
    cc_chacha20_block(blk, key, counter++, nonce);
    size_t n = len < 64 ? len : 64;
    for (size_t i = 0; i < n; i++) out[off + i] = in[off + i] ^ blk[i];
    off += n; len -= n;
  }
}

/* ---------- Poly1305 (donna 32-bit, tek seferlik) ---------- */
static inline void cc_poly1305(uint8_t mac[16], const uint8_t* m, size_t bytes, const uint8_t key[32]) {
  uint32_t r0, r1, r2, r3, r4, s1, s2, s3, s4;
  uint32_t h0 = 0, h1 = 0, h2 = 0, h3 = 0, h4 = 0;
  uint32_t t0, t1, t2, t3, c;
  uint64_t d0, d1, d2, d3, d4;

  t0 = cc_u8to32le(key + 0); t1 = cc_u8to32le(key + 4);
  t2 = cc_u8to32le(key + 8); t3 = cc_u8to32le(key + 12);
  r0 = t0 & 0x3ffffff; t0 = (t0 >> 26) | (t1 << 6);
  r1 = t0 & 0x3ffff03; t1 = (t1 >> 20) | (t2 << 12);
  r2 = t1 & 0x3ffc0ff; t2 = (t2 >> 14) | (t3 << 18);
  r3 = t2 & 0x3f03fff; t3 = (t3 >> 8);
  r4 = t3 & 0x00fffff;
  s1 = r1 * 5; s2 = r2 * 5; s3 = r3 * 5; s4 = r4 * 5;

  uint8_t buf[16];
  const uint8_t* p = m;
  size_t left = bytes;
  while (left > 0) {
    uint32_t hibit;
    const uint8_t* blk;
    if (left >= 16) { blk = p; hibit = (1UL << 24); }
    else { memset(buf, 0, 16); memcpy(buf, p, left); buf[left] = 1; blk = buf; hibit = 0; }

    t0 = cc_u8to32le(blk + 0); t1 = cc_u8to32le(blk + 4);
    t2 = cc_u8to32le(blk + 8); t3 = cc_u8to32le(blk + 12);
    h0 += t0 & 0x3ffffff;
    h1 += (uint32_t)((((uint64_t)t1 << 32) | t0) >> 26) & 0x3ffffff;
    h2 += (uint32_t)((((uint64_t)t2 << 32) | t1) >> 20) & 0x3ffffff;
    h3 += (uint32_t)((((uint64_t)t3 << 32) | t2) >> 14) & 0x3ffffff;
    h4 += (t3 >> 8) | hibit;

    d0 = (uint64_t)h0*r0 + (uint64_t)h1*s4 + (uint64_t)h2*s3 + (uint64_t)h3*s2 + (uint64_t)h4*s1;
    d1 = (uint64_t)h0*r1 + (uint64_t)h1*r0 + (uint64_t)h2*s4 + (uint64_t)h3*s3 + (uint64_t)h4*s2;
    d2 = (uint64_t)h0*r2 + (uint64_t)h1*r1 + (uint64_t)h2*r0 + (uint64_t)h3*s4 + (uint64_t)h4*s3;
    d3 = (uint64_t)h0*r3 + (uint64_t)h1*r2 + (uint64_t)h2*r1 + (uint64_t)h3*r0 + (uint64_t)h4*s4;
    d4 = (uint64_t)h0*r4 + (uint64_t)h1*r3 + (uint64_t)h2*r2 + (uint64_t)h3*r1 + (uint64_t)h4*r0;

    c = (uint32_t)(d0 >> 26); h0 = (uint32_t)d0 & 0x3ffffff;
    d1 += c; c = (uint32_t)(d1 >> 26); h1 = (uint32_t)d1 & 0x3ffffff;
    d2 += c; c = (uint32_t)(d2 >> 26); h2 = (uint32_t)d2 & 0x3ffffff;
    d3 += c; c = (uint32_t)(d3 >> 26); h3 = (uint32_t)d3 & 0x3ffffff;
    d4 += c; c = (uint32_t)(d4 >> 26); h4 = (uint32_t)d4 & 0x3ffffff;
    h0 += c * 5; c = h0 >> 26; h0 = h0 & 0x3ffffff;
    h1 += c;

    if (left >= 16) { p += 16; left -= 16; } else { left = 0; }
  }

  /* tam taşıma */
  c = h1 >> 26; h1 &= 0x3ffffff; h2 += c;
  c = h2 >> 26; h2 &= 0x3ffffff; h3 += c;
  c = h3 >> 26; h3 &= 0x3ffffff; h4 += c;
  c = h4 >> 26; h4 &= 0x3ffffff; h0 += c * 5;
  c = h0 >> 26; h0 &= 0x3ffffff; h1 += c;

  /* h + -p ile indirgeme */
  uint32_t g0, g1, g2, g3, g4;
  g0 = h0 + 5; c = g0 >> 26; g0 &= 0x3ffffff;
  g1 = h1 + c; c = g1 >> 26; g1 &= 0x3ffffff;
  g2 = h2 + c; c = g2 >> 26; g2 &= 0x3ffffff;
  g3 = h3 + c; c = g3 >> 26; g3 &= 0x3ffffff;
  g4 = h4 + c - (1UL << 26);

  uint32_t mask = (g4 >> 31) - 1;
  h0 = (h0 & ~mask) | (g0 & mask);
  h1 = (h1 & ~mask) | (g1 & mask);
  h2 = (h2 & ~mask) | (g2 & mask);
  h3 = (h3 & ~mask) | (g3 & mask);
  h4 = (h4 & ~mask) | (g4 & mask);

  /* 130-bit -> 128-bit */
  h0 = (h0 | (h1 << 26));
  h1 = ((h1 >> 6)  | (h2 << 20));
  h2 = ((h2 >> 12) | (h3 << 14));
  h3 = ((h3 >> 18) | (h4 << 8));

  /* mac = (h + s) mod 2^128 */
  uint64_t f;
  f = (uint64_t)h0 + cc_u8to32le(key + 16);             h0 = (uint32_t)f;
  f = (uint64_t)h1 + cc_u8to32le(key + 20) + (f >> 32); h1 = (uint32_t)f;
  f = (uint64_t)h2 + cc_u8to32le(key + 24) + (f >> 32); h2 = (uint32_t)f;
  f = (uint64_t)h3 + cc_u8to32le(key + 28) + (f >> 32); h3 = (uint32_t)f;

  cc_u32to8le(mac + 0, h0); cc_u32to8le(mac + 4, h1);
  cc_u32to8le(mac + 8, h2); cc_u32to8le(mac + 12, h3);
}

/* ---------- AEAD (RFC 8439) ---------- */
/* c: mlen bayt şifreli; tag: 16 bayt. Bu projede veri küçük (<~1KB). */
static inline void chacha20poly1305_encrypt(uint8_t* c, uint8_t* tag,
    const uint8_t* m, size_t mlen,
    const uint8_t* ad, size_t adlen,
    const uint8_t* nonce12, const uint8_t* key32) {
  /* Poly1305 anahtarı: counter=0 bloğunun ilk 32 baytı */
  uint8_t polyblock[64];
  cc_chacha20_block(polyblock, key32, 0, nonce12);

  /* Şifrele: counter=1'den başla */
  cc_chacha20_xor(c, m, mlen, key32, 1, nonce12);

  /* MAC verisi: ad || pad16 || c || pad16 || le64(adlen) || le64(mlen) */
  uint8_t macdata[1088];   /* bu proje için fazlasıyla yeterli */
  size_t pos = 0;
  size_t adpad = (16 - (adlen % 16)) % 16;
  size_t cpad  = (16 - (mlen  % 16)) % 16;
  if (adlen + adpad + mlen + cpad + 16 > sizeof(macdata)) return;  /* güvenlik sınırı */

  memcpy(macdata + pos, ad, adlen);          pos += adlen;
  memset(macdata + pos, 0, adpad);           pos += adpad;
  memcpy(macdata + pos, c, mlen);            pos += mlen;
  memset(macdata + pos, 0, cpad);            pos += cpad;
  uint64_t a64 = adlen, c64 = mlen;
  for (int i = 0; i < 8; i++) macdata[pos++] = (uint8_t)(a64 >> (8 * i));
  for (int i = 0; i < 8; i++) macdata[pos++] = (uint8_t)(c64 >> (8 * i));

  cc_poly1305(tag, macdata, pos, polyblock);
}

#endif /* CHACHA20POLY1305_H */
