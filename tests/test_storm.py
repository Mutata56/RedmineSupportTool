# -*- coding: utf-8 -*-


import logging
from datetime import datetime, timedelta, timezone

from agent.pipe_grafana import GrafanaMixin


class _FakeRedmine:
    def __init__(self):
        self.taken = []
        self.relations = []

    def take_issue(self, iid, aid, sid):
        self.taken.append((iid, aid, sid))

    def add_relation(self, iid, to_id):
        self.relations.append((iid, to_id))


class _FakeJournal:
    def __init__(self, seen_ids=()):
        self._seen = {"ticket-%d" % i for i in seen_ids}
        self.records = []

    def seen(self, key):
        return key in self._seen

    def record(self, key, verdict, **kw):
        self.records.append((verdict, kw))


class _Ag(GrafanaMixin):
    pass


def _agent(threshold=7, window=10):
    a = _Ag()
    a.redmine = _FakeRedmine()
    a.journal = _FakeJournal()
    a.dry_run = False
    a.log = logging.getLogger("test.storm")
    a.gf_cfg = {"storm_threshold": threshold, "storm_window_minutes": window}

    a.cfg = {"roles": {"chief_engineer": 1, "engineer": 2},
             "shift_handoff": {"client_a_clients": ["Клиент A"]}, "work_status_id": 2}
    a.schedule = None
    a._deferred_178 = {}
    return a


def _mk(iid, mins_ago, code="CLB_SITE04"):

    ts = datetime.now(timezone.utc) - timedelta(minutes=mins_ago)
    return {"id": iid, "subject": "[Alerting] %s LOCKS" % code,
            "created_on": ts.strftime("%Y-%m-%dT%H:%M:%SZ"), "project": ""}


def test_storm_seven_in_window_takes_all():
    a = _agent(threshold=7, window=10)
    tickets = [_mk(800 + i, mins_ago=i + 1) for i in range(7)]
    handled = a._maybe_handle_storm(tickets, {})
    assert handled == {800 + i for i in range(7)}
    assert [x[0] for x in a.redmine.taken] == [800 + i for i in range(7)]
    assert all(x[1] == 2 for x in a.redmine.taken)
    anchor = 800
    assert a.redmine.relations == [(800 + i, anchor) for i in range(1, 7)]


def test_storm_respects_take_toggle():


    a = _agent(threshold=7, window=10)
    a.cfg["roles"]["auto_take_engineer"] = False
    tickets = [_mk(800 + i, mins_ago=i + 1) for i in range(7)]
    handled = a._maybe_handle_storm(tickets, {})
    assert handled == {800 + i for i in range(7)}
    assert a.redmine.taken == [] and a.redmine.relations == []
    assert {v for v, _kw in a.journal.records} == {"take_disabled"}


def test_storm_below_threshold_noop():
    a = _agent(threshold=7, window=10)
    tickets = [_mk(800 + i, mins_ago=i + 1) for i in range(6)]
    handled = a._maybe_handle_storm(tickets, {})
    assert handled == set() and a.redmine.taken == []


def test_storm_excludes_stale_outside_window():
    a = _agent(threshold=7, window=10)
    tickets = [_mk(800 + i, mins_ago=i + 1) for i in range(6)]
    tickets.append(_mk(900, mins_ago=30))
    handled = a._maybe_handle_storm(tickets, {})
    assert handled == set() and a.redmine.taken == []


def test_storm_excludes_already_seen():
    a = _agent(threshold=7, window=10)
    a.journal = _FakeJournal(seen_ids=[800])
    tickets = [_mk(800 + i, mins_ago=i + 1) for i in range(7)]
    handled = a._maybe_handle_storm(tickets, {})
    assert handled == set() and a.redmine.taken == []


def test_storm_threshold_zero_disables():
    a = _agent(threshold=0, window=10)
    tickets = [_mk(800 + i, mins_ago=1) for i in range(20)]
    assert a._maybe_handle_storm(tickets, {}) == set()
