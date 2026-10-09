# -*- coding: utf-8 -*-
"""Ajan araclarinin uygulanmasi.

Her arac: fn(args: dict, ctx: ToolContext) -> str  (modele geri giden sonuc metni).
Guvenlik:
- Dosya araclarindaki yollar workspace + allowed_dirs ile sinirlidir.
- run_command icin kara liste filtresi + zaman asimi + cikti kirpma.
- run_ssh sadece config'de tanimli sunucularda calisir.
"""

import os
import re
import subprocess
import time
import zipfile
from datetime import datetime
from urllib.parse import urlparse

import requests

from . import safety
from .utils import fmt_size, safe_name, truncate


class ToolContext(object):
    """Bir gorev boyunca araclara gecen baglam."""

    def __init__(self, cfg, tg, chat_id):
        self.cfg = cfg
        self.tg = tg
        self.chat_id = chat_id
        self.workspace = cfg["workspace"]
        self.allowed_dirs = cfg.get("allowed_dirs") or []
        agent = cfg.get("agent") or {}
        self.cmd_timeout = int(agent.get("command_timeout_seconds") or 180)
        self.block_dangerous = bool(agent.get("block_dangerous_commands", True))
        self.confirm_installs = bool(agent.get("confirm_installs", True))
        self.ssh_hosts = cfg.get("ssh_hosts") or {}
        self.max_download_mb = int(cfg.get("max_download_mb") or 200)
        self.status_cb = None   # runner tarafindan set edilir
        self.approvals = None   # runner tarafindan set edilir (ApprovalManager)

    def status(self, text):
        if self.status_cb:
            try:
                self.status_cb(text)
            except Exception:
                pass

    def resolve(self, path):
        return safety.resolve_path(path, self.workspace, self.allowed_dirs)


# ---------------------------------------------------------------------- #
# Sistem bilgisi (hem arac hem /status komutu icin)
# ---------------------------------------------------------------------- #

def sys_info_str():
    lines = []
    try:
        with open("/proc/loadavg", "r") as f:
            lines.append("Yuk (1/5/15dk): " + f.read().strip())
    except Exception:
        pass
    try:
        info = {}
        with open("/proc/meminfo", "r") as f:
            for ln in f:
                parts = ln.split(":", 1)
                if len(parts) == 2:
                    info[parts[0]] = int(parts[1].strip().split()[0])
        total = info.get("MemTotal", 0)
        avail = info.get("MemAvailable", 0)
        if total:
            used = total - avail
            lines.append(
                "RAM: %s / %s kullaniliyor"
                % (fmt_size(used * 1024), fmt_size(total * 1024))
            )
    except Exception:
        pass
    try:
        import shutil

        du = shutil.disk_usage("/")
        lines.append(
            "Disk (/): %s bos / %s toplam" % (fmt_size(du.free), fmt_size(du.total))
        )
    except Exception:
        pass
    try:
        with open("/proc/uptime", "r") as f:
            secs = float(f.read().split()[0])
            days, rem = divmod(int(secs), 86400)
            hours, rem = divmod(rem, 3600)
            mins = rem // 60
            lines.append("Acik kalma: %dg %ds %ddk" % (days, hours, mins))
    except Exception:
        pass
    try:
        import platform

        lines.append("Sistem: " + platform.platform())
    except Exception:
        pass
    return "\n".join(lines) or "Sistem bilgisi alinamadi."


# ---------------------------------------------------------------------- #
# Onay gerektiren komutlar (kullaniciya Evet/Hayir sorulur)
# ---------------------------------------------------------------------- #

CONFIRM_PATTERNS = [
    r"\bsudo\b",
    r"\bapt(?:-get)?\s+(?:install|remove|purge|upgrade|update|full-upgrade)\b",
    r"\bdpkg\s+(?:-i|--install|--remove|--purge)\b",
    r"\bpip3?\s+install\b",
    r"\bnpm\s+(?:install|i|add)\b",
    r"\bpnpm\s+(?:install|add)\b",
    r"\byarn\s+(?:add|install)\b",
    r"\bsnap\s+(?:install|remove)\b",
    r"\bgem\s+install\b",
    r"\bcargo\s+install\b",
    r"\bmake\s+install\b",
    r"\bsystemctl\s+(?:start|stop|restart|reload|enable|disable)\b",
]
_CONFIRM_RE = [re.compile(p, re.IGNORECASE) for p in CONFIRM_PATTERNS]


