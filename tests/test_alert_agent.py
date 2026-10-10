# -*- coding: utf-8 -*-


import json
import logging
import os
import threading
import time

import pytest

from agent import alert_agent as aa
from agent import default_flow as dfl
from agent.agent_base import _TicketDefer
from agent.pipe_grafana import GrafanaMixin


class _FakeRedmine:
    def __init__(self):
        self.taken, self.notes, self.reassigned, self.time_entries = [], [], [], []

    def take_issue(self, iid, aid, status):
        self.taken.append((iid, aid, status))

    def add_note(self, iid, text, uploads=None, private=True):
        self.notes.append((iid, text, private))

    def reassign(self, iid, gid, tag_list=None, custom_fields=None):
        self.reassigned.append((iid, gid, tag_list, custom_fields))

    def create_time_entry(self, iid, hours, comments=""):
        self.time_entries.append((iid, hours, comments))


class _FakeJournal:
    def __init__(self):
        self.records = []

    def record(self, key, verdict, **kw):
        self.records.append((key, verdict, kw))

    def seen(self, key):
        return False

    def verdicts(self):
        return [v for _k, v, _kw in self.records]


class _Ag(GrafanaMixin):
    pass


def _agent(root, aa_enabled=True, dry=False, servers=None):
    a = _Ag()
    a.root = str(root)
    a.redmine = _FakeRedmine()
    a.journal = _FakeJournal()
    a.dry_run = dry
    a.log = logging.getLogger("test.alert_agent")


    a.cfg = {"assigned_to_id": 1, "work_status_id": 2,
             "roles": {"chief_engineer": 1, "engineer": 1},
             "locks": {"enabled": True, "dba_group_id": 547, "dba_tag": "DBA", "login": "sa"},
             "db": {"servers": servers or {}},
             "agent_analysis": {"enabled": aa_enabled, "model": "claude-opus-4-8",
                                "effort": "high", "cli_timeout_sec": 5, "max_concurrent": 2}}
    a.gf_cfg = {"take_without_set": True, "max_ticket_age_minutes": 0, "take_statuses": [],
                "base": "http://service.example.invalid", "influx_ds_id": 3, "influx_db": "telegraf"}
    a.gf_sets = []
    a.gf_user, a.gf_password = "kk", "pw"
    a.default_cfg = {"search_limit": 40}
    a.llm_cfg = {}
    a.table_analysis = {}
    a._svc_gf = "dead"
    a._deferred_178 = {}
    a._rm_url, a._rm_key = "http://service.example.invalid", "k"
    return a


def _ticket(subject, iid=10104):
    return {"id": iid, "subject": subject, "status": "Новая", "assigned_to_id": None,
            "assigned_to": "", "author": "grafana", "description": "тело алерта",
            "created_on": "2026-07-15T10:00:00Z", "project": "Клиент B (Площадка 2)"}


def _join_bg(a, iid, timeout=5):
    for th in a._aa_threads():
        if th.name == "alert-agent-%d" % iid:
            th.join(timeout)


def test_prompt_alert_variant_full():
    shots = [{"sid": "p78", "path": "/tmp/d/p78.png", "title": "Св. место · APP",
              "measurement": "win_disk"}]
    hints = aa.build_hints({"reason": "обрезка прошла, алерт горит - аномалия", "mode": "llm"},
                           alert_state="alerting", metric_fresh=False)
    p = aa.build_alert_prompt(
        10104, "Площадка B4 (CLB_SITE04)", "[Alerting] CLB_SITE04 C_FREESPACE", "тело",
        shots, ["win_disk (поле Free_Megabytes)"], hints_block=hints,
        playbooks=[("grafana-freespace.md", "Freespace")], graph_project="CLIENT_B")

    assert "алерт Grafana по заявке #10104" in p
    assert "influx_query" in p
    assert "Программа уже сняла скриншоты панелей" in p and "p78" in p and "/tmp/d/p78.png" in p
    assert "Системные имена этих таблиц/метрик: win_disk (поле Free_Megabytes)" in p
    assert "1) Проанализируй ИМЕННО эти метрики через influx_query" in p
    assert "Верни список id одобренных" in p and "approved_screenshots" in p
    assert "- screenshots: id одобренных." in p


    assert "!имя_файла! в тексте разбора" in p
    assert "!p78.png!" in p
    assert "программа допишет в конец" in p

    assert "Что заметила программа" in p
    assert "ГОРИТ (state=alerting)" in p
    assert "МОЛЧИТ" in p
    assert "обрезка прошла, алерт горит - аномалия" in p

    assert "ПЛЕЙБУКИ" in p and "grafana-freespace.md" in p
    assert "codebase-memory" in p and "«CLIENT_B»" in p

    assert "[Alerting] CLB_SITE04 C_FREESPACE" in p and "h3. Разбор:" in p


