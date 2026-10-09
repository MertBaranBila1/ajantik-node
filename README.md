# Ajantik Node 🤖

Eski/az güçlü bir Debian bilgisayarı (32-bit, tek çekirdek, 2GB RAM dahil)
Telegram üzerinden yönetilebilen kişisel görev ajanına dönüştürür.

**Mimari — beyin ayrı, eller makinada:**
- Bu bilgisayarda çok hafif bir ajan çalışır (~60-80MB RAM, tek bağımlılık:
  `requests`). Telegram botunu dinler, komut çalıştırır, dosya/zip işleri
  yapar, dosyaları sohbete geri gönderir, GitHub'a bağlanır.
- Beyin (LLM) hariciden çağrılır: bulut API **veya** kendi başka bir
  makinenizdeki Ollama. Laptop'ın kendisinde model çalıştırmaya gerek yok
  (o donanımda zaten pratik değil).

## Neler yapabilir

- "X klasöründeki dosyaları zip'le gönder" → yapar, ZIP'i sohbete atar
- "Sistemin durumu ne?" → RAM/disk/yük bilgisini yazar
- "Bu hataya bak" → dosyaları okur, düzenler (önce otomatik yedek alır)
- "Şu linkteki dosyayı indir" → indirir, işler
- "Sitemiz çalışmıyor, düzelt" → GitHub'a bağlanır (telefonundan kod
  girmen yeterli), site dosyalarını düzeltir, push'lar; Netlify otomatik
  yayınlar, sonra siteyi kontrol edip söyler
- **Paket kurma/silme gibi sistem işleri için sana Telegram'da
  Evet/Hayır butonu ile onay sorar** — onaysız hiçbir kurulum yapmaz
- Telegram'a dosya atarsın → workspace/downloads'a iner, ajan işler
- Config'de tanımlıysa uzak sunucuda SSH ile komut çalıştırır

Sınırlar: Telegram bot API dosya **indirme** 20MB, **gönderme** 50MB ile
sınırlıdır. Aynı anda tek görev işler (tek çekirdek).

## HAZIR KURULUM (bu paket)

Bu zip içindeki `config.json` **senden alına gerçek değerlerle doldurulmuş
halde** geliyor: bot token'ın, OpenRouter anahtarın ve seçilmiş model.
Tek eksik: `allowed_user_ids` (aşağıda).

## Kurulum (laptop'ta)

### 1) Kodu kur

```bash
sudo apt update && sudo apt install -y python3 python3-venv git

# GitHub'dan ya da zip'ten:
git clone https://github.com/MertBaranBila1/ajantik-node.git
cd ajantik-node

bash install.sh
```

