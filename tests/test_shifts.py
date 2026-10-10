# -*- coding: utf-8 -*-

import logging
import os
import tempfile
from datetime import date, datetime

from agent import shifts
from agent.pipe_shift import ShiftMixin

MSK = shifts.MSK


def _sched(workdays, roster=None, start="09:00", window=None):
    d = {"me": {"name": "K", "id": 1}, "shift_start": start,
         "roster": roster or {"korshunov": {"name": "Engineer02", "id": 2}},
         "workdays": workdays}
    if window is not None:
        d["handoff_window_minutes"] = window
    return shifts.Schedule(d)


def test_is_my_workday():
    s = _sched({"2026-08-01": "korshunov"})
    assert s.is_my_workday(date(2026, 8, 1))
    assert not s.is_my_workday(date(2026, 8, 2))


def test_roster_is_reference_only():


    s = _sched({"2026-08-01": "korshunov", "2026-08-05": None, "2026-08-09": "engineer_three"},
               roster={"korshunov": {"name": "Engineer02", "id": 2},
                       "engineer_three": {"name": "Engineer Three", "id": None}})
    assert not hasattr(s, "partner_for") and not hasattr(s, "me_id")
    assert s.is_my_workday(date(2026, 8, 5)) and s.is_my_workday(date(2026, 8, 9))
    assert not s.is_my_workday(date(2026, 8, 2))


def test_should_handoff_gates():
    s = _sched({"2026-08-01": "korshunov"})
    at9 = datetime(2026, 8, 1, 9, 0, tzinfo=MSK)
    at859 = datetime(2026, 8, 1, 8, 59, tzinfo=MSK)
    off = datetime(2026, 8, 2, 10, 0, tzinfo=MSK)
    assert s.should_handoff(at9, None)
    assert s.should_handoff(at859, None)
    assert not s.should_handoff(off, None)
    assert not s.should_handoff(at9, "2026-08-01")
    assert s.should_handoff(at9, "2026-07-28")


def test_handoff_window_20min():


    s = _sched({"2026-08-01": "korshunov"})
    at = lambda h, m: datetime(2026, 8, 1, h, m, tzinfo=MSK)
    assert s.handoff_state(at(8, 39), None) == "early"
    assert s.handoff_state(at(8, 40), None) == "go"
    assert s.handoff_state(at(9, 20), None) == "go"
    assert s.handoff_state(at(9, 21), None) == "late"
    assert s.handoff_state(at(22, 0), None) == "late"
    assert s.handoff_state(at(22, 0), "2026-08-01") == "done"
    assert s.handoff_state(datetime(2026, 8, 2, 9, 0, tzinfo=MSK), None) == "off"
    assert not s.should_handoff(at(22, 0), None)


def test_handoff_window_configurable():

    wide = _sched({"2026-08-01": "korshunov"}, window=120)
    assert wide.should_handoff(datetime(2026, 8, 1, 10, 59, tzinfo=MSK), None)
    assert not wide.should_handoff(datetime(2026, 8, 1, 11, 1, tzinfo=MSK), None)
    zero = _sched({"2026-08-01": "korshunov"}, window=0)
    assert zero.should_handoff(datetime(2026, 8, 1, 9, 0, tzinfo=MSK), None)
    assert not zero.should_handoff(datetime(2026, 8, 1, 9, 1, tzinfo=MSK), None)
    assert _sched({"2026-08-01": "korshunov"}, window="хрень").window_minutes == 20
    assert _sched({"2026-08-01": "korshunov"}, window=-5).window_minutes == 20


def test_load_missing():
    assert shifts.Schedule.load("/no/such/shift.json") is None


class _FakeRedmine:
    def __init__(self, issues):
        self.issues = issues
        self.reassigned = []

    def query_issues(self, qid, project=None, max_pages=10):
        return self.issues

    def reassign(self, iid, aid):
        self.reassigned.append((iid, aid))


class _FakeJournal:
    def __init__(self):
        self.records = []

    def record(self, key, verdict, **kw):
        self.records.append((verdict, kw))


class _Ag(ShiftMixin):
    pass


def _agent(issues, dry_run, sched, at=datetime(2026, 8, 1, 9, 10, tzinfo=MSK),
           roles={"chief_engineer": 1, "engineer": 2}, known=None):
    a = _Ag()
    a.redmine = _FakeRedmine(issues)
    a.journal = _FakeJournal()
    a.dry_run = dry_run
    a.log = logging.getLogger("test.shift")
    a.cfg = {"assigned_to_id": 1}
    if roles is not None:
        a.cfg["roles"] = roles
    if known is not None:
        a.cfg["known_people"] = known
    a.shift_cfg = {"enabled": True, "query_id": 178, "in_work_status": "В процессе: В работе",
                   "client_a_clients": ["Клиент A"], "second_line_group": "Вторая линия",
                   "second_line_ids": [602, 596]}
    a.schedule = sched
    sched.now = lambda: at
    a._handoff_stamp_file = tempfile.mktemp(prefix="handoff_test_")
    return a


