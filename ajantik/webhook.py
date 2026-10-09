# -*- coding: utf-8 -*-
"""Bulut modu gecisi: Telegram webhook yonetimi.

Laptop acilirken ajan webhook'u siler (polling moduna gecer); kapanirken
(systemd ExecStopPost) webhook'u tekrar ayarlar — boylece laptop kapaliyken
mesajlar buluttaki kisitli kopyaya gider.

Kullanim:
  python -m ajantik.webhook on     -> webhook'u ayarlar (bulut devralir)
  python -m ajantik.webhook off    -> webhook'u siler (laptop polling'e gecer)
  python -m ajantik.webhook durumu -> mevcut webhook bilgisi
"""

import sys

import requests

from .config import load_config


def _call(token, method, data=None):
    try:
        r = requests.post(
            "https://api.telegram.org/bot%s/%s" % (token, method),
            json=data if data is not None else {},
            timeout=30,
        )
    except requests.RequestException as e:
        return {"ok": False, "description": str(e)}
    try:
        return r.json()
    except ValueError:
        return {"ok": False, "description": "HTTP %s" % r.status_code}


def main(argv=None):
    argv = list(argv) if argv is not None else sys.argv[1:]
    if not argv or argv[0] not in ("on", "off", "durumu"):
        sys.stdout.write(__doc__ or "")
        return 1
    cmd = argv[0]
    cfg_path = argv[1] if len(argv) > 1 else "config.json"
    try:
        cfg = load_config(cfg_path)
    except Exception as e:
        print("HATA: config okunamadi (%s): %s" % (cfg_path, e))
        return 1
    token = cfg.get("telegram_token")
    if not token:
        print("HATA: telegram_token bos.")
        return 1

    if cmd == "on":
        url = (cfg.get("cloud_webhook_url") or "").strip()
        if not url:
            # Bulut adresi tanimlanmamis; sessizce gec (ExecStopPost icin guvenli)
            print("Bilgi: cloud_webhook_url bos; bulut modu tanimlanmamis, atlandi.")
            return 0
        res = _call(token, "setWebhook", {"url": url})
        if res.get("ok"):
            print("OK: Bulut moduna gecildi; mesajlar artik buluta gider:")
            print("     %s" % url)
            return 0
        print("HATA: setWebhook basarisiz: %s" % res.get("description"))
        return 1

    if cmd == "off":
        res = _call(token, "deleteWebhook", {"drop_pending_updates": False})
        if res.get("ok"):
            print("OK: Webhook silindi; laptop polling moduna gecti.")
            return 0
        print("HATA: deleteWebhook basarisiz: %s" % res.get("description"))
        return 1

    # durumu
    res = _call(token, "getWebhookInfo")
    if not res.get("ok"):
        print("HATA: %s" % res.get("description"))
        return 1
    info = res.get("result") or {}
    url = (info.get("url") or "").strip()
    if url:
        print("BULUT MODU: mesajlar su adrese gidiyor:")
        print("  %s" % url)
        print("(laptop acilinca ajan otomatik geri alir)")
    else:
        print("LAPTOP MODU: webhook yok, ajan polling yapiyor (normal calisma).")
    print("Bekleyen mesaj sayisi: %s" % info.get("pending_update_count", 0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