def test_prompt_without_screenshots_and_graph():
    p = aa.build_alert_prompt(1, "Площадка C1 (CLC_SITE01)", "тема", "тело", [], [],
                              hints_block="", playbooks=None, graph_project=None)
    assert "Программа уже сняла скриншоты" not in p
    assert "3) Реши, какие скриншоты" not in p
    assert "approved_screenshots" not in p
    assert "codebase-memory" not in p
    assert "Что заметила программа" not in p
    assert "2) Если есть коннект" in p


def test_hints_empty_and_ok_state():
    assert aa.build_hints(None) == ""
    h = aa.build_hints({"reason": "apache: служба жива - ложное, закрыть"},
                       alert_state="ok", metric_fresh=True)
    assert "ПОГАС (state=ok" in h and "метрика панели реально поступает" in h
    assert "apache: служба жива" in h


def test_build_mcp_config_extra_servers():
    cfg = dfl.build_mcp_config("http://rm", "key", 5, [1, 2],
                               sql_env={"WA_DB_HOST": "192.0.2.10", "WA_DB_TDSVER": "7.0"},
                               influx_env={"WA_GF_BASE": "http://service.example.invalid"})
    srv = cfg["mcpServers"]
    assert "wa-sql" in srv and srv["wa-sql"]["args"] == [dfl._SQL_MCP_SERVER]
    assert srv["wa-sql"]["env"]["WA_DB_TDSVER"] == "7.0"
    assert "wa-influx" in srv and srv["wa-influx"]["args"] == [dfl._INFLUX_MCP_SERVER]

    cfg2 = dfl.build_mcp_config("http://rm", "key", 5, [1, 2])
    assert set(cfg2["mcpServers"]) == {"redmine"}


def test_analyze_alert_plumbing(monkeypatch):
    seen = {}

    def fake_run_cli(cmd, timeout):
        seen["cmd"] = cmd
        i = cmd.index("--mcp-config")
        mcp = json.load(open(cmd[i + 1]))
        seen["mcp"] = mcp

        draft_file = mcp["mcpServers"]["redmine"]["env"]["RM_DRAFT_FILE"]
        with open(draft_file, "w", encoding="utf-8") as f:
            json.dump({"note": "разбор + sql", "confidence": "high",
                       "approved_screenshots": ["p78"], "issue_id": 10104}, f)
        return True, "sess-42", "итог", None

    monkeypatch.setattr(dfl, "_run_cli", fake_run_cli)
    res = aa.analyze_alert("промпт", 10104, "http://rm", "key", [621],
                           sql_env={"WA_DB_HOST": "192.0.2.10", "WA_DB_LOGIN": "sa"},
                           influx_env={"WA_GF_BASE": "http://service.example.invalid", "WA_GF_PASSWORD": "pw"},
                           graph=True, timeout=5)
    assert res["ok"] and res["session_id"] == "sess-42"
    assert res["draft"] == {"note": "разбор + sql", "confidence": "high",
                            "approved_screenshots": ["p78"], "issue_id": 10104}

    cmd = seen["cmd"]
    allowed = cmd[cmd.index("--allowedTools") + 1]
    assert "mcp__wa-sql__run_select" in allowed and "mcp__wa-influx__influx_query" in allowed
    assert allowed.endswith(",Read") and cmd[cmd.index("--tools") + 1] == "Read"

    sysp = cmd[cmd.index("--append-system-prompt") + 1]
    assert "wa-sql" in sysp and "СТИЛЬ ТЕКСТА" in sysp

    srv = seen["mcp"]["mcpServers"]
    assert set(srv) == {"redmine", "codebase-memory-mcp", "wa-sql", "wa-influx"}
    assert srv["redmine"]["env"]["RM_DRY"] == "1"
    assert srv["wa-sql"]["env"]["WA_SQL_LOG"] == srv["wa-influx"]["env"]["WA_INFLUX_LOG"]


