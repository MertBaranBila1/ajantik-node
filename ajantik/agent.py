# -*- coding: utf-8 -*-
"""Ajan dongusu: LLM <-> araclar.

Protokol saglayicidan bagimsizdir: modelden JSON ({"tool": ...} ya da
{"final": ...}) istenir; JSON bozuk gelirse model bir kez uyarilir.
"""

import json
import re

from . import tools as toolmod
from .llm import LLMError
from .prompts import build_system_prompt
from .utils import truncate

_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)
_MAX_JSON_RETRIES = 2


def parse_tool_call(text):
    """Model cevabini ayristirir.

    Donus:
      {"tool": ad, "args": {...}}  -> arac cagrisi
      {"final": metin}             -> gorev bitti
      None                         -> JSON yok, metnin kendisi final sayilir
    """
    t = (text or "").strip()
    if not t:
        return None
    candidates = []
    m = _JSON_BLOCK_RE.search(t)
    if m:
        candidates.append(m.group(1).strip())
    if t.startswith("{"):
        candidates.append(t)
    s, e = t.find("{"), t.rfind("}")
    if s != -1 and e > s:
        candidates.append(t[s : e + 1])
    for cand in candidates:
        try:
            d = json.loads(cand)
        except (ValueError, TypeError):
            continue
        if not isinstance(d, dict):
            continue
        if "tool" in d:
            args = d.get("args")
            if not isinstance(args, dict):
                args = {}
            return {"tool": str(d["tool"]), "args": args}
        if "final" in d:
            return {"final": str(d["final"])}
    return None


class AgentSession(object):
    """Bir Telegram sohbeti icin gorev oturumu."""

    def __init__(self, cfg, llm, tg, chat_id, history, approvals=None):
        self.cfg = cfg
        self.llm = llm
        self.chat_id = chat_id
        self.history = history  # ortak liste: [{"role":..,"content":..}, ...]
        self.system_prompt = build_system_prompt(cfg)
        self.max_iterations = int((cfg.get("agent") or {}).get("max_iterations") or 200)
        self.max_history = int((cfg.get("agent") or {}).get("max_history_messages") or 30)
        self.ctx = toolmod.ToolContext(cfg, tg, chat_id)
        self.ctx.approvals = approvals

    # ------------------------------------------------------------------ #
    def run(self, user_text):
        messages = [{"role": "system", "content": self.system_prompt}]
        messages += self._trimmed_history()
        messages.append({"role": "user", "content": user_text})

        json_retries = 0
        steps = []
        for i in range(self.max_iterations):
            reply = self.llm.chat(messages)
            messages.append({"role": "assistant", "content": reply})
            call = parse_tool_call(reply)

            if call is None:
                # Model JSON unuttu ya da bozuk gonderdi: bir kez uyar, tekrar dene.
                if json_retries < _MAX_JSON_RETRIES:
                    json_retries += 1
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                'UYARI: cevabin gecerli JSON degildi. SADECE su bicimlerden '
                                'biriyle cevap ver: {"tool": "...", "args": {...}} veya '
                                '{"final": "..."}.'
                            ),
                        }
                    )
                    continue
                final = reply.strip()
                self._remember(user_text, final)
                return final

            if "final" in call:
                final = call["final"].strip()
                self._remember(user_text, final)
                return final

            # Arac cagrisi
            tool_name = call["tool"]
            args = call["args"]
            steps.append(tool_name)
            self.ctx.status(
                "Adim %d: %s calisiyor..." % (i + 1, tool_name)
            )
            result = toolmod.run_tool(tool_name, args, self.ctx)
            messages.append(
                {"role": "user", "content": "ARAC_SONUCU (%s):\n%s" % (tool_name, result)}
            )

        final = (
            "Bu gorev cok uzun surdu (%d adim limitine ulastim) ve burada durdum. "
            "Simdiye kadarki adimlar: %s. Devam etmemi istersen sadece "
            "'devam et' yaz; kaldigim yerden surerim."
            % (self.max_iterations, ", ".join(steps[-40:]))
        )
        self._remember(user_text, final)
        return final

    # ------------------------------------------------------------------ #
    def _trimmed_history(self):
        limit = max(0, self.max_history) * 2  # user+assistant ciftleri
        if len(self.history) > limit:
            return self.history[-limit:]
        return list(self.history)

    def _remember(self, user_text, final):
        self.history.append({"role": "user", "content": truncate(user_text, 4000)})
        self.history.append({"role": "assistant", "content": truncate(final, 4000)})
        limit = max(0, self.max_history) * 2
        if len(self.history) > limit:
            del self.history[: len(self.history) - limit]
