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
import urllib.error
import pytest
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import agent.orchestrator as O


class FakeRedmine:
    def __init__(self, url, api_key):
        self.url = url
        self.api_key = api_key

        self.dashboard_result = []
        self.new_result = []
        self.dashboard_calls = 0
        self.new_calls = 0
        self.created = []
        self.updated = []
        self.notes = []
        self.next_id = 4242
        self.create_error = None
        self.update_error = None

    def dashboard_issues(self, query_id, project, max_pages=5):
        self.dashboard_calls += 1
        if isinstance(self.dashboard_result, BaseException):
            raise self.dashboard_result
        return [dict(x) for x in self.dashboard_result]

    def new_issues(self, tracker_id, status_id=1, max_pages=3):
        self.new_calls += 1
        if isinstance(self.new_result, BaseException):
            raise self.new_result
        return [dict(x) for x in self.new_result]

    def create_issue(self, project_id, tracker_id, subject, description="",
                     priority_id=None, assigned_to_id=None, is_private=False,
                     custom_fields=None):
        self.created.append({"project_id": project_id, "tracker_id": tracker_id,
                             "subject": subject, "description": description,
                             "priority_id": priority_id, "assigned_to_id": assigned_to_id,
                             "is_private": is_private, "custom_fields": custom_fields})
        if self.create_error is not None:
            raise self.create_error
        return self.next_id

    def update_status(self, issue_id, status_id):
        self.updated.append((issue_id, status_id))
        if self.update_error is not None:
            raise self.update_error

    def add_note(self, issue_id, note, uploads=None, private=True):
        self.notes.append({"issue_id": issue_id, "note": note, "private": private})


class FakeMail:
    def __init__(self, host, port, login, password, folder="INBOX"):
        self.host, self.port, self.login, self.password, self.folder = (
            host, port, login, password, folder)
        self.queue = []
        self.uidnext_val = 2000
        self.uidvalidity_val = None
        self.fetch_calls = 0
        self.closed = False

    def uidnext(self):
        return self.uidnext_val

    def uidvalidity(self):
        return self.uidvalidity_val

    def fetch_new(self, last_uid, body_limit=4000, max_bytes=2_000_000):
        self.fetch_calls += 1
        out, self.queue = self.queue, []
        return out

    def close(self):
        self.closed = True


@pytest.fixture(autouse=True)
def isolate_clients(monkeypatch):
    monkeypatch.setattr(O, "RedmineClient", FakeRedmine)
    monkeypatch.setattr(O, "MailClient", FakeMail)
    monkeypatch.setattr(O, "tr", types.SimpleNamespace(status=lambda *a, **k: None, trace=lambda *a, **k: None))
    previous = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    yield
    logging.disable(previous)


BASE_CONFIG = {
    "imap": {"host": "imap.test", "port": 993, "folder": "INBOX"},
    "dry_run": True,
    "max_issues_per_hour": 3,
    "max_mail_age_minutes": 60,
    "max_mail_bytes": 2_000_000,
    "body_excerpt_chars": 4000,
    "llm": {"enabled": False},
    "tracker_id": 65,
    "priority_id": None,
    "assigned_to_id": 1,


    "roles": {"chief_engineer": 1, "engineer": 1},
    "is_private": True,
    "work_status_id": 2,
    "description_mode": "empty",
    "sender_blacklist": ["sender-012@example.invalid"],
    "markers": [
        {"key": "healthscript", "pattern": r"(?i)health\s*script"},
        {"key": "alertmark", "pattern": r"(?i)тест\s*алерт"},
    ],
    "dedup": {
        "query_id": 178,
        "query_project": "example-project-001",
        "blocking_statuses": ["В процессе: В работе", "Ожидание ответа от клиента", "Новая"],
        "also_new_tracker_id": 65,
    },
    "routing": {
        "TESTSRV": {"project_id": 100, "client": "Тест Клиент"},
        "TESTSRV2": {"project_id": 200, "client": "Тест Клиент 2"},
    },


}

SECRETS = {
    "redmine_url": "http://service.example.invalid",
    "redmine_api_key": "test-key",
    "imap_login": "agent@test",
    "imap_password": "x",
}

_ROOTS = []


