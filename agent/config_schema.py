# -*- coding: utf-8 -*-


__all__ = ["validate", "SCHEMA", "Field", "Section"]


_INT = "int"
_BOOL = "bool"
_STR = "str"
_NUM = "num"
_LIST = "list"
_DICT = "dict"

_TYPE_NAME = {
    _INT: "целое число", _BOOL: "true/false", _STR: "строка",
    _NUM: "число", _LIST: "список", _DICT: "объект",
}


class Field:


    def __init__(self, kind, default=None, min=None, max=None, choices=None, nullable=False):
        self.kind = kind
        self.default = default
        self.min = min
        self.max = max
        self.choices = choices
        self.nullable = nullable


class Section(Field):


    def __init__(self, schema):
        super().__init__(_DICT)
        self.schema = schema


def _int(default=None, min=None, max=None, nullable=False):
    return Field(_INT, default, min=min, max=max, nullable=nullable)


def _num(default=None, min=None, max=None):
    return Field(_NUM, default, min=min, max=max)


def _bool(default=None):
    return Field(_BOOL, default)


def _str(default=None, choices=None, nullable=False):
    return Field(_STR, default, choices=choices, nullable=nullable)


def _list(default=None, nullable=False):
    return Field(_LIST, default, nullable=nullable)


def _map(default=None):


    return Field(_DICT, default)


_ONE_TO_10M = 10_000_000


_IMAP = {
    "host":   _str("imap.yandex.ru"),
    "port":   _int(993, min=1, max=65535),
    "folder": _str("INBOX"),
}

_LLM = {
    "enabled":          _bool(True),
    "backend":          _str("cli", choices=("cli", "api")),
    "model":            _str("sonnet"),
    "effort":           _str("low"),
    "cli_timeout":      _num(25, min=1),
    "max_calls_route":  _int(15, min=0, max=200),
    "max_calls_intent": _int(15, min=0, max=200),
    "neg_cache_minutes": _int(60, min=0),
    "claude_bin":       _str("claude"),
    "api_model":        _str("claude-haiku-4-5"),


}

_DEDUP = {
    "query_id":            _int(178, min=1, max=_ONE_TO_10M),
    "query_project":       _str("example-project-001"),
    "blocking_statuses":   _list([]),
    "also_new_tracker_id": _int(65, min=0, nullable=True),
}

_GRAFANA = {
    "enabled":                _bool(True),
    "base":                   _str("http://service.example.invalid"),
    "cookie_domain":          _str("192.0.2.10"),
    "sets_file":              _str("config/grafana_sets.yml"),
    "browser_path":           _str(""),
    "tracker_id":             _int(65, min=1),


    "take_statuses":          _list(["Новая", "В процессе: В работе"], nullable=True),
    "max_ticket_age_minutes": _int(15, min=0),
    "storm_window_minutes":   _int(10, min=0),
    "storm_gap_minutes":      _int(15, min=0),
    "storm_threshold":        _int(7, min=0),
    "take_without_set":       _bool(False),
    "influx_window":          _str("30h"),
    "influx_step":            _str("10m"),
    "influx_points":          _int(200, min=1),
    "influx_ds_id":           _int(3, min=1),
    "influx_db":              _str("telegraf"),
    "from":                   _str("now-6h"),
    "to":                     _str("now"),
    "panel_width":            _int(1100, min=1),
    "panel_height":           _int(520, min=1),
    "panel_scale":            _num(2, min=1),
    "hover":                  _bool(True),
    "caption":                _bool(True),
}

_DB = {
    "enabled":         _bool(False),
    "query_timeout":   _num(30, min=1),
    "count_timeout":   _num(15, min=1),
    "connect_timeout": _num(4, min=1),
    "login_default":   _str("wmwhse1"),
    "login":           _str("wmwhse1"),
    "servers":         _map({}),
}

_LOCKS = {
    "enabled":       _bool(True),


    "dba_group_id":  _int(547, min=1, nullable=True),
    "dba_tag":       _str("DBA"),
    "login":         _str("sa"),
    "time_spent_minutes": _int(5, min=0),
}

