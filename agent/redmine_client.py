# -*- coding: utf-8 -*-


import http.client
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request

log = logging.getLogger("agent.redmine")


_TRANSIENT_HTTP = frozenset({429, 500, 502, 503, 504})
_GET_RETRIES = 2
_GET_BACKOFF = (1, 3)


DEFAULT_ACCOUNT = "default"


def mask_key(key):


    key = (key or "").strip()
    if not key:
        return ""
    return "••••" + key[-4:] if len(key) >= 4 else "••••"


def resolve_account(secrets, name=None):


    secrets = secrets or {}
    flat_url = (secrets.get("redmine_url") or "").rstrip("/")
    flat_key = (secrets.get("redmine_api_key") or "").strip()
    accs = secrets.get("redmine_accounts")
    if not isinstance(accs, dict) or not accs:
        return {"name": DEFAULT_ACCOUNT, "label": DEFAULT_ACCOUNT, "url": flat_url,
                "api_key": flat_key, "user_id": _as_int(secrets.get("redmine_user_id"))}
    want = name or (secrets.get("redmine_active") or "")
    if want not in accs or not isinstance(accs.get(want), dict):
        want = sorted(accs)[0]
    a = accs.get(want) if isinstance(accs.get(want), dict) else {}
    return {"name": want, "label": a.get("label") or want,
            "url": (a.get("url") or flat_url or "").rstrip("/"),
            "api_key": (a.get("api_key") or "").strip(),
            "user_id": _as_int(a.get("user_id"))}


def _as_int(v):
    try:
        return int(v) if v is not None and str(v).strip() != "" else None
    except (TypeError, ValueError):
        return None


def list_accounts(secrets):


    secrets = secrets or {}
    active = resolve_account(secrets)["name"]
    accs = secrets.get("redmine_accounts")
    if not isinstance(accs, dict) or not accs:
        a = resolve_account(secrets)
        return [{"name": a["name"], "label": a["label"], "url": a["url"],
                 "user_id": a["user_id"], "active": True,
                 "key_masked": mask_key(a["api_key"]), "legacy": True}]
    out = []
    for n in sorted(accs):
        a = accs[n] if isinstance(accs[n], dict) else {}
        out.append({"name": n, "label": a.get("label") or n,
                    "url": (a.get("url") or (secrets.get("redmine_url") or "")).rstrip("/"),
                    "user_id": _as_int(a.get("user_id")), "active": n == active,
                    "key_masked": mask_key(a.get("api_key")), "legacy": False})
    return out