def _needs_confirm(cmd):
    return any(rx.search(cmd or "") for rx in _CONFIRM_RE)


# ---------------------------------------------------------------------- #
# Araclar
# ---------------------------------------------------------------------- #

def tool_run_command(args, ctx):
    cmd = args.get("command")
    if not cmd or not isinstance(cmd, str):
        return "HATA: 'command' argumani gerekli."
    if ctx.block_dangerous and safety.is_dangerous(cmd):
        return "RED: Bu komut guvenlik filtresine takildi (sistem yikici komut)."
    if ctx.confirm_installs and ctx.approvals and _needs_confirm(cmd):
        verdict = ctx.approvals.request(
            ctx.chat_id,
            "⚠️ Ajan şu komutu çalıştırmak istiyor. Onaylıyor musun?\n\n"
            + truncate(cmd, 1200),
            timeout=300,
        )
        if verdict is None:
            return "RED: Onay zamanaşımı (5 dk) — komut çalıştırılmadı."
        if not verdict:
            return "RED: Kullanıcı bu komutu onaylamadı."
    _audit_log(ctx, cmd)
    ctx.status("Komut calistiriliyor: " + truncate(cmd, 80))
    try:
        p = subprocess.run(
            cmd,
            shell=True,
            cwd=ctx.workspace,
            capture_output=True,
            timeout=ctx.cmd_timeout,
        )
    except subprocess.TimeoutExpired:
        return "HATA: komut %d saniyede bitmedi (zaman asimi)." % ctx.cmd_timeout
    except Exception as e:
        return "HATA: komut calistirilamadi: %s" % e
    out = (p.stdout or b"") + (p.stderr or b"")
    out = out.decode("utf-8", "replace").strip()
    if len(out) > 4000:
        out = out[:4000] + "\n...(cikti kirpildi, toplam %d karakter)" % len(out)
    return "exit_code=%s\n%s" % (p.returncode, out or "(cikti yok)")


def tool_read_file(args, ctx):
    path = ctx.resolve(args.get("path"))
    if not path:
        return _deny(args.get("path"))
    if not os.path.isfile(path):
        return "HATA: dosya yok: %s" % args.get("path")
    if os.path.getsize(path) > 2 * 1024 * 1024:
        return "HATA: dosya 2MB'den buyuk; run_command ile isle ya da parca oku."
    try:
        with open(path, "rb") as f:
            head = f.read(1024)
        if b"\x00" in head:
            return "HATA: bu ikili (binary) dosya; read_file okuyamaz."
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except Exception as e:
        return "HATA: okunamadi: %s" % e
    return "DOSYA: %s\n%s" % (path, truncate(content, 8000))


def tool_write_file(args, ctx):
    path = ctx.resolve(args.get("path"))
    content = args.get("content")
    if not path:
        return _deny(args.get("path"))
    if content is None or not isinstance(content, str):
        return "HATA: 'content' argumani gerekli."
    if len(content) > 2 * 1024 * 1024:
        return "HATA: icerik 2MB'den buyuk olamaz."
    backup = args.get("backup", True)
    bak = None
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if backup and os.path.exists(path):
            bak = path + ".yedek-" + datetime.now().strftime("%Y%m%d-%H%M%S")
            with open(path, "rb") as src, open(bak, "wb") as dst:
                dst.write(src.read())
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
    except Exception as e:
        return "HATA: yazilamadi: %s" % e
    note = ""
    if bak:
        note = "\nEski surum yedeklendi: " + bak
    return "Yazildi: %s (%s)%s" % (path, fmt_size(len(content)), note)


def tool_list_dir(args, ctx):
    raw = args.get("path") or "."
    path = ctx.resolve(raw)
    if not path:
        return _deny(raw)
    if not os.path.isdir(path):
        return "HATA: klasor yok: %s" % raw
    items = []
    try:
        for name in sorted(os.listdir(path))[:200]:
            full = os.path.join(path, name)
            if os.path.isdir(full):
                items.append("[D] " + name)
            else:
                try:
                    items.append("%s  %s" % (fmt_size(os.path.getsize(full)), name))
                except OSError:
                    items.append("?  " + name)
    except Exception as e:
        return "HATA: listelenemedi: %s" % e
    if not items:
        return "(klasor bos): " + path
    return "KLASOR: %s\n%s" % (path, "\n".join(items[:200]))


