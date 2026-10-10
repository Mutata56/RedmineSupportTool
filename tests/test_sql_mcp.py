# -*- coding: utf-8 -*-


import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from agent import sql_mcp


class FakeSession:

    calls = []
    result = (True, "id\tname\n1\talpha\n2\tbeta")

    def __init__(self, host, port, login=None, pwd=None):
        self.host, self.port, self.login, self.pwd = host, port, login, pwd
        self.started = self.closed = False

    def start(self):
        self.started = True
        return self

    def run_batch(self, sql, timeout=120):
        FakeSession.calls.append((sql, timeout))
        return FakeSession.result

    def close(self):
        self.closed = True


def _wire_ok_path(monkeypatch, result=None):


    FakeSession.calls = []
    FakeSession.result = result or (True, "id\tname\n1\talpha\n2\tbeta")
    monkeypatch.setattr(sql_mcp, "_HOST", "192.0.2.10")
    monkeypatch.setattr(sql_mcp, "_PORT", 1433)
    monkeypatch.setattr(sql_mcp, "_LOGIN", "sa")
    monkeypatch.setattr(sql_mcp, "_TIMEOUT", 30)
    monkeypatch.setattr(sql_mcp.se, "read_db_pass", lambda login: "pw")
    monkeypatch.setattr(sql_mcp, "_preflight", lambda host, port, timeout=4: (True, ""))
    monkeypatch.setattr(sql_mcp.se, "TsqlSession", FakeSession)
    return FakeSession


def test_guard_rejects_update():
    out = sql_mcp._tool_run_select({"sql": "UPDATE orders SET qty=0"})
    assert "отклонён read-only гардом" in out


def test_guard_rejects_two_statements():
    out = sql_mcp._tool_run_select({"sql": "SELECT 1; SELECT 2"})
    assert "отклонён read-only гардом" in out


def test_guard_rejects_sp():
    out = sql_mcp._tool_run_select({"sql": "sp_who"})
    assert "отклонён read-only гардом" in out

    out2 = sql_mcp._tool_run_select({"sql": "SELECT 1 sp_configure"})
    assert "отклонён read-only гардом" in out2


def test_guard_rejects_go():
    out = sql_mcp._tool_run_select({"sql": "SELECT 1\nGO\nSELECT 2"})
    assert "отклонён read-only гардом" in out


def test_guard_rejects_delete_and_exec():
    assert "отклонён read-only гардом" in sql_mcp._tool_run_select({"sql": "DELETE FROM t"})
    assert "отклонён read-only гардом" in sql_mcp._tool_run_select({"sql": "EXEC xp_cmdshell 'dir'"})


def test_guard_rejects_empty():
    assert "отклонён read-only гардом" in sql_mcp._tool_run_select({"sql": "   "})


def test_guard_allows_select(monkeypatch):
    fs = _wire_ok_path(monkeypatch)
    out = sql_mcp._tool_run_select({"sql": "SELECT id, name FROM sku"})
    assert "отклонён" not in out
    assert "alpha" in out and "beta" in out
    assert "строк: 2" in out
    assert fs.calls == [("SELECT id, name FROM sku", 30)]


def test_guard_allows_with(monkeypatch):
    _wire_ok_path(monkeypatch)
    out = sql_mcp._tool_run_select(
        {"sql": "WITH t AS (SELECT 1 AS id) SELECT * FROM t"})
    assert "отклонён" not in out
    assert "строк: 2" in out


def test_no_password(monkeypatch):
    monkeypatch.setattr(sql_mcp, "_HOST", "192.0.2.10")
    monkeypatch.setattr(sql_mcp, "_LOGIN", "sa")
    monkeypatch.setattr(sql_mcp.se, "read_db_pass", lambda login: None)
    out = sql_mcp._tool_run_select({"sql": "SELECT 1"})
    assert "нет пароля логина sa" in out


def test_db_unreachable(monkeypatch):
    monkeypatch.setattr(sql_mcp, "_HOST", "192.0.2.10")
    monkeypatch.setattr(sql_mcp, "_PORT", 1433)
    monkeypatch.setattr(sql_mcp.se, "read_db_pass", lambda login: "pw")
    monkeypatch.setattr(sql_mcp, "_preflight",
                        lambda host, port, timeout=4: (False, "timed out"))
    out = sql_mcp._tool_run_select({"sql": "SELECT 1"})
    assert "БД недоступна (192.0.2.10:1433)" in out and "timed out" in out


