# -*- coding: utf-8 -*-


import json
import logging
import os
import re
import threading
import time

import pytest

from agent import alert_agent as aa
from agent import approvals
from agent import default_flow as dfl
from agent import router
from agent.agent_base import _TicketDefer
from agent.alert_agent import AlertAgentMixin
from agent.pipe_default import DefaultMixin


class _FakeRedmine:
    def __init__(self):
        self.taken, self.notes = [], []

    def take_issue(self, iid, aid, status):
        self.taken.append((iid, aid, status))

    def add_note(self, iid, text, uploads=None, private=True):
        self.notes.append((iid, text, private))


class _FakeJournal:
    def __init__(self):
        self.records = []

    def record(self, key, verdict, **kw):
        self.records.append((key, verdict, kw))

    def seen(self, key):
        return False

    def verdicts(self):
        return [v for _k, v, _kw in self.records]


class _Ag(DefaultMixin, AlertAgentMixin):
    pass


def _agent(root, dry=False, servers=None, docs=None):
    a = _Ag()
    a.root = str(root)
    a.redmine = _FakeRedmine()
    a.journal = _FakeJournal()
    a.dry_run = dry
    a.log = logging.getLogger("test.default_agent")

    a.cfg = {"assigned_to_id": 1, "work_status_id": 2,
             "roles": {"chief_engineer": 1, "engineer": 1},
             "locks": {"login": "sa"},
             "db": {"servers": servers if servers is not None else {
                 "CLC_SITE05": {"host": "192.0.2.10", "port": 1433, "tdsver": "7.0"}}},
             "agent_analysis": {"enabled": True, "model": "claude-opus-4-8",
                                "effort": "high", "cli_timeout_sec": 7, "max_concurrent": 2}}

    a.default_cfg = {"enabled": True, "search_limit": 40, "contour_overrides": {},
                     "docs_dirs": docs if docs is not None else
                     {"Клиент C": "./example-workspace"},
                     "model": "sonnet", "effort": "low", "cli_timeout_sec": 600}
    a.llm_cfg = {}
    a._deferred_178 = {}
    a._rm_url, a._rm_key = "http://service.example.invalid", "k"
    a._default_threads = []
    a._all_projects_cache = [{"id": 900, "name": "Клиент C. Площадка C5"},
                             {"id": 901, "name": "Клиент C. Площадка C1"},
                             {"id": 902, "name": "Клиент G"}]
    return a


def _issue(iid=10105, subject="Не печатается этикетка на приёмке",
           project="Клиент C. Площадка C5", status_id=1):
    return {"id": iid, "subject": subject, "description": "тело заявки клиента",
            "project": {"id": 900, "name": project},
            "status": {"id": status_id, "name": "Новая"},
            "tracker": {"id": 1}, "assigned_to": None,
            "created_on": "2026-07-15T10:00:00Z"}


def _join_bg(a, iid, timeout=5):
    for th in a._aa_threads():
        if th.name == "default-agent-%d" % iid:
            th.join(timeout)


def test_site_from_project():
    s = aa.site_from_project("Клиент C. Площадка C5")
    assert s and s["code"] == "CLC_SITE05" and s["network"] == "clc"
    assert (aa.site_from_project("Клиент B (Площадка B2)") or {}).get("code") == "CLB_SITE02"

    assert (aa.site_from_project("КЛИЕНТ D Площадка D3") or {}).get("code") in \
        ("CLD_SITE02", "CLD_SITE03")
    assert (aa.site_from_project("КЛИЕНТ D Площадка D4") or {}).get("code") == "CLD_SITE04"

    assert aa.site_from_project("Клиент G") is None
    assert aa.site_from_project("") is None

    assert aa.site_from_project("Клиент A Т/П") is None


