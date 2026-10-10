#!/usr/bin/env python3
# -*- coding: utf-8 -*-


import json
import os
import socket
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agent import sql_engine as se

PROTOCOL_VERSION = "2025-06-18"
SERVER_INFO = {"name": "wa-sql", "version": "1.0.0"}

_HOST = os.environ.get("WA_DB_HOST", "")
_PORT = int(os.environ.get("WA_DB_PORT", "1433") or "1433")
_LOGIN = os.environ.get("WA_DB_LOGIN", "sa") or "sa"
_WHSE = os.environ.get("WA_DB_WHSE", "")
_TIMEOUT = int(os.environ.get("WA_DB_TIMEOUT", "30") or "30")
_LOG = os.environ.get("WA_SQL_LOG", "")


try:
    _SERVERS = json.loads(os.environ.get("WA_DB_SERVERS") or "{}")
    if not isinstance(_SERVERS, dict):
        _SERVERS = {}
except Exception:
    _SERVERS = {}


if os.environ.get("WA_DB_TDSVER"):
    os.environ["DBPICK_TDSVER"] = os.environ["WA_DB_TDSVER"]

MAX_ROWS = 50
MAX_CELL = 200
MAX_ERR = 500


def _audit(kind, detail):

    if not _LOG:
        return
    try:
        with open(_LOG, "a", encoding="utf-8") as f:
            f.write("[%s] %s: %s\n" % (time.strftime("%H:%M:%S"), kind, detail))
    except OSError:
        pass


_SRV_LIST = ", ".join("%s=%s" % (k, v) for k, v in sorted(_SERVERS.items()))
_SRV_NAMES = ", ".join(sorted(_SERVERS))
_props = {
    "sql": {"type": "string", "description": "одиночный SELECT или WITH … SELECT"},
    "timeout_sec": {"type": "integer",
                    "description": "таймаут запроса в секундах (по умолчанию %d)" % _TIMEOUT},
}
if _SERVERS:
    _props["server"] = {"type": "string",
                        "description": "какая площадка (обязателен при нескольких): %s" % _SRV_NAMES}
TOOLS = [
    {"name": "run_select",
     "description": ((os.environ.get("WA_DB_DESCRIPTION", "") + " ").lstrip() +
                     "Выполнить ОДИН read-only SELECT/WITH на SQL-сервере площадки (логин %s%s). "
                     "Никаких изменений данных: гард отклонит всё, кроме одиночного SELECT/WITH. "
                     "Ответ ограничен 50 строками и 200 символами на ячейку. "
                     "timeout_sec ограничен диапазоном 1–600 секунд.%s"
                     % (_LOGIN, (", схема %s" % _WHSE) if _WHSE else "",
                        (" Доступные server: %s." % _SRV_LIST) if _SERVERS else "")),
     "inputSchema": {"type": "object", "properties": _props, "required": ["sql"]}},
]


def _clip(v):

    s = str(v)
    return s if len(s) <= MAX_CELL else s[:MAX_CELL - 1] + "…"


def _format_result(header, rows):


    total = len(rows)
    if not header:
        return "(нет данных)\nстрок: 0"
    n = len(header)
    shown = [[_clip(r[i] if i < len(r) else "") for i in range(n)] for r in rows[:MAX_ROWS]]
    head = [_clip(h) for h in header]
    w = [len(head[i]) for i in range(n)]
    for r in shown:
        for i in range(n):
            w[i] = max(w[i], len(r[i]))
    def fmt(cells):
        return " | ".join(cells[i].ljust(w[i]) for i in range(n))
    out = [fmt(head), "-+-".join("-" * w[i] for i in range(n))]
    out += [fmt(r) for r in shown] if shown else ["(пусто)"]
    if total > MAX_ROWS:
        out.append("…показано %d из %d" % (MAX_ROWS, total))
    out.append("строк: %d" % total)
    return "\n".join(out)


def _preflight(host, port, timeout=4):


    try:
        sock = socket.create_connection((host, int(port)), timeout=timeout)
        sock.close()
        return True, ""
    except OSError as e:
        return False, str(e)


