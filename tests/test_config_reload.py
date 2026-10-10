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

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import agent.orchestrator as O

_ORIG_REDMINE_CLIENT = O.RedmineClient
_ORIG_MAIL_CLIENT = O.MailClient
_ORIG_TR = O.tr


class FakeRedmine:
    def __init__(self, url, api_key):
        self.url, self.api_key = url, api_key

    def _request(self, method, path, params=None):
        return {}

    def paged(self, path, params=None, max_pages=5, item_key="issues"):
        return []

    def newest_issue_id(self, tracker_id):
        return 100000


class FakeMail:


    def __init__(self, host, port, login, password, folder="INBOX"):
        self.folder = folder
        self.fetch_calls = 0
        self.closed = False

    def uidnext(self):
        return 2000

    def uidvalidity(self):
        return None

    def fetch_new(self, cursor, body_limit=4000, max_bytes=2_000_000):
        self.fetch_calls += 1
        return []

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
    "mail_enabled": True,
    "max_issues_per_hour": 15,
    "sender_blacklist": ["sender-012@example.invalid"],
    "roles": {"auto_take_engineer": True},
    "ticket_poll": {"query_id": 178, "query_project": "example-project-001"},
    "default_flow": {"enabled": False},
}

SECRETS = {
    "redmine_url": "http://service.example.invalid",
    "redmine_api_key": "test-key",
    "imap_login": "agent@test",
    "imap_password": "x",
}

_ROOTS = []


def build_agent(cfg_overrides=None):
    root = tempfile.mkdtemp(prefix="wa_cfgreload_")
    _ROOTS.append(root)
    os.makedirs(os.path.join(root, "config"))
    os.makedirs(os.path.join(root, "state"))
    cfg = copy.deepcopy(BASE_CONFIG)
    if cfg_overrides:
        cfg.update(cfg_overrides)
    write_config(root, cfg)
    with open(os.path.join(root, "config", "secrets.local.json"), "w", encoding="utf-8") as f:
        json.dump(SECRETS, f, ensure_ascii=False)
    with open(os.path.join(root, "state", "last_uid.json"), "w", encoding="utf-8") as f:
        json.dump({"last_uid": 1000}, f)
    return O.Agent(root, dry_run_override=True)


def write_config(root, cfg, raw=None):


    path = os.path.join(root, "config", "config.json")
    with open(path, "w", encoding="utf-8") as f:
        if raw is not None:
            f.write(raw)
        else:
            json.dump(cfg, f, ensure_ascii=False)
    future = time.time() + 10
    os.utime(path, (future, future))


CASES = []


def case(fn):
    CASES.append(fn)
    return fn


@case
def test_no_change_no_reload():

    a = build_agent()
    assert a.reload_config() is False, "перечитал неизменившийся конфиг"


@case
def test_mail_toggle_applies_without_restart():

    a = build_agent()
    assert a.cfg.get("mail_enabled") is True

    cfg = copy.deepcopy(BASE_CONFIG)
    cfg["mail_enabled"] = False
    write_config(a.root, cfg)

    assert a.reload_config() is True, "правка конфига не подхватилась"
    assert a.cfg["mail_enabled"] is False

    a.mailer.fetch_calls = 0
    a.poll()
    assert a.mailer.fetch_calls == 0, \
        "почта выключена, а IMAP всё равно опрошен (%d раз)" % a.mailer.fetch_calls


@case
def test_mail_on_still_polls():


    a = build_agent()
    a.mailer.fetch_calls = 0
    a.poll()
    assert a.mailer.fetch_calls == 1, \
        "почта включена, но IMAP не опрошен (%d)" % a.mailer.fetch_calls


@case
def test_cfg_mutated_in_place():

    a = build_agent()
    same = a.cfg
    cfg = copy.deepcopy(BASE_CONFIG)
    cfg["max_issues_per_hour"] = 3
    write_config(a.root, cfg)
    a.reload_config()
    assert a.cfg is same, "cfg подменён новым объектом — ссылки на старый протухли"
    assert same["max_issues_per_hour"] == 3


@case
def test_derived_views_refreshed():

    a = build_agent()
    assert a.blacklist == ["sender-012@example.invalid"]
    cfg = copy.deepcopy(BASE_CONFIG)
    cfg["sender_blacklist"] = ["sender-011@example.invalid"]
    write_config(a.root, cfg)
    a.reload_config()
    assert a.blacklist == ["sender-011@example.invalid"], a.blacklist


@case
def test_take_toggle_applies():

    a = build_agent()
    assert a._auto_take_enabled("Клиент B") is True
    cfg = copy.deepcopy(BASE_CONFIG)
    cfg["roles"] = {"auto_take_engineer": False}
    write_config(a.root, cfg)
    a.reload_config()
    assert a._auto_take_enabled("Клиент B") is False


@case
def test_dry_run_not_hot_applied():


    a = build_agent()
    before = a.dry_run
    cfg = copy.deepcopy(BASE_CONFIG)
    cfg["dry_run"] = False
    write_config(a.root, cfg)
    a.reload_config()
    assert a.dry_run is before, "dry_run переключился горячим перечитыванием"


@case
def test_broken_config_ignored():

    a = build_agent()
    before = copy.deepcopy(a.cfg)
    write_config(a.root, None, raw="{ это не json ")
    assert a.reload_config() is False
    assert a.cfg == before, "битый конфиг затёр рабочий"


@case
def test_invalid_config_ignored():

    a = build_agent()
    before = copy.deepcopy(a.cfg)
    cfg = copy.deepcopy(BASE_CONFIG)
    cfg["max_issues_per_hour"] = "много"
    write_config(a.root, cfg)
    assert a.reload_config() is False
    assert a.cfg == before


@case
def test_broken_config_not_retried_every_pass():

    a = build_agent()
    write_config(a.root, None, raw="{ битый ")
    assert a.reload_config() is False
    assert a.reload_config() is False
    mtime = os.stat(os.path.join(a.root, "config", "config.json")).st_mtime
    assert a._cfg_mtime == mtime, "отметка времени не запомнена — будем читать битый файл вечно"


def main():
    _apply_client_patches()
    failed = 0
    try:
        for fn in CASES:
            try:
                fn()
                print("  ok    " + fn.__name__)
            except AssertionError as e:
                failed += 1
                print("  ПРОВАЛ " + fn.__name__ + "  → " + str(e))
            except Exception as e:
                failed += 1
                print("  ОШИБКА " + fn.__name__ + "  → %s: %s" % (type(e).__name__, e))
    finally:
        _restore_client_patches()
        for r in _ROOTS:
            shutil.rmtree(r, ignore_errors=True)
    print("ПРОВАЛОВ: %d" % failed if failed else "Всё сошлось (%d проверок)." % len(CASES))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
