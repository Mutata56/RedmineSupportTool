# -*- coding: utf-8 -*-


import re
from datetime import datetime, timedelta, timezone

from . import grafana_sets as gfs

MSK = timezone(timedelta(hours=3))


QTY_TABLES = {"LOTXLOCXID", "SKUXLOC", "PICKDETAIL", "TASKDETAIL", "ITRN"}

MASTER_TABLES = {"LOT"}


_PHASE_UP = re.compile(r"(?:\bнабор|\bпик|\bрост|\bкопит|\bребилд)[а-яё]*\s*[~≈]?\s*$")

_BOTTOM_RANGE = re.compile(
    r"(?:дно|спад|сброс|срез|минимум)[а-яё]*[^;,()\d]{0,10}?"
    r"(?<!\d)(\d{1,2})\s*-\s*(\d{1,2})\s*h(?![a-zа-яё0-9])")

_BOTTOM_HOUR = re.compile(
    r"(дно|спад|сброс|срез|минимум)[а-яё]*[^;,()\d]{0,10}?"
    r"(?<!\d)(\d{1,2})\s*h(?![a-zа-яё0-9])")
_HOUR_UTC = re.compile(r"(?<![\d.])(\d{1,2})\s*h\s*utc")


def _cut_windows(cut_str):


    if not cut_str:
        return []
    s = cut_str.lower()
    i = s.find("utc")
    head = s[:i] if i >= 0 else s
    out, seen = [], set()

    def _push(ha, hb):
        if ha < 24 and hb < 24 and (ha, hb) not in seen:
            seen.add((ha, hb))
            out.append((ha, hb))


    for m in re.finditer(r"(?<!\d)(\d{1,2})\s*-\s*(\d{1,2})\s*h(?![a-zа-яё0-9])", head):
        if _PHASE_UP.search(head[max(0, m.start() - 14):m.start()]):
            continue
        _push(int(m.group(1)), int(m.group(2)))
    if out:
        return out


    for m in _BOTTOM_RANGE.finditer(s):
        _push(int(m.group(1)), int(m.group(2)))
    if out:
        return out

    for m in _BOTTOM_HOUR.finditer(s):
        h = int(m.group(2)) % 24
        if m.group(1) in ("дно", "минимум"):
            _push((h - 1) % 24, h)
        else:
            _push(h, (h + 1) % 24)
    if out:
        return out


    for m in _HOUR_UTC.finditer(s):
        if _PHASE_UP.search(s[max(0, m.start() - 14):m.start()]):
            continue
        h = int(m.group(1)) % 24
        return [(h, (h + 1) % 24)]
    return []


def _cut_hours(cut_str):

    w = _cut_windows(cut_str)
    return w[0] if w else None


def _fmt_hhmm_utc_msk(hour):
    utc = "%02d:00 UTC" % hour
    msk = "%02d:00 MSK" % ((hour + 3) % 24)
    return "%s (%s)" % (utc, msk)


def _table_queries(table, schema):


    tbl = (schema + "." if schema else "") + table.lower()
    q = [("-- зафиксировать текущий объём %s (схема %s)" % (table, schema),
          "select count(*) as total from %s" % tbl)]
    if table in QTY_TABLES:
        q.append(("-- из них с QTY=0 - кандидаты на ночную обрезку",
                  "select count(*) as zero_qty from %s where qty = 0" % tbl))
    return q


def _sql_block(table, schema, runner=None):


    lines = ["<pre><code class=\"sql\">"]
    for comment, query in _table_queries(table, schema):
        lines.append(comment)
        res = runner(query) if runner else None
        lines.append("%s;%s" % (query, ("   -- => %s" % res) if res else ""))
    lines.append("</code></pre>")
    return "\n".join(lines)


def _schema_for(code):
    return "wmwhse2" if code == "CLE" else "wmwhse1"


