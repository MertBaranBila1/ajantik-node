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

mkdir -p workspace/downloads workspace/outputs workspace/logs

echo ""
echo "== Kurulum tamam =="
echo "1) config.json dosyasini doldur (bkz. README.md)"
echo "2) Baslatmak icin:  ./run.sh"