def _tool_run_select(args):


    sql = str(args.get("sql") or "")
    ok, why = se.read_only_guard(sql)
    if not ok:
        _audit("run_select[REJECTED]", "%r: %s" % (" ".join(sql.split())[:200], why))
        return "запрос отклонён read-only гардом: %s" % why
    try:
        timeout = int(args.get("timeout_sec") or _TIMEOUT)
    except (TypeError, ValueError):
        timeout = _TIMEOUT
    timeout = max(1, min(timeout, 600))

    server = args.get("server")
    if server is not None and str(server) != "":
        host = _SERVERS.get(str(server))
        if not host:
            return "неизвестный server «%s». Доступны: %s" % (server, _SRV_NAMES or "—")
    elif _HOST:
        host = _HOST
    elif len(_SERVERS) == 1:
        host = next(iter(_SERVERS.values()))
    elif _SERVERS:
        return "укажи server (площадку): %s" % _SRV_NAMES
    else:
        return "WA_DB_HOST не задан - серверу некуда подключаться."
    pwd = se.read_db_pass(_LOGIN)
    if not pwd:
        _audit("run_select[NOPASS]", "логин=%s" % _LOGIN)
        return "нет пароля логина %s" % _LOGIN
    alive, err = _preflight(host, _PORT)
    if not alive:
        _audit("run_select[NOCONNECT]", "%s:%s: %s" % (host, _PORT, err))
        return "БД недоступна (%s:%s): %s" % (host, _PORT, err)
    t0 = time.time()
    sess = se.TsqlSession(host, _PORT, _LOGIN, pwd)
    try:
        sess.start()
        ok, out = sess.run_batch(sql, timeout=timeout)
    except se.SessionDead as e:
        _audit("run_select[DEAD]", "%r: %s" % (" ".join(sql.split())[:200], e))
        return "БД недоступна (%s:%s): %s" % (host, _PORT, e)
    finally:
        sess.close()
    if not ok:
        _audit("run_select[SQLERR]", "%r -> %s" % (" ".join(sql.split())[:200],
                                                   " ".join(out.split())[:200]))
        return "ошибка SQL:\n%s" % out[:MAX_ERR]
    header, rows = se._tsql_rows(out)
    _audit("run_select", "%r -> ok, строк=%d (%.1fс)"
           % (" ".join(sql.split())[:200], len(rows), time.time() - t0))
    return _format_result(header, rows)


_HANDLERS = {"run_select": _tool_run_select}


def _send(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _result(rid, result):
    _send({"jsonrpc": "2.0", "id": rid, "result": result})


def _error(rid, code, message):
    _send({"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}})


def _handle(msg):
    method = msg.get("method")
    rid = msg.get("id")
    if method == "initialize":
        client_ver = (msg.get("params") or {}).get("protocolVersion") or PROTOCOL_VERSION
        _result(rid, {"protocolVersion": client_ver,
                      "capabilities": {"tools": {"listChanged": False}},
                      "serverInfo": SERVER_INFO})
    elif method in ("notifications/initialized", "initialized"):
        pass
    elif method == "ping":
        _result(rid, {})
    elif method == "tools/list":
        _result(rid, {"tools": TOOLS})
    elif method == "tools/call":
        params = msg.get("params") or {}
        name = params.get("name")
        args = params.get("arguments") or {}
        fn = _HANDLERS.get(name)
        if not fn:
            _result(rid, {"content": [{"type": "text", "text": "Неизвестный инструмент: %s" % name}],
                          "isError": True})
            return
        try:
            text = fn(args)
            _result(rid, {"content": [{"type": "text", "text": text}]})
        except Exception as e:
            _result(rid, {"content": [{"type": "text", "text": "Ошибка инструмента %s: %s"
                                       % (name, e)}], "isError": True})
    elif rid is not None:
        _error(rid, -32601, "Method not found: %s" % method)


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        try:
            _handle(msg)
        except Exception as e:
            if isinstance(msg, dict) and msg.get("id") is not None:
                _error(msg.get("id"), -32603, "Internal error: %s" % e)


if __name__ == "__main__":
    main()