def _issue(iid, project, assignee_id, assignee_name, status="В процессе: В работе"):
    return {"id": iid, "project_name": project, "status": status,
            "assignee_id": assignee_id, "assignee_name": assignee_name, "subject": "s%d" % iid}


def test_sweep_routing_live():

    issues = [
        _issue(1, "Клиент A Т/П", 999, "Чужой"),
        _issue(2, "Клиент C. Площадка C5", 999, "Чужой"),
        _issue(3, "Клиент C. Площадка C5", 602, "Engineer 01"),
        _issue(4, "Клиент A Т/П", 1, "K"),
        _issue(5, "Клиент C. Площадка C5", 999, "Чужой", status="Новая"),
        _issue(6, "Клиент C. Площадка C5", None, None),
    ]
    a = _agent(issues, dry_run=False, sched=_sched({"2026-08-01": "korshunov"}))
    a._shift_handoff()
    r = dict(a.redmine.reassigned)
    assert r == {1: 1, 2: 2, 6: 2}


def test_sweep_second_line_skipped_by_id_only():

    issues = [
        _issue(10, "Клиент C. Площадка C5", 602, "Engineer 01"),
        _issue(11, "Клиент C. Площадка C5", 4242, "Вторая линия"),
    ]
    a = _agent(issues, dry_run=False, sched=_sched({"2026-08-01": "korshunov"}))
    a._shift_handoff()
    assert a.redmine.reassigned == [(11, 2)]


def test_sweep_solo_day_still_uses_roles():


    issues = [_issue(20, "Клиент C. Площадка C5", 999, "Чужой")]
    a = _agent(issues, dry_run=False, sched=_sched({"2026-08-01": None}))
    a._shift_handoff()
    assert a.redmine.reassigned == [(20, 2)]


def test_sweep_dry_run_no_writes_but_stamped():
    import json
    issues = [_issue(30, "Клиент A Т/П", 999, "Чужой")]
    a = _agent(issues, dry_run=True, sched=_sched({"2026-08-01": "korshunov"}))
    a._shift_handoff()
    assert a.redmine.reassigned == []
    assert any(v == "handoff_dry_run" for v, _ in a.journal.records)
    with open(a._handoff_stamp_file, encoding="utf-8") as f:
        assert json.load(f)["date"] == "2026-08-01"


def test_dry_stamp_does_not_block_live_same_day():

    sched = _sched({"2026-08-01": "korshunov"})
    stamp = tempfile.mktemp(prefix="handoff_test_")
    a1 = _agent([_issue(50, "Клиент A Т/П", 999, "Ч")], dry_run=True, sched=sched)
    a1._handoff_stamp_file = stamp
    a1._shift_handoff()
    assert a1.redmine.reassigned == []
    a2 = _agent([_issue(50, "Клиент A Т/П", 999, "Ч")], dry_run=False,
                sched=_sched({"2026-08-01": "korshunov"}))
    a2._handoff_stamp_file = stamp
    a2._shift_handoff()
    assert a2.redmine.reassigned == [(50, 1)]


def test_sweep_not_my_day_noop():
    issues = [_issue(40, "Клиент A Т/П", 999, "Чужой")]
    a = _agent(issues, dry_run=False, sched=_sched({"2026-08-05": "korshunov"}),
               at=datetime(2026, 8, 1, 9, 10, tzinfo=MSK))
    a._shift_handoff()
    assert a.redmine.reassigned == []


def test_sweep_outside_window_noop_but_warns(caplog):


    issues = [_issue(41, "Клиент A Т/П", 999, "Чужой")]
    a = _agent(issues, dry_run=False, sched=_sched({"2026-08-01": "korshunov"}),
               at=datetime(2026, 8, 1, 22, 0, tzinfo=MSK))
    with caplog.at_level(logging.WARNING, logger="test.shift"):
        a._shift_handoff()
        a._shift_handoff()
    assert a.redmine.reassigned == []
    assert sum("окно" in r.message for r in caplog.records) == 1
    assert not os.path.exists(a._handoff_stamp_file)


