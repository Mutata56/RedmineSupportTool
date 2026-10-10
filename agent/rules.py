# -*- coding: utf-8 -*-


import re

SERVER_RE = re.compile(r"(?i)server\s*:\s*([A-Za-z0-9_\-\.]+)")
_PREFIX_RE = re.compile(r"(?i)^(?:(?:re|fwd|fw)\s*(?:\[\d+\])?\s*:\s*)+")


FIRING_RE = re.compile(r"(?i)\[[^\]]*\bFIRING\b(?:\s*:\s*(\d+))?[^\]]*\]")


class Marker:
    def __init__(self, raw):
        self.key = raw["key"]
        self.rx = re.compile(raw["pattern"])


        self.dedup_by = raw.get("dedup_by", "marker")


        self.issue_subject = raw.get("issue_subject")


def load_markers(cfg):
    return [Marker(m) for m in cfg.get("markers", [])]


def match_marker(mail, markers):

    for m in markers:
        if m.rx.search(mail.subject) or m.rx.search(mail.body):
            return m
    return None


class Ping:


    def __init__(self, raw):
        self.key = raw["key"]
        self.rx = re.compile(raw["subject"])
        self.text = raw.get("text") or raw["key"]


def load_pings(cfg):

    p = cfg.get("mail_pings") or {}
    if not p.get("enabled", True):
        return []
    return [Ping(r) for r in (p.get("rules") or [])
            if isinstance(r, dict) and r.get("key") and r.get("subject")]


def match_ping(mail, pings):


    subj = mail.subject or ""
    m = FIRING_RE.search(subj)
    if not m:
        return None, 0
    for p in pings:
        if p.rx.search(subj):
            return p, int(m.group(1) or 1)
    return None, 0


def sender_email(mail):
    m = re.search(r"<([^>]+)>", mail.from_)
    return (m.group(1) if m else mail.from_).strip().lower()


def sender_blacklisted(mail, blacklist):


    se = sender_email(mail)
    for b in blacklist:
        b = b.lower().lstrip("@")
        if se == b or se.endswith("@" + b):
            return True
    return False


def load_routing(cfg):

    out = {}
    for token, spec in cfg.get("routing", {}).items():
        if isinstance(spec, dict) and spec.get("project_id"):
            out[token.upper()] = spec
    return out


def extract_route(mail, routing):


    m = SERVER_RE.search(mail.body)
    candidate = m.group(1).strip(".").upper() if m else None
    if candidate and candidate in routing:
        return candidate, candidate


    hay = (mail.subject + " " + mail.from_ + " " + mail.body).upper()
    for token in sorted(routing, key=len, reverse=True):
        if re.search(r"(?<![A-ZА-ЯЁ0-9_])" + re.escape(token) + r"(?![A-ZА-ЯЁ0-9_])", hay):
            return token, candidate
    return None, candidate


def clean_subject(s):

    s = _PREFIX_RE.sub("", s or "")
    return re.sub(r"\s+", " ", s).strip()
