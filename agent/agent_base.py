# -*- coding: utf-8 -*-


import email.utils
import http.client
import json
import imaplib
import logging
import os
import re
import tempfile
import threading
import time
import urllib.error
from datetime import datetime, timedelta, timezone

from . import approvals
from . import trace as tr
from .dedup import Journal, normalize_subject
from . import claude_cli as ccli
from .llm import classify_server
from .mail_client import MailClient
from .redmine_client import RedmineClient
from .rules import (clean_subject, extract_route, load_markers, load_routing,
                    match_marker, sender_blacklisted)
from . import grafana_sets as gfs
from . import table_verdict as tv
from . import service_verdict as sv
from . import default_flow as dfl

MSK = timezone(timedelta(hours=3))

DESCRIPTION_TEMPLATE = """{body}

---
_Создано автоматически из письма: {from_} | {date}_
"""


def _load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _write_json(path, obj, indent=None):


    os.makedirs(os.path.dirname(path), exist_ok=True)


    fd, tmp = tempfile.mkstemp(prefix=os.path.basename(path) + ".", suffix=".tmp",
                               dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=indent)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


class _GrafanaSessionExpired(RuntimeError):
    pass


class _TicketDefer(Exception):


    def __init__(self, issue_id, err, quiet=False):
        self.issue_id = issue_id
        self.err = err
        self.quiet = quiet
        super().__init__("defer #%s: %s" % (issue_id, err))


class RoleMixin:


    def _role_ids(self):


        roles = self.cfg.get("roles") or {}
        known = self.cfg.get("known_people") or {}
        id2name = {v: k for k, v in known.items() if isinstance(v, int)}
        return roles.get("chief_engineer"), roles.get("engineer"), id2name

    def _default_assignee(self):


        return (self.cfg.get("assigned_to_id")
                or (getattr(self, "rm_account", None) or {}).get("user_id"))

    def _role_name(self, pid, id2name):


        if pid is None:
            return None
        name = id2name.get(pid)
        if name:
            return name
        acc = getattr(self, "rm_account", None) or {}
        if acc.get("user_id") == pid and acc.get("label"):
            return acc["label"]
        return None

    def _role_label(self, role, pid, id2name):


        if pid is None:
            return "@%s (не задан в настройках)" % role
        return "@%s (%s)" % (role, self._role_name(pid, id2name) or ("id %s" % pid))

    def _role_engineer(self):


        _chief, eng, id2name = self._role_ids()
        return eng, self._role_label("engineer", eng, id2name)

    def _is_client_a(self, project_name):


        shift_cfg = getattr(self, "shift_cfg", None) or self.cfg.get("shift_handoff") or {}
        client_a = [str(m).lower() for m in (shift_cfg.get("client_a_clients") or ["Клиент A"])]
        pname = (project_name or "").lower()
        return any(pname.startswith(m) for m in client_a)

    def _auto_take_enabled(self, project_name):


        roles = self.cfg.get("roles") or {}
        key = "auto_take_chief" if self._is_client_a(project_name) else "auto_take_engineer"
        return bool(roles.get(key, True))

    def _take_off_note(self, project_name):

        if self._is_client_a(project_name):
            return "взятие Клиент Aа на @chiefEngineer выключено тумблером (настройки → Роли)"
        return "взятие остальных клиентов на @engineer выключено тумблером (настройки → Роли)"

    def _role_for_client(self, project_name):


        chief_id, engineer_id, id2name = self._role_ids()
        if self._is_client_a(project_name):
            return chief_id, self._role_label("chiefEngineer", chief_id, id2name)
        return engineer_id, self._role_label("engineer", engineer_id, id2name)
