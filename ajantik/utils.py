# -*- coding: utf-8 -*-
"""Kucuk yardimcilar."""

import os
import re
import unicodedata


def fmt_size(n):
    try:
        n = float(n)
    except (TypeError, ValueError):
        return "?"
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            if unit == "B":
                return "%d %s" % (n, unit)
            return "%.1f %s" % (n, unit)
        n /= 1024.0
    return "%s" % n


def truncate(text, limit):
    text = str(text)
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...(cok uzun, kirpildi)"


def split_text(text, limit):
    text = str(text)
    if not text:
        return []
    if len(text) <= limit:
        return [text]
    parts = []
    while text:
        parts.append(text[:limit])
        text = text[limit:]
    return parts


def safe_name(name):
    """Dosya adi: yol ayiricilarini ve sorunlu karakterleri temizler."""
    name = os.path.basename(str(name or ""))
    try:
        name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    except Exception:
        pass
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    return (name or "dosya")[:120]
