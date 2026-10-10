# -*- coding: utf-8 -*-


import json

from agent.agent_base import RoleMixin
from agent.redmine_client import DEFAULT_ACCOUNT, list_accounts, mask_key, resolve_account


def test_legacy_flat_secrets_still_work():

    a = resolve_account({"redmine_url": "http://rm/", "redmine_api_key": "k1"})
    assert a["name"] == DEFAULT_ACCOUNT
    assert a["url"] == "http://rm" and a["api_key"] == "k1"
    assert a["user_id"] is None


def test_empty_secrets_do_not_crash():
    for bad in (None, {}, {"redmine_accounts": {}}, {"redmine_accounts": "не-словарь"}):
        a = resolve_account(bad)
        assert a["name"] == DEFAULT_ACCOUNT and a["api_key"] == ""


def test_accounts_active_selection_and_url_inheritance():
    sec = {"redmine_url": "http://rm",
           "redmine_accounts": {"a": {"api_key": "ka", "user_id": 1},
                                "b": {"api_key": "kb", "user_id": 2, "url": "http://service.example.invalid"}},
           "redmine_active": "b"}
    a = resolve_account(sec)
    assert a["name"] == "b" and a["api_key"] == "kb" and a["user_id"] == 2
    assert a["url"] == "http://service.example.invalid"
    assert resolve_account(sec, name="a")["url"] == "http://rm"


def test_active_missing_falls_back_to_first_alphabetically():

    sec = {"redmine_accounts": {"zeta": {"api_key": "z"}, "alpha": {"api_key": "a"}},
           "redmine_active": "нет-такого"}
    assert resolve_account(sec)["name"] == "alpha"
    sec.pop("redmine_active")
    assert resolve_account(sec)["name"] == "alpha"
    sec["redmine_accounts"]["alpha"] = "не-словарь"
    assert resolve_account(sec)["name"] in ("alpha", "zeta")


def test_user_id_coerced_and_bad_ignored():
    assert resolve_account({"redmine_accounts": {"a": {"api_key": "k", "user_id": "1"}}})["user_id"] == 1
    assert resolve_account({"redmine_accounts": {"a": {"api_key": "k", "user_id": "мусор"}}})["user_id"] is None
    assert resolve_account({"redmine_accounts": {"a": {"api_key": "k"}}})["user_id"] is None


def test_mask_key_never_leaks():
    assert mask_key("abcdefgh1234") == "••••1234"
    assert mask_key("") == ""
    assert mask_key("ab") == "••••"


def test_list_accounts_masks_and_marks_active():
    sec = {"redmine_accounts": {"a": {"api_key": "keyAAAA1111", "user_id": 1},
                                "b": {"api_key": "keyBBBB2222", "user_id": 2, "label": "Б"}},
           "redmine_active": "b"}
    lst = list_accounts(sec)
    assert [x["name"] for x in lst] == ["a", "b"]
    assert [x["active"] for x in lst] == [False, True]
    assert lst[1]["label"] == "Б" and lst[0]["label"] == "a"
    blob = json.dumps(lst, ensure_ascii=False)
    assert "keyAAAA1111" not in blob and "keyBBBB2222" not in blob
    assert all("api_key" not in x and x["key_masked"].startswith("••••") for x in lst)


def test_list_accounts_legacy_shows_one_row():
    lst = list_accounts({"redmine_url": "http://rm", "redmine_api_key": "keyZZZZ9999"})
    assert len(lst) == 1 and lst[0]["legacy"] is True and lst[0]["active"] is True
    assert "keyZZZZ9999" not in json.dumps(lst) and lst[0]["key_masked"] == "••••9999"


class _Fake(RoleMixin):
    def __init__(self, cfg, acc=None, sched=None):
        self.cfg = cfg
        self.schedule = sched
        if acc is not None:
            self.rm_account = acc


def test_roles_come_only_from_settings():


    f = _Fake({"assigned_to_id": 42, "roles": {}}, acc={"user_id": 999})
    chief, eng, _i = f._role_ids()
    assert chief is None and eng is None
    assert f._default_assignee() == 42
    f2 = _Fake({"assigned_to_id": 42, "roles": {"chief_engineer": 7, "engineer": 8}},
               acc={"user_id": 999})
    assert f2._role_ids()[:2] == (7, 8)


def test_role_chain_without_account_is_safe():

    f = _Fake({"assigned_to_id": None, "roles": {}})
    assert f._default_assignee() is None
    assert f._role_ids()[0] is None


def test_unset_role_label_says_so():

    f = _Fake({"roles": {"chief_engineer": None, "engineer": None}})
    assert f._role_engineer() == (None, "@engineer (не задан в настройках)")
    assert f._role_for_client("Клиент A Т/П")[1] == "@chiefEngineer (не задан в настройках)"


class _Sched:
    def __init__(self, me):
        self._me = me

    def me_id(self):
        return self._me

    def partner_for(self, _d):
        return None

    def now(self):
        import datetime
        return datetime.datetime(2026, 7, 22, 9, 0)


def test_schedule_does_not_touch_roles():


    cfg = {"assigned_to_id": None, "roles": {}}
    acc = {"user_id": 555}
    with_sched = _Fake(cfg, acc=acc, sched=_Sched(1))
    assert with_sched._role_ids()[:2] == (None, None)
    assert with_sched._default_assignee() == 555


def test_explicit_roles_are_used_as_is():

    f = _Fake({"assigned_to_id": None, "roles": {"chief_engineer": 683, "engineer": 723}},
              acc={"user_id": 555}, sched=_Sched(1))
    chief, eng, _i = f._role_ids()
    assert chief == 683 and eng == 723
