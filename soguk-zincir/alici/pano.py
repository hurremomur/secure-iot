"""
pano.py — Soğuk Zincir İzleme Panosu (web dashboard)
=====================================================
alici.py'nin SQLite veritabanını (soguk_zincir.db) okuyup tarayıcıda
CANLI gösterir: güncel sıcaklık, soğuk zincir durumu, sıcaklık-zaman
grafiği, son olaylar ve şifreleme tekniklerinin karşılaştırması.

Neden ayrı bir program?
    - alici.py cihazdan/simülasyondan gelen veriyi çözer, doğrular ve
      veritabanına yazar (ÜRETEN taraf).
    - pano.py sadece o veritabanını OKUR ve gösterir (TÜKETEN taraf).
    Böylece ikisi birbirini bozmadan aynı anda çalışabilir: yarın cihaz
    bağlanınca alici.py gerçek veriyi yazar, pano.py onu canlı gösterir.
    Kod değişmez — sadece veritabanı dolar.

Ek kütüphane GEREKMEZ (Python'ın kendi http.server ve sqlite3'ü yeter).

Çalıştırma:
    1) (Bir terminalde) veritabanını doldur:   python alici.py
    2) (Aynı/başka terminalde) panoyu başlat:   python pano.py
    3) Tarayıcıda aç:                           http://localhost:8000

Grafik/tablolar her 2 saniyede bir kendini yeniler; alici.py yeni kayıt
ekledikçe pano güncellenir.
"""

import json
import sqlite3
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

VERITABANI = "soguk_zincir.db"      # alici.py ile aynı dosya
BENCHMARK = "benchmark_sonuc.json"  # benchmark.py üretir (varsa gösterilir)
PORT = 8000

# Soğuk zincir güvenli aralığı (paket.py ile aynı olmalı)
SICAKLIK_MIN = 2.0
SICAKLIK_MAX = 8.0


# ---------------------------------------------------------------------------
# Veri okuma — veritabanından panonun ihtiyacı olan her şeyi toplar
# ---------------------------------------------------------------------------
def veriyi_topla():
    """Veritabanını (ve varsa benchmark dosyasını) okuyup tek bir sözlük döndürür."""
    veri = {
        "baglandi": False,     # veritabanı açıldı mı
        "guncel": None,        # en son ölçüm
        "olcumler": [],        # son N ölçüm (grafik için)
        "olaylar": [],         # son olaylar (ihlal/sahte paket)
        "sayilar": {"toplam": 0, "ok": 0, "uyari": 0, "bozuldu": 0, "red": 0},
        "benchmark": [],       # teknik karşılaştırması (varsa)
        "aralik": {"min": SICAKLIK_MIN, "max": SICAKLIK_MAX},
    }

    try:
        db = sqlite3.connect(VERITABANI)
        db.row_factory = sqlite3.Row
    except sqlite3.Error:
        return veri  # veritabanı yoksa boş pano göster

    try:
        # Tablolar var mı? (alici.py hiç çalışmadıysa olmayabilir)
        tablolar = {r[0] for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}

        if "olcumler" in tablolar:
            veri["baglandi"] = True

            # Son 60 ölçüm (grafik + güncel değer için) — eskiden yeniye sıralı
            satirlar = db.execute(
                "SELECT zaman,sicaklik,nem,kapak,sayac,durum "
                "FROM olcumler ORDER BY id DESC LIMIT 60").fetchall()
            satirlar = list(reversed(satirlar))
            veri["olcumler"] = [dict(r) for r in satirlar]

            if satirlar:
                veri["guncel"] = dict(satirlar[-1])

            # Durum sayıları (tüm kayıtlar üzerinden)
            for durum, adet in db.execute(
                    "SELECT durum, COUNT(*) FROM olcumler GROUP BY durum"):
                veri["sayilar"]["toplam"] += adet
                anahtar = {"OK": "ok", "UYARI": "uyari",
                           "BOZULDU": "bozuldu"}.get(durum)
                if anahtar:
                    veri["sayilar"][anahtar] += adet

        if "olaylar" in tablolar:
            olaylar = db.execute(
                "SELECT zaman,tur,aciklama FROM olaylar "
                "ORDER BY id DESC LIMIT 15").fetchall()
            veri["olaylar"] = [dict(r) for r in olaylar]
            # Reddedilen (sahte/replay) paket sayısı
            red = db.execute(
                "SELECT COUNT(*) FROM olaylar "
                "WHERE tur IN ('manipulasyon','replay')").fetchone()
            veri["sayilar"]["red"] = red[0] if red else 0
    except sqlite3.Error:
        pass
    finally:
        db.close()

    # Benchmark sonucu (opsiyonel)
    try:
        with open(BENCHMARK, encoding="utf-8") as f:
            veri["benchmark"] = json.load(f)
    except (OSError, json.JSONDecodeError):
        pass

    return veri


