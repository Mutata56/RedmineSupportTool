# -*- coding: utf-8 -*-


import json
import logging
import os
import re
import shutil
import tempfile
import threading
import time

from . import core
from agent import redmine_client as rmc

log = logging.getLogger("dashboard.drafts")

DRAFTS_DIR = os.path.join(core.ROOT, "state", "drafts")


_APPROVE_RE = re.compile(
    r"^(ок|ok|да|да,?\s*пости.*|пости.*|публикуй.*|одобряю.*|запость.*|аппрув.*)[!. ]*$",
    re.IGNORECASE)
_DECLINE_RE = re.compile(r"^(не\s+пости.*|отклоняю.*|не\s+надо.*|отмена.*)$", re.IGNORECASE)


_INSTRUCTION_MARKERS = re.compile(
    r"(?:^|\W)(?:но|однако|сначала|сперва|после|когда|если|пока|"
    r"поправ\w*|переделай\w*|перепиш\w*|замен\w*|исправ\w*|добав\w*|убер\w*|"
    r"покажи\w*|посмотр\w*|проверь\w*|уточни\w*|дополни\w*|"
    r"торопи\w*|подожди\w*|не\s+трог\w*)(?:\W|$)", re.IGNORECASE)


def _is_command(text, rx):

    t = (text or "").strip().lower()
    if not t or _INSTRUCTION_MARKERS.search(t):
        return False
    return bool(rx.match(t))


def is_affirmative(text):

    return _is_command(text, _APPROVE_RE)


def is_decline(text):

    return _is_command(text, _DECLINE_RE)


def draft_path(issue_id):
    return os.path.join(DRAFTS_DIR, "%d.json" % issue_id)


