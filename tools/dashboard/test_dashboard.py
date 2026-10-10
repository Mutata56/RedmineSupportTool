#!/usr/bin/env python3
# -*- coding: utf-8 -*-


import io
import json
import os
import re
import shutil
import sys
import tempfile
import time
import types

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)


_CORE_ROOT = tempfile.mkdtemp(prefix="wa_test_core_")
os.makedirs(os.path.join(_CORE_ROOT, "config"))
os.makedirs(os.path.join(_CORE_ROOT, "state"))
os.environ["WA_CC_ROOT"] = _CORE_ROOT

from agent import approvals
from tools.dashboard import core

_fail = []


def check(name, cond, extra=""):
    print("%-54s %s %s" % (name, "OK" if cond else "FAIL", extra))
    if not cond:
        _fail.append(name)
        assert cond, f"{name}: {extra}"


def _chat_wait(iid, timeout=10.0):


    from tools.dashboard.routes import chats as _ch
    t0 = time.time()
    while time.time() - t0 < timeout:
        if not _ch._is_active(iid):
            return True
        time.sleep(0.02)
    return False


def test_agent_config():


    base = {
        "imap": {"host": "x"},
        "poll_seconds": 30, "dry_run": True,
        "max_mail_age_minutes": 60, "max_issues_per_hour": 15,
        "llm": {"enabled": True, "max_calls_route": 15, "max_calls_intent": 15},
        "ticket_poll": {"query_id": 178},
        "dedup": {"query_id": 178, "query_project": "example-project-001"},
        "routing": {"OLDSRV": {"project_id": 1, "client": "старый"}},
    }

    def write_cfg(d):
        with open(core.CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)

    def read_cfg():
        with open(core.CONFIG_FILE, encoding="utf-8") as f:
            return json.load(f)

    write_cfg(base)
    with open(core.SECRETS_FILE, "w", encoding="utf-8") as f:
        json.dump({"anthropic_api_key": "sk-ant-api03-SECRET-VALUE-WXYZ"}, f)


    snap = core.read_agent_config()
    check("read_agent_config: whitelisted-поля + routing + dry_run",
          snap["poll_seconds"] == 30 and snap["query_id"] == 178
          and snap["max_calls_route"] == 15
          and snap["routing"].get("OLDSRV", {}).get("project_id") == 1 and snap["dry_run"] is True)
    check("read_agent_config: API-ключ ЗАМАСКИРОВАН (полный не отдаётся)",
          snap["anthropic_api_key"] == "sk-ant-••••WXYZ" and "SECRET" not in snap["anthropic_api_key"])
    with open(core.SECRETS_FILE, "w", encoding="utf-8") as f:
        json.dump({"anthropic_api_key": ""}, f)
    check("read_agent_config: пустой ключ -> ''", core.read_agent_config()["anthropic_api_key"] == "")


    ok, _ = core.set_agent_config({"poll_seconds": 45, "query_id": 200,
                                   "max_calls_route": 7})
    c = read_cfg()
    check("set_agent_config: валидное обновление (top + вложенные по месту)",
          ok and c["poll_seconds"] == 45 and c["dedup"]["query_id"] == 200
          and c["llm"]["max_calls_route"] == 7)
    check("set_agent_config: посторонние блоки/ключи уцелели (не клоббер, ticket_poll.query_id не тронут)",
          c["imap"]["host"] == "x" and c["ticket_poll"]["query_id"] == 178
          and c["dedup"]["query_project"] == "example-project-001" and c["llm"]["max_calls_intent"] == 15)


    before = read_cfg()
    ok2, _ = core.set_agent_config({"poll_seconds": 99, "unknown_field": 1})
    check("set_agent_config: неизвестное поле -> отказ, config не тронут", not ok2 and read_cfg() == before)


    bad = [core.set_agent_config({"poll_seconds": "30"})[0],
           core.set_agent_config({"poll_seconds": True})[0],
           core.set_agent_config({"poll_seconds": 4})[0],
           core.set_agent_config({"max_calls_route": 999})[0]]
    check("set_agent_config: битый тип / bool<->int / выход за границы -> отказ",
          not any(bad) and read_cfg() == before)


    write_cfg({"poll_seconds": 30})
    okn, _ = core.set_agent_config({"max_calls_route": 7})
    check("set_agent_config: отсутствующий вложенный dict (llm) создаётся",
          okn and read_cfg().get("llm") == {"max_calls_route": 7})


    write_cfg(base)
    okr, _ = core.edit_routing("add", "newsrv", project_id=621, client="Клиент B")
    r = read_cfg()["routing"]
    check("edit_routing add: ключ в UPPER + project_id/client, старые целы",
          okr and r.get("NEWSRV") == {"project_id": 621, "client": "Клиент B"} and "OLDSRV" in r)
    okd, _ = core.edit_routing("delete", "newsrv")
    r2 = read_cfg()["routing"]
    check("edit_routing delete: ключ убран, остальные целы",
          okd and "NEWSRV" not in r2 and "OLDSRV" in r2)
    check("edit_routing: пустой ключ / add без project_id / битый action / delete отсутствующего -> отказ",
          not core.edit_routing("add", "  ", project_id=1)[0]
          and not core.edit_routing("add", "x")[0]
          and not core.edit_routing("bogus", "x")[0]
          and not core.edit_routing("delete", "nope")[0])


    write_cfg(dict(base, roles={"chief_engineer": 1, "engineer": None},
                   known_people={"Engineer 01": 1}))
    snap = core.read_agent_config()
    check("read_agent_config: роли + known_people отдаются в GUI",
          snap["role_chief_engineer"] == 1 and snap["role_engineer"] is None
          and snap["known_people"] == {"Engineer 01": 1})

    check("тумблеры взятия: нет ключей -> True (старое поведение)",
          snap["take_chief"] is True and snap["take_engineer"] is True)
    okt, _et = core.set_agent_config({"take_engineer": False})
    ct = read_cfg()
    check("тумблер «остальные на напарника» -> roles.auto_take_engineer=false, роли не задеты",
          okt and ct["roles"]["auto_take_engineer"] is False
          and ct["roles"].get("auto_take_chief") in (None, True)
          and ct["roles"]["chief_engineer"] == 1)
    okt2, _et2 = core.set_agent_config({"take_chief": False, "take_engineer": True})
    ct2 = read_cfg()
    check("оба тумблера пишутся независимо",
          okt2 and ct2["roles"]["auto_take_chief"] is False
          and ct2["roles"]["auto_take_engineer"] is True)
    check("auto_analyze больше не отдаётся GUI (тумблер снят вместе с авто-разбором)",
          "auto_analyze" not in snap)

    okx, _ = core.set_agent_config({"role_engineer": 2, "role_chief_engineer": 0})
    c = read_cfg()
    check("set_agent_config: роль пишется по месту, 0 -> null",
          okx and c["roles"]["engineer"] == 2 and c["roles"]["chief_engineer"] is None)
    check("set_agent_config: роль вне диапазона / bool -> отказ",
          not core.set_agent_config({"role_engineer": -1})[0]
          and not core.set_agent_config({"role_engineer": True})[0])


    write_cfg(dict(base, messengers={"enabled": [], "events": ["new_ticket"],
                                     "telegram": {"chat_id": None},
                                     "ntfy": {"url": "https://ntfy.sh", "topic": ""}}))
    with open(core.SECRETS_FILE, "w", encoding="utf-8") as f:
        json.dump({"telegram_bot_token": "123:SECRET"}, f)
    snap = core.read_agent_config()
    check("read_agent_config: мессенджеры (тогглы из enabled + токен только фактом)",
          snap["messenger_telegram"] is False and snap["messenger_ntfy"] is False
          and snap["telegram_token_set"] is True
          and "SECRET" not in json.dumps(snap, ensure_ascii=False))
    okm, _ = core.set_agent_config({"messenger_telegram": True, "messenger_ntfy": True,
                                    "telegram_chat_id": " 42 ", "ntfy_topic": "wa-alerts"})
    c = read_cfg()
    check("set_agent_config: тогглы собраны в enabled + chat_id/topic (со strip)",
          okm and c["messengers"]["enabled"] == ["telegram", "ntfy"]
          and c["messengers"]["telegram"]["chat_id"] == "42"
          and c["messengers"]["ntfy"]["topic"] == "wa-alerts"
          and c["messengers"]["events"] == ["new_ticket"])
    okm2, _ = core.set_agent_config({"messenger_telegram": False, "telegram_chat_id": ""})
    c = read_cfg()
    check("set_agent_config: тоггл off убирает из enabled, пустой chat_id -> null",
          okm2 and c["messengers"]["enabled"] == ["ntfy"]
          and c["messengers"]["telegram"]["chat_id"] is None)
    check("set_agent_config: chat_id не-строка / topic длиннее лимита -> отказ",
          not core.set_agent_config({"telegram_chat_id": 42})[0]
          and not core.set_agent_config({"ntfy_topic": "x" * 200})[0])


