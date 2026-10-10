# -*- coding: utf-8 -*-


import json
import logging
import os
import sys
import urllib.error
import urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import agent.redmine_client as R

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


def raises(label, exc_types, fn):

    try:
        fn()
    except exc_types as e:
        _ok(label)
        return e
    except Exception as e:
        _bad(label, "поднято %r, ждали %s" % (e, exc_types))
        return None
    _bad(label, "исключение НЕ поднято")
    return None


def group(fn):

    try:
        fn()
    except Exception as e:
        _bad(fn.__name__, "НЕЖДАННОЕ ИСКЛЮЧЕНИЕ: %r" % e)


class _Resp:

    def __init__(self, body):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeUrlopen:
    def __init__(self):
        self.reset()

    def reset(self):
        self.calls = []
        self.timeouts = []
        self._queue = []
        self.default = b"{}"

    def push(self, *items):
        self._queue.extend(items)
        return self

    def __call__(self, req, timeout=None):
        self.calls.append(req)
        self.timeouts.append(timeout)
        item = self._queue.pop(0) if self._queue else self.default
        if isinstance(item, BaseException):
            raise item
        return _Resp(item)

    @property
    def n(self):
        return len(self.calls)


class _LogCap(logging.Handler):
    def __init__(self):
        super().__init__(level=0)
        self.records = []

    def emit(self, rec):
        self.records.append(rec)

    def reset(self):
        self.records = []

    def warned(self):
        return any(r.levelno >= logging.WARNING for r in self.records)

    def text(self):
        return " | ".join(r.getMessage() for r in self.records)


FAKE = FakeUrlopen()
LOGCAP = _LogCap()

R.urllib.request.urlopen = FAKE
R.log.addHandler(LOGCAP)
R.log.setLevel(logging.WARNING)
R.log.propagate = False

URL = "http://service.example.invalid/"
KEY = "secret-api-key"


def client():
    return R.RedmineClient(URL, KEY)


def arm(*responses):

    FAKE.reset()
    LOGCAP.reset()
    FAKE.push(*responses)
    return client()


def jb(obj):
    return json.dumps(obj).encode("utf-8")


def hdr(req, name):


    return req.headers.get(name.capitalize())


def req_query(req):

    return dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(req.full_url).query))


def req_base(req):

    p = urllib.parse.urlsplit(req.full_url)
    return "%s://%s%s" % (p.scheme, p.netloc, p.path)


def body_json(req):
    return json.loads(req.data.decode("utf-8"))


def issue_full(i, pid=100, pname="Проект", status="Новая"):

    return {"id": i, "project": {"id": pid, "name": pname},
            "subject": "тема %d" % i, "status": {"name": status}}


def test_get_assembly():
    c = arm(jb({"issues": [], "total_count": 0}))
    eq("__init__ срезает завершающий '/' у url", c.url, "http://service.example.invalid")
    out = c._request("GET", "/issues.json", params={"query_id": 178, "project_id": "example-project-9",
                                                    "limit": 100, "offset": 0})
    eq("_request GET: РОВНО один вызов urlopen (без ретраев на успехе)", FAKE.n, 1)
    eq("_request GET: возвращён распарсенный dict", out, {"issues": [], "total_count": 0})
    req = FAKE.calls[0]
    eq("_request GET: метод", req.get_method(), "GET")
    eq("_request GET: заголовок X-Redmine-API-Key = api_key", hdr(req, "X-Redmine-API-Key"), KEY)
    eq("_request GET: Content-Type всегда application/json", hdr(req, "Content-Type"), "application/json")
    eq("_request GET: User-Agent", hdr(req, "User-Agent"), "work-agent/0.1")
    is_true("_request GET: у GET тело data = None", req.data is None,
            "data=%r" % (req.data,))
    eq("_request GET: URL = base+path", req_base(req), "http://service.example.invalid/issues.json")
    eq("_request GET: query из params (значения = строки)", req_query(req),
       {"query_id": "178", "project_id": "example-project-9", "limit": "100", "offset": "0"})
    eq("_request GET: timeout = 45", FAKE.timeouts[0], 45)


    is_true("_request CURRENT: заголовок на проводе = 'X-redmine-api-key'",
            "X-redmine-api-key" in req.headers)
    is_false("_request CURRENT: исходной формы 'X-Redmine-API-Key' в headers НЕТ",
             "X-Redmine-API-Key" in req.headers)


