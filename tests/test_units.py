# -*- coding: utf-8 -*-


import json
import os
import sys
import tempfile
import time
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from agent import rules
from agent import dedup
from agent import sql_engine as se
from agent import default_flow as df
from agent import claude_cli as cc
from agent import cli_json as cj
from agent import grafana_sets as gfs

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass


_PASS = 0
_FAIL = 0


def _ok(label):
    global _PASS
    _PASS += 1
    print("OK   " + label)


def _bad(label, detail):
    global _FAIL
    _FAIL += 1
    print("FAIL " + label + "  --  " + detail)


def eq(label, got, want):
    if got == want:
        _ok(label)
    else:
        _bad(label, "got %r, want %r" % (got, want))


def is_true(label, cond, detail="ожидалось True"):
    if cond:
        _ok(label)
    else:
        _bad(label, detail)


def is_false(label, cond, detail="ожидалось False"):
    if not cond:
        _ok(label)
    else:
        _bad(label, detail)


def has(label, hay, needle):

    if needle in (hay or ""):
        _ok(label)
    else:
        _bad(label, "%r нет в %r" % (needle, hay))


def group(fn):

    try:
        fn()
    except Exception as e:
        _bad(fn.__name__, "НЕЖДАННОЕ ИСКЛЮЧЕНИЕ: %r" % e)


def mail(subject="", body="", from_="sender-002@example.invalid", message_id="<m1>", uid=1, date=""):

    return types.SimpleNamespace(subject=subject, body=body, from_=from_,
                                 message_id=message_id, uid=uid, date=date, internal_ts=None)


MARKER_CFG = {"markers": [
    {"key": "healthscript", "pattern": r"(?i)health\s*script"},
    {"key": "scheduler", "pattern": r"(?i)проверка\s+логов\s+планировщика"},
    {"key": "jobfailed",
     "pattern": r"(?i)\[(the job failed\.?|failed)\]\s*sql server job system",
     "dedup_by": "subject"},
    {"key": "dbsync_lag", "pattern": r"(?i)dbsync\s+не\s+берет",
     "dedup_by": "subject", "issue_subject": "DBSYNC лаг — {token}"},
]}


def test_rules_markers():
    mk = rules.load_markers(MARKER_CFG)
    eq("rules.load_markers: количество", len(mk), 4)

    eq("match_marker healthscript в теме",
       rules.match_marker(mail(subject="Support HealthScript alert"), mk).key, "healthscript")
    eq("match_marker healthscript в теле",
       rules.match_marker(mail(body="see the health script output"), mk).key, "healthscript")
    eq("match_marker 'health script' (пробел, \\s*)",
       rules.match_marker(mail(subject="health   script"), mk).key, "healthscript")
    eq("match_marker планировщик",
       rules.match_marker(mail(subject="Проверка логов планировщика на CLB"), mk).key, "scheduler")
    eq("match_marker падение джоба [The job failed.]",
       rules.match_marker(mail(subject="[The job failed.] SQL Server Job System"), mk).key, "jobfailed")
    eq("match_marker падение джоба [FAILED]",
       rules.match_marker(mail(subject="[FAILED] SQL Server Job System"), mk).key, "jobfailed")
    eq("match_marker ничего -> None",
       rules.match_marker(mail(subject="обычная тема", body="обычное тело"), mk), None)

    by_key = {m.key: m for m in mk}
    eq("Marker.dedup_by default = 'marker'", by_key["healthscript"].dedup_by, "marker")
    eq("Marker.dedup_by jobfailed = 'subject'", by_key["jobfailed"].dedup_by, "subject")
    eq("Marker.issue_subject по умолчанию None", by_key["healthscript"].issue_subject, None)
    eq("Marker.issue_subject dbsync шаблон с {token}",
       by_key["dbsync_lag"].issue_subject, "DBSYNC лаг — {token}")