def test_model_effort():

    tmp = tempfile.mkdtemp(prefix="wa_test_meq_")
    try:
        ok, _ = approvals.create_manual_opus(tmp, 555, "тема", "инстр", model="sonnet", effort="xhigh")
        f = approvals.load(tmp, 555)
        check("create_manual_opus сохраняет model/effort",
              ok and f.get("model") == "sonnet" and f.get("effort") == "xhigh", str(f.get("model")))

        approvals.save(tmp, 556, {"pipe": "opus", "issue_id": 556, "status": "pending"})
        ok2, _ = approvals.decide(tmp, 556, "approved", model="claude-haiku-4-5", effort="low")
        f2 = approvals.load(tmp, 556)
        check("decide(opus) сохраняет model/effort + status",
              ok2 and f2.get("model") == "claude-haiku-4-5" and f2.get("effort") == "low"
              and f2.get("status") == "approved")

        approvals.save(tmp, 557, {"pipe": "alert", "issue_id": 557, "status": "pending"})
        approvals.decide(tmp, 557, "approved", model="sonnet", effort="max")
        check("не-opus ветка НЕ хранит model/effort", "model" not in approvals.load(tmp, 557))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_mode_honesty():

    core._pid_alive = lambda p: True
    core._pid_is_agent = lambda p: True

    def write_status(**kw):
        base = {"status": "кручусь", "ts": time.time(), "at": "now",
                "pid": 4242, "started_at": "2026-01-01 00:00:00"}
        base.update(kw)
        with open(core.STATUS_FILE, "w", encoding="utf-8") as f:
            json.dump(base, f)

    with open(core.CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump({"dry_run": True}, f)
    write_status(dry_run=False)
    s = core.agent_status()
    check("боевой процесс (config dry) -> GUI показывает running/live",
          s["state"] == "running" and s["dry_run"] is False, str(s["state"]))

    with open(core.CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump({"dry_run": False}, f)
    write_status(dry_run=True)
    s = core.agent_status()
    check("status.json dry главнее config live -> dry-run",
          s["state"] == "dry-run" and s["dry_run"] is True, str(s["state"]))


    write_status(ts=time.time() - 99999, dry_run=False)
    s = core.agent_status()
    check("протухший heartbeat при ЖИВОМ pid -> всё ещё running + stale=True",
          s["state"] == "running" and s["stale"] is True and s["pid"] == 4242, str(s["state"]))

    saved_alive = core._pid_alive
    try:
        core._pid_alive = lambda pid: False
        s2 = core.agent_status()
        check("протухший статус + МЁРТВЫЙ pid -> stopped, pid/started_at обнулены",
              s2["state"] == "stopped" and s2["pid"] is None and s2["started_at"] is None)
    finally:
        core._pid_alive = saved_alive


def test_pause_control():


    with open(core.CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump({"dry_run": True}, f)

    core.set_paused(False)
    check("is_paused() дефолт -> False", core.is_paused() is False)
    ok, _ = core.set_paused(True)
    check("set_paused(True) -> ok и is_paused()=True", ok and core.is_paused() is True)

    with open(core.CONFIG_FILE, encoding="utf-8") as f:
        cfg_after = json.load(f)
    check("пауза НЕ трогает config.json", cfg_after == {"dry_run": True})

    with open(core.CONTROL_FILE, "w", encoding="utf-8") as f:
        f.write("{ битый json")
    check("битый control.json -> is_paused()=False (fail-safe)", core.is_paused() is False)

    core.set_paused(True)
    with open(core.STATUS_FILE, "w", encoding="utf-8") as f:
        json.dump({"status": "кручусь", "ts": time.time(), "at": "now",
                   "pid": 4242, "started_at": "2026-01-01 00:00:00", "dry_run": True}, f)
    s = core.agent_status()
    check("agent_status: живой + пауза -> paused=True",
          s.get("paused") is True and s["state"] == "dry-run", str(s.get("paused")))


    with open(core.STATUS_FILE, "w", encoding="utf-8") as f:
        json.dump({"status": "x", "ts": time.time() - 99999, "pid": 4242,
                   "started_at": "2026-01-01 00:00:00"}, f)
    _saved_alive = core._pid_alive
    try:
        core._pid_alive = lambda pid: False
        s2 = core.agent_status()
    finally:
        core._pid_alive = _saved_alive
    check("agent_status: stopped -> paused=False (флаг игнорируется)",
          s2["state"] == "stopped" and s2["paused"] is False)

    core.set_paused(True)
    saved_kill, saved_live = core.os.kill, core._live_agent_pid
    core.os.kill = lambda *a, **k: None
    core._live_agent_pid = lambda: (4242, None)
    try:
        core.stop_agent()
    finally:
        core.os.kill, core._live_agent_pid = saved_kill, saved_live
    check("stop_agent снимает паузу", core.is_paused() is False)


def test_start_cmd():

    cap = {}

    class FakeProc:
        pid = 1

    def fake_popen(cmd, **kw):
        cap["cmd"] = cmd
        return FakeProc()

    orig_popen = core.subprocess.Popen
    core.subprocess.Popen = fake_popen
    core.agent_status = lambda: {"state": "stopped", "pid": None}
    try:
        with open(core.CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump({"dry_run": True}, f)
        core.start_agent(live=None)
        check("start(config dry, live=None) -> без --live", "--live" not in cap["cmd"])

        with open(core.CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump({"dry_run": False}, f)
        cap.clear(); core.start_agent(live=None)
        check("start(config live, live=None) -> --live", "--live" in cap["cmd"])

        cap.clear(); core.start_agent(live=True)
        check("start(live=True override) -> --live", "--live" in cap["cmd"])

        cap.clear(); core.start_agent(live=False)
        check("start(live=False override) -> без --live", "--live" not in cap["cmd"])
    finally:
        core.subprocess.Popen = orig_popen


def test_alert_escalation():


    from agent.orchestrator import Agent
    tmp = tempfile.mkdtemp(prefix="wa_test_esc_")
    try:
        f = types.SimpleNamespace()
        f.default_cfg = {"enabled": True, "model": "claude-opus-4-8", "effort": "high",
                         "escalate_alert_types": ["locks", "log_size", "freespace", "archive_backup"]}
        f.root = tmp
        f.journal = types.SimpleNamespace(record=lambda *a, **k: None)
        f.log = types.SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None)
        f._request_opus = types.MethodType(Agent._request_opus, f)
        esc = types.MethodType(Agent._maybe_escalate_alert_to_opus, f)

        esc({"id": 12345, "subject": "[Alerting] LOCKS", "description": "b"},
            {"type": "locks", "comment": "sql", "mode": "deterministic"}, "ticket-12345")
        ap = approvals.load(tmp, 12345)
        check("locks -> opus alert_analysis pending + get_issue prompt",
              bool(ap) and ap["pipe"] == "opus" and ap["reason"] == "alert_analysis"
              and ap["status"] == "pending" and "get_issue" in ap.get("prompt", ""))

        allok = True
        for tp, iid in (("freespace", 101), ("log_size", 102), ("archive_backup", 103)):
            esc({"id": iid, "subject": "x"}, {"type": tp, "comment": "c"}, "ticket-%d" % iid)
            a = approvals.load(tmp, iid)
            allok = allok and bool(a) and a["reason"] == "alert_analysis"
        check("freespace/log_size/archive_backup все эскалируют", allok)

        esc({"id": 999, "subject": "x"}, {"type": "tempdb", "comment": "c"}, "ticket-999")
        check("не-настроенный тип (tempdb) НЕ эскалирует", approvals.load(tmp, 999) is None)

        approvals.save(tmp, 555, {"pipe": "opus", "issue_id": 555, "status": "pending", "reason": "old"})
        esc({"id": 555, "subject": "x"}, {"type": "locks", "comment": "c"}, "ticket-555")
        check("существующий pending НЕ перетирается", approvals.load(tmp, 555)["reason"] == "old")

        f.default_cfg = dict(f.default_cfg, enabled=False)
        esc({"id": 777, "subject": "x"}, {"type": "locks", "comment": "c"}, "ticket-777")
        check("enabled=false -> НЕ эскалирует", approvals.load(tmp, 777) is None)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_docs_dir_resolution():


    from agent.orchestrator import Agent
    f = types.SimpleNamespace()
    f.default_cfg = {"docs_dirs": {"Клиент B": "/d/CLIENT_B", "Клиент C": "/d/CLC", "Клиент A": "/d/client_a"}}
    g = types.MethodType(Agent._docs_dir_for, f)
    ok = (g("Клиент B - Т/П") == "/d/CLIENT_B" and g("Клиент B Площадка B5") == "/d/CLIENT_B"
          and g("Клиент B Площадка B4") == "/d/CLIENT_B" and g("Клиент C. Площадка C6") == "/d/CLC"
          and g("Клиент A Т/П") == "/d/client_a" and g("КЛИЕНТ D. ИМ Площадка D5") is None
          and g("CLE.LV - ТП") is None and g("") is None)
    check("docs_dirs prefix-резолвинг (Клиент B*/Клиент C*/Клиент A* -> папки, прочие None)", ok)

    f.default_cfg = {"docs_dirs": {}}
    check("пустой docs_dirs -> None", types.MethodType(Agent._docs_dir_for, f)("Клиент B") is None)


def test_manual_dispatch():


    tmp = tempfile.mkdtemp(prefix="wa_test_disp_")
    try:
        ok, _ = approvals.create_manual_alert(tmp, 10100, "[Alerting] LOCKS")
        fa = approvals.load(tmp, 10100)
        check("create_manual_alert: override pipe=alert + alert_overrides()",
              ok and fa["pipe"] == "alert" and approvals.alert_overrides(tmp) == {10100})
        check("alert-handoff виден в held_ids() (удержание от возрастного фильтра)",
              10100 in approvals.held_ids(tmp))
        approvals.save(tmp, 999, {"pipe": "opus", "issue_id": 999, "status": "pending"})
        ok3, _ = approvals.create_manual_alert(tmp, 999, "t")
        check("висящий pending не перетирается", not ok3)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_influx_series_helpers():

    from agent import grafana_sets as gfs
    dash = {"dashboard": {"panels": [
        {"title": "Блокировки", "targets": [{"measurement": "t_AdmLockBlock", "policy": "default",
            "select": [[{"type": "field", "params": ["wait_duration_ms"]}, {"type": "max", "params": []}]],
            "tags": [{"key": "host", "value": "h1", "operator": "="}]}]},
        {"title": "Log_Size_WMS_EXAMPLE", "targets": [{"measurement": "Log size (bytes)", "policy": "1day",
            "select": [[{"type": "field", "params": ["WMS_EXAMPLE"]}, {"type": "mean", "params": []}]],
            "tags": [{"key": "servername", "value": "DB1", "operator": "="}]}]},
    ]}}
    tg = gfs.service_series_targets(dash, "locks")
    check("service_series_targets: locks -> t_AdmLockBlock/max",
          len(tg) == 1 and tg[0][1]["measurement"] == "t_AdmLockBlock"
          and tg[0][1]["agg"] == "max" and tg[0][1]["field"] == "wait_duration_ms")
    q = gfs.influx_series_query(tg[0][1], window="30h", every="10m", limit=200)
    check("influx_series_query: max-агрегация + LIMIT 200 + measurement",
          'max("wait_duration_ms")' in q and "LIMIT 200" in q and "t_AdmLockBlock" in q)
    tl = gfs.service_series_targets(dash, "log_size")
    check("log_size: retention-policy 1day в запросе",
          bool(tl) and '"1day"."Log size (bytes)"' in gfs.influx_series_query(tl[0][1]))
    blk = gfs.format_series("Блокировки", [["2026-07-12T04:30:00Z", 9520], ["2026-07-12T04:20:00Z", 100]])
    check("format_series: блок с меткой и значением", bool(blk) and "Блокировки" in blk and "9520" in blk)
    check("format_series: пустой ряд -> None", gfs.format_series("x", []) is None)


def test_influx_series_into_prompt():


    from agent.orchestrator import Agent
    tmp = tempfile.mkdtemp(prefix="wa_test_infp_")
    try:
        f = types.SimpleNamespace()
        f.default_cfg = {"enabled": True, "model": "claude-opus-4-8", "effort": "high",
                         "escalate_alert_types": ["locks"]}
        f.gf_cfg = {"influx_window": "30h", "influx_step": "10m", "influx_points": 200,
                    "influx_ds_id": 3, "influx_db": "telegraf"}
        f.root = tmp
        f.journal = types.SimpleNamespace(record=lambda *a, **k: None)
        f.log = types.SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None)
        f._request_opus = types.MethodType(Agent._request_opus, f)
        sis = types.MethodType(Agent._service_influx_series, f)
        esc = types.MethodType(Agent._maybe_escalate_alert_to_opus, f)

        class StubGC:
            def dashboard(self, uid):
                return {"dashboard": {"panels": [{"title": "Блокировки", "targets": [{
                    "measurement": "t_AdmLockBlock", "policy": "default",
                    "select": [[{"type": "field", "params": ["wait_duration_ms"]},
                                {"type": "max", "params": []}]],
                    "tags": [{"key": "host", "value": "h1", "operator": "="}]}]}]}}

            def influx(self, q, ds_id=3, db="telegraf"):
                return {"results": [{"series": [{"values": [["2026-07-12T04:30:00Z", 9520],
                                                            ["2026-07-12T04:20:00Z", 100]]}]}]}

        verdict = {"type": "locks", "comment": "sql"}
        sis(StubGC(), {"uid": "X"}, verdict, "тема")
        check("_service_influx_series заполняет verdict['influx_series']",
              "influx_series" in verdict and "9520" in verdict["influx_series"])
        esc({"id": 42, "subject": "[Alerting] LOCKS", "description": "b"}, verdict, "ticket-42")
        ap = approvals.load(tmp, 42)
        check("ряд InfluxDB попал в промпт эскалации",
              bool(ap) and "9520" in ap.get("prompt", "") and "МОМЕНТ АЛЕРТА" in ap.get("prompt", ""))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


PNG_1PX = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8z8BQDwAEhQGAhKmMIQ"
           "AAAABJRU5ErkJggg==")


def _write_draft(iid, **over):

    import base64
    from tools.dashboard import drafts
    shot_dir = os.path.join(drafts.DRAFTS_DIR, str(iid))
    os.makedirs(shot_dir, exist_ok=True)
    with open(os.path.join(shot_dir, "p1.png"), "wb") as f:
        f.write(base64.b64decode(PNG_1PX))
    d = {"issue_id": iid, "subject": "[Alerting] TEST", "kind": "alert", "status": "pending",
         "analysis": "Разбор: всплеск блокировок, виноват джоб X.",
         "sql": "<pre>SELECT 1 /* 42 */</pre>",
         "screenshots": [{"sid": "p1", "file": "state/drafts/%d/p1.png" % iid,
                          "title": "Блокировки · APP", "approved": True}],
         "comment": "h3. Разбор\n\nВсплеск блокировок.\n\n<pre>SELECT 1</pre>",
         "created_at": "2026-07-15 10:00:00",
         "session_id": "dddd0000-1111-2222-3333-444455556666"}
    d.update(over)
    drafts.save_draft(iid, d)
    return d


def test_draft_helpers():


    from tools.dashboard import drafts
    yes = ["ок", "Ок!", "ok", "да", "да, пости", "пости в редмайн", "публикуй",
           "одобряю.", "запость её", "аппрув"]
    no_cmd = ["ок, но поправь sql", "хорошо", "что делать?", "пости\nи поправь ещё вот это",
              "не пости", ""]
    check("draft: аффирмативы матчатся (всё сообщение целиком)",
          all(drafts.is_affirmative(t) for t in yes),
          str([t for t in yes if not drafts.is_affirmative(t)]))
    check("draft: правки/вопросы/отказ НЕ аффирматив",
          not any(drafts.is_affirmative(t) for t in no_cmd),
          str([t for t in no_cmd if drafts.is_affirmative(t)]))
    dec = ["не пости", "Не пости это", "отклоняю", "не надо", "отмена!"]
    check("draft: отклонения матчатся, прочее нет",
          all(drafts.is_decline(t) for t in dec)
          and not drafts.is_decline("неправильно") and not drafts.is_decline("ок"))


    instr_no_approve = ["пости после того как поправишь раздел про блокировки",
                        "одобряю но замени таблицу", "ок, но поправь sql",
                        "публикуй когда проверишь SQL"]
    instr_no_decline = ["не надо торопиться, сначала покажи LOTXLOCXID",
                        "не надо трогать ORDERS, посмотри по PICKDETAIL",
                        "не надо, сперва уточни у клиента"]
    check("draft: «пости ПОСЛЕ ТОГО КАК поправишь» НЕ публикует",
          not any(drafts.is_affirmative(t) for t in instr_no_approve),
          str([t for t in instr_no_approve if drafts.is_affirmative(t)]))
    check("draft: «не надо торопиться, покажи X» НЕ отклоняет (скрины не сносятся)",
          not any(drafts.is_decline(t) for t in instr_no_decline),
          str([t for t in instr_no_decline if drafts.is_decline(t)]))

    check("draft: textile_image_lines -> '!имя!'-строки",
          drafts.textile_image_lines(["a.png", "b.png"]) == "!a.png!\n!b.png!")

    d = _write_draft(43199)
    check("draft: save/load round-trip + pending_drafts()",
          drafts.load_draft(43199)["analysis"] == d["analysis"]
          and 43199 in drafts.pending_drafts())


    with open(core.CONFIG_FILE, "a", encoding="utf-8"):
        pass
    evil = dict(d, screenshots=d["screenshots"] + [
        {"sid": "evil", "file": "config/config.json", "approved": True},
        {"sid": "gone", "file": "state/drafts/43199/nope.png", "approved": True},
        {"sid": "trav", "file": "state/drafts/../../config/config.json", "approved": True}])
    ok_path = drafts.resolve_shot(evil, "p1")
    check("draft: resolve_shot по sid -> файл под state/drafts/",
          bool(ok_path) and ok_path.endswith(os.path.join("43199", "p1.png")))
    check("draft: чужой путь / traversal / пропавший файл / левый sid -> None",
          drafts.resolve_shot(evil, "evil") is None and drafts.resolve_shot(evil, "trav") is None
          and drafts.resolve_shot(evil, "gone") is None and drafts.resolve_shot(evil, "xx") is None)
    check("draft: approved_shots только живые одобренные",
          [s[0] for s in drafts.approved_shots(evil)] == ["p1"])

    note = drafts.build_note(d, ["p1.png"])
    check("draft: build_note = comment + '!img!'-строки",
          note.startswith("h3. Разбор") and note.endswith("\n\n!p1.png!"))
    fb = drafts.build_note({"analysis": "тело", "sql": "<pre>q</pre>"}, [])
    check("draft: build_note без comment собирается из analysis+sql",
          fb == "h3. Разбор\n\nтело\n\n<pre>q</pre>")

    m = drafts.draft_message(43199, d)
    check("draft: сообщение role=draft (text/sql/скрины c url/ts по created_at)",
          m["role"] == "draft" and m["text"] == d["analysis"] and m["sql"] == d["sql"]
          and m["screenshots"] == [{"sid": "p1", "title": "Блокировки · APP",
                                    "url": "/api/drafts/43199/shot/p1"}]
          and m["at"] == "2026-07-15 10:00:00" and m["ts"] > 0)

    drafts.clean_shots(43199)
    check("draft: clean_shots убирает PNG-папку",
          not os.path.isdir(os.path.join(drafts.DRAFTS_DIR, "43199")))
    try:
        os.remove(drafts.draft_path(43199))
    except OSError:
        pass


def test_draft_chat_flow():


    try:
        import fastapi
    except ImportError:
        print("%-54s SKIP (нет fastapi)" % "draft chat flow")
        return
    from tools.dashboard import drafts
    from tools.dashboard.routes import chats
    from tools.dashboard.routes import drafts as drafts_routes
    from tools.dashboard.models import ChatSendRequest
    root = core.ROOT
    with open(os.path.join(root, "config", "secrets.local.json"), "w", encoding="utf-8") as f:
        json.dump({"redmine_url": "http://service.example.invalid", "redmine_api_key": "k"}, f)

    with open(os.path.join(root, "state", "processed.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": 1500, "at": "2026-07-15 09:59:00", "message_id": "ticket-43210",
                            "verdict": "draft_ready", "subject": "[Alerting] TEST",
                            "issue_id": 43210, "detail": "Разбор: всплеск блокировок",
                            "note": "черновик готов", "interim": True}) + "\n")
    d = _write_draft(43210)

    hist = chats.chat_history(43210)
    dm = [m for m in hist["messages"] if m.get("role") == "draft"]
    check("draft flow: pending-черновик в истории чата (role=draft, скрины, сид сессии)",
          len(dm) == 1 and dm[0]["screenshots"][0]["url"] == "/api/drafts/43210/shot/p1"
          and hist["session_id"] == d["session_id"])
    check("draft flow: вердикт draft_ready сидирует историю (role=agent)",
          any(m.get("role") == "agent" and "всплеск блокировок" in m.get("text", "")
              for m in hist["messages"]))
    c = next((x for x in chats.chats_list()["items"] if x["issue_id"] == 43210), None)
    check("draft flow: заявка в списке чатов с has_draft и превью",
          bool(c) and c["has_draft"] and "Разбор" in c["preview"], str(c)[:100])


    r_ok = drafts_routes.draft_shot(43210, "p1")
    r_404 = drafts_routes.draft_shot(43210, "../../etc/passwd")
    check("draft flow: GET shot -> PNG по sid, мусорный sid -> 404",
          getattr(r_ok, "path", "").endswith("p1.png") and r_404.status_code == 404)

    saved_status = core.agent_status
    saved_rc = drafts.rmc.RedmineClient
    try:


        core.agent_status = lambda: {"dry_run": True}
        r1 = drafts_routes.draft_publish(43210)
        check("draft flow: /publish в dry -> DRY-RUN, черновик pending + след в чате",
              r1["ok"] and r1.get("dry") and "DRY-RUN" in r1["text"]
              and drafts.load_draft(43210)["status"] == "pending"
              and any("DRY-RUN" in m.get("text", "")
                      for m in chats.chat_history(43210)["messages"]))


        core.agent_status = lambda: {"dry_run": False}
        posted, ups = [], []

        class FakeRC:
            def __init__(self, url, key):
                pass

            def upload(self, data, filename):
                ups.append((filename, len(data)))
                return "tok-" + filename

            def add_note(self, issue_id, note, uploads=None, private=True):
                posted.append((issue_id, note, uploads, private))

        drafts.rmc.RedmineClient = FakeRC
        r2 = drafts_routes.draft_publish(43210)
        note = posted[0][1] if posted else ""
        check("draft flow: /publish боевой -> upload PNG + add_note(private, comment+!img!)",
              r2["ok"] and r2.get("posted") and len(posted) == 1 and posted[0][0] == 43210
              and posted[0][3] is True
              and note.startswith("h3. Разбор") and "!p1.png!" in note
              and ups and ups[0][0] == "p1.png" and ups[0][1] > 0
              and posted[0][2][0]["token"] == "tok-p1.png")
        check("draft flow: черновик posted + «Опубликовано ✓» в истории чата",
              drafts.load_draft(43210)["status"] == "posted" and "Опубликовано ✓" in r2["text"]
              and not any(m.get("role") == "draft" for m in chats.chat_history(43210)["messages"])
              and any("Опубликовано ✓" in m.get("text", "")
                      for m in chats.chat_history(43210)["messages"]))


        _write_draft(43211)
        r3 = chats.chat_send(43211, ChatSendRequest(message="не пости"))
        check("draft flow: «не пости» -> declined + PNG-папка убрана",
              r3["ok"] and drafts.load_draft(43211)["status"] == "declined"
              and not os.path.isdir(os.path.join(drafts.DRAFTS_DIR, "43211")))


        tmp = tempfile.mkdtemp(prefix="wa_test_dflow_")
        saved_projects = chats.CLAUDE_PROJECTS
        try:
            d3 = _write_draft(43212)
            sess_cwd = os.path.join(tmp, "draft_cwd")
            os.makedirs(os.path.join(tmp, "projects", "p1"))
            with open(os.path.join(tmp, "projects", "p1", d3["session_id"] + ".jsonl"), "w") as f:
                f.write(json.dumps({"type": "user", "cwd": sess_cwd}) + "\n")
            chats.CLAUDE_PROJECTS = os.path.join(tmp, "projects")
            cap, reply = os.path.join(tmp, "cap.txt"), os.path.join(tmp, "reply.json")


            hook = os.path.join(tmp, "drafthook.py")
            with open(hook, "w", encoding="utf-8") as f:
                f.write("import sys, json\n"
                        "a = sys.argv[1:]\n"
                        "if '--mcp-config' in a:\n"
                        "    try:\n"
                        "        cfg = json.load(open(a[a.index('--mcp-config') + 1]))\n"
                        "        df = cfg['mcpServers']['redmine']['env'].get('RM_DRAFT_FILE')\n"
                        "        if df:\n"
                        "            json.dump({'note': 'Переделанный разбор: топ-5 по "
                        "wait_duration_ms, джоб X перенесён на 03:00.', 'confidence': 'high', "
                        "'issue_id': 43212}, open(df, 'w'))\n"
                        "    except Exception:\n"
                        "        pass\n")
            fake = os.path.join(tmp, "claude")
            with open(fake, "w") as f:
                f.write('#!/bin/sh\n{ for a in "$@"; do printf "%s\\n" "$a"; done; cat; } > "'
                        + cap + '"\npython3 "' + hook + '" "$@"\ncat "' + reply + '"\n')
            os.chmod(fake, 0o755)
            os.environ["DASH_CLAUDE_BIN"] = fake
            with open(reply, "w") as f:
                json.dump({"is_error": False, "result": "поправил",
                           "session_id": d3["session_id"]}, f)
            r4 = chats.chat_send(43212, ChatSendRequest(message="поправь SQL: возьми топ-5"))
            _chat_wait(43212)
            argv = open(cap, encoding="utf-8").read().splitlines()
            da = drafts.load_draft(43212)
            hist4 = chats.chat_history(43212)


            check("draft flow: правки -> resume сессии + черновик ПЕРЕПИСАН новой версией (draft-режим)",
                  r4["ok"] and r4.get("queued") and "--resume" in argv
                  and argv[argv.index("--resume") + 1] == d3["session_id"]
                  and da["status"] == "pending"
                  and da["analysis"].startswith("Переделанный разбор: топ-5")
                  and da["comment"].endswith("джоб X перенесён на 03:00.")
                  and da.get("analysis_seconds", -1) >= 0
                  and any("Черновик разбора обновлён" in m.get("text", "")
                          for m in hist4["messages"]))
        finally:
            os.environ.pop("DASH_CLAUDE_BIN", None)
            chats.CLAUDE_PROJECTS = saved_projects
            shutil.rmtree(tmp, ignore_errors=True)
    finally:
        core.agent_status = saved_status
        drafts.rmc.RedmineClient = saved_rc


def test_chats():


    try:
        import fastapi
    except ImportError:
        print("%-54s SKIP (нет fastapi)" % "chats")
        return
    from tools.dashboard.routes import chats
    from tools.dashboard.models import ChatSendRequest
    sid = "abc12345-dead-beef-0000-000000000001"
    sid2 = "ffff1111-2222-3333-4444-555566667777"
    root = core.ROOT
    with open(os.path.join(root, "state", "processed.jsonl"), "w", encoding="utf-8") as f:
        f.write(json.dumps({"ts": 1000, "at": "2026-07-12 10:00:00", "message_id": "ticket-777",
                            "verdict": "grafana_attached", "subject": "[Alerting] LOCKS",
                            "issue_id": 777, "note": "взята"}) + "\n")

        f.write(json.dumps({"ts": 2000, "at": "2026-07-12 11:00:00", "message_id": "default-777",
                            "verdict": "default_done", "subject": "[Alerting] LOCKS",
                            "issue_id": 777, "detail": "Разбор: похожие #100, SQL ниже",
                            "note": "ok=True пассов=1; DRY (live_post=false), session=%s; "
                                    "полный ответ ИИ ниже" % sid}) + "\n")
    with open(os.path.join(root, "config", "secrets.local.json"), "w", encoding="utf-8") as f:
        json.dump({"redmine_url": "http://service.example.invalid", "redmine_api_key": "k"}, f)

    tmp = tempfile.mkdtemp(prefix="wa_test_chat_")
    try:

        sess_cwd = os.path.join(tmp, "wa_default_gone")
        os.makedirs(os.path.join(tmp, "projects", "p1"))
        with open(os.path.join(tmp, "projects", "p1", sid + ".jsonl"), "w") as f:
            f.write(json.dumps({"type": "user", "cwd": sess_cwd}) + "\n")
        chats.CLAUDE_PROJECTS = os.path.join(tmp, "projects")


        cap, reply = os.path.join(tmp, "cap.txt"), os.path.join(tmp, "reply.json")
        fake = os.path.join(tmp, "claude")
        with open(fake, "w") as f:
            f.write('#!/bin/sh\n{ printf "%s\\n" "$PWD"; for a in "$@"; do '
                    'printf "%s\\n" "$a"; done; cat; } > "' + cap + '"\ncat "' + reply + '"\n')
        os.chmod(fake, 0o755)
        os.environ["DASH_CLAUDE_BIN"] = fake
        with open(reply, "w") as f:
            json.dump({"is_error": False, "result": "Ответ модели: ```sql\nSELECT 1\n```",
                       "session_id": sid2, "usage": {"input_tokens": 5, "output_tokens": 7}}, f)

        lst = chats.chats_list()["items"]
        c777 = next((c for c in lst if c["issue_id"] == 777), None)
        check("chats: заявка с ИИ-разбором в списке чатов",
              bool(c777) and c777["has_session"] and "Разбор" in c777["preview"], str(c777)[:80])

        hist = chats.chat_history(777)
        check("chats: история сидируется разбором агента + session из журнала",
              hist["session_id"] == sid and len(hist["messages"]) == 1
              and hist["messages"][0]["role"] == "agent")

        r = chats.chat_send(777, ChatSendRequest(message="что делать?", model="sonnet"))
        check("chat_send: очередь (ответ считает фоновый воркер)",
              r["ok"] and r.get("queued") and _chat_wait(777))
        argv = open(cap, encoding="utf-8").read().splitlines()
        check("chat_send: ok + resume сессии заявки", r["ok"] and "--resume" in argv
              and argv[argv.index("--resume") + 1] == sid)
        check("chat_send: запуск из cwd сессии (пересоздан)", os.path.realpath(argv[0]) == os.path.realpath(sess_cwd)
              and os.path.isdir(sess_cwd))

        raw = "\n".join(argv)
        check("chat_send: к сообщению приложена ссылка на заявку + get_issue",
              "#777" in raw and "http://service.example.invalid/issues/777" in raw
              and "Содержимое заявки можно посмотреть инструментом get_issue" in raw)


        check("chat_send: полноправная сессия (bypassPermissions, без strict/allowedTools-замка)",
              "bypassPermissions" in argv and "--strict-mcp-config" not in argv
              and "--allowedTools" not in argv and "--mcp-config" in argv)
        import agent.default_flow as _dfl
        _rmenv = _dfl.build_mcp_config("u", "k", 777, [], dry=True)["mcpServers"]["redmine"]["env"]
        check("chat: build_mcp_config(dry=True) -> RM_DRY=1 (сухой режим доезжает до MCP)",
              _rmenv.get("RM_DRY") == "1")
        check("chat_send: model прокинута", "--model" in argv
              and argv[argv.index("--model") + 1] == "sonnet")

        saved = json.load(open(os.path.join(root, "state", "chats", "777.json")))
        check("chats: история на диске (вопрос+ответ, новый session_id, pending снят)",
              len(saved["messages"]) == 2 and saved["session_id"] == sid2
              and saved["messages"][0]["role"] == "user"
              and not saved["messages"][0].get("pending"))
        hist2 = chats.chat_history(777)
        check("chats: история = разбор агента + переписка", len(hist2["messages"]) == 3)


        r2 = chats.chat_send(888, ChatSendRequest(message="привет", subject="тест"))
        _chat_wait(888)
        argv2 = open(cap, encoding="utf-8").read().splitlines()
        check("chat_send без сессии: новая сессия в стабильном cwd",
              r2["ok"] and "--resume" not in argv2 and os.path.realpath(argv2[0]) == os.path.realpath(chats.CHAT_CWD))


        with open(reply, "w") as f:
            json.dump({"is_error": True, "result": "boom"}, f)
        r3 = chats.chat_send(777, ChatSendRequest(message="ещё раз"))
        _chat_wait(777)
        m3 = json.load(open(os.path.join(root, "state", "chats", "777.json")))["messages"]
        check("chat_send: ошибка CLI -> вопрос сохранён + ответ-ошибка от воркера",
              r3["ok"] and len(m3) == 4
              and m3[-2]["role"] == "user" and m3[-2]["text"] == "ещё раз"
              and not m3[-2].get("pending")
              and m3[-1]["role"] == "ai" and m3[-1].get("error"))
    finally:
        os.environ.pop("DASH_CLAUDE_BIN", None)
        shutil.rmtree(tmp, ignore_errors=True)


def test_chat_pending():


    try:
        import fastapi
    except ImportError:
        print("%-54s SKIP (нет fastapi)" % "chat pending")
        return
    from tools.dashboard.routes import chats
    from tools.dashboard.models import ChatSendRequest
    root = core.ROOT
    with open(os.path.join(root, "config", "secrets.local.json"), "w", encoding="utf-8") as f:
        json.dump({"redmine_url": "http://service.example.invalid", "redmine_api_key": "k"}, f)
    tmp = tempfile.mkdtemp(prefix="wa_test_pend_")
    try:
        chatfile = os.path.join(root, "state", "chats", "889.json")
        mid, reply = os.path.join(tmp, "mid.txt"), os.path.join(tmp, "reply.json")
        fake = os.path.join(tmp, "claude")
        with open(fake, "w") as f:
            f.write('#!/bin/sh\ncat "' + chatfile + '" > "' + mid + '" 2>/dev/null\ncat "' + reply + '"\n')
        os.chmod(fake, 0o755)
        os.environ["DASH_CLAUDE_BIN"] = fake
        with open(reply, "w") as f:
            json.dump({"is_error": False, "result": "готово", "session_id": "s"}, f)
        r = chats.chat_send(889, ChatSendRequest(message="долгий вопрос"))
        _chat_wait(889)
        midtxt = open(mid, encoding="utf-8").read() if os.path.exists(mid) else ""
        check("chat pending: вопрос записан ДО ответа (pending, виден mid-run)",
              '"pending": true' in midtxt and "долгий вопрос" in midtxt)
        m = json.load(open(chatfile))["messages"]
        u = [x for x in m if x["role"] == "user"][-1]
        check("chat pending: после ответа pending снят, ответ дописан",
              r["ok"] and not u.get("pending")
              and m[-1]["role"] == "ai" and m[-1]["text"] == "готово")


        chats._save_chat(890, {"issue_id": 890, "session_id": None, "messages": [
            {"role": "user", "text": "оборванный", "at": "x", "ts": 1, "pending": True}]})
        r2 = chats.chat_send(890, ChatSendRequest(message="новый вопрос"))
        _chat_wait(890)
        m2 = json.load(open(os.path.join(root, "state", "chats", "890.json")))["messages"]
        check("chat pending: осиротевший pending закрыт на следующем send'е",
              r2["ok"] and not m2[0].get("pending") and m2[1].get("error")
              and m2[2]["role"] == "user" and m2[2]["text"] == "новый вопрос"
              and not m2[2].get("pending") and m2[3]["role"] == "ai")
    finally:
        os.environ.pop("DASH_CLAUDE_BIN", None)
        shutil.rmtree(tmp, ignore_errors=True)


def test_chat_attachments():


    try:
        import fastapi
    except ImportError:
        print("%-54s SKIP (нет fastapi)" % "chat attachments")
        return
    from tools.dashboard.routes import chats
    from tools.dashboard.models import ChatSendRequest
    root = core.ROOT
    with open(os.path.join(root, "config", "secrets.local.json"), "w", encoding="utf-8") as f:
        json.dump({"redmine_url": "http://service.example.invalid", "redmine_api_key": "k"}, f)
    tmp = tempfile.mkdtemp(prefix="wa_test_att_")
    try:
        cap, reply = os.path.join(tmp, "cap.txt"), os.path.join(tmp, "reply.json")
        fake = os.path.join(tmp, "claude")


        with open(fake, "w") as f:
            f.write('#!/bin/sh\n{ for a in "$@"; do printf "ARG:%s\\n" "$a"; done; '
                    'for ff in $(find . -type f 2>/dev/null); do '
                    'printf "DISK:%s:%s\\n" "$(basename "$ff")" "$(wc -c < "$ff")"; done; '
                    'cat; } > "' + cap + '"\ncat "' + reply + '"\n')
        os.chmod(fake, 0o755)
        os.environ["DASH_CLAUDE_BIN"] = fake
        with open(reply, "w") as f:
            json.dump({"is_error": False, "result": "посмотрел файлы", "session_id": "s"}, f)
        png = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8z8BQDwAEhQGAhKmMIQ"
               "AAAABJRU5ErkJggg==")
        big = "X" * 300000
        r = chats.chat_send(778, ChatSendRequest(message="глянь", attachments=[
            {"name": "err.log", "text": "DEADLOCK on ITRN\nline2"},
            {"name": "big.log", "text": big},
            {"name": "shot.png", "b64": png}]))
        _chat_wait(778)
        cap_txt = open(cap, encoding="utf-8").read()
        check("chat att: ok, мелкий текст ТОЖЕ пишется на диск (в промпт НЕ вклеивается)",
              r["ok"] and "DISK:err.log:" in cap_txt and "DEADLOCK on ITRN" not in cap_txt)
        check("chat att: все файлы приложены по пути (полноправная сессия читает их сама)",
              "shot.png" in cap_txt and "err.log" in cap_txt and "big.log" in cap_txt)
        check("chat att: крупный текст НЕ вклеен, записан на диск ЦЕЛИКОМ (без усечения)",
              ("X" * 1000) not in cap_txt and bool(re.search(r"DISK:big\.log:\s*300000\b", cap_txt)))
        saved = json.load(open(os.path.join(root, "state", "chats", "778.json")))
        umsg = [m for m in saved["messages"] if m.get("role") == "user"][-1]
        check("chat att: имена вложений сохранены в истории",
              umsg.get("att") == ["err.log", "big.log", "shot.png"])
        leftover = ([d for d in os.listdir(chats.CHAT_CWD) if d.startswith("_wa_att")]
                    if os.path.isdir(chats.CHAT_CWD) else [])
        check("chat att: подкаталог вложений убран из cwd после прогона (изоляция+cleanup)",
              not leftover)

        _df, nm = chats._prepare_attachments([
            {"name": "a.txt", "text": "1"}, {"name": "a.txt", "text": "2"},
            {"name": "bad", "b64": "!!!не base64"}, {"name": "empty"}])
        check("chat att: дедуп одинаковых имён + скип битых/пустых",
              nm == ["a.txt", "a_2.txt"])
    finally:
        os.environ.pop("DASH_CLAUDE_BIN", None)
        shutil.rmtree(tmp, ignore_errors=True)


