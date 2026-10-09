#!/usr/bin/env bash
# Ajantik Node kurulumu (Debian, 32-bit uyumlu).
# Kullanim:  bash install.sh

set -e
cd "$(dirname "$0")"

echo "== Ajantik Node kurulumu =="

if ! command -v python3 >/dev/null 2>&1; then
    echo "HATA: python3 bulunamadi. Once sunu calistir:"
    echo "  sudo apt update && sudo apt install -y python3 python3-venv"
    exit 1
fi

echo "Python: $(python3 --version)"

# Yarim kalmis venv var mi? (klasor var ama pip yok -> bastan olustur)
if [ -d venv ] && [ ! -x venv/bin/pip ]; then
    echo "Yarim kalmis venv bulundu; temizlenip yeniden olusturulacak..."
    rm -rf venv
fi

if [ ! -d venv ]; then
    echo "Sanal ortam (venv) olusturuluyor..."
    if ! python3 -m venv venv; then
        echo ""
        echo "HATA: venv olusturulamadi."
        echo "Debian'da venv ozelligi ayri pakettir; muhtemelen eksik."
        echo "Sunu calistirip tekrar dene:"
        echo "  sudo apt update && sudo apt install -y python3-venv"
        echo "  bash install.sh"
        exit 1
    fi
fi

# venv gercekten saglam mi? (pip olusmussa evet)
if [ ! -x venv/bin/pip ]; then
    echo ""
    echo "HATA: venv eksik olustu (icinde pip yok)."
    echo "Su uc komutla duzelir:"
    echo "  rm -rf venv"
    echo "  sudo apt update && sudo apt install -y python3-venv"
    echo "  bash install.sh"
    exit 1
fi

echo "Kutuphaneler kuruluyor (sadece 'requests')..."
./venv/bin/pip install --quiet --disable-pip-version-check -r requirements.txt

if [ ! -f config.json ]; then
    cp config.example.json config.json
    echo ""
    echo "ONEMLI: config.example.json kopyalanarak config.json olusturuldu."
    echo "Simdi icini doldurman gerek (telegram_token, llm, allowed_user_ids)."
else
    echo "config.json zaten var; dokunmadim."
fi

echo ""
echo "NOT: Calisma alani (workspace) config.json'daki ayara gore olusur:"
echo "$('grep' -o '"workspace": "[^"]*"' config.json 2>/dev/null | head -1 | cut -d'"' -f4 || echo './workspace')"
echo "Bot ilk acilista bu klasoru ve alt klasorlerini otomatik olusturur."

# -------------------------------------------------------------------- #
# Opsiyonel: ajanin apt ile uygulama kurup kaldirabilmesi
# (Telegram'daki Evet/Hayir onay sistemi her durumda aktif kalir)
# -------------------------------------------------------------------- #
if [ -t 0 ]; then
    echo ""
    echo "Ajanin 'apt' ile uygulama kurup kaldirabilmesi icin sifresiz"
    echo "apt yetkisi vermek ister misin? (E/h)"
    read -r cevap || cevap="h"
    case "$cevap" in
        [Ee]*)
            if echo "$USER ALL=(ALL) NOPASSWD: /usr/bin/apt, /usr/bin/apt-get" | sudo tee /etc/sudoers.d/ajantik-apt >/dev/null 2>&1; then
                sudo chmod 440 /etc/sudoers.d/ajantik-apt 2>/dev/null
                echo "OK: Verildi. Ajan artik apt komutlarini sorunsuz calistirabilir."
            else
                echo "UYARI: Verilemedi (sudo hata verdi). Ajan apt icin sudo sifresi isteyecek."
                echo "Istersen sonra elle ekle:"
                echo "  echo \"$USER ALL=(ALL) NOPASSWD: /usr/bin/apt, /usr/bin/apt-get\" | sudo tee /etc/sudoers.d/ajantik-apt"
                echo "  sudo chmod 440 /etc/sudoers.d/ajantik-apt"
            fi
            ;;
        *) echo "Atlandi. Ajan apt komutlarinda sudo sifresi isteyecek." ;;
    esac
fi

echo ""
echo "== Kurulum tamam =="
echo "1) config.json dosyasini doldur (bkz. README.md)"
echo "2) Baslatmak icin:  ./run.sh"
