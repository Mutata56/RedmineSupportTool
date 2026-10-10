# -*- coding: utf-8 -*-


import json
import os
import tempfile

from agent import notify


class _FakeResp:
    def read(self):
        return b"{}"


class _FakeOpen:

    def __init__(self, raise_exc=None):
        self.calls = []
        self.raise_exc = raise_exc

    def __call__(self, req, timeout=None):
        self.calls.append((req.full_url, json.loads(req.data.decode("utf-8"))))
        if self.raise_exc:
            raise self.raise_exc
        return _FakeResp()


def _notifier(enabled=("telegram", "ntfy"), events=None, token="TOK", chat="42",
              topic="wa-topic", dry=False, state_dir=None):
    cfg = {"messengers": {
        "enabled": list(enabled),
        "events": list(events) if events is not None else ["new_ticket", "new_info", "draft_ready"],
        "telegram": {"chat_id": chat},
        "ntfy": {"url": "https://service.example.invalid", "topic": topic}}}
    secrets = {"telegram_bot_token": token, "redmine_url": "https://service.example.invalid"}
    return notify.Notifier(cfg, secrets, state_dir or tempfile.mkdtemp(prefix="notify_t_"),
                           dry_run=dry)


def test_telegram_payload(monkeypatch):
    fake = _FakeOpen()
    monkeypatch.setattr(notify, "_urlopen", fake)
    n = _notifier(enabled=["telegram"])
    n.send("new_ticket", "#10104 [Alerting] CLC_SITE05 <FREESPACE>", "алерт взят в работу",
           issue_id=10104)
    assert len(fake.calls) == 1
    url, payload = fake.calls[0]
    assert url == "https://api.telegram.org/botTOK/sendMessage"
    assert payload["chat_id"] == "42"
    assert payload["parse_mode"] == "HTML"
    assert "&lt;FREESPACE&gt;" in payload["text"]
    assert "https://service.example.invalid/issues/10104" in payload["text"]
    assert "Новая заявка" in payload["text"]


def test_ntfy_payload(monkeypatch):
    fake = _FakeOpen()
    monkeypatch.setattr(notify, "_urlopen", fake)
    n = _notifier(enabled=["ntfy"])
    n.send("draft_ready", "#7 тема", "черновик готов", issue_id=7)
    url, payload = fake.calls[0]
    assert url == "https://service.example.invalid"
    assert payload["topic"] == "wa-topic"
    assert payload["title"] == "#7 тема"
    assert "Черновик агента ждёт одобрения" in payload["message"]


def test_dedup_same_event_issue(monkeypatch):
    fake = _FakeOpen()
    monkeypatch.setattr(notify, "_urlopen", fake)
    n = _notifier(enabled=["ntfy"])
    n.send("new_ticket", "#1 t", "x", issue_id=1)
    n.send("new_ticket", "#1 t", "x", issue_id=1)
    n.send("new_info", "#1 t", "x", issue_id=1)
    n.send("new_ticket", "#2 t", "x", issue_id=2)
    assert len(fake.calls) == 3


def test_dedup_survives_restart(monkeypatch):
    fake = _FakeOpen()
    monkeypatch.setattr(notify, "_urlopen", fake)
    d = tempfile.mkdtemp(prefix="notify_t_")
    _notifier(enabled=["ntfy"], state_dir=d).send("new_ticket", "#1", "x", issue_id=1)
    _notifier(enabled=["ntfy"], state_dir=d).send("new_ticket", "#1", "x", issue_id=1)
    assert len(fake.calls) == 1


def test_errors_do_not_raise_but_marked_seen(monkeypatch):
    fake = _FakeOpen(raise_exc=OSError("boom"))
    monkeypatch.setattr(notify, "_urlopen", fake)
    n = _notifier()
    n.send("new_ticket", "#1 t", "x", issue_id=1)
    assert len(fake.calls) == 2
    fake.raise_exc = None
    n.send("new_ticket", "#1 t", "x", issue_id=1)
    assert len(fake.calls) == 2


def test_events_filter(monkeypatch):
    fake = _FakeOpen()
    monkeypatch.setattr(notify, "_urlopen", fake)
    n = _notifier(events=["draft_ready"])
    n.send("new_ticket", "#1", "x", issue_id=1)
    assert fake.calls == []
    n.send("draft_ready", "#1", "x", issue_id=1)
    assert len(fake.calls) == 2


def test_telegram_without_token_silently_off(monkeypatch):
    fake = _FakeOpen()
    monkeypatch.setattr(notify, "_urlopen", fake)
    n = _notifier(enabled=["telegram", "ntfy"], token="")
    n.send("new_ticket", "#1", "x", issue_id=1)
    assert len(fake.calls) == 1
    assert fake.calls[0][0] == "https://service.example.invalid"


def test_dry_run_marks_dry(monkeypatch):
    fake = _FakeOpen()
    monkeypatch.setattr(notify, "_urlopen", fake)
    n = _notifier(enabled=["ntfy"], dry=True)
    n.send("new_ticket", "#1 t", "создал бы", issue_id=1)
    _, payload = fake.calls[0]
    assert payload["title"].startswith("[DRY] ")
    assert "[DRY]" in payload["message"]


def test_emit_without_notifier_noop():
    class _Bare:
        pass
    notify.emit(_Bare(), "new_ticket", 1, "s", "t")


def test_emit_builds_title(monkeypatch):
    fake = _FakeOpen()
    monkeypatch.setattr(notify, "_urlopen", fake)

    class _Ag:
        pass
    a = _Ag()
    a.notifier = _notifier(enabled=["ntfy"])
    notify.emit(a, "new_ticket", 5, "тема", "текст")
    assert fake.calls[0][1]["title"] == "#5 тема"


def _iss(iid, status_id):
    return {"id": iid, "subject": "s%d" % iid, "status": {"id": status_id, "name": "x"}}


def test_poll178_new_info_first_pass_snapshot_only():
    f = tempfile.mktemp(prefix="poll178_t_")
    assert notify.poll178_new_info(f, [_iss(1, 49), _iss(2, 2)]) == []
    assert os.path.exists(f)


def test_poll178_new_info_detects_transition():
    f = tempfile.mktemp(prefix="poll178_t_")
    notify.poll178_new_info(f, [_iss(1, 2), _iss(2, 2)])
    got = notify.poll178_new_info(f, [_iss(1, 49), _iss(2, 2)])
    assert [it["id"] for it in got] == [1]
    got2 = notify.poll178_new_info(f, [_iss(1, 49), _iss(2, 2)])
    assert got2 == []


def test_poll178_new_info_new_issue_already_49():


    f = tempfile.mktemp(prefix="poll178_t_")
    notify.poll178_new_info(f, [_iss(1, 2)])
    got = notify.poll178_new_info(f, [_iss(1, 2), _iss(3, 49)])
    assert [it["id"] for it in got] == [3]


def test_poll178_new_info_broken_snapshot_resets():
    f = tempfile.mktemp(prefix="poll178_t_")
    with open(f, "w", encoding="utf-8") as fh:
        fh.write("{битый json")
    assert notify.poll178_new_info(f, [_iss(1, 49)]) == []
    assert notify.poll178_new_info(f, [_iss(1, 49)]) == []