def test_draft_update_from_chat():


    from tools.dashboard import drafts
    _write_draft(43220, analysis_seconds=600)
    upd = drafts.update_draft_from_chat(43220, "Новый разбор из чата.", session_id="sess-new",
                                        analysis_seconds=1200)
    check("draft update: analysis/comment переписаны, pending, скрины целы, время накоплено",
          upd["analysis"] == "Новый разбор из чата."
          and upd["comment"] == "h3. Разбор:\n\nНовый разбор из чата."
          and upd["status"] == "pending" and upd["session_id"] == "sess-new"
          and upd["analysis_seconds"] == 1800.0
          and [s["sid"] for s in upd["screenshots"]] == ["p1"])
    drafts.save_draft(43221, {"issue_id": 43221, "status": "posted"})
    check("draft update: не-pending или пустой note -> None (не трогаем)",
          drafts.update_draft_from_chat(43221, "x") is None
          and drafts.update_draft_from_chat(43220, "   ") is None
          and drafts.update_draft_from_chat(999999999, "y") is None)
    for iid in (43220, 43221):
        try:
            os.remove(drafts.draft_path(iid))
        except OSError:
            pass
        drafts.clean_shots(iid)


def test_draft_publish():


    from tools.dashboard import drafts
    with open(os.path.join(core.ROOT, "config", "secrets.local.json"), "w", encoding="utf-8") as f:
        json.dump({"redmine_url": "http://service.example.invalid", "redmine_api_key": "k"}, f)
    saved_status = core.agent_status
    saved_rc = drafts.rmc.RedmineClient

    class FakeRC:
        def __init__(self, url, key):
            pass

        def upload(self, data, filename):
            return "tok-" + filename

        def add_note(self, iid, note, uploads=None, private=True):
            self.posted.append((iid, note, uploads, private))

        def create_time_entry(self, iid, hours, comments=""):
            self.times.append((iid, hours, comments))
    FakeRC.posted, FakeRC.times = [], []
    try:

        core.agent_status = lambda: {"dry_run": False}
        r0 = drafts.publish_draft(999001)
        check("publish: нет черновика -> ok=False, reason=no_draft, posted=False",
              r0["ok"] is False and r0["reason"] == "no_draft" and r0["posted"] is False)


        core.agent_status = lambda: {"dry_run": True}
        _write_draft(999002, analysis_seconds=3600)
        rd = drafts.publish_draft(999002)
        check("publish dry: ok, posted=False, dry, черновик pending, время не списано",
              rd["ok"] and rd["posted"] is False and rd.get("dry") and "DRY-RUN" in rd["text"]
              and drafts.load_draft(999002)["status"] == "pending"
              and rd.get("time_logged") is None)


        core.agent_status = lambda: {"dry_run": False}
        drafts.rmc.RedmineClient = FakeRC
        FakeRC.posted, FakeRC.times = [], []
        _write_draft(999003, analysis_seconds=1830)
        rp = drafts.publish_draft(999003)
        check("publish боевой: add_note(private, comment+!img!) + posted + время списано",
              rp["ok"] and rp["posted"] and len(FakeRC.posted) == 1 and FakeRC.posted[0][3] is True
              and "!p1.png!" in FakeRC.posted[0][1]
              and drafts.load_draft(999003)["status"] == "posted"
              and FakeRC.times == [(999003, 0.51, "Разбор заявки")]
              and rp["time_logged"] == 0.51, str(FakeRC.times))


        FakeRC.posted, FakeRC.times = [], []
        rp2 = drafts.publish_draft(999003)
        check("publish posted -> ok=False reason=already_posted, коммент НЕ перепостит",
              rp2["ok"] is False and rp2["reason"] == "already_posted"
              and not FakeRC.posted and not FakeRC.times)


        class FailTimeRC(FakeRC):
            def create_time_entry(self, iid, hours, comments=""):
                raise RuntimeError("403 Forbidden")
        FailTimeRC.posted, FailTimeRC.times = [], []
        drafts.rmc.RedmineClient = FailTimeRC
        _write_draft(999004, analysis_seconds=3600)
        rf = drafts.publish_draft(999004)
        check("publish: ошибка времени проглочена -> posted всё равно, приписка в ответе",
              rf["ok"] and rf["posted"] and rf["time_logged"] is None
              and "время не списалось" in rf["text"]
              and "!p1.png!" in FailTimeRC.posted[0][1]
              and drafts.load_draft(999004)["status"] == "posted")


        FakeRC.posted, FakeRC.times = [], []
        drafts.rmc.RedmineClient = FakeRC
        _write_draft(999005)
        rn = drafts.publish_draft(999005)
        check("publish: analysis_seconds нет -> коммент есть, время не списываем",
              rn["posted"] and rn["time_logged"] is None and FakeRC.times == []
              and len(FakeRC.posted) == 1)
    finally:
        core.agent_status = saved_status
        drafts.rmc.RedmineClient = saved_rc
        for iid in (999002, 999003, 999004, 999005):
            try:
                os.remove(drafts.draft_path(iid))
            except OSError:
                pass
            drafts.clean_shots(iid)