def tool_search_text(args, ctx):
    pattern = args.get("pattern")
    if not pattern:
        return "HATA: 'pattern' argumani gerekli."
    raw = args.get("path") or "."
    root = ctx.resolve(raw)
    if not root:
        return _deny(raw)
    try:
        rx = re.compile(pattern)
    except re.error as e:
        return "HATA: gecersiz regex: %s" % e
    hits = []
    scanned = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d != "__pycache__"]
        for fn in filenames:
            full = os.path.join(dirpath, fn)
            scanned += 1
            if scanned > 4000:
                return truncate(
                    "Tarama 4000 dosyada kesildi. Sonuclar:\n" + "\n".join(hits), 6000
                )
            try:
                if os.path.getsize(full) > 256 * 1024:
                    continue
                with open(full, "rb") as f:
                    blob = f.read()
                if b"\x00" in blob[:1024]:
                    continue
                for i, line in enumerate(blob.decode("utf-8", "replace").splitlines()):
                    if rx.search(line):
                        hits.append("%s:%d: %s" % (full, i + 1, line.strip()[:200]))
                        if len(hits) >= 40:
                            return truncate("\n".join(hits), 6000)
                        break  # dosya basina 1 eslesme
            except OSError:
                continue
    if not hits:
        return "Eslesme bulunamadi: /%s/ ( %s )" % (pattern, root)
    return truncate("\n".join(hits), 6000)


def tool_zip_files(args, ctx):
    raw_paths = args.get("paths") or []
    if isinstance(raw_paths, str):
        raw_paths = [raw_paths]
    if not raw_paths:
        return "HATA: 'paths' listesi gerekli (dosya ya da klasorler)."
    zip_name = safe_name(args.get("zip_name") or ("arsiv-%s.zip" % datetime.now().strftime("%Y%m%d-%H%M%S")))
    if not zip_name.lower().endswith(".zip"):
        zip_name += ".zip"
    out_dir = os.path.join(ctx.workspace, "outputs")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, zip_name)
    count = 0
    missing = []
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for raw in raw_paths:
            p = ctx.resolve(str(raw))
            if not p:
                missing.append("%s (izin yok)" % raw)
                continue
            if not os.path.exists(p):
                missing.append("%s (yok)" % raw)
                continue
            base = os.path.basename(p.rstrip("/\\")) or "icerik"
            if os.path.isfile(p):
                zf.write(p, base)
                count += 1
            else:
                for dirpath, dirnames, filenames in os.walk(p):
                    for fn in filenames:
                        full = os.path.join(dirpath, fn)
                        arc = os.path.join(base, os.path.relpath(full, p))
                        try:
                            zf.write(full, arc)
                            count += 1
                        except OSError:
                            pass
    msg = "ZIP hazir: %s (%s, %d dosya)" % (out_path, fmt_size(os.path.getsize(out_path)), count)
    if missing:
        msg += "\nEKLENEMEYENLER: " + ", ".join(missing)
    if count == 0:
        os.remove(out_path)
        return "HATA: zip'e eklenebilir dosya yok.\n" + msg
    return msg


def tool_send_file(args, ctx):
    raw = args.get("path")
    p = ctx.resolve(raw)
    if not p:
        return _deny(raw)
    if not os.path.exists(p):
        return "HATA: dosya yok: %s" % raw
    ctx.status("Dosya gonderiliyor: " + truncate(p, 80))
    result = ctx.tg.send_document(ctx.chat_id, p, caption=args.get("caption"))
    return result