def test_rules_pings():


    _fail0 = _FAIL
    cfg = {"mail_pings": {"enabled": True, "rules": [
        {"key": "scheduler_pbl", "subject": r"(?i)LTWMS\s+Шедуллер\s+статус",
         "text": "ШЕДУЛЕР FIRING"},
        {"key": "datasource_nodata", "subject": "(?i)DatasourceNoData",
         "text": "Datasource FIRING"}]}}
    pg = rules.load_pings(cfg)
    eq("rules.load_pings: количество", len(pg), 2)

    def m(subject):
        p, n = rules.match_ping(mail(subject=subject), pg)
        return (p.text if p else None, n)


    eq("шедулер FIRING:1 -> «ШЕДУЛЕР FIRING»",
       m("[FIRING:1] LTWMS Шедуллер статус EXAMPLE_WMS (Распределение товаров PBL)"),
       ("ШЕДУЛЕР FIRING", 1))
    eq("DatasourceNoData FIRING:5 -> «Datasource FIRING», число любое",
       m("[FIRING:5] DatasourceNoData EXAMPLE_WMS (d9060d8b A Подрядчик EXAMPLE_WMS)"),
       ("Datasource FIRING", 5))
    eq("DatasourceNoData FIRING:10 (двузначное) тоже ловится",
       m("[FIRING:10] DatasourceNoData EXAMPLE_WMS (Подрядчик EXAMPLE_WMS)"), ("Datasource FIRING", 10))
    eq("FIRING без числа -> считаем 1",
       m("[FIRING] DatasourceNoData EXAMPLE_WMS"), ("Datasource FIRING", 1))


    eq("смешанное [FIRING:2, RESOLVED:2] -> пинг, алертов 2",
       m("[FIRING:2, RESOLVED:2] DatasourceNoData EXAMPLE_WMS/EXAMPLE_WMS_Kolomna"),
       ("Datasource FIRING", 2))
    eq("смешанное [RESOLVED:1, FIRING:3] (обратный порядок) -> пинг, алертов 3",
       m("[RESOLVED:1, FIRING:3] DatasourceNoData EXAMPLE_WMS"), ("Datasource FIRING", 3))

    eq("RESOLVED шедулера -> молчим",
       m("[RESOLVED] LTWMS Шедуллер статус EXAMPLE_WMS (Распределение товаров PBL)"), (None, 0))
    eq("RESOLVED DatasourceNoData -> молчим",
       m("[RESOLVED] DatasourceNoData EXAMPLE_WMS (Подрядчик EXAMPLE_WMS)"), (None, 0))

    eq("прочий FIRING (Disk > 90%) под правила не подходит -> молчим",
       m("[FIRING:1] Prod Disk > 90% EXAMPLE_WMS (dm-0 0003 prod example-app-99 rw /)"), (None, 0))
    eq("DatasourceError (не NoData) -> молчим",
       m("[FIRING:1] DatasourceError EXAMPLE_WMS (d9060d8b A Testing Disk > 90%)"), (None, 0))
    eq("тема без FIRING/RESOLVED вовсе -> молчим", m("LTWMS Шедуллер статус EXAMPLE_WMS"), (None, 0))

    eq("mail_pings.enabled=false -> правил нет, ветка мертва",
       len(rules.load_pings({"mail_pings": {"enabled": False, "rules": [
           {"key": "x", "subject": "y"}]}})), 0)
    eq("секции нет вовсе -> []", len(rules.load_pings({})), 0)
    assert _FAIL == _fail0, "см. строки FAIL выше"


def test_rules_blacklist():
    bl = ["sender-012@example.invalid"]
    is_true("blacklist: точный адрес в display-форме",
            rules.sender_blacklisted(mail(from_="Redmine <sender-012@example.invalid>"), bl))
    is_true("blacklist: голый адрес", rules.sender_blacklisted(mail(from_="sender-012@example.invalid"), bl))
    is_false("blacklist: другой local-part того же домена НЕ ловится",
             rules.sender_blacklisted(mail(from_="sender-004@example.invalid"), bl))

    is_false("blacklist: подстрока-обманка sender-013@example.invalid НЕ ловится",
             rules.sender_blacklisted(mail(from_="sender-013@example.invalid"), bl))

    is_true("blacklist: доменная запись '@example-company.ru' ловит sender-004@example.invalid",
            rules.sender_blacklisted(mail(from_="sender-004@example.invalid"), ["@example-company.ru"]))
    is_true("blacklist: доменная запись 'example-company.ru' ловит sender-004@example.invalid",
            rules.sender_blacklisted(mail(from_="sender-004@example.invalid"), ["example-company.ru"]))

    is_false("blacklist: 'example-company.ru' НЕ ловит поддомен sender-022@example.invalid",
             rules.sender_blacklisted(mail(from_="sender-022@example.invalid"), ["example-company.ru"]))