(Zip kullandıysan zip'i aç, klasöre gir, `bash install.sh`.)

### 2) Kullanıcıları tanı (allowed_user_ids)

Bot sadece listedeki Telegram kullanıcılarını dinler. Senin ID'n
(`708331817`) bu pakette zaten kayıtlı — botu sen direkt kullanabilirsin.

**Yeni kullanıcı eklemek çok kolay (bot çalışırken):**
1. Ekleyeceğin kişi bota herhangi bir şey yazar → ona "⛔ ... Senin ID'n:
   123456789" cevabı gider (ya da kişi sana `/kimlik` çıktısını atar)
2. Sen bota yazarsın: `/ekle 123456789`
3. Bitti — kişi artık botu kullanabilir ✅

Liste `config.json`'a **kalıcı** yazılır; bot yeniden başlasa da durur.
Diğer komutlar: `/sil <id>` (yetkiyi kaldır), `/liste` (yetkilileri göster).
Bu komutları sadece bot sahibi (`admin_user_ids`) kullanabilir.

Yeni kullanıcıyı elle de ekleyebilirsin: `config.json > allowed_user_ids`
listesine ID'yi yaz.

## Çalışma alanı ve klasör izinleri

- Ajanın çalışma alanı (workspace): **`Masaüstü/Ajan Klasörü`** — bot ilk
  açılışta kendisi oluşturur. Klonladığı repolar, ürettiği çıktılar,
  indirdiği dosyalar hep burada toplanır.
- Ajan ayrıca şu klasörlere erişebilir: **Masaüstü (tamamı)** ve
  **İndirilenler**.
- Yeni klasör izni vermek (telefonundan, bot sahibi olarak):
  - `/klasor` → izinli klasörleri listeler
  - `/klasor ekle /home/asus/Belgeler` → kalıcı izin verir
  - `/klasor sil <yol>` → izni kaldırır
- Ajan bir yolda "izin yok" hatası alırsa sana söyler ve bu komutu
  hatırlatır.

## Uygulama kurma/silme (apt)

Ajan `apt install/remove` gibi komutları çalıştırmadan önce sana
Telegram'da **Evet/Hayır** gönderir. Ek olarak, kurulum sırasında
`install.sh` sana "şifresiz apt yetkisi vereyim mi?" diye sorar:
- **E** dersen: sadece `apt`/`apt-get` komutları sudo şifresi istemez
  (sudoers.d/ajantik-apt dosyası). Telegram onayı yine devam eder —
  yani çifte kontrol: senin onayın + şifresiz apt.
- **h** dersen: ajan apt komutlarında sudo şifresi yüzünden takılır;
  sonra elle de verebilirsin:
  `echo "$USER ALL=(ALL) NOPASSWD: /usr/bin/apt, /usr/bin/apt-get" | sudo tee /etc/sudoers.d/ajantik-apt && sudo chmod 440 /etc/sudoers.d/ajantik-apt`

### 3) Çalıştır

```bash
./run.sh
```

Telefonda botuna yaz: `/start`. Bitti 🎉

**Otomatik başlangıç (açılışta):**

```bash
sudo cp -r . /opt/ajantik-node
sudo cp /opt/ajantik-node/ajantik.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ajantik
journalctl -u ajantik -f   # log takibi
```

## GitHub bağlama (site tamiri için)

Ajan, GitHub'daki dosyaları düzenleyip push'layabilmek için bir kez
bağlanmanı ister:

1. Bota de ki: "GitHub'a bağlan"
2. Ajan sana bir kod gönderir: `XXXX-XXXX`
3. Telefonundan `github.com/login/device` adresini aç, kodu gir
4. Ajan otomatik bağlanır — artık clone/push yapabilir

Bu bir kere yapılır; token bilgisayarda saklanır. Alternatif: kendi
oluşturduğun bir PAT'ı `config.json > github_token` alanına yapıştır,
bağlantısız da çalışır.

## Site geliştirme + Netlify akışı

- Siten zaten Netlify'da **GitHub reposundan** yayınlanıyorsa: ajan
  repoyu clone eder, düzenler, push'lar → **Netlify otomatik deploy eder**.
  Ajan sonrasında siteyi kontrol edip sonucu söyler.
- Siten Netlify'ya henüz GitHub'a bağlı değilse: bir kez Netlify panelinde
  "Import from Git" ile reponu bağla; sonrası otomatik.
- Ajan ayrıca sitenin dosyalarını düzeltmeden önce `list_dir`/`read_file`
  ile inceler, düzenlemeleri yedek alarak yapar.

## Onay sistemi (güvenli kurulum)

Ajan şu tür komutları çalıştırmadan önce sana Telegram'da Evet/Hayır
butonu gönderir: `apt`, `pip install`, `npm install`, `sudo ...`,
`systemctl ...` gibi. Onaylamazsan çalışmaz. Kapatmak istersen config'de
`agent.confirm_installs: false` yap.

İpucu: kurulum sırasında `install.sh` bunu otomatik sorar (E/h); el ile
vermek istersen:

## LLM / model bilgisi

Bot **3 model profiliyle** geliyor; hangisinin çalışacağını Telegram'dan
değiştirirsin (sadece bot sahibi):

- `/model` → profilleri listeler (aktif olan ✅ ile işaretli)
- `/model gemini-hizli` → o profile geçer (hemen + kalıcı)
- `/modeltest` → aktif modele kısa bir test mesajı atar

Profiller:
| Profil | Model | Not |
|---|---|---|
| `gemini` | gemini-flash-latest | **Aktif.** Google AI Studio ücretsiz kotası; dengeli ve yetenekli |
| `gemini-hizli` | gemini-flash-lite-latest | Çok hızlı (basit işler için); aynı ücretsiz kota |
| `openrouter` | nemotron-3-ultra-550b-a55b:free | Yedek; OpenRouter ücretsiz kotası (günde ~50 istek) |

- Gemini ücretsiz kotada dakikalık/günlük istek sınırları vardır; limit
  dolarsa bot "LLM hatası" der → `/model` ile başka profile geçersin.
- `gemini-flash-latest` gibi `-latest` isimli modeller Google model
  güncellese de otomatik en yeni sürüme işaret eder.
- Yeni profil eklemek: `config.json > llm_profiles` içine yeni bir blok
  (base_url + api_key + model) ekle; `/model` listesinde görünür.
- Tamamen kapalı sistem istersen: güçlü başka bir makinene Ollama kur;
  profile `base_url: http://<PC-IP>:11434/v1`, `api_key: ollama` yaz.

## Güvenlik — önemli

- Bota sadece `allowed_user_ids` listesindekiler erişebilir.
- Dosya işlemleri workspace + `allowed_dirs` ile sınırlıdır.
- Yıkıcı komutlar (rm -rf /, mkfs, shutdown...) kara listededir.
- Kurulum/sistem komutları Evet/Hayır onayı ister.
- Çalıştırılan tüm komutlar `workspace/logs/komutlar.log` dosyasına yazılır.
- **`config.json` içinde bot token'ı ve API anahtarın var; bu dosyayı
  kimseyle paylaşma.** GitHub'a asla yüklenmez (.gitignore hariç tutuyor).
- **Gizlilik gerçeği:** Bulut API kullanırsan görev metinleri ve ajanın
  okuduğu dosya içerikleri o sağlayıcıya gider. Hiçbir şeyin dışarı
  çıkmamasını istiyorsan Ollama seçeneğini kullan.

## Sorun giderme

| Sorun | Çözüm |
|---|---|
| "LLM'e ulaşılamadı" | İnternet çıkışı; `/modeltest` ile dene, `/model <profil>` ile diğerine geç |
| Ücretsiz model "rate limit" hatası | Günlük limit doldu; ertesi gün ya da ücretli model |
| Bot cevap vermiyor | `journalctl -u ajantik -f` ya da `./run.sh` çıktısı |
| "⛔ Bu bot sana kapalı" | ID bot sahibine iletilmeli; sahibi `/ekle <id>` yazar |
| Ajan "güvenlik gereği erişemiyorum" diyor | Yeniden denesin (eski sürüm huyuydu, v1.4'te prompt'a yasak kondu). Gerçek "izin yok" ise `/klasor ekle <yol>` |
| Ajan bir klasöre "izin yok" diyor | `/klasor ekle <yol>` ile izin ver |
| GitHub'a push hata veriyor | `github_connect` ile tekrar bağlan; token süresi bitmiş olabilir |
| Dosya gönderilemedi | 50MB sınırı; dosyayı böl ya da linkle |
| `venv/bin/pip: Böyle bir dosya ya da dizin yok` | Debian'da `python3-venv` paketi eksik. Çöz: `rm -rf venv && sudo apt update && sudo apt install -y python3-venv && bash install.sh` |
| Onay butonu geldi, dokunmadım | 5 dk sonra otomatik reddedilir |

## Teknik

- Python 3.7+ (Debian 10/11/12 i386 ile uyumlu), tek bağımlılık `requests`
- LLM protokolü: OpenAI uyumlu `/chat/completions` + JSON araç çağrısı
- 13 araç: run_command, read_file, write_file, list_dir, search_text,
  zip_files, send_file, download_file, run_ssh, sys_info,
  github_connect, github_status, ask_user
