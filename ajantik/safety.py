# -*- coding: utf-8 -*-
"""Guvenlik: tehlikeli komut filtresi + dosya yolu sinirlamasi."""

import os
import re

# Temel koruma: sistemi tamamen kilitleyecek/silecek komutlar.
# Not: liste tam bir koruma degil; botu yine de sadece guvendigin
# kisilerin Telegram ID'sine ac (config: allowed_user_ids).
DANGEROUS_PATTERNS = [
    r"\brm\s+(?:-{1,2}[a-zA-Z]+\s+)*?(?:/|/\*|~|~/\*|\$HOME)(?:\s|$)",  # rm -rf / , rm -rf ~
    r"\bmkfs\b",
    r"\bdd\b[^|;&]*\bof=/dev/",
    r"\b(shutdown|reboot|halt|poweroff)\b",
    r"\binit\s+[06]\b",
    r":\(\)\s*\{.*\}\s*;\s*:",  # fork bomb
    r">\s*/dev/sd",
    r"\bchmod\s+-R\s+[0-7]*7[0-7]*\s+/(?:\s|$)",
    r"\bcurl\b[^|]*\|\s*(ba)?sh\b",
    r"\bwget\b[^|]*\|\s*(ba)?sh\b",
]
_DANGEROUS_RE = [re.compile(p, re.IGNORECASE | re.DOTALL) for p in DANGEROUS_PATTERNS]


def is_dangerous(cmd):
    if not cmd:
        return False
    if len(cmd) > 8000:
        return True
    for rx in _DANGEROUS_RE:
        if rx.search(cmd):
            return True
    return False


def normalize_path(path):
    return os.path.realpath(os.path.abspath(os.path.expanduser(path)))


def _within(path, root):
    path = normalize_path(path)
    root = normalize_path(root)
    return path == root or path.startswith(root + os.sep)


def resolve_path(path, workspace, allowed_dirs):
    """Dosya araclari icin yol cozumleme.

    - Goreli yollar workspace icine cozulur.
    - Mutlak yollar sadece workspace + allowed_dirs icinde kabul edilir.
    - Disarida kalirsa None doner (arac 'izin yok' hatasi verir).
    """
    if not path or not isinstance(path, str):
        return None
    path = os.path.expanduser(path)
    if not os.path.isabs(path):
        path = os.path.join(workspace, path)
    for root in [workspace] + list(allowed_dirs or []):
        if _within(path, root):
            return normalize_path(path)
    return None
