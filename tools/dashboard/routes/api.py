# -*- coding: utf-8 -*-


import time

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from .. import core
from ..models import (AgentConfigRequest, DecideRequest, DispatchRequest,
                      InvokeOpusRequest, ModeRequest, PauseRequest,
                      RedmineAccountRequest, RedmineActiveRequest, RoutingEditRequest)

router = APIRouter(prefix="/api")


@router.get("/dashboard")
def dashboard():
    feed = core.build_feed(core.ROOT)
    return {"agent": core.agent_status(),
            "stats": core.stats24(feed),
            "recent": core.recent_events(feed, limit=30),
            "redmine_url": feed["redmine_url"]}


@router.get("/emails")
def emails(q: str = "", verdict: str = "", period: str = "", limit: int = 300):


    feed = core.build_feed(core.ROOT, limit=max(1, min(limit, 1000)))
    mails = feed["mails"]
    if q:
        ql = q.lower()
        mails = [e for e in mails
                 if ql in (e["subject"] + " " + e["note"] + " " + e["key"]).lower()]
    if verdict:
        mails = [e for e in mails if e["verdict"] == verdict]
    horizon = {"today": 1, "week": 7, "month": 30}.get(period)
    if horizon:
        cutoff = time.time() - horizon * core.DAY
        mails = [e for e in mails if e["last_ts"] > cutoff]
    for e in mails:
        e["session_id"] = core.find_session_id(e)
    return {"items": mails, "redmine_url": feed["redmine_url"]}


@router.get("/approvals")
def approvals_list():
    feed = core.build_feed(core.ROOT)
    return {"items": feed["approvals"], "redmine_url": feed["redmine_url"]}


@router.post("/approvals/{issue_id}")
def approvals_decide(issue_id: int, body: DecideRequest):


    ok, err = core.approvals.decide(core.ROOT, issue_id, body.decision,
                                    model=body.model, effort=body.effort)
    return {"ok": ok, "error": err}


@router.post("/tickets/{issue_id}/invoke_opus")
def invoke_opus(issue_id: int, body: InvokeOpusRequest):


    ok, err = core.approvals.create_manual_opus(
        core.ROOT, issue_id, body.subject or "", body.prompt or "",
        model=body.model, effort=body.effort)
    return {"ok": ok, "error": err}


@router.post("/tickets/{issue_id}/dispatch")
def dispatch(issue_id: int, body: DispatchRequest):


    if body.branch == "opus":
        ok, err = core.approvals.create_manual_opus(
            core.ROOT, issue_id, body.subject or "", body.prompt or "",
            model=body.model, effort=body.effort)
    else:
        ok, err = core.approvals.create_manual_alert(core.ROOT, issue_id, body.subject or "")
    return {"ok": ok, "error": err}


@router.get("/logs")
def logs(src: str = "logs", q: str = "", level: str = "", logger: str = "", n: int = 400):


    if src == "trace":
        return core.read_trace(q=q, n=n)
    recs = core.read_logs(core.ROOT, q=q, n=5000)
    if level:
        want = {s.strip().upper() for s in level.split(",") if s.strip()}
        recs = [r for r in recs if str(r.get("level", "")).upper() in want]
    if logger:
        lgl = logger.lower()
        recs = [r for r in recs if lgl in str(r.get("logger", "")).lower()]
    try:
        n = max(1, min(int(n), 5000))
    except (TypeError, ValueError):
        n = 400
    return recs[-n:]


@router.get("/agent/status")
def agent_status():
    return core.agent_status()


@router.post("/agent/start")
def agent_start():
    ok, msg = core.start_agent()
    return {"ok": ok, "message": msg}


@router.post("/agent/stop")
def agent_stop():
    ok, msg = core.stop_agent()
    return {"ok": ok, "message": msg}


@router.post("/agent/restart")
def agent_restart():
    ok, msg = core.restart_agent()
    return {"ok": ok, "message": msg}


@router.post("/agent/mode")
def agent_mode(body: ModeRequest):


    ok, msg = core.set_run_mode(body.dry_run)
    return {"ok": ok, "message": msg}


@router.post("/agent/pause")
def agent_pause(body: PauseRequest):


    ok, msg = core.set_paused(body.paused)
    return {"ok": ok, "message": msg}


@router.get("/agent/config")
def agent_config_get():

    return core.read_agent_config()


@router.post("/agent/config")
def agent_config_set(body: AgentConfigRequest):


    ok, msg = core.set_agent_config(body.dict(exclude_none=True))
    return {"ok": ok, "message": msg}


@router.get("/redmine/accounts")
def redmine_accounts_get():


    accs = core.redmine_accounts()
    return {"accounts": accs, "active": next((a["name"] for a in accs if a["active"]), None)}


@router.post("/redmine/accounts")
def redmine_account_save(body: RedmineAccountRequest):


    ok, msg = core.save_redmine_account(body.name, api_key=body.api_key, url=body.url,
                                        label=body.label, make_active=body.make_active)
    return {"ok": ok, "message": msg}


@router.post("/redmine/accounts/active")
def redmine_account_activate(body: RedmineActiveRequest):

    ok, msg = core.set_redmine_active(body.name)
    return {"ok": ok, "message": msg}


@router.post("/redmine/accounts/delete")
def redmine_account_delete(body: RedmineActiveRequest):

    ok, msg = core.delete_redmine_account(body.name)
    return {"ok": ok, "message": msg}


@router.post("/agent/routing")
def agent_routing(body: RoutingEditRequest):

    ok, msg = core.edit_routing(body.action, body.key,
                                project_id=body.project_id, client=body.client)
    return {"ok": ok, "message": msg}


_EXPORT = {"logs": (core.LOG_FILE, "agent.jsonl"),
           "trace": (core.TRACE_FILE, "agent_trace.jsonl"),
           "journal": (core.JOURNAL_FILE, "processed.jsonl")}


@router.get("/export/logs")
def export_logs(src: str = "logs"):


    if src not in _EXPORT:
        raise HTTPException(400, "src должен быть logs|trace|journal")
    path, name = _EXPORT[src]
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        raise HTTPException(404, "файл %s ещё не создан" % name)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return Response(data, media_type="application/jsonl", headers={
        "Content-Disposition": 'attachment; filename="%s-%s"' % (stamp, name)})