def test_rules_routing():
    cfg = {"routing": {
        "EXAMPLE-DB-01": {"project_id": 621, "client": "Клиент B (Площадка B5)"},
        "EXAMPLE-DB-17": {"project_id": 10, "client": "Короткий токен"},
        "NOID": {"client": "без project_id"},
    }}
    routing = rules.load_routing(cfg)
    eq("load_routing: запись без project_id отброшена, ключи в upper",
       sorted(routing.keys()), ["EXAMPLE-DB-01", "EXAMPLE-DB-17"])

    eq("extract_route: 'Server: XXX' из тела",
       rules.extract_route(mail(body="Server: EXAMPLE-DB-01\nprocess down"), routing),
       ("EXAMPLE-DB-01", "EXAMPLE-DB-01"))

    eq("extract_route: токен в теме, candidate=None",
       rules.extract_route(mail(subject="alert EXAMPLE-DB-17 now"), routing), ("EXAMPLE-DB-17", None))

    eq("extract_route: по границе слова (CEXAMPLE-DB-17 не матчит EXAMPLE-DB-17)",
       rules.extract_route(mail(subject="CEXAMPLE-DB-17 detected"), routing), (None, None))

    eq("extract_route: неизвестный Server -> (None, candidate)",
       rules.extract_route(mail(body="Server: FOO"), routing), (None, "FOO"))
    eq("extract_route: ничего -> (None, None)",
       rules.extract_route(mail(subject="plain", body="text"), routing), (None, None))


def test_rules_clean_subject():
    eq("clean_subject: Re:/Fwd:", rules.clean_subject("Re: Fwd: Hello"), "Hello")
    eq("clean_subject: RE[2]:", rules.clean_subject("RE[2]: test"), "test")
    eq("clean_subject: схлопывание пробелов", rules.clean_subject("  multi   space  "), "multi space")
    eq("clean_subject: Fw: Re:", rules.clean_subject("Fw: Re: x"), "x")
    eq("clean_subject: без префикса — регистр сохраняется",
       rules.clean_subject("No Prefix Here"), "No Prefix Here")


def test_normalize_subject():
    eq("normalize_subject: Re/Fwd + lower + один пробел",
       dedup.normalize_subject("Re: Fwd: Hello World"), "hello world")
    eq("normalize_subject: RE[2]:", dedup.normalize_subject("RE[2]:  Test"), "test")
    eq("normalize_subject: trim + collapse + lower",
       dedup.normalize_subject("  UPPER   Case  "), "upper case")
    eq("normalize_subject: инженерица в нижний регистр",
       dedup.normalize_subject("Обычная Тема"), "обычная тема")


def test_journal():
    d = tempfile.mkdtemp(prefix="wa_test_journal_")
    p = os.path.join(d, "processed.jsonl")
    j = dedup.Journal(p, count_dry=True)
    is_false("Journal.seen нового message_id = False", j.seen("<mid-1>"))
    j.record("<mid-1>", "created", subject="s1")
    is_true("Journal.seen после created = True", j.seen("<mid-1>"))
    eq("Journal.created_last_hour после created = 1", j.created_last_hour(), 1)


    j.record("<mid-2>", "in_work", interim=True)
    is_false("interim-запись НЕ помечает seen (фактическое поведение)", j.seen("<mid-2>"))
    lines = [json.loads(x) for x in open(p, encoding="utf-8") if x.strip()]
    is_true("interim-запись всё же попадает в файл журнала",
            any(r.get("message_id") == "<mid-2>" and r.get("interim") for r in lines))


    j.record("<mid-3>", "dry_run_create")
    eq("created_last_hour при count_dry=True считает и dry (=2)", j.created_last_hour(), 2)


    j2 = dedup.Journal(p, count_dry=False)
    is_true("после рестарта seen(<mid-1>) = True", j2.seen("<mid-1>"))
    is_false("после рестарта interim <mid-2> всё ещё НЕ seen", j2.seen("<mid-2>"))
    eq("created_last_hour при count_dry=False НЕ считает dry (=1)", j2.created_last_hour(), 1)
    j2t = dedup.Journal(p, count_dry=True)
    eq("тот же файл, count_dry=True снова считает dry (=2)", j2t.created_last_hour(), 2)


    p2 = os.path.join(d, "old.jsonl")
    with open(p2, "w", encoding="utf-8") as f:
        f.write(json.dumps({"message_id": "<old>", "verdict": "created",
                            "ts": int(time.time()) - 4000}) + "\n")
        f.write(json.dumps({"message_id": "<new>", "verdict": "created",
                            "ts": int(time.time())}) + "\n")
    j3 = dedup.Journal(p2, count_dry=True)
    eq("created_last_hour: запись >1ч выпадает (=1)", j3.created_last_hour(), 1)
    is_true("но seen видит и старую запись", j3.seen("<old>") and j3.seen("<new>"))


    p3 = os.path.join(d, "corrupt.jsonl")
    with open(p3, "w", encoding="utf-8") as f:
        f.write("не json вовсе\n")
        f.write(json.dumps({"message_id": "<ok>", "verdict": "created",
                            "ts": int(time.time())}) + "\n")
        f.write("[1,2,3]\n")
    j4 = dedup.Journal(p3, count_dry=True)
    is_true("битые/не-dict строки пропущены, валидная прочитана", j4.seen("<ok>"))
    eq("после битых строк created_last_hour = 1", j4.created_last_hour(), 1)


