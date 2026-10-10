#!/usr/bin/env python3
# -*- coding: utf-8 -*-


import asyncio
import json
import os
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

FAKE_ENVELOPE = {"result": "привет из мока", "session_id": "00000000-mock",
                 "usage": {"input_tokens": 11, "output_tokens": 7},
                 "duration_ms": 5, "is_error": False}


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def make_fake_claude(tmpdir):

    path = os.path.join(tmpdir, "claude-fake")
    with open(path, "w", encoding="utf-8") as f:
        f.write("#!/bin/sh\ncat <<'EOF'\n%s\nEOF\n"
                % json.dumps(FAKE_ENVELOPE, ensure_ascii=False))
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)
    return path


def get(url, timeout=10):


    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def post(url, payload, timeout=15):
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
            status = r.status
    except urllib.error.HTTPError as e:
        body, status = e.read(), e.code
    try:
        return status, json.loads(body)
    except ValueError:
        return status, {}


def main():
    tmpdir = tempfile.mkdtemp(prefix="wa_dash_smoke_")
    os.environ["DASH_CLAUDE_BIN"] = make_fake_claude(tmpdir)

    import uvicorn
    from tools.dashboard.app import app

    port = free_port()
    base = "http://127.0.0.1:%d" % port
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port,
                                           log_level="warning"))
    th = threading.Thread(target=server.run, daemon=True)
    th.start()
    deadline = time.time() + 15
    while not server.started:
        if time.time() > deadline:
            raise SystemExit("сервер не поднялся за 15 сек")
        time.sleep(0.1)

    failures = []

    def check(name, cond, extra=""):
        print("%-46s %s %s" % (name, "OK" if cond else "FAIL", extra))
        if not cond:
            failures.append(name)

    try:

        st, body = get(base + "/")
        check("GET /", st == 200 and b"AI Agent Control Center" in body)
        for u, key in [("/api/dashboard", "agent"), ("/api/emails", "items"),
                       ("/api/tickets", "items"), ("/api/approvals", "items"),
                       ("/api/agent/status", "state")]:
            st, body = get(base + u)
            data = json.loads(body)
            check("GET " + u, st == 200 and key in data)
        for u in ["/api/logs?n=5", "/api/logs?src=trace&n=5",
                  "/api/logs?level=ERROR&n=5", "/api/logs?logger=agent.llm&n=5"]:
            st, body = get(base + u)
            check("GET " + u, st == 200 and isinstance(json.loads(body), list))
        st, body = get(base + "/api/export/logs?src=journal")

        check("GET /api/export/logs?src=journal",
              (st == 200 and len(body) > 0) or st == 404)


        st, body = get(base + "/api/tickets")
        items = json.loads(body)["items"]
        if items:
            iid = items[0]["issue_id"]
            st, body = get(base + "/api/tickets/%d" % iid)
            check("GET /api/tickets/%d" % iid,
                  st == 200 and json.loads(body)["issue_id"] == iid)
            st, body = get(base + "/api/tickets/%d/logs" % iid)
            d = json.loads(body)
            check("GET /api/tickets/%d/logs" % iid,
                  st == 200 and "logs" in d and "trace" in d)


        st, d = post(base + "/api/approvals/999999999", {"decision": "manual"})
        check("POST /api/approvals/<нет такой>", st == 200 and d["ok"] is False, d.get("error", ""))


        st, d = post(base + "/api/claude/chat", {"message": "smoke-проверка"})
        check("POST /api/claude/chat (мок)",
              st == 200 and d.get("ok") and d.get("text") == "привет из мока"
              and d.get("session_id") == "00000000-mock",
              str(d)[:100])
        st, body = get(base + "/api/claude/sessions")
        check("GET /api/claude/sessions",
              st == 200 and len(json.loads(body)["items"]) == 1)


        async def ws_probe():
            import websockets
            async with websockets.connect("ws://127.0.0.1:%d/ws/events" % port,
                                          open_timeout=10) as ws:
                first = json.loads(await asyncio.wait_for(ws.recv(), 10))
                second = json.loads(await asyncio.wait_for(ws.recv(), 10))
                return first, second

        first, second = asyncio.run(ws_probe())
        check("WS /ws/events (agent_status + approvals)",
              first.get("type") == "agent_status" and second.get("type") == "approvals",
              "status=%s" % first.get("status"))


        t = subprocess.run([sys.executable, "-m", "pytest", os.path.join(ROOT, "tools", "dashboard", "test_dashboard.py"), "-q"],
                           capture_output=True, text=True)
        tail = (t.stdout + t.stderr).strip().splitlines()
        check("регресс-тесты (test_dashboard.py)", t.returncode == 0,
              tail[-1] if tail else "нет вывода")
    finally:
        server.should_exit = True
        th.join(timeout=10)

    if failures:
        raise SystemExit("ПРОВАЛЕНО: %s" % ", ".join(failures))
    print("\nвсе smoke-проверки пройдены")


if __name__ == "__main__":
    main()