def build_agent(dry_run, *, last_uid=1000, cfg_overrides=None):

    root = tempfile.mkdtemp(prefix="wa_pipe_")
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
    if last_uid is not None:
        with open(os.path.join(root, "state", "last_uid.json"), "w", encoding="utf-8") as f:
            json.dump({"last_uid": last_uid}, f)
    return O.Agent(root, dry_run_override=dry_run)


def make_mail(mid, subject="", body="", from_="sender-016@example.invalid",
              uid=1001, internal_ts=None, date="Mon, 13 Jul 2026 10:00:00 +0300"):


    if internal_ts is None:
        internal_ts = time.time()
    return types.SimpleNamespace(uid=uid, message_id=mid, subject=subject, body=body,
                                 from_=from_, date=date, internal_ts=internal_ts)


def fresh_stats(new=0):


    return {"new": new, "created": 0, "dry": 0, "dup": 0, "stale": 0, "unknown_srv": 0,
            "llm_routed": 0, "no_marker": 0, "blacklisted": 0, "skipped": 0, "pinged": 0}


def journal_records(agent):
    recs = []
    p = os.path.join(agent.root, "state", "processed.jsonl")
    if not os.path.exists(p):
        return recs
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                recs.append(json.loads(line))
    return recs


def verdicts_for(agent, mid):
    return [r["verdict"] for r in journal_records(agent) if r.get("message_id") == mid]


def cursor_on_disk(agent):
    with open(agent._cursor_file, encoding="utf-8") as f:
        return json.load(f)["last_uid"]


_fail = []
_count = 0


def check(name, cond, extra=""):
    global _count
    _count += 1
    print("%-64s %s %s" % (name, "OK" if cond else "FAIL", extra))
    if not cond:
        _fail.append(name)
        assert cond, f"{name}: {extra}"


def test_agent_builds():
    a = build_agent(dry_run=True)
    check("Agent собран на фейках (redmine/mailer подменены, курсор из last_uid.json)",
          isinstance(a.redmine, FakeRedmine) and isinstance(a.mailer, FakeMail)
          and a.cursor == 1000 and a.dry_run is True, "cursor=%s" % a.cursor)

    b = build_agent(dry_run=False, last_uid=None)
    check("last_uid отсутствует -> курсор = mailer.uidnext()-1 (первый запуск)",
          b.cursor == b.mailer.uidnext_val - 1 and b.dry_run is False, "cursor=%s" % b.cursor)


def test_seen_idempotency():
    a = build_agent(dry_run=True)
    mid = "<dup-1@test>"

    a.journal.record(mid, "duplicate", subject="раньше")
    before = len(journal_records(a))
    a.redmine.dashboard_result = []
    st = fresh_stats()
    done = a._process(make_mail(mid, subject="Тест Алерт", body="Server: TESTSRV"), st, {})
    after = len(journal_records(a))
    check("seen: письмо с уже-записанным message_id -> _process True, skipped++, дальше не идём",
          done is True and st["skipped"] == 1 and after == before
          and a.redmine.dashboard_calls == 0 and a.redmine.created == [],
          "skipped=%s dash_calls=%s" % (st["skipped"], a.redmine.dashboard_calls))


def test_blacklist_and_no_marker():
    a = build_agent(dry_run=True)
    st = fresh_stats()
    done = a._process(make_mail("<bl-1@test>", subject="что угодно", body="тело",
                                from_="sender-012@example.invalid"), st, {})
    check("blacklist: отправитель в ЧС -> True, вердикт 'blacklisted', dashboard не тронут",
          done is True and st["blacklisted"] == 1
          and verdicts_for(a, "<bl-1@test>") == ["blacklisted"]
          and a.redmine.dashboard_calls == 0)

    st2 = fresh_stats()
    done2 = a._process(make_mail("<nm-1@test>", subject="случайная тема", body="без признаков",
                                 from_="sender-017@example.invalid"), st2, {})
    check("no_marker: маркер не найден -> True, вердикт 'no_marker'",
          done2 is True and st2["no_marker"] == 1
          and verdicts_for(a, "<nm-1@test>") == ["no_marker"])


_PINGS = {"mail_pings": {"enabled": True, "rules": [
    {"key": "scheduler_pbl", "subject": r"(?i)LTWMS\s+Шедуллер\s+статус", "text": "ШЕДУЛЕР FIRING"},
    {"key": "datasource_nodata", "subject": "(?i)DatasourceNoData", "text": "Datasource FIRING"}]}}