LOCKS_DESC = "h5. t_AdmLockBlock.max\n\nh5. 89506.000\n"


def _install_dispatch_recorder(a):
    calls = []

    def rec(t, key, site, setdef, verdict, alert_state=None, metric_fresh=None, relaunches=0):
        calls.append({"id": t["id"], "key": key, "verdict": verdict,
                      "alert_state": alert_state, "metric_fresh": metric_fresh,
                      "relaunches": relaunches})
        raise _TicketDefer(t["id"], "запущен (тест)", quiet=True)

    a._alert_agent_dispatch = rec
    return calls


def test_routing_non_locks_goes_to_agent(tmp_path):
    a = _agent(tmp_path)
    calls = _install_dispatch_recorder(a)
    t = _ticket("[Alerting] CLB_SITE04 Apache alert")
    with pytest.raises(_TicketDefer):
        a._process_ticket(t, "ticket-10104", {})
    assert [c["id"] for c in calls] == [10104]
    assert calls[0]["verdict"]["type"] == "apache"
    assert a.redmine.taken == [(10104, 1, 2)]
    assert a.redmine.notes == []
    assert "alert_agent_error" not in a.journal.verdicts()


def test_take_toggle_off_skips_alert(tmp_path):


    a = _agent(tmp_path)
    a.cfg["roles"] = {"chief_engineer": 1, "engineer": 2, "auto_take_engineer": False}
    calls = _install_dispatch_recorder(a)
    t = _ticket("[Alerting] CLB_SITE04 C_FREESPACE", iid=10107)
    a._process_ticket(t, "ticket-10107", {})
    assert calls == [] and a.redmine.taken == [] and a.redmine.notes == []
    assert a.journal.verdicts() == ["take_disabled"]


def test_take_toggle_client_a_independent(tmp_path):

    a = _agent(tmp_path)
    a.cfg["roles"] = {"chief_engineer": 1, "engineer": 2, "auto_take_chief": False}
    _install_dispatch_recorder(a)
    t = _ticket("[Alerting] CLB_SITE04 C_FREESPACE", iid=10108)
    with pytest.raises(_TicketDefer):
        a._process_ticket(t, "ticket-10108", {})
    assert a.redmine.taken == [(10108, 2, 2)]
    assert "take_disabled" not in a.journal.verdicts()


def test_routing_locks_always_query_no_autorun(tmp_path, monkeypatch):


    import agent.sql_report as sr
    monkeypatch.setattr(sr, "run_diag",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("run_diag не должен зваться")))
    a = _agent(tmp_path, servers={"CLB_SITE04": {"host": "192.0.2.10", "port": 1433}})
    calls = _install_dispatch_recorder(a)
    t = _ticket("[Alerting] CLB_SITE04 LOCKS", iid=10103)
    t["description"] = LOCKS_DESC
    a._process_ticket(t, "ticket-10103", {})
    assert calls == []
    assert len(a.redmine.notes) == 1
    note = a.redmine.notes[0][1]
    assert "t_AdmLockBlock" in note and "Выполнить запрос вручную." in note
    assert a.redmine.reassigned == []
    assert a.redmine.time_entries == []
    assert "locks_dba" not in a.journal.verdicts()
    assert "note_posted" in a.journal.verdicts() and "ticket_taken" in a.journal.verdicts()


def test_routing_locks_no_db_only_query_no_handoff(tmp_path, monkeypatch):


    import agent.sql_report as sr
    monkeypatch.setattr(sr, "run_diag",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("run_diag не должен зваться")))
    a = _agent(tmp_path)
    calls = _install_dispatch_recorder(a)
    t = _ticket("[Alerting] CLB_SITE04 LOCKS", iid=10103)
    t["description"] = LOCKS_DESC
    a._process_ticket(t, "ticket-10103", {})
    assert calls == []
    assert len(a.redmine.notes) == 1
    assert ("t_AdmLockBlock" in a.redmine.notes[0][1]
            and "Выполнить запрос вручную" in a.redmine.notes[0][1])
    assert a.redmine.reassigned == []
    assert a.redmine.time_entries == []
    assert "locks_dba" not in a.journal.verdicts()