def test_prompt_default_no_grafana_inserts():
    site = {"code": "CLC_SITE05", "network": "clc", "uid": "x", "warehouse": "Площадка C5"}
    p = aa.build_default_prompt(10105, "Клиент C. Площадка C5", "тема заявки", "тело заявки",
                                sql=True, site=site,
                                playbooks=[("grafana-freespace.md", "Freespace")],
                                graph_project="CLC")

    assert "influx_query" not in p
    assert "скриншот" not in p.lower()
    assert "approved_screenshots" not in p
    assert "- screenshots" not in p

    assert "заявку клиента #10105" in p and "«Клиент C. Площадка C5»" in p
    assert "площадка Площадка C5 (CLC_SITE05)" in p
    assert "run_select" in p and "search_similar" in p and "get_issue" in p
    assert "h3. Разбор:" in p

    assert "0) СНАЧАЛА ПЛЕЙБУКИ" in p
    assert "\n1) Найди 4-5" in p
    assert "\n2) Сделай SELECT'ы (run_select)" in p
    assert "\n3) Можешь смотреть код клиента через codebase-memory" in p and "«CLC»" in p
    assert "\n4)" not in p

    assert "тема заявки" in p and "тело заявки" in p


def test_prompt_default_without_sql_and_graph():
    p = aa.build_default_prompt(5, "Клиент G", "тема", "тело",
                                sql=False, site=None, playbooks=None, graph_project=None)
    assert "run_select" not in p
    assert "Коннекта к БД площадки нет" in p and "текстом" in p
    assert "площадка" not in p

    assert "0)" not in p
    assert "\n1) Найди 4-5" in p
    assert "\n2) Полезные диагностические SELECT'ы предложи ТЕКСТОМ" in p
    assert "\n3)" not in p


def test_default_system_prompt_variants():
    sp = aa.default_system_prompt(True)
    assert "wa-sql" in sp and "post_private_note" in sp and "ЧЕРНОВИК" in sp
    sp2 = aa.default_system_prompt(False)
    assert "wa-sql" not in sp2 and "SQL предлагай текстом" in sp2


def test_analyze_default_plumbing(monkeypatch):
    seen = {}

    def fake_run_cli(cmd, timeout, cwd=None):
        seen["cmd"] = cmd
        i = cmd.index("--mcp-config")
        seen["mcp"] = json.load(open(cmd[i + 1]))
        draft_file = seen["mcp"]["mcpServers"]["redmine"]["env"]["RM_DRAFT_FILE"]
        with open(draft_file, "w", encoding="utf-8") as f:
            json.dump({"note": "разбор", "confidence": "medium", "issue_id": 5}, f)
        return True, "sess-7", "итог", None

    monkeypatch.setattr(dfl, "_run_cli", fake_run_cli)
    res = aa.analyze_alert("промпт", 5, "http://rm", "key", [900, 901],
                           sql_env=None, influx_env=None, graph=True, timeout=5,
                           mcp_tools=dfl.MCP_TOOLS,
                           system_prompt=aa.default_system_prompt(False),
                           builtin_tools="", tag="default-agent")
    assert res["ok"] and res["draft"]["note"] == "разбор"

    assert set(seen["mcp"]["mcpServers"]) == {"redmine", "codebase-memory-mcp"}
    assert seen["mcp"]["mcpServers"]["redmine"]["env"]["RM_DRY"] == "1"
    cmd = seen["cmd"]
    allowed = cmd[cmd.index("--allowedTools") + 1]
    assert "wa-sql" not in allowed and "wa-influx" not in allowed
    assert "mcp__redmine__post_private_note" in allowed
    assert cmd[cmd.index("--tools") + 1] == ""
    sysp = cmd[cmd.index("--append-system-prompt") + 1]
    assert "SQL предлагай текстом" in sysp and "СТИЛЬ ТЕКСТА" in sysp


