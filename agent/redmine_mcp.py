#!/usr/bin/env python3
# -*- coding: utf-8 -*-


import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agent.redmine_client import RedmineClient

PROTOCOL_VERSION = "2025-06-18"
SERVER_INFO = {"name": "redmine", "version": "1.0.0"}

_URL = os.environ.get("RM_URL", "")
_KEY = os.environ.get("RM_API_KEY", "")
def _env_int(name, default=0):


    try:
        return int((os.environ.get(name) or "").strip() or default)
    except (TypeError, ValueError):
        return default


def _env_int_list(name):


    out = []
    for x in (os.environ.get(name) or "").split(","):
        x = x.strip()
        if not x:
            continue
        try:
            out.append(int(x))
        except ValueError:
            continue
    return out


_SOURCE = _env_int("RM_SOURCE_ISSUE", 0)
_CONTOURS = _env_int_list("RM_CONTOUR_PROJECTS")
_LIMIT = _env_int("RM_SEARCH_LIMIT", 40) or 40
_DRY = os.environ.get("RM_DRY", "") == "1"
_READ_ONLY = os.environ.get("RM_READ_ONLY", "") == "1"
_LOG = os.environ.get("RM_LOG", "")
_DRAFT = os.environ.get("RM_DRAFT_FILE", "")


_rc = RedmineClient(_URL, _KEY)


def _audit(kind, detail):


    if not _LOG:
        return
    try:
        with open(_LOG, "a", encoding="utf-8") as f:
            f.write("[%s] %s: %s\n" % (time.strftime("%H:%M:%S"), kind, detail))
    except OSError:
        pass


TOOLS = [
    {"name": "search_similar",
     "description": "Найти похожие заявки в настроенных проектах Redmine, РЕШЁННЫЕ первыми "
                    "(resolved=true). Возвращает id, тему, проект, статус, resolved. "
                    "Дальше бери детали через get_issue.",
     "inputSchema": {"type": "object", "properties": {
         "query": {"type": "string", "description": "ключевые слова из темы/тела заявки"}},
         "required": ["query"]}},
    {"name": "get_issue",
     "description": "Тема, тело и ВСЕ комментарии (журналы) заявки по её id - там инженеры оставляли "
                    "SQL и решения. Read-only.",
     "inputSchema": {"type": "object", "properties": {
         "issue_id": {"type": "integer", "description": "id заявки"}},
         "required": ["issue_id"]}},
    {"name": "post_private_note",
     "description": "Добавить ПРИВАТНЫЙ комментарий в ЭТУ заявку (id фиксирован сервером). "
                    "Единственная операция записи. Только приватно, только в исходную заявку. "
                    "ПУБЛИКУЕТСЯ ТОЛЬКО при confidence=high; при medium/low комментарий НЕ "
                    "публикуется, а сохраняется в логах для человека - оценивай честно, "
                    "непубликация при сомнении является правильным исходом.",
     "inputSchema": {"type": "object", "properties": {
         "note": {"type": "string", "description": "текст приватного комментария (Markdown/Textile)"},
         "confidence": {"type": "string", "enum": ["high", "medium", "low"],
                        "description": "честная уверенность в предложенном решении"},
         "approved_screenshots": {"type": "array", "items": {"type": "string"},
                                  "description": "разбор алерта: id одобренных скриншотов "
                                                 "(напр. [\"p78\"]) - программа приложит "
                                                 "ТОЛЬКО их к комментарию; без скриншотов "
                                                 "параметр не передавай"}},
         "required": ["note", "confidence"]}},
]


if _READ_ONLY:

    TOOLS = [tool for tool in TOOLS if tool["name"] != "post_private_note"]


def _tool_search_similar(args):
    query = (args.get("query") or "").strip()
    if not query:
        return "Пустой запрос."
    if not _CONTOURS:
        return "Контуры клиента не заданы - поиск отключён."


    data = _rc._request("GET", "/search.json",
                        params={"q": query, "issues": 1, "limit": _LIMIT})
    ids = [r["id"] for r in data.get("results", []) if r.get("id")]
    if not ids:
        return "Похожих заявок не найдено по запросу: %s" % query

    det = _rc._request("GET", "/issues.json",
                       params={"issue_id": ",".join(map(str, ids)), "status_id": "*",
                               "limit": len(ids)})


    closed_ids = {it["id"] for it in _rc._request(
        "GET", "/issues.json",
        params={"issue_id": ",".join(map(str, ids)), "status_id": "closed",
                "limit": len(ids)}).get("issues", [])}
    out = []
    for it in det.get("issues", []):
        pid = it.get("project", {}).get("id")
        if _CONTOURS and pid not in _CONTOURS:
            continue
        out.append({"id": it["id"], "subject": it.get("subject", ""),
                    "project": it.get("project", {}).get("name", ""),
                    "status": it.get("status", {}).get("name", ""),
                    "resolved": it["id"] in closed_ids})


    out.sort(key=lambda r: not r["resolved"])
    _audit("search_similar", "query=%r -> %d кандидатов, %d в контурах (решённых %d)"
           % (query, len(ids), len(out), sum(1 for r in out if r["resolved"])))
    if not out:
        return ("Найдено %d заявок, но ни одной в контурах клиента (%s). Запрос: %s"
                % (len(ids), _CONTOURS, query))
    return json.dumps(out, ensure_ascii=False, indent=2)