def tool_download_file(args, ctx):
    url = args.get("url")
    if not url or not isinstance(url, str):
        return "HATA: 'url' argumani gerekli."
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return "HATA: sadece http/https linkler destekleniyor."
    filename = safe_name(args.get("filename") or os.path.basename(parsed.path) or "")
    if not filename or filename == "dosya":
        filename = "indirilen-%s" % datetime.now().strftime("%Y%m%d-%H%M%S")
    dest_dir = os.path.join(ctx.workspace, "downloads")
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, filename)
    i = 1
    while os.path.exists(dest):
        dest = os.path.join(dest_dir, "%d-%s" % (i, filename))
        i += 1
    limit = ctx.max_download_mb * 1024 * 1024
    try:
        with ctx.tg.session.get(url, timeout=300, stream=True) as r:
            r.raise_for_status()
            total = 0
            with open(dest, "wb") as f:
                for chunk in r.iter_content(64 * 1024):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > limit:
                        f.close()
                        os.remove(dest)
                        return "HATA: dosya %dMB sinirini asti." % ctx.max_download_mb
                    f.write(chunk)
    except Exception as e:
        if os.path.exists(dest):
            try:
                os.remove(dest)
            except OSError:
                pass
        return "HATA: indirilemedi: %s" % e
    return "Indirildi: %s (%s)" % (dest, fmt_size(os.path.getsize(dest)))


def tool_run_ssh(args, ctx):
    host_key = args.get("host")
    command = args.get("command")
    if not host_key or not command:
        return "HATA: 'host' ve 'command' argumanlari gerekli."
    conf = ctx.ssh_hosts.get(host_key)
    if not conf:
        return (
            "HATA: '%s' tanimli bir SSH sunucusu degil. Tanimlar config.json > ssh_hosts "
            "bolumunde (guvenlik icin sadece orada yazili sunuculara baglanilabilir)." % host_key
        )
    user = conf.get("user") or "root"
    host = conf.get("host") or host_key
    port = str(conf.get("port") or 22)
    cmd = [
        "ssh",
        "-p", port,
        "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "ConnectTimeout=15",
        "%s@%s" % (user, host),
        command,
    ]
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=ctx.cmd_timeout)
    except FileNotFoundError:
        return "HATA: ssh komutu yok (apt install openssh-client)."
    except subprocess.TimeoutExpired:
        return "HATA: SSH komutu zaman asimina ugradi."
    out = (p.stdout or b"") + (p.stderr or b"")
    out = out.decode("utf-8", "replace").strip()
    return "exit_code=%s\n%s" % (p.returncode, truncate(out, 4000) or "(cikti yok)")


def tool_sys_info(args, ctx):
    return sys_info_str()


# ---------------------------------------------------------------------- #
# GitHub baglantisi (device flow: kullanici telefonda kod girer)
# ---------------------------------------------------------------------- #

GH_CLIENT_ID = "178c6fc778ccc68e1d6a"  # gh CLI'nin herkese acik OAuth client id'si
GH_TOKEN_FILENAME = ".github_token"


def _gh_token_path(workspace):
    return os.path.join(workspace, GH_TOKEN_FILENAME)


def _gh_load_token(workspace):
    path = _gh_token_path(workspace)
    try:
        with open(path, "r", encoding="utf-8") as f:
            tok = f.read().strip()
        return tok or None
    except OSError:
        return None


def _gh_login(token):
    """Token'i dogrular; kullanici adini ya da None dondurur."""
    try:
        r = requests.get(
            "https://api.github.com/user",
            headers={"Authorization": "token " + token, "Accept": "application/vnd.github+json"},
            timeout=30,
        )
        if r.status_code != 200:
            return None
        return (r.json() or {}).get("login")
    except Exception:
        return None