def test_read_only_guard_pass():
    for label, sql in [
        ("чистый SELECT", "SELECT * FROM lotxlocxid"),
        ("SELECT TOP", "SELECT TOP 1 * FROM receipt"),
        ("WITH ... SELECT", "WITH c AS (SELECT 1 AS x) SELECT * FROM c"),
        ("SELECT FROM #tmp", "SELECT * FROM #tmp"),

        ("ключевое слово ВНУТРИ строки", "SELECT 'UPDATE me' AS note"),
        ("ключевое слово в -- комментарии", "SELECT 1 -- UPDATE now\n"),
        ("ключевое слово в /* */ комментарии", "SELECT 1 /* DELETE */ FROM t"),

        ("JOIN", "SELECT a.x FROM t1 a JOIN t2 b ON a.id=b.id"),
        ("оконная функция OVER", "SELECT ROW_NUMBER() OVER (ORDER BY id) rn FROM t"),
        ("FOR XML (не путать с NEXT VALUE FOR)", "SELECT x FROM t FOR XML AUTO"),
        ("подзапрос", "SELECT * FROM (SELECT id FROM t) q"),

        ("столбец [update] в скобках", "SELECT [update] FROM t"),
    ]:
        ok, reason = se.read_only_guard(sql)
        is_true("read_only_guard ПРОПУСКАЕТ: " + label, ok, "отвергнут: %r" % reason)


def test_read_only_guard_reject():
    cases = [
        ("UPDATE", "UPDATE t SET x=1 WHERE id=2", "только SELECT"),
        ("INSERT", "INSERT INTO t (a) VALUES (1)", "только SELECT"),
        ("DELETE", "DELETE FROM t WHERE id=1", "только SELECT"),
        ("DROP", "DROP TABLE t", "только SELECT"),
        ("TRUNCATE", "TRUNCATE TABLE t", "только SELECT"),
        ("ALTER", "ALTER TABLE t ADD x int", "только SELECT"),
        ("EXEC", "EXEC sp_who", "только SELECT"),
        ("MERGE", "MERGE t USING s ON t.id=s.id", "только SELECT"),
        ("многооператорный SELECT;UPDATE", "SELECT 1; UPDATE t SET x=1 WHERE id=1", "несколько выражений"),
        ("пакетный GO", "SELECT 1\nGO", "GO"),
        ("склейка SELECT ... KILL", "SELECT 1 KILL 55", "KILL"),
        ("sp_-процедура", "SELECT * FROM sp_foo", "sp_foo"),
        ("пустой запрос", "   ", "пустой"),

        ("SELECT INTO таблицу", "SELECT * INTO newtbl FROM t", "INTO"),
        ("WITH ... DELETE (запись внутри WITH)", "WITH c AS (SELECT 1 AS x) DELETE FROM t", "DELETE"),
        ("стек без ; (SELECT ... DROP)", "SELECT 1 DROP TABLE t", "DROP"),
        ("xp_cmdshell через EXEC", "SELECT 1 EXEC xp_cmdshell 'whoami'", "EXEC"),
        ("WAITFOR DELAY (DoS по времени)", "SELECT 1 WAITFOR DELAY '00:00:05'", "WAITFOR"),
        ("OPENROWSET (файлы/удалёнка)", "SELECT * FROM OPENROWSET('a','b','c')", "OPENROWSET"),
        ("sp_executesql как функция", "SELECT sp_executesql(1)", "sp_executesql"),
        ("NEXT VALUE FOR сдвигает sequence", "SELECT NEXT VALUE FOR dbo.Seq", "sequence"),
        ("Service Broker RECEIVE", "SELECT 1 RECEIVE TOP(1) body FROM q", "RECEIVE"),
    ]
    for label, sql, needle in cases:
        ok, reason = se.read_only_guard(sql)
        is_false("read_only_guard ОТВЕРГАЕТ: " + label, ok, "пропущен!")
        has("read_only_guard причина: " + label, reason, needle)
    ok, reason = se.read_only_guard("SELECT a INTO #tmp FROM t")
    is_false("read_only_guard CURRENT: SELECT INTO #tmp ОТВЕРГНУТ (into в блэклисте)", ok)
    has("read_only_guard: причина для SELECT INTO #tmp", reason, "INTO")


