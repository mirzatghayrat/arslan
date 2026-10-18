<div align="center">

<a href="https://aralem.dev/arslan/">
  <img src="docs/assets/readme/banner.jpg" alt="Arslan — işi yapar, harekete geçmeden önce sorar. Mac'in çentiğindeki Arslan Island, dosyaları taşımak için onay bekliyor." width="100%">
</a>

<br/><br/>

**Mac'inde yaşayan — ve iPhone'unu dinleyen — açık kaynaklı bir yapay zekâ ajanı.**<br/>
**Terminalini ve uygulamalarını kullanır, sen konuşurken çalışmaya devam eder.**<br/>
**Senin adına yapılan her şey *senin* tıklamanı bekler.**

<br/>

[![Release](https://img.shields.io/github/v/release/mirzatghayrat/arslan?style=flat-square&color=34d399&label=release)](https://github.com/mirzatghayrat/arslan/releases/latest)
[![License](https://img.shields.io/badge/license-Apache--2.0-4c72e0?style=flat-square)](LICENSE)
[![Platform](https://img.shields.io/badge/macOS_11+-Apple_Silicon-111?style=flat-square)](README.md#status--honest-about-whats-proven)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-2ea44f?style=flat-square)](CONTRIBUTING.md)

<br/>

<a href="https://github.com/mirzatghayrat/arslan/releases/latest/download/Arslan-macos-arm64.dmg"><img src="docs/assets/btn/tr-download.png" alt="macOS için indir" height="28"></a>&nbsp;&nbsp;<a href="https://aralem.dev/arslan/"><img src="docs/assets/btn/tr-website.png" alt="Web sitesi" height="28"></a>&nbsp;&nbsp;<a href="docs/QUICKSTART.md"><img src="docs/assets/btn/tr-quickstart.png" alt="Hızlı başlangıç" height="28"></a>&nbsp;&nbsp;<a href="SECURITY.md"><img src="docs/assets/btn/tr-security.png" alt="Güvenlik" height="28"></a>&nbsp;&nbsp;<a href="CONTRIBUTING.md"><img src="docs/assets/btn/tr-contributing.png" alt="Katkıda bulun" height="28"></a>

<a href="README.md"><a href="https://aralem.dev/arslan/docs/"><b>📖 Teknik belgeler</b></a> <sub>(İngilizce · Çince)</sub>

<img src="docs/assets/btn/lang-en.png" alt="English" height="22"></a>&nbsp;<a href="README.zh-CN.md"><img src="docs/assets/btn/lang-zh.png" alt="简体中文" height="22"></a>&nbsp;<a href="README.de.md"><img src="docs/assets/btn/lang-de.png" alt="Deutsch" height="22"></a>&nbsp;<a href="README.ja.md"><img src="docs/assets/btn/lang-ja.png" alt="日本語" height="22"></a>&nbsp;<a href="README.es.md"><img src="docs/assets/btn/lang-es.png" alt="Español" height="22"></a>&nbsp;<img src="docs/assets/btn/lang-tr-on.png" alt="Türkçe" height="22">

</div>

---

<div align="center">
  <img src="docs/assets/readme/island.gif" alt="Arslan — işi yapar, harekete geçmeden önce sorar. Mac'in çentiğindeki Arslan Island, dosyaları taşımak için onay bekliyor." width="760">
  <br/>
  <sub>Çentikte canlı bir arka plan işi: çalışır, dosyalarını taşımadan önce <b>durup sorar</b>, sonra ne bulduğunu söyler.</sub>
</div>

## Ondan şunları isteyebilirsin

> *“Bu yılın faturalarını İndirilenler'den tek bir klasörde topla ve hangi ayların eksik olduğunu söyle.”*<br/>
> *“İndirilenler'de kaç kopya dosya var? Kopyaları Çöp Sepeti'ne taşı, en yenisini tut.”*<br/>
> *“sales_q3.csv dosyasını grafikli tek sayfalık bir rapora dönüştür.”*<br/>
> *“Notlar'da bu toplantının üç maddesiyle bir not oluştur.”*<br/>
> *“Her sabah 9'da bu sayfaya bak, fiyat değiştiyse bana söyle.”*

O çalışırken sen konuşmaya devam edersin. Silen, gönderen, kuran ya da başka bir uygulamaya dokunan her şey **önce sana sorar** — Mac'inde ya da iPhone'unda.

## Bir dakikada başla

1. **[macOS için Arslan'ı indir](https://github.com/mirzatghayrat/arslan/releases/latest/download/Arslan-macos-arm64.dmg)** (Apple Silicon, macOS 11+) — imzalı, noter onaylı, kendini günceller.
2. **Uygulamalar**'a sürükle ve aç.
3. Ayarlar'a bir model API anahtarı yapıştır — OpenAI, Anthropic, Gemini, DeepSeek, Qwen, Kimi, OpenRouter ve diğerleri — ya da **Ollama** ile yerel bir modele bağla.

Bu kadar. Hesap yok, kayıt yok, Arslan sunucusu yok.

## 0.1.62'de yeni — uzun komutlar sonuna kadar çalışır, daha az “kontrolün gerekir”, MCP araçları sohbeti bozamaz

Bir düzeltme sürümü: öğrenilecek yeni bir şey yok, ters giden şeyler artık ters gitmiyor. Bir terminal komutu artık 20 saniyede kesilmek yerine istediği süre kadar çalışıyor (varsayılan 2 dakika, en fazla 10), yanıtın kalan süresini asla aşmıyor ve bir sınır onu durdurduğunda Arslan yine de yazdırdıklarını görüyor. Bir görev “kontrolün gerekir” ile yalnızca bir eylem Mac'inin dışında gerçekten iz bırakmış olabileceğinde bitiyor: yalnızca okuyan bir komut ya da hiç çalışmamış bir eylem artık kontrol istemiyor. Araç açıklamalarını bir sağlayıcının reddettiği bir MCP sunucusu artık her sohbeti bozmuyor: Arslan açıklamaları yeniden biçimlendiriyor ve yine de reddedilen araç yalnızca o yanıt için dışarıda bırakılıyor. Terminaldeki `osascript` ve `shortcuts run` yaygın yazılışlarında her seferinde soruyor, bir dosyayı yazmak da bir bağlantıyı izleyip çalışma klasörünün dışına çıkmıyor. [Tüm sürüm notları →](https://github.com/mirzatghayrat/arslan/releases/tag/v0.1.62)

Son sürümler:
- **[0.1.61](https://github.com/mirzatghayrat/arslan/releases/tag/v0.1.61)** — her yerde tek onay kartı: sohbette, Inbox'ta, Island'da ve iPhone'unda aynı kart; MCP sunucuları kendiliğinden başlıyor; Claude'un en yeni modelleri yine yanıt veriyor.
- **[0.1.60](https://github.com/mirzatghayrat/arslan/releases/tag/v0.1.60)** — Hands v2: üzerinde çalıştığı tek pencerenin görüntüsü, toplu adımlar, birkaç uygulama için tek kart, önü ödünç alma, başka bir masaüstünü ziyaret etme ve ekranı yalnızca senin onayınla devralma.

<div align="center">
  <img src="docs/assets/readme/devices.jpg" alt="Mac'te Arslan — arka planda faturaları toplayan bir iş — ve bekleyen bir onayı gösteren iPhone için Arslan" width="100%">
</div>

<p align="center"><sub>Mac: 0.1.52 tanıtım filminden; arayüz kaynak koddan yeniden kuruldu, sahne kurgudur. iPhone: gerçek bir ekran kaydı. <a href="https://aralem.dev/arslan/#film">▶ Tüm sistem 60 saniyede</a></sub></p>

## Neden Arslan

| | |
|---|---|
| **Tek döngü, her işlem bir kapının ardında** | Bir mesaj tek bir yerel araç çağırma döngüsüne girer. Model önerir; her kabuk komutu çalışmadan önce sabit bir politika fonksiyonu — başka bir model değil — **run**, **ask** ya da **forbid** der. Sonuçlar güvenilmez veri olarak sarılı döner; bir web sayfasına gizlenmiş talimatlar okunur, uygulanmaz. |
| **Sen konuşurken çalışmaya devam eder** | Uzun iş arka plan işine dönüşür ve tur biter. Bir iş **done**, **partial**, **blocked** ya da **stopped** ile biter — asla sessizce değil. Zamanlanmış görevler en sık 15 dakikada bir çalışır (en fazla 10) ve Mac uyurken kaçırılanlar sonradan tekrarlanmaz. |
| **Durum çentikte** | **Arslan Island** ne yaptığını gösterir, sana ihtiyaç olduğunda sorar ve bittiğinde haber verir. Menü çubuğu, bas-konuş ve süren her şey için bir Stop düğmesi. |
| **Eller — varsayılmaz, sorulur** | Arslan Hands ile Mac uygulamaları, Arslan'ın kendi tarayıcısı, Kestirmelerin, AppleScript. Asla bir parola alanına yazmaz; Anahtar Zinciri Erişimi'ne, parola yöneticilerine, Sistem Ayarları'na, macOS güvenlik istemlerine, Bildirim Merkezi'ne ve kendisine asla dokunmaz. |
| **Mac'in cebinde** | iPhone için Arslan (yakında App Store'da) Mac'inle **kendi özel iCloud'un** üzerinden, uçtan uca şifreli konuşur. Aynı onay kartı ikisinde de görünür; ilk cevap geçerlidir. Yanıtsız kalan bir kart 30 dakika bekler ve sürenin dolması bir ret sayılmaz (0.1.61'den itibaren; önceki sürümler 300 saniye sonra reddederdi). |
| **Önce yerel, kendi anahtarınla** | Bellek Mac'indeki SQLite'ta durur; model sağlayıcın yalnızca gönderdiğin turları, senin anahtarınla görür. **Arslan hiçbir sunucu çalıştırmaz.** Bir kez düzelt, o yöntemi hatırlar — Geri Al ile. |
| <img src="docs/assets/icons/shield-check.svg" width="16"> **Kimlik bilgileri senin kalır** | Arslan hesap kimlik bilgilerini asla almaz ya da enjekte etmez. Kimlik doğrulamalı bağlayıcılar (App Store Connect gibi), yalıtılmış bir kimlik bilgisi aracısı güvenlik incelemesinden geçene kadar devre dışıdır — bkz. [W11](docs/companion/W11-security-boundary.md). Sandbox dışında çalıştırmayı onayladığın bir komut kendi yetkilerinle çalışır. |

## Bir tur, baştan sona

<div align="center">
  <img src="docs/assets/readme/loop.jpg" alt="Döngü: Mesaj, Döngü, Politika, Sanal alan, Sonuç — her adım onu uygulayan dosyayı gösterir" width="100%">
</div>

| Adım | Ne olur | Uygulandığı yer |
|---|---|---|
| **Mesaj** | Pencereden, iPhone'undan ya da sesinle — tek sohbet, tek döngü | `server/orchestrator/arslan.py`, `server/services/phone_bridge.py` |
| **Döngü** | Yerel araç çağrıları; planı ana süreç tutar; yarıda kesilen yanıt tahmin yerine devam eder; model çağrısı başına 75 sn | `server/orchestrator/tool_loop.py` |
| **Politika** | `run` · `ask` · `forbid`, komut metninin saf bir fonksiyonu | `server/services/terminal_policy.py` (yıkıcı komut algılama Hermes Agent'tan, MIT) |
| **Sanal alan** | macOS seatbelt: komutlar yalnızca çalışma klasörüne, geçici klasörlere ve önbelleklere yazar; SSH anahtarları, anahtar zinciri ve Arslan'ın verileri kapalı kalır; model anahtarları bir komuta asla ulaşmaz; bir komut varsayılan olarak en fazla 2 dk çalışır (üst sınır 10 dk) | `server/services/command_sandbox.py`, `terminal_exec.py` |
| **Sonuç** | Güvenilmez veri olarak sarılır ve sana ulaşmadan kontrol edilir; hiç yapılmamış işle ilgili iddiaları deterministik bir koruma yakalar | `server/orchestrator/untrusted.py`, `promise_guard.py` |

## Kapı

<div align="center">
  <img src="docs/assets/readme/gate.jpg" alt="Proje sitesindeki kapı: bir komut yaz ve Arslan'ın gerçek cevabını gör — anahtar zinciri parolalarını okumak forbid" width="100%">
</div>

| Cevap | Ne zaman | Örnekler (her biri `terminal_policy.assess()`'in gerçek cevabı) |
|---|---|---|
| **run** | Okuma, listeleme, dönüştürme, derleme, bir sayfa çekme | `ls -la ~/Downloads` · `ffmpeg -i talk.mov talk.mp4` · `npm run build` · `curl -s https://example.com` |
| **ask** | Yıkıcı ya da senin adına dışarıya dönük | `rm -rf build/` · `git push --force` · `curl … \| sh` · `osascript …` · `brew install jq` · `mail -s …` · `scp … mac-mini:` |
| **forbid** | Asla, “bir daha sorma” ile bile | `security find-generic-password … -w` · `cat ~/.arslan/secret_key` · `rm -rf ~` · `sudo …` · `shutdown` |

“Bir daha sorma” komut türüne göre hatırlanır ve Ayarlar › Gelişmiş'te listelenir; forbid kuralları asla hatırlanamaz. Kapı hatalara ve araya sızdırılmış talimatlara karşı korur — kafes değildir: izin verdiğin bir komut senin yetkilerinle çalışır. 64 komutu [proje sitesinde](https://aralem.dev/arslan/#gate) dene.

## Eller, arka plan işleri ve iPhone

<div align="center">
  <img src="docs/assets/readme/hands.jpg" alt="Eller: Arslan Hands ile Mac uygulamaları, tarayıcı, Kestirmeler ve AppleScript; görünür ve durdurulabilir; asla dokunulmayan uygulamalar" width="100%">
</div>

<div align="center">
  <img src="docs/assets/readme/iphone.jpg" alt="Mac ve iPhone: özel iCloud'un üzerinden uçtan uca şifreleme (X25519, HKDF-SHA256, ChaCha20-Poly1305, Ed25519), ilk cevap geçerli, Island'ın yüzü" width="100%">
</div>

iPhone bağlantısında Arslan sunucusu ya da aktarıcı yoktur: mesajlar özel iCloud veritabanındaki bir CloudKit bölgesinden geçer — X25519 anahtar anlaşması, HKDF-SHA256, ChaCha20-Poly1305, Ed25519 imzaları. Teslim edilen mesajlar silinir; geride kalanları Arslan for Mac 7 günden eski olduklarında siler — Mac açık ve çevrimiçiyken yaklaşık günde bir kez kontrol eder, değilse daha sonra.

## Gizlilik

<div align="center">
  <img src="docs/assets/readme/privacy.jpg" alt="Kim neyi görür: bu Mac her şeyi, model sağlayıcın gönderdiğin turları, iCloud şifreli metni ve yönlendirmeyi, Arslan'ın sunucuları hiçbir şeyi — çünkü yoklar" width="100%">
</div>

## Kurulum

Kaynak koddan ya da Docker ile çalıştırmak için (katkıda bulunanlar ve kendi sunucusunda barındıranlar): **[docs/QUICKSTART.md](docs/QUICKSTART.md)**.

Görsellerde ve taranmış PDF'lerde metin tanıma, güvenlik duruşunun tamamı, ortam değişkenleri ve veri yedekleme için [İngilizce README](README.md#install)'ye bak (esas olan İngilizce sürümdür).

## Durum — kanıtlanana dair dürüst

- **Pre-v1.** Şimdilik yalnızca Apple Silicon'da macOS 11+. Sanal alanlar macOS seatbelt'tir; diğer platformlarda üretilen Python reddedilir, kabuk komutları ise sanal alan olmadan çalışır ve bu açıkça belirtilir.
- **Kendi model anahtarın.** Arslan senin hesabınla çalışır; faturayı sağlayıcın keser. Yerel araç taşıma OpenAI uyumlu, Anthropic ve Gemini yolları için uygulanmış ve protokol düzeyinde test edilmiştir — bu her model ya da uç noktanın canlı sertifikası değildir.
- **Hands henüz ekrandaki bir konuma tıklayamıyor ya da sürükleyemiyor.** Başka bir masaüstündeki pencereye kısa bir süre oraya giderek ulaşır (önü ödünç alma açıkken). Bir uygulamanın öne fırladığı ~50 ms içinde basılan tuş o uygulamaya gider ve büyük bir pencerenin (çok notlu Notlar) okunması 10–20 saniye sürebilir.
- **iPhone için Arslan yakında App Store'da.** Mac tarafı 0.1.53 ile geldi.
- **Kendi takvimine göre para harcayan her şey kapalı gelir.** Arka plan bellek düzenleme, yalnızca Ayarlar › Otomasyon'da açarsan modelini çağırır; yine de sağlayıcının fatura panelinde kesin bir sınır koy.
- API'ler, şemalar ve varsayılanlar v1'den önce değişebilir.

## Topluluk

- Bir hata mı buldun ya da bir fikrin mi var? [Issue aç](https://github.com/mirzatghayrat/arslan/issues).
- Yardım etmek mi istiyorsun? [CONTRIBUTING.md](CONTRIBUTING.md) ile başla.
- Proje sitesi [`docs/index.html`](docs/index.html) içinde (GitHub Pages). Bu README'deki görseller o sitenin ekran görüntüleridir.

## Lisans

Apache-2.0. [LICENSE](LICENSE) ve [NOTICE](NOTICE) dosyalarına bak. Hermes Agent (MIT) ve agent-desktop (Apache-2.0, Arslan'ın bir değişikliğini taşıyan bir fork'tan derlenip Arslan Hands içinde dağıtılır) dahil üçüncü taraf bildirimleri [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) içinde. Simgeler: [Lucide](https://lucide.dev) (ISC).

---

<div align="center">
<sub>Arslan sana hitap ediyorsa, <a href="https://github.com/mirzatghayrat/arslan/stargazers">bir <img src="docs/assets/icons/star.svg" width="12" height="12"> başkalarının onu bulmasına yardım eder</a>.</sub>
</div>
