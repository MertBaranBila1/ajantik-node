#!/usr/bin/env bash
# Ajantik Node kurulumu (Debian, 32-bit uyumlu).
# Kullanim:  bash install.sh

set -e
cd "$(dirname "$0")"

echo "== Ajantik Node kurulumu =="

if ! command -v python3 >/dev/null 2>&1; then
    echo "HATA: python3 bulunamadi. Once su komutu calistir:"
    echo "  sudo apt update && sudo apt install -y python3 python3-venv"
    exit 1
fi

echo "Python: $(python3 --version)"

if [ ! -d venv ]; then
    if ! python3 -m venv venv 2>/dev/null; then
        echo "venv olusturulamadi. Su komutu calistirip tekrar dene:"
        echo "  sudo apt install -y python3-venv"
        exit 1
    fi
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