def test_post_put_assembly():
    c = arm(jb({"issue": {"id": 1}}))
    c._request("POST", "/issues.json", payload={"issue": {"subject": "S"}})
    req = FAKE.calls[0]
    eq("_request POST: метод", req.get_method(), "POST")
    eq("_request POST: тело — JSON payload", body_json(req), {"issue": {"subject": "S"}})
    eq("_request POST: тело — точные bytes json.dumps(payload)", req.data,
       json.dumps({"issue": {"subject": "S"}}).encode("utf-8"))
    eq("_request POST: Content-Type application/json", hdr(req, "Content-Type"), "application/json")
    eq("_request POST: РОВНО один вызов urlopen", FAKE.n, 1)

    c = arm(jb({}))
    c._request("PUT", "/issues/5.json", payload={"issue": {"status_id": 2}})
    req = FAKE.calls[0]
    eq("_request PUT: метод", req.get_method(), "PUT")
    eq("_request PUT: тело — JSON payload", body_json(req), {"issue": {"status_id": 2}})
    eq("_request PUT: URL = base+path без query (params нет)", req_base(req),
       "http://service.example.invalid/issues/5.json")
    eq("_request PUT: query пуст", req_query(req), {})


def test_response_parsing():
    c = arm(jb({"a": {"b": 2}, "list": [1, 2, 3]}))
    eq("_request: вложенный JSON распарсен целиком", c._request("GET", "/x.json"),
       {"a": {"b": 2}, "list": [1, 2, 3]})

    c = arm(b"")
    eq("_request: ПУСТОЕ тело -> {} (а не ошибка парсинга)", c._request("GET", "/x.json"), {})
    eq("_request: пустое тело — тоже один вызов", FAKE.n, 1)


def test_retries():
    R.time.sleep = lambda *a: None

    c = arm(jb({"ok": 1}))
    c._request("GET", "/x.json")
    eq("retry/успех GET: urlopen зван РОВНО 1 раз", FAKE.n, 1)


    boom = urllib.error.HTTPError("http://service.example.invalid/x.json", 500, "Server Error", None, None)
    c = arm(boom, boom, boom)
    e = raises("retry/GET 500: исчерпав повторы -> проброс", urllib.error.HTTPError,
               lambda: c._request("GET", "/x.json"))
    eq("retry/GET 500: urlopen зван 3 раза (1+2 повтора)", FAKE.n, 3)
    is_true("retry/GET 500: проброшен ТОТ ЖЕ объект", e is boom)


    down = urllib.error.URLError("connection refused")
    c = arm(down, down, down)
    e = raises("retry/GET URLError: исчерпав повторы -> проброс", urllib.error.URLError,
               lambda: c._request("GET", "/x.json"))
    eq("retry/GET URLError: urlopen зван 3 раза", FAKE.n, 3)
    is_true("retry/GET URLError: проброшен ТОТ ЖЕ объект", e is down)


    c = arm(down, urllib.error.URLError("still"), jb({"ok": 1}))
    r = c._request("GET", "/x.json")
    eq("retry/GET восстановление: 2 сбоя+успех -> результат", r, {"ok": 1})
    eq("retry/GET восстановление: urlopen зван 3 раза", FAKE.n, 3)


    e422 = urllib.error.HTTPError("http://service.example.invalid/x.json", 422, "Unproc", None, None)
    c = arm(e422)
    ex = raises("retry/GET 422: перманентно -> проброс без повторов", urllib.error.HTTPError,
                lambda: c._request("GET", "/x.json"))
    eq("retry/GET 422: urlopen зван РОВНО 1 раз (4xx не ретраим)", FAKE.n, 1)
    is_true("retry/GET 422: тот же объект", ex is e422)


    c = arm(urllib.error.HTTPError("http://service.example.invalid/x.json", 500, "SE", None, None))
    raises("retry/POST 500: мутирующий -> проброс без повторов", urllib.error.HTTPError,
           lambda: c._request("POST", "/x.json", payload={"a": 1}))
    eq("retry/POST 500: urlopen зван РОВНО 1 раз", FAKE.n, 1)


    c = arm(urllib.error.URLError("down"))
    raises("retry/PUT URLError: мутирующий -> проброс без повторов", urllib.error.URLError,
           lambda: c._request("PUT", "/x.json", payload={"a": 1}))
    eq("retry/PUT URLError: urlopen зван РОВНО 1 раз", FAKE.n, 1)