def test_safe_att_name_sanitizes():

    assert dfl._safe_att_name("../../etc/passwd", 0) == "passwd"
    safe = dfl._safe_att_name("/abs/скрин ошибки.png", 1)
    assert safe and "/" not in safe and dfl._SAFE_NAME.sub("", safe) == safe
    assert dfl._safe_att_name("", 3) == "attach_3"


    for src, ext in (("Ошибка.png", ".png"), ("скрин ошибки.jpg", ".jpg"),
                     ("Отчёт по приёмке.pdf", ".pdf"), ("ЧЗ_расхождение.PNG", ".PNG")):
        got = dfl._safe_att_name(src, 0)
        assert got.endswith(ext), "%r -> %r: потеряно расширение" % (src, got)
        assert len(got) > len(ext), "%r -> %r: остался один суффикс" % (src, got)
    assert dfl._safe_att_name("error.png", 0) == "error.png"
    assert dfl._safe_att_name("a" * 200, 0) == "a" * 80


def test_looks_viewable():

    assert dfl._looks_viewable({"content_type": "image/png", "filename": "e.png"})
    assert dfl._looks_viewable({"content_type": "application/pdf", "filename": "d"})
    assert dfl._looks_viewable({"content_type": "application/octet-stream", "filename": "E.PNG"})
    assert not dfl._looks_viewable({"content_type": "text/plain", "filename": "log.txt"})
    assert not dfl._looks_viewable({"content_type": "application/vnd.ms-excel", "filename": "a.xlsx"})


def test_download_client_files_filters_dedups_isolates(tmp_path, monkeypatch):


    downloaded = []

    class FakeRC:
        def __init__(self, url, key):
            pass

        def get_issue(self, iid, include=None):
            return {"attachments": [
                {"id": 1, "filename": "a.png", "content_type": "image/png",
                 "filesize": 10, "content_url": "u1"},
                {"id": 2, "filename": "log.txt", "content_type": "text/plain",
                 "filesize": 5, "content_url": "u2"},
                {"id": 3, "filename": "big.png", "content_type": "image/png",
                 "filesize": 99999999, "content_url": "u3"},
                {"id": 4, "filename": "err.pdf", "content_type": "application/pdf",
                 "filesize": 20, "content_url": "u4"},
                {"id": 5, "filename": "a.png", "content_type": "image/png",
                 "filesize": 12, "content_url": "u5"},
                {"id": 6, "filename": "broken.png", "content_type": "image/png",
                 "filesize": 8, "content_url": "u6"},
            ]}

        def download_attachment(self, att, max_bytes=None):
            downloaded.append(att["id"])
            return None if att["id"] == 6 else ("BYTES-%d" % att["id"]).encode()

    monkeypatch.setattr(dfl, "RedmineClient", FakeRC)
    out = dfl.download_client_files("http://rm", "key", 7, str(tmp_path), max_files=6, max_mb=1)
    names = [n for n, _p in out]
    assert 2 not in downloaded and 3 not in downloaded
    assert names == ["a.png", "err.pdf", "a_2.png"]
    for _n, p in out:
        assert os.path.exists(p)
    assert open(out[0][1], "rb").read() == b"BYTES-1"


def test_download_client_files_respects_max_files(tmp_path, monkeypatch):

    class FakeRC:
        def __init__(self, url, key):
            pass

        def get_issue(self, iid, include=None):
            return {"attachments": [
                {"id": i, "filename": "s%d.png" % i, "content_type": "image/png",
                 "filesize": 5, "content_url": "u%d" % i} for i in range(10)]}

        def download_attachment(self, att, max_bytes=None):
            return b"X"

    monkeypatch.setattr(dfl, "RedmineClient", FakeRC)
    out = dfl.download_client_files("http://rm", "key", 7, str(tmp_path), max_files=3, max_mb=1)
    assert len(out) == 3


def test_download_client_files_get_issue_failure_is_silent(tmp_path, monkeypatch):

    class FakeRC:
        def __init__(self, url, key):
            pass

        def get_issue(self, iid, include=None):
            raise OSError("сеть отвалилась")

    monkeypatch.setattr(dfl, "RedmineClient", FakeRC)
    assert dfl.download_client_files("http://rm", "key", 7, str(tmp_path)) == []


