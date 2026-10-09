# -*- coding: utf-8 -*-
"""Telegram uzerinden Evet/Hayir onayi (inline keyboard).

Ajan sistem degistiren komutlar (apt, pip, sudo...) calistirmadan once
kullaniciya sorar; cevap butondan gelince bekleyen gorev devam eder.
Ana dongu (getUpdates) callback_query olaylarini buraya yonlendirir.
"""

import threading
import uuid


class ApprovalManager(object):
    def __init__(self, tg):
        self.tg = tg
        self._pending = {}  # rid -> {"event", "result", "chat_id", "msg_id", "question"}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ #
    def request(self, chat_id, question, timeout=300):
        """Evet/Hayir sorusu gonderir ve cevabi bekler.

        Donus: True (evet) / False (hayir) / None (zaman asimi).
        Gorev thread'inden cagirilir; ana dongu burada bloklanmaz.
        """
        rid = uuid.uuid4().hex[:12]
        ev = threading.Event()
        with self._lock:
            self._pending[rid] = {
                "event": ev,
                "result": None,
                "chat_id": chat_id,
                "msg_id": None,
                "question": question,
            }
        try:
            mid = self.tg.send_message_with_buttons(
                chat_id,
                question,
                [("✅ Evet", "ok:" + rid), ("⛔ Hayır", "no:" + rid)],
            )
            with self._lock:
                if rid in self._pending:
                    self._pending[rid]["msg_id"] = mid
        except Exception:
            with self._lock:
                self._pending.pop(rid, None)
            return None

        answered = ev.wait(timeout)
        with self._lock:
            item = self._pending.pop(rid, None)
        if not answered or not item or item["result"] is None:
            if item and item.get("msg_id"):
                self.tg.edit_message(
                    item["chat_id"], item["msg_id"],
                    "⌛ Onay zamanaşımı:\n" + (item["question"] or "")[:1500],
                )
            return None
        return bool(item["result"])

    # ------------------------------------------------------------------ #
    def resolve(self, data, user_id):
        """Ana donguden cagirilir. data: 'ok:<rid>' ya da 'no:<rid>'."""
        if not data or ":" not in data:
            return False
        verdict, rid = data.split(":", 1)
        if verdict not in ("ok", "no"):
            return False
        with self._lock:
            item = self._pending.get(rid)
            if not item:
                return False
            item["result"] = (verdict == "ok")
            ev = item["event"]
            mid = item.get("msg_id")
            chat_id = item.get("chat_id")
        ev.set()
        # Buton mesajini guncelle (kalicilik icin)
        if mid:
            mark = "✅ ONAYLANDI" if verdict == "ok" else "⛔ REDDEDİLDİ"
            self.tg.edit_message(
                chat_id, mid, mark + " (kullanıcı: %s)\n" % user_id + (item.get("question") or "")[:1200]
            )
        return True

    def pending_count(self):
        with self._lock:
            return len(self._pending)