def test_no_host_configured(monkeypatch):
    monkeypatch.setattr(sql_mcp, "_HOST", "")
    out = sql_mcp._tool_run_select({"sql": "SELECT 1"})
    assert "WA_DB_HOST" in out


def test_sql_error_truncated(monkeypatch):
    _wire_ok_path(monkeypatch, result=(False, "Msg 208, Level 16: " + "x" * 2000))
    out = sql_mcp._tool_run_select({"sql": "SELECT * FROM missing"})
    assert out.startswith("ошибка SQL")
    assert "Msg 208" in out
    assert len(out) <= 500 + len("ошибка SQL:\n")


def test_session_closed_and_per_call(monkeypatch):

    fs = _wire_ok_path(monkeypatch)
    created = []
    orig_init = fs.__init__

    def spy_init(self, *a, **kw):
        orig_init(self, *a, **kw)
        created.append(self)
    monkeypatch.setattr(fs, "__init__", spy_init)
    sql_mcp._tool_run_select({"sql": "SELECT 1"})
    sql_mcp._tool_run_select({"sql": "SELECT 2"})
    assert len(created) == 2
    assert all(s.started and s.closed for s in created)


def test_timeout_sec_passthrough(monkeypatch):
    fs = _wire_ok_path(monkeypatch)
    sql_mcp._tool_run_select({"sql": "SELECT 1", "timeout_sec": 5})
    assert fs.calls[0][1] == 5

    sql_mcp._tool_run_select({"sql": "SELECT 1", "timeout_sec": "мусор"})
    assert fs.calls[1][1] == 30
    sql_mcp._tool_run_select({"sql": "SELECT 1", "timeout_sec": -7})
    assert fs.calls[2][1] == 1


def test_format_result_basic():
    out = sql_mcp._format_result(["id", "name"], [["1", "alpha"], ["2", "beta"]])
    lines = out.split("\n")
    assert lines[0] == "id | name "
    assert "-+-" in lines[1]
    assert lines[2].startswith("1  | alpha")
    assert lines[-1] == "строк: 2"


def test_format_result_empty():
    assert sql_mcp._format_result([], []) == "(нет данных)\nстрок: 0"
    out = sql_mcp._format_result(["id"], [])
    assert "(пусто)" in out and "строк: 0" in out


def test_format_result_cap_50():
    rows = [[str(i), "v%d" % i] for i in range(60)]
    out = sql_mcp._format_result(["id", "val"], rows)
    assert "…показано 50 из 60" in out
    assert "строк: 60" in out
    assert "v49" in out and "v50" not in out


def test_format_result_clips_long_values():
    out = sql_mcp._format_result(["txt"], [["x" * 500]])
    line = out.split("\n")[2]
    assert len(line) <= 200
    assert line.rstrip().endswith("…")


def test_format_result_ragged_rows():

    out = sql_mcp._format_result(["a", "b", "c"], [["1"], ["1", "2", "3", "4"]])
    assert "строк: 2" in out


def test_audit_log_written(monkeypatch, tmp_path):
    log = tmp_path / "sql.log"
    monkeypatch.setattr(sql_mcp, "_LOG", str(log))
    sql_mcp._tool_run_select({"sql": "DROP TABLE users"})
    text = log.read_text(encoding="utf-8")
    assert "run_select[REJECTED]" in text and "DROP TABLE users" in text


def test_protocol_smoke():
    server = os.path.join(ROOT, "agent", "sql_mcp.py")
    stdin = "\n".join([
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"protocolVersion": "2025-06-18"}}),
        json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
        json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
    ]) + "\n"
    env = dict(os.environ, WA_DB_HOST="127.0.0.1", WA_DB_WHSE="wmwhse1", WA_SQL_LOG="")
    p = subprocess.run([sys.executable, server], input=stdin, capture_output=True,
                       text=True, timeout=30, env=env)
    replies = {m["id"]: m for m in map(json.loads, p.stdout.strip().splitlines())}
    init = replies[1]["result"]
    assert init["serverInfo"]["name"] == "wa-sql"
    assert init["protocolVersion"] == "2025-06-18"
    tools = replies[2]["result"]["tools"]
    assert [t["name"] for t in tools] == ["run_select"]
    assert "sa" in tools[0]["description"]
    assert "wmwhse1" in tools[0]["description"]
    assert tools[0]["inputSchema"]["required"] == ["sql"]