def test_download_attachment_caps_and_isolates(monkeypatch):

    from agent import redmine_client as rcmod
    rc = rcmod.RedmineClient("http://rm", "key")
    assert rc.download_attachment({"filename": "x"}) is None
    assert rc.download_attachment({"content_url": "://bad"}) is None

    class FakeResp:
        def __init__(self, data):
            self._d = data

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self, n=None):
            return self._d[:n] if n else self._d

    monkeypatch.setattr(rcmod.urllib.request, "urlopen",
                        lambda req, timeout=None: FakeResp(b"HELLO"))
    assert rc.download_attachment({"content_url": "http://rm/att/1/a", "filename": "a"}, max_bytes=100) == b"HELLO"

    monkeypatch.setattr(rcmod.urllib.request, "urlopen",
                        lambda req, timeout=None: FakeResp(b"X" * 200))
    assert rc.download_attachment({"content_url": "http://rm/att/1/a", "filename": "a"}, max_bytes=50) is None

    def boom(req, timeout=None):
        raise OSError("net")
    monkeypatch.setattr(rcmod.urllib.request, "urlopen", boom)
    assert rc.download_attachment({"content_url": "http://rm/att/1/a", "filename": "a"}) is None


def _capture_run_cli(seen):
    def fake_run_cli(cmd, timeout, cwd=None):
        seen["cmd"] = cmd
        return True, "s1", "итог", None
    return fake_run_cli


def test_analyze_injects_attachments(monkeypatch):


    monkeypatch.setattr(dfl, "playbook_index", lambda: [])
    fake_files = [("err.png", "/tmp/wa_att_x/err.png"), ("doc.pdf", "/tmp/wa_att_x/doc.pdf")]
    got = {}

    def fake_dl(url, api_key, source_id, dest_dir, max_files=6, max_mb=15, log=None):
        got.update(dest=dest_dir, max_files=max_files, max_mb=max_mb)
        return fake_files

    monkeypatch.setattr(dfl, "download_client_files", fake_dl)
    seen = {}
    monkeypatch.setattr(dfl, "_run_cli", _capture_run_cli(seen))
    dfl.analyze("тема", "тело", 7, "http://rm", "key", [1], timeout=5, dry=True,
                stage_draft=False, attachments=True, attach_max_files=4, attach_max_mb=9)
    cmd = seen["cmd"]
    assert cmd[cmd.index("--tools") + 1] == "Read"
    assert "Read" in cmd[cmd.index("--allowedTools") + 1]
    add_dirs = [cmd[i + 1] for i, x in enumerate(cmd) if x == "--add-dir"]
    assert got["dest"] in add_dirs
    prompt = cmd[cmd.index("-p") + 1]
    assert "err.png" in prompt and "doc.pdf" in prompt and "ОБЯЗАТЕЛЬНО открой" in prompt
    assert got["max_files"] == 4 and got["max_mb"] == 9


def test_analyze_no_attachments_no_read(monkeypatch):

    monkeypatch.setattr(dfl, "playbook_index", lambda: [])
    monkeypatch.setattr(dfl, "download_client_files", lambda *a, **k: [])
    seen = {}
    monkeypatch.setattr(dfl, "_run_cli", _capture_run_cli(seen))
    dfl.analyze("тема", "тело", 7, "http://rm", "key", [1], timeout=5, dry=True,
                stage_draft=False, attachments=True)
    cmd = seen["cmd"]
    assert cmd[cmd.index("--tools") + 1] == ""
    assert "--add-dir" not in cmd


def test_analyze_attachments_disabled_skips_download(monkeypatch):

    monkeypatch.setattr(dfl, "playbook_index", lambda: [])
    called = {"n": 0}

    def fake_dl(*a, **k):
        called["n"] += 1
        return []

    monkeypatch.setattr(dfl, "download_client_files", fake_dl)
    seen = {}
    monkeypatch.setattr(dfl, "_run_cli", _capture_run_cli(seen))
    dfl.analyze("тема", "тело", 7, "http://rm", "key", [1], timeout=5, dry=True,
                stage_draft=False, attachments=False)
    assert called["n"] == 0
    assert seen["cmd"][seen["cmd"].index("--tools") + 1] == ""


