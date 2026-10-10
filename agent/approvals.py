# -*- coding: utf-8 -*-


import json
import os
import re
import tempfile
import time

_ID_RE = re.compile(r"^\d+$")


def _draft_status(root, issue_id):


    try:
        with open(os.path.join(root, "state", "drafts", "%d.json" % int(issue_id)),
                  encoding="utf-8") as f:
            d = json.load(f)
        return d.get("status") if isinstance(d, dict) else None
    except (OSError, ValueError, TypeError):
        return None


def _busy(ex):


    if not ex:
        return None
    if ex.get("status") == "pending":
        return "уже висит запрос (%s)" % ex.get("pipe")
    if ex.get("status") == "approved":
        return "решение уже одобрено и ждёт исполнения (%s)" % ex.get("pipe")
    if ex.get("stage") in ("running", "reviewing"):
        return "фоновый анализ ИИ ещё выполняется (%s)" % ex.get("pipe")
    return None


def _dir(root):
    return os.path.join(root, "state", "approvals")


def _path(root, issue_id):
    return os.path.join(_dir(root), "%d.json" % int(issue_id))


def load(root, issue_id):

    try:
        with open(_path(root, issue_id), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def save(root, issue_id, data, if_rev=None):


    os.makedirs(_dir(root), exist_ok=True)
    cur_rev = (load(root, issue_id) or {}).get("rev", 0)
    if if_rev is not None and cur_rev != if_rev:
        return False, ("файл решения #%s изменился (rev=%s, ждали %s) - перечитай"
                       % (issue_id, cur_rev, if_rev))
    data = dict(data)
    data["rev"] = cur_rev + 1
    fd, tmp = tempfile.mkstemp(prefix="%d." % int(issue_id), suffix=".tmp", dir=_dir(root))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, _path(root, issue_id))
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    return True, ""


def clear(root, issue_id):
    try:
        os.remove(_path(root, issue_id))
    except OSError:
        pass


def load_all(root):

    out = []
    try:
        names = os.listdir(_dir(root))
    except OSError:
        return out
    for name in sorted(names):
        if name.endswith(".json") and _ID_RE.match(name[:-5]):
            ap = load(root, int(name[:-5]))
            if ap:
                out.append(ap)
    return out


def held_ids(root):


    return {ap["issue_id"] for ap in load_all(root)
            if isinstance(ap.get("issue_id"), int)}


def create_manual_opus(root, issue_id, subject, prompt="", model=None, effort=None):


    try:
        issue_id = int(issue_id)
    except (TypeError, ValueError):
        return False, "некорректный issue_id"
    busy = _busy(load(root, issue_id))
    if busy:
        return False, "по заявке #%d %s - сначала дождись/реши его" % (issue_id, busy)


    if _draft_status(root, issue_id) == "running":
        return False, ("по заявке #%d уже идёт агент-разбор (черновик в работе) - дождись его"
                       % issue_id)
    data = {
        "pipe": "opus", "issue_id": issue_id, "subject": subject or "", "reason": "manual",
        "origin_key": "opus-%d" % issue_id, "prompt": (prompt or "").strip(),
        "proposal": ("Ручной запуск Opus" + (":\n\n" + prompt if (prompt or "").strip()
                     else " (сам ищет похожие)")),
        "status": "approved", "decided_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    if model:
        data["model"] = model
    if effort:
        data["effort"] = effort
    save(root, issue_id, data)
    return True, ""


def create_manual_alert(root, issue_id, subject=""):


    try:
        issue_id = int(issue_id)
    except (TypeError, ValueError):
        return False, "некорректный issue_id"
    busy = _busy(load(root, issue_id))
    if busy:
        return False, "по заявке #%d %s - сначала дождись/реши его" % (issue_id, busy)


    if _draft_status(root, issue_id) == "running":
        return False, ("по заявке #%d уже идёт агент-разбор (черновик в работе) - дождись его"
                       % issue_id)
    save(root, issue_id, {"pipe": "alert", "issue_id": issue_id, "subject": subject or "",
                          "status": "handoff", "reason": "manual_dispatch",
                          "created_at": time.strftime("%Y-%m-%d %H:%M:%S")})
    return True, ""


def alert_overrides(root):


    return {ap["issue_id"] for ap in load_all(root)
            if ap.get("pipe") == "alert" and isinstance(ap.get("issue_id"), int)}


def decide(root, issue_id, decision, model=None, effort=None):


    ap = load(root, issue_id)
    if not ap:
        return False, "запроса по заявке #%s нет" % issue_id
    if ap.get("status") != "pending":
        return False, "запрос уже решён (status=%s)" % ap.get("status")
    if ap.get("stage") == "reviewing":


        return False, ("по заявке #%s идёт ИИ-ревью - решение будет запрошено "
                       "после его завершения" % issue_id)

    if ap.get("pipe") == "opus":
        if model:
            ap["model"] = model
        if effort:
            ap["effort"] = effort
    if decision in ("approved", "manual", "ignore"):
        ap["status"] = decision
    else:
        return False, "неизвестное решение: %r" % decision
    ap["decided_at"] = time.strftime("%Y-%m-%d %H:%M:%S")


    ok, err = save(root, issue_id, ap, if_rev=ap.get("rev", 0))
    if not ok:
        return False, "решение не записано (%s) - файл изменил агент, попробуй ещё раз" % err
    return True, ""
