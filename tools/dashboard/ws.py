# -*- coding: utf-8 -*-


import asyncio
import json
import logging
import os

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from . import core

log = logging.getLogger("dashboard.ws")
router = APIRouter()

POLL_SECONDS = 1.0
MAX_PUSH_PER_TICK = 80
SEND_TIMEOUT = 5.0
MAX_TAIL_BYTES = 512 * 1024


class Broadcaster:
    def __init__(self):
        self.clients = set()

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.clients.add(ws)

    def forget(self, ws: WebSocket):
        self.clients.discard(ws)

    async def broadcast(self, payload: dict):


        clients = list(self.clients)
        if not clients:
            return
        results = await asyncio.gather(
            *(asyncio.wait_for(ws.send_json(payload), SEND_TIMEOUT) for ws in clients),
            return_exceptions=True)
        for ws, res in zip(clients, results):
            if isinstance(res, BaseException):


                self.forget(ws)
                try:
                    await ws.close()
                except Exception:
                    pass


broadcaster = Broadcaster()


class FileTail:


    def __init__(self, path):
        self.path = path
        self.offset = None
        self.inode = None

    def read_new(self):
        try:
            stat = os.stat(self.path)
            size, inode = stat.st_size, stat.st_ino
        except OSError:
            self.offset = self.inode = None
            return []
        if self.offset is None:
            self.offset, self.inode = size, inode
            return []


        if inode != self.inode or size < self.offset:
            self.offset, self.inode = 0, inode
        if size <= self.offset:
            return []


        start = self.offset
        skipped_mid = False
        if size - start > MAX_TAIL_BYTES:
            start = size - MAX_TAIL_BYTES
            skipped_mid = True
        out = []
        try:
            with open(self.path, "rb") as f:
                f.seek(start)
                data = f.read(size - start)
            if skipped_mid:

                nl = data.find(b"\n")
                if nl < 0:
                    self.offset = size
                    return []
                data = data[nl + 1:]
                start += nl + 1

            end = data.rfind(b"\n")
            if end < 0:
                return []
            self.offset = start + end + 1
            for raw in data[:end].splitlines():
                try:
                    rec = json.loads(raw.decode("utf-8", "replace"))
                except json.JSONDecodeError:
                    continue
                if isinstance(rec, dict):
                    out.append(rec)
        except OSError:
            pass
        return out


def _status_payload():
    st = core.agent_status()
    return {"type": "agent_status",
            "status": st["state"],
            "mode": "dry-run" if st["dry_run"] else "live",
            "status_line": st["status_line"],
            "uptime": st["uptime_seconds"],
            "started_at": st["started_at"],
            "pid": st["pid"],
            "paused": st.get("paused", False)}


class Watcher:
    def __init__(self):
        self.log_tail = FileTail(core.LOG_FILE)
        self.trace_tail = FileTail(core.TRACE_FILE)
        self.last_status = None
        self.known_pending = None
        self.journal_size = None
        self._task = None

    def start(self):

        self._task = asyncio.get_running_loop().create_task(self._loop())

    async def stop(self):
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass

    async def _loop(self):
        while True:
            try:
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("тик наблюдателя упал - продолжаю")
            await asyncio.sleep(POLL_SECONDS)

    async def _tick(self):

        for rec in self.log_tail.read_new()[-MAX_PUSH_PER_TICK:]:
            await broadcaster.broadcast({"type": "event", "data": rec})
        for rec in self.trace_tail.read_new()[-MAX_PUSH_PER_TICK:]:
            await broadcaster.broadcast({"type": "trace", "data": rec})


        payload = _status_payload()
        sig = (payload["status"], payload["status_line"], payload["pid"],
               payload["mode"], payload["paused"])
        if sig != self.last_status:
            self.last_status = sig
            await broadcaster.broadcast(payload)


        pend = {}
        for ap in core.approvals.load_all(core.ROOT):
            if ap.get("status") == "pending":
                pend[(ap.get("issue_id"), ap.get("stage"))] = ap
        keys = set(pend)
        if self.known_pending is None:
            self.known_pending = keys
        elif keys != self.known_pending:
            for key in keys - self.known_pending:
                ap = pend[key]
                if ap.get("stage") == "reviewing":
                    continue
                iid = ap.get("issue_id")
                await broadcaster.broadcast({
                    "type": "approval_request", "approval_id": iid, "issue_id": iid,
                    "pipe": ap.get("pipe"), "stage": ap.get("stage"),
                    "subject": ap.get("subject"),
                    "proposal": (ap.get("proposal") or "")[:4000],
                    "requires_attention": True})
            self.known_pending = keys
            actionable = {iid for iid, stage in keys if stage != "reviewing"}
            await broadcaster.broadcast({"type": "approvals", "count": len(actionable)})


        try:
            jsize = os.path.getsize(core.JOURNAL_FILE)
        except OSError:
            jsize = 0
        if self.journal_size is None:
            self.journal_size = jsize
        elif jsize != self.journal_size:
            self.journal_size = jsize
            await broadcaster.broadcast({"type": "feed_update"})


watcher = Watcher()


@router.websocket("/ws/events")
async def ws_events(ws: WebSocket):


    origin = ws.headers.get("origin")
    if origin and not core.origin_allowed(origin, core.allowed_ext_origins()):
        await ws.close(code=4403)
        return
    await ws.accept()


    try:
        await ws.send_json(_status_payload())
        pend = {ap.get("issue_id") for ap in core.approvals.load_all(core.ROOT)
                if ap.get("status") == "pending" and ap.get("stage") != "reviewing"}
        await ws.send_json({"type": "approvals", "count": len(pend)})
    except Exception:
        return
    broadcaster.clients.add(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        broadcaster.forget(ws)