def test_read_only_guard_go_batch_desync():


    for label, sql in [
        ("GO внутри /* */", "SELECT 1 /*\nGO\nUPDATE ORDERS SET status=9\nGO\n*/"),
        ("GO внутри '...'", "SELECT 'x\nGO\nUPDATE ORDERS SET status=9\nGO\ny'"),
        ("GO внутри [...]", "SELECT [a\nGO\nUPDATE ORDERS SET status=9\nGO\nb]"),
        ("GO внутри \"...\"", 'SELECT "a\nGO\nEXEC xp_cmdshell \'whoami\'\nGO\nb"'),
        ("GO после незакрытой кавычки", "SELECT 1 WHERE x='q\nGO\nUPDATE t SET x=1"),
        ("GO после незакрытого /*", "SELECT 1 /* q\nGO\nDROP TABLE t"),
    ]:
        ok, reason = se.read_only_guard(sql)
        is_false("read_only_guard ОТВЕРГАЕТ спрятанный GO: " + label, ok, "ПРОШЁЛ - запись в БД!")
        has("read_only_guard причина: " + label, reason, "GO")

    ok, reason = se.read_only_guard("SELECT 1 WHERE x='q DROP TABLE t")
    is_false("read_only_guard ОТВЕРГАЕТ незакрытую кавычку", ok, "ПРОШЁЛ")
    has("read_only_guard причина: незакрытая кавычка", reason, "незакрыт")

    ok, reason = se.read_only_guard("SELECT cargo_id,\n       gone\n  FROM t\n WHERE x=1")
    is_true("read_only_guard ПРОПУСКАЕТ многострочный SELECT (cargo/gone не GO)", ok,
            "отвергнут: %r" % reason)


def test_classify_script():
    for label, sql in [
        ("много SELECT через GO", "SELECT 1\nGO\nSELECT 2\nGO"),
        ("SELECT INTO #tmp + чтение", "SELECT a INTO #tmp FROM t\nGO\nSELECT * FROM #tmp"),
        ("CREATE #tmp TABLE + чтение", "CREATE TABLE #x (a int)\nGO\nSELECT * FROM #x"),
    ]:
        ok, reason = se.classify_script(sql)
        is_true("classify_script ПРОПУСКАЕТ: " + label, ok, "отвергнут: %r" % reason)
    for label, sql, needle in [
        ("SELECT INTO боевую", "SELECT a INTO realtbl FROM t", "realtbl"),
        ("есть UPDATE", "SELECT 1\nGO\nUPDATE t SET x=1 WHERE id=1", "update"),
        ("есть DELETE", "DELETE FROM t WHERE id=1", "delete"),
        ("есть EXEC", "EXEC sp_who", "exec"),
        ("CREATE боевой таблицы", "CREATE TABLE realx (a int)", "realx"),
        ("WAITFOR (побочка)", "WAITFOR DELAY '00:00:05'", "waitfor"),
        ("пустой скрипт", "   ", "пустой"),
    ]:
        ok, reason = se.classify_script(sql)
        is_false("classify_script ОТВЕРГАЕТ: " + label, ok, "пропущен!")
        has("classify_script причина: " + label, reason, needle)