_TICKET_POLL = {

    "query_id":              _int(178, min=1, max=_ONE_TO_10M),
    "query_project":         _str("example-project-001"),
    "fresh_minutes":         _int(10, min=0),
    "trigger_statuses":      _list([1, 49, 2]),
    "tracker_id":            _int(1, min=1),
    "route_alerts_from_178": _bool(True),
    "alert_subject_re":      _str(r"\[alerting\]"),
    "alert_exclude_projects": _list(["Клиент A Т/П"]),
}

_DEFAULT_FLOW = {


    "enabled":              _bool(True),


    "model":                _str("claude-opus-4-8"),
    "effort":               _str("high"),
    "cli_timeout_sec":      _num(600, min=1),
    "max_concurrent":       _int(2, min=0),
    "search_limit":         _int(40, min=1),
    "attachments":          _bool(True),
    "attach_max_files":     _int(6, min=0),
    "attach_max_mb":        _num(15, min=1),
    "escalate_alert_types": _list([]),
    "docs_dirs":            _map({}),
    "contour_overrides":    _map({}),
}

_AGENT_ANALYSIS = {


    "enabled":         _bool(True),
    "model":           _str("claude-opus-4-8"),
    "effort":          _str("high"),
    "cli_timeout_sec": _num(900, min=1),
    "max_concurrent":  _int(2, min=0),
}

_ROLES = {


    "chief_engineer": _int(None, min=1, max=_ONE_TO_10M, nullable=True),
    "engineer":       _int(None, min=1, max=_ONE_TO_10M, nullable=True),


    "auto_take_chief":    _bool(True),
    "auto_take_engineer": _bool(True),
}

_MAIL_PINGS = {


    "enabled": _bool(True),
    "rules":   _list([]),
}

_MESSENGERS = {

    "enabled":  _list([]),
    "events":   _list(["new_ticket", "new_info", "draft_ready", "mail_ping"]),
    "telegram": Section({"chat_id": _str(None, nullable=True)}),
    "ntfy":     Section({"url": _str("https://ntfy.sh"), "topic": _str("")}),
}

_HUMANIZER = {
    "enabled":          _bool(True),
    "model":            _str("sonnet"),
    "effort":           _str("medium"),
    "timeout":          _num(300, min=1),
    "max_examples":     _int(8, min=0),
    "lint_max_retries": _int(2, min=0),
    "brevity":          _num(0.85, min=0),
    "profile_file":     _str("documentation/style/maintainer-style-profile.md"),
    "examples_file":    _str("state/style_corpus/examples.jsonl"),
}

_SHIFT_HANDOFF = {
    "enabled":           _bool(True),
    "schedule_file":     _str("config/shift_schedule.json"),
    "query_id":          _int(178, min=1),
    "max_pages":         _int(10, min=1),
    "in_work_status":    _str("В процессе: В работе"),
    "client_a_clients":    _list([]),
    "second_line_ids":   _list([]),
    "protect_ids":       _list([]),
    "query_project":     _str(None, nullable=True),
}


