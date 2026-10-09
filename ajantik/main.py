# -*- coding: utf-8 -*-
"""Ajantik Node — giris noktasi.

Kullanim:  python -m ajantik config.json
"""

import logging
import os
import sys
import time

from . import __version__
from .config import load_config, save_allowed_ids, save_allowed_dirs, save_llm_config
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
    "/ekle <id> — (sadece bot sahibi) yeni kullanici yetkilendirir\n"
    "/sil <id> — (sadece bot sahibi) kullaniciyi yetkisiz birakir\n"
    "/liste — yetkili kullanicilar\n"
    "/model — (sadece bot sahibi) AI modelini gosterir/degistirir\n"
    "/modeltest — (sadece bot sahibi) aktif modeli test eder\n"
    "/klasor — (sadece bot sahibi) klasor izinlerini yonetir (/klasor ekle <yol>)\n"
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


def _ensure_polling(tg):
    """Webhook setliyse siler; laptop polling moduna gecer.

    Bulut modundan donuste bekleyen mesajlar bulut tarafindan cevaplanmis
    olabileceginden drop_pending_updates=True kullanilir (tekrar islenmesin).
    Ayrica webhook setliyken getUpdates hata verdiginden, bu cagri olmaksizin
    polling hic baslamaz.
    """
    try:
        info = tg.get_webhook_info() or {}
    except TelegramError as e:
        log.warning("getWebhookInfo hatasi: %s", e)
        return
    url = (info.get("url") or "").strip()
    if not url:
        log.info("Webhook yok; laptop polling modunda (normal).")
        return
    try:
        tg.delete_webhook(drop_pending=True)
        log.info("Bulut webhook'u silindi; laptop polling moduna gecti.")
    except TelegramError as e:
        log.warning("deleteWebhook hatasi: %s", e)


def _load_offset(path):
    """Son islenen Telegram update offsetini okur (restart korumasi).

    Offset kalici olmadiginda her acilista son 24 saatin mesajlari bastan
    islenirdi; bu dosya onu onler.
    """
    try:
        with open(path, "r") as f:
            return int((f.read() or "0").strip() or 0)
    except (OSError, ValueError):
        return 0


def _save_offset(path, offset):
    try:
        with open(path, "w") as f:
            f.write(str(offset))
    except OSError:
        pass


def _klasor_command(text, cfg, admins, user_id):
    """Bot sahibi icin klasor izni yonetimi. Donus: cevap metni ya da None.

    /klasor            -> izinli klasorleri listeler
    /klasor ekle <yol> -> kalici izin verir
    /klasor sil <yol>  -> izni kaldirir
    """
    parts = text.split()
    cmd = (parts[0] if parts else "").split("@")[0].lower()
    if cmd != "/klasor":
        return None
    if user_id not in admins:
        return "⛔ Bu komut sadece bot sahibine acik."
    dirs = cfg.get("allowed_dirs") or []

    if len(parts) == 1:
        if not dirs:
            return ("Izinli ekstra klasor yok (ajan sadece workspace icinde calisir).\n"
                    "Eklemek icin: /klasor ekle /home/asus/Belgeler")
        return ("📂 Izinli klasorler:\n" + "\n".join("- " + d for d in dirs)
                + "\n\nCikarmak icin: /klasor sil <yol>")

    alt = parts[1].lower()
    if alt not in ("ekle", "sil", "kaldir"):
        return "Kullanim:\n/klasor ekle <yol>\n/klasor sil <yol>\n/klasor (liste)"

    if len(parts) < 3:
        return "Yol eksik. Ornek: /klasor ekle /home/asus/Belgeler"
    yol = " ".join(parts[2:])
    yol = os.path.expanduser(yol)
    if not os.path.isabs(yol):
        return "Lutfen tam yol yaz. Ornek: /home/asus/Belgeler (ya da ~/Belgeler)"

    if alt == "ekle":
        if yol in dirs:
            return "%s zaten izinli." % yol
        if not os.path.isdir(yol):
            return "Boyle bir klasor yok: %s\n(yolu kontrol et)" % yol
        dirs.append(yol)
        try:
            save_allowed_dirs(cfg, dirs)
            return "✅ %s eklendi; ajan artik burada calisabilir." % yol
        except Exception as e:
            return "⚠️ Bellekte eklendi ama config'e yazilamadi: %s" % e
    # sil
    if yol not in dirs:
        return "%s izin listesinde yok." % yol
    dirs.remove(yol)
    try:
        save_allowed_dirs(cfg, dirs)
        return "❌ %s izni kaldirildi." % yol
    except Exception as e:
        return "⚠️ Bellekten cikarildi ama config'e yazilamadi: %s" % e


def _model_list_text(cfg):
    """Profil listesini okunur metin olarak dondurur."""
    profiles = cfg.get("llm_profiles") or {}
    active = cfg.get("active_profile") or ""
    satirlar = []
    aktif_model = (cfg.get("llm") or {}).get("model") or "?"
    satirlar.append("🧠 Aktif model: %s (%s)" % (active or "(isimsiz)", aktif_model))
    satirlar.append("")
    satirlar.append("Profiller:")
    for ad in sorted(profiles):
        m = (profiles[ad] or {}).get("model") or "?"
        isaret = " ✅ (aktif)" if ad == active else ""
        satirlar.append("- %s — %s%s" % (ad, m, isaret))
    satirlar.append("")
    satirlar.append("Geçmek için: /model <profil-adı>")
    satirlar.append("Test için: /modeltest")
    return "\n".join(satirlar)