class _FakeNotifier:


    def __init__(self):
        self.sent = []

    def send(self, event, title, text, issue_id=None):
        self.sent.append((event, title, text, issue_id))


def test_mail_ping_firing_sends_without_issue():

    a = build_agent(dry_run=False, cfg_overrides=_PINGS)
    a.notifier = _FakeNotifier()
    st = fresh_stats()
    subj = "[FIRING:1] LTWMS Шедуллер статус EXAMPLE_WMS (Распределение товаров PBL)"
    done = a._process(make_mail("<ping-1@test>", subject=subj, body="<html>grafana</html>",
                                from_="Grafana <sender-019@example.invalid>"), st, {})
    check("ping FIRING: True, pinged++, вердикт 'mail_ping', заявка НЕ создана",
          done is True and st["pinged"] == 1 and st["no_marker"] == 0
          and verdicts_for(a, "<ping-1@test>") == ["mail_ping"]
          and a.redmine.created == [] and a.redmine.dashboard_calls == 0)
    check("ping FIRING: в мессенджер ушёл ровно текст правила («ШЕДУЛЕР FIRING»)",
          a.notifier.sent == [("mail_ping", "ШЕДУЛЕР FIRING",
                               "%s (алертов: 1)" % subj, None)],
          repr(a.notifier.sent))


def test_mail_ping_any_alert_count():

    a = build_agent(dry_run=False, cfg_overrides=_PINGS)
    a.notifier = _FakeNotifier()
    st = fresh_stats()
    a._process(make_mail("<ping-5@test>",
                         subject="[FIRING:5] DatasourceNoData EXAMPLE_WMS (d9060d8b A Подрядчик)",
                         body="x"), st, {})
    check("ping [FIRING:5] DatasourceNoData -> «Datasource FIRING», алертов 5",
          st["pinged"] == 1 and a.notifier.sent
          and a.notifier.sent[0][1] == "Datasource FIRING"
          and "алертов: 5" in a.notifier.sent[0][2], repr(a.notifier.sent))


def test_mail_ping_resolved_is_silent():

    a = build_agent(dry_run=False, cfg_overrides=_PINGS)
    a.notifier = _FakeNotifier()
    st = fresh_stats()
    done = a._process(make_mail("<ping-res@test>",
                                subject="[RESOLVED] LTWMS Шедуллер статус EXAMPLE_WMS (Распределение товаров PBL)",
                                body="x"), st, {})
    check("ping RESOLVED: молчим, вердикт 'no_marker', pinged=0",
          done is True and st["pinged"] == 0 and st["no_marker"] == 1
          and verdicts_for(a, "<ping-res@test>") == ["no_marker"]
          and a.notifier.sent == [])


def test_mail_ping_stale_not_sent():

    a = build_agent(dry_run=False, cfg_overrides=_PINGS)
    a.notifier = _FakeNotifier()
    st = fresh_stats()
    old_ts = time.time() - 3 * 3600
    done = a._process(make_mail("<ping-old@test>", subject="[FIRING:2] DatasourceNoData EXAMPLE_WMS",
                                body="x", internal_ts=old_ts), st, {})
    check("ping stale: True, stale++, вердикт 'ping_stale', мессенджеры молчат",
          done is True and st["stale"] == 1 and st["pinged"] == 0
          and verdicts_for(a, "<ping-old@test>") == ["ping_stale"]
          and a.notifier.sent == [])


def test_mail_ping_does_not_shadow_markers():

    cfg = dict(_PINGS)
    cfg["mail_pings"] = {"enabled": True, "rules": [
        {"key": "hs_like", "subject": "(?i)health", "text": "НЕ ДОЛЖНО УЙТИ"}]}
    a = build_agent(dry_run=True, cfg_overrides=cfg)
    a.notifier = _FakeNotifier()
    st = fresh_stats()
    a._process(make_mail("<ping-mk@test>", subject="[FIRING:1] Health Script отчёт",
                         body="Расхождения в пунктах:\n<12> comparing\nServer: TESTSRV"), st, {})

    pings_sent = [e for e, *_ in a.notifier.sent if e == "mail_ping"]
    check("маркер важнее пинга: письмо ушло в ветку HealthScript, пинга нет",
          st["pinged"] == 0 and pings_sent == []
          and "mail_ping" not in verdicts_for(a, "<ping-mk@test>"),
          repr(verdicts_for(a, "<ping-mk@test>")))