def test_draft_publish_endpoint():


    try:
        import fastapi
        from tools.dashboard.routes import chats
        from tools.dashboard.routes import drafts as drafts_routes
    except ImportError:
        print("%-54s SKIP (нет fastapi)" % "draft publish endpoint")
        return
    from tools.dashboard import drafts
    with open(os.path.join(core.ROOT, "config", "secrets.local.json"), "w", encoding="utf-8") as f:
        json.dump({"redmine_url": "http://service.example.invalid", "redmine_api_key": "k"}, f)
    saved_status = core.agent_status
    saved_rc = drafts.rmc.RedmineClient

    class FakeRC:
        def __init__(self, url, key):
            pass

        def upload(self, data, filename):
            return "tok"

        def add_note(self, iid, note, uploads=None, private=True):
            posted.append(iid)

        def create_time_entry(self, iid, hours, comments=""):
            pass
    posted = []
    try:
        core.agent_status = lambda: {"dry_run": False}

        r404 = drafts_routes.draft_publish(998001)
        check("publish endpoint: нет черновика -> 404",
              getattr(r404, "status_code", None) == 404)


        drafts.rmc.RedmineClient = FakeRC
        _write_draft(998002)
        res = drafts_routes.draft_publish(998002)
        hist = chats.chat_history(998002)
        check("publish endpoint: боевой -> ok/posted + «Опубликовано ✓» в чате заявки",
              isinstance(res, dict) and res["ok"] and res["posted"] and posted == [998002]
              and any("Опубликовано ✓" in m.get("text", "")
                      for m in hist["messages"] if m.get("role") == "ai"))


        res2 = drafts_routes.draft_publish(998002)
        check("publish endpoint: уже опубликован -> ok=False reason=already_posted (не 404)",
              isinstance(res2, dict) and res2["ok"] is False
              and res2["reason"] == "already_posted")
    finally:
        core.agent_status = saved_status
        drafts.rmc.RedmineClient = saved_rc
        try:
            os.remove(drafts.draft_path(998002))
        except OSError:
            pass
        drafts.clean_shots(998002)
        try:
            os.remove(os.path.join(core.ROOT, "state", "chats", "998002.json"))
        except OSError:
            pass