def test_dashboard_issues_paging():
    p1 = jb({"total_count": 250, "issues": [issue_full(i) for i in range(1, 101)]})
    p2 = jb({"total_count": 250, "issues": [issue_full(i) for i in range(101, 201)]})
    p3 = jb({"total_count": 250, "issues": [issue_full(i) for i in range(201, 251)]})
    c = arm(p1, p2, p3)
    out = c.dashboard_issues(query_id=778, project="example-project-9")
    eq("dashboard: 250 при total_count=250 -> 3 страницы (стоп по offset>=total_count)", FAKE.n, 3)
    eq("dashboard: собрано все 250 записей", len(out), 250)
    is_false("dashboard: НЕ упёрлись в потолок -> нет предупреждения", LOGCAP.warned(),
             "warned: %s" % LOGCAP.text())

    eq("dashboard: offset страниц 0/100/200",
       [req_query(r)["offset"] for r in FAKE.calls], ["0", "100", "200"])

    q = req_query(FAKE.calls[0])
    eq("dashboard: параметры page1 (query_id/project_id/limit/offset)", q,
       {"query_id": "778", "project_id": "example-project-9", "limit": "100", "offset": "0"})
    eq("dashboard: путь /issues.json", req_base(FAKE.calls[0]), "http://service.example.invalid/issues.json")
    is_true("dashboard: у GET-страницы тело None", FAKE.calls[0].data is None)

    eq("dashboard: форма записи (плоские id/project_id/project_name/subject/status)", out[0],
       {"id": 1, "project_id": 100, "project_name": "Проект", "subject": "тема 1", "status": "Новая"})


def test_dashboard_issues_empty_batch_stop():

    p1 = jb({"total_count": 999, "issues": [issue_full(i) for i in range(1, 31)]})
    p2 = jb({"total_count": 999, "issues": []})
    c = arm(p1, p2)
    out = c.dashboard_issues(query_id=1, project="p")
    eq("dashboard/пустой batch: стоп на 2-й странице (не тянем до вранья total_count)", FAKE.n, 2)
    eq("dashboard/пустой batch: собрано 30", len(out), 30)
    is_false("dashboard/пустой batch: без предупреждения (штатный стоп)", LOGCAP.warned())


def test_dashboard_issues_cap_warns():

    full = lambda base: jb({"total_count": 10_000,
                            "issues": [issue_full(i) for i in range(base, base + 100)]})
    c = arm(full(1), full(101), full(201), full(301), full(401))
    out = c.dashboard_issues(query_id=1, project="p")
    eq("dashboard/потолок: РОВНО max_pages(5) запросов", FAKE.n, 5)
    eq("dashboard/потолок: результат ОБРЕЗАН до 500 (хвост потерян)", len(out), 500)
    is_true("dashboard/потолок: залогировано предупреждение о хвосте/дублях", LOGCAP.warned(),
            "нет warning: %s" % LOGCAP.text())
    is_true("dashboard/потолок: текст предупреждения про 'хвост'", "хвост" in LOGCAP.text())


