import copy
import http.client
import json
import threading
from contextlib import contextmanager
from http.server import ThreadingHTTPServer

from tools import screenshot_demo as demo


@contextmanager
def demo_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), demo.DemoHandler)
    server.audit_file = None
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
    thread.start()
    try:
        yield server.server_port
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def request(port, method, path):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
    try:
        connection.request(method, path)
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()


def test_demo_serves_only_fictional_mail_and_existing_dashboard_assets():
    with demo_server() as port:
        status, headers, body = request(port, "GET", "/")
        assert status == 200
        assert "ДЕМО · вымышленные данные" in body.decode()
        assert "connect-src 'self'" in headers["Content-Security-Policy"]
        status, _, body = request(port, "GET", "/api/emails")
        assert status == 200
        result = json.loads(body)
        assert len(result["items"]) == 3
        assert all(item["subject"].startswith("Демо:") for item in result["items"])
        assert result["redmine_url"] == "https://tickets.example.invalid"


def test_every_supported_write_method_is_rejected_without_changing_fixtures():
    before = copy.deepcopy((demo.AGENT, demo.MAILS, demo.TICKETS, demo.APPROVALS))
    with demo_server() as port:
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            for path in ("/api/agent/start", "/api/agent/mode", "/api/claude/chat", "/api/approvals/1001"):
                status, _, body = request(port, method, path)
                assert status == 405
                assert json.loads(body)["ok"] is False
    assert (demo.AGENT, demo.MAILS, demo.TICKETS, demo.APPROVALS) == before


def test_unknown_api_and_configuration_paths_cannot_be_read():
    with demo_server() as port:
        for path in ("/api/mail/poll", "/api/agent/start", "/api/tickets/9999",
                     "/config/secrets.local.json", "/static/../../config/config.example.json"):
            status, _, _ = request(port, "GET", path)
            assert status == 404


def test_head_returns_no_body():
    with demo_server() as port:
        status, headers, body = request(port, "HEAD", "/api/dashboard")
        assert status == 200
        assert int(headers["Content-Length"]) > 0
        assert body == b""
