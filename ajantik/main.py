# -*- coding: utf-8 -*-
"""Ajantik Node — giris noktasi.

Kullanim:  python -m ajantik config.json
"""

import logging
import os
import sys
import time

from . import __version__
from .config import load_config
from .runner import TaskRunner
from .telegram_api import TelegramAPI, TelegramError
from .tools import setup_github_token
from .utils import fmt_size

log = logging.getLogger("ajantik")

HELP_TEXT = (
    "🤖 Ajantik Node — kisisel gorev ajani\n\n"
    "Bana dogal dilde yaz; gorevleri bilgisayarda yaparim:\n"
    "• Dosya/klasor islemleri, zip yapip gonderme\n"
    "• Kabuk komutu calistirma, sistem durumu\n"
    "• Indirilen dosyalari isleme, linkten dosya indirme\n"
    "• Config'de tanimliysa uzak sunucuda (SSH) komut\n\n"
    "Komutlar:\n"
    "/status — kuyruk ve sistem durumu\n"
    "/reset — konusma hafizasini sifirla\n"
    "/kimlik — Telegram ID'ni gosterir\n"
    "\n"
    "Ornek: \"workspace'deki raporlari zip'le gonder\" veya "
    "\"sunucu durumunu soyle\"."
)


def _setup_logging(workspace):
    log_dir = os.path.join(workspace, "logs")
    os.makedirs(log_dir, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    log.setLevel(logging.INFO)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    log.addHandler(sh)
    fh = logging.FileHandler(os.path.join(log_dir, "ajantik.log"), encoding="utf-8")
    fh.setFormatter(fmt)
    log.addHandler(fh)


def _cmd_of(text):
    if not text:
        return ""
    return (text.split()[0] or "").split("@")[0].lower()


def _download_incoming(tg, msg, workspace):
    """Gelen dosya/fotografi indirir; (path, aciklama) doner."""
    dl_dir = os.path.join(workspace, "downloads")
    if msg.get("document"):
        doc = msg["document"]
        path, size = tg.download(doc["file_id"], dl_dir)
        name = doc.get("file_name") or os.path.basename(path)
        return path, "DOSYA: %s (%s)" % (name, fmt_size(size))
    if msg.get("photo"):
        biggest = msg["photo"][-1]
        path, size = tg.download(biggest["file_id"], dl_dir)
        return path, "FOTOGRAF (%s)" % fmt_size(size)
    return None, None


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    cfg_path = argv[0] if argv else "config.json"
    cfg = load_config(cfg_path)

    for sub in ("downloads", "outputs", "logs"):
        os.makedirs(os.path.join(cfg["workspace"], sub), exist_ok=True)
    _setup_logging(cfg["workspace"])

    if not cfg.get("telegram_token"):
        print("HATA: config.json icinde telegram_token bos.")
        print("1) Telegram'da @BotFather'a /newbot de, token'i al.")
        print("2) config.json > telegram_token alanina yapistir.")
        sys.exit(1)

    tg = TelegramAPI(cfg["telegram_token"])
    try:
        me = tg.get_me()
    except TelegramError as e:
        print("HATA: Telegram'a baglanilamadi: %s" % e)
        sys.exit(1)

    runner = TaskRunner(cfg, tg)
    allowed = set(cfg.get("allowed_user_ids") or [])

    # Config'e elle yazilmis GitHub token'i varsa kur (github_connect alternatifi)
    if cfg.get("github_token"):
        try:
            setup_github_token(cfg, cfg["github_token"])
            log.info("Config'deki GitHub token'i kurulu (git push hazir).")
        except Exception:
            log.exception("GitHub token kurulumu basarisiz")

    log.info(
        "Ajantik Node v%s basladi: @%s | izinli kullanici: %s | workspace: %s",
        __version__,
        me.get("username"),
        (sorted(allowed) if allowed else "HICBIRI (config > allowed_user_ids bos!)"),
        cfg["workspace"],
    )

    offset = 0
    while True:
        try:
            updates = tg.get_updates(offset)
        except TelegramError as e:
            log.warning("getUpdates hatasi: %s", e)
            time.sleep(5)
            continue
        except Exception:
            log.exception("getUpdates beklenmeyen hata")
            time.sleep(5)
            continue

        for upd in updates:
            offset = max(offset, (upd.get("update_id") or 0) + 1)

            # Onay butonlari (Evet/Hayir) — gorev thread'lerini uyandirir
            cb = upd.get("callback_query")
            if cb:
                tg.answer_callback(cb.get("id"))
                cb_user = (cb.get("from") or {}).get("id")
                if cb_user in allowed:
                    runner.approvals.resolve(cb.get("data") or "", cb_user)
                continue

            msg = upd.get("message")
            if not msg:
                continue
            chat = msg.get("chat") or {}
            if chat.get("type") != "private":
                continue
            chat_id = chat.get("id")
            user = msg.get("from") or {}
            user_id = user.get("id")
            text = (msg.get("text") or msg.get("caption") or "").strip()
            cmd = _cmd_of(text)

            # /kimlik herkese acik (izin listesine eklemek icin gerekli)
            if cmd == "/kimlik":
                tg.send_message(
                    chat_id,
                    "Senin Telegram ID'n: %s\nBot sahibi bu sayiyi config.json > "
                    "allowed_user_ids listesine eklerse botu kullanabilirsin." % user_id,
                )
                continue

            if user_id not in allowed:
                tg.send_message(
                    chat_id,
                    "⛔ Bu bot sana kapali. Bot sahibine soyle; senin ID'n: %s "
                    "(bu sayiyi ona ilet.)",
                )
                log.info("Yetkisiz erisim: user_id=%s username=%s", user_id, user.get("username"))
                continue

            if cmd == "/start":
                tg.send_message(chat_id, HELP_TEXT)
                continue
            if cmd in ("/yardim", "/help"):
                tg.send_message(chat_id, HELP_TEXT)
                continue
            if cmd == "/reset":
                runner.reset(chat_id)
                tg.send_message(chat_id, "🧹 Konusma hafizasi temizlendi.")
                continue
            if cmd == "/status":
                tg.send_message(chat_id, runner.status_text())
                continue

            # Dosya gelmis mi?
            file_part = ""
            try:
                path, desc = _download_incoming(tg, msg, cfg["workspace"])
            except Exception as e:
                log.exception("Dosya indirme hatasi")
                tg.send_message(chat_id, "❌ Dosya indirilemedi: %s" % e)
                continue
            if path:
                file_part = "[Kullanici bir dosya gonderdi: %s → %s]" % (desc, path)
                if not text:
                    text = file_part + " Kullanici ne yapilacagini yazmadi; kibarca sor."
                else:
                    text = file_part + " Istek: " + text

            if not text:
                tg.send_message(chat_id, "Anlasilir bir istek goremedim; kisa yazarmisin?")
                continue

            runner.enqueue(chat_id, user_id, text)


if __name__ == "__main__":
    main()