def test_paged_basic():

    p1 = jb({"total_count": 250, "issues": [issue_full(i) for i in range(1, 101)]})
    p2 = jb({"total_count": 250, "issues": [issue_full(i) for i in range(101, 201)]})
    p3 = jb({"total_count": 250, "issues": [issue_full(i) for i in range(201, 251)]})
    c = arm(p1, p2, p3)
    out = c.paged("/issues.json", {"query_id": 5})
    eq("paged: 250 при total=250 -> 3 страницы (стоп offset>=total_count)", FAKE.n, 3)
    eq("paged: собрано 250 СЫРЫХ элементов", len(out), 250)
    is_false("paged: не упёрлись в потолок -> без предупреждения", LOGCAP.warned())

    eq("paged: возвращает СЫРОЙ элемент (без маппинга id/project_id/...)", out[0], issue_full(1))

    eq("paged: offset страниц 0/100/200",
       [req_query(r)["offset"] for r in FAKE.calls], ["0", "100", "200"])
    eq("paged: параметры page1 (query_id вызывающего + limit=100/offset=0)",
       req_query(FAKE.calls[0]), {"query_id": "5", "limit": "100", "offset": "0"})
    eq("paged: путь = переданный path", req_base(FAKE.calls[0]), "http://service.example.invalid/issues.json")
    is_true("paged: у GET-страницы тело None", FAKE.calls[0].data is None)


def test_paged_empty_batch_stop():

    p1 = jb({"total_count": 999, "issues": [issue_full(i) for i in range(1, 31)]})
    p2 = jb({"total_count": 999, "issues": []})
    c = arm(p1, p2)
    out = c.paged("/issues.json")
    eq("paged/пустой batch: стоп на 2-й странице (не тянем до вранья total_count)", FAKE.n, 2)
    eq("paged/пустой batch: собрано 30", len(out), 30)
    is_false("paged/пустой batch: без предупреждения (штатный стоп)", LOGCAP.warned())


def test_paged_cap_warns():

    full = lambda base: jb({"total_count": 10_000,
                            "issues": [issue_full(i) for i in range(base, base + 100)]})
    c = arm(full(1), full(101))
    out = c.paged("/issues.json", max_pages=2)
    eq("paged/потолок: РОВНО max_pages(2) запросов", FAKE.n, 2)
    eq("paged/потолок: результат ОБРЕЗАН до 200 (хвост потерян)", len(out), 200)
    is_true("paged/потолок: предупреждение залогировано", LOGCAP.warned(),
            "нет warning: %s" % LOGCAP.text())
    is_true("paged/потолок: текст предупреждения про 'хвост'", "хвост" in LOGCAP.text())


def test_paged_item_key():

    c = arm(jb({"total_count": 2, "projects": [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}]}))
    out = c.paged("/projects.json", item_key="projects")
    eq("paged/item_key: собрал элементы из data['projects'] (сырьё)", out,
       [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}])
    eq("paged/item_key: один запрос (offset>=total_count после page1)", FAKE.n, 1)
    eq("paged/item_key: params=None -> только limit/offset", req_query(FAKE.calls[0]),
       {"limit": "100", "offset": "0"})

    c = arm(jb({"total_count": 5, "issues": [issue_full(1)]}))
    out = c.paged("/issues.json", item_key="widgets")
    eq("paged/item_key: отсутствующий ключ -> [] (стоп по пустому batch)", out, [])
    eq("paged/item_key: отсутствующий ключ -> один запрос", FAKE.n, 1)


