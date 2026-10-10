# -*- coding: utf-8 -*-


import logging

from agent import service_verdict as sv
from agent.pipe_grafana import GrafanaMixin

DESC = "h5. t_AdmLockBlock.max\n\nh5. 89506.000\n"


class _Ag(GrafanaMixin):
    pass


def _agent():
    a = _Ag()
    a.dry_run = False
    a.log = logging.getLogger("test.locks")
    a.cfg = {"locks": {"enabled": True, "login": "sa"},
             "reason_custom_field": {"id": 109, "value": "Превентивные мероприятия"}}
    return a


def _locks_verdict():

    v = sv.build_service_verdict("[Alerting] CLB_SITE04 LOCKS", site_name="Площадка 2", code="CLB_SITE04",
                                 influx=None, alert_state=None, description=DESC)
    assert v and v.get("type") == "locks", v
    return v


def test_locks_comment_keeps_query_and_asks_to_run():

    a, v = _agent(), _locks_verdict()
    before = v["comment"]
    a._locks_manual_note(v)
    assert "Выполнить запрос вручную." in v["comment"]
    assert before.rstrip() in v["comment"]
    assert "select" in v["comment"].lower() and "t_AdmLockBlock".lower() in v["comment"].lower()


def test_locks_note_is_idempotent():

    a, v = _agent(), _locks_verdict()
    a._locks_manual_note(v)
    a._locks_manual_note(v)
    assert v["comment"].count("Выполнить запрос вручную.") == 1


def test_locks_autorun_and_dba_handoff_are_gone():


    a = _agent()
    assert not hasattr(a, "_locks_autorun")
    assert not hasattr(a, "_locks_handoff")


def test_locks_not_in_escalate_types():

    import json
    cfg = json.load(open("config/config.example.json", encoding="utf-8"))
    assert "locks" not in (cfg.get("default_flow") or {}).get("escalate_alert_types", [])
