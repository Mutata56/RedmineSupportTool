# -*- coding: utf-8 -*-


from fastapi import APIRouter
from fastapi.responses import FileResponse, JSONResponse

from .. import drafts
from . import chats

router = APIRouter(prefix="/api/drafts")


@router.get("/{issue_id}/shot/{sid}")
def draft_shot(issue_id: int, sid: str):
    path = drafts.resolve_shot(drafts.load_draft(issue_id), sid)
    if not path:
        return JSONResponse({"ok": False, "error": "нет такого скриншота"}, status_code=404)
    return FileResponse(path, media_type="image/png")


@router.post("/{issue_id}/publish")
def draft_publish(issue_id: int):


    res = drafts.publish_draft(issue_id)
    reason = res.get("reason")
    if reason not in ("no_draft", "already_posted"):

        chats.append_ai_note(issue_id, res.get("text") or "", error=not res.get("ok"))
    if reason == "no_draft":
        return JSONResponse(res, status_code=404)
    return res