def test_opus_post_approval():


    from agent.orchestrator import Agent, _TicketDefer
    tmp = tempfile.mkdtemp(prefix="wa_test_post_")
    try:
        posted, recs = [], []
        f = types.SimpleNamespace()
        f.root = tmp
        f.dry_run = False
        f.redmine = types.SimpleNamespace(
            add_note=lambda iid, text, private=True: posted.append((iid, text, private)))
        f.journal = types.SimpleNamespace(record=lambda *a, **k: recs.append((a, k)))
        f.log = types.SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None)
        post = types.MethodType(Agent._handle_opus_post, f)
        base = {"pipe": "opus", "stage": "post", "draft": "h3. Разбор\nSELECT 1", "confidence": "high"}

        try:
            post(dict(base, issue_id=501), 501, "тема", "default-501", "pending")
            check("opus-post pending -> defer", False)
        except _TicketDefer:
            check("opus-post pending -> defer", True)

        approvals.save(tmp, 501, dict(base, issue_id=501, status="approved", decided_at="now"))
        post(approvals.load(tmp, 501), 501, "тема", "default-501", "approved")
        check("opus-post approved -> приватный коммент опубликован + очищено + default_done",
              posted == [(501, "h3. Разбор\nSELECT 1", True)] and approvals.load(tmp, 501) is None
              and any(a[0][1] == "default_done" for a in recs))

        posted.clear(); recs.clear()
        approvals.save(tmp, 502, dict(base, issue_id=502, status="ignore"))
        post(approvals.load(tmp, 502), 502, "тема", "default-502", "ignore")
        check("opus-post ignore -> НЕ публикуем + очищено + opus_post_declined",
              not posted and approvals.load(tmp, 502) is None
              and any(a[0][1] == "opus_post_declined" for a in recs))

        posted.clear(); f.dry_run = True
        approvals.save(tmp, 503, dict(base, issue_id=503, status="approved"))
        post(approvals.load(tmp, 503), 503, "тема", "default-503", "approved")
        check("opus-post dry_run -> НЕ публикуем (симуляция)",
              not posted and approvals.load(tmp, 503) is None)
        f.dry_run = False

        posted.clear()
        approvals.save(tmp, 504, dict(base, issue_id=504, draft="   ", status="approved"))
        post(approvals.load(tmp, 504), 504, "тема", "default-504", "approved")
        check("opus-post пустой черновик -> НЕ публикуем", not posted and approvals.load(tmp, 504) is None)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_mcp_draft_stage():


    import agent.redmine_mcp as mcp
    tmp = tempfile.mkdtemp(prefix="wa_test_mcp_")
    draft = os.path.join(tmp, "d.json")
    saved = (mcp._DRAFT, mcp._SOURCE, mcp._LOG)
    posted = []
    mcp._rc.add_note = lambda *a, **k: posted.append(a)
    try:
        mcp._DRAFT, mcp._SOURCE, mcp._LOG = draft, 77, ""
        out = mcp._tool_post_private_note({"note": "чек SELECT 1", "confidence": "low"})
        d = json.load(open(draft, encoding="utf-8"))
        check("MCP draft-режим: черновик записан, коммент НЕ опубликован",
              d["note"] == "чек SELECT 1" and d["confidence"] == "low" and d["issue_id"] == 77
              and "ОДОБРЕНИЕ" in out and not posted)
    finally:
        mcp._DRAFT, mcp._SOURCE, mcp._LOG = saved
        shutil.rmtree(tmp, ignore_errors=True)


def test_poll_mail_outage_decoupled():


    import agent.orchestrator as o
    from agent.orchestrator import Agent
    saved_tr = o.tr
    o.tr = types.SimpleNamespace(status=lambda *a, **k: None, trace=lambda *a, **k: None)
    try:
        f = types.SimpleNamespace()
        f.cursor = 100
        f.mode = "DRY-RUN"
        f.cfg = {}
        f.log = types.SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None,
                                      exception=lambda *a, **k: None)
        f._shift_handoff = lambda: None
        f._check_uidvalidity = lambda: None
        f.mailer = types.SimpleNamespace(
            fetch_new=lambda *a, **k: (_ for _ in ()).throw(o.imaplib.IMAP4.abort("dns down")))
        state = {"poll178": False, "saved": None}
        f._poll_178 = lambda stats: state.__setitem__("poll178", True)
        f._save_cursor = lambda uid: state.__setitem__("saved", uid)
        types.MethodType(Agent.poll, f)()
        check("обрыв IMAP: проход не упал + тикет-сторона (_poll_178) отработала",
              state["poll178"] and state["saved"] is None and f.cursor == 100)
    finally:
        o.tr = saved_tr


def test_ticket_info_card():


    from tools.dashboard import ticket_info as ti
    issue = {
        "id": 10101, "subject": "Зависли блокировки", "is_private": False,
        "status": {"id": 2, "name": "В работе"}, "priority": {"id": 5, "name": "Срочная"},
        "project": {"id": 9, "name": "Клиент B - Т/П"}, "tracker": {"id": 3, "name": "Поддержка"},
        "author": {"id": 11, "name": "Engineer Example"}, "assigned_to": {"id": 22, "name": "Инженер"},
        "created_on": "2026-07-15T08:00:00Z", "updated_on": "2026-07-15T09:30:00Z",
        "description": "wait_duration_ms растёт",
        "journals": [
            {"id": 501, "user": {"id": 11, "name": "Engineer Example"},
             "created_on": "2026-07-15T08:10:00Z",
             "notes": "видим по мониторингу", "private_notes": False, "details": []},
            {"user": {"id": 22, "name": "Инженер"}, "created_on": "2026-07-15T08:20:00Z",
             "notes": "", "private_notes": False, "details": [
                 {"property": "attr", "name": "status_id", "old_value": "1", "new_value": "2"},
                 {"property": "attr", "name": "assigned_to_id", "old_value": None,
                  "new_value": "22"}]},
            {"user": {"id": 33, "name": "Бот"}, "created_on": "2026-07-15T08:25:00Z",
             "notes": "приватный разбор ИИ", "private_notes": True, "details": []},

            {"user": {"id": 11, "name": "Engineer Example"}, "created_on": "2026-07-15T08:30:00Z",
             "notes": "", "private_notes": False, "details": [
                 {"property": "cf", "name": "7", "old_value": "", "new_value": "x"}]},
        ],
        "attachments": [{"id": 9001, "filename": "deadlock.png", "filesize": 12345,
                         "content_type": "image/png",
                         "created_on": "2026-07-15T08:11:00Z",
                         "author": {"id": 11, "name": "Engineer Example"}}],
    }
    card = ti.build_card(issue, statuses={"1": "Новая", "2": "В работе"}, priorities={})
    check("ticket_info: шапка (статус/приоритет/автор/назначенец/даты)",
          card["id"] == 10101 and card["status"] == "В работе" and card["priority"] == "Срочная"
          and card["author"] == "Engineer Example" and card["assigned_to"] == "Инженер"
          and card["project"] == "Клиент B - Т/П" and card["created_on"].startswith("2026-07-15"))
    check("ticket_info: пустая журнальная запись (cf) выброшена, остальные на месте",
          len(card["journals"]) == 3 and card["journals"][0]["notes"] == "видим по мониторингу")
    j2 = card["journals"][1]
    check("ticket_info: details -> «статус: X → Y» + назначенец по имени из заявки",
          j2["changes"] == ["статус: Новая → В работе", "назначенец: (снят) → Инженер"])
    check("ticket_info: private_notes помечены",
          card["journals"][2]["private"] is True and card["journals"][0]["private"] is False)
    check("ticket_info: вложения (id+имя+размер+content_type+автор — id/тип нужны "
          "прокси картинок)",
          card["attachments"] == [{"id": 9001, "filename": "deadlock.png",
                                   "filesize": 12345, "content_type": "image/png",
                                   "at": "2026-07-15T08:11:00Z", "author": "Engineer Example"}])
    check("ticket_info: journal id пробрасывается (ключ свёрнутости в GUI)",
          card["journals"][0]["id"] == 501 and card["journals"][1]["id"] is None)

    raw = ti.format_change({"property": "attr", "name": "status_id",
                            "old_value": "8", "new_value": "9"}, {}, {}, {})
    check("ticket_info: без справочника статусов строка не падает (сырые id)",
          raw == "статус: 8 → 9")
    check("ticket_info: вложение/связь/шум-cf в details",
          ti.format_change({"property": "attachment", "name": "1", "new_value": "a.log"},
                           {}, {}, {}) == "вложение: a.log"
          and ti.format_change({"property": "relation", "name": "relates", "new_value": "5"},
                               {}, {}, {}) == "связь с #5"
          and ti.format_change({"property": "cf", "name": "7", "new_value": "x"},
                               {}, {}, {}) is None)