def test_client_prefix():
    eq("client_prefix: 'Клиент C. Площадка C6' -> 'Клиент C'", df.client_prefix("Клиент C. Площадка C6"), "Клиент C")
    eq("client_prefix: 'Клиент B (Площадка B2)' -> 'Клиент B'", df.client_prefix("Клиент B (Площадка B2)"), "Клиент B")
    eq("client_prefix: 'Клиент B - Т/П' -> 'Клиент B'", df.client_prefix("Клиент B - Т/П"), "Клиент B")
    eq("client_prefix: 'CLE.LV - ТП' -> 'CLE'", df.client_prefix("CLE.LV - ТП"), "CLE")
    eq("client_prefix: плоское имя без разделителей — как есть",
       df.client_prefix("Плоское"), "Плоское")
    eq("client_prefix: em-dash тоже разделитель", df.client_prefix("Клиент B — Т/П"), "Клиент B")


def test_contour_project_ids():
    projects = [
        {"id": 1, "name": "Клиент C. Площадка C6"},
        {"id": 2, "name": "Клиент C. Площадка C1"},
        {"id": 3, "name": "Клиент B (Площадка B2)"},
        {"id": 4, "name": "CLE.LV - ТП"},
    ]
    eq("contour_project_ids: все контуры Клиент C",
       df.contour_project_ids("Клиент C. Площадка C6", projects), [1, 2])
    eq("contour_project_ids: единственный контур клиента",
       df.contour_project_ids("Клиент B (Площадка B2)", projects), [3])
    eq("contour_project_ids: override перебивает эвристику",
       df.contour_project_ids("Клиент C. Площадка C6", projects, overrides={"Клиент C": [99]}), [99])
    eq("contour_project_ids: неизвестное имя без совпадений -> []",
       df.contour_project_ids("Незнакомый проект", projects), [])


def test_extract_json():
    eq("_extract_json: чистый объект", cc._extract_json('{"a": 1}'), {"a": 1})
    eq("_extract_json: JSON внутри прозы",
       cc._extract_json('роутер ответил: {"project_id": 5, "confidence": "high"} — всё'),
       {"project_id": 5, "confidence": "high"})
    eq("_extract_json: вложенный объект берётся целиком",
       cc._extract_json('x {"a": {"b": 2}} y'), {"a": {"b": 2}})


    eq("_extract_json: два объекта -> ПЕРВЫЙ (нежадно)",
       cc._extract_json('первый {"a": 1} затем {"b": 2} конец'), {"a": 1})
    eq("_extract_json: нет JSON -> None", cc._extract_json("no json here"), None)
    eq("_extract_json: невалидный -> None", cc._extract_json("{not json}"), None)

    eq("_extract_json: объект в ```json-заборе",
       cc._extract_json('```json\n{"project_id": 7, "confidence": "high"}\n```'),
       {"project_id": 7, "confidence": "high"})


def test_cli_json_envelope():

    eq("parse_envelope: чистый однострочный конверт",
       cj.parse_envelope('{"is_error": false, "result": "hi", "session_id": "s1"}'),
       {"is_error": False, "result": "hi", "session_id": "s1"})
    eq("parse_envelope: лог-строка ПЕРЕД JSON (весь-парс падает, берём {…})",
       cj.parse_envelope('warning: foo\n{"is_error": false, "result": "x"}'),
       {"is_error": False, "result": "x"})
    eq("parse_envelope: pretty-print (многострочный) конверт",
       cj.parse_envelope('{\n  "is_error": false,\n  "result": "y"\n}'),
       {"is_error": False, "result": "y"})
    eq("parse_envelope: скобки ВНУТРИ строки result не ломают разбор",
       cj.parse_envelope('{"result": "text {x} more", "is_error": false}'),
       {"result": "text {x} more", "is_error": False})
    eq("parse_envelope: пустой вывод -> None", cj.parse_envelope(""), None)
    eq("parse_envelope: мусор без JSON -> None", cj.parse_envelope("не json вовсе"), None)


