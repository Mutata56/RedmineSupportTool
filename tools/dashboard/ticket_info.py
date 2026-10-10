# -*- coding: utf-8 -*-


import json
import threading
import time
import urllib.parse
import urllib.request

from . import core
from agent import redmine_client as rmc

TTL = 30
ERR_TTL = 10
LOOKUP_TTL = 1800

_cache_guard = threading.Lock()
_cache = {}
_lookups = {"ts": 0, "statuses": {}, "priorities": {}}


def _name(d):

    return (d or {}).get("name") or "" if isinstance(d, dict) else ""


def _users_map(issue):


    users = {}
    for u in [issue.get("author"), issue.get("assigned_to")] + \
             [j.get("user") for j in issue.get("journals") or []]:
        if isinstance(u, dict) and u.get("id") is not None and u.get("name"):
            users[str(u["id"])] = u["name"]
    return users


def _user_label(val, users):
    if not val:
        return "(снят)"
    return users.get(str(val)) or ("id %s" % val)


def format_change(d, statuses, priorities, users):


    prop, name = d.get("property"), d.get("name") or ""
    old, new = d.get("old_value"), d.get("new_value")
    if prop == "attr":
        if name == "status_id":
            return "статус: %s → %s" % (statuses.get(str(old), old or "—"),
                                        statuses.get(str(new), new or "—"))
        if name == "assigned_to_id":
            return "назначенец: %s → %s" % (_user_label(old, users), _user_label(new, users))
        if name == "priority_id":
            return "приоритет: %s → %s" % (priorities.get(str(old), old or "—"),
                                           priorities.get(str(new), new or "—"))
        if name == "subject":
            return "тема: %s" % (new or "")
        if name == "description":
            return "описание изменено"
        if name == "done_ratio":
            return "готовность: %s%% → %s%%" % (old or 0, new or 0)
        if name == "is_private":
            return "заявка " + ("сделана приватной" if new in ("1", 1, True) else "открыта")
        if name in ("due_date", "start_date"):
            label = "срок" if name == "due_date" else "начало"
            return "%s: %s → %s" % (label, old or "—", new or "—")
        if name == "tracker_id":
            return "трекер изменён"
        if name == "tag_list":
            return "метки: %s" % (new or "—")
        return "%s изменено" % name
    if prop == "attachment":
        return ("вложение: %s" % new) if new else None
    if prop == "relation":
        return ("связь с #%s" % new) if new else None
    return None


def build_card(issue, statuses=None, priorities=None):


    statuses, priorities = statuses or {}, priorities or {}
    users = _users_map(issue)
    journals = []
    for j in issue.get("journals") or []:
        notes = (j.get("notes") or "").strip()
        changes = [c for c in (format_change(d, statuses, priorities, users)
                               for d in j.get("details") or []) if c]
        if not notes and not changes:
            continue
        journals.append({
            "id": j.get("id"),
            "user": _name(j.get("user")),
            "at": j.get("created_on") or "",
            "notes": notes,
            "private": bool(j.get("private_notes")),
            "changes": changes,
        })
    return {
        "id": issue.get("id"),
        "subject": issue.get("subject") or "",
        "status": _name(issue.get("status")),
        "priority": _name(issue.get("priority")),
        "project": _name(issue.get("project")),
        "tracker": _name(issue.get("tracker")),
        "author": _name(issue.get("author")),
        "assigned_to": _name(issue.get("assigned_to")),
        "created_on": issue.get("created_on") or "",
        "updated_on": issue.get("updated_on") or "",
        "description": issue.get("description") or "",
        "is_private": bool(issue.get("is_private")),
        "journals": journals,
        "attachments": [{
            "id": a.get("id"),
            "filename": a.get("filename") or "",
            "filesize": a.get("filesize") or 0,
            "content_type": a.get("content_type") or "",
            "at": a.get("created_on") or "",
            "author": _name(a.get("author")),
        } for a in issue.get("attachments") or []],
    }


def _secrets():
    try:
        with open(core.SECRETS_FILE, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _lookup_maps(rc):


    now = time.time()
    if now - _lookups["ts"] < LOOKUP_TTL and (_lookups["statuses"] or _lookups["priorities"]):
        return _lookups["statuses"], _lookups["priorities"]
    try:
        _lookups["statuses"] = {str(s["id"]): s.get("name", "") for s in rc.issue_statuses()}
        _lookups["priorities"] = {str(p["id"]): p.get("name", "") for p in rc.issue_priorities()}
        _lookups["ts"] = now
    except Exception:
        pass
    return _lookups["statuses"], _lookups["priorities"]


def get_info(issue_id):


    issue_id = int(issue_id)
    now = time.time()
    with _cache_guard:
        hit = _cache.get(issue_id)
        if hit and now - hit[0] < (TTL if hit[1].get("ok") else ERR_TTL):
            return hit[1]
    acc = rmc.resolve_account(_secrets())
    url, key = acc["url"], acc["api_key"]
    if not url or not key:
        out = {"ok": False, "error": "нет redmine_url/redmine_api_key в secrets.local.json"}
    else:
        try:
            rc = rmc.RedmineClient(url, key)
            issue = rc.get_issue(issue_id)
            if not issue:
                out = {"ok": False, "error": "Redmine вернул пустую заявку #%d" % issue_id}
            else:
                statuses, priorities = _lookup_maps(rc)
                out = {"ok": True, "redmine_url": url,
                       "issue": build_card(issue, statuses, priorities),
                       "fetched_at": time.strftime("%Y-%m-%d %H:%M:%S")}
        except Exception as e:
            out = {"ok": False, "error": "Redmine недоступен: %s" % e}
    with _cache_guard:
        _cache[issue_id] = (now, out)
        if len(_cache) > 200:
            for k in sorted(_cache, key=lambda k: _cache[k][0])[:100]:
                _cache.pop(k, None)
    return out


def find_attachment(issue_id, attachment_id):


    info = get_info(issue_id)
    if not info.get("ok"):
        return None
    for a in (info.get("issue") or {}).get("attachments") or []:
        if a.get("id") == attachment_id:
            return a
    return None


def open_attachment(issue_id, attachment_id):


    att = find_attachment(issue_id, attachment_id)
    if not att or not att.get("id"):
        return None
    acc = rmc.resolve_account(_secrets())
    url, key = acc["url"], acc["api_key"]
    if not url or not key:
        return None
    dl = "%s/attachments/download/%d/%s" % (
        url, att["id"], urllib.parse.quote(att.get("filename") or ""))
    req = urllib.request.Request(dl, headers={
        "X-Redmine-API-Key": key, "User-Agent": "work-agent/0.1"})
    resp = urllib.request.urlopen(req, timeout=45)
    ctype = (resp.headers.get("Content-Type") or "").split(";")[0].strip() \
        or att.get("content_type") or "application/octet-stream"
    return resp, ctype, att.get("filename") or ""