class RedmineClient:
    def __init__(self, url, api_key):
        self.url = url.rstrip("/")
        self.api_key = api_key

    def _request(self, method, path, params=None, payload=None):
        url = self.url + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers={
            "X-Redmine-API-Key": self.api_key,
            "Content-Type": "application/json",
            "User-Agent": "work-agent/0.1",
        })


        attempt = 0
        while True:
            try:
                with urllib.request.urlopen(req, timeout=45) as r:
                    body = r.read()
                    return json.loads(body) if body else {}
            except urllib.error.HTTPError as e:
                if method != "GET" or e.code not in _TRANSIENT_HTTP or attempt >= _GET_RETRIES:
                    raise
                reason = "HTTP %s" % e.code
            except (urllib.error.URLError, http.client.HTTPException, OSError) as e:
                if method != "GET" or attempt >= _GET_RETRIES:
                    raise
                reason = str(getattr(e, "reason", None) or e)
            time.sleep(_GET_BACKOFF[min(attempt, len(_GET_BACKOFF) - 1)])
            attempt += 1
            log.info("redmine GET %s: транзиентный сбой (%s), повтор %d/%d",
                     path, reason, attempt, _GET_RETRIES)

    def paged(self, path, params=None, max_pages=5, item_key="issues"):


        out = []
        offset = 0
        hit_cap = True
        for _ in range(max_pages):
            p = dict(params or {})
            p["limit"] = 100
            p["offset"] = offset
            data = self._request("GET", path, params=p)
            batch = data.get(item_key, [])
            out += batch
            offset += len(batch)
            if not batch or offset >= data.get("total_count", 0):
                hit_cap = False
                break
        if hit_cap:
            log.warning("paged(%s): собрано > %d элементов - хвост за потолком в этот проход "
                        "не вошёл, возможны дубли", path, 100 * max_pages)
        return out

    def dashboard_issues(self, query_id, project, max_pages=5):


        return [{
            "id": i.get("id"),
            "project_id": i.get("project", {}).get("id"),
            "project_name": i.get("project", {}).get("name", ""),
            "subject": i.get("subject", ""),
            "status": i.get("status", {}).get("name", ""),
        } for i in self.paged("/issues.json",
                              {"query_id": query_id, "project_id": project}, max_pages=max_pages)]

    def new_issues(self, tracker_id, status_id=1, max_pages=3):


        return [{
            "id": i.get("id"),
            "project_id": i.get("project", {}).get("id"),
            "project_name": i.get("project", {}).get("name", ""),
            "subject": i.get("subject", ""),
            "status": i.get("status", {}).get("name", ""),
        } for i in self.paged("/issues.json",
                              {"tracker_id": tracker_id, "status_id": status_id}, max_pages=max_pages)]

    def create_issue(self, project_id, tracker_id, subject, description="",
                     priority_id=None, assigned_to_id=None, is_private=False,
                     custom_fields=None):


        issue = {
            "project_id": project_id,
            "tracker_id": tracker_id,
            "subject": subject[:250],
            "description": description or "",
            "is_private": bool(is_private),
        }
        if priority_id:
            issue["priority_id"] = priority_id
        if assigned_to_id:
            issue["assigned_to_id"] = assigned_to_id
        if custom_fields:
            issue["custom_fields"] = custom_fields
        data = self._request("POST", "/issues.json", payload={"issue": issue})


        try:
            return data["issue"]["id"]
        except (KeyError, TypeError):
            raise ValueError(
                "Redmine принял POST /issues.json, но не вернул issue.id (пустой/неожиданный "
                "ответ). Заявка МОГЛА быть создана - проверь в Redmine перед повтором.")

    def update_status(self, issue_id, status_id):

        self._request("PUT", f"/issues/{issue_id}.json",
                      payload={"issue": {"status_id": status_id}})


    def newest_issue_id(self, tracker_id):

        data = self._request("GET", "/issues.json", params={
            "tracker_id": tracker_id, "status_id": "*", "limit": 1, "sort": "id:desc"})
        issues = data.get("issues", [])
        return issues[0]["id"] if issues else 0

    def issues_after(self, tracker_id, after_id, page=100, max_pages=50):


        out = []
        offset = 0
        hit_cap = True
        for _ in range(max_pages):
            data = self._request("GET", "/issues.json", params={
                "tracker_id": tracker_id, "status_id": "*",
                "limit": page, "offset": offset, "sort": "id:desc"})
            batch = data.get("issues", [])
            stop = False
            for i in batch:
                if i["id"] <= after_id:
                    stop = True
                    break
                out.append({
                    "id": i["id"],
                    "subject": i.get("subject", ""),
                    "status": i.get("status", {}).get("name", ""),
                    "author": i.get("author", {}).get("name", ""),
                    "project": i.get("project", {}).get("name", ""),


                    "assigned_to_id": (i.get("assigned_to") or {}).get("id"),
                    "assigned_to": (i.get("assigned_to") or {}).get("name", ""),
                    "created_on": i.get("created_on", ""),


                    "description": i.get("description", ""),
                })
            offset += len(batch)
            if stop or not batch or offset >= data.get("total_count", 0):
                hit_cap = False
                break
        if hit_cap:


            log.warning("issues_after: бэклог > %d заявок, нижний хвост отложен на след. проход",
                        page * max_pages)
        return sorted(out, key=lambda x: x["id"])

    def add_relation(self, issue_id, to_id, relation_type="relates"):

        self._request("POST", "/issues/%s/relations.json" % issue_id,
                      payload={"relation": {"issue_to_id": to_id, "relation_type": relation_type}})

    def take_issue(self, issue_id, assigned_to_id, status_id):


        issue = {"status_id": status_id}
        if assigned_to_id:
            issue["assigned_to_id"] = assigned_to_id
        self._request("PUT", f"/issues/{issue_id}.json", payload={"issue": issue})

    def reassign(self, issue_id, assigned_to_id, tag_list=None, custom_fields=None):


        issue = {"assigned_to_id": assigned_to_id}
        if tag_list is not None:
            issue["tag_list"] = tag_list
        if custom_fields:
            issue["custom_fields"] = custom_fields
        self._request("PUT", f"/issues/{issue_id}.json", payload={"issue": issue})

    def query_issues(self, query_id, project=None, max_pages=10):


        return [{
            "id": i.get("id"),
            "project_id": i.get("project", {}).get("id"),
            "project_name": i.get("project", {}).get("name", ""),
            "subject": i.get("subject", ""),
            "status": i.get("status", {}).get("name", ""),
            "assignee_id": (i.get("assigned_to") or {}).get("id"),
            "assignee_name": (i.get("assigned_to") or {}).get("name", ""),
        } for i in self.paged("/issues.json",
                              {"query_id": query_id, "project_id": project or "example-project-001"},
                              max_pages=max_pages)]


    def get_issue(self, issue_id, include="journals,attachments"):


        params = {"include": include} if include else None
        data = self._request("GET", "/issues/%d.json" % int(issue_id), params=params)
        return data.get("issue") or {}

    def download_attachment(self, att, max_bytes=15 * 1024 * 1024):


        url = (att or {}).get("content_url")
        if not url:
            return None
        try:
            req = urllib.request.Request(url, headers={
                "X-Redmine-API-Key": self.api_key, "User-Agent": "work-agent/0.1"})
            with urllib.request.urlopen(req, timeout=45) as r:
                data = r.read(int(max_bytes) + 1)
        except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError) as e:
            log.info("redmine: вложение %s не скачалось (%s)", att.get("filename"), e)
            return None
        if len(data) > max_bytes:
            log.info("redmine: вложение %s больше лимита %d Б - пропущено",
                     att.get("filename"), max_bytes)
            return None
        return data

    def current_user(self):


        u = self._request("GET", "/users/current.json").get("user") or {}
        name = " ".join(x for x in (u.get("firstname"), u.get("lastname")) if x).strip()
        return {"id": u.get("id"), "login": u.get("login") or "", "name": name}

    def issue_statuses(self):


        return self._request("GET", "/issue_statuses.json").get("issue_statuses", [])

    def issue_priorities(self):

        return self._request(
            "GET", "/enumerations/issue_priorities.json").get("issue_priorities", [])

    def upload(self, data, filename):

        req = urllib.request.Request(
            self.url + "/uploads.json?" + urllib.parse.urlencode({"filename": filename}),
            data=data, method="POST",
            headers={"X-Redmine-API-Key": self.api_key,
                     "Content-Type": "application/octet-stream",
                     "User-Agent": "work-agent/0.1"})
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode())["upload"]["token"]

    def add_note(self, issue_id, note, uploads=None, private=True):

        issue = {"notes": note, "private_notes": bool(private)}
        if uploads:
            issue["uploads"] = uploads
        self._request("PUT", f"/issues/{issue_id}.json", payload={"issue": issue})

    def create_time_entry(self, issue_id, hours, comments=""):


        entry = {"issue_id": issue_id, "hours": round(float(hours), 2), "comments": comments}
        self._request("POST", "/time_entries.json", payload={"time_entry": entry})
