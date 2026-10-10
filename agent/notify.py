# -*- coding: utf-8 -*-


import json
import logging
import os
import threading
import time
import urllib.request

from .redmine_client import resolve_account


_urlopen = urllib.request.urlopen

_SEEN_CAP = 400
_SEEN_TTL = 14 * 86400
_TIMEOUT = 10


EVENT_RU = {
    "new_ticket": "Новая заявка",
    "new_info": "Новая информация по заявке",
    "draft_ready": "Черновик агента ждёт одобрения",
    "mail_ping": "Алерт-письмо",
}


def _esc_html(s):

    return (str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


class Notifier:
    def __init__(self, cfg, secrets, state_dir, dry_run=False, log=None):
        m = cfg.get("messengers") if isinstance(cfg.get("messengers"), dict) else {}
        self.enabled = [str(x) for x in (m.get("enabled") or [])]
        self.events = set(m.get("events")
                          or ["new_ticket", "new_info", "draft_ready", "mail_ping"])
        tg = m.get("telegram") if isinstance(m.get("telegram"), dict) else {}
        nf = m.get("ntfy") if isinstance(m.get("ntfy"), dict) else {}
        self.tg_chat = tg.get("chat_id")
        self.tg_token = (secrets.get("telegram_bot_token") or "").strip() \
            if isinstance(secrets, dict) else ""
        self.ntfy_url = (nf.get("url") or "https://ntfy.sh").rstrip("/")
        self.ntfy_topic = (nf.get("topic") or "").strip()

        self.redmine_url = resolve_account(secrets)["url"] if isinstance(secrets, dict) else ""
        self.dry_run = bool(dry_run)
        self.log = log or logging.getLogger("agent.notify")
        self._seen_file = os.path.join(state_dir, "notify_seen.json")
        self._lock = threading.Lock()

        if "telegram" in self.enabled and not self.tg_token:
            self.log.warning("messengers: telegram включён, но telegram_bot_token в "
                             "secrets.local.json не задан - телеграм выключен")


    def _load_seen(self):
        try:
            with open(self._seen_file, encoding="utf-8") as f:
                d = json.load(f)
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def _mark_seen(self, seen, key):
        now = time.time()
        seen[key] = now

        seen = {k: v for k, v in seen.items() if now - v < _SEEN_TTL}
        if len(seen) > _SEEN_CAP:
            seen = dict(sorted(seen.items(), key=lambda kv: kv[1])[-_SEEN_CAP:])
        try:
            tmp = self._seen_file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(seen, f, ensure_ascii=False)
            os.replace(tmp, self._seen_file)
        except OSError as e:
            self.log.warning("messengers: notify_seen.json не записался (%s)", e)


    def send(self, event, title, text, issue_id=None):


        try:
            self._send(event, title, text, issue_id)
        except Exception:
            self.log.exception("messengers: отправка уведомления упала (проглочено)")

    def _send(self, event, title, text, issue_id):
        if event not in self.events or not self.enabled:
            return
        key = None
        if issue_id is not None:
            key = "%s:%s" % (event, issue_id)
        with self._lock:
            seen = self._load_seen()
            if key and key in seen:
                return
            ru = EVENT_RU.get(event, event)
            link = ("%s/issues/%s" % (self.redmine_url, issue_id)
                    if (self.redmine_url and issue_id) else "")
            dry = "[DRY] " if self.dry_run else ""
            full_title = dry + (title or ru)
            body = "%s%s: %s" % (dry, ru, text or "")
            if link:
                body += "\n" + link
            if "telegram" in self.enabled:
                self._send_telegram(full_title, body)
            if "ntfy" in self.enabled:
                self._send_ntfy(full_title, body)


            if key:
                self._mark_seen(seen, key)

    def _send_telegram(self, title, body):

        if not self.tg_token or not self.tg_chat:
            return False
        text = "<b>%s</b>\n%s" % (_esc_html(title), _esc_html(body))
        payload = {"chat_id": self.tg_chat, "text": text,
                   "parse_mode": "HTML", "disable_web_page_preview": True}
        req = urllib.request.Request(
            "https://api.telegram.org/bot%s/sendMessage" % self.tg_token,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        try:
            _urlopen(req, timeout=_TIMEOUT).read()
            return True
        except Exception as e:
            self.log.warning("messengers: telegram не отправился (%s)", e)
            return False

    def _send_ntfy(self, title, body):


        if not self.ntfy_topic:
            return False
        payload = {"topic": self.ntfy_topic, "title": title, "message": body}
        req = urllib.request.Request(
            self.ntfy_url, data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        try:
            _urlopen(req, timeout=_TIMEOUT).read()
            return True
        except Exception as e:
            self.log.warning("messengers: ntfy не отправился (%s)", e)
            return False


def emit(agent, event, issue_id, subject, text):


    n = getattr(agent, "notifier", None)
    if n is None:
        return
    title = ("#%s %s" % (issue_id, subject)).strip() if issue_id else (subject or "")
    n.send(event, title, text, issue_id=issue_id)


def poll178_new_info(state_file, issues, status_id=49):


    cur = {}
    for it in issues:
        iid = it.get("id")
        sid = (it.get("status") or {}).get("id") if isinstance(it.get("status"), dict) else None
        if iid is not None and sid is not None:
            cur[int(iid)] = int(sid)
    prev = None
    try:
        with open(state_file, encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict):
            prev = {int(k): int(v) for k, v in d.items()}
    except (OSError, ValueError, TypeError):
        prev = None
    tmp = state_file + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({str(k): v for k, v in cur.items()}, f)
    os.replace(tmp, state_file)
    if prev is None:
        return []
    fresh = []
    for it in issues:
        iid = it.get("id")
        if iid is None:
            continue
        iid = int(iid)
        if cur.get(iid) == status_id and prev.get(iid) != status_id:
            fresh.append(it)
    return fresh