def _tool_get_issue(args):
    iid = args.get("issue_id")
    try:
        iid = int(iid)
    except (TypeError, ValueError):
        return "issue_id должен быть числом."
    d = _rc._request("GET", "/issues/%d.json" % iid, params={"include": "journals"})
    i = d.get("issue", {})
    pid = i.get("project", {}).get("id")


    if iid != _SOURCE and (not _CONTOURS or pid not in _CONTOURS):
        _audit("get_issue", "#%d ОТКАЗ (вне контуров)" % iid)
        return "Заявка #%d вне контуров этого клиента - чтение запрещено." % iid
    _audit("get_issue", "#%d %r" % (iid, (i.get("subject") or "")[:60]))
    notes = [{"author": j.get("user", {}).get("name", ""), "on": j.get("created_on", ""),
              "note": j.get("notes", "")}
             for j in i.get("journals", []) if (j.get("notes") or "").strip()]
    return json.dumps({"id": i.get("id"), "subject": i.get("subject", ""),
                       "project": i.get("project", {}).get("name", ""),
                       "status": i.get("status", {}).get("name", ""),
                       "tracker": i.get("tracker", {}).get("name", ""),
                       "description": i.get("description", ""),
                       "journals": notes}, ensure_ascii=False, indent=2)


def _tool_post_private_note(args):


    if _READ_ONLY:
        return "Операция записи отключена в глобальном MCP Redmine."
    note = args.get("note")
    if not note or not str(note).strip():
        return "Пустой комментарий - не пишу."
    conf = str(args.get("confidence") or "").strip().lower()
    if _DRAFT:


        payload = {"note": str(note), "confidence": conf, "issue_id": _SOURCE}
        shots = args.get("approved_screenshots")
        if isinstance(shots, list):
            payload["approved_screenshots"] = [str(x) for x in shots]
        try:
            with open(_DRAFT, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
        except OSError as e:
            _audit("draft_write_failed", "цель=#%d: %s" % (_SOURCE, e))

            return ("ОШИБКА: черновик НЕ сохранён (%s). Ничего не потеряй: повтори вызов "
                    "post_private_note тем же текстом." % e)
        _audit("post_private_note[STAGED]",
               "цель=#%d, confidence=%s, длина=%d%s - отправлен на ОДОБРЕНИЕ публикации в GUI"
               % (_SOURCE, conf or "не указана", len(str(note)),
                  (", скринов одобрено %d" % len(shots)) if isinstance(shots, list) else ""))
        return ("Черновик приватного комментария сохранён и отправлен инженеру на ОДОБРЕНИЕ "
                "публикации в GUI - он опубликует вручную. Больше по этой заявке ничего делать "
                "не нужно, задача выполнена.")
    if conf != "high":
        _audit("POST_SUPPRESSED", "confidence=%s, цель=#%d, черновик:\n%s"
               % (conf or "не указана", _SOURCE, str(note)))
        return ("Комментарий НЕ опубликован: confidence=%s (публикуем только high). Это "
                "ожидаемое поведение - заявку разберёт человек, твой анализ сохранён в логах."
                % (conf or "не указана"))
    if not _SOURCE:
        return "RM_SOURCE_ISSUE не задан - писать некуда."
    if _DRY:

        _audit("post_private_note[DRY]", "цель=#%d, черновик:\n%s" % (_SOURCE, str(note)))
        return "DRY: приватный коммент НЕ отправлен (RM_DRY=1). Длина=%d симв., цель=#%d." % (
            len(str(note)), _SOURCE)
    _rc.add_note(_SOURCE, str(note), private=True)
    _audit("post_private_note", "цель=#%d, длина=%d" % (_SOURCE, len(str(note))))
    return "Приватный комментарий добавлен в заявку #%d." % _SOURCE


_HANDLERS = {"search_similar": _tool_search_similar,
             "get_issue": _tool_get_issue,
             "post_private_note": _tool_post_private_note}
if _READ_ONLY:

    _HANDLERS.pop("post_private_note")


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