def test_site_from_subject():
    r = gfs.site_from_subject("[Alerting] CLB_SITE01 LOTXLOCXID alert")
    eq("site_from_subject: CLB_SITE01 code", (r or {}).get("code"), "CLB_SITE01")
    eq("site_from_subject: CLB_SITE01 network", (r or {}).get("network"), "client_b")
    eq("site_from_subject: CLB_SITE01 uid", (r or {}).get("uid"), "example-dashboard-01")
    eq("site_from_subject: CLB_SITE01 warehouse", (r or {}).get("warehouse"), "Площадка B1")

    r2 = gfs.site_from_subject("[Alerting] CLD_SITE08 heap alert")
    eq("site_from_subject: CLD_SITE08 распознан", (r2 or {}).get("code"), "CLD_SITE08")
    eq("site_from_subject CURRENT: CLD_SITE08 uid ПУСТОЙ", (r2 or {}).get("uid"), "")
    eq("site_from_subject: CLE (короткий код по границе)",
       (gfs.site_from_subject("[Alerting] CLE alert") or {}).get("network"), "cle")

    eq("site_from_subject: подстрока prefixDEPOsuffix НЕ матчит",
       gfs.site_from_subject("prefixDEPOsuffix"), None)
    eq("site_from_subject: нет площадки -> None", gfs.site_from_subject("no site here"), None)


def test_match_set():

    try:
        import yaml
    except ImportError:
        print("SKIP match_set (skip: no PyYAML)")
        return
    yml = os.path.join(ROOT, "config", "grafana_sets.yml")
    if not os.path.exists(yml):
        print("SKIP match_set (нет config/grafana_sets.yml)")
        return
    sets = gfs.load_sets(yml)
    is_true("load_sets: наборы загружены", len(sets) > 0, "0 наборов")
    eq("match_set: heapmemory",
       (gfs.match_set("HeapMemory Reports alert", sets) or {}).get("name"),
       "HeapMemory <служба> (куча JVM-службы)")
    eq("match_set: pickdetail",
       (gfs.match_set("PICKDETAIL alert", sets) or {}).get("name"),
       "PICKDETAIL (объём таблицы / архивация)")
    eq("match_set: нет совпадения -> None",
       gfs.match_set("совсем не про алерты", sets), None)


def test_service_verdict_nodata_guard():


    from agent import service_verdict as sv
    subj = "[Alerting] CLB_SITE04 APP1_JBOSS_Connection_Pool alert"

    def out(mf):
        v = sv.build_service_verdict(subj, site_name="Площадка B4", code="CLB_SITE04",
                                     alert_state="ok", metric_fresh=mf)
        return ("Можно закрывать" in v["comment"], "No data" in v["comment"])

    close_f, nodata_f = out(False)
    eq("service ok+No data: НЕ закрывать", close_f, False)
    eq("service ok+No data: флаг «No data»", nodata_f, True)
    eq("service ok+метрика идёт: закрыть", out(True)[0], True)
    eq("service ok+не проверить: закрыть как раньше", out(None)[0], True)

    v2 = sv.build_service_verdict(subj, site_name="Площадка 2", code="CLB_SITE04", alert_state="alerting")
    eq("service jboss alerting: не закрывать", "Можно закрывать" in v2["comment"], False)


def main():
    for fn in (test_rules_markers, test_rules_pings, test_rules_blacklist, test_rules_routing, test_rules_clean_subject,
               test_normalize_subject, test_journal,
               test_read_only_guard_pass, test_read_only_guard_reject,
               test_read_only_guard_go_batch_desync,
               test_classify_script,
               test_client_prefix, test_contour_project_ids,
               test_extract_json, test_cli_json_envelope, test_site_from_subject, test_match_set,
               test_service_verdict_nodata_guard):
        group(fn)
    total = _PASS + _FAIL
    print()
    print("=" * 60)
    print("%d/%d пройдено" % (_PASS, total))
    if _FAIL:
        print("ПРОВАЛЕНО: %d" % _FAIL)
    sys.exit(1 if _FAIL else 0)


if __name__ == "__main__":
    main()


