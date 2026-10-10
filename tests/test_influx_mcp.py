# -*- coding: utf-8 -*-


import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from agent import influx_mcp


def test_guard_allows_show():
    ok, why = influx_mcp.influx_guard("SHOW MEASUREMENTS")
    assert ok, why
    ok, _ = influx_mcp.influx_guard('SHOW TAG VALUES FROM "tableCounts" WITH KEY = "host"')
    assert ok


def test_guard_allows_select_any_case():
    ok, _ = influx_mcp.influx_guard(
        'select mean("count") from "tableCounts" where time > now()-24h')
    assert ok
    ok, _ = influx_mcp.influx_guard(
        '  SELECT mean("count") FROM "tableCounts" GROUP BY time(10m) fill(none) LIMIT 150')
    assert ok


def test_guard_rejects_drop():
    ok, why = influx_mcp.influx_guard("DROP MEASUREMENT tableCounts")
    assert not ok and "DROP" in why


def test_guard_rejects_delete_create_and_co():
    for q in ("DELETE FROM x WHERE time < now()", "CREATE DATABASE hack",
              "GRANT ALL ON x TO u", "REVOKE ALL ON x FROM u",
              "KILL QUERY 42", "ALTER RETENTION POLICY p ON db"):
        ok, why = influx_mcp.influx_guard(q)
        assert not ok, q


def test_guard_rejects_non_select_head():
    ok, why = influx_mcp.influx_guard("EXPLAIN SELECT * FROM x")
    assert not ok and "EXPLAIN" in why


def test_guard_rejects_select_into():

    ok, why = influx_mcp.influx_guard('SELECT * INTO "backup" FROM "cpu"')
    assert not ok and "INTO" in why


def test_guard_rejects_deny_word_in_tail():

    ok, _ = influx_mcp.influx_guard("SELECT 1; DROP MEASUREMENT x")
    assert not ok


def test_guard_words_not_substrings():

    ok, why = influx_mcp.influx_guard(
        'SELECT mean("dropped_packets") FROM "net" WHERE "iface"=\'delete0\'')
    assert ok, why
    ok, why = influx_mcp.influx_guard("SELECT dropped_packets FROM net")
    assert ok, why


def test_guard_rejects_empty():
    ok, _ = influx_mcp.influx_guard("")
    assert not ok
    ok, _ = influx_mcp.influx_guard("   ")
    assert not ok


def _payload(values, columns=("time", "mean"), name="tableCounts", tags=None):
    s = {"name": name, "columns": list(columns), "values": values}
    if tags:
        s["tags"] = tags
    return {"results": [{"series": [s]}]}


def test_format_series_basic():
    ok, text = influx_mcp.format_results(_payload(
        [["2026-07-14T10:00:00Z", 10], ["2026-07-14T11:00:00Z", 20]],
        tags={"host": "wms01"}))
    assert ok
    assert "серия: tableCounts {host=wms01}" in text
    assert "time | mean" in text

    assert text.index("11:00") < text.index("10:00")


def test_format_series_skips_nulls():
    ok, text = influx_mcp.format_results(_payload(
        [["t1", None], ["t2", 5], ["t3", None]]))
    assert ok
    assert "t2" in text
    assert "t1" not in text and "t3" not in text


def test_format_series_caps_200_points():
    ok, text = influx_mcp.format_results(_payload([[i, i * 1.5] for i in range(300)]))
    assert ok
    assert "…300 точек всего, показано 200" in text
    lines = text.split("\n")
    assert lines[2].startswith("299")

    assert len(lines) == 2 + 200 + 1


def test_format_multiple_series():
    payload = {"results": [{"series": [
        {"name": "cpu", "columns": ["time", "usage"], "values": [[1, 50]]},
        {"name": "mem", "columns": ["time", "used"], "values": [[1, 80]]},
    ]}]}
    ok, text = influx_mcp.format_results(payload)
    assert ok
    assert "серия: cpu" in text and "серия: mem" in text


def test_format_error_passthrough():
    ok, text = influx_mcp.format_results(
        {"results": [{"error": "database not found: telegraf2"}]})
    assert not ok
    assert "database not found: telegraf2" in text


def test_format_empty():
    ok, text = influx_mcp.format_results({"results": [{}]})
    assert ok and text == "(нет данных)"
    ok, text = influx_mcp.format_results({"results": []})
    assert ok and text == "(нет данных)"
    ok, text = influx_mcp.format_results(None)
    assert ok and text == "(нет данных)"


class FakeGrafana:
    def __init__(self, payload=None, fail=None):
        self.payload = payload or {"results": [{}]}
        self.fail = fail
        self.queries = []

    def influx(self, q, ds_id, db):
        if self.fail:
            raise self.fail
        self.queries.append((q, ds_id, db))
        return self.payload


def test_tool_rejected_by_guard(monkeypatch):
    out = influx_mcp._tool_influx_query({"q": "DROP MEASUREMENT x"})
    assert "отклонён гардом" in out


def test_tool_ok_path(monkeypatch):
    gc = FakeGrafana(payload=_payload([["t1", 1]]))
    monkeypatch.setattr(influx_mcp, "_BASE", "http://service.example.invalid")
    monkeypatch.setattr(influx_mcp, "_PASSWORD", "pw")
    monkeypatch.setattr(influx_mcp, "_DS_ID", 3)
    monkeypatch.setattr(influx_mcp, "_DB", "telegraf")
    monkeypatch.setattr(influx_mcp, "_client", lambda: gc)
    out = influx_mcp._tool_influx_query({"q": 'SELECT mean("count") FROM "tableCounts"'})
    assert "серия: tableCounts" in out
    assert gc.queries == [('SELECT mean("count") FROM "tableCounts"', 3, "telegraf")]


