# -*- coding: utf-8 -*-


import copy
import json
import logging
import os
import shutil
import sys
import tempfile
import time
import types
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import agent.orchestrator as O
from agent import approvals


_ORIG_REDMINE_CLIENT = O.RedmineClient
_ORIG_MAIL_CLIENT = O.MailClient
_ORIG_TR = O.tr


class FakeRedmine:
    def __init__(self, url, api_key):
        self.url, self.api_key = url, api_key
        self.issues = []
        self.request_calls = []

    def _request(self, method, path, params=None):
        self.request_calls.append((method, path, dict(params or {})))
        if isinstance(self.issues, BaseException):
            raise self.issues
        if path == "/issues.json":
            offset = int((params or {}).get("offset", 0))
            limit = int((params or {}).get("limit", 100))
            page = self.issues[offset:offset + limit]
            return {"issues": [copy.deepcopy(x) for x in page], "total_count": len(self.issues)}
        return {}

    def paged(self, path, params=None, max_pages=5, item_key="issues"):


        out, offset = [], 0
        for _ in range(max_pages):
            p = dict(params or {})
            p["limit"] = 100
            p["offset"] = offset
            data = self._request("GET", path, params=p)
            batch = data.get(item_key, [])
            out += batch
            offset += len(batch)
            if not batch or offset >= data.get("total_count", 0):
                break
        return out

    def newest_issue_id(self, tracker_id):
        return 100000


class FakeMail:
    def __init__(self, host, port, login, password, folder="INBOX"):
        self.host, self.port, self.login, self.password, self.folder = (
            host, port, login, password, folder)
        self.uidnext_val = 2000
        self.closed = False

    def uidnext(self):
        return self.uidnext_val

    def uidvalidity(self):
        return None

    def close(self):
        self.closed = True


def _apply_client_patches():
    O.RedmineClient = FakeRedmine
    O.MailClient = FakeMail
    O.tr = types.SimpleNamespace(status=lambda *a, **k: None, trace=lambda *a, **k: None)


def _restore_client_patches():
    O.RedmineClient = _ORIG_REDMINE_CLIENT
    O.MailClient = _ORIG_MAIL_CLIENT
    O.tr = _ORIG_TR


try:
    import pytest

    @pytest.fixture(autouse=True, scope="module")
    def _agent_client_patches():
        _apply_client_patches()
        yield
        _restore_client_patches()
except ImportError:
    pass

logging.disable(logging.CRITICAL)


BASE_CONFIG = {
    "imap": {"host": "imap.test", "port": 993, "folder": "INBOX"},
    "dry_run": True,
    "assigned_to_id": 1,
    "work_status_id": 2,
    "ticket_poll": {
        "query_id": 178,
        "query_project": "example-project-001",
        "trigger_statuses": [1, 49, 2],
        "fresh_minutes": 10,
        "tracker_id": 1,
        "alert_subject_re": r"\[alerting\]",
        "alert_exclude_projects": ["Клиент A Т/П"],
    },
    "default_flow": {"enabled": True},
    "grafana": {"enabled": True, "tracker_id": 65},
}

SECRETS = {
    "redmine_url": "http://service.example.invalid",
    "redmine_api_key": "test-key",
    "imap_login": "agent@test",
    "imap_password": "x",
}

_ROOTS = []