def test_roles_are_the_only_source():


    issues = [
        _issue(60, "Клиент A Т/П", 999, "Чужой"),
        _issue(61, "Клиент C. Площадка C5", 999, "Чужой"),
    ]
    a = _agent(issues, dry_run=False, sched=_sched({"2026-08-01": "korshunov"}),
               roles={"chief_engineer": 555, "engineer": 666})
    a._shift_handoff()
    assert dict(a.redmine.reassigned) == {60: 555, 61: 666}


def test_partner_of_the_day_does_not_route(caplog):


    sched = _sched({"2026-08-01": "engineer_three"},
                   roster={"korshunov": {"name": "Engineer02", "id": 2},
                           "engineer_three": {"name": "Engineer Three", "id": None}})
    a = _agent([_issue(65, "Клиент C. Площадка C5", 999, "Чужой")], dry_run=False, sched=sched)
    a._shift_handoff()
    assert a.redmine.reassigned == [(65, 2)]


def test_sweep_skipped_when_role_unset(caplog):

    for roles in ({"chief_engineer": None, "engineer": 2},
                  {"chief_engineer": 1, "engineer": None}):
        a = _agent([_issue(90, "Клиент A Т/П", 999, "Чужой")], dry_run=False,
                   sched=_sched({"2026-08-01": "korshunov"}), roles=roles)
        with caplog.at_level(logging.WARNING, logger="test.shift"):
            caplog.clear()
            a._shift_handoff()
            a._shift_handoff()
        assert a.redmine.reassigned == []
        assert sum("не задано" in r.message for r in caplog.records) == 1
        assert not os.path.exists(a._handoff_stamp_file)


def test_journal_labels_human_readable():

    issues = [_issue(95, "Клиент A Т/П", 999, "Чужой"), _issue(96, "Клиент C. Площадка C5", 999, "Чужой")]
    a = _agent(issues, dry_run=True, sched=_sched({"2026-08-01": "korshunov"}),
               roles={"chief_engineer": 1, "engineer": 2},
               known={"Engineer 01": 1, "Engineer 02": 2})
    a._shift_handoff()
    notes = " | ".join(kw.get("note", "") for _, kw in a.journal.records)
    assert "@chiefEngineer (Engineer 01)" in notes
    assert "@engineer (Engineer 02)" in notes


def test_role_id_without_known_name_labeled_by_id():

    issues = [_issue(97, "Клиент C. Площадка C5", 999, "Чужой")]
    a = _agent(issues, dry_run=True, sched=_sched({"2026-08-01": None}),
               roles={"chief_engineer": 555, "engineer": 4242}, known={})
    a._shift_handoff()
    notes = " | ".join(kw.get("note", "") for _, kw in a.journal.records)
    assert "@engineer (id 4242)" in notes


def test_sweep_does_not_steal_locks_from_dba_group():


    issues = [
        _issue(20, "Клиент C. Площадка C5", 547, "DBA"),
        _issue(21, "Клиент C. Площадка C5", 999, "Чужой"),
    ]
    a = _agent(issues, dry_run=False, sched=_sched({"2026-08-01": "korshunov"}))
    a.cfg["locks"] = {"dba_group_id": 547}
    a._shift_handoff()
    assert a.redmine.reassigned == [(21, 2)]


def test_sweep_without_dba_config_still_works():

    a = _agent([_issue(22, "Клиент C. Площадка C5", 999, "Ч")], dry_run=False,
               sched=_sched({"2026-08-01": "korshunov"}))
    a._shift_handoff()
    assert a.redmine.reassigned == [(22, 2)]


def test_sweep_stamp_is_per_mode_not_overwritten():


    import json as _json
    sched = _sched({"2026-08-01": "korshunov"})
    a = _agent([_issue(30, "Клиент C. Площадка C5", 999, "Ч")], dry_run=False, sched=sched)
    a._shift_handoff()
    assert a.redmine.reassigned == [(30, 2)]
    stamp = _json.load(open(a._handoff_stamp_file))
    assert stamp["by_mode"]["live"] == "2026-08-01"

    b = _agent([_issue(31, "Клиент C. Площадка C5", 999, "Ч")], dry_run=True, sched=_sched({"2026-08-01": "korshunov"}))
    b._handoff_stamp_file = a._handoff_stamp_file
    b._shift_handoff()
    st2 = _json.load(open(b._handoff_stamp_file))
    assert st2["by_mode"]["live"] == "2026-08-01"
    assert st2["by_mode"]["dry"] == "2026-08-01"

    c = _agent([_issue(32, "Клиент C. Площадка C5", 999, "Ч")], dry_run=False, sched=_sched({"2026-08-01": "korshunov"}))
    c._handoff_stamp_file = a._handoff_stamp_file
    c._shift_handoff()
    assert c.redmine.reassigned == [], "второй боевой свип в тот же день"