def load_draft(issue_id):
    try:
        with open(draft_path(issue_id), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def save_draft(issue_id, data):


    os.makedirs(DRAFTS_DIR, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=DRAFTS_DIR, prefix=".%d." % int(issue_id), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, draft_path(issue_id))
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def pending_drafts():

    out = {}
    try:
        names = os.listdir(DRAFTS_DIR)
    except OSError:
        return out
    for n in names:
        if not n.endswith(".json"):
            continue
        try:
            iid = int(n[:-5])
        except ValueError:
            continue
        d = load_draft(iid)
        if d and d.get("status") == "pending":
            out[iid] = d
    return out


def clean_shots(issue_id):

    shutil.rmtree(os.path.join(DRAFTS_DIR, str(int(issue_id))), ignore_errors=True)


def resolve_shot(draft, sid):


    for s in (draft or {}).get("screenshots") or ():
        if not isinstance(s, dict) or s.get("sid") != sid:
            continue
        f = str(s.get("file") or "")
        if not f:
            return None
        path = f if os.path.isabs(f) else os.path.join(core.ROOT, f)
        real = os.path.realpath(path)
        if real.startswith(os.path.realpath(DRAFTS_DIR) + os.sep) and os.path.isfile(real):
            return real
        return None
    return None


def approved_shots(draft):


    out, used = [], set()
    for s in (draft or {}).get("screenshots") or ():
        if not isinstance(s, dict) or not s.get("approved"):
            continue
        sid = s.get("sid")
        path = resolve_shot(draft, sid)
        if not path:
            continue
        fname = os.path.basename(path)
        if fname in used:
            root, ext = os.path.splitext(fname)
            fname = "%s_%s%s" % (root, sid, ext)
        used.add(fname)
        out.append((sid, fname, path))
    return out


def textile_image_lines(filenames):

    return "\n".join("!%s!" % n for n in filenames)


def build_note(draft, filenames):


    note = (draft.get("comment") or "").strip()
    if not note:
        parts = ["h3. Разбор",
                 (draft.get("analysis") or "").strip(), (draft.get("sql") or "").strip()]
        note = "\n\n".join(p for p in parts if p)
    rest = [n for n in filenames if ("!%s!" % n) not in note]
    imgs = textile_image_lines(rest)
    return (note + "\n\n" + imgs) if imgs else note


def _at_ts(at):
    try:
        return int(time.mktime(time.strptime(at, "%Y-%m-%d %H:%M:%S")))
    except (ValueError, TypeError, OverflowError):
        return 0


def draft_message(issue_id, draft):


    at = draft.get("created_at") or ""
    return {
        "role": "draft",
        "text": draft.get("analysis") or "",
        "sql": draft.get("sql") or "",


        "humanize": draft.get("humanize"),
        "original": draft.get("analysis_original"),
        "screenshots": [{"sid": sid, "title": next(
                            (s.get("title") or "" for s in draft.get("screenshots") or ()
                             if isinstance(s, dict) and s.get("sid") == sid), ""),
                         "url": "/api/drafts/%d/shot/%s" % (issue_id, sid)}
                        for sid, _fn, _p in approved_shots(draft)],
        "ts": _at_ts(at), "at": at,
    }


def _secrets():

    try:
        with open(os.path.join(core.ROOT, "config", "secrets.local.json"),
                  encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def upsert_draft_from_chat(issue_id, note, subject="", session_id=None, analysis_seconds=None):


    note = (note or "").strip()
    if not note:
        return None, False
    upd = update_draft_from_chat(issue_id, note, session_id=session_id,
                                 analysis_seconds=analysis_seconds)
    if upd:
        return upd, False
    cur = load_draft(issue_id)
    if cur and cur.get("status") not in (None, "pending"):
        return None, False
    d = {"issue_id": int(issue_id), "subject": subject or (cur or {}).get("subject", ""),
         "kind": "chat", "status": "pending", "analysis": note,
         "comment": "h3. Разбор:\n\n" + note, "sql": "", "screenshots": [],
         "created_at": _now(), "session_id": session_id,
         "confidence": (cur or {}).get("confidence"),
         "analysis_seconds": round(float(analysis_seconds or 0), 2)}
    try:
        save_draft(issue_id, d)
    except OSError:
        return None, False
    return d, True


def update_draft_from_chat(issue_id, note, session_id=None, analysis_seconds=None):


    note = (note or "").strip()
    d = load_draft(issue_id)
    if not d or d.get("status") != "pending" or not note:
        return None
    d["analysis"] = note
    d["comment"] = "h3. Разбор:\n\n" + note


    d.pop("humanize", None)
    d.pop("analysis_original", None)
    d.pop("comment_original", None)
    if session_id:
        d["session_id"] = session_id
    if analysis_seconds:
        d["analysis_seconds"] = round(float(d.get("analysis_seconds") or 0)
                                      + float(analysis_seconds), 2)
    d["edited_at"] = _now()
    try:
        save_draft(issue_id, d)
    except OSError:
        return None
    return d


_pub_guard = threading.Lock()
_pub_locks = {}


def _publish_lock(issue_id):
    with _pub_guard:
        return _pub_locks.setdefault(int(issue_id), threading.Lock())


def publish_draft(issue_id):
    with _publish_lock(issue_id):
        return _publish_draft_locked(issue_id)


def _publish_draft_locked(issue_id):


    draft = load_draft(issue_id)
    if not draft:
        return {"ok": False, "posted": False, "reason": "no_draft",
                "draft_status": None, "text": "⚠ черновика по заявке #%d нет" % issue_id}
    if draft.get("status") == "posted":

        return {"ok": False, "posted": False, "reason": "already_posted",
                "draft_status": "posted",
                "text": "Черновик #%d уже опубликован ✓ — повторно не пощу." % issue_id}

    shots = approved_shots(draft)
    note = build_note(draft, [fn for _sid, fn, _p in shots])
    if bool(core.agent_status().get("dry_run", True)):
        return {"ok": True, "posted": False, "dry": True, "draft_status": draft.get("status"),
                "text": "DRY-RUN: опубликовал бы приватный коммент в #%d (скринов: %d). Черновик "
                        "остаётся ждать — включи боевой режим и повтори." % (issue_id, len(shots))}


    acc = rmc.resolve_account(_secrets())
    url, key = acc["url"], acc["api_key"]
    if not url or not key:
        return {"ok": False, "posted": False, "reason": "no_secrets",
                "draft_status": draft.get("status"),
                "text": "⚠ не могу опубликовать: нет redmine_url/redmine_api_key в secrets.local.json"}
    rc = rmc.RedmineClient(url, key)
    try:
        uploads = []
        for _sid, fname, path in shots:
            with open(path, "rb") as f:
                uploads.append({"token": rc.upload(f.read(), fname),
                                "filename": fname, "content_type": "image/png"})
        rc.add_note(issue_id, note, uploads=uploads or None, private=True)
    except Exception as e:
        return {"ok": False, "posted": False, "reason": "publish_failed",
                "draft_status": draft.get("status"),
                "text": "⚠ публикация не удалась: %s. Черновик остаётся — повтори позже." % e}
    draft["status"], draft["posted_at"] = "posted", _now()


    saved, save_err = False, None
    for _try in range(3):
        try:
            save_draft(issue_id, draft)
            saved = True
            break
        except OSError as e:
            save_err = e
            time.sleep(0.2)
    if not saved:
        log.error("publish_draft #%d: коммент ОПУБЛИКОВАН, но статус не записан (%s) — "
                  "черновик остался pending, повторная публикация задвоит коммент",
                  issue_id, save_err)


    time_logged, extra = None, ""
    secs = float(draft.get("analysis_seconds") or 0)
    if secs > 0:
        hours = max(0.01, round(secs / 3600, 2))
        try:
            rc.create_time_entry(issue_id, hours, "Разбор заявки")
            time_logged = hours
        except Exception as e:
            log.warning("publish_draft #%d: время (%.2f ч) не списалось: %s", issue_id, hours, e)
            extra = " (время не списалось: %s)" % e
    if not saved:
        extra += (" ⚠ статус черновика НЕ записан на диск — НЕ публикуй повторно, "
                  "иначе коммент задвоится")
    return {"ok": True, "posted": True, "time_logged": time_logged,
            "draft_status": "posted" if saved else draft.get("status"),
            "status_saved": saved,
            "text": "Опубликовано ✓ — приватный коммент в #%d (скринов: %d).%s"
                    % (issue_id, len(shots), extra)}