def test_new_issues_paging():
    p1 = jb({"total_count": 150, "issues": [issue_full(i, status="Новая") for i in range(1, 101)]})
    p2 = jb({"total_count": 150, "issues": [issue_full(i, status="Новая") for i in range(101, 151)]})
    c = arm(p1, p2)
    out = c.new_issues(tracker_id=65)
    eq("new_issues: 150 при total=150 -> 2 страницы", FAKE.n, 2)
    eq("new_issues: собрано 150", len(out), 150)
    q = req_query(FAKE.calls[0])
    eq("new_issues: параметры (tracker_id/status_id=1 по умолчанию/limit/offset)", q,
       {"tracker_id": "65", "status_id": "1", "limit": "100", "offset": "0"})
    eq("new_issues: форма записи как у dashboard", out[0],
       {"id": 1, "project_id": 100, "project_name": "Проект", "subject": "тема 1", "status": "Новая"})
    is_false("new_issues: без потолка -> без предупреждения", LOGCAP.warned())


    full = lambda base: jb({"total_count": 10_000,
                            "issues": [issue_full(i) for i in range(base, base + 100)]})
    c = arm(full(1), full(101), full(201))
    c.new_issues(tracker_id=65, status_id=1)
    eq("new_issues/потолок: РОВНО max_pages(3) запросов", FAKE.n, 3)
    is_true("new_issues/потолок: предупреждение залогировано", LOGCAP.warned())


def test_newest_issue_id():
    c = arm(jb({"total_count": 1, "issues": [{"id": 9042, "subject": "s"}]}))
    eq("newest_issue_id: возвращает id верхней заявки", c.newest_issue_id(tracker_id=65), 9042)
    eq("newest_issue_id: один запрос", FAKE.n, 1)
    q = req_query(FAKE.calls[0])
    eq("newest_issue_id: параметры (tracker_id/status_id='*'/limit=1/sort=id:desc)", q,
       {"tracker_id": "65", "status_id": "*", "limit": "1", "sort": "id:desc"})

    c = arm(jb({"total_count": 0, "issues": []}))
    eq("newest_issue_id: пустой набор -> 0", c.newest_issue_id(tracker_id=65), 0)


def test_issues_after_paging():

    def page(ids):
        return jb({"total_count": 5, "issues": [
            {"id": i, "subject": "s%d" % i, "status": {"name": "Новая"},
             "author": {"name": "A"}, "project": {"name": "P"},
             "created_on": "2026-07-13T00:00:00Z", "description": "d%d" % i} for i in ids]})
    c = arm(page([5, 4]), page([3, 2]), page([1]))
    out = c.issues_after(tracker_id=65, after_id=0, page=2)
    eq("issues_after: 5 при total=5, page=2 -> 3 страницы", FAKE.n, 3)
    eq("issues_after: offset шагает 0/2/4",
       [req_query(r)["offset"] for r in FAKE.calls], ["0", "2", "4"])
    q = req_query(FAKE.calls[0])
    eq("issues_after: параметры (tracker_id/status_id='*'/limit=page/offset/sort=id:desc)", q,
       {"tracker_id": "65", "status_id": "*", "limit": "2", "offset": "0", "sort": "id:desc"})

    eq("issues_after: результат отсортирован ВОЗРАСТАЮЩЕ по id",
       [x["id"] for x in out], [1, 2, 3, 4, 5])
    is_false("issues_after: без потолка -> без предупреждения", LOGCAP.warned())


def test_issues_after_stop_on_seen():

    page = jb({"total_count": 999, "issues": [
        {"id": 105, "subject": "s105", "status": {"name": "Новая"},
         "author": {"name": "Grafana"}, "project": {"name": "P"},
         "assigned_to": {"id": 7, "name": "Боб"},
         "created_on": "2026-07-13T10:00:00Z", "description": "тело105"},
        {"id": 104, "subject": "s104", "status": {"name": "В работе"},
         "author": {"name": "Grafana"}, "project": {"name": "P"},
         "assigned_to": None,
         "created_on": "", "description": ""},
        {"id": 103, "subject": "s103", "status": {"name": "Новая"},
         "author": {"name": "Grafana"}, "project": {"name": "P"},
         "created_on": "", "description": ""},
        {"id": 100, "subject": "seen", "status": {"name": "x"}},
        {"id": 99, "subject": "old", "status": {"name": "x"}},
    ]})
    c = arm(page)
    out = c.issues_after(tracker_id=65, after_id=100)
    eq("issues_after/стоп: один запрос (стоп внутри страницы по id<=after_id)", FAKE.n, 1)
    eq("issues_after/стоп: id 100 и 99 ОТСЕЧЕНЫ, взяты только >100 (сорт возр.)",
       [x["id"] for x in out], [103, 104, 105])
    top = out[-1]
    eq("issues_after: полная форма записи (assigned_to присутствует)", top, {
        "id": 105, "subject": "s105", "status": "Новая", "author": "Grafana", "project": "P",
        "assigned_to_id": 7, "assigned_to": "Боб",
        "created_on": "2026-07-13T10:00:00Z", "description": "тело105"})
    null_rec = out[1]
    eq("issues_after: assigned_to=null -> assigned_to_id None (`or {}` спасает от AttributeError)",
       null_rec["assigned_to_id"], None)
    eq("issues_after: assigned_to=null -> assigned_to '' (дефолт name)", null_rec["assigned_to"], "")
    miss_rec = out[0]
    eq("issues_after: assigned_to ОТСУТСТВУЕТ -> assigned_to_id None", miss_rec["assigned_to_id"], None)