def test_healthscript_ignored_points():
    a = build_agent(dry_run=True)
    body = "Health Script отчёт.\nРасхождения в пунктах:\n<11> comparing QtyExpected skuxloc vs lotxlocxid"
    st = fresh_stats()
    done = a._process(make_mail("<hs-11@test>", subject="Health Script", body=body), st, {})
    check("healthscript п.11-only -> True, вердикт 'healthscript_ignored'",
          done is True and st["skipped"] == 1
          and verdicts_for(a, "<hs-11@test>") == ["healthscript_ignored"]
          and a.redmine.dashboard_calls == 0)

    st30 = fresh_stats()
    a._process(make_mail("<hs-30@test>", subject="Health Script",
                         body="Health Script\nРасхождения в пунктах:\n<30> comparing ..."), st30, {})
    check("healthscript п.30-only -> skip",
          st30["skipped"] == 1 and verdicts_for(a, "<hs-30@test>") == ["healthscript_ignored"])
    st1130 = fresh_stats()
    a._process(make_mail("<hs-11-30@test>", subject="Health Script",
                         body="Health Script\nРасхождения:\n<11> ...\n<30> ..."), st1130, {})
    check("healthscript 11+30 -> skip",
          st1130["skipped"] == 1 and verdicts_for(a, "<hs-11-30@test>") == ["healthscript_ignored"])


    body2 = "Health Script\nServer: TESTSRV\nРасхождения в пунктах:\n<12> ...\n<11> ..."
    st2 = fresh_stats()
    a._process(make_mail("<hs-multi@test>", subject="Health Script", body=body2), st2, {})
    check("healthscript многопунктовое ({11,12}) НЕ игнорируется (доходит до дедупа)",
          "healthscript_ignored" not in verdicts_for(a, "<hs-multi@test>")
          and a.redmine.dashboard_calls == 1)


def test_healthscript_cld_off_toggle():


    body = "Health Script\nServer: TESTSRV\nРасхождения:\n<12> ...\n<11> ..."
    a = build_agent(dry_run=True, cfg_overrides={"healthscript_cld_off": True})
    st = fresh_stats()
    done = a._process(make_mail("<hs-cld@test>", subject="Health Script", body=body,
                                from_="sender-014@example.invalid"), st, {})
    check("healthscript CLD off=true -> пропуск без заявки (вердикт healthscript_cld_off)",
          done is True and st["skipped"] == 1
          and verdicts_for(a, "<hs-cld@test>") == ["healthscript_cld_off"]
          and a.redmine.dashboard_calls == 0)

    a2 = build_agent(dry_run=True, cfg_overrides={"healthscript_cld_off": False})
    st2 = fresh_stats()
    a2._process(make_mail("<hs-eva2@test>", subject="Health Script", body=body,
                          from_="sender-014@example.invalid"), st2, {})
    check("healthscript CLD off=false -> НЕ пропускаем (доходит до дедупа)",
          "healthscript_cld_off" not in verdicts_for(a2, "<hs-eva2@test>")
          and a2.redmine.dashboard_calls == 1)

    a3 = build_agent(dry_run=True, cfg_overrides={"healthscript_cld_off": True})
    st3 = fresh_stats()
    a3._process(make_mail("<hs-oth@test>", subject="Health Script", body=body,
                          from_="sender-015@example.invalid"), st3, {})
    check("healthscript CLD off + не-CLD отправитель -> обрабатывается (чужих не отсекаем)",
          "healthscript_cld_off" not in verdicts_for(a3, "<hs-oth@test>")
          and a3.redmine.dashboard_calls == 1)


def test_stale_skipped():
    a = build_agent(dry_run=True)
    old_ts = time.time() - 90 * 60
    st = fresh_stats()
    done = a._process(make_mail("<stale-1@test>", subject="Тест Алерт", body="Server: TESTSRV",
                                internal_ts=old_ts), st, {})
    check("stale: письму 90 мин (лимит 60) -> True, вердикт 'stale_skipped', до дедупа не доходим",
          done is True and st["stale"] == 1
          and verdicts_for(a, "<stale-1@test>") == ["stale_skipped"]
          and a.redmine.dashboard_calls == 0)