# ---------------------------------------------------------------------------
# HTML sayfası — tarayıcıya gönderilir, /veri'yi yoklayıp kendini yeniler
# ---------------------------------------------------------------------------
SAYFA = r"""<!doctype html>
<html lang="tr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Soğuk Zincir İzleme Panosu</title>
<style>
  :root{
    --bg:#0e1420; --panel:#161e2e; --panel2:#1c2740; --cizgi:#283347;
    --metin:#e8edf5; --soluk:#8da2c0; --mavi:#4b9fff;
    --ok:#2fd27e; --uyari:#f5b445; --bozuk:#ff5c6c; --red:#b06bff;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--metin);
    font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
    -webkit-font-smoothing:antialiased}
  .kap{max-width:1100px;margin:0 auto;padding:20px 16px 48px}
  header{display:flex;align-items:baseline;justify-content:space-between;
    flex-wrap:wrap;gap:8px;margin-bottom:18px}
  h1{font-size:20px;margin:0;font-weight:650;letter-spacing:.2px}
  .alt{color:var(--soluk);font-size:13px}
  .nokta{display:inline-block;width:8px;height:8px;border-radius:50%;
    background:var(--ok);margin-right:6px;vertical-align:middle}
  .nokta.kopuk{background:var(--soluk)}

  .izgara{display:grid;gap:14px}
  .ust{grid-template-columns:1.3fr 1fr 1fr}
  .orta{grid-template-columns:1fr}
  .alt2{grid-template-columns:1fr 1fr;margin-top:14px}
  @media(max-width:760px){.ust,.alt2{grid-template-columns:1fr}}

  .kart{background:var(--panel);border:1px solid var(--cizgi);
    border-radius:14px;padding:16px 18px}
  .baslik{font-size:12px;text-transform:uppercase;letter-spacing:.6px;
    color:var(--soluk);margin:0 0 12px}

  .sic{font-size:52px;font-weight:700;line-height:1;letter-spacing:-1px}
  .sic small{font-size:22px;font-weight:600;color:var(--soluk)}
  .rozet{display:inline-block;margin-top:12px;padding:5px 12px;border-radius:999px;
    font-size:13px;font-weight:650}
  .r-ok{background:rgba(47,210,126,.15);color:var(--ok)}
  .r-uyari{background:rgba(245,180,69,.15);color:var(--uyari)}
  .r-bozuk{background:rgba(255,92,108,.15);color:var(--bozuk)}
  .r-yok{background:var(--panel2);color:var(--soluk)}
  .satir{display:flex;justify-content:space-between;padding:7px 0;
    border-bottom:1px solid var(--cizgi);font-size:14px}
  .satir:last-child{border-bottom:none}
  .satir .d{color:var(--soluk)}

  .sayi{font-size:30px;font-weight:700}
  .say-izgara{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}
  .say-kutu{background:var(--panel2);border-radius:10px;padding:12px;text-align:center}
  .say-kutu .e{font-size:11px;color:var(--soluk);text-transform:uppercase;
    letter-spacing:.5px;margin-top:4px}

  canvas{width:100%;height:260px;display:block}

  ul{list-style:none;margin:0;padding:0;max-height:260px;overflow:auto}
  li{display:flex;gap:10px;align-items:flex-start;padding:9px 0;
    border-bottom:1px solid var(--cizgi);font-size:13px}
  li:last-child{border-bottom:none}
  .et{flex:0 0 auto;font-size:11px;font-weight:700;padding:2px 8px;border-radius:6px;
    text-transform:uppercase;letter-spacing:.4px}
  .e-bozuldu{background:rgba(255,92,108,.15);color:var(--bozuk)}
  .e-uyari{background:rgba(245,180,69,.15);color:var(--uyari)}
  .e-red{background:rgba(176,107,255,.15);color:var(--red)}
  .bos{color:var(--soluk);font-size:14px;padding:18px 0;text-align:center}

  table{width:100%;border-collapse:collapse;font-size:13px}
  th,td{text-align:right;padding:8px 6px;border-bottom:1px solid var(--cizgi)}
  th:first-child,td:first-child{text-align:left}
  th{color:var(--soluk);font-weight:600;font-size:11px;text-transform:uppercase;
    letter-spacing:.4px}
  .aead-e{color:var(--ok)}  .aead-h{color:var(--bozuk)}
  .uyari-kutu{background:rgba(245,180,69,.1);border:1px solid rgba(245,180,69,.3);
    color:var(--uyari);border-radius:10px;padding:12px 14px;font-size:13px;margin-bottom:14px}
</style>
</head>
<body>
<div class="kap">
  <header>
    <div>
      <h1>Soğuk Zincir İzleme Panosu</h1>
      <div class="alt">Uçtan uca şifreli sıcaklık takibi · ESP32</div>
    </div>
    <div class="alt"><span id="nokta" class="nokta kopuk"></span><span id="durumYazi">bağlanıyor…</span></div>
  </header>

  <div id="uyari"></div>

  <div class="izgara ust">
    <div class="kart">
      <p class="baslik">Güncel Sıcaklık</p>
      <div><span id="sicaklik" class="sic">–<small>°C</small></span></div>
      <div id="rozet" class="rozet r-yok">veri yok</div>
    </div>
    <div class="kart">
      <p class="baslik">Son Ölçüm</p>
      <div class="satir"><span class="d">Nem</span><span id="nem">–</span></div>
      <div class="satir"><span class="d">Kapak</span><span id="kapak">–</span></div>
      <div class="satir"><span class="d">Sayaç (n)</span><span id="sayac">–</span></div>
      <div class="satir"><span class="d">Güvenli aralık</span><span id="aralik">–</span></div>
    </div>
    <div class="kart">
      <p class="baslik">Özet</p>
      <div class="say-izgara">
        <div class="say-kutu"><div class="sayi" id="s-toplam">0</div><div class="e">Ölçüm</div></div>
        <div class="say-kutu"><div class="sayi" style="color:var(--ok)" id="s-ok">0</div><div class="e">Güvenli</div></div>
        <div class="say-kutu"><div class="sayi" style="color:var(--bozuk)" id="s-bozuldu">0</div><div class="e">Bozuldu</div></div>
        <div class="say-kutu"><div class="sayi" style="color:var(--red)" id="s-red">0</div><div class="e">Reddedildi</div></div>
      </div>
    </div>
  </div>

  <div class="izgara orta" style="margin-top:14px">
    <div class="kart">
      <p class="baslik">Sıcaklık — Zaman (son ölçümler)</p>
      <canvas id="grafik"></canvas>
    </div>
  </div>

  <div class="izgara alt2">
    <div class="kart">
      <p class="baslik">Son Olaylar</p>
      <ul id="olaylar"><li class="bos">Henüz olay yok.</li></ul>
    </div>
    <div class="kart">
      <p class="baslik">Şifreleme Tekniği Karşılaştırması</p>
      <div id="benchmark"><div class="bos">benchmark.py çalıştırılmadı.<br>
        <span style="font-size:12px">(python benchmark.py)</span></div></div>
    </div>
  </div>
</div>

<script>
// Durum -> renk/metin eşlemesi
const ROZET = {
  OK:      ["r-ok",    "GÜVENLİ"],
  UYARI:   ["r-uyari", "UYARI (kapak açık)"],
  BOZULDU: ["r-bozuk", "SOĞUK ZİNCİR KIRILDI"],
};

function metin(id, v){ document.getElementById(id).textContent = v; }

async function yenile(){
  let v;
  try{
    const c = await fetch("/veri", {cache:"no-store"});
    v = await c.json();
  }catch(e){
    document.getElementById("nokta").className = "nokta kopuk";
    metin("durumYazi", "pano sunucusuna ulaşılamadı");
    return;
  }

  // Bağlantı göstergesi
  const bagli = v.baglandi && v.guncel;
  document.getElementById("nokta").className = "nokta" + (bagli ? "" : " kopuk");
  metin("durumYazi", bagli ? "canlı · " + new Date().toLocaleTimeString("tr-TR")
                           : "veri bekleniyor (python alici.py)");

  // Uyarı kutusu (veritabanı yok / boş)
  const u = document.getElementById("uyari");
  if(!v.baglandi){
    u.innerHTML = '<div class="uyari-kutu">Veritabanı henüz yok. Bir terminalde '
      + '<b>python alici.py</b> çalıştırın; bu pano otomatik dolacak.</div>';
  }else if(!v.guncel){
    u.innerHTML = '<div class="uyari-kutu">Veritabanı boş. <b>python alici.py</b> '
      + 'ile örnek/gerçek veri ekleyin.</div>';
  }else{ u.innerHTML = ""; }

  metin("aralik", v.aralik.min + "–" + v.aralik.max + " °C");

  // Güncel ölçüm
  const g = v.guncel;
  if(g){
    document.getElementById("sicaklik").innerHTML =
      g.sicaklik.toFixed(1) + '<small>°C</small>';
    metin("nem", "%" + g.nem.toFixed(1));
    metin("kapak", g.kapak ? "açık" : "kapalı");
    metin("sayac", g.sayac);
    const [sinif, yazi] = ROZET[g.durum] || ["r-yok", g.durum || "–"];
    const r = document.getElementById("rozet");
    r.className = "rozet " + sinif;
    r.textContent = yazi;
  }else{
    document.getElementById("sicaklik").innerHTML = '–<small>°C</small>';
    const r = document.getElementById("rozet");
    r.className = "rozet r-yok"; r.textContent = "veri yok";
  }

  // Sayılar
  metin("s-toplam",  v.sayilar.toplam);
  metin("s-ok",      v.sayilar.ok);
  metin("s-bozuldu", v.sayilar.bozuldu);
  metin("s-red",     v.sayilar.red);

  // Olaylar
  const ol = document.getElementById("olaylar");
  if(v.olaylar.length === 0){
    ol.innerHTML = '<li class="bos">Henüz olay yok.</li>';
  }else{
    const et = {bozuldu:["e-bozuldu","BOZULDU"], uyari:["e-uyari","UYARI"],
                manipulasyon:["e-red","SAHTE"], replay:["e-red","REPLAY"]};
    ol.innerHTML = v.olaylar.map(o=>{
      const [s,y] = et[o.tur] || ["e-uyari", (o.tur||"").toUpperCase()];
      const z = o.zaman ? new Date(o.zaman*1000).toLocaleTimeString("tr-TR") : "";
      return `<li><span class="et ${s}">${y}</span><span>${o.aciklama||""}`
           + `<div class="d" style="color:var(--soluk);font-size:11px">${z}</div></span></li>`;
    }).join("");
  }

  // Benchmark tablosu (benchmark.py'nin ürettiği alanlar)
  const b = document.getElementById("benchmark");
  if(v.benchmark && v.benchmark.length){
    const u = '<span style="text-transform:none">(µs)</span>';
    let t = '<table><tr><th>Teknik</th><th>AEAD</th><th>Şifre '+u+'</th>'
          + '<th>Çöz '+u+'</th><th>Boyut</th><th>Ek yük</th></tr>';
    for(const r of v.benchmark){
      const aead = r.dogrulamali ? '<span class="aead-e">evet</span>'
                                 : '<span class="aead-h">hayır</span>';
      const n = (x)=> (typeof x === "number") ? x.toFixed(2) : "–";
      t += `<tr><td>${r.ad}</td><td>${aead}</td>`
         + `<td>${n(r.sifre_us)}</td><td>${n(r.coz_us)}</td>`
         + `<td>${r.boyut ?? "–"}</td><td>${r.ek_yuk ?? "–"} B</td></tr>`;
    }
    t += '</table>';
    t += '<div class="d" style="color:var(--soluk);font-size:11px;margin-top:10px">'
       + 'PC referans ölçümü (AES-NI nedeniyle AES avantajlı görünür). '
       + 'Asıl karşılaştırma ESP32 üzerinde yapılacak.</div>';
    b.innerHTML = t;
  }

  // Grafik
  grafikCiz(v);
}

// --- Basit sıcaklık-zaman grafiği (canvas, kütüphanesiz) ---
function grafikCiz(v){
  const c = document.getElementById("grafik");
  const dpr = window.devicePixelRatio || 1;
  const G = c.getContext("2d");
  const W = c.clientWidth, H = c.clientHeight;
  c.width = W*dpr; c.height = H*dpr; G.scale(dpr,dpr);
  G.clearRect(0,0,W,H);

  const d = v.olcumler;
  const pad = {l:38, r:12, t:12, b:22};
  const gw = W - pad.l - pad.r, gh = H - pad.t - pad.b;

  // Y ekseni aralığı: veriye + güvenli banda göre
  let min = v.aralik.min, max = v.aralik.max;
  for(const o of d){ min = Math.min(min,o.sicaklik); max = Math.max(max,o.sicaklik); }
  min = Math.floor(min-1); max = Math.ceil(max+1);
  if(max-min < 4){ max = min+4; }

  const x = i => pad.l + (d.length<=1 ? gw/2 : gw*i/(d.length-1));
  const y = t => pad.t + gh*(1-(t-min)/(max-min));

  // Güvenli bant (2–8 °C) — yeşil şerit
  G.fillStyle = "rgba(47,210,126,.10)";
  const yb = y(v.aralik.max), yt = y(v.aralik.min);
  G.fillRect(pad.l, yb, gw, yt-yb);

  // Izgara + Y etiketleri
  G.strokeStyle = "#283347"; G.fillStyle = "#8da2c0";
  G.font = "11px system-ui"; G.textAlign = "right"; G.textBaseline = "middle";
  const adim = Math.max(1, Math.round((max-min)/4));
  for(let t=min; t<=max; t+=adim){
    const yy = y(t);
    G.beginPath(); G.moveTo(pad.l,yy); G.lineTo(W-pad.r,yy); G.stroke();
    G.fillText(t+"°", pad.l-6, yy);
  }

  if(d.length === 0){
    G.fillStyle = "#8da2c0"; G.textAlign = "center"; G.font = "13px system-ui";
    G.fillText("veri bekleniyor…", W/2, H/2);
    return;
  }

  // Sıcaklık çizgisi
  G.strokeStyle = "#4b9fff"; G.lineWidth = 2; G.beginPath();
  d.forEach((o,i)=>{ const px=x(i), py=y(o.sicaklik);
    i ? G.lineTo(px,py) : G.moveTo(px,py); });
  G.stroke();

  // Noktalar (duruma göre renk)
  const renk = {OK:"#2fd27e", UYARI:"#f5b445", BOZULDU:"#ff5c6c"};
  d.forEach((o,i)=>{
    G.fillStyle = renk[o.durum] || "#4b9fff";
    G.beginPath(); G.arc(x(i), y(o.sicaklik), 3.2, 0, 7); G.fill();
  });
}

yenile();
setInterval(yenile, 2000);
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Küçük HTTP sunucusu
# ---------------------------------------------------------------------------
class Isleyici(BaseHTTPRequestHandler):
    def _gonder(self, icerik, tur="text/html; charset=utf-8", kod=200):
        gov = icerik.encode("utf-8") if isinstance(icerik, str) else icerik
        self.send_response(kod)
        self.send_header("Content-Type", tur)
        self.send_header("Content-Length", str(len(gov)))
        self.end_headers()
        self.wfile.write(gov)

    def do_GET(self):
        if self.path == "/" or self.path.startswith("/index"):
            self._gonder(SAYFA)
        elif self.path.startswith("/veri"):
            self._gonder(json.dumps(veriyi_topla()),
                         tur="application/json; charset=utf-8")
        else:
            self._gonder("bulunamadı", kod=404)

    def log_message(self, *a):  # terminali log'la doldurma
        pass


def main():
    adres = ("127.0.0.1", PORT)
    sunucu = ThreadingHTTPServer(adres, Isleyici)
    url = f"http://localhost:{PORT}"
    print("Soğuk Zincir İzleme Panosu çalışıyor.")
    print(f"  Tarayıcıda aç:  {url}")
    print("  Veri kaynağı :  soguk_zincir.db  (python alici.py ile doldurulur)")
    print("  Durdurmak için: Ctrl+C\n")
    try:
        webbrowser.open(url)   # tarayıcıyı otomatik aç (açılmazsa elle aç)
    except Exception:
        pass
    try:
        sunucu.serve_forever()
    except KeyboardInterrupt:
        print("\nPano kapatıldı.")
        sunucu.shutdown()


if __name__ == "__main__":
    main()