def test_ticket_info_endpoint():


    from tools.dashboard import ticket_info as ti
    with open(core.SECRETS_FILE, "w", encoding="utf-8") as f:
        json.dump({"redmine_url": "http://service.example.invalid/", "redmine_api_key": "k"}, f)
    calls = {"n": 0}

    class FakeRC:
        def __init__(self, url, key):
            calls["url"] = url

        def get_issue(self, iid, include="journals,attachments"):
            calls["n"] += 1
            return {"id": iid, "subject": "тема", "status": {"name": "Новая"},
                    "journals": [], "attachments": []}

        def issue_statuses(self):
            return [{"id": 1, "name": "Новая"}]

        def issue_priorities(self):
            return []

    saved_rc = ti.rmc.RedmineClient
    ti.rmc.RedmineClient = FakeRC
    ti._cache.clear()
    ti._lookups.update(ts=0, statuses={}, priorities={})
    try:
        r1 = ti.get_info(555001)
        r2 = ti.get_info(555001)
        check("ticket_info: ok-ответ + redmine_url без хвостового / + кэш 30с (1 fetch)",
              r1["ok"] and r1["issue"]["subject"] == "тема" and r1["redmine_url"] == "http://service.example.invalid"
              and r2 is r1 and calls["n"] == 1)

        class BoomRC(FakeRC):
            def get_issue(self, iid, include="journals,attachments"):
                raise OSError("connection refused")

        ti.rmc.RedmineClient = BoomRC
        e1 = ti.get_info(555002)
        check("ticket_info: ошибка Redmine -> ok=False с текстом",
              e1["ok"] is False and "connection refused" in e1["error"])
        ti._cache[555002] = (time.time() - ti.ERR_TTL - 1, e1)
        ti.rmc.RedmineClient = FakeRC
        e2 = ti.get_info(555002)
        check("ticket_info: протухшая ошибка перезапрашивается и оживает",
              e2["ok"] is True)

        with open(core.SECRETS_FILE, "w", encoding="utf-8") as f:
            json.dump({}, f)
        ti._cache.clear()
        check("ticket_info: без secrets -> ok=False (не бросает)",
              ti.get_info(555003)["ok"] is False)
    finally:
        ti.rmc.RedmineClient = saved_rc
        ti._cache.clear()


def test_ticket_attachment_proxy():


    from tools.dashboard import ticket_info as ti
    with open(core.SECRETS_FILE, "w", encoding="utf-8") as f:
        json.dump({"redmine_url": "http://service.example.invalid", "redmine_api_key": "k"}, f)

    class AttRC:
        def __init__(self, url, key):
            pass

        def get_issue(self, iid, include="journals,attachments"):
            return {"id": iid, "subject": "с вложением", "journals": [],
                    "attachments": [
                        {"id": 9001, "filename": "скрин ошибки.png", "filesize": 10,
                         "content_type": "image/png"},
                        {"id": 9002, "filename": "dump.html", "filesize": 20,
                         "content_type": "text/html"}]}

        def issue_statuses(self):
            return []

        def issue_priorities(self):
            return []

    saved_rc = ti.rmc.RedmineClient
    saved_open = ti.urllib.request.urlopen
    ti.rmc.RedmineClient = AttRC
    ti._cache.clear()
    opened = {}

    class FakeHTTP(io.BytesIO):
        headers = {"Content-Type": "image/png"}

        def get(self, k):
            return self.headers.get(k)

    def fake_urlopen(req, timeout=0):
        opened["url"] = req.full_url
        opened["key"] = req.headers.get("X-redmine-api-key")
        r = FakeHTTP(b"PNGDATA")
        r.headers = {"Content-Type": "image/png"}
        return r

    ti.urllib.request.urlopen = fake_urlopen
    try:
        check("att-прокси: чужой attachment_id -> None (принадлежность заявке)",
              ti.find_attachment(556001, 777777) is None
              and ti.find_attachment(556001, 9001)["filename"] == "скрин ошибки.png")
        got = ti.open_attachment(556001, 9001)
        check("att-прокси: свой id -> поток + content-type + ключ + quoted имя в URL",
              got is not None and got[1] == "image/png" and got[2] == "скрин ошибки.png"
              and opened["key"] == "k"
              and opened["url"] == "http://service.example.invalid/attachments/download/9001/"
                  + "%D1%81%D0%BA%D1%80%D0%B8%D0%BD%20%D0%BE%D1%88%D0%B8%D0%B1%D0%BA%D0%B8.png")
        check("att-прокси: чужой id -> open_attachment None",
              ti.open_attachment(556001, 777777) is None)
        try:
            from fastapi import HTTPException
            from tools.dashboard.routes import tickets as rt
        except ImportError:
            print("%-54s SKIP (нет fastapi)" % "att-прокси: роут")
            return
        code = None
        try:
            rt.ticket_attachment(556001, 777777)
        except HTTPException as e:
            code = e.status_code
        check("att-прокси: роут отдаёт 404 на чужой id", code == 404)
        r = rt.ticket_attachment(556001, 9001)
        check("att-прокси: роут: image/* inline + Cache-Control private + nosniff",
              r.media_type == "image/png"
              and r.headers.get("cache-control") == "private, max-age=3600"
              and r.headers.get("x-content-type-options") == "nosniff"
              and r.headers.get("content-disposition", "").startswith("inline;"))

        def fake_urlopen_html(req, timeout=0):
            r = FakeHTTP(b"<html>")
            r.headers = {"Content-Type": "text/html"}
            return r

        ti.urllib.request.urlopen = fake_urlopen_html
        r2 = rt.ticket_attachment(556001, 9002)
        check("att-прокси: не-картинка -> Content-Disposition attachment (без inline-XSS)",
              r2.headers.get("content-disposition", "").startswith("attachment;"))


        def fake_urlopen_svg(req, timeout=0):
            rr = FakeHTTP(b"<svg xmlns='http://www.w3.org/2000/svg'><script>x()</script></svg>")
            rr.headers = {"Content-Type": "image/svg+xml"}
            return rr

        ti.urllib.request.urlopen = fake_urlopen_svg
        r3 = rt.ticket_attachment(556001, 9001)
        check("att-прокси: SVG НЕ inline (image/*, но исполняемый) -> attachment",
              r3.headers.get("content-disposition", "").startswith("attachment;"),
              r3.headers.get("content-disposition", ""))
    finally:
        ti.rmc.RedmineClient = saved_rc
        ti.urllib.request.urlopen = saved_open
        ti._cache.clear()


def test_stats_pending_excludes_reviewing():


    feed = {"mails": [], "tickets": [], "redmine_url": "",
            "approvals": [
                {"issue_id": 1, "status": "pending", "stage": "write"},
                {"issue_id": 2, "status": "pending", "stage": "reviewing"},
                {"issue_id": 3, "status": "pending", "stage": "branch"},
            ]}
    check("stats.pending исключает reviewing (2 actionable из 3 pending)",
          core.stats24(feed)["pending"] == 2)


def _hz_wait(iid, timeout=10.0):


    from tools.dashboard.routes import humanize as _hz
    t0 = time.time()
    while time.time() - t0 < timeout:
        if not _hz._is_active(iid):
            return True
        time.sleep(0.02)
    return False


_HZ_ANALYSIS = ("Всплеск блокировок по таблице LOTXLOCXID, wait 5000 мс.\n\n"
                "```sql\nSELECT 1\n```\n\nНужно перезапустить джоб.")
_HZ_COMMENT = "h3. Разбор:\n\n" + _HZ_ANALYSIS


def test_humanize_worker():


    try:
        import fastapi
        from tools.dashboard.routes import humanize as hz
        from tools.dashboard.routes import chats
    except ImportError:
        print("%-54s SKIP (нет fastapi)" % "humanize worker")
        return
    from tools.dashboard import drafts
    saved_run, saved_cfg = hz._run_model, hz._cfg
    hz._cfg = lambda: {"model": "sonnet", "effort": "medium", "timeout": 300,
                       "lint_max_retries": 2, "max_examples": 8}
    try:

        _write_draft(45001, analysis=_HZ_ANALYSIS, comment=_HZ_COMMENT)
        clean = "Блокировки на LOTXLOCXID, ждём 5000 мс.\n\n⟦CODE_1⟧\n\nПерезапусти джоб."
        hz._run_model = lambda prompt, model, effort, timeout: (clean, None)
        hz._humanize_worker(45001)
        d = drafts.load_draft(45001)
        check("humanize success: analysis/comment переписаны, comment БЕЗ h3, SQL восстановлен",
              d["analysis"].startswith("Блокировки на LOTXLOCXID")
              and "```sql\nSELECT 1\n```" in d["analysis"]
              and d["comment"] == d["analysis"] and not d["comment"].startswith("h3")
              and d["humanize"]["status"] == "done" and d["humanize"]["attempts"] == 1)
        check("humanize success: оригинал в *_original + линт-бейджи (dict) есть",
              d["analysis_original"] == _HZ_ANALYSIS and d["comment_original"] == _HZ_COMMENT
              and isinstance(d["humanize"].get("lint"), dict)
              and "cliches" in d["humanize"]["lint"])


        _write_draft(45002, analysis=_HZ_ANALYSIS, comment=_HZ_COMMENT)
        bad = "Блокировки на LOTXLOCXID, ждём 9999 мс.\n\n⟦CODE_1⟧\n\nПерезапусти джоб."
        hz._run_model = lambda prompt, model, effort, timeout: (bad, None)
        hz._humanize_worker(45002)
        d2 = drafts.load_draft(45002)
        ch2 = chats._load_chat(45002) or {}
        check("humanize fact-fail: черновик НЕ изменён, humanize.status=error",
              d2["analysis"] == _HZ_ANALYSIS and d2["comment"] == _HZ_COMMENT
              and d2["humanize"]["status"] == "error" and "analysis_original" not in d2)
        check("humanize fact-fail: уведомление в чат (role=agent, «Humanize не прошёл»)",
              any(m.get("role") == "agent" and "Humanize не прошёл" in m.get("text", "")
                  for m in ch2.get("messages", [])))


        _write_draft(45003, analysis=_HZ_ANALYSIS, comment=_HZ_COMMENT)
        drop = "Блокировки на LOTXLOCXID, ждём 5000 мс. Перезапусти джоб."
        hz._run_model = lambda prompt, model, effort, timeout: (drop, None)
        hz._humanize_worker(45003)
        d3 = drafts.load_draft(45003)
        check("humanize restore-fail: плейсхолдер потерян -> оригинал цел, status=error",
              d3["analysis"] == _HZ_ANALYSIS and d3["humanize"]["status"] == "error"
              and "код" in d3["humanize"]["error"])


        _write_draft(45004, analysis=_HZ_ANALYSIS, comment=_HZ_COMMENT)
        cliche = ("Таким образом, блокировки на LOTXLOCXID, ждём 5000 мс.\n\n⟦CODE_1⟧\n\n"
                  "Стоит отметить, перезапусти джоб.")
        prompts = []

        def _cliche_run(prompt, model, effort, timeout):
            prompts.append(prompt)
            return cliche, None
        hz._run_model = _cliche_run
        hz._humanize_worker(45004)
        d4 = drafts.load_draft(45004)
        ch4 = chats._load_chat(45004) or {}
        check("humanize retry-fail: 1+lint_max_retries прогонов, оригинал цел, status=error",
              len(prompts) == 3 and d4["analysis"] == _HZ_ANALYSIS
              and d4["humanize"]["status"] == "error" and d4["humanize"]["attempts"] == 3
              and "клише" in d4["humanize"]["error"])
        check("humanize retry-fail: на ретрае в промпт добавлен фидбек + уведомление в чат",
              "остались" in prompts[-1]
              and any("Humanize не прошёл" in m.get("text", "")
                      for m in ch4.get("messages", [])))


        star = ("Проверил количество строк.\n\n"
                "```sql\nSELECT *, COUNT(*) FROM ORDERS WHERE qty -> 0\n```\n\nВсё ок.")
        _write_draft(45005, analysis=star, comment="h3. Разбор:\n\n" + star)
        star_clean = "Проверил число строк.\n\n⟦CODE_1⟧\n\nВсё ок."
        hz._run_model = lambda prompt, model, effort, timeout: (star_clean, None)
        hz._humanize_worker(45005)
        d5 = drafts.load_draft(45005)
        check("humanize: SQL со * и -> НЕ даёт ложных марок -> УСПЕХ (линт по frozen)",
              d5["humanize"]["status"] == "done"
              and "SELECT *, COUNT(*)" in d5["analysis"] and "qty -> 0" in d5["analysis"])


        _write_draft(45006, analysis=_HZ_ANALYSIS, comment=_HZ_COMMENT)
        fx_prompts, fx_calls = [], [0]

        def _fact_recover(prompt, model, effort, timeout):
            fx_prompts.append(prompt)
            fx_calls[0] += 1
            if fx_calls[0] == 1:
                return "Блокировки, ждём 5000 мс.\n\n⟦CODE_1⟧\n\nПерезапусти джоб.", None
            return "Блокировки на LOTXLOCXID, ждём 5000 мс.\n\n⟦CODE_1⟧\n\nПерезапусти.", None
        hz._run_model = _fact_recover
        hz._humanize_worker(45006)
        d6 = drafts.load_draft(45006)

        _write_draft(45009, analysis=_HZ_ANALYSIS, comment=_HZ_COMMENT)

        def _slow_then_edit(prompt, model, effort, timeout):
            d_now = drafts.load_draft(45009)
            d_now["analysis"] = "СВЕЖАЯ правка из чата"
            drafts.save_draft(45009, d_now)
            return "Блокировки на LOTXLOCXID, ждём 5000 мс.\n\n⟦CODE_1⟧\n\nПерезапусти джоб.", None
        hz._run_model = _slow_then_edit
        hz._humanize_worker(45009)
        d9 = drafts.load_draft(45009)
        check("humanize конфликт: правка из чата НЕ затирается результатом humanize",
              d9["analysis"] == "СВЕЖАЯ правка из чата"
              and d9["humanize"]["status"] == "error"
              and "изменил" in d9["humanize"]["error"]
              and "analysis_original" not in d9, str(d9.get("humanize")))

        check("humanize факт-ретрай: 1й выронил факт -> ретрай с списком -> УСПЕХ (attempts=2)",
              d6["humanize"]["status"] == "done" and d6["humanize"]["attempts"] == 2
              and "LOTXLOCXID" in d6["analysis"]
              and "LOTXLOCXID" in fx_prompts[-1])


        hz._cfg = lambda: {"model": "sonnet", "effort": "medium", "timeout": 300,
                           "lint_max_retries": 2, "max_examples": 8, "brevity": 0.85}
        long_cand = ("Всплеск блокировок по таблице LOTXLOCXID, ожидание 5000 мс, и это тянется "
                     "довольно долго уже некоторое заметное время подряд.\n\n⟦CODE_1⟧\n\n"
                     "Нужно перезапустить джоб, иначе само ничего не разрешится и придётся "
                     "вмешиваться руками снова.")
        short_cand = "Блокировки на LOTXLOCXID, ждём 5000 мс.\n\n⟦CODE_1⟧\n\nПерезапусти джоб."
        _write_draft(45007, analysis=_HZ_ANALYSIS, comment=_HZ_COMMENT)
        br_prompts, br_calls = [], [0]

        def _brev_run(prompt, model, effort, timeout):
            br_prompts.append(prompt)
            br_calls[0] += 1
            return (long_cand if br_calls[0] == 1 else short_cand), None
        hz._run_model = _brev_run
        hz._humanize_worker(45007)
        d7 = drafts.load_draft(45007)
        check("humanize краткость: длинный 1й -> ретрай «СОКРАТИ» -> короткий -> УСПЕХ (attempts=2)",
              d7["humanize"]["status"] == "done" and d7["humanize"]["attempts"] == 2
              and d7["analysis"].startswith("Блокировки на LOTXLOCXID")
              and "СОКРАТИ" in br_prompts[-1])


        _write_draft(45008, analysis=_HZ_ANALYSIS, comment=_HZ_COMMENT)
        hz._run_model = lambda prompt, model, effort, timeout: (long_cand, None)
        hz._humanize_worker(45008)
        d8 = drafts.load_draft(45008)
        check("humanize краткость: упорно длинный -> длина НЕ валит -> ПРИНЯТ (done, attempts=3)",
              d8["humanize"]["status"] == "done" and d8["humanize"]["attempts"] == 3
              and d8["analysis"].startswith("Всплеск блокировок по таблице LOTXLOCXID"))
    finally:
        hz._run_model, hz._cfg = saved_run, saved_cfg
        for iid in (45001, 45002, 45003, 45004, 45005, 45006, 45007, 45008, 45009):
            try:
                os.remove(drafts.draft_path(iid))
            except OSError:
                pass
            drafts.clean_shots(iid)
            try:
                os.remove(os.path.join(core.ROOT, "state", "chats", "%d.json" % iid))
            except OSError:
                pass