def test_tool_login_failure(monkeypatch):
    def boom():
        raise RuntimeError("Grafana не отдала сессию (VPN включён? пароль клиент B?)")
    monkeypatch.setattr(influx_mcp, "_BASE", "http://service.example.invalid")
    monkeypatch.setattr(influx_mcp, "_PASSWORD", "pw")
    monkeypatch.setattr(influx_mcp, "_client", boom)
    out = influx_mcp._tool_influx_query({"q": "SHOW MEASUREMENTS"})
    assert "Grafana недоступна" in out and "VPN" in out


def test_tool_missing_config(monkeypatch):
    monkeypatch.setattr(influx_mcp, "_BASE", "")
    monkeypatch.setattr(influx_mcp, "_PASSWORD", "")
    out = influx_mcp._tool_influx_query({"q": "SHOW MEASUREMENTS"})
    assert "WA_GF_BASE" in out


def test_client_not_cached_on_failure(monkeypatch):

    attempts = []

    class FailingClient:
        def __init__(self, base, user, password):
            pass

        def login(self):
            attempts.append(1)
            raise RuntimeError("нет сети")
    monkeypatch.setattr(influx_mcp, "_gc", None)
    monkeypatch.setattr(influx_mcp, "GrafanaClient", FailingClient)
    for _ in range(2):
        try:
            influx_mcp._client()
        except RuntimeError:
            pass
    assert len(attempts) == 2
    assert influx_mcp._gc is None


def test_audit_log_written(monkeypatch, tmp_path):
    log = tmp_path / "influx.log"
    monkeypatch.setattr(influx_mcp, "_LOG", str(log))
    influx_mcp._tool_influx_query({"q": "DROP MEASUREMENT x"})
    text = log.read_text(encoding="utf-8")
    assert "influx_query[REJECTED]" in text and "DROP MEASUREMENT x" in text


def test_protocol_smoke():
    server = os.path.join(ROOT, "agent", "influx_mcp.py")
    stdin = "\n".join([
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"protocolVersion": "2025-06-18"}}),
        json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
        json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
    ]) + "\n"
    env = dict(os.environ, WA_GF_BASE="http://127.0.0.1", WA_GF_USER="u",
               WA_GF_PASSWORD="p", WA_INFLUX_LOG="")
    p = subprocess.run([sys.executable, server], input=stdin, capture_output=True,
                       text=True, timeout=30, env=env)
    replies = {m["id"]: m for m in map(json.loads, p.stdout.strip().splitlines())}
    init = replies[1]["result"]
    assert init["serverInfo"]["name"] == "wa-influx"
    assert init["protocolVersion"] == "2025-06-18"
    tools = replies[2]["result"]["tools"]
    assert [t["name"] for t in tools] == ["influx_query"]
    assert tools[0]["inputSchema"]["required"] == ["q"]


def test_guard_rejects_unbalanced_quote_bypass():


    for q in ("SELECT * FROM /it's/ INTO \"evil\"",
              "SELECT * FROM \"a WHERE x='1 INTO \"evil\""):
        ok, why = influx_mcp.influx_guard(q)
        assert not ok, "обход гарда: %r прошёл" % q
        assert ("кавычк" in why) or ("INTO" in why), why


def test_guard_rejects_regex_literal_and_semicolon_bypass():


    for q in ("SELECT * FROM /'/ ; DROP DATABASE telegraf ; SELECT * FROM /'/",
              "SELECT * FROM /'/ ; SELECT * INTO \"evil\" FROM \"cpu\" ; SELECT * FROM /'/",
              "SELECT * FROM m WHERE host=~/'/ ; DROP DATABASE telegraf ; SELECT 1 FROM /'/",
              "SELECT * FROM \"cpu\" ; SET PASSWORD FOR admin = 'hacked'"):
        ok, why = influx_mcp.influx_guard(q)
        assert not ok, "обход гарда: %r прошёл" % q

    ok, why = influx_mcp.influx_guard("SELECT * FROM \"cpu\" SET PASSWORD FOR admin = 'x'")
    assert not ok and ("SET" in why or "PASSWORD" in why), why


def test_guard_allows_division_not_regex():


    for q in ("SELECT mean(\"mem\")/1024/1024 AS mb FROM sys WHERE time > now()-1h",
              "SELECT a/b FROM t",
              "SELECT non_negative_derivative(mean(\"x\"), 1s)/60 FROM m GROUP BY time(5m)",
              "SELECT last(\"Uptime\") FROM java_runtime WHERE host=~/EXAMPLE-APP-02-1|EXAMPLE-APP-02-2/",
              "SELECT last(\"value\") FROM m WHERE host!~/^test/"):
        ok, why = influx_mcp.influx_guard(q)
        assert ok, "легальный запрос зарезан: %r -> %s" % (q, why)


def test_guard_still_allows_escaped_quotes():

    ok, _ = influx_mcp.influx_guard("SELECT * FROM \"t\" WHERE a='it\\'s'")
    assert ok