def build_agent(cfg_overrides=None):


    root = tempfile.mkdtemp(prefix="wa_178_")
    _ROOTS.append(root)
    os.makedirs(os.path.join(root, "config"))
    os.makedirs(os.path.join(root, "state"))
    cfg = copy.deepcopy(BASE_CONFIG)
    if cfg_overrides:
        cfg.update(cfg_overrides)
    with open(os.path.join(root, "config", "config.json"), "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False)
    with open(os.path.join(root, "config", "secrets.local.json"), "w", encoding="utf-8") as f:
        json.dump(SECRETS, f, ensure_ascii=False)
    with open(os.path.join(root, "state", "last_uid.json"), "w", encoding="utf-8") as f:
        json.dump({"last_uid": 1000}, f)
    return O.Agent(root, dry_run_override=True)


def iso_ago(minutes):
    dt = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def make_issue(iid, *, tracker=1, subject="", description="",
               project_id=900, project_name="Обычный клиент",
               status_id=1, created_min_ago=1, created_on=None):

    return {
        "id": iid,
        "tracker": {"id": tracker},
        "subject": subject,
        "description": description,
        "project": {"id": project_id, "name": project_name},
        "status": {"id": status_id, "name": "Новая"},
        "created_on": created_on if created_on is not None else iso_ago(created_min_ago),
        "author": {"name": "тестер"},
        "assigned_to": None,
    }


def install_recorders(agent, behavior=None):


    behavior = behavior or {}
    calls = []
    agent._dispatched = calls

    def _raise(branch, iid):
        b = behavior.get(branch)
        if b == "defer":
            raise O._TicketDefer(iid, "test-defer", quiet=True)
        if b == "crash":
            raise RuntimeError("test-crash-%s" % branch)

    def default(issue, key, stats):
        calls.append({"branch": "default", "id": issue["id"], "key": key})
        _raise("default", issue["id"])

    def ticket(t, key, stats, force=False):
        calls.append({"branch": "alert", "id": t["id"], "key": key, "force": force})
        _raise("alert", t["id"])

    def opus(i, ap, stats):
        calls.append({"branch": "opus", "id": i["id"], "pipe": ap.get("pipe")})
        _raise("opus", i["id"])

    def storm(new, stats):
        calls.append({"branch": "storm", "ids": sorted(t["id"] for t in new)})


    agent._process_default = default
    agent._process_ticket = ticket
    agent._handle_opus_request = opus
    agent._maybe_handle_storm = storm
    return calls


def run_dispatch(agent, issues, alerts=True, behavior=None):

    agent.redmine.issues = issues
    if alerts:
        agent.ticket_cursor = 1
    else:
        agent.ticket_cursor = None
        agent.gf_sets = []
    calls = install_recorders(agent, behavior)
    agent._poll_178({})
    return calls


def ids(calls, branch):
    return sorted(c["id"] for c in calls if c["branch"] == branch)


def journal_records(agent):
    recs = []
    p = os.path.join(agent.root, "state", "processed.jsonl")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    recs.append(json.loads(line))
    return recs


def seed_seen(agent, key, verdict="seed_terminal", issue_id=None):

    agent.journal.record(key, verdict, subject="seed", issue_id=issue_id)


_fail = []
_count = 0


def check(name, cond, extra=""):
    global _count
    _count += 1
    print("%-72s %s %s" % (name, "OK" if cond else "FAIL", extra))
    if not cond:
        _fail.append(name)
        assert cond, f"{name}: {extra}"


def test_agent_builds():
    a = build_agent()
    check("Agent собран на фейках (redmine=Fake, ticket_cursor=None, gf_sets=[])",
          isinstance(a.redmine, FakeRedmine) and a.ticket_cursor is None and a.gf_sets == [],
          "gf_sets=%r cursor=%r" % (a.gf_sets, a.ticket_cursor))
    check("гейты: ticket_poll прочитан, default_flow.enabled прочитан",
          a.cfg["ticket_poll"]["query_id"] == 178 and bool(a.default_cfg["enabled"]))


def test_classification():
    a = build_agent()
    issues = [
        make_issue(101, tracker=1, subject="[Alerting] CPU высокий", project_name="Клиент G"),
        make_issue(102, tracker=65, subject="сборщик встал", project_name="Клиент G"),
        make_issue(103, tracker=1, subject="Не отрабатывает алкокод по товару"),
        make_issue(104, tracker=1, subject="Смена типа приёмки",
                   description="переделайте приёмку в возврат с учётом марок"),
        make_issue(105, tracker=1, subject="Не печатает чек на кассе"),
        make_issue(106, tracker=14, subject="регламентная заявка"),
        make_issue(107, tracker=65, subject="алерт Клиент Aа", project_name="Клиент A Т/П"),
    ]
    calls = run_dispatch(a, issues, alerts=True)
    check("классиф: [Alerting]-тема (трекер1) И трекер65-непрофильный проект -> alert (2 шт)",
          ids(calls, "alert") == [101, 102], "alert=%s" % ids(calls, "alert"))
    check("классиф: трекер1 «прочее» (в т.ч. бывшие Клиент C связка/retype) -> default",
          ids(calls, "default") == [103, 104, 105], "default=%s" % ids(calls, "default"))
    check("классиф: трекер14 (регламент) И трекер65-в-Клиент A-Т/П -> НИКУДА не диспетчеризуются",
          all(c["id"] not in (106, 107) for c in calls if c["branch"] != "storm"),
          "непрофильные среди dispatched: %s"
          % [c["id"] for c in calls if c["branch"] != "storm" and c["id"] in (106, 107)])
    check("классиф: авто-алерт идёт с force=False (ручного дисптача нет)",
          all(c["force"] is False for c in calls if c["branch"] == "alert"))
    check("классиф: ключи веток по префиксам (default-/ticket-)",
          {c["key"] for c in calls if c["branch"] == "default"}
          == {"default-103", "default-104", "default-105"}
          and {c["key"] for c in calls if c["branch"] == "alert"} == {"ticket-101", "ticket-102"})


def test_override_priority():

    a = build_agent()
    approvals.create_manual_opus(a.root, 201, "незнакомая заявка")
    iss = make_issue(201, tracker=1, subject="Не отрабатывает алкокод")
    calls = run_dispatch(a, [iss], alerts=True)
    check("оверрайд/opus: живой pipe=opus -> _handle_opus_request перехватывает, default НЕ вызван",
          ids(calls, "opus") == [201] and ids(calls, "default") == [],
          "opus=%s default=%s" % (ids(calls, "opus"), ids(calls, "default")))


    a = build_agent()
    approvals.create_manual_alert(a.root, 202, "не работает касса")
    iss = make_issue(202, tracker=1, subject="Не работает касса")
    calls = run_dispatch(a, [iss], alerts=True)
    alert_calls = [c for c in calls if c["branch"] == "alert"]
    check("оверрайд/alert: pipe=alert форсит alert (force=True) в обход детекта, default НЕ вызван",
          ids(calls, "alert") == [202] and ids(calls, "default") == []
          and alert_calls and alert_calls[0]["force"] is True,
          "alert=%s force=%s default=%s" % (ids(calls, "alert"),
          alert_calls[0]["force"] if alert_calls else "—", ids(calls, "default")))


    a = build_agent()
    approvals.create_manual_alert(a.root, 203, "вручную в графану")
    issues = [make_issue(203, tracker=1, subject="Не работает касса"),
              make_issue(204, tracker=1, subject="[Alerting] LOCKS CLB")]
    calls = run_dispatch(a, issues, alerts=False)
    check("оверрайд/alert при alerts_on=False: ручной -> alert (force), авто-детект НЕ в alert",
          ids(calls, "alert") == [203] and 204 not in ids(calls, "alert"),
          "alert=%s" % ids(calls, "alert"))


def test_seen_skips():
    a = build_agent()
    seed_seen(a, "default-301", "default_done", issue_id=301)
    issues = [
        make_issue(301, tracker=1, subject="повторная заявка"),
        make_issue(302, tracker=1, subject="свежая заявка"),
    ]
    calls = run_dispatch(a, issues, alerts=True)
    check("seen: default-N уже seen -> ПРОПУСК (не диспетчеризуется)",
          301 not in ids(calls, "default"), "default=%s" % ids(calls, "default"))
    check("seen: не-seen заявка того же прохода обрабатывается",
          302 in ids(calls, "default"), "default=%s" % ids(calls, "default"))


def test_alert_override_clear_timing():

    a = build_agent()
    approvals.create_manual_alert(a.root, 401, "алерт вручную")
    calls = run_dispatch(a, [make_issue(401, tracker=1, subject="касса лежит")], alerts=True)
    check("clear/успех: manual_alert обработан -> файл pipe=alert снят ПОСЛЕ успеха, id не в _deferred_178",
          ids(calls, "alert") == [401] and approvals.load(a.root, 401) is None
          and 401 not in a._deferred_178, "file=%s def=%s"
          % (approvals.load(a.root, 401), 401 in a._deferred_178))


    a = build_agent()
    approvals.create_manual_alert(a.root, 402, "алерт вручную")
    calls = run_dispatch(a, [make_issue(402, tracker=1, subject="касса лежит")],
                         alerts=True, behavior={"alert": "defer"})
    ap = approvals.load(a.root, 402)
    check("clear/defer: _process_ticket бросил _TicketDefer -> файл pipe=alert ОСТАЁТСЯ, id в _deferred_178",
          ap is not None and ap.get("pipe") == "alert" and 402 in a._deferred_178,
          "file=%s def=%s" % (ap, 402 in a._deferred_178))


    a = build_agent()
    approvals.create_manual_alert(a.root, 403, "алерт вручную")
    calls = run_dispatch(a, [make_issue(403, tracker=1, subject="касса лежит")],
                         alerts=True, behavior={"alert": "crash"})
    verds = {r["verdict"] for r in journal_records(a) if r.get("message_id") == "ticket-403"}
    check("clear/краш: не-defer краш -> файл снят (poison-pill) + журнал 'error' по ticket-403",
          approvals.load(a.root, 403) is None and "error" in verds,
          "file=%s verds=%s" % (approvals.load(a.root, 403), verds))


def test_status_age_held_filters():
    a = build_agent()


    approvals.save(a.root, 503, {"issue_id": 503, "pipe": "note", "status": "pending"})
    issues = [
        make_issue(501, tracker=1, subject="заявка", status_id=5),
        make_issue(502, tracker=1, subject="заявка", created_min_ago=30),
        make_issue(503, tracker=1, subject="заявка", status_id=5,
                   created_min_ago=30),
    ]
    calls = run_dispatch(a, issues, alerts=True)
    check("фильтр/статус: status.id вне trigger_statuses и не held -> ПРОПУСК",
          501 not in ids(calls, "default"), "default=%s" % ids(calls, "default"))
    check("фильтр/возраст: created_on старше fresh_minutes и не held -> ПРОПУСК",
          502 not in ids(calls, "default"), "default=%s" % ids(calls, "default"))
    check("фильтр/held: живой approval-файл (held_ids) ОБХОДИТ И статус, И возраст -> обработка",
          503 in ids(calls, "default"), "default=%s" % ids(calls, "default"))


def test_defer_and_age_freeze():

    a = build_agent()
    issues = [
        make_issue(601, tracker=1, subject="заявка раз"),
        make_issue(602, tracker=1, subject="заявка два"),
    ]
    calls = run_dispatch(a, issues, alerts=True, behavior={"default": "defer"})
    check("defer: обе default-заявки -> id в _deferred_178, journal.seen НЕ поставлен",
          601 in a._deferred_178 and 602 in a._deferred_178
          and not a.journal.seen("default-601") and not a.journal.seen("default-602"),
          "def=%s seen601=%s" % (sorted(a._deferred_178), a.journal.seen("default-601")))


    a = build_agent()
    created = datetime.now(timezone.utc) - timedelta(minutes=30)
    created_str = created.strftime("%Y-%m-%dT%H:%M:%SZ")
    a._deferred_178[701] = created.timestamp() + 60
    issues = [
        make_issue(701, tracker=1, subject="заявка", created_on=created_str),
        make_issue(702, tracker=1, subject="заявка", created_on=created_str),
    ]
    calls = run_dispatch(a, issues, alerts=True)
    check("заморозка: заявка с _deferred_178 (возраст мерян от дефера=1мин) НЕ протухла -> обработана",
          701 in ids(calls, "default"), "default=%s" % ids(calls, "default"))
    check("заморозка-контроль: та же заявка БЕЗ защёлки (возраст от «сейчас»=30мин > fresh) -> ПРОПУСК",
          702 not in ids(calls, "default"), "default=%s" % ids(calls, "default"))


def test_storm_prepass():
    a = build_agent()
    issues = [
        make_issue(801, tracker=65, subject="алерт A", project_name="Клиент G"),
        make_issue(802, tracker=1, subject="обычная заявка"),
        make_issue(803, tracker=1, subject="[Alerting] алерт C", project_name="Клиент B"),
    ]
    calls = run_dispatch(a, issues, alerts=True)
    storm = [c for c in calls if c["branch"] == "storm"]
    check("шторм: _maybe_handle_storm вызван РОВНО один раз (пре-пасс)",
          len(storm) == 1, "storm-вызовов=%d" % len(storm))
    check("шторм: переданы ТОЛЬКО alert-заявки ([Alerting]|трекер65-непрофильный), default НЕ включена",
          storm and storm[0]["ids"] == [801, 803], "ids=%s" % (storm[0]["ids"] if storm else None))
    check("шторм: заглушка не пометила seen -> alert-заявки всё равно дошли до поштучного _process_ticket",
          ids(calls, "alert") == [801, 803] and ids(calls, "default") == [802])


def test_crash_poison_pill():
    a = build_agent()
    iss = make_issue(1101, tracker=1, subject="заявка")
    run_dispatch(a, [iss], alerts=True, behavior={"default": "crash"})
    verds = {r["verdict"] for r in journal_records(a) if r.get("message_id") == "default-1101"}
    check("краш/default: не-defer краш -> журнал 'error' по default-1101 И journal.seen ставится (poison-pill)",
          "error" in verds and a.journal.seen("default-1101"), "verds=%s" % verds)
    calls2 = run_dispatch(a, [iss], alerts=True)
    check("краш/default: 2-й проход -> заявка НЕ переобрабатывается (seen поглотил)",
          ids(calls2, "default") == [], "default=%s" % ids(calls2, "default"))


def test_manual_alert_bypasses_alerts_on():

    a = build_agent()
    approvals.create_manual_alert(a.root, 1001, "алерт вручную")
    iss = make_issue(1001, tracker=65, subject="сборщик встал", project_name="Клиент G")
    calls = run_dispatch(a, [iss], alerts=False)
    check("alerts_on=False -> ручной pipe=alert ВСЁ РАВНО форсит alert, файл снят после успеха",
          ids(calls, "alert") == [1001] and approvals.load(a.root, 1001) is None,
          "alert=%s file=%s" % (ids(calls, "alert"), approvals.load(a.root, 1001) is not None))


    a = build_agent()
    approvals.create_manual_alert(a.root, 1002, "алерт вручную")
    iss = make_issue(1002, tracker=1, subject="Не работает касса")
    calls = run_dispatch(a, [iss], alerts=False)
    check("alerts_on=False + pipe=alert на трекер1 -> alert (НЕ default), файл снят",
          ids(calls, "alert") == [1002] and ids(calls, "default") == []
          and approvals.load(a.root, 1002) is None,
          "alert=%s default=%s file=%s" % (ids(calls, "alert"), ids(calls, "default"),
          approvals.load(a.root, 1002) is not None))


def test_all_projects_maps_and_caches():
    a = build_agent()
    calls = []

    def fake_paged(path, params=None, max_pages=5, item_key="issues"):
        calls.append((path, item_key, max_pages))
        return [{"id": 10, "name": "Клиент B"}, {"id": 11}]

    a.redmine = types.SimpleNamespace(paged=fake_paged)
    out = a._all_projects()
    check("_all_projects: paged('/projects.json', item_key='projects', max_pages=50) + маппинг "
          "{id,name} (name по умолчанию '')",
          out == [{"id": 10, "name": "Клиент B"}, {"id": 11, "name": ""}]
          and calls == [("/projects.json", "projects", 50)],
          "out=%s calls=%s" % (out, calls))
    out2 = a._all_projects()
    check("_all_projects: второй вызов берёт кеш процесса (paged повторно НЕ дёргается)",
          out2 == out and len(calls) == 1, "calls=%d" % len(calls))


def test_request_opus_preserves_live_foreign_approval():


    a = build_agent()
    approvals.save(a.root, 601, {"pipe": "alert", "issue_id": 601,
                                 "status": "pending", "subject": "ручной дисптач"})
    a._request_opus(601, "заявка", "тело", "проект", origin_key="default-601", reason="default")
    ap = approvals.load(a.root, 601)
    check("A#2: живой чужой approval (pipe=alert, pending) НЕ перезатёрт opus-запросом",
          ap is not None and ap.get("pipe") == "alert" and ap.get("status") == "pending",
          "ap=%s" % ap)

    a._request_opus(602, "незнакомая", "тело", "проект", origin_key="default-602", reason="default")
    ap2 = approvals.load(a.root, 602)
    check("A#2 контроль: без живого файла создаётся pipe=opus/pending",
          ap2 is not None and ap2.get("pipe") == "opus" and ap2.get("status") == "pending",
          "ap2=%s" % ap2)


def test_approvals_cas():

    a = build_agent()
    root = a.root
    approvals.save(root, 5000, {"pipe": "opus", "issue_id": 5000, "status": "pending"})
    ap = approvals.load(root, 5000)
    check("CAS: rev штампуется при создании (rev=1)", ap.get("rev") == 1, "rev=%s" % ap.get("rev"))
    ok, _ = approvals.save(root, 5000, dict(ap, status="approved"), if_rev=1)
    check("CAS: запись с ВЕРНЫМ if_rev проходит, rev->2",
          ok and approvals.load(root, 5000)["rev"] == 2, "ok=%s" % ok)
    ok2, _ = approvals.save(root, 5000, dict(ap, status="ignore"), if_rev=1)
    cur = approvals.load(root, 5000)
    check("CAS: запись со СТАРЫМ if_rev ОТКЛОНЕНА, файл не тронут",
          (not ok2) and cur["status"] == "approved" and cur["rev"] == 2,
          "ok2=%s status=%s rev=%s" % (ok2, cur.get("status"), cur.get("rev")))
    approvals.save(root, 5001, {"pipe": "opus", "issue_id": 5001, "status": "pending"})
    ok3, _ = approvals.decide(root, 5001, "approved")
    check("CAS: decide на свежий pending проходит",
          ok3 and approvals.load(root, 5001)["status"] == "approved", "ok3=%s" % ok3)
    ok4, err4 = approvals.decide(root, 5001, "ignore")
    check("CAS: повторный decide на уже решённый -> отказ",
          (not ok4) and "решён" in (err4 or ""), "ok4=%s err=%s" % (ok4, err4))


def test_branch_switches():


    issues = [make_issue(801, tracker=1, subject="Не работает касса"),
              make_issue(802, tracker=1, subject="[Alerting] CLB LOCKS")]
    a = build_agent()
    calls = run_dispatch(a, issues, alerts=True)
    check("обе ветки включены: диспетч работает", len(calls) > 0, "calls=%d" % len(calls))

    a2 = build_agent()
    a2.default_cfg["enabled"] = False
    calls2 = run_dispatch(a2, issues, alerts=True)
    check("default_flow.enabled=false: default-ветка молчит, алерт остаётся",
          not ids(calls2, "default") and ids(calls2, "alert"),
          "calls=%s" % [c["branch"] for c in calls2])

    a3 = build_agent()
    calls3 = run_dispatch(a3, issues, alerts=False)
    check("алерт-ветка выключена: алерт не диспетчеризуется",
          not ids(calls3, "alert"), "calls=%s" % [c["branch"] for c in calls3])


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    _apply_client_patches()
    try:
        test_agent_builds()
        test_classification()
        test_override_priority()
        test_seen_skips()
        test_alert_override_clear_timing()
        test_status_age_held_filters()
        test_defer_and_age_freeze()
        test_storm_prepass()
        test_crash_poison_pill()
        test_manual_alert_bypasses_alerts_on()
        test_all_projects_maps_and_caches()
        test_request_opus_preserves_live_foreign_approval()
        test_approvals_cas()
        test_branch_switches()
    finally:
        for r in _ROOTS:
            shutil.rmtree(r, ignore_errors=True)
        _restore_client_patches()

    print("\nвсего проверок: %d, провалено: %d" % (_count, len(_fail)))
    if _fail:
        print("ПРОВАЛЕНО: %s" % ", ".join(_fail))
        sys.exit(1)
    print("все характеризационные тесты диспетчера _poll_178 пройдены")
    sys.exit(0)


if __name__ == "__main__":
    main()
