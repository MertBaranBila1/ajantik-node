#!/usr/bin/env bash
# Ajantik Node kurulumu (Debian, 32-bit uyumlu).
# Kullanim:  bash install.sh

set -e
cd "$(dirname "$0")"
KLASOR="$(pwd)"

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
echo "NOT: Calisma alani (workspace) config.json'daki ayara gore olusur."
echo "Bot ilk acilista 'Masaustu/Ajan Klasoru' ve alt klasorlerini olusturur."

# -------------------------------------------------------------------- #
# 1) Opsiyonel: sifresiz apt (uygulama kurma/silme)
# -------------------------------------------------------------------- #
if [ -t 0 ]; then
    echo ""
    echo "1) Ajanin 'apt' ile uygulama kurup kaldirabilmesi icin sifresiz"
    echo "   apt yetkisi vermek ister misin? (E/h)"
    read -r cevap || cevap="h"
    case "$cevap" in
        [Ee]*)
            if echo "$USER ALL=(ALL) NOPASSWD: /usr/bin/apt, /usr/bin/apt-get" | sudo tee /etc/sudoers.d/ajantik-apt >/dev/null 2>&1; then
                sudo chmod 440 /etc/sudoers.d/ajantik-apt 2>/dev/null || true
                echo "   OK: Verildi."
            else
                echo "   UYARI: Verilemedi; sonra elle ekleyebilirsin (README'ye bak)."
            fi
            ;;
        *)
            echo "   Atlandi."
            ;;
    esac

    # ---------------------------------------------------------------- #
    # 2) Opsiyonel: bilgisayar acilinca otomatik baslatma (arka plan)
    # ---------------------------------------------------------------- #
    echo ""
    echo "2) Bilgisayar acildiginda ajan otomatik (arka planda) baslasin mi? (E/h)"
    read -r cevap || cevap="h"
    case "$cevap" in
        [Ee]*)
            SRVFILE="$(mktemp)"
            cat > "$SRVFILE" <<EOF
[Unit]
Description=Ajantik Node - kisisel gorev ajani
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$KLASOR
ExecStart=$KLASOR/venv/bin/python -m ajantik $KLASOR/config.json
ExecStopPost=$KLASOR/venv/bin/python -m ajantik.webhook on $KLASOR/config.json
Restart=always
RestartSec=15

[Install]
WantedBy=multi-user.target
EOF
            if sudo install -m 644 "$SRVFILE" /etc/systemd/system/ajantik.service 2>/dev/null \
               && sudo systemctl daemon-reload \
               && sudo systemctl enable ajantik >/dev/null 2>&1 \
               && sudo systemctl restart ajantik; then
                sleep 2
                if systemctl is-active --quiet ajantik; then
                    echo "   OK: Servis kuruldu ve CALISIYOR."
                    echo "   - Bilgisayar acilinca otomatik baslar (hiçbir şeye basmana gerek yok)."
                    echo "   - Yonetim: sudo systemctl status|stop|restart ajantik"
                    echo "   - Loglar:  journalctl -u ajantik -f"
                else
                    echo "   UYARI: Servis kuruldu ama baslamadi. Loglar:"
                    echo "   journalctl -u ajantik -n 30"
                fi
            else
                echo "   UYARI: Servis kurulamadi (sudo/systemctl sorunu)."
                echo "   Botu elle baslatabilirsin:  ./run.sh"
            fi
            rm -f "$SRVFILE"
            ;;
        *)
            echo "   Atlandi. Botu elle baslatmak icin: ./run.sh"
            ;;
    esac
fi

# -------------------------------------------------------------------- #
# Masaustu kisayolu (masaustu varsa sessizce olustur; tek tikla baslatma)
# -------------------------------------------------------------------- #
DT=""
for d in "$HOME/Masaüstü" "$HOME/Masaustu" "$HOME/Desktop"; do
    if [ -d "$d" ]; then
        DT="$d"
        break
    fi
done
if [ -n "$DT" ]; then
    cat > "$DT/Ajantik-Baslat.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Ajantik Botu Başlat
Comment=Telegram ajanını başlatır (arka plan servisi yoksa)
Exec="$KLASOR/run.sh"
Terminal=true
Categories=Utility;
EOF
    chmod +x "$DT/Ajantik-Baslat.desktop" 2>/dev/null || true
    echo ""
    echo "Masaustune kisayolu olusturuldu: 'Ajantik Botu Baslat'"
    echo "(Servis kurulmussa buna ihtiyacin olmaz; cift tik acilmazsa sag tik -> 'Launch'/'Izin ver')"
fi

echo ""
echo "== Kurulum tamam =="
if [ -t 0 ]; then
    echo "Botu elle baslatmak istersen:  ./run.sh"
fi
