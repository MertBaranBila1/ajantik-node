# -*- coding: utf-8 -*-
"""OpenAI-uyumlu /chat/completions istemcisi.

Bulut saglayicilar (OpenRouter, OpenAI, Groq, DeepSeek...) VEYA lokal
sunucular (Ollama, llama.cpp server, vLLM...) ile calisir — config'de
llm.base_url + llm.model yeterli.
"""

import json
import time

import requests


class LLMError(Exception):
    pass


class LLMClient(object):
    def __init__(self, conf):
        conf = conf or {}
        self.base_url = (conf.get("base_url") or "").rstrip("/")
        self.api_key = conf.get("api_key") or ""
        self.model = conf.get("model") or ""
        self.temperature = conf.get("temperature", 0.2)
        self.timeout = int(conf.get("timeout_seconds") or 600)
        self.session = requests.Session()
        if self.api_key:
            self.session.headers["Authorization"] = "Bearer " + self.api_key

    def chat(self, messages):
        if not self.base_url or not self.model:
            raise LLMError(
                "LLM ayari eksik: config.json icinde llm.base_url ve llm.model doldurulmali."
            )
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
        }
        err = None
        for attempt in range(3):
            try:
                resp = self.session.post(
                    self.base_url + "/chat/completions", json=payload, timeout=self.timeout
                )
            except (requests.ConnectionError, requests.Timeout) as e:
                err = str(e)
                time.sleep(3 * (attempt + 1))
                continue
            if resp.status_code in (429, 500, 502, 503, 504):
                err = "HTTP %s" % resp.status_code
                time.sleep(5 * (attempt + 1))
                continue
            if resp.status_code == 401:
                raise LLMError("API anahtari reddedildi (401). llm.api_key kontrol et.")
            if resp.status_code == 404:
                raise LLMError("Model/endpoint bulunamadi (404). llm.base_url ve llm.model kontrol et.")
            if resp.status_code >= 400:
                try:
                    detail = resp.json().get("error", {}).get("message", resp.text[:300])
                except Exception:
                    detail = resp.text[:300]
                raise LLMError("LLM hatasi (HTTP %s): %s" % (resp.status_code, detail))
            try:
                data = resp.json()
            except ValueError:
                raise LLMError("LLM yaniti JSON degil.")
            try:
                content = data["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError):
                raise LLMError(
                    "LLM yaniti beklenen bicimde degil: "
                    + json.dumps(data, ensure_ascii=False)[:300]
                )
            return content or ""
        raise LLMError("LLM'e ulasilamadi: %s" % err)