def build_verdict(subject, analysis_base, now_utc=None, msk_offset=3, alert_state=None,
                  sql_runner=None):


    table = gfs.table_from_subject(subject)
    site = gfs.site_from_subject(subject)
    code = site.get("code") if site else None
    site_name = (site.get("warehouse") or site.get("code")) if site else code
    schema = _schema_for(code) if code else "wmwhse1"

    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    now_h = now_utc.hour

    head = "h3. Разбор\n\n"


    if table == "WAVEINPROCESS":
        if alert_state == "ok":
            body = (head + "Алерт по *WAVEINPROCESS* на площадке %s погас, метрика в норме. "
                    "Можно закрывать." % site_name)
            return {"mode": "deterministic", "comment": body, "code": code, "table": table,
                    "reason": "WAVEINPROCESS погас - закрыть"}
        return {"mode": "skip", "comment": None, "code": code, "table": table,
                "reason": "WAVEINPROCESS горит - разбор не пишем"}


    if alert_state == "ok":
        body = (head +
                "Проверил в Grafana: алерт по *%s* на площадке %s погас, метрика вернулась в "
                "норму (сердечко зелёное). Скачок кратковременный, вмешательства не требуется.\n\n"
                "Можно закрывать." % (table or "таблице", site_name))
        return {"mode": "deterministic", "comment": body, "code": code, "table": table,
                "reason": "алерт погас (state=ok) - метрика в норме, закрыть"}


    routed = gfs.analysis_for(subject, analysis_base)
    if not routed:
        body = (head +
                "Таблица *%s* на площадке %s. Алерт горит, годового профиля обрезки нет - "
                "зафиксировать состояние и эскалировать:\n\n%s"
                % (table or "?", site_name, _sql_block(table or "", schema, sql_runner) if table else ""))
        return {"mode": "deterministic", "comment": body, "code": code, "table": table,
                "reason": "нет годового профиля, алерт горит - эскалировать"}
    code, table, rec = routed
    pattern = (rec.get("pattern") or "").lower()
    cut = rec.get("cut") or ""


    windows = _cut_windows(cut)
    POST_CUT_GRACE = 3
    if windows:
        def in_window(h, s, e):
            return s <= h <= e if s <= e else (h >= s or h <= e)


        cur = next(((s, e) for s, e in windows if in_window(now_h, s, e)), None)
        if cur:
            s, e = cur
            body = (head +
                    "Таблица *%s* на площадке %s. По годовому профилю обрезка идёт сейчас "
                    "(~%s). Зафиксировать значение, подождать ~1 час и перепроверить:\n\n"
                    "%s\n\n"
                    "После %s: метрика вернулась в норму (сердечко зелёное) - закрыть; "
                    "осталась выше - эскалировать."
                    % (table, site_name, _cut_range(s, e),
                       _sql_block(table, schema, sql_runner), _fmt_hhmm_utc_msk(e)))
            return {"mode": "deterministic", "comment": body, "code": code, "table": table,
                    "reason": "обрезка идёт сейчас - ждать и перепроверить"}


        next_w = min(windows, key=lambda w: (w[0] - now_h) % 24)
        secs_to_next = (next_w[0] - now_h) % 24
        just = any((now_h - e) % 24 <= POST_CUT_GRACE and (now_h - e) % 24 != 0
                   for s, e in windows)


        if not just or secs_to_next <= POST_CUT_GRACE:
            s, e = next_w
            body = (head +
                    "Таблица *%s* на площадке %s. Ближайшая обрезка ~%s, сейчас %s. "
                    "Ждать обрезки. Зафиксировать значение:\n\n"
                    "%s\n\n"
                    "После %s перепроверить: метрика вернулась в норму - закрыть; "
                    "обрезка не сработала - эскалировать."
                    % (table, site_name, _cut_range(s, e),
                       _now_str(now_utc, msk_offset), _sql_block(table, schema, sql_runner),
                       _fmt_hhmm_utc_msk(e)))
            return {"mode": "deterministic", "comment": body, "code": code, "table": table,
                    "reason": "обрезка впереди - ждать обрезки"}


        cut_txt = _cut_range(*windows[-1])
        sql = _sql_block(table, schema, sql_runner)
        body = (head +
                "Таблица *%s* на площадке %s. Обрезка (~%s) уже прошла, а алерт горит - "
                "надо эскалировать (обрезка не сработала / метрика выше порога). "
                "Зафиксировать состояние:\n\n%s" % (table, site_name, cut_txt, sql))


        context = (
            "Алерт (тема заявки): %s\n"
            "Площадка: %s\n"
            "Что заметил детерминированный анализатор: суточная обрезка таблицы %s обычно идёт "
            "~%s, но сейчас это окно уже прошло, а алерт всё ещё горит — значит таблица не "
            "обрезалась или растёт аномально.\n\n"
            "%s"
            % (subject, site_name, table, cut_txt,
               gfs.format_analysis_note(code, table, rec)))
        return {"mode": "llm", "comment": body, "context": context, "sql": sql,
                "code": code, "table": table,
                "reason": "обрезка прошла, алерт горит - аномалия, разбор в Sonnet"}


    body = (head +
            "Таблица *%s* на площадке %s. Алерт горит, суточной обрезки в профиле не видно. "
            "Зафиксировать состояние и эскалировать:\n\n%s"
            % (table, site_name, _sql_block(table, schema, sql_runner)))
    return {"mode": "deterministic", "comment": body, "code": code, "table": table,
            "reason": "обрезка не распознана, алерт горит - эскалировать"}


def _cut_range(a, b):
    return "%02d-%02dh UTC (%02d-%02dh MSK)" % (a, b, (a + 3) % 24, (b + 3) % 24)


def _now_str(now_utc, msk_offset):
    msk = now_utc + timedelta(hours=msk_offset)
    return "%s UTC (%s MSK)" % (now_utc.strftime("%d.%m %H:%M"), msk.strftime("%H:%M"))
