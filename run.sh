#!/usr/bin/env bash
cd "$(dirname "$0")"

# Servis zaten arka planda calisiyorsa cakismayi onle (Telegram 409 hatasi)
if command -v systemctl >/dev/null 2>&1 && systemctl is-active --quiet ajantik 2>/dev/null; then
    echo "Ajantik zaten ARKA PLANDA calisiyor (systemd servisi)."
    echo ""
    echo "Yonetim komutlari:"
    echo "  durum:   systemctl status ajantik"
    echo "  durdur:  sudo systemctl stop ajantik"
    echo "  yeniden: sudo systemctl restart ajantik"
    echo ""
    echo "Yine de one-cikarip buradan calistirmak istersen once durdur."
    echo "(Kapatmak icin Enter)"
    read -r _bekle || true
    exit 0
fi

exec ./venv/bin/python -m ajantik config.json