SCHEMA = {

    "imap":         Section(_IMAP),
    "llm":          Section(_LLM),
    "dedup":        Section(_DEDUP),
    "grafana":      Section(_GRAFANA),
    "db":           Section(_DB),
    "locks":        Section(_LOCKS),
    "ticket_poll":  Section(_TICKET_POLL),
    "default_flow": Section(_DEFAULT_FLOW),
    "agent_analysis": Section(_AGENT_ANALYSIS),
    "shift_handoff": Section(_SHIFT_HANDOFF),
    "roles":        Section(_ROLES),
    "messengers":   Section(_MESSENGERS),
    "mail_pings":   Section(_MAIL_PINGS),
    "humanizer":    Section(_HUMANIZER),

    "poll_seconds":          _int(30, min=5, max=3600),
    "dry_run":               _bool(True),
    "dashboard_ext_origins": _list([]),
    "max_issues_per_hour":   _int(15, min=0, max=1000),
    "max_mail_age_minutes":  _int(60, min=1, max=1440),
    "max_mail_bytes":        _int(2_000_000, min=1),
    "body_excerpt_chars":    _int(4000, min=1),
    "tracker_id":            _int(65, min=1),
    "priority_id":           _int(None, min=1, nullable=True),


    "assigned_to_id":        _int(None, min=1, nullable=True),
    "is_private":            _bool(True),
    "work_status_id":        _int(2, min=1, nullable=True),
    "mail_enabled":          _bool(True),
    "description_mode":      _str("empty", choices=("empty", "mail_body")),
    "sender_blacklist":      _list([]),
    "healthscript_ignore_points": _list([11, 30]),
    "healthscript_cld_off":  _bool(False),
    "healthscript_cld_sender": _str("sender-014@example.invalid"),
    "markers":               _list([]),
    "routing":               _map({}),
    "reason_custom_field":   _map({}),
    "known_people":          _map({}),
}


def _short(v):
    s = repr(v)
    return s if len(s) <= 60 else s[:57] + "..."


def _type_ok(kind, v):
    if kind == _BOOL:
        return isinstance(v, bool)
    if kind == _INT:
        return isinstance(v, int) and not isinstance(v, bool)
    if kind == _NUM:
        return isinstance(v, (int, float)) and not isinstance(v, bool)
    if kind == _STR:
        return isinstance(v, str)
    if kind == _LIST:
        return isinstance(v, list)
    if kind == _DICT:
        return isinstance(v, dict)
    return True


def _check_value(path, field, value, errors):

    if value is None:
        if not field.nullable:
            errors.append("%s: null недопустим (ожидалось %s)"
                          % (path, _TYPE_NAME.get(field.kind, field.kind)))
        return
    if not _type_ok(field.kind, value):
        errors.append("%s: ожидалось %s, получено %s (%s)"
                      % (path, _TYPE_NAME.get(field.kind, field.kind),
                         type(value).__name__, _short(value)))
        return
    if field.choices is not None and value not in field.choices:
        errors.append("%s: значение %s не из допустимых %s"
                      % (path, _short(value), list(field.choices)))
        return
    if field.kind in (_INT, _NUM):
        if field.min is not None and value < field.min:
            errors.append("%s: %s меньше минимума %s" % (path, _short(value), field.min))
        elif field.max is not None and value > field.max:
            errors.append("%s: %s больше максимума %s" % (path, _short(value), field.max))


def _walk_section(prefix, section, value, warnings, errors):


    for sub, subval in value.items():
        if sub.startswith("_"):
            continue
        subfield = section.schema.get(sub)
        if subfield is None:
            warnings.append("неизвестный ключ %s.%s "
                            "(опечатка? код его проигнорирует)" % (prefix, sub))
            continue
        path = "%s.%s" % (prefix, sub)
        _check_value(path, subfield, subval, errors)
        if isinstance(subfield, Section) and isinstance(subval, dict):
            _walk_section(path, subfield, subval, warnings, errors)


def validate(cfg, log=None):


    warnings = []
    errors = []

    if not isinstance(cfg, dict):
        raise ValueError("config.json должен быть JSON-объектом, получено %s"
                         % type(cfg).__name__)

    for key, value in cfg.items():
        if key.startswith("_"):
            continue
        field = SCHEMA.get(key)
        if field is None:
            warnings.append("неизвестный ключ верхнего уровня %r "
                            "(опечатка? код его проигнорирует)" % key)
            continue
        _check_value(key, field, value, errors)
        if isinstance(field, Section) and isinstance(value, dict):
            _walk_section(key, field, value, warnings, errors)

    if log is not None:
        for w in warnings:
            log.warning("config: %s", w)

    if errors:
        raise ValueError(
            "config.json невалиден — %d ошиб(ка/ки/ок), исправь и перезапусти:\n  - %s"
            % (len(errors), "\n  - ".join(errors)))

    return warnings