def test_humanize_endpoints():


    try:
        import fastapi
        from tools.dashboard.routes import humanize as hz
    except ImportError:
        print("%-54s SKIP (нет fastapi)" % "humanize endpoints")
        return
    from tools.dashboard import drafts
    saved_run, saved_cfg = hz._run_model, hz._cfg
    hz._cfg = lambda: {"model": "sonnet", "effort": "medium", "timeout": 300,
                       "lint_max_retries": 2, "max_examples": 8}


    hz._run_model = lambda prompt, model, effort, timeout: (
        "Блокировки на LOTXLOCXID, ждём 5000 мс.\n\n⟦CODE_1⟧\n\nПерезапусти джоб.", None)
    try:
        check("humanize endpoint: нет черновика -> 404",
              getattr(hz.humanize_start(46000), "status_code", None) == 404)
        _write_draft(46001, status="posted")
        check("humanize endpoint: не pending -> 400",
              getattr(hz.humanize_start(46001), "status_code", None) == 400)


        _write_draft(46002, analysis=_HZ_ANALYSIS, comment=_HZ_COMMENT,
                     humanize={"status": "running"})
        ro = hz.humanize_start(46002)
        _hz_wait(46002)
        check("humanize endpoint: осиротевший running (не в active) -> перезапуск, не 409",
              isinstance(ro, dict) and ro.get("ok") and ro.get("status") == "running")

        _write_draft(46003)
        hz._active.add(46003)
        try:
            r409b = hz.humanize_start(46003)
        finally:
            hz._active.discard(46003)
        check("humanize endpoint: issue в active set (живой воркер) -> 409",
              getattr(r409b, "status_code", None) == 409)


        _write_draft(46004, analysis=_HZ_ANALYSIS, comment=_HZ_COMMENT)
        clean = "Блокировки на LOTXLOCXID, ждём 5000 мс.\n\n⟦CODE_1⟧\n\nПерезапусти джоб."
        hz._run_model = lambda prompt, model, effort, timeout: (clean, None)
        rs = hz.humanize_start(46004)
        ok_wait = _hz_wait(46004)
        d = drafts.load_draft(46004)
        check("humanize endpoint: start -> {ok,running} + воркер довёл до done",
              rs.get("ok") and rs.get("status") == "running" and ok_wait
              and d["humanize"]["status"] == "done" and d["analysis"].startswith("Блокировки"))

        rv = hz.humanize_revert(46004)
        d2 = drafts.load_draft(46004)
        check("humanize revert: оригинал восстановлен, status=idle, *_original очищены",
              rv.get("ok") and d2["analysis"] == _HZ_ANALYSIS and d2["comment"] == _HZ_COMMENT
              and d2["humanize"]["status"] == "idle" and "analysis_original" not in d2)
        rn = hz.humanize_revert(46004)
        check("humanize revert: нет оригинала -> nothing_to_revert",
              rn.get("ok") is False and rn.get("reason") == "nothing_to_revert")
    finally:
        hz._run_model, hz._cfg = saved_run, saved_cfg
        for iid in (46001, 46002, 46003, 46004):
            try:
                os.remove(drafts.draft_path(iid))
            except OSError:
                pass
            drafts.clean_shots(iid)
            try:
                os.remove(os.path.join(core.ROOT, "state", "chats", "%d.json" % iid))
            except OSError:
                pass


def test_humanize_chat_reset():


    from tools.dashboard import drafts
    _write_draft(47001, analysis="Хуманизированный текст.", comment="Хуманизированный текст.",
                 analysis_original="Оригинал разбора.",
                 comment_original="h3. Разбор:\n\nОригинал разбора.",
                 humanize={"status": "done", "attempts": 1, "lint": {"cliches": 0}})
    m = drafts.draft_message(47001, drafts.load_draft(47001))
    check("humanize draft_message: humanize/original проброшены в сообщение чата",
          m["humanize"]["status"] == "done" and m["original"] == "Оригинал разбора.")
    upd = drafts.update_draft_from_chat(47001, "Совсем новый разбор из чата.")
    check("humanize chat-reset: правка из чата чистит humanize и *_original",
          upd["analysis"] == "Совсем новый разбор из чата."
          and "humanize" not in upd and "analysis_original" not in upd
          and "comment_original" not in upd)
    m2 = drafts.draft_message(47001, upd)
    check("humanize draft_message: после сброса humanize/original -> None",
          m2["humanize"] is None and m2["original"] is None)
    try:
        os.remove(drafts.draft_path(47001))
    except OSError:
        pass
    drafts.clean_shots(47001)


def test_redmine_accounts_core():


    from agent import redmine_client as rmc
    saved = open(core.SECRETS_FILE, encoding="utf-8").read() \
        if os.path.exists(core.SECRETS_FILE) else None
    saved_client = rmc.RedmineClient
    try:
        with open(core.SECRETS_FILE, "w", encoding="utf-8") as f:
            json.dump({"redmine_url": "http://service.example.invalid",
                       "redmine_accounts": {
                           "maintainer": {"api_key": "keyKKKK1111", "user_id": 1, "label": "Инженер"},
                           "bot": {"api_key": "keyBBBB2222", "user_id": 900}},
                       "redmine_active": "maintainer"}, f)

        accs = core.redmine_accounts()
        blob = json.dumps(accs, ensure_ascii=False)
        check("аккаунты: список маскирует токены (сырых ключей в выдаче НЕТ)",
              "keyKKKK1111" not in blob and "keyBBBB2222" not in blob
              and all(a["key_masked"].startswith("••••") for a in accs))
        check("аккаунты: активный помечен (maintainer), user_id виден",
              next(a for a in accs if a["name"] == "maintainer")["active"] is True
              and next(a for a in accs if a["name"] == "bot")["active"] is False
              and next(a for a in accs if a["name"] == "maintainer")["user_id"] == 1)

        ok, _m = core.set_redmine_active("bot")
        a2 = rmc.resolve_account(json.load(open(core.SECRETS_FILE, encoding="utf-8")))
        check("аккаунты: переключение по ИМЕНИ -> резолвится новый токен и user_id",
              ok and a2["name"] == "bot" and a2["api_key"] == "keyBBBB2222" and a2["user_id"] == 900)

        bad_ok, bad_msg = core.set_redmine_active("нет-такого")
        check("аккаунты: переключение на несуществующий -> отказ, активный не сменился",
              not bad_ok and "не найден" in bad_msg
              and rmc.resolve_account(json.load(open(core.SECRETS_FILE, encoding="utf-8")))["name"] == "bot")


        class _FakeRC:
            def __init__(self, url, key):
                self.key = key

            def current_user(self):
                if self.key == "keyNEW3333":
                    return {"id": 555, "login": "newbie", "name": "Новый Пользователь"}
                raise OSError("401 неклиент B токен")
        rmc.RedmineClient = _FakeRC
        ok3, msg3 = core.save_redmine_account("newbie", api_key="keyNEW3333", make_active=True)
        sec3 = json.load(open(core.SECRETS_FILE, encoding="utf-8"))
        check("аккаунты: добавление токена САМО проставляет user_id (/users/current.json)",
              ok3 and sec3["redmine_accounts"]["newbie"]["user_id"] == 555
              and sec3["redmine_accounts"]["newbie"]["label"] == "Новый Пользователь"
              and sec3["redmine_active"] == "newbie", msg3)
        ok4, msg4 = core.save_redmine_account("плохой", api_key="мусор")
        check("аккаунты: невалидный токен -> отказ, в файл не попал",
              not ok4 and "не принят" in msg4
              and "плохой" not in json.load(open(core.SECRETS_FILE, encoding="utf-8"))["redmine_accounts"])

        core.delete_redmine_account("newbie")
        core.delete_redmine_account("bot")
        ok5, msg5 = core.delete_redmine_account("maintainer")
        check("аккаунты: последний удалить нельзя",
              not ok5 and "последний" in msg5
              and list(json.load(open(core.SECRETS_FILE, encoding="utf-8"))["redmine_accounts"]) == ["maintainer"])
    finally:
        rmc.RedmineClient = saved_client
        if saved is not None:
            with open(core.SECRETS_FILE, "w", encoding="utf-8") as f:
                f.write(saved)


def test_secrets_fail_closed_and_publish_account():


    from agent import redmine_client as rmc
    saved = open(core.SECRETS_FILE, encoding="utf-8").read() \
        if os.path.exists(core.SECRETS_FILE) else None
    try:

        with open(core.SECRETS_FILE, "w", encoding="utf-8") as f:
            f.write('{"imap_password": "СЕКРЕТ", "redmine_accounts": {oops')
        before = open(core.SECRETS_FILE, encoding="utf-8").read()
        ok1, m1 = core.save_redmine_account("новый", api_key="x" * 40)
        ok2, m2 = core.set_redmine_active("любой")
        ok3, m3 = core.delete_redmine_account("любой")
        after = open(core.SECRETS_FILE, encoding="utf-8").read()
        check("secrets fail-closed: битый файл -> все три писателя отказали, файл НЕ перезаписан",
              (not ok1) and (not ok2) and (not ok3) and after == before
              and "не прочитан" in m1, m1)


        with open(core.SECRETS_FILE, "w", encoding="utf-8") as f:
            json.dump({"redmine_url": "http://service.example.invalid", "redmine_api_key": "LEGACYKEY",
                       "redmine_accounts": {"active_one": {
                           "url": "http://service.example.invalid", "api_key": "ACTIVEKEY", "user_id": 42}},
                       "redmine_active": "active_one"}, f)
        acc = rmc.resolve_account(json.load(open(core.SECRETS_FILE, encoding="utf-8")))
        used = {}

        class _FakeRC:
            def __init__(self, url, key):
                used["url"], used["key"] = url, key

            def upload(self, *a, **k):
                return "tok"

            def add_note(self, *a, **k):
                pass

            def create_time_entry(self, *a, **k):
                pass
        from tools.dashboard import drafts as _d
        saved_rc, saved_status = _d.rmc.RedmineClient, core.agent_status
        try:
            _d.rmc.RedmineClient = _FakeRC
            core.agent_status = lambda: {"dry_run": False}
            _write_draft(46001, status="pending")
            _d.publish_draft(46001)
        finally:
            _d.rmc.RedmineClient, core.agent_status = saved_rc, saved_status
            try:
                os.remove(_d.draft_path(46001))
            except OSError:
                pass
        check("publish_draft: коммент уходит под АКТИВНЫМ аккаунтом, не под legacy-токеном",
              used.get("key") == "ACTIVEKEY" and used.get("url") == "http://service.example.invalid"
              and acc["api_key"] == "ACTIVEKEY", str(used))
    finally:
        if saved is not None:
            with open(core.SECRETS_FILE, "w", encoding="utf-8") as f:
                f.write(saved)