def test_issues_after_cap_warns():

    p1 = jb({"total_count": 9999, "issues": [
        {"id": 999, "subject": "a", "status": {"name": "N"}}]})
    p2 = jb({"total_count": 9999, "issues": [
        {"id": 998, "subject": "b", "status": {"name": "N"}}]})
    c = arm(p1, p2)
    out = c.issues_after(tracker_id=65, after_id=0, page=1, max_pages=2)
    eq("issues_after/потолок: РОВНО max_pages(2) запросов", FAKE.n, 2)
    eq("issues_after/потолок: собрано 2 (нижний хвост отложен)", len(out), 2)
    is_true("issues_after/потолок: предупреждение о бэклоге залогировано", LOGCAP.warned(),
            "нет warning: %s" % LOGCAP.text())


def test_create_issue_full_payload():
    c = arm(jb({"issue": {"id": 4242, "subject": "X"}}))
    rid = c.create_issue(project_id=100, tracker_id=65, subject="Тема заявки",
                         description="Описание", priority_id=7, assigned_to_id=1, is_private=True)
    eq("create_issue: возвращает data['issue']['id']", rid, 4242)
    eq("create_issue: РОВНО один вызов urlopen (без лишних записей)", FAKE.n, 1)
    req = FAKE.calls[0]
    eq("create_issue: метод POST", req.get_method(), "POST")
    eq("create_issue: путь /issues.json", req_base(req), "http://service.example.invalid/issues.json")
    eq("create_issue: тело — {issue:{...}} со всеми полями", body_json(req), {"issue": {
        "project_id": 100, "tracker_id": 65, "subject": "Тема заявки",
        "description": "Описание", "is_private": True,
        "priority_id": 7, "assigned_to_id": 1}})


def test_create_issue_optional_omitted():
    c = arm(jb({"issue": {"id": 1}}))
    c.create_issue(project_id=1, tracker_id=2, subject="s")
    issue = body_json(FAKE.calls[0])["issue"]
    eq("create_issue/дефолты: базовые поля", issue,
       {"project_id": 1, "tracker_id": 2, "subject": "s", "description": "", "is_private": False})
    is_false("create_issue/дефолты: priority_id ОТСУТСТВУЕТ (None -> if priority_id пропускает)",
             "priority_id" in issue)
    is_false("create_issue/дефолты: assigned_to_id ОТСУТСТВУЕТ", "assigned_to_id" in issue)


    c = arm(jb({"issue": {"id": 1}}))
    c.create_issue(project_id=1, tracker_id=2, subject="s", priority_id=0, assigned_to_id=0)
    issue0 = body_json(FAKE.calls[0])["issue"]
    is_false("create_issue CURRENT: priority_id=0 ОТБРОШЕН (falsy)", "priority_id" in issue0)
    is_false("create_issue CURRENT: assigned_to_id=0 ОТБРОШЕН (falsy)", "assigned_to_id" in issue0)


