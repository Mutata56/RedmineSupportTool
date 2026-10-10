# -*- coding: utf-8 -*-


import email
import email.header
import imaplib
import logging
import re
import time
from dataclasses import dataclass

from . import trace as tr

log = logging.getLogger("agent.mail")


@dataclass
class Mail:
    uid: int
    message_id: str
    from_: str
    subject: str
    date: str
    body: str
    internal_ts: float = None


def _decode_header(value):
    if not value:
        return ""
    out = []
    for text, enc in email.header.decode_header(value):
        if isinstance(text, bytes):
            for e in (enc, "utf-8", "cp1251", "koi8-r"):
                if not e:
                    continue
                try:
                    out.append(text.decode(e))
                    break
                except (UnicodeDecodeError, LookupError):
                    continue
            else:
                out.append(text.decode("utf-8", "replace"))
        else:
            out.append(text)
    return "".join(out).strip()


def _body_text(msg, limit):
    def dec(part):
        payload = part.get_payload(decode=True) or b""
        charset = part.get_content_charset() or "utf-8"
        try:
            return payload.decode(charset, "replace")
        except LookupError:
            return payload.decode("utf-8", "replace")

    plain, html = None, None
    for part in (msg.walk() if msg.is_multipart() else [msg]):


        disp = (part.get_content_disposition() or "").lower()
        if disp == "attachment" or (disp == "inline" and part.get_filename()
                                    and part.get_content_type() not in ("text/plain", "text/html")):
            continue
        ctype = part.get_content_type()
        if ctype == "text/plain" and plain is None:
            plain = dec(part)
        elif ctype == "text/html" and html is None:
            html = dec(part)


    text = plain if (plain and plain.strip()) else re.sub(r"<[^>]+>", " ", html or "")
    return re.sub(r"[ \t\r]+", " ", text).strip()[:limit]


class MailClient:
    def __init__(self, host, port, login, password, folder="INBOX"):
        self.host = host
        self.port = port
        self.login = login
        self.password = password
        self.folder = folder
        self.conn = None

    def _connect(self):

        self.conn = imaplib.IMAP4_SSL(self.host, self.port, timeout=60)
        self.conn.login(self.login, self.password)
        self.conn.select(self.folder, readonly=True)

    def _drop(self):
        if self.conn is not None:
            try:
                self.conn.logout()
            except Exception:
                pass
        self.conn = None

    def _ensure(self):
        if self.conn is None:
            self._connect()
            return
        try:
            self.conn.noop()
        except Exception as e:
            log.warning("IMAP-соединение умерло (%s) - переподключаюсь", e)
            tr.trace("IMAP: соединение умерло (%s) - переподключаюсь", e)
            self._drop()
            self._connect()

    def uidvalidity(self):


        self._ensure()
        typ, data = self.conn.response("UIDVALIDITY")
        try:
            return int(data[0])
        except (TypeError, ValueError, IndexError):
            return None

    def uidnext(self):


        self._ensure()
        typ, data = self.conn.status(self.folder, "(UIDNEXT)")
        m = re.search(rb"UIDNEXT\s+(\d+)", data[0] if data and data[0] else b"")
        if not m:


            log.warning("IMAP не вернул UIDNEXT (%r) - точка старта с начала ящика", data)
        return int(m.group(1)) if m else 1

    def fetch_new(self, last_uid, body_limit=4000, max_bytes=2_000_000):


        attempts = 3
        for attempt in range(1, attempts + 1):
            try:
                self._ensure()
                return self._fetch(last_uid, body_limit, max_bytes)
            except (imaplib.IMAP4.abort, imaplib.IMAP4.error, OSError) as e:
                self._drop()
                if attempt == attempts:
                    log.warning("IMAP-обрыв при выборке (%s) - исчерпаны %d попытки, "
                                "пробросил (poll() продолжит тикет-сторону, письма — след. проходом)",
                                e, attempts)
                    raise
                backoff = attempt
                log.warning("IMAP-обрыв при выборке (%s) - попытка %d/%d, жду %dс и переподключаюсь",
                            e, attempt, attempts, backoff)
                tr.trace("IMAP: обрыв (%s), бэкофф %dс перед повтором %d/%d",
                         e, backoff, attempt + 1, attempts)
                time.sleep(backoff)
        return []

    def _fetch(self, last_uid, body_limit, max_bytes):
        typ, data = self.conn.uid("SEARCH", None, f"UID {last_uid + 1}:*")
        raw_uids = data[0].split() if data and data[0] else []

        uids = sorted(int(u) for u in raw_uids if int(u) > last_uid)
        tr.trace("IMAP: SEARCH UID>%d -> новых писем %d", last_uid, len(uids))
        if not uids:
            return []


        metas = {}
        for i in range(0, len(uids), 50):
            rng = ",".join(str(u) for u in uids[i:i + 50])
            typ, md = self.conn.uid(
                "FETCH", rng,
                "(RFC822.SIZE INTERNALDATE BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE MESSAGE-ID)])")
            for chunk in md or []:
                if not isinstance(chunk, tuple):
                    continue
                mu = re.search(rb"UID (\d+)", chunk[0])
                ms = re.search(rb"RFC822\.SIZE\s+(\d+)", chunk[0])
                it = imaplib.Internaldate2tuple(chunk[0])
                if mu:
                    metas[int(mu.group(1))] = (int(ms.group(1)) if ms else 0, chunk[1],
                                               time.mktime(it) if it else None)
        missing = [u for u in uids if u not in metas]
        if missing:

            log.warning("IMAP не отдал заголовки %d писем (UID %s%s) - они будут пропущены",
                        len(missing), missing[:20], "..." if len(missing) > 20 else "")


        small = [u for u in uids if u in metas and metas[u][0] <= max_bytes]
        tr.trace("IMAP: заголовков получено %d, тел к скачиванию %d (лимит %d байт)",
                 len(metas), len(small), max_bytes)
        bodies = {}
        for i in range(0, len(small), 10):
            rng = ",".join(str(u) for u in small[i:i + 10])
            typ, md = self.conn.uid("FETCH", rng, "(BODY.PEEK[])")
            cur = None
            for chunk in md or []:
                if not isinstance(chunk, tuple):
                    continue
                mu = re.search(rb"UID (\d+)", chunk[0])
                cur = int(mu.group(1)) if mu else cur
                if cur is not None:
                    bodies[cur] = chunk[1]

        mails = []
        for u in uids:
            if u not in metas:
                continue
            hmsg = email.message_from_bytes(metas[u][1])
            body = ""
            if u in bodies:
                body = _body_text(email.message_from_bytes(bodies[u]), body_limit)
            elif metas[u][0] <= max_bytes:
                log.warning("IMAP не отдал тело UID %d - обрабатываю по одним заголовкам", u)
            mails.append(Mail(
                uid=u,


                message_id=(hmsg.get("Message-ID") or "").strip() or f"no-mid-uid-{u}",
                from_=_decode_header(hmsg.get("From")),
                subject=_decode_header(hmsg.get("Subject")),
                date=hmsg.get("Date") or "",
                body=body,
                internal_ts=metas[u][2],
            ))
        return mails

    def close(self):
        self._drop()
