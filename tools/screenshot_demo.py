#!/usr/bin/env python3
"""Serve the dashboard with fictional data on a fresh localhost port.

Only static assets and the fixtures below are read. No agent, configuration,
mailbox, database, or integration module is imported. Every write is rejected.
"""
from __future__ import annotations

import argparse
import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

STATIC = Path(__file__).resolve().parent / "dashboard" / "static"
EXAMPLE_URL = "https://tickets.example.invalid"
DAY = "2026-01-01"


def record(verdict, minute, note, detail=""):
    return {"verdict": verdict, "at": f"{DAY} 10:{minute:02}:00", "ts": 1767261600 + minute * 60,
            "note": note, "detail": detail}


def ticket(number, subject, verdict, minute, note, awaiting=False):
    history = [record("routed", minute - 2, "Демонстрационная карточка распознана"),
               record("ticket_taken", minute - 1, "Подготовлен пример для просмотра интерфейса"),
               record(verdict, minute, note)]
    return {"key": f"demo-ticket-{number}", "issue_id": number, "subject": subject,
            "pipe": "alert", "verdict": verdict, "last_at": history[-1]["at"],
            "last_ts": history[-1]["ts"], "note": note, "records": history,
            "awaiting_decision": awaiting, "count": len(history)}


TICKETS = [
    ticket(1001, "Демо: увеличилось время обработки задания", "opus_draft_ready", 24,
           "Черновик разбора подготовлен. Ожидает решения инженера.", True),
    ticket(1002, "Демо: очередь заданий ожидает проверки", "opus_requested", 20,
           "Демонстрационная эскалация: доступны выбор модели и уровня анализа.", True),
    ticket(1003, "Демо: проверка доступности сервиса", "grafana_attached", 16,
           "Пример завершённой обработки: диагностические материалы собраны."),
    ticket(1004, "Демо: импорт демонстрационного файла", "ticket_taken", 11,
           "Карточка показана в рабочем списке. Внешние действия отключены."),
]

APPROVALS = [
    {"issue_id": 1001, "subject": TICKETS[0]["subject"], "status": "pending", "pipe": "opus",
     "stage": "post", "reason": "alert_analysis", "created_at": f"{DAY} 10:24:00",
     "model": "sonnet", "effort": "high", "proposal":
     "Демонстрационный разбор\n\nНаблюдение: время обработки выросло в вымышленной серии измерений.\n"
     "Проверка: сравнить длину очереди и доступность сервиса.\n"
     "Предложение: инженер проверяет выводы и выбирает дальнейшее действие.\n\n"
     "Все данные этой карточки созданы только для демонстрации интерфейса."},
    {"issue_id": 1002, "subject": TICKETS[1]["subject"], "status": "pending", "pipe": "opus",
     "reason": "manual", "created_at": f"{DAY} 10:20:00", "model": "sonnet", "effort": "high",
     "prompt": "Покажи пример разбора вымышленной очереди заданий.", "proposal":
     "Пример запроса дополнительного анализа. Выбор модели и effort показан на демонстрационных данных."},
]

MAILS = [
    {"key": "demo-mail-1", "subject": "Демо: ежедневная проверка сервиса", "verdict": "dry_run_create",
     "issue_id": None, "last_at": f"{DAY} 10:18:00", "last_ts": 1767262680,
     "note": "Вымышленное письмо. В демостенде почтовые подключения отсутствуют.",
     "records": [record("routed", 17, "Распознан демонстрационный маркер"),
                 record("dry_run_create", 18, "Пример результата обработки: запись не выполняется.")]},
    {"key": "demo-mail-2", "subject": "Демо: повторное уведомление", "verdict": "duplicate",
     "issue_id": 1003, "last_at": f"{DAY} 10:15:00", "last_ts": 1767262500,
     "note": "Пример дедупликации уведомлений.",
     "records": [record("duplicate", 15, "Вымышленный дубль связан с демонстрационной карточкой.")]},
    {"key": "demo-mail-3", "subject": "Демо: информационное сообщение", "verdict": "no_marker",
     "issue_id": None, "last_at": f"{DAY} 10:08:00", "last_ts": 1767262080,
     "note": "Пример сообщения без маркера обработки.",
     "records": [record("no_marker", 8, "Демонстрационный информационный текст.")]},
]

