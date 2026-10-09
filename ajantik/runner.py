# -*- coding: utf-8 -*-
"""Gorev kuyrugu: Telegram mesajlari sirayi isleyen tek worker thread'e duser.

Tek cekirdek makinede ayni anda tek gorev calisir; sirada bekleyenlere
"onunde is var" bilgisi gider. Ana dongu (long polling) hic bloklanmaz.
"""

import logging
import queue
import threading
import time

from .agent import AgentSession
from .approvals import ApprovalManager
from .llm import LLMClient, LLMError
from .tools import sys_info_str

log = logging.getLogger("ajantik.runner")


class TaskRunner(object):
    def __init__(self, cfg, tg):
        self.cfg = cfg
        self.tg = tg
        self.llm = LLMClient(cfg.get("llm"))
        self.approvals = ApprovalManager(tg)
        self.q = queue.Queue()
        self.sessions = {}  # chat_id -> history listesi
        self._sessions_lock = threading.Lock()
        self._busy = False
        self._busy_lock = threading.Lock()
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    # ------------------------------------------------------------------ #
    def enqueue(self, chat_id, user_id, text):
        with self._busy_lock:
            busy = self._busy
        if busy or not self.q.empty():
            self.tg.send_message(
                chat_id,
                "⏳ Onunde %d is var; siraya eklendin." % (self.q.qsize() + (1 if busy else 0)),
            )
        self.q.put({"chat_id": chat_id, "user_id": user_id, "text": text})

    def reset(self, chat_id):
        with self._sessions_lock:
            self.sessions[chat_id] = []
        return True

    def queue_len(self):
        with self._busy_lock:
            return self.q.qsize() + (1 if self._busy else 0)

    # ------------------------------------------------------------------ #
    def _worker(self):
        while True:
            task = self.q.get()
            with self._busy_lock:
                self._busy = True
            try:
                self._run_task(task)
            except Exception:
                log.exception("Gorev patladi: %r", task)
                try:
                    self.tg.send_message(task["chat_id"], "❌ Beklenmeyen bir hata oldu; kayitlara baktim, tekrar dener misin?")
                except Exception:
                    pass
            finally:
                with self._busy_lock:
                    self._busy = False
                self.q.task_done()

    def _history(self, chat_id):
        with self._sessions_lock:
            if chat_id not in self.sessions:
                self.sessions[chat_id] = []
            return self.sessions[chat_id]

    def _run_task(self, task):
        chat_id = task["chat_id"]
        mid = self.tg.send_message(chat_id, "🤖 Gorev alindi, calisiyorum...")
        if not mid:
            mid = None
        history = self._history(chat_id)
        agent = AgentSession(self.cfg, self.llm, self.tg, chat_id, history, approvals=self.approvals)
        state = {"last": 0.0}

        def status(text):
            now = time.monotonic()
            if now - state["last"] < 3.0:
                return
            state["last"] = now
            if mid:
                self.tg.edit_message(chat_id, mid, "⏳ " + text)

        agent.ctx.status_cb = status
        try:
            final = agent.run(task["text"])
            if mid:
                self.tg.edit_message(chat_id, mid, "✅ Gorev tamamlandi.")
            self.tg.send_message(chat_id, final or "(bos cevap)")
        except LLMError as e:
            if mid:
                self.tg.edit_message(chat_id, mid, "❌ Beyne (LLM) ulasilamadi.")
            self.tg.send_message(chat_id, "❌ LLM hatasi: %s" % e)
        except Exception as e:
            log.exception("Ajan dongusu hatasi")
            if mid:
                self.tg.edit_message(chat_id, mid, "❌ Hata oldu.")
            self.tg.send_message(chat_id, "❌ Hata: %r" % e)

    # ------------------------------------------------------------------ #
    def status_text(self):
        busy = "meşgul" if self.queue_len() > 0 else "boşta"
        pending = self.approvals.pending_count()
        onay = ("\n⏳ Cevap beklenen onay sorusu: %d (butonla yanıtla!)" % pending) if pending else ""
        return "Kuyruk: %d iş (%s)%s\n\n%s" % (self.queue_len(), busy, onay, sys_info_str())
