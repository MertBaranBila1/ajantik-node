# Ajantik Node 🤖

Eski/az güçlü bir Debian bilgisayarı (32-bit, tek çekirdek, 2GB RAM dahil)
Telegram üzerinden yönetilebilen kişisel görev ajanına dönüştürür.

**Mimari — beyin ayrı, eller makinada:**
- Bu bilgisayarda çok hafif bir ajan çalışır (~60-80MB RAM, tek bağımlılık:
  `requests`). Telegram botunu dinler, komut çalıştırır, dosya/zip işleri
  yapar, dosyaları sohbete geri gönderir.
- Beyin (LLM) hariciden çağrılır: bulut API **veya** kendi başka bir
  makinenizdeki Ollama. Laptop'ın kendisinde model çalıştırmaya gerek yok
  (o donanımda zaten pratik değil).

## Neler yapabilir

- "X klasöründeki dosyaları zip'le gönder" → yapar, ZIP'i sohbete atar
- "Sistemin durumu ne?" → RAM/disk/yük bilgisini yazar
- "Bu hataya bak" → dosyaları okur, düzenler (önce otomatik yedek alır)
- "Şu linkteki dosyayı indir" → indirir, işler
- Telegram'a dosya atarsın → workspace/downloads'a iner, ajan işler
- Config'de tanımlıysa uzak sunucuda SSH ile komut çalıştırır
  ("sitemiz çalışmıyor" → sunucuda log'a bakar, dosyayı düzeltir)

Sınırlar: Telegram bot API dosya **indirme** 20MB, **gönderme** 50MB ile
sınırlıdır. Aynı anda tek görev işler (tek çekirdek).

## Kurulum

### 1) Telegram botu oluştur (2 dakika)

1. Telefonda `@BotFather`'ı aç → `/newbot` yaz
2. Bota bir isim ver (örn. `Ajantik`)
3. Bir kullanıcı adı ver (örn. `ajantik_dukkani_bot` — `bot` ile bitmeli)
4. Verdiği **token**'ı kopyala (`123456:ABC-xyz...` gibi)

### 2) Beyin (LLM) seç

**A) Bulut API (kolay, önerilen):** [openrouter.ai](https://openrouter.ai)
ücretsiz üyelikte API anahtarı verir; yüzlerce modelden birini
kullanabilirsin (ucuz bir sohbet modeli yeterli; agent işleri için
"GPT-4o-mini / DeepSeek sınıfı" modeller iyi çalışır).
- `base_url`: `https://openrouter.ai/api/v1`
- `api_key`: aldığın anahtar
- `model`: seçtiğin model adı

**B) Tam gizlilik — kendi makinen:** Güçlü başka bir bilgisayarına
[Ollama](https://ollama.com) kur, `ollama serve` ile aç (0.0.0.0'da
dinlemesi için `OLLAMA_HOST=0.0.0.0`), bir model çek (`ollama pull qwen2.5:7b`
gibi). Laptop'ta:
- `base_url`: `http://<PC-IP>:11434/v1`
- `api_key`: `ollama` (önemsenmez ama boş bırakma)
- `model`: çektiğin model adı
- Not: veri hiç dışarı çıkmaz, ama o PC'nin açık ve aynı ağda olması gerekir.

**Dürüst not:** Laptop'ın KENDİSİNDE model çalıştırmak (32-bit Atom, 2GB)
teknik olarak denenebilir ama bir cevap dakikalar sürer; site tamiri gibi
işler için kullanılamaz. Bu yüzden tasarım beyin-harici'dir.

### 3) Kurulumu yap (laptop'ta)

```bash
# Gerekenler: python3 (Debian'da genelde kurulu)
sudo apt update && sudo apt install -y python3 python3-venv git

# Kodu al (repo) ya da zip'i aç
git clone https://github.com/MertBaranBila1/ajantik-node.git
cd ajantik-node

bash install.sh
```

### 4) config.json doldur

`install.sh` senin için `config.json` oluşturur (kopyası). Doldur:

```json
{
  "telegram_token": "BOTFATHER_TOKENIN",
  "llm": {
    "base_url": "https://openrouter.ai/api/v1",
    "api_key": "ANAHTARIN",
    "model": "MODEL_ADI"
  },
  "allowed_user_ids": [TELEGRAM_IDLER],
  "workspace": "./workspace",
  "allowed_dirs": [],
  "ssh_hosts": {}
}
```

- `allowed_user_ids`: Bota kimler erişebilir (sen + yakınların). Telegram
  ID'lerini öğrenmek için: bota ilk kez bir şey yaz → "⛔ Bu bot sana kapalı"
  cevabında ID'n yazar (ya da `/kimlik` yaz, o herkese açıktır). O sayıları
  bu listeye ekle.
- `allowed_dirs`: Ajanın dosya araçlarıyla dokunabileceği ekstra klasörler
  (örn. `"/var/www/sitem"`). Boşsa sadece workspace içinde çalışır.
- `ssh_hosts`: Uzak sunucu tanımları. Örnek:
  `"sitem": {"user": "root", "host": "1.2.3.4", "port": 22}` — laptop'ta
  o sunucuya `ssh-keygen` + `ssh-copy-id` ile anahtarsız girişi hazırla.
  Ajan `"sitem"` adıyla komut çalıştırabilir (site tamiri bununla olur).
- `personality`: Ajanın tarzı (örn. "kibar ve esprili ol") — opsiyonel.

### 5) Çalıştır

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

## Güvenlik — önemli

- Bota sadece `allowed_user_ids` listesindekiler erişebilir.
- Dosya işlemleri workspace + `allowed_dirs` ile sınırlıdır.
- Yıkıcı komutlar (rm -rf /, mkfs, shutdown...) kara listededir; config'den
  `block_dangerous_commands: false` yaparak kapatbilirsin (önerilmez).
- Çalıştırılan tüm komutlar `workspace/logs/komutlar.log` dosyasına yazılır.
- **Gizlilik gerçeği:** Bulut API kullanırsan görev metinleri ve ajanın
  okuduğu dosya içerikleri o sağlayıcıya gider (kod ve dosyalar makinende
  kalır). Hiçbir şeyin dışarı çıkmamasını istiyorsan B) Ollama seçeneğini
  kullan.
- Bot token ve API anahtarı `config.json` içinde; **bu dosyayı kimseyle
  paylaşma, repoya koyma** (`.gitignore` zaten hariç tutuyor).

## Sorun giderme

| Sorun | Çözüm |
|---|---|
| "LLM'e ulaşılamadı" | `base_url`/`api_key`/`model` kontrol et; internet çıkışı var mı |
| "API anahtarı reddedildi (401)" | Anahtar yanlış/süresi geçmiş |
| Bot cevap vermiyor | `journalctl -u ajantik -f` ya da `./run.sh` çıktısına bak |
| Dosya gönderilemedi | 50MB sınırı; dosyayı böl ya da linkle |
| `pip` hatası | `python3 -m venv venv` çalışmadıysa `sudo apt install python3-venv` |

## Teknik

- Python 3.7+ (Debian 10/11/12 i386 ile uyumlu), tek bağımlılık `requests`
- LLM protokolü: OpenAI uyumlu `/chat/completions` + JSON araç çağrısı
  (her sağlayıcıda çalışır)
- Kaynak: `ajantik/` paketi ~1000 satır; okunabilir, değiştirilebilir