def test_dry_run_create_and_inpass_dup():
    a = build_agent(dry_run=True)
    a.redmine.dashboard_result = []
    cache = {}
    st = fresh_stats()
    done = a._process(make_mail("<dry-a@test>", subject="Тест Алерт по TESTSRV",
                                body="Server: TESTSRV"), st, cache)
    synth = [d for d in cache.get("dash", []) if d.get("id") == 0]
    check("dry-run: валидное письмо, чистый дашборд -> True, вердикт 'dry_run_create', create НЕ вызван",
          done is True and st["dry"] == 1
          and "dry_run_create" in verdicts_for(a, "<dry-a@test>")
          and a.redmine.created == []
          and len(synth) == 1 and synth[0]["project_id"] == 100,
          "created=%s synth=%s" % (a.redmine.created, synth))

    st2 = fresh_stats()
    done2 = a._process(make_mail("<dry-b@test>", subject="Тест Алерт по TESTSRV",
                                 body="Server: TESTSRV"), st2, cache)
    check("dry-run: второе письмо того же типа в проходе -> True, вердикт 'duplicate' (по синтетике)",
          done2 is True and st2["dup"] == 1
          and "duplicate" in verdicts_for(a, "<dry-b@test>")
          and a.redmine.created == [])


def test_dedup_by_dashboard():
    a = build_agent(dry_run=False)
    a.redmine.dashboard_result = [
        {"id": 555, "project_id": 100, "project_name": "Тест Клиент",
         "subject": "Тест Алерт висящая", "status": "В процессе: В работе"}]
    st = fresh_stats()
    done = a._process(make_mail("<dd-1@test>", subject="Тест Алерт свежий",
                                body="Server: TESTSRV"), st, {})
    check("дедуп-дашборд: блокирующая заявка того же проекта+типа -> True, 'duplicate', create НЕ вызван",
          done is True and st["dup"] == 1
          and "duplicate" in verdicts_for(a, "<dd-1@test>")
          and a.redmine.created == [])


def test_defer_process_level():
    a = build_agent(dry_run=False)
    a.redmine.dashboard_result = urllib.error.URLError("redmine down")
    mid = "<defer-1@test>"
    st = fresh_stats()
    done = a._process(make_mail(mid, subject="Тест Алерт", body="Server: TESTSRV"), st, {})
    terminal = [r for r in journal_records(a) if r.get("message_id") == mid and not r.get("interim")]
    check("defer: dashboard бросил URLError -> _process False, create НЕ вызван, mid НЕ seen",
          done is False and a.redmine.created == [] and a.journal.seen(mid) is False
          and terminal == [],
          "verdicts=%s" % verdicts_for(a, mid))


def test_defer_poll_level():
    a = build_agent(dry_run=False, last_uid=1000)
    a.redmine.dashboard_result = urllib.error.URLError("redmine down")
    mails = [make_mail("<pq-1@test>", subject="Тест Алерт", body="Server: TESTSRV", uid=1001),
             make_mail("<pq-2@test>", subject="Тест Алерт", body="Server: TESTSRV", uid=1002),
             make_mail("<pq-3@test>", subject="Тест Алерт", body="Server: TESTSRV", uid=1003)]
    a.mailer.queue = list(mails)
    a.poll()
    deferred = a._deferred_mail
    check("poll/defer: курсор НЕ продвинулся (в памяти и на диске), create НЕ вызван",
          a.cursor == 1000 and cursor_on_disk(a) == 1000 and a.redmine.created == [],
          "cursor=%s disk=%s" % (a.cursor, cursor_on_disk(a)))
    check("poll/defer: ВЕСЬ хвост очереди помечен в _deferred_mail (setdefault на первом дефере)",
          all(m.message_id in deferred for m in mails) and len(deferred) == 3,
          "deferred=%d" % len(deferred))