LOG_MESSAGES = [
    "Демонстрационный интерфейс готов к просмотру",
    "Внешние интеграции отключены; используется фиктивный набор данных",
    "Подготовлены четыре демонстрационные карточки",
    "Показаны примеры маршрутизации и дедупликации",
    "Сформирован пример диагностического контекста",
    "Для карточки #1001 подготовлен демонстрационный черновик",
    "Публикация черновика ожидает решения инженера",
    "Для карточки #1002 показан пример эскалации",
    "Все операции изменения данных заблокированы демостендом",
    "Почтовый агент и рабочие сервисы не запускаются",
    "Демонстрационные данные обновлены",
    "Интерфейс ожидает действий пользователя",
]
LOGS = [{"at": f"10:{8 + i:02}:00", "level": "INFO", "logger": "demo.monitor", "msg": message}
        for i, message in enumerate(LOG_MESSAGES)]

AGENT = {"state": "dry-run", "dry_run": True, "paused": False,
         "status_line": "Демонстрационный просмотр · интеграции отключены", "uptime_seconds": 3720,
         "started_at": f"{DAY} 09:00:00", "pid": None}


def fixture(path):
    if path == "/api/dashboard":
        return {"agent": AGENT, "redmine_url": EXAMPLE_URL,
                "stats": {"mails_24h": 12, "tickets_24h": 8, "pending": 2, "created_24h": 6,
                          "errors_24h": 0, "ai_calls_24h": 4}}
    if path == "/api/emails":
        return {"items": MAILS, "redmine_url": EXAMPLE_URL}
    if path == "/api/tickets":
        return {"items": TICKETS, "redmine_url": EXAMPLE_URL}
    if path == "/api/approvals":
        return {"items": APPROVALS, "redmine_url": EXAMPLE_URL}
    if path == "/api/logs":
        return LOGS
    if path == "/api/agent/status":
        return AGENT
    if path == "/api/claude/sessions":
        return {"items": []}
    if path.startswith("/api/tickets/"):
        parts = path.strip("/").split("/")
        if len(parts) not in {3, 4} or not parts[2].isdigit():
            return None
        number = int(parts[2])
        item = next((item for item in TICKETS if item["issue_id"] == number), None)
        if item is None:
            return None
        if len(parts) == 4:
            return {"logs": LOGS[-5:], "trace": []} if parts[3] == "logs" else None
        result = dict(item)
        result["approval"] = next((a for a in APPROVALS if a["issue_id"] == number), None)
        return result
    return None


class DemoHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def audit(self):
        if self.server.audit_file:
            with self.server.audit_file.open("a", encoding="utf-8") as file:
                file.write(json.dumps({"method": self.command, "path": urlsplit(self.path).path}) + "\n")

    def send_data(self, data, content_type, status=200):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", "default-src 'self'; connect-src 'self'; "
                         "img-src 'self' data:; font-src 'self'; style-src 'self' 'unsafe-inline'; "
                         "script-src 'self' 'unsafe-inline' 'unsafe-eval'")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def do_GET(self):
        self.audit()
        path = urlsplit(self.path).path
        if path.startswith("/api/"):
            value = fixture(path)
            status = 200 if value is not None else 404
            value = value if value is not None else {"ok": False, "error": "Endpoint unavailable in demo"}
            return self.send_data(json.dumps(value, ensure_ascii=False).encode(), "application/json; charset=utf-8", status)
        if path == "/":
            data = (STATIC / "index.html").read_text()
            badge = '<div style="position:fixed;bottom:12px;right:20px;z-index:50;padding:7px 12px;border:1px solid #334155;border-radius:8px;background:#0f172a;color:#94a3b8;font:12px sans-serif">ДЕМО · вымышленные данные</div>'
            data = data.replace("</body>", badge + "</body>")
            return self.send_data(data.encode(), "text/html; charset=utf-8")
        if path.startswith("/static/"):
            file = (STATIC / path.removeprefix("/static/")).resolve()
            if file.is_relative_to(STATIC.resolve()) and file.is_file():
                return self.send_data(file.read_bytes(), mimetypes.guess_type(file.name)[0] or "application/octet-stream")
        self.send_data(b"Not found", "text/plain", 404)

    do_HEAD = do_GET

    def do_POST(self):
        self.audit()
        self.send_data(json.dumps({"ok": False, "error": "Demo is read-only; actions are disabled"}).encode(),
                       "application/json", 405)

    do_PUT = do_POST
    do_PATCH = do_POST
    do_DELETE = do_POST


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ready-file", type=Path)
    parser.add_argument("--audit-file", type=Path)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", 0), DemoHandler)
    server.audit_file = args.audit_file
    url = f"http://127.0.0.1:{server.server_port}"
    if args.ready_file:
        args.ready_file.write_text(json.dumps({"url": url, "read_only": True, "synthetic_data": True}))
    print(url, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