def test_routing_dry_run_launches_nothing(tmp_path):
    a = _agent(tmp_path, dry=True)
    calls = _install_dispatch_recorder(a)
    a._process_ticket(_ticket("[Alerting] CLB_SITE04 Apache alert"), "ticket-10104", {})
    assert calls == [] and a.redmine.taken == [] and a.redmine.notes == []
    assert "grafana_dry_run" in a.journal.verdicts()
    assert aa.load_draft(a.root, 10104) is None


def test_routing_agent_disabled_falls_back_to_old_path(tmp_path):
    a = _agent(tmp_path, aa_enabled=False)
    calls = _install_dispatch_recorder(a)
    a._process_ticket(_ticket("[Alerting] CLB_SITE04 Apache alert"), "ticket-10104", {})
    assert calls == []
    assert len(a.redmine.notes) == 1
    assert "h3. Разбор" in a.redmine.notes[0][1]


def test_resume_states(tmp_path):
    a = _agent(tmp_path)
    t = _ticket("[Alerting] CLB_SITE04 Apache alert")


    assert a._alert_agent_resume(t, "ticket-10104") == 0


    aa.save_draft(a.root, 10104, {"issue_id": 10104, "status": "running"})
    th = threading.Thread(target=time.sleep, args=(1,), name="alert-agent-10104", daemon=True)
    th.start()
    a._aa_threads().append(th)
    with pytest.raises(_TicketDefer):
        a._alert_agent_resume(t, "ticket-10104")
    th.join()


    a._alert_agent_threads = []
    assert a._alert_agent_resume(t, "ticket-10104") == 1


    aa.save_draft(a.root, 10104, {"issue_id": 10104, "status": "running", "relaunches": 1})
    assert a._alert_agent_resume(t, "ticket-10104") is None
    assert "alert_agent_error" in a.journal.verdicts()
    assert aa.load_draft(a.root, 10104) is None


    aa.save_draft(a.root, 10104, {"issue_id": 10104, "status": "pending"})
    with pytest.raises(_TicketDefer):
        a._alert_agent_resume(t, "ticket-10104")


    aa.save_draft(a.root, 10104, {"issue_id": 10104, "status": "posted"})
    assert a._alert_agent_resume(t, "ticket-10104") is None
    assert "draft_closed" in a.journal.verdicts()


def test_resume_cap_defers_fresh_launch(tmp_path):
    a = _agent(tmp_path)
    for i in (1, 2):
        th = threading.Thread(target=time.sleep, args=(1,), name="alert-agent-%d" % i,
                              daemon=True)
        th.start()
        a._aa_threads().append(th)
    with pytest.raises(_TicketDefer):
        a._alert_agent_resume(_ticket("[Alerting] CLB_SITE04 Apache alert"), "ticket-10104")


def test_resume_noop_in_dry_or_disabled(tmp_path):
    a = _agent(tmp_path, dry=True)
    aa.save_draft(a.root, 10104, {"issue_id": 10104, "status": "pending"})
    assert a._alert_agent_resume(_ticket("x"), "ticket-10104") == 0
    a2 = _agent(tmp_path, aa_enabled=False)
    assert a2._alert_agent_resume(_ticket("x"), "ticket-10104") == 0


def _dispatch_with_fake_cli(tmp_path, monkeypatch, fake_analyze, servers=None):
    a = _agent(tmp_path, servers=servers)
    iid = 10104
    ddir = aa.draft_dir(a.root, iid)
    os.makedirs(ddir, exist_ok=True)
    shots = [{"sid": "p78", "path": os.path.join(ddir, "p78.png"),
              "title": "Св. место · APP", "measurement": "win_disk"},
             {"sid": "p79", "path": os.path.join(ddir, "p79.png"),
              "title": "Св. место · DB", "measurement": "win_disk"}]
    a._alert_render_for_draft = lambda t, site, setdef: (shots, ["win_disk"])
    monkeypatch.setattr(aa, "analyze_alert", fake_analyze)
    t = _ticket("[Alerting] CLB_SITE04 C_FREESPACE")
    with pytest.raises(_TicketDefer):
        a._process_ticket(t, "ticket-%d" % iid, {})
    _join_bg(a, iid)
    return a, iid