def _test_llm_async(tg, chat_id, llm, name):
    """Aktif LLM'e kisa bir ping atar; sonucu sohbete yazar (thread'de)."""
    import threading

    def run():
        try:
            import time as _t
            t0 = _t.time()
            cevap = llm.chat([{"role": "user", "content": "Tek kelime yaz: OK"}])
            sure = _t.time() - t0
            tg.send_message(
                chat_id,
                "✅ %s çalışıyor (%.1f sn yanıt): %s"
                % (name, sure, (cevap or "").strip()[:100]),
            )
        except Exception as e:
            tg.send_message(chat_id, "❌ %s hatası: %s" % (name, e))

    th = threading.Thread(target=run, daemon=True)
    th.start()


def _cmd_of(text):
    if not text:
        return ""
    return (text.split()[0] or "").split("@")[0].lower()


def _admin_command(text, cfg, allowed, admins, user_id):
    """Bot sahibinin kullanici yonetim komutlari.

    Donus: cevap metni; komut degilse None.
    /ekle <id> — yetkilendir (config'e kalici yazar)
    /sil <id>  — yetkiyi kaldir
    /liste     — yetkilileri listele
    """
    parts = text.split()
    cmd = (parts[0] if parts else "").split("@")[0].lower()
    if cmd not in ("/ekle", "/sil", "/liste"):
        return None
    if user_id not in admins:
        return "⛔ Bu komut sadece bot sahibine acik."
    if cmd == "/liste":
        if not allowed:
            return "Yetkili kullanici yok."
        satirlar = []
        for i in sorted(allowed):
            etiket = " (admin)" if i in admins else ""
            satirlar.append("- %d%s" % (i, etiket))
        return "Yetkili kullanicilar:\n" + "\n".join(satirlar)
    if len(parts) < 2 or not parts[1].lstrip("-").isdigit():
        return "Kullanim: /ekle <telegram_id>  ya da  /sil <telegram_id>\n(Kisinin ID'sini ogrenmesi icin ona /kimlik yazdir.)"
    new_id = int(parts[1])
    if cmd == "/ekle":
        if new_id in allowed:
            return "%d zaten yetkili." % new_id
        allowed.add(new_id)
        try:
            save_allowed_ids(cfg, allowed)
            return "✅ %d eklendi; artik botu kullanabilir." % new_id
        except Exception as e:
            return "⚠️ Eklendi ama config'e yazilamadi (%s); botu yeniden baslatmadan once elle ekle." % e
    if new_id not in allowed:
        return "%d listede yok." % new_id
    if new_id in admins:
        return "Kendini (admin) listeden cikaramazsin."
    allowed.discard(new_id)
    try:
        save_allowed_ids(cfg, allowed)
        return "❌ %d cikarildi; artık botu kullanamaz." % new_id
    except Exception as e:
        return "⚠️ Cikarildi ama config'e yazilamadi (%s)." % e


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

    # Bulut modundan donus: webhook varsa sil, laptop polling'e gecer.
    _ensure_polling(tg)

    runner = TaskRunner(cfg, tg)
    allowed = set(cfg.get("allowed_user_ids") or [])
    admins = set(cfg.get("admin_user_ids") or [])
    if not admins and len(allowed) == 1:
        # Tek yetkili kullanici varsa o, bot sahibi sayilir
        admins = set(allowed)
    if not admins:
        log.warning("admin_user_ids bos; /ekle /sil komutlari kullanilamaz.")

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

    offset_path = os.path.join(cfg["workspace"], "logs", "offset.txt")
    offset = _load_offset(offset_path)
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

            # Bot sahibi komutlari: /ekle /sil /liste /model /modeltest
            if cmd in ("/model", "/modeltest"):
                if user_id not in admins:
                    tg.send_message(chat_id, "⛔ Bu komut sadece bot sahibine acik.")
                    continue
                profiles = cfg.get("llm_profiles") or {}
                active = cfg.get("active_profile") or ""
                if cmd == "/modeltest":
                    tg.send_message(
                        chat_id,
                        "🧪 Aktif model test ediliyor: %s" % (active or cfg.get("llm", {}).get("model", "?")),
                    )
                    _test_llm_async(tg, chat_id, runner.llm, active or "aktif")
                    continue
                parca = text.split()
                if len(parca) == 1:
                    tg.send_message(chat_id, _model_list_text(cfg))
                    continue
                ad = parca[1].lower()
                if ad not in profiles:
                    tg.send_message(
                        chat_id,
                        "Boyle bir profil yok: %s\n\n%s" % (ad, _model_list_text(cfg)),
                    )
                    continue
                if ad == active:
                    tg.send_message(chat_id, "%s zaten aktif." % ad)
                    continue
                try:
                    save_llm_config(cfg, ad)
                    runner.set_llm(cfg["llm"])
                    tg.send_message(
                        chat_id,
                        "✅ Model değişti: %s (%s)\nYeni görevler artık bununla çalışır."
                        % (ad, cfg["llm"].get("model")),
                    )
                except Exception as e:
                    tg.send_message(chat_id, "❌ Model değiştirilemedi: %s" % e)
                continue

            cevap = _klasor_command(text, cfg, admins, user_id)
            if cevap is not None:
                tg.send_message(chat_id, cevap)
                continue

            cevap = _admin_command(text, cfg, allowed, admins, user_id)
            if cevap is not None:
                tg.send_message(chat_id, cevap)
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

        # Islenen batch'in offsetini diske yaz (restart korumasi)
        if updates:
            _save_offset(offset_path, offset)


if __name__ == "__main__":
    main()