def test_age_freeze():
    a = build_agent(dry_run=True)
    a.redmine.dashboard_result = []
    now = time.time()
    old_ts = now - 90 * 60

    st_ctrl = fresh_stats()
    a._process(make_mail("<frz-ctrl@test>", subject="Тест Алерт", body="Server: TESTSRV",
                         internal_ts=old_ts), st_ctrl, {})
    check("возраст-контроль: старое письмо БЕЗ защёлки -> 'stale_skipped'",
          st_ctrl["stale"] == 1 and "stale_skipped" in verdicts_for(a, "<frz-ctrl@test>"))


    frz_mid = "<frz-1@test>"
    a._deferred_mail[frz_mid] = now - 40 * 60
    st_frz = fresh_stats()
    done = a._process(make_mail(frz_mid, subject="Тест Алерт", body="Server: TESTSRV",
                                internal_ts=old_ts), st_frz, {})
    vs = verdicts_for(a, frz_mid)
    check("возраст-заморозка: то же письмо с _deferred_mail(40мин) -> НЕ stale, доходит до 'dry_run_create'",
          done is True and st_frz["stale"] == 0 and "stale_skipped" not in vs
          and "dry_run_create" in vs, "verdicts=%s" % vs)


def test_rate_limit():
    a = build_agent(dry_run=False)
    a.redmine.dashboard_result = []
    for i in range(3):
        a.journal.record("<seed-%d@test>" % i, "created", subject="s", issue_id=i, project_id=100)
    check("предпосылка: created_last_hour() == лимит (3)",
          a.journal.created_last_hour() == 3, str(a.journal.created_last_hour()))
    mid = "<rl-1@test>"
    st = fresh_stats()
    done = a._process(make_mail(mid, subject="Тест Алерт", body="Server: TESTSRV"), st, {})
    terminal = [r for r in journal_records(a) if r.get("message_id") == mid and not r.get("interim")]
    check("лимит/час достигнут: валидное письмо -> _process False (отложено), create НЕ вызван, НЕ seen",
          done is False and a.redmine.created == [] and a.journal.seen(mid) is False
          and terminal == [])


def test_live_create_taken():
    a = build_agent(dry_run=False)
    a.redmine.dashboard_result = []
    a.redmine.next_id = 4242
    mid = "<live-1@test>"
    st = fresh_stats()
    done = a._process(make_mail(mid, subject="Тест Алерт боевой", body="Server: TESTSRV"), st, {})
    vs = verdicts_for(a, mid)
    call = a.redmine.created[0] if a.redmine.created else {}
    check("боевое: create вызван (проект 100, трекер 65, на 1, приватная), update_status(4242,2)",
          done is True and len(a.redmine.created) == 1
          and call.get("project_id") == 100 and call.get("tracker_id") == 65
          and call.get("assigned_to_id") == 1 and call.get("is_private") is True
          and a.redmine.updated == [(4242, 2)],
          "call=%s upd=%s" % (call, a.redmine.updated))
    check("боевое: вердикты 'created' (issue_id=4242) + interim 'issue_taken', stats.created==1",
          "created" in vs and "issue_taken" in vs and st["created"] == 1
          and any(r.get("verdict") == "created" and r.get("issue_id") == 4242
                  for r in journal_records(a)), "verdicts=%s" % vs)


def test_live_create_not_taken():
    a = build_agent(dry_run=False)
    a.redmine.dashboard_result = []
    a.redmine.next_id = 4242

    a.redmine.update_error = urllib.error.URLError("VPN flap")
    cache = {}
    mid = "<nt-1@test>"
    st = fresh_stats()
    done = a._process(make_mail(mid, subject="Тест Алерт боевой", body="Server: TESTSRV"), st, cache)
    created_rec = next((r for r in journal_records(a)
                        if r.get("message_id") == mid and r.get("verdict") == "created"), None)
    check("боевое/не взята: update_status упал -> 'created' с пометкой «НЕ взята», issue_taken НЕТ",
          done is True and created_rec is not None
          and "НЕ взята" in (created_rec.get("note") or "")
          and "issue_taken" not in verdicts_for(a, mid),
          "note=%r" % (created_rec.get("note") if created_rec else None))
    check("боевое/не взята: заявка #4242 ВСЁ РАВНО в cache['dash'] (append безусловный, :631)",
          any(d.get("id") == 4242 for d in cache.get("dash", [])))

    st2 = fresh_stats()
    done2 = a._process(make_mail("<nt-2@test>", subject="Тест Алерт боевой",
                                 body="Server: TESTSRV"), st2, cache)
    check("боевое/не взята: 2-е письмо того же типа в проходе -> 'duplicate' (не дублируем заявку)",
          done2 is True and st2["dup"] == 1 and "duplicate" in verdicts_for(a, "<nt-2@test>")
          and len(a.redmine.created) == 1)