def _git_setup_credentials(token):
    """git push/pull icin credential store kurar (~/.git-credentials)."""
    try:
        subprocess.run(
            ["git", "config", "--global", "credential.helper", "store"],
            capture_output=True, timeout=30,
        )
    except Exception:
        pass
    cred_path = os.path.expanduser("~/.git-credentials")
    line = "https://x-access-token:%s@github.com" % token
    lines = []
    try:
        if os.path.exists(cred_path):
            with open(cred_path, "r", encoding="utf-8") as f:
                lines = [ln.strip() for ln in f if ln.strip() and "@github.com" not in ln]
    except OSError:
        lines = []
    lines.append(line)
    try:
        with open(cred_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        os.chmod(cred_path, 0o600)
    except OSError:
        pass


def setup_github_token(cfg, token):
    """Config'de verilen token'i diske yazar + git credential kurar (main'de cagirilir)."""
    workspace = cfg["workspace"]
    os.makedirs(workspace, exist_ok=True)
    try:
        with open(_gh_token_path(workspace), "w", encoding="utf-8") as f:
            f.write(token.strip())
        os.chmod(_gh_token_path(workspace), 0o600)
    except OSError:
        pass
    _git_setup_credentials(token.strip())


def tool_github_connect(args, ctx):
    """GitHub device-flow baglantisi: kod gonderir, kullanicinin girmesini bekler."""
    token = _gh_load_token(ctx.workspace)
    if token:
        login = _gh_login(token)
        if login:
            return (
                "Zaten bagli: %s. (Baska hesaba gecmek istersen once bana soyle; "
                "token'i temizlerim.)" % login
            )
    try:
        r = requests.post(
            "https://github.com/login/device/code",
            data={"client_id": GH_CLIENT_ID, "scope": "repo"},
            headers={"Accept": "application/json"},
            timeout=30,
        )
        r.raise_for_status()
        d = r.json()
    except Exception as e:
        return "HATA: GitHub'dan baglanti kodu alinamadi: %s" % e
    user_code = d.get("user_code") or "?"
    uri = d.get("verification_uri") or "https://github.com/login/device"
    interval = max(3, int(d.get("interval") or 5))
    expires = int(d.get("expires_in") or 900)
    device_code = d.get("device_code") or ""
    ctx.tg.send_message(
        ctx.chat_id,
        "🔐 GitHub bağlantısı:\n"
        "1) Şu adresi aç (telefonundan olur): %s\n"
        "2) Bu kodu gir: %s\n"
        "Kod %d dakika geçerli. Girdikten sonra burada otomatik devam edeceğim..."
        % (uri, user_code, max(1, expires // 60)),
    )
    deadline = time.time() + expires
    while time.time() < deadline:
        time.sleep(interval)
        try:
            r = requests.post(
                "https://github.com/login/oauth/access_token",
                data={
                    "client_id": GH_CLIENT_ID,
                    "device_code": device_code,
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                },
                headers={"Accept": "application/json"},
                timeout=30,
            )
            d = r.json()
        except Exception:
            continue
        if "access_token" in d and d.get("access_token"):
            token = d["access_token"]
            login = _gh_login(token)
            if not login:
                return "HATA: token alindi ama dogrulanamadi; tekrar dene."
            try:
                with open(_gh_token_path(ctx.workspace), "w", encoding="utf-8") as f:
                    f.write(token)
                os.chmod(_gh_token_path(ctx.workspace), 0o600)
            except OSError:
                pass
            _git_setup_credentials(token)
            return (
                "GitHub baglandi: %s\nArtik git clone/push (https) komutlari "
                "calisir. Ornek: git clone https://github.com/<kullanici>/<repo>.git" % login
            )
        err = d.get("error")
        if err == "authorization_pending":
            continue
        if err == "slow_down":
            interval += 5
            continue
        return "HATA: GitHub baglantisi kurulamadi (%s). Kullanici kodu girmeden mi dendi, tekrar dene." % err
    return "HATA: Sure doldu, kod girilmedi gibi gorunuyor. Kullanici hazirsa tekrar dene."


def tool_github_status(args, ctx):
    token = _gh_load_token(ctx.workspace)
    if not token:
        return "GitHub bagli DEGIL. Once github_connect aracini kullan."
    login = _gh_login(token)
    if not login:
        return "Token gecersiz gorunuyor. Yeniden baglamak icin github_connect kullan (once eski token'i sil)."
    return "GitHub bagli: %s" % login


def tool_ask_user(args, ctx):
    question = args.get("question")
    if not question or not isinstance(question, str):
        return "HATA: 'question' argumani gerekli."
    if not ctx.approvals:
        return "HATA: onay sistemi su an kullanilamiyor."
    verdict = ctx.approvals.request(ctx.chat_id, "❓ " + question, timeout=600)
    if verdict is None:
        return "Kullanici cevaplamadi (zaman asimi). Durumu kullaniciya anlat; varsayimla ilerleme."
    return "Kullanici cevabi: " + ("EVET" if verdict else "HAYIR")


# ---------------------------------------------------------------------- #
# Kayit + yardimcilar
# ---------------------------------------------------------------------- #

def _deny(raw):
    return (
        "HATA: '%s' yoluna izin yok. Dosya islemleri sadece workspace ve "
        "config.json > allowed_dirs ile acilan klasorlerde calisir." % raw
    )


def _audit_log(ctx, cmd):
    try:
        log_dir = os.path.join(ctx.workspace, "logs")
        os.makedirs(log_dir, exist_ok=True)
        with open(os.path.join(log_dir, "komutlar.log"), "a", encoding="utf-8") as f:
            f.write("[%s] chat=%s: %s\n" % (datetime.now().isoformat(), ctx.chat_id, cmd.replace("\n", " ")[:500]))
    except Exception:
        pass


TOOLS = {
    "run_command": {
        "fn": tool_run_command,
        "desc": "Bilgisayarda kabuk (shell) komutu calistirir. ciktiyi dondurur.",
        "args": '{"command": "<komut>"}',
    },
    "read_file": {
        "fn": tool_read_file,
        "desc": "Metin dosyasi okur (2MB siniri, binary reddedilir).",
        "args": '{"path": "<dosya yolu>"}',
    },
    "write_file": {
        "fn": tool_write_file,
        "desc": "Metin dosya yazar. Varsa once .yedek-<tarih> kopyasi olusturur.",
        "args": '{"path": "<yol>", "content": "<tum icerik>", "backup": true}',
    },
    "list_dir": {
        "fn": tool_list_dir,
        "desc": "Klasor icerigini listeler (boyutlarla).",
        "args": '{"path": "<klasor yolu>"}',
    },
    "search_text": {
        "fn": tool_search_text,
        "desc": "Klasordeki dosyalarda regex aramasi yapar (grep benzeri).",
        "args": '{"pattern": "<regex>", "path": "<klasor>"}',
    },
    "zip_files": {
        "fn": tool_zip_files,
        "desc": "Dosya/klasorleri ZIP'ler; workspace/outputs icine kaydeder.",
        "args": '{"paths": ["<yol1>", "<yol2>"], "zip_name": "arsiv.zip"}',
    },
    "send_file": {
        "fn": tool_send_file,
        "desc": "Dosyayi Telegram sohbetine gonderir (50MB siniri).",
        "args": '{"path": "<dosya yolu>", "caption": "opsiyonel not"}',
    },
    "download_file": {
        "fn": tool_download_file,
        "desc": "http/https linkten dosya indirir; workspace/downloads'a kaydeder.",
        "args": '{"url": "<link>", "filename": "opsiyonel ad"}',
    },
    "run_ssh": {
        "fn": tool_run_ssh,
        "desc": "Config'de tanimli bir sunucuda komut calistirir (uzak site tamiri icin).",
        "args": '{"host": "<config ssh_hosts icindeki anahtar>", "command": "<komut>"}',
    },
    "sys_info": {
        "fn": tool_sys_info,
        "desc": "Bilgisayarin durumu: RAM, disk, yuk, acik kalma suresi.",
        "args": "{}",
    },
    "github_connect": {
        "fn": tool_github_connect,
        "desc": "GitHub hesabina baglanir: kullaniciya bir kod gonderir, girmesini bekler. Sonra git clone/push calisir. Site islerinden ONCE bir kez kullan.",
        "args": "{}",
    },
    "github_status": {
        "fn": tool_github_status,
        "desc": "GitHub baglantisinin olup olmadigini kontrol eder.",
        "args": "{}",
    },
    "ask_user": {
        "fn": tool_ask_user,
        "desc": "Kullaniciya Evet/Hayir sorusu sorar (onemli/onay gerektiren kararlarda kullan).",
        "args": '{"question": "<soru>"}',
    },
}


def tools_docs():
    lines = []
    for name, spec in TOOLS.items():
        lines.append("- %s: %s  Args: %s" % (name, spec["desc"], spec["args"]))
    return "\n".join(lines)


def run_tool(name, args, ctx):
    spec = TOOLS.get(name)
    if not spec:
        return (
            "HATA: boyle bir arac yok: '%s'. Musait araclar: %s"
            % (name, ", ".join(sorted(TOOLS)))
        )
    if not isinstance(args, dict):
        args = {}
    try:
        return spec["fn"](args, ctx)
    except Exception as e:
        return "HATA: arac calisirken sorun: %r" % e
