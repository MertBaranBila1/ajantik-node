# -*- coding: utf-8 -*-
"""Ayar yukleme: config.json + makul varsayilanlar."""

import json
import os

DEFAULTS = {
    "telegram_token": "",
    "llm": {
        "base_url": "",
        "api_key": "",
        "model": "",
        "temperature": 0.2,
        "timeout_seconds": 180,
    },
    "allowed_user_ids": [],
    "workspace": "./workspace",
    "allowed_dirs": [],
    "ssh_hosts": {},
    "agent": {
        "max_iterations": 15,
        "command_timeout_seconds": 180,
        "max_history_messages": 30,
        "block_dangerous_commands": True,
    },
    "max_download_mb": 200,
    "personality": "",
}


def _merge(base, extra):
    out = dict(base)
    for k, v in (extra or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path):
    """config.json okur, eksik alanlari varsayilanla tamamlar.

    workspace ve allowed_dirs yollari, config dosyasinin bulundugu klasore
    gore mutlak hale getirilir (systemd altinda calisirken de dogru olur).
    """
    data = {}
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    cfg = _merge(DEFAULTS, data)
    cfg["_path"] = os.path.abspath(path)
    base_dir = os.path.dirname(os.path.abspath(path))

    ws = cfg.get("workspace") or "./workspace"
    if not os.path.isabs(ws):
        ws = os.path.join(base_dir, ws)
    cfg["workspace"] = os.path.abspath(ws)

    roots = []
    for d in cfg.get("allowed_dirs") or []:
        if not os.path.isabs(d):
            d = os.path.join(base_dir, d)
        roots.append(os.path.abspath(d))
    cfg["allowed_dirs"] = roots

    cfg["allowed_user_ids"] = [int(x) for x in cfg.get("allowed_user_ids") or []]
    return cfg