def test_live_create_not_taken_jsondecode():


    a = build_agent(dry_run=False)
    a.redmine.dashboard_result = []
    a.redmine.next_id = 4242
    a.redmine.update_error = json.JSONDecodeError("Expecting value", "битое-тело", 0)
    cache = {}
    mid = "<ntj-1@test>"
    st = fresh_stats()
    done = a._process(make_mail(mid, subject="Тест Алерт боевой", body="Server: TESTSRV"), st, cache)
    created_rec = next((r for r in journal_records(a)
                        if r.get("message_id") == mid and r.get("verdict") == "created"), None)
    check("JSONDecode на PUT: _process НЕ крашит -> 'created' + «НЕ взята», issue_taken НЕТ",
          done is True and created_rec is not None
          and "НЕ взята" in (created_rec.get("note") or "")
          and "issue_taken" not in verdicts_for(a, mid),
          "done=%s rec=%s" % (done, bool(created_rec)))
    st2 = fresh_stats()
    a._process(make_mail("<ntj-2@test>", subject="Тест Алерт боевой", body="Server: TESTSRV"), st2, cache)
    check("JSONDecode на PUT: заявка в cache -> 2-е письмо 'duplicate', create РОВНО раз (нет дубля)",
          any(d.get("id") == 4242 for d in cache.get("dash", []))
          and st2["dup"] == 1 and len(a.redmine.created) == 1)


def test_poll_advances_cursor():
    a = build_agent(dry_run=True, last_uid=1000)
    a.redmine.dashboard_result = []
    a.mailer.queue = [
        make_mail("<adv-1@test>", subject="Тест Алерт A", body="Server: TESTSRV", uid=1001),
        make_mail("<adv-2@test>", subject="Тест Алерт B", body="Server: TESTSRV2", uid=1002)]
    stats = a.poll()
    dvals = [r["verdict"] for r in journal_records(a) if r.get("verdict") == "dry_run_create"]
    check("poll/успех: курсор 1000 -> 1002 (в памяти и на диске), _deferred_mail пуст",
          a.cursor == 1002 and cursor_on_disk(a) == 1002 and a._deferred_mail == {},
          "cursor=%s disk=%s" % (a.cursor, cursor_on_disk(a)))
    check("poll/успех: оба письма -> dry_run_create, stats.new==2, stats.dry==2",
          len(dvals) == 2 and stats["new"] == 2 and stats["dry"] == 2,
          "dry=%s new=%s" % (stats["dry"], stats["new"]))


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    try:
        test_agent_builds()
        test_seen_idempotency()
        test_blacklist_and_no_marker()
        test_mail_ping_firing_sends_without_issue()
        test_mail_ping_any_alert_count()
        test_mail_ping_resolved_is_silent()
        test_mail_ping_stale_not_sent()
        test_mail_ping_does_not_shadow_markers()
        test_healthscript_ignored_points()
        test_healthscript_cld_off_toggle()
        test_healthscript_content_as_comment()
        test_live_create_engineer_role_and_reason_cf()
        test_mail_take_follows_role_toggles()
        test_mail_client_a_goes_to_chief()
        test_stale_skipped()
        test_dry_run_create_and_inpass_dup()
        test_dedup_by_dashboard()
        test_defer_process_level()
        test_defer_poll_level()
        test_age_freeze()
        test_rate_limit()
        test_live_create_taken()
        test_live_create_not_taken()
        test_live_create_not_taken_jsondecode()
        test_poll_advances_cursor()
    finally:
        for r in _ROOTS:
            shutil.rmtree(r, ignore_errors=True)

    print("\nвсего проверок: %d, провалено: %d" % (_count, len(_fail)))
    if _fail:
        print("ПРОВАЛЕНО: %s" % ", ".join(_fail))
        sys.exit(1)
    print("все характеризационные тесты почтовой трубы пройдены")
    sys.exit(0)


def test_live_create_engineer_role_and_reason_cf():

    a = build_agent(dry_run=False, cfg_overrides={
        "roles": {"chief_engineer": 1, "engineer": 2},
        "reason_custom_field": {"id": 109, "value": "Превентивные мероприятия"}})
    a.redmine.dashboard_result = []
    a.redmine.next_id = 5000
    st = fresh_stats()
    done = a._process(make_mail("<b19-1@test>", subject="Тест Алерт роль",
                                body="Server: TESTSRV"), st, {})
    call = a.redmine.created[0] if a.redmine.created else {}
    check("Блок 1.9: заявка на @engineer (2), CF 109 «Превентивные мероприятия»",
          done is True and call.get("assigned_to_id") == 2
          and call.get("custom_fields") == [{"id": 109, "value": "Превентивные мероприятия"}],
          "call=%s" % call)