def test_analyze_alert_injects_attachments(monkeypatch):


    monkeypatch.setattr(dfl, "download_client_files",
                        lambda *a, **k: [("err.png", "/tmp/wa_att_y/err.png")])
    seen = {}
    monkeypatch.setattr(dfl, "_run_cli", _capture_run_cli(seen))
    aa.analyze_alert("базовый промпт разбора", 7, "http://rm", "key", [1],
                     sql_env=None, influx_env=None, graph=False, timeout=5,
                     mcp_tools=dfl.MCP_TOOLS, system_prompt="СИС",
                     builtin_tools="", tag="default-agent", attachments=True)
    cmd = seen["cmd"]
    assert cmd[cmd.index("--tools") + 1] == "Read"
    assert "Read" in cmd[cmd.index("--allowedTools") + 1]
    prompt = cmd[cmd.index("-p") + 1]
    assert "err.png" in prompt and "ОБЯЗАТЕЛЬНО открой" in prompt
    add_dirs = [cmd[i + 1] for i, x in enumerate(cmd) if x == "--add-dir"]
    assert add_dirs


def test_analyze_alert_no_attachments_by_default(monkeypatch):

    called = {"n": 0}

    def fake_dl(*a, **k):
        called["n"] += 1
        return []

    monkeypatch.setattr(dfl, "download_client_files", fake_dl)
    seen = {}
    monkeypatch.setattr(dfl, "_run_cli", _capture_run_cli(seen))
    aa.analyze_alert("промпт", 7, "http://rm", "key", [1], timeout=5,
                     mcp_tools=dfl.MCP_TOOLS, system_prompt="СИС", builtin_tools="")
    assert called["n"] == 0


class _FakeNotifier:
    def __init__(self):
        self.sent = []

    def send(self, event, title, text, issue_id=None):
        self.sent.append((event, title, text, issue_id))


def test_default_takes_in_work_and_notifies(tmp_path, monkeypatch):


    called = []
    monkeypatch.setattr(aa, "analyze_alert", lambda *a_, **kw: called.append(1))
    a = _agent(tmp_path)
    a.notifier = _FakeNotifier()
    a.cfg["roles"] = {"chief_engineer": 1, "engineer": 2}
    a._process_default(_issue(), "default-10105", {})
    assert a.redmine.taken == [(10105, 2, 2)]
    assert called == [] and aa.load_draft(a.root, 10105) is None
    assert "ticket_taken" in a.journal.verdicts()
    assert [e for e, *_ in a.notifier.sent] == ["new_ticket"]


def test_default_client_a_goes_to_chief(tmp_path, monkeypatch):

    a = _agent(tmp_path)
    a.cfg["roles"] = {"chief_engineer": 1, "engineer": 2}
    a.cfg["shift_handoff"] = {"client_a_clients": ["Клиент A"]}
    issue = dict(_issue(), project={"id": 5, "name": "Клиент A Т/П"})
    a._process_default(issue, "default-10105", {})
    assert a.redmine.taken == [(10105, 1, 2)]


def test_default_take_toggle_off_does_not_touch_ticket(tmp_path):


    a = _agent(tmp_path)
    a.notifier = _FakeNotifier()
    a.cfg["roles"] = {"chief_engineer": 1, "engineer": 2, "auto_take_engineer": False}
    a._process_default(_issue(), "default-10105", {})
    assert a.redmine.taken == []
    assert a.notifier.sent == []
    assert a.journal.verdicts() == ["take_disabled"]


def test_default_already_in_work_on_human_not_touched(tmp_path):

    a = _agent(tmp_path)
    a.cfg["roles"] = {"chief_engineer": 1, "engineer": 2}
    issue = dict(_issue(), status={"id": 2, "name": "В процессе: В работе"},
                 assigned_to={"id": 999, "name": "Чужой"})
    a._process_default(issue, "default-10105", {})
    assert a.redmine.taken == []
    assert "ticket_taken" in a.journal.verdicts()