def test_empty_plain_part_does_not_shadow_html():


    import email as _email
    from agent.mail_client import _body_text
    raw = ("From: a@b.c\nSubject: t\nMIME-Version: 1.0\n"
           'Content-Type: multipart/alternative; boundary="X"\n\n'
           "--X\nContent-Type: text/plain; charset=utf-8\n\n\n"
           "--X\nContent-Type: text/html; charset=utf-8\n\n"
           "<html><body>Server: EXAMPLE-DB-07 расхождение</body></html>\n--X--\n")

    body = _body_text(_email.message_from_bytes(raw.encode("utf-8")), 4000)
    assert "EXAMPLE-DB-07" in body and "расхождение" in body


def test_nonempty_plain_still_wins_over_html():

    import email as _email
    from agent.mail_client import _body_text
    raw = ("From: a@b.c\nSubject: t\nMIME-Version: 1.0\n"
           'Content-Type: multipart/alternative; boundary="X"\n\n'
           "--X\nContent-Type: text/plain; charset=utf-8\n\nServer: PLAIN-WINS\n"
           "--X\nContent-Type: text/html; charset=utf-8\n\n"
           "<html><body>HTML-версия</body></html>\n--X--\n")

    body = _body_text(_email.message_from_bytes(raw.encode("utf-8")), 4000)
    assert "PLAIN-WINS" in body and "HTML" not in body


def test_redmine_mcp_env_fail_closed(monkeypatch):


    import importlib.util as u
    monkeypatch.setenv("RM_CONTOUR_PROJECTS", "Клиент B (Площадка B2),Клиент B - Т/П")
    monkeypatch.setenv("RM_SOURCE_ISSUE", "abc")
    monkeypatch.setenv("RM_SEARCH_LIMIT", "")
    spec = u.spec_from_file_location("rm_mcp_t", "agent/redmine_mcp.py")
    m = u.module_from_spec(spec)
    try:
        spec.loader.exec_module(m)
    except SystemExit:
        pass
    assert m._SOURCE == 0 and m._CONTOURS == [] and m._LIMIT == 40


def test_redmine_mcp_env_normal(monkeypatch):

    import importlib.util as u
    monkeypatch.setenv("RM_CONTOUR_PROJECTS", "900,901")
    monkeypatch.setenv("RM_SOURCE_ISSUE", "10105")
    monkeypatch.setenv("RM_SEARCH_LIMIT", "40")
    spec = u.spec_from_file_location("rm_mcp_t2", "agent/redmine_mcp.py")
    m = u.module_from_spec(spec)
    try:
        spec.loader.exec_module(m)
    except SystemExit:
        pass
    assert m._SOURCE == 10105 and m._CONTOURS == [900, 901] and m._LIMIT == 40


def test_journal_repairs_truncated_tail(tmp_path):


    from agent.dedup import Journal
    p = str(tmp_path / "processed.jsonl")
    with open(p, "w", encoding="utf-8") as f:
        f.write(json.dumps({"message_id": "<a>", "verdict": "created"}) + "\n")
    with open(p, "a", encoding="utf-8") as f:
        f.write('{"message_id":"<b>","verdi')
    Journal(p).record("<c>", "created")
    j2 = Journal(p)
    assert j2.seen("<a>"), "старая запись потеряна"
    assert j2.seen("<c>"), "запись ПОСЛЕ обрыва склеилась и потерялась"


def test_take_issue_omits_none_assignee(monkeypatch):


    from agent.redmine_client import RedmineClient
    sent = {}
    rc = RedmineClient("http://rm", "k")
    monkeypatch.setattr(rc, "_request",
                        lambda m, p, params=None, payload=None: sent.update(payload=payload) or {})
    rc.take_issue(1, None, 2)
    assert "assigned_to_id" not in sent["payload"]["issue"]
    assert sent["payload"]["issue"]["status_id"] == 2
    rc.take_issue(1, 1, 2)
    assert sent["payload"]["issue"]["assigned_to_id"] == 1


def test_create_issue_empty_body_gives_clear_error(monkeypatch):


    import pytest as _pt
    from agent.redmine_client import RedmineClient
    rc = RedmineClient("http://rm", "k")
    monkeypatch.setattr(rc, "_request", lambda *a, **k: {})
    with _pt.raises(ValueError) as ei:
        rc.create_issue(1, 65, "тема")
    assert "МОГЛА быть создана" in str(ei.value)
