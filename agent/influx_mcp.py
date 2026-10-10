#!/usr/bin/env python3
# -*- coding: utf-8 -*-


import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agent.grafana_client import GrafanaClient

PROTOCOL_VERSION = "2025-06-18"
SERVER_INFO = {"name": "wa-influx", "version": "1.0.0"}

_BASE = os.environ.get("WA_GF_BASE", "")
_USER = os.environ.get("WA_GF_USER", "")
_PASSWORD = os.environ.get("WA_GF_PASSWORD", "")
_DS_ID = int(os.environ.get("WA_GF_DS_ID", "3") or "3")
_DB = os.environ.get("WA_GF_DB", "telegraf") or "telegraf"
_LOG = os.environ.get("WA_INFLUX_LOG", "")

MAX_POINTS = 200


def _audit(kind, detail):

    if not _LOG:
        return
    try:
        with open(_LOG, "a", encoding="utf-8") as f:
            f.write("[%s] %s: %s\n" % (time.strftime("%H:%M:%S"), kind, detail))
    except OSError:
        pass


TOOLS = [
    {"name": "influx_query",
     "description": "InfluxQL read-only (только SELECT/SHOW) через настроенный прокси Grafana. "
                    "Адрес, источник данных и база задаются локальной конфигурацией. "
                    "Начни с SHOW MEASUREMENTS / SHOW TAG VALUES, если не знаешь схему. "
                    "До 200 точек на серию в ответе. Используй для анализа трендов, "
                    "аномалий и состояния служб.",
     "inputSchema": {"type": "object", "properties": {
         "q": {"type": "string", "description": "InfluxQL-запрос (только SELECT или SHOW)"}},
         "required": ["q"]}},
]


_DENY = frozenset(("drop", "delete", "create", "grant", "revoke", "kill",
                   "alter", "write", "into",


                   "set", "password"))


def _regex_pos(out):


    tail = "".join(out).rstrip()
    if tail.endswith("~"):
        return True
    return re.search(r"(?:^|[^A-Za-z0-9_])from$", tail, re.I) is not None


def _strip_quoted(q):


    out, i, n = [], 0, len(q)
    balanced = True
    while i < n:
        c = q[i]
        if c == "/" and _regex_pos(out):
            i += 1
            closed = False
            while i < n:
                if q[i] == "\\" and i + 1 < n:
                    i += 2
                    continue
                if q[i] == "/":
                    i += 1
                    closed = True
                    break
                i += 1
            if not closed:
                balanced = False
            out.append(" ")
            continue
        if c in ("'", '"'):
            quote = c
            i += 1
            closed = False
            while i < n:
                if q[i] == "\\" and i + 1 < n:
                    i += 2
                    continue
                if q[i] == quote:
                    i += 1
                    closed = True
                    break
                i += 1
            if not closed:
                balanced = False
            out.append(" ")
            continue
        out.append(c)
        i += 1
    return "".join(out), balanced


def influx_guard(q):

    code, balanced = _strip_quoted(str(q or ""))
    if not balanced:
        return False, "незакрытая кавычка или регексп в запросе"


    stmts = [s for s in code.split(";") if s.strip()]
    if len(stmts) > 1:
        return False, "несколько выражений (через ;), можно только одно"
    tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", code)
    if not tokens:
        return False, "пустой запрос"
    head = tokens[0].lower()
    if head not in ("select", "show"):
        return False, "только SELECT / SHOW (а тут «%s»)" % tokens[0]
    for t in tokens:
        if t.lower() in _DENY:
            return False, "запрещённое слово «%s», только чтение" % t
    return True, ""


_gc = None


def _client():


    global _gc
    if _gc is not None:
        return _gc
    gc = GrafanaClient(_BASE, _USER, _PASSWORD)
    gc.login()
    _gc = gc
    return _gc


def _fmt_val(v):

    if isinstance(v, float) and v == int(v):
        return str(int(v))
    return str(v)


def _format_series(series):


    name = series.get("name") or "(без имени)"
    tags = series.get("tags") or {}
    cols = series.get("columns") or []
    values = series.get("values") or []
    head = name
    if tags:
        head += " {%s}" % ", ".join("%s=%s" % (k, tags[k]) for k in sorted(tags))


    pts = [v for v in values if any(x is not None for x in v[1:])] if cols[:1] == ["time"] \
        else [v for v in values if any(x is not None for x in v)]
    total = len(pts)


    if cols[:1] == ["time"]:
        try:
            pts = sorted(pts, key=lambda v: v[0], reverse=True)
        except TypeError:
            pts = list(reversed(pts))
    shown = pts[:MAX_POINTS]
    out = ["серия: %s" % head, " | ".join(str(c) for c in cols)]
    for v in shown:
        out.append(" | ".join("" if x is None else _fmt_val(x) for x in v))
    if total > MAX_POINTS:
        out.append("…%d точек всего, показано %d" % (total, MAX_POINTS))
    return "\n".join(out)


def format_results(payload):


    results = (payload or {}).get("results") or []
    if not results:
        return True, "(нет данных)"
    r0 = results[0]
    if r0.get("error"):
        return False, "ошибка InfluxDB: %s" % r0["error"]
    series = r0.get("series") or []
    if not series:
        return True, "(нет данных)"
    return True, "\n\n".join(_format_series(s) for s in series)


def _tool_influx_query(args):


    q = str(args.get("q") or "")
    ok, why = influx_guard(q)
    if not ok:
        _audit("influx_query[REJECTED]", "%r: %s" % (" ".join(q.split())[:200], why))
        return "запрос отклонён гардом: %s" % why
    if not _BASE or not _PASSWORD:
        return "WA_GF_BASE/WA_GF_PASSWORD не заданы - Grafana недоступна."
    try:
        gc = _client()
    except Exception as e:
        _audit("influx_query[NOLOGIN]", "%s" % e)
        return "Grafana недоступна: %s" % e
    t0 = time.time()
    try:
        payload = gc.influx(q, _DS_ID, _DB)
    except Exception as e:
        _audit("influx_query[ERR]", "%r -> %s" % (" ".join(q.split())[:200], e))
        return "запрос не прошёл: %s" % e
    ok, text = format_results(payload)
    nser = len(((payload or {}).get("results") or [{}])[0].get("series") or [])
    _audit("influx_query", "%r -> %s, серий=%d (%.1fс)"
           % (" ".join(q.split())[:200], "ok" if ok else "ошибка", nser, time.time() - t0))
    return text


_HANDLERS = {"influx_query": _tool_influx_query}


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