def test_healthscript_content_as_comment():


    a = build_agent(dry_run=False)
    a.redmine.dashboard_result = []
    a.redmine.next_id = 5100
    body = "Health Script\nServer: TESTSRV\nРасхождения:\n<12> comparing X\n<11> comparing Y"
    st = fresh_stats()
    done = a._process(make_mail("<hs-cmt@test>", subject="Health Script", body=body), st, {})
    call = a.redmine.created[0] if a.redmine.created else {}
    note = a.redmine.notes[0] if a.redmine.notes else {}
    check("HealthScript: тело заявки ПУСТОЕ, контент - отдельным комментом (не private_notes)",
          done is True
          and call.get("description") == ""
          and note.get("issue_id") == 5100 and note.get("private") is False
          and "<12> comparing X" in note.get("note", "")
          and "<11> comparing Y" in note.get("note", ""))


def test_mail_take_follows_role_toggles():


    a = build_agent(dry_run=False, cfg_overrides={
        "roles": {"chief_engineer": 1, "engineer": 2, "auto_take_engineer": False}})
    a.redmine.dashboard_result = []
    a.redmine.next_id = 7001
    done = a._process(make_mail("<mtake-off@test>", subject="Тест Алерт off",
                                body="Server: TESTSRV"), fresh_stats(), {})
    call = a.redmine.created[0] if a.redmine.created else {}
    check("кнопка «остальные» ВЫКЛ: заявка создана, назначенца нет, update_status НЕ вызван",
          done is True and bool(a.redmine.created) and call.get("assigned_to_id") is None
          and not a.redmine.updated,
          "assignee=%s upd=%s" % (call.get("assigned_to_id"), a.redmine.updated))


    a2 = build_agent(dry_run=False, cfg_overrides={
        "roles": {"chief_engineer": 1, "engineer": 2}})
    a2.redmine.dashboard_result = []
    a2.redmine.next_id = 7002
    a2._process(make_mail("<mtake-on@test>", subject="Тест Алерт on",
                          body="Server: TESTSRV"), fresh_stats(), {})
    call2 = a2.redmine.created[0] if a2.redmine.created else {}
    check("кнопка ВКЛ: заявка на @engineer (2) + update_status вызван",
          call2.get("assigned_to_id") == 2 and bool(a2.redmine.updated),
          "assignee=%s upd=%s" % (call2.get("assigned_to_id"), a2.redmine.updated))


def test_mail_client_a_goes_to_chief():

    routing = {"MAGSRV": {"project_id": 300, "client": "Клиент A Т/П"}}
    a = build_agent(dry_run=False, cfg_overrides={
        "routing": routing, "roles": {"chief_engineer": 1, "engineer": 2}})
    a.redmine.dashboard_result = []
    a.redmine.next_id = 7003
    a._process(make_mail("<mag-on@test>", subject="Тест Алерт клиент A",
                         body="Server: MAGSRV"), fresh_stats(), {})
    call = a.redmine.created[0] if a.redmine.created else {}
    check("Клиент A из почты -> @chiefEngineer (1), проект из routing",
          call.get("assigned_to_id") == 1 and call.get("project_id") == 300,
          "call=%s" % call)


    a2 = build_agent(dry_run=False, cfg_overrides={
        "routing": routing,
        "roles": {"chief_engineer": 1, "engineer": 2, "auto_take_chief": False}})
    a2.redmine.dashboard_result = []
    a2.redmine.next_id = 7004
    a2._process(make_mail("<mag-off@test>", subject="Тест Алерт клиент A off",
                          body="Server: MAGSRV"), fresh_stats(), {})
    call2 = a2.redmine.created[0] if a2.redmine.created else {}
    check("кнопка Клиент Aа ВЫКЛ: создана без назначенца, в работу не взята",
          call2.get("assigned_to_id") is None and not a2.redmine.updated,
          "assignee=%s upd=%s" % (call2.get("assigned_to_id"), a2.redmine.updated))


if __name__ == "__main__":
    main()