def test_dry_run_launches_nothing(tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(aa, "analyze_alert",
                        lambda *a_, **kw: called.append(1))
    a = _agent(tmp_path, dry=True)
    a._process_default(_issue(), "default-10105", {})
    assert called == [] and a.redmine.taken == []
    assert aa.load_draft(a.root, 10105) is None
    assert approvals.load(a.root, 10105) is None
    assert a._aa_threads() == []
    assert "default_dry" in a.journal.verdicts()


def test_manual_opus_path_alive(tmp_path):
    a = _agent(tmp_path)

    ok, err = approvals.create_manual_opus(a.root, 10109, "заявка", prompt="проверь батчи")
    assert ok, err
    ap = approvals.load(a.root, 10109)
    assert ap["pipe"] == "opus" and ap["reason"] == "manual"

    ctx = router.Ctx(root=a.root, alert_overrides=set(), approval_held={10109},
                     trig={1, 49, 2}, fresh=10, alert_re=re.compile(r"\[alerting\]", re.I),
                     req_tracker=1, gf_tracker=65, alert_excl=[],
                     alerts_on=True, default_on=True, deferred_178={},
                     ticket_created=lambda i: None)
    d = router.classify_ticket(_issue(iid=10109), ctx, ap)
    assert d.branch == "opus"

    ap["status"] = "pending"
    with pytest.raises(_TicketDefer):
        a._handle_opus_request(_issue(iid=10109), ap, {})

    a._request_opus(10111, "тема", "тело", "Клиент G", origin_key="opus-10111",
                    reason="manual")
    ap2 = approvals.load(a.root, 10111)
    assert ap2 and ap2["pipe"] == "opus" and ap2["status"] == "pending"


def test_manual_opus_approved_writes_draft_card(tmp_path, monkeypatch):


    a = _agent(tmp_path, dry=False)

    def fake_dfl_analyze(subj, body, iid, url, key, contours, **kw):
        return {"ok": True, "session_id": "sess-op", "result": "итог", "error": None,
                "passes": 1, "tool_log": "",
                "draft": {"note": "Разбор ручного opus.", "confidence": "medium", "issue_id": iid}}
    monkeypatch.setattr(dfl, "analyze", fake_dfl_analyze)

    iid = 10112
    approvals.save(a.root, iid, {"pipe": "opus", "issue_id": iid, "subject": "тема",
                                 "reason": "manual", "origin_key": "opus-%d" % iid,
                                 "prompt": "", "status": "approved"})
    ap = approvals.load(a.root, iid)
    a._handle_opus_request(_issue(iid=iid), ap, {})
    for th in a._default_threads:
        if th.name == "default-%d" % iid:
            th.join(5)


    d = aa.load_draft(a.root, iid)
    assert d and d["status"] == "pending" and d["kind"] == "default"
    assert d["analysis"] == "Разбор ручного opus."
    assert d["comment"] == "h3. Разбор:\n\n" + d["analysis"]
    assert d["session_id"] == "sess-op" and d["screenshots"] == []

    assert approvals.load(a.root, iid) is None
    assert "opus_draft_ready" in a.journal.verdicts()


def test_held_draft_ids(tmp_path):
    root = str(tmp_path)
    assert aa.held_draft_ids(root) == set()
    aa.save_draft(root, 11, {"issue_id": 11, "status": "running"})
    aa.save_draft(root, 12, {"issue_id": 12, "status": "pending"})
    aa.save_draft(root, 13, {"issue_id": 13, "status": "posted"})
    assert aa.held_draft_ids(root) == {11, 12}


def test_contours_case_insensitive():


    projects = [{"id": 1, "name": "Клиент C. Площадка C5"}, {"id": 2, "name": "клиент C. Площадка C1"},
                {"id": 3, "name": "Клиент B (Площадка B2)"}]
    got = dfl.contour_project_ids("Клиент C. Площадка C5", projects)
    assert sorted(got) == [1, 2], got

    assert dfl.client_prefix("Клиент C. Площадка C5") == "Клиент C"
    assert dfl.client_prefix("клиент C. Площадка C1") == "клиент C"
