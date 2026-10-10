#!/usr/bin/env python3
# -*- coding: utf-8 -*-


import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from agent import config_schema as cs

_fail = []


def check(name, cond, extra=""):
    print("%-58s %s %s" % (name, "OK" if cond else "FAIL", extra))
    if not cond:
        _fail.append(name)
        assert cond, f"{name}: {extra}"


class _Log:


    def __init__(self):
        self.warnings = []

    def warning(self, fmt, *args):
        self.warnings.append(fmt % args if args else fmt)


def _raises(cfg, log=None):

    try:
        cs.validate(cfg, log=log)
    except ValueError as e:
        return True, str(e)
    return False, ""


def test_real_config():


    with open(os.path.join(ROOT, "config", "config.example.json"), encoding="utf-8") as f:
        real = json.load(f)
    raised, msg = _raises(real)
    check("реальный config.json: validate НЕ бросает ValueError", not raised, msg[:200])
    if not raised:
        w = cs.validate(real)
        check("реальный config.json: 0 неожиданных warning'ов", w == [],
              "" if w == [] else "warns=%r" % w)


def test_unknown_keys_warn():

    w = cs.validate({"poll_secondz": 30})
    check("опечатка топ-левел ключа -> ровно 1 warning",
          len(w) == 1 and "poll_secondz" in w[0], repr(w))

    w = cs.validate({"llm": {"modell": "sonnet"}})
    check("опечатка ключа внутри секции (llm.modell) -> warning",
          len(w) == 1 and "llm.modell" in w[0], repr(w))


    raised, _ = _raises({"future_feature_flag": True, "poll_seconds": 30})
    check("неизвестный ключ НЕ бросает (будущий ключ не ронит старт)", not raised)


def test_underscore_comments_skip():

    w = cs.validate({
        "_intent_gate_note": "коммент верхнего уровня",
        "poll_seconds": 30,
        "llm": {"_backend_note": "коммент секции", "backend": "cli"},
    })
    check("_note-ключи (топ + вложенный) НЕ триггерят warning", w == [], repr(w))


def test_bad_type_and_bounds_raise():

    raised, _ = _raises({"poll_seconds": "abc"})
    check("кривой тип (poll_seconds='abc') -> ValueError", raised)

    raised, _ = _raises({"max_issues_per_hour": -1})
    check("выход за нижнюю границу (max_issues_per_hour=-1) -> ValueError", raised)

    raised, _ = _raises({"poll_seconds": True})
    check("bool в int-поле (poll_seconds=True) -> ValueError (bool != int)", raised)

    raised, _ = _raises({"llm": {"max_calls_route": 999}})
    check("выше верхней границы (llm.max_calls_route=999>200) -> ValueError", raised)

    raised, _ = _raises({"llm": {"backend": "grpc"}})
    check("enum-нарушение (llm.backend='grpc') -> ValueError", raised)

    raised, _ = _raises({"description_mode": "fancy"})
    check("enum-нарушение (description_mode='fancy') -> ValueError", raised)


def test_nullable_and_missing_ok():

    w = cs.validate({"priority_id": None, "work_status_id": None, "poll_seconds": 30})
    check("nullable-поля = null -> ОК (без ошибок/warning'ов)", w == [], repr(w))


    w2 = cs.validate({"grafana": {"take_statuses": None}})
    check("null у take_statuses -> ОК (регресс WS-8)", w2 == [], repr(w2))
    check("контроль: null у blocking_statuses -> ValueError (set(None) крашит код, не-nullable верно)",
          _raises({"dedup": {"blocking_statuses": None}})[0])


    minimal = {"imap": {"host": "h", "port": 993}, "poll_seconds": 30, "dry_run": True}
    raised, msg = _raises(minimal)
    check("конфиг без опциональных секций (нет grafana/...) -> ОК", not raised, msg[:120])
    check("минимальный конфиг: 0 warning'ов", cs.validate(minimal) == [])


def test_multiple_errors_collected():

    raised, msg = _raises({"poll_seconds": "x", "max_issues_per_hour": -1,
                           "llm": {"backend": "nope"}})
    check("несколько ошибок -> один ValueError со ВСЕМИ",
          raised and "poll_seconds" in msg and "max_issues_per_hour" in msg
          and "backend" in msg, msg[:160])


def test_warnings_logged():

    lg = _Log()
    w = cs.validate({"poll_secondz": 30}, log=lg)
    check("log передан: warning залогирован и возвращён",
          len(w) == 1 and len(lg.warnings) == 1 and "poll_secondz" in lg.warnings[0])

    lg2 = _Log()
    raised, _ = _raises({"poll_secondz": 30, "poll_seconds": "bad"}, log=lg2)
    check("при ОШИБКЕ warning всё равно залогирован до raise",
          raised and len(lg2.warnings) == 1)


def test_root_and_section_shape():

    raised, _ = _raises([1, 2, 3])
    check("config не JSON-объект (список) -> ValueError", raised)

    raised, _ = _raises({"imap": 5})
    check("секция с не-dict значением (imap=5) -> ValueError", raised)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    test_real_config()
    test_unknown_keys_warn()
    test_underscore_comments_skip()
    test_bad_type_and_bounds_raise()
    test_nullable_and_missing_ok()
    test_multiple_errors_collected()
    test_warnings_logged()
    test_root_and_section_shape()
    if _fail:
        print("\nПРОВАЛЕНО (%d): %s" % (len(_fail), ", ".join(_fail)))
        sys.exit(1)
    print("\nвсе тесты config_schema пройдены")


if __name__ == "__main__":
    main()