def test_create_issue_edges():

    c = arm(jb({"issue": {"id": 1}}))
    c.create_issue(project_id=1, tracker_id=2, subject="X" * 300)
    eq("create_issue: subject усечён до 250", len(body_json(FAKE.calls[0])["issue"]["subject"]), 250)

    c = arm(jb({"issue": {"id": 1}}))
    c.create_issue(project_id=1, tracker_id=2, subject="s", description=None)
    eq("create_issue: description=None -> '' ", body_json(FAKE.calls[0])["issue"]["description"], "")

    c = arm(jb({"issue": {"id": 1}}))
    c.create_issue(project_id=1, tracker_id=2, subject="s", is_private=1)
    eq("create_issue: is_private=1 -> True (bool())", body_json(FAKE.calls[0])["issue"]["is_private"], True)


    c = arm(b"")
    raises("create_issue: пустое тело ответа -> ValueError с понятным текстом", ValueError,
           lambda: c.create_issue(project_id=1, tracker_id=2, subject="s"))

    boom = urllib.error.HTTPError("http://service.example.invalid/issues.json", 422, "Unprocessable", None, None)
    c = arm(boom)
    raises("create_issue: HTTPError 422 проброшен", urllib.error.HTTPError,
           lambda: c.create_issue(project_id=1, tracker_id=2, subject="s"))
    eq("create_issue/422: urlopen зван РОВНО 1 раз (без повторов)", FAKE.n, 1)


def test_update_status():
    c = arm(jb({}))
    rv = c.update_status(555, 2)
    eq("update_status: возвращает None", rv, None)
    eq("update_status: один вызов", FAKE.n, 1)
    req = FAKE.calls[0]
    eq("update_status: метод PUT", req.get_method(), "PUT")
    eq("update_status: путь /issues/555.json", req_base(req), "http://service.example.invalid/issues/555.json")
    eq("update_status: тело {issue:{status_id}}", body_json(req), {"issue": {"status_id": 2}})


def test_add_relation():
    c = arm(jb({}))
    rv = c.add_relation(10, 20)
    eq("add_relation: возвращает None", rv, None)
    req = FAKE.calls[0]
    eq("add_relation: метод POST", req.get_method(), "POST")
    eq("add_relation: путь /issues/10/relations.json", req_base(req),
       "http://service.example.invalid/issues/10/relations.json")
    eq("add_relation: тип по умолчанию 'relates'", body_json(req),
       {"relation": {"issue_to_id": 20, "relation_type": "relates"}})

    c = arm(jb({}))
    c.add_relation(10, 30, relation_type="duplicates")
    eq("add_relation: явный relation_type", body_json(FAKE.calls[0])["relation"]["relation_type"],
       "duplicates")


def test_take_issue():
    c = arm(jb({}))
    rv = c.take_issue(77, 1, 2)
    eq("take_issue: возвращает None", rv, None)

    eq("take_issue: РОВНО один PUT (не create+update)", FAKE.n, 1)
    req = FAKE.calls[0]
    eq("take_issue: метод PUT", req.get_method(), "PUT")
    eq("take_issue: путь /issues/77.json", req_base(req), "http://service.example.invalid/issues/77.json")
    eq("take_issue: тело {issue:{assigned_to_id, status_id}} одним запросом", body_json(req),
       {"issue": {"assigned_to_id": 1, "status_id": 2}})


