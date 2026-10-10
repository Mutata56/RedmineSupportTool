# -*- coding: utf-8 -*-

import re
import time
import urllib.parse

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from .. import core, ticket_info

router = APIRouter(prefix="/api")


def _decorate(e, pending_ids):

    e["awaiting_decision"] = e["issue_id"] in pending_ids
    e["session_id"] = core.find_session_id(e)
    e["has_ai"] = bool(e["session_id"]) or any(
        r["verdict"] in ("llm_analysis", "default_done", "default_dispatched",
                         "llm_low_confidence", "default_low_confidence")
        for r in e["records"])
    return e


@router.get("/tickets")
def tickets(q: str = "", verdict: str = "", period: str = "", limit: int = 300):
    feed = core.build_feed(core.ROOT, limit=max(1, min(limit, 1000)))
    pending_ids = {a.get("issue_id") for a in feed["approvals"]}
    items = feed["tickets"]
    if q:
        ql = q.lower()
        items = [e for e in items
                 if ql in (e["subject"] + " " + e["note"] + " #" + str(e["issue_id"])).lower()]
    if verdict:
        items = [e for e in items if e["verdict"] == verdict]
    horizon = {"today": 1, "week": 7, "month": 30}.get(period)
    if horizon:
        cutoff = time.time() - horizon * core.DAY
        items = [e for e in items if e["last_ts"] > cutoff]
    return {"items": [_decorate(e, pending_ids) for e in items],
            "redmine_url": feed["redmine_url"]}


@router.get("/tickets/{issue_id}")
def ticket_detail(issue_id: int):
    feed = core.build_feed(core.ROOT, limit=1000)
    pending = {a.get("issue_id"): a for a in feed["approvals"]}
    for e in feed["tickets"]:
        if e["issue_id"] == issue_id:
            e = _decorate(e, set(pending))
            e["approval"] = pending.get(issue_id)
            e["redmine_url"] = feed["redmine_url"]
            return e
    raise HTTPException(404, "заявка #%d в журнале агента не найдена" % issue_id)


@router.get("/tickets/{issue_id}/info")
def ticket_full_info(issue_id: int):


    return ticket_info.get_info(issue_id)


@router.get("/tickets/{issue_id}/att/{attachment_id}")
def ticket_attachment(issue_id: int, attachment_id: int):


    try:
        opened = ticket_info.open_attachment(issue_id, attachment_id)
    except Exception as e:
        raise HTTPException(502, "Redmine недоступен: %s" % e)
    if not opened:
        raise HTTPException(404, "вложение %d не принадлежит заявке #%d или заявка "
                                 "недоступна" % (attachment_id, issue_id))
    resp, ctype, filename = opened


    _inline_ok = ctype.startswith("image/") and "svg" not in ctype and "xml" not in ctype
    disp = "inline" if _inline_ok else "attachment"
    return StreamingResponse(resp, media_type=ctype, headers={
        "Cache-Control": "private, max-age=3600",
        "X-Content-Type-Options": "nosniff",
        "Content-Disposition": "%s; filename*=UTF-8''%s" % (
            disp, urllib.parse.quote(filename or "file")),
    })


@router.get("/tickets/{issue_id}/logs")
def ticket_logs(issue_id: int, n: int = 300):


    q = "#%d" % issue_id
    rx = re.compile(r"%s(?!\d)" % re.escape(q))

    def _own(recs):
        return [r for r in recs
                if rx.search(str(r.get("msg") or "") + " " + str(r.get("exc") or ""))]

    return {"logs": _own(core.read_logs(core.ROOT, q=q, n=n)),
            "trace": _own(core.read_trace(q=q, n=n))}
