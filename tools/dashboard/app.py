# -*- coding: utf-8 -*-


import contextlib
import logging
import os

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import core, ws
from .routes import api, chats, claude, drafts, humanize, tickets

logging.basicConfig(level=logging.INFO)

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


@contextlib.asynccontextmanager
async def _lifespan(app):
    ws.watcher.start()
    yield
    await ws.watcher.stop()


app = FastAPI(title="work_agent dashboard", docs_url="/api/docs",
              openapi_url="/api/openapi.json", lifespan=_lifespan)


@app.middleware("http")
async def _csrf_guard(request: Request, call_next):


    host = (request.headers.get("host") or "").rsplit(":", 1)[0].strip("[]")
    if host and host not in core.LOCAL_HOSTS:
        return JSONResponse({"ok": False, "error": "недопустимый Host"}, status_code=403)
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        origin = request.headers.get("origin") or request.headers.get("referer")


        if origin and not core.origin_allowed(origin, core.allowed_ext_origins()):
            return JSONResponse({"ok": False, "error": "cross-origin запрос отклонён"},
                                status_code=403)
    return await call_next(request)


app.include_router(api.router)
app.include_router(tickets.router)
app.include_router(claude.router)
app.include_router(chats.router)
app.include_router(drafts.router)
app.include_router(humanize.router)
app.include_router(ws.router)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(os.path.join(STATIC, "index.html"))