def test_create_time_entry():

    c = arm(jb({"time_entry": {"id": 1}}))
    rv = c.create_time_entry(770, 0.226, "Автоматизированный разбор (ИИ)")
    eq("create_time_entry: возвращает None", rv, None)
    eq("create_time_entry: один вызов", FAKE.n, 1)
    req = FAKE.calls[0]
    eq("create_time_entry: метод POST", req.get_method(), "POST")
    eq("create_time_entry: путь /time_entries.json", req_base(req),
       "http://service.example.invalid/time_entries.json")
    eq("create_time_entry: тело {time_entry:{issue_id, hours округл. 2, comments}}", body_json(req),
       {"time_entry": {"issue_id": 770, "hours": 0.23,
                       "comments": "Автоматизированный разбор (ИИ)"}})
    is_false("create_time_entry: activity_id НЕ передаётся (дефолт Redmine)",
             "activity_id" in body_json(req)["time_entry"])

    c = arm(jb({"time_entry": {"id": 2}}))
    c.create_time_entry(771, "1.005")
    eq("create_time_entry/дефолт: comments='', hours из строки округлён", body_json(FAKE.calls[0]),
       {"time_entry": {"issue_id": 771, "hours": 1.0, "comments": ""}})

    boom = urllib.error.HTTPError("http://service.example.invalid/time_entries.json", 422, "Unproc", None, None)
    c = arm(boom)
    raises("create_time_entry: HTTPError 422 проброшен", urllib.error.HTTPError,
           lambda: c.create_time_entry(772, 0.5))
    eq("create_time_entry/422: РОВНО один вызов (POST не ретраим)", FAKE.n, 1)


def test_add_note():

    c = arm(jb({}))
    rv = c.add_note(88, "коммент")
    eq("add_note: возвращает None", rv, None)
    req = FAKE.calls[0]
    eq("add_note: метод PUT", req.get_method(), "PUT")
    eq("add_note: путь /issues/88.json", req_base(req), "http://service.example.invalid/issues/88.json")
    eq("add_note: по умолчанию ПРИВАТНЫЙ (private_notes True), без uploads", body_json(req),
       {"issue": {"notes": "коммент", "private_notes": True}})
    is_false("add_note: uploads не добавлен, когда его нет", "uploads" in body_json(req)["issue"])

    c = arm(jb({}))
    c.add_note(88, "с файлом", uploads=[{"token": "tok-1"}], private=False)
    eq("add_note: private=False -> private_notes False; uploads добавлен", body_json(FAKE.calls[0]),
       {"issue": {"notes": "с файлом", "private_notes": False, "uploads": [{"token": "tok-1"}]}})


def test_upload():
    c = arm(jb({"upload": {"id": 7, "token": "abc123"}}))
    tok = c.upload(b"\x00\x01BINARY", "screenshot.png")
    eq("upload: возвращает upload.token", tok, "abc123")
    eq("upload: один вызов urlopen", FAKE.n, 1)
    req = FAKE.calls[0]
    eq("upload: метод POST", req.get_method(), "POST")
    eq("upload: тело — сырые bytes (без JSON-обёртки)", req.data, b"\x00\x01BINARY")
    eq("upload: Content-Type application/octet-stream", hdr(req, "Content-Type"),
       "application/octet-stream")
    eq("upload: заголовок X-Redmine-API-Key", hdr(req, "X-Redmine-API-Key"), KEY)
    eq("upload: User-Agent", hdr(req, "User-Agent"), "work-agent/0.1")
    eq("upload: путь /uploads.json", req_base(req), "http://service.example.invalid/uploads.json")
    eq("upload: filename в query", req_query(req), {"filename": "screenshot.png"})
    eq("upload: timeout = 60 (отдельно от _request=45)", FAKE.timeouts[0], 60)

    c = arm(jb({"nothing": 1}))
    raises("upload CURRENT: ответ без 'upload' -> KeyError", KeyError,
           lambda: c.upload(b"x", "f.bin"))


def main():
    for fn in (test_get_assembly, test_post_put_assembly, test_response_parsing,
               test_retries,
               test_dashboard_issues_paging, test_dashboard_issues_empty_batch_stop,
               test_dashboard_issues_cap_warns,
               test_paged_basic, test_paged_empty_batch_stop, test_paged_cap_warns,
               test_paged_item_key,
               test_new_issues_paging, test_newest_issue_id,
               test_issues_after_paging, test_issues_after_stop_on_seen,
               test_issues_after_cap_warns,
               test_create_issue_full_payload, test_create_issue_optional_omitted,
               test_create_issue_edges,
               test_update_status, test_add_relation, test_take_issue,
               test_create_time_entry, test_add_note,
               test_upload):
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
