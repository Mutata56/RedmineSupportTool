# -*- coding: utf-8 -*-


import json
import os
import shutil
import signal
import subprocess
import tempfile
import threading
import time

from fastapi import APIRouter

from .. import core
from ..models import ChatRequest
from agent.claude_cli import _DENY_TOOLS

router = APIRouter(prefix="/api/claude")

TIMEOUT = 120
SESSIONS = {}
_SESSIONS_LOCK = threading.Lock()
MAX_SESSIONS = 50
MAX_MESSAGES = 200


def _claude_bin():
    return (os.environ.get("DASH_CLAUDE_BIN")
            or (core.load_config().get("llm") or {}).get("claude_bin")
            or "claude")


def _run(message, session_id=None):

    claude_bin = _claude_bin()
    if not shutil.which(claude_bin) and not os.path.isabs(claude_bin):
        return None, "claude CLI не найден (%s)" % claude_bin


    cmd = [claude_bin, "-p",
           "--output-format", "json",
           "--disallowedTools", _DENY_TOOLS,

           "--strict-mcp-config",
           "--permission-mode", "default"]
    if session_id:
        cmd += ["--resume", session_id]
    env = os.environ.copy()
    env.pop("ANTHROPIC_API_KEY", None)
    env.pop("ANTHROPIC_AUTH_TOKEN", None)


    cwd = os.path.join(core.ROOT, "state", "dash_chat_cwd")
    os.makedirs(cwd, exist_ok=True)
    try:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                env=env, cwd=cwd, start_new_session=True, text=True)
        try:
            out, err = proc.communicate(input=message, timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except OSError:
                proc.kill()
            proc.communicate()
            return None, "таймаут %d сек" % TIMEOUT
        if proc.returncode != 0:
            return None, "claude rc=%s (%s)" % (proc.returncode, (err or "").strip()[:200])
    except OSError as e:
        return None, "запуск не удался: %s" % e
    try:
        envelope = json.loads(out)
    except (json.JSONDecodeError, TypeError):
        return None, "битый JSON-ответ CLI"
    if not isinstance(envelope, dict) or envelope.get("is_error"):
        return None, "CLI вернул ошибку: %s" % str(envelope)[:200]
    return envelope, None


def _remember(sid, role, text):
    with _SESSIONS_LOCK:
        s = SESSIONS.setdefault(sid, {"created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                                      "messages": []})
        s["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        s["messages"].append({"role": role, "text": text,
                              "at": time.strftime("%H:%M:%S")})
        if len(s["messages"]) > MAX_MESSAGES:
            del s["messages"][:-MAX_MESSAGES]
        while len(SESSIONS) > MAX_SESSIONS:
            oldest = min(SESSIONS, key=lambda k: SESSIONS[k].get("updated_at", ""))
            if oldest == sid:
                break
            del SESSIONS[oldest]


@router.post("/chat")
def chat(body: ChatRequest):


    envelope, err = _run(body.message.strip(), body.session_id)
    if err:
        return {"ok": False, "error": err, "session_id": body.session_id}
    sid = envelope.get("session_id") or body.session_id or "?"
    text = (envelope.get("result") or "").strip() or "(пустой ответ)"
    _remember(sid, "user", body.message.strip())
    _remember(sid, "claude", text)
    usage = envelope.get("usage") or {}
    return {"ok": True, "text": text, "session_id": sid,
            "usage": {"input_tokens": usage.get("input_tokens"),
                      "output_tokens": usage.get("output_tokens"),
                      "duration_ms": envelope.get("duration_ms"),
                      "total_cost_usd": envelope.get("total_cost_usd")}}


@router.get("/sessions")
def sessions():

    with _SESSIONS_LOCK:
        items = [{"session_id": sid,
                  "created_at": s.get("created_at"),
                  "updated_at": s.get("updated_at"),
                  "messages": len(s["messages"])}
                 for sid, s in SESSIONS.items()]
    return {"items": items}


@router.get("/sessions/{session_id}")
def session_history(session_id: str):
    s = SESSIONS.get(session_id)
    return {"session_id": session_id, "messages": (s or {}).get("messages", [])}
