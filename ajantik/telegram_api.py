# -*- coding: utf-8 -*-
"""Ham Telegram Bot API istemcisi (ek kutuphane sadece 'requests').

telebot vb. kutuphaneler yerine ham API kullaniyoruz:
- 32-bit Debian'da uyumluluk riski sifir,
- RAM kullanimi cok dusuk,
- baglilik tek paket: requests.
"""

import json
import os
import time

import requests

from .utils import fmt_size, safe_name, split_text, truncate

API_BASE = "https://api.telegram.org/bot{token}/{method}"
FILE_BASE = "https://api.telegram.org/file/bot{token}/{file_path}"

# Bot API sinirlari: dosya INDIRME 20MB, GONDERME 50MB.
MAX_DOWNLOAD = 20 * 1024 * 1024
MAX_UPLOAD = 49 * 1024 * 1024


class TelegramError(Exception):
    pass


class TelegramAPI(object):
    def __init__(self, token):
        self.token = token
        self.session = requests.Session()

    # ------------------------------------------------------------------ #
    def _call(self, method, data=None, files=None, timeout=90):
        url = API_BASE.format(token=self.token, method=method)
        last_err = None
        for attempt in range(4):
            try:
                resp = self.session.post(url, data=data, files=files, timeout=timeout)
            except (requests.ConnectionError, requests.Timeout) as e:
                last_err = str(e)
                time.sleep(min(2 ** attempt * 2, 30))
                continue
            if resp.status_code == 429:
                wait = int(resp.headers.get("retry-after", "5")) + 1
                time.sleep(min(wait, 60))
                continue
            if resp.status_code >= 500:
                last_err = "HTTP %s" % resp.status_code
                time.sleep(3)
                continue
            try:
                body = resp.json()
            except ValueError:
                raise TelegramError("Beklenmeyen yanit (HTTP %s)" % resp.status_code)
            if not body.get("ok"):
                raise TelegramError(body.get("description") or ("HTTP %s" % resp.status_code))
            return body.get("result")
        raise TelegramError("Telegram'a ulasilamadi: %s" % last_err)

    # ------------------------------------------------------------------ #
    def get_me(self):
        return self._call("getMe")

    def get_updates(self, offset=0, timeout=30):
        data = {
            "offset": offset,
            "timeout": timeout,
            "allowed_updates": json.dumps(["message", "callback_query"]),
        }
        return self._call("getUpdates", data=data, timeout=timeout + 25)

    def send_message_with_buttons(self, chat_id, text, buttons):
        """Inline klavyeyle mesaj gonderir. buttons: [(etiket, callback_data), ...]"""
        kb = {"inline_keyboard": [[{"text": lbl, "callback_data": dat} for lbl, dat in buttons]]}
        data = {
            "chat_id": chat_id,
            "text": truncate(text, 3900),
            "reply_markup": json.dumps(kb),
        }
        result = self._call("sendMessage", data=data)
        return (result or {}).get("message_id")

    def answer_callback(self, callback_id, text=None):
        data = {"callback_query_id": callback_id}
        if text:
            data["text"] = truncate(text, 190)
        try:
            self._call("answerCallbackQuery", data=data)
        except TelegramError:
            pass

    def send_message(self, chat_id, text, reply_to=None):
        """Mesaj gonderir (4096 karakteri asarsa boler). Ilk mesaj id'si doner."""
        if not text:
            return None
        first_id = None
        for part in split_text(text, 3900):
            data = {
                "chat_id": chat_id,
                "text": part,
                "disable_web_page_preview": "true",
            }
            if reply_to is not None and first_id is None:
                data["reply_to_message_id"] = reply_to
            result = self._call("sendMessage", data=data)
            if first_id is None and result:
                first_id = result.get("message_id")
        return first_id

    def edit_message(self, chat_id, message_id, text):
        try:
            self._call(
                "editMessageText",
                {
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "text": truncate(text, 3900),
                },
            )
            return True
        except TelegramError as e:
            if "message is not modified" in str(e).lower():
                return True
            return False

    def send_document(self, chat_id, path, caption=None):
        """Dosya gonderir. Basari metni ya da 'HATA: ...' doner."""
        try:
            size = os.path.getsize(path)
        except OSError as e:
            return "HATA: dosya okunamadi: %s" % e
        if size > MAX_UPLOAD:
            return "HATA: dosya %s, Telegram siniri 50MB." % fmt_size(size)
        try:
            with open(path, "rb") as f:
                data = {"chat_id": chat_id}
                if caption:
                    data["caption"] = truncate(caption, 1000)
                self._call("sendDocument", data=data, files={"document": f}, timeout=600)
        except TelegramError as e:
            return "HATA: Telegram gonderemedi: %s" % e
        return "Dosya Telegram'a gonderildi (%s)." % fmt_size(size)

    def download(self, file_id, dest_dir):
        """Telegram'dan gelen dosyayi indirir. (path, boyut) doner."""
        info = self._call("getFile", {"file_id": file_id})
        file_path = info.get("file_path") or ""
        if file_path and file_path.startswith("/"):
            # Telegram bazen '/document/file_1.pdf' tarzi yol verir
            file_path = file_path.lstrip("/")
        url = FILE_BASE.format(token=self.token, file_path=file_path)
        os.makedirs(dest_dir, exist_ok=True)
        stamp = int(time.time() * 1000) % 100000000
        name = safe_name(os.path.basename(file_path) or ("dosya_%d" % stamp))
        dest = os.path.join(dest_dir, "%d_%s" % (stamp, name))
        resp = self.session.get(url, timeout=300, stream=True)
        resp.raise_for_status()
        total = 0
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(64 * 1024):
                if chunk:
                    f.write(chunk)
                    total += len(chunk)
                    if total > MAX_DOWNLOAD:
                        f.close()
                        os.remove(dest)
                        raise TelegramError("Dosya 20MB'den buyuk, Bot API indiremiyor.")
        return dest, total