def test_publish_is_serialized_and_svg_not_inline():


    from tools.dashboard import drafts
    import threading as _th


    posts = []
    saved_rc, saved_status = drafts.rmc.RedmineClient, core.agent_status

    class _SlowRC:
        def __init__(self, url, key):
            pass

        def upload(self, *a, **k):
            return "tok"

        def add_note(self, iid, note, uploads=None, private=True):
            time.sleep(0.25)
            posts.append(iid)

        def create_time_entry(self, *a, **k):
            pass
    try:
        drafts.rmc.RedmineClient = _SlowRC
        core.agent_status = lambda: {"dry_run": False}
        _write_draft(46201, status="pending")
        res = []
        ths = [_th.Thread(target=lambda: res.append(drafts.publish_draft(46201)))
               for _ in range(2)]
        [t.start() for t in ths]
        [t.join(10) for t in ths]
        check("publish_draft: два параллельных клика -> РОВНО один коммент в Redmine",
              len(posts) == 1 and sum(1 for r in res if r.get("posted")) == 1
              and any(r.get("reason") == "already_posted" for r in res), str(posts))
    finally:
        drafts.rmc.RedmineClient, core.agent_status = saved_rc, saved_status
        try:
            os.remove(drafts.draft_path(46201))
        except OSError:
            pass


    errs = []

    def _writer(tag):
        for _i in range(25):
            try:
                drafts.save_draft(46202, {"issue_id": 46202, "status": "pending",
                                          "analysis": tag * 400})
                if drafts.load_draft(46202) is None:
                    errs.append("битый json")
            except Exception as e:
                errs.append(str(e))
    ts = [_th.Thread(target=_writer, args=(c,)) for c in ("A", "B")]
    [t.start() for t in ts]
    [t.join(15) for t in ts]
    check("save_draft: параллельная запись одной заявки не портит файл", not errs, str(errs[:2]))
    try:
        os.remove(drafts.draft_path(46202))
    except OSError:
        pass


def test_chat_always_makes_draft():


    from tools.dashboard import drafts
    for iid in (46101, 46102, 46103, 46104):
        try:
            os.remove(drafts.draft_path(iid))
        except OSError:
            pass
    try:

        d, created = drafts.upsert_draft_from_chat(46101, "Разбор: не выгрузился документ.",
                                                   subject="тема", session_id="s1")
        got = drafts.load_draft(46101)
        check("чат: нет черновика -> СОЗДАН из ответа ИИ (kind=chat, pending, публикуемый)",
              created and d and got["status"] == "pending" and got["kind"] == "chat"
              and got["analysis"].startswith("Разбор:")
              and got["comment"] == "h3. Разбор:\n\n" + got["analysis"]
              and got["screenshots"] == [] and got["session_id"] == "s1")


        _write_draft(46102, status="pending", analysis="старый разбор")
        d2, created2 = drafts.upsert_draft_from_chat(46102, "новый разбор из чата")
        got2 = drafts.load_draft(46102)
        check("чат: pending-черновик ОБНОВЛЁН тем же файлом (не создан второй)",
              (not created2) and d2 and got2["analysis"] == "новый разбор из чата"
              and got2["status"] == "pending")


        _write_draft(46103, status="posted", analysis="опубликовано")
        d3, _c3 = drafts.upsert_draft_from_chat(46103, "болтовня после публикации")
        got3 = drafts.load_draft(46103)
        check("чат: posted-черновик НЕ воскрешается и не затирается",
              d3 is None and got3["status"] == "posted" and got3["analysis"] == "опубликовано")


        d4, _c4 = drafts.upsert_draft_from_chat(46104, "   ")
        check("чат: пустой ответ -> черновик не заводится",
              d4 is None and drafts.load_draft(46104) is None)
    finally:
        for iid in (46101, 46102, 46103, 46104):
            try:
                os.remove(drafts.draft_path(iid))
            except OSError:
                pass


def test_chat_never_publishes_directly():


    try:
        import fastapi
        from tools.dashboard.routes import chats
    except ImportError:
        print("%-54s SKIP (нет fastapi)" % "chat draft-mode")
        return
    seen = {}
    saved_popen, saved_status = chats.subprocess.Popen, core.agent_status

    class _FakeProc:
        returncode = 0
        pid = 4242

        def communicate(self, input=None, timeout=None):
            i = self.cmd.index("--mcp-config")
            seen["mcp"] = json.load(open(self.cmd[i + 1]))
            return json.dumps({"result": "ответ", "session_id": "s"}), ""

        def kill(self):
            pass

    def fake_popen(cmd, **kw):
        p = _FakeProc()
        p.cmd = cmd
        return p
    try:
        chats.subprocess.Popen = fake_popen
        core.agent_status = lambda: {"dry_run": False}
        chats._run_claude("вопрос", 46105, None, chats.CHAT_CWD, draft_pending=False)
        env = (seen.get("mcp", {}).get("mcpServers", {}).get("redmine", {}) or {}).get("env", {})
        check("чат в БОЕВОМ режиме без черновика: redmine всё равно draft-режим (RM_DRAFT_FILE+RM_DRY=1)",
              bool(env.get("RM_DRAFT_FILE")) and env.get("RM_DRY") == "1", str(env)[:120])
    finally:
        chats.subprocess.Popen, core.agent_status = saved_popen, saved_status


def test_humanizer_enabled_toggle():

    try:
        import fastapi
        from tools.dashboard.routes import humanize as hz
    except ImportError:
        print("%-54s SKIP (нет fastapi)" % "humanizer enabled toggle")
        return
    from tools.dashboard import drafts
    saved_cfg = hz._cfg
    try:
        _write_draft(46002, status="pending")
        hz._cfg = lambda: {"enabled": False}
        r = hz.humanize_start(46002)
        body = json.loads(bytes(r.body).decode()) if hasattr(r, "body") else r
        d = drafts.load_draft(46002)
        check("humanizer.enabled=false -> отказ (disabled), черновик не помечен running",
              body.get("reason") == "disabled" and (d.get("humanize") or {}).get("status") != "running")
    finally:
        hz._cfg = saved_cfg
        try:
            os.remove(drafts.draft_path(46002))
        except OSError:
            pass


def test_build_note_inline_images():


    from tools.dashboard import drafts
    d1 = {"comment": "h3. Разбор\n\nМесто кончается на app01:\n!p78.png!\n\nНа app02 норма."}
    n1 = drafts.build_note(d1, ["p78.png"])
    check("build_note: расставленную агентом картинку в конец НЕ дублируем",
          n1.count("!p78.png!") == 1 and n1.endswith("На app02 норма."), repr(n1[-40:]))
    d2 = {"comment": "h3. Разбор\n\nМесто кончается на app01:\n!p78.png!"}
    n2 = drafts.build_note(d2, ["p78.png", "p79.png"])
    check("build_note: НЕрасставленные дописываются в конец (страховка)",
          n2.count("!p78.png!") == 1 and n2.rstrip().endswith("!p79.png!"), repr(n2[-40:]))
    d3 = {"comment": "h3. Разбор\n\nбез картинок в тексте"}
    n3 = drafts.build_note(d3, ["p78.png", "p79.png"])
    check("build_note: агент ничего не расставил -> обе строки хвостом (как раньше)",
          n3.rstrip().endswith("!p78.png!\n!p79.png!"), repr(n3[-40:]))
    check("build_note: пустой comment -> собираем из analysis+sql",
          drafts.build_note({"analysis": "текст", "sql": "select 1"}, [])
          == "h3. Разбор\n\nтекст\n\nselect 1")


def test_chat_standard_prompt():


    try:
        import fastapi
    except ImportError:
        print("%-54s SKIP (нет fastapi)" % "chat standard prompt")
        return
    from tools.dashboard.routes import chats
    from tools.dashboard.models import ChatSendRequest
    iid = 46200
    sent = []

    def fake_worker(issue_id, subject, sid, text, url, model, effort, atts, draft_pending):
        sent.append(text)
        chats._active.discard(issue_id)

    orig_worker, orig_std = chats._answer_worker, chats.standard_prompt
    chats._answer_worker = fake_worker
    chats.standard_prompt = lambda *a, **k: "СТАНДАРТНЫЙ ПРОМПТ"
    try:
        try:
            os.remove(chats._chat_path(iid))
        except OSError:
            pass
        r1 = chats.chat_send(iid, ChatSendRequest(message="почему не печатается этикетка?"))
        _chat_wait(iid)
        check("чат: ПЕРВОЕ сообщение = мой текст + пустая строка + стандартный промпт",
              r1.get("ok") and sent
              and sent[-1] == "почему не печатается этикетка?\n\nСТАНДАРТНЫЙ ПРОМПТ",
              repr(sent[-1][:60] if sent else None))
        hist = chats._load_chat(iid)["messages"]
        check("чат: в историю пишется мой текст с пометкой std (не портянка промпта)",
              hist[-1]["text"] == "почему не печатается этикетка?" and hist[-1].get("std") is True)

        r2 = chats.chat_send(iid, ChatSendRequest(message="а если склад другой?"))
        _chat_wait(iid)
        check("чат: ВТОРОЕ сообщение уходит БЕЗ стандартного промпта",
              r2.get("ok") and sent[-1] == "а если склад другой?", repr(sent[-1][:40]))

        r3 = chats.chat_send(iid, ChatSendRequest(message="", std_prompt=True))
        _chat_wait(iid)
        check("чат: кнопка «Стандартный промпт» с пустым полем -> уходит только промпт",
              r3.get("ok") and sent[-1] == "СТАНДАРТНЫЙ ПРОМПТ", repr(sent[-1][:40]))
        hist3 = chats._load_chat(iid)["messages"]
        check("чат: кнопка без текста -> в истории понятная подпись",
              hist3[-1]["text"] == "Разбери заявку по стандартному промпту."
              and hist3[-1].get("std") is True)

        r4 = chats.chat_send(iid, ChatSendRequest(message="", std_prompt=False))
        check("чат: пустое сообщение без флага по-прежнему отвергается",
              r4.get("ok") is False and "пуст" in (r4.get("error") or ""))


        iid2 = 46201
        try:
            os.remove(chats._chat_path(iid2))
        except OSError:
            pass
        _write_draft(iid2, status="pending", analysis="разбор алерта")
        try:
            r5 = chats.chat_send(iid2, ChatSendRequest(message="а почему так?"))
            _chat_wait(iid2)
            check("чат: у УЖЕ разобранной заявки (есть черновик) промпт НЕ приклеивается",
                  r5.get("ok") and sent[-1] == "а почему так?", repr(sent[-1][:40]))
            r6 = chats.chat_send(iid2, ChatSendRequest(message="", std_prompt=True))
            _chat_wait(iid2)
            check("чат: кнопка перебивает это — промпт уходит по явному нажатию",
                  r6.get("ok") and sent[-1] == "СТАНДАРТНЫЙ ПРОМПТ", repr(sent[-1][:40]))
        finally:
            from tools.dashboard import drafts as _d
            for f_ in (_d.draft_path(iid2), chats._chat_path(iid2)):
                try:
                    os.remove(f_)
                except OSError:
                    pass
    finally:
        chats._answer_worker, chats.standard_prompt = orig_worker, orig_std
        try:
            os.remove(chats._chat_path(iid))
        except OSError:
            pass


def main():
    try:


        test_agent_config()
        test_model_effort()
        test_mode_honesty()
        test_pause_control()
        test_start_cmd()
        test_alert_escalation()
        test_docs_dir_resolution()
        test_influx_series_helpers()
        test_influx_series_into_prompt()
        test_manual_dispatch()
        test_draft_helpers()
        test_chats()
        test_chat_pending()
        test_chat_attachments()
        test_draft_chat_flow()
        test_draft_update_from_chat()
        test_draft_publish()
        test_draft_publish_endpoint()
        test_humanize_worker()
        test_humanize_endpoints()
        test_humanize_chat_reset()
        test_opus_post_approval()
        test_mcp_draft_stage()
        test_ticket_info_card()
        test_ticket_info_endpoint()
        test_ticket_attachment_proxy()
        test_stats_pending_excludes_reviewing()
        test_poll_mail_outage_decoupled()
        test_redmine_accounts_core()
        test_secrets_fail_closed_and_publish_account()
        test_publish_is_serialized_and_svg_not_inline()
        test_chat_always_makes_draft()
        test_build_note_inline_images()
        test_chat_standard_prompt()
        test_chat_never_publishes_directly()
        test_humanizer_enabled_toggle()
    finally:
        shutil.rmtree(_CORE_ROOT, ignore_errors=True)
    if _fail:
        print("\nПРОВАЛЕНО: %s" % ", ".join(_fail))
        sys.exit(1)
    print("\nвсе регресс-тесты dashboard пройдены")


if __name__ == "__main__":
    main()