def test_dispatch_writes_contract_draft(tmp_path, monkeypatch):
    captured = {}

    def fake_analyze(prompt, iid, url, key, contours, **kw):
        captured.update(prompt=prompt, iid=iid, url=url, contours=contours, kw=kw)
        return {"ok": True, "session_id": "sess-1", "result": "итог", "error": None,
                "tool_log": "", "draft": {"note": "Разбор простым языком.\n\nSQL: ...",
                                          "confidence": "high",
                                          "approved_screenshots": ["p78"], "issue_id": iid}}

    a, iid = _dispatch_with_fake_cli(
        tmp_path, monkeypatch, fake_analyze,
        servers={"CLB_SITE04": {"host": "192.0.2.10", "port": 1433, "tdsver": "7.0"}})


    d = aa.load_draft(a.root, iid)
    assert d["issue_id"] == iid and d["kind"] == "alert" and d["status"] == "pending"
    assert d["subject"] == "[Alerting] CLB_SITE04 C_FREESPACE"
    assert d["analysis"] == "Разбор простым языком.\n\nSQL: ..."
    assert d["comment"] == "h3. Разбор:\n\n" + d["analysis"]
    assert d["sql"] == "" and d["created_at"] and d["session_id"] == "sess-1"
    assert "analysis_seconds" in d and d["analysis_seconds"] >= 0
    flags = {s["sid"]: s["approved"] for s in d["screenshots"]}
    assert flags == {"p78": True, "p79": False}
    assert d["screenshots"][0]["file"] == os.path.join("state", "drafts", str(iid), "p78.png")
    assert d["screenshots"][0]["title"] == "Св. место · APP"


    recs = {v: kw for _k, v, kw in a.journal.records}
    assert recs["alert_agent_started"].get("interim") is True
    assert recs["draft_ready"].get("interim") is True
    assert recs["draft_ready"].get("detail") == d["analysis"]


    kw = captured["kw"]
    assert kw["sql_env"]["WA_DB_HOST"] == "192.0.2.10"
    assert kw["sql_env"]["WA_DB_LOGIN"] == "sa"
    assert kw["sql_env"]["WA_DB_TDSVER"] == "7.0"
    assert kw["sql_env"]["WA_DB_WHSE"] == "wmwhse1"
    assert kw["influx_env"]["WA_GF_BASE"] == "http://service.example.invalid"
    assert kw["influx_env"]["WA_GF_PASSWORD"] == "pw"
    assert kw["influx_env"]["WA_GF_DS_ID"] == "3"
    assert kw["graph"] is True


    p = captured["prompt"]
    assert "заявке #10104" in p and "p78" in p and "win_disk" in p
    assert "Что заметила программа" in p
    assert "influx_query" in p and "approved_screenshots" in p


def test_dispatch_cli_failure_retries_then_terminal(tmp_path, monkeypatch):
    calls = []

    def fake_analyze(prompt, iid, url, key, contours, **kw):
        calls.append(1)
        return {"ok": False, "session_id": None, "result": "", "error": "CLI таймаут",
                "tool_log": "", "draft": None}

    a, iid = _dispatch_with_fake_cli(tmp_path, monkeypatch, fake_analyze)
    assert len(calls) == 2
    assert aa.load_draft(a.root, iid) is None
    recs = {v: kw for _k, v, kw in a.journal.records}
    assert "alert_agent_error" in recs and not recs["alert_agent_error"].get("interim")


def test_finalize_draft_defaults_all_approved(tmp_path):
    aa.save_draft(str(tmp_path), 7, {"issue_id": 7, "status": "running",
                                     "screenshots": [{"sid": "p1", "approved": False},
                                                     {"sid": "p2", "approved": False}]})
    d = aa.finalize_draft(str(tmp_path), 7, "текст", session_id="s")
    assert all(s["approved"] for s in d["screenshots"])
    assert "analysis_seconds" not in d
    d2 = aa.finalize_draft(str(tmp_path), 7, "текст", approved=[])
    assert not any(s["approved"] for s in d2["screenshots"])


def test_finalize_draft_accumulates_seconds(tmp_path):

    aa.save_draft(str(tmp_path), 8, {"issue_id": 8, "status": "running", "screenshots": []})
    d1 = aa.finalize_draft(str(tmp_path), 8, "текст", analysis_seconds=1000.0)
    assert d1["analysis_seconds"] == 1000.0
    d2 = aa.finalize_draft(str(tmp_path), 8, "текст2", analysis_seconds=500.5)
    assert d2["analysis_seconds"] == 1500.5

    d3 = aa.finalize_draft(str(tmp_path), 8, "текст3")
    assert d3["analysis_seconds"] == 1500.5
