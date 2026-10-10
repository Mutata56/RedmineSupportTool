# -*- coding: utf-8 -*-


import json
import os
import shutil
import tempfile
import threading
import time

from . import default_flow as dfl
from . import grafana_sets as gfs
from . import notify
from . import service_verdict as sv
from .agent_base import _GrafanaSessionExpired, _TicketDefer, _write_json


ALERT_MCP_TOOLS = (dfl.MCP_TOOLS +
                   ",mcp__wa-sql__run_select,mcp__wa-influx__influx_query")


_GRAPH_BY_NETWORK = {"client_b": "CLIENT_B", "clc": "CLC"}


def site_from_project(project_name):


    name = (project_name or "").lower()
    if not name:
        return None
    best = None
    for code, net, uid, wh in gfs.SITES:
        if wh and wh.lower() in name and (best is None or len(wh) > len(best[3])):
            best = (code, net, uid, wh)
    if best is None:
        return None
    code, net, uid, wh = best
    return {"code": code, "network": net, "uid": uid, "warehouse": wh}


def held_draft_ids(root):


    out = set()
    try:
        names = os.listdir(os.path.join(root, "state", "drafts"))
    except OSError:
        return out
    for n in names:
        if n.endswith(".json") and n[:-5].isdigit():
            d = load_draft(root, int(n[:-5]))
            if d and d.get("status") in ("running", "pending"):
                out.add(int(n[:-5]))
    return out


ALERT_SYSTEM_PROMPT = (
    "Ты — инженер техподдержки WMS (Infor SCE), разбираешь алерт мониторинга Grafana. "
    "Тебе доступны ТОЛЬКО инструменты: redmine (search_similar, get_issue, post_private_note), "
    "wa-influx (influx_query — InfluxQL-ЧТЕНИЕ метрик мониторинга), wa-sql (run_select — ОДИН "
    "read-only SELECT/WITH под логином sa), Read (снятые скриншоты панелей и плейбуки) и, если "
    "код клиента проиндексирован, codebase-memory на ЧТЕНИЕ графа кода. Ты НЕ выполняешь команды "
    "в шелле, не ходишь в интернет, не меняешь статусы заявок и НИЧЕГО не меняешь в БД — только "
    "читаешь и ПРЕДЛАГАЕШЬ. Итог всегда клади ОДНИМ вызовом post_private_note в эту же заявку: "
    "это ЧЕРНОВИК на одобрение, публикует человек. Пиши по-русски, кратко и по делу.")


def default_system_prompt(sql):


    return (
        "Ты — инженер техподдержки WMS (Infor SCE), разбираешь заявку клиента. Тебе доступны "
        "ТОЛЬКО инструменты: redmine (search_similar, get_issue, post_private_note), "
        "%sRead (плейбуки) и, если код клиента проиндексирован, codebase-memory на ЧТЕНИЕ "
        "графа кода. Ты НЕ выполняешь команды в шелле, не ходишь в интернет, не меняешь "
        "статусы заявок и НИЧЕГО не меняешь в БД — только читаешь и ПРЕДЛАГАЕШЬ.%s "
        "Итог всегда клади ОДНИМ вызовом post_private_note в эту же заявку: это ЧЕРНОВИК "
        "на одобрение, публикует человек. Пиши по-русски, кратко и по делу."
        % ("wa-sql (run_select — ОДИН read-only SELECT/WITH под логином sa), " if sql else "",
           "" if sql else " Коннекта к БД площадки нет — SQL предлагай текстом."))


def draft_dir(root, issue_id):
    return os.path.join(root, "state", "drafts", str(issue_id))


def draft_path(root, issue_id):
    return os.path.join(root, "state", "drafts", "%d.json" % int(issue_id))


def load_draft(root, issue_id):

    try:
        with open(draft_path(root, issue_id), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def save_draft(root, issue_id, d):
    _write_json(draft_path(root, issue_id), d)


def clear_draft(root, issue_id):

    try:
        os.remove(draft_path(root, issue_id))
    except OSError:
        pass
    shutil.rmtree(draft_dir(root, issue_id), ignore_errors=True)


def finalize_draft(root, issue_id, note, session_id=None, approved=None, analysis_seconds=None):


    d = load_draft(root, issue_id) or {"issue_id": int(issue_id), "screenshots": []}
    d["status"] = "pending"
    d["analysis"] = note
    d["comment"] = "h3. Разбор:\n\n" + note
    d["session_id"] = session_id
    if analysis_seconds is not None:
        prev = float(d.get("analysis_seconds") or 0)
        d["analysis_seconds"] = round(prev + float(analysis_seconds or 0), 2)
    ok_set = None if approved is None else {str(x) for x in approved}
    for s in d.get("screenshots", []):
        s["approved"] = True if ok_set is None else (s.get("sid") in ok_set)
    save_draft(root, issue_id, d)
    return d


def build_hints(verdict=None, alert_state=None, metric_fresh=None):


    lines = []
    if alert_state == "ok":
        lines.append("алерт в Grafana сейчас ПОГАС (state=ok, сердечко зелёное)")
    elif alert_state == "alerting":
        lines.append("алерт в Grafana всё ещё ГОРИТ (state=alerting)")
    elif alert_state:
        lines.append("состояние алерта Grafana: %s" % alert_state)
    if metric_fresh is True:
        lines.append("метрика панели реально поступает (свежие точки за 20 мин)")
    elif metric_fresh is False:
        lines.append("метрика панели МОЛЧИТ (подтверждённый No data): зелёный алерт НЕ "
                     "доказывает норму - сначала проверь, жива ли служба и сбор метрик")
    if verdict and verdict.get("reason"):
        lines.append("вывод детерминированного анализатора: %s" % verdict["reason"])
    if verdict and verdict.get("mode") == "llm":
        lines.append("анализатор считает случай пограничным/аномальным - нужен именно "
                     "разбор по данным, а не шаблон")
    if not lines:
        return ""
    return ("Что заметила программа (подсказки её детерминированных проверок - проверь их "
            "по живым данным, слепо не верь):\n" +
            "\n".join("- %s" % ln for ln in lines) + "\n")


def _codebase_step(graph_project, code_path):


    if not graph_project:
        return ""
    where = (" Исходники клиента лежат в %s (по ним собран индекс; читать их можно ТОЛЬКО через "
             "граф codebase-memory, не файлами)." % code_path) if code_path else ""
    return ("Можешь смотреть код клиента через codebase-memory (граф кода, ТОЛЬКО чтение): "
            "код этого клиента проиндексирован как проект «%s» — первый аргумент project у "
            "каждого тула. Инструменты: search_code (семантический/текстовый поиск по коду), "
            "search_graph (найти класс/метод/таблицу/процедуру по имени), trace_path (кто "
            "вызывает и что вызывает — связи), get_code_snippet (исходник узла). Это быстрее, "
            "чем читать файлы подряд.%s" % (graph_project, where))


def build_alert_prompt(issue_id, site_label, subject, body, screenshots, measurements,
                       hints_block="", playbooks=None, graph_project=None, code_path=None):


    meas_txt = ", ".join(measurements) if measurements else ""
    if screenshots:
        shots_json = json.dumps(
            [{"id": s["sid"], "файл": s["path"], "заголовок": s["title"],
              "measurement": s.get("measurement") or "?"} for s in screenshots],
            ensure_ascii=False)
        shots_block = (
            "- Программа уже сняла скриншоты панелей: %s.\n"
            "  Системные имена этих таблиц/метрик: %s. Смотри ТОЛЬКО их — на другие метрики "
            "НЕ отвлекайся, это трата времени.\n"
            "  Картинку можно ВСТАВИТЬ В ТЕКСТ разбора по месту: напиши !имя_файла! отдельной "
            "строкой там, где она к месту (имя = basename из «файл», напр. !%s!). Что не "
            "вставишь — программа допишет в конец коммента.\n"
            % (shots_json, meas_txt or "?",
               os.path.basename(screenshots[0]["path"]) if screenshots else "panel.png"))
    elif measurements:
        shots_block = (
            "- Скриншоты панелей снять не удалось, но системные имена метрик алерта известны: "
            "%s. Смотри ТОЛЬКО их — на другие метрики НЕ отвлекайся.\n" % meas_txt)
    else:
        shots_block = ""

    steps = [dfl._playbook_step(playbooks)]
    steps.append(
        "1) Проанализируй ИМЕННО эти метрики через influx_query (тренд, аномалия, вернулось "
        "ли в норму). InfluxDB=telegraf; свежие ряды размеров таблиц — measurement «tableCounts» "
        "(поле = имя таблицы, теги host/schema; у CLE schema=wmwhse2). Сырьё хранится ~24ч, "
        "глубже — только годовой профиль; состав узнаёшь через SHOW MEASUREMENTS / SHOW FIELD KEYS.\n")
    steps.append(
        "2) Если есть коннект — сделай SELECT'ы (run_select), которые помогут понять причину. "
        "ОБЯЗАТЕЛЬНО фиксируй каждый: запрос + результат. Нет коннекта — предложи запрос "
        "текстом. Свой SQL можно (только SELECT), логин sa. run_select уже подключён к БД ЭТОЙ "
        "площадки (маппинг площадка→сервер — config/config.json → db.servers: CLB_*/CLC_*/CLD/CLE).\n")
    if screenshots:
        steps.append(
            "3) Реши, какие скриншоты приложить: две одинаковые метрики, одна здоровая — "
            "оставь только показательную (нездоровую), здоровый дубль отбрось. Верни список "
            "id одобренных (параметр approved_screenshots) И расставь их !имя_файла! в тексте "
            "разбора там, где они к месту (строкой после абзаца, который иллюстрируют).\n")
    steps.append(
        "4) Можешь проанализировать похожие заявки в Redmine (search_similar по ключевым "
        "словам темы/тела, get_issue по найденным — в журналах бывает готовое решение/SQL). "
        "Писать можно только в приватный комментарий и только в ИСХОДНУЮ заявку, по которой "
        "идёт работа (post_private_note, уйдёт как черновик на одобрение).\n")
    if graph_project:
        steps.append("5) " + _codebase_step(graph_project, code_path) + "\n")

    tail_shots = "\n- screenshots: id одобренных." if screenshots else ""
    return (
        "Ты — инженер техподдержки WMS (Infor SCE). Разбираешь алерт Grafana по заявке #%d, "
        "площадка %s.\n"
        "Доступно: influx_query (InfluxDB через Grafana), run_select (read-only SQL, логин sa, "
        "ТОЛЬКО SELECT), get_issue (чтение заявки), search_similar (похожие решённые заявки), "
        "Read (прочитать снятые скриншоты).\n"
        "В БД писать НЕЛЬЗЯ. Ничего не меняй, не удаляй, не вставляй в БД, пока тебя об этом "
        "явно не попросят!!\n\n"
        "Контекст:\n"
        "- Тема: %s\n"
        "- Тело:\n%s\n"
        "%s\n"
        "%s"
        "Шаги:\n%s\n"
        "Итог (уйдёт человеку на одобрение, потом в приватный коммент):\n"
        "- analysis: КРАТКИЙ разбор простым языком, как для обычного человека из ТП, БЕЗ "
        "DBA-жаргона и сложных сокращений. Что случилось, что это значит, что делать. Лишнего "
        "не пиши.\n"
        "- sql: выполненные запросы и результаты (или предложенные, если нет коннекта).%s\n"
        "Итог отправь ОДНИМ вызовом post_private_note: note = analysis + sql, confidence = "
        "честная оценка%s.\n"
        "Коммент уйдёт как «h3. Разбор:» + твой текст + (SQL)%s."
        % (issue_id, site_label, subject or "", (body or "")[:4000], shots_block,
           ("\n" + hints_block) if hints_block else "",
           "".join(steps), tail_shots,
           ", approved_screenshots = id одобренных скринов" if screenshots else "",
           " + (скрины, которые ты не расставил !именем! в тексте, программа допишет в конец)"
           if screenshots else ""))


def build_default_prompt(issue_id, project_name, subject, body, sql=False, site=None,
                         playbooks=None, graph_project=None, code_path=None):


    place = ", площадка %s (%s)" % (site["warehouse"], site["code"]) if site else ""
    if sql:
        tools_line = ("Доступно: run_select (read-only SQL по БД площадки, логин sa, ТОЛЬКО "
                      "SELECT), get_issue (чтение заявки), search_similar (похожие решённые "
                      "заявки).\n")
    else:
        tools_line = ("Доступно: get_issue (чтение заявки), search_similar (похожие решённые "
                      "заявки). Коннекта к БД площадки нет — SQL НЕ выполняй, предлагай "
                      "запросы текстом (в блоке).\n")
    steps = [dfl._playbook_step(playbooks)]
    num = [0]

    def _step(txt):
        num[0] += 1
        return "%d) %s\n" % (num[0], txt)

    steps.append(_step(
        "Найди 4-5 максимально похожих РЕШЁННЫХ заявок (search_similar по ключевым словам "
        "темы/тела, get_issue по найденным — в журналах бывает готовое решение/SQL). Писать "
        "можно только в приватный комментарий и только в ИСХОДНУЮ заявку, по которой идёт "
        "работа (post_private_note, уйдёт как черновик на одобрение)."))
    if sql:
        steps.append(_step(
            "Сделай SELECT'ы (run_select), которые помогут понять причину. ОБЯЗАТЕЛЬНО "
            "фиксируй каждый: запрос + результат. Свой SQL можно (только SELECT), логин sa. "
            "run_select уже подключён к БД площадки (маппинг площадка→сервер — "
            "config/config.json → db.servers)."))
    else:
        steps.append(_step(
            "Полезные диагностические SELECT'ы предложи ТЕКСТОМ (коннекта к БД нет): запрос "
            "в блоке + что он покажет. НЕ выполнять."))
    if graph_project:
        steps.append(_step(_codebase_step(graph_project, code_path)))
    return (
        "Ты — инженер техподдержки WMS (Infor SCE). Разбираешь заявку клиента #%d, проект "
        "«%s»%s.\n"
        "%s"
        "В БД писать НЕЛЬЗЯ. Ничего не меняй, не удаляй, не вставляй в БД, пока тебя об этом "
        "явно не попросят!!\n\n"
        "Контекст:\n"
        "- Тема: %s\n"
        "- Тело:\n%s\n\n"
        "Шаги:\n%s\n"
        "Итог (уйдёт человеку на одобрение, потом в приватный коммент):\n"
        "- analysis: КРАТКИЙ разбор простым языком, как для обычного человека из ТП, БЕЗ "
        "DBA-жаргона и сложных сокращений. ЧТО за проблема, С ЧЕМ связана, вероятные причины "
        "(с УПОМИНАНИЕМ источника: id похожей заявки, плейбук, узел кода), что делать. "
        "Лишнего не пиши.\n"
        "- sql: выполненные запросы и результаты (или предложенные текстом, если нет "
        "коннекта).\n"
        "Итог отправь ОДНИМ вызовом post_private_note: note = analysis + sql, confidence = "
        "честная оценка.\n"
        "Коммент уйдёт как «h3. Разбор:» + твой текст + (SQL)."
        % (issue_id, project_name or "?", place, tools_line, subject or "",
           (body or "")[:4000], "".join(steps)))


def analyze_alert(prompt, issue_id, url, api_key, contour_ids, sql_env=None, influx_env=None,
                  graph=False, model="claude-opus-4-8", effort="high", timeout=900,
                  add_dirs=None, search_limit=40, log=None, claude_bin="claude",
                  mcp_tools=None, system_prompt=None, builtin_tools="Read", tag="alert-agent",
                  attachments=False, attach_max_files=6, attach_max_mb=15):


    _log = log or (lambda *a: None)
    res = {"source_id": issue_id, "session_id": None, "ok": False, "error": None,
           "result": "", "tool_log": "", "draft": None}
    lfd, log_path = tempfile.mkstemp(suffix=".log", prefix="waalert_")
    os.close(lfd)
    dfd, draft_tmp = tempfile.mkstemp(suffix=".json", prefix="waalert_draft_")
    os.close(dfd)
    attach_dir = None
    if sql_env is not None:
        sql_env = dict(sql_env)
        sql_env.setdefault("WA_SQL_LOG", log_path)
    if influx_env is not None:
        influx_env = dict(influx_env)
        influx_env.setdefault("WA_INFLUX_LOG", log_path)
    cfg = dfl.build_mcp_config(url, api_key, issue_id, contour_ids, dry=True,
                               search_limit=search_limit, log_path=log_path,
                               draft_file=draft_tmp, graph=graph,
                               sql_env=sql_env, influx_env=influx_env)
    fd, cfg_path = tempfile.mkstemp(suffix=".json", prefix="waalert_mcp_")
    try:
        os.write(fd, json.dumps(cfg).encode("utf-8"))
        os.close(fd)
        os.chmod(cfg_path, 0o600)


        if attachments:
            attach_dir = tempfile.mkdtemp(prefix="waalert_att_")
            att_files = dfl.download_client_files(url, api_key, issue_id, attach_dir,
                                                  max_files=attach_max_files,
                                                  max_mb=attach_max_mb, log=log)
            if att_files:
                prompt = prompt + dfl._attach_prompt(att_files)
                add_dirs = list(add_dirs or []) + [attach_dir]
                if "Read" not in (builtin_tools or ""):
                    builtin_tools = (builtin_tools + ",Read").strip(",") if builtin_tools else "Read"
        cmd = dfl._cli_cmd(prompt, cfg_path, model, effort, claude_bin=claude_bin,
                           add_dirs=add_dirs, extra_builtin_tools=builtin_tools,
                           mcp_tools=mcp_tools or ALERT_MCP_TOOLS,
                           system_prompt=(system_prompt or ALERT_SYSTEM_PROMPT)
                           + dfl.HUMANIZER_STYLE)
        _log("%s #%d: пасс CLI (%s, effort=%s, таймаут %dс)",
             tag, issue_id, model, effort, int(timeout))
        ok, sid, result, err = dfl._run_cli(cmd, timeout)
        res.update(ok=ok, session_id=sid, result=result or "", error=err)
        _log("%s #%d: пасс -> ok=%s sid=%s err=%s", tag, issue_id, ok, sid, err)
        try:
            with open(log_path, encoding="utf-8") as f:
                res["tool_log"] = f.read().strip()
        except OSError:
            pass
        try:
            with open(draft_tmp, encoding="utf-8") as f:
                txt = f.read().strip()
            if txt:
                d = json.loads(txt)
                if isinstance(d, dict) and d.get("note"):
                    res["draft"] = d
                    _log("%s #%d: черновик готов (confidence=%s, %d симв., скринов %s)",
                         tag, issue_id, d.get("confidence"), len(d.get("note", "")),
                         len(d.get("approved_screenshots"))
                         if isinstance(d.get("approved_screenshots"), list) else "все")
        except (OSError, ValueError):
            pass
        return res
    finally:
        for pth in (cfg_path, log_path, draft_tmp):
            try:
                os.remove(pth)
            except OSError:
                pass
        if attach_dir:
            shutil.rmtree(attach_dir, ignore_errors=True)


class AlertAgentMixin:


    def _aa_cfg(self):
        return self.cfg.get("agent_analysis", {})

    def _aa_threads(self):
        if not hasattr(self, "_alert_agent_threads"):
            self._alert_agent_threads = []
        return self._alert_agent_threads

    def _alert_agent_resume(self, t, key):


        if self.dry_run or not self._aa_cfg().get("enabled", True):
            return 0
        if sv._alert_type(t.get("subject")) == "locks":
            return 0
        return self._draft_resume(t["id"], t.get("subject", ""), key,
                                  prefix="alert-agent", err_verdict="alert_agent_error",
                                  what="алерта")

    def _draft_resume(self, iid, subject, key, prefix, err_verdict, what):


        d = load_draft(self.root, iid)
        if d:
            st = d.get("status")
            if st == "running":
                alive = any(getattr(th, "name", "") == "%s-%d" % (prefix, iid) and th.is_alive()
                            for th in self._aa_threads())
                if alive:
                    raise _TicketDefer(iid, "агент-разбор %s выполняется в фоне" % what,
                                       quiet=True)
                if int(d.get("relaunches") or 0) >= 1:

                    clear_draft(self.root, iid)
                    self.journal.record(key, err_verdict, subject=subject, issue_id=iid,
                                        note="агент-разбор дважды прервался (рестарт/краш "
                                             "посреди CLI) - ручной разбор")
                    self.log.error("%s #%d: разбор дважды осиротел - сдаюсь", prefix, iid)
                    return None
                self.log.warning("%s #%d: разбор осиротел (рестарт посреди CLI) - "
                                 "перезапускаю (попытка %d)", prefix, iid,
                                 int(d.get("relaunches") or 0) + 1)
                return int(d.get("relaunches") or 0) + 1
            if st == "pending":
                raise _TicketDefer(iid, "черновик разбора ждёт одобрения в чате", quiet=True)

            self.journal.record(key, "draft_closed", subject=subject, issue_id=iid,
                                note="черновик агент-разбора закрыт в чате (status=%s) - "
                                     "ветка %s завершена" % (st, what))
            return None


        self._alert_agent_threads = [th for th in self._aa_threads() if th.is_alive()]
        cap = int(self._aa_cfg().get("max_concurrent", 2))
        if cap and len(self._alert_agent_threads) >= cap:
            raise _TicketDefer(iid, "занято: %d агент-разборов (кап %d, общий на алерты и "
                                    "default)" % (len(self._alert_agent_threads), cap),
                               quiet=True)
        return 0

    def _alert_render_for_draft(self, t, site, setdef):


        shots, meas = [], []
        if not setdef:
            return shots, meas
        ddir = draft_dir(self.root, t["id"])
        os.makedirs(ddir, exist_ok=True)
        try:
            try:
                items = self._grafana_render_panels(t, site, setdef, ddir)
            except _GrafanaSessionExpired as e:

                self.log.warning("#%d: сессия Grafana протухла при рендере для агента (%s) - "
                                 "повторяю с новым логином", t["id"], e)
                items = self._grafana_render_panels(t, site, setdef, ddir)
        except Exception as e:
            self.log.warning("#%d: скрины для агент-разбора не отрендерились (%s) - разбор "
                             "без них", t["id"], e)
            return shots, meas
        for it in items:
            shots.append({"sid": "p%s" % it["panel_id"], "path": it["png"],
                          "title": it["label"], "measurement": it.get("measurement")})
            if it.get("measurement") and it["measurement"] not in meas:
                meas.append(it["measurement"])
        return shots, meas

    def _alert_measurements(self, site, subject):


        try:
            gc = self._service_grafana()
            if not gc or not site.get("uid"):
                return []
            dash = gc.dashboard(site["uid"])
        except Exception as e:
            self.log.info("alert-agent: measurement'ы алерта не собрались (%s)", e)
            return []
        out = []
        try:
            table = gfs.table_from_subject(subject)
            if table:
                tgt = gfs.tablecounts_target(dash, table)
                if tgt:
                    out.append("%s (поле %s)" % (tgt["measurement"], tgt["field"]))
            atype = sv._alert_type(subject)
            if atype:
                for _label, tgt in gfs.service_series_targets(dash, atype, subject):
                    m = "%s (поле %s)" % (tgt["measurement"], tgt["field"])
                    if m not in out:
                        out.append(m)
        except Exception as e:
            self.log.info("alert-agent: таргеты алерта не разобрались (%s)", e)
        return out

    def _alert_agent_dispatch(self, t, key, site, setdef, verdict, alert_state=None,
                              metric_fresh=None, relaunches=0):


        iid = t["id"]
        acfg = self._aa_cfg()

        shots, measurements = self._alert_render_for_draft(t, site, setdef)
        for m in self._alert_measurements(site, t.get("subject", "")):
            if m not in measurements:
                measurements.append(m)

        playbooks = dfl.playbook_index()
        graph_project = _GRAPH_BY_NETWORK.get(site.get("network"))

        code_path = next((v for v in (self.default_cfg.get("docs_dirs") or {}).values()
                          if os.path.basename(str(v).rstrip("/")) == graph_project),
                         None) if graph_project else None
        hints = build_hints(verdict, alert_state=alert_state, metric_fresh=metric_fresh)
        prompt = build_alert_prompt(
            iid, "%s (%s)" % (site.get("warehouse") or site["code"], site["code"]),
            t.get("subject", ""), t.get("description", ""), shots, measurements,
            hints_block=hints, playbooks=playbooks, graph_project=graph_project,
            code_path=code_path)


        try:
            contours = dfl.contour_project_ids(t.get("project", ""), self._all_projects(),
                                               self.default_cfg.get("contour_overrides"))
        except Exception as e:
            contours = []
            self.log.warning("alert-agent #%d: контуры клиента не собрались (%s) - "
                             "search_similar будет отключён", iid, e)

        srv = (self.cfg.get("db", {}).get("servers") or {}).get(site["code"]) or {}
        sql_env = {"WA_DB_HOST": str(srv.get("host") or ""),
                   "WA_DB_PORT": str(srv.get("port") or 1433),
                   "WA_DB_LOGIN": self.cfg.get("locks", {}).get("login", "sa") or "sa",
                   "WA_DB_WHSE": "wmwhse2" if site["code"] == "CLE" else "wmwhse1"}
        if srv.get("tdsver"):
            sql_env["WA_DB_TDSVER"] = str(srv["tdsver"])
        influx_env = {"WA_GF_BASE": self.gf_cfg.get("base", "http://service.example.invalid"),
                      "WA_GF_USER": self.gf_user or "",
                      "WA_GF_PASSWORD": self.gf_password or "",
                      "WA_GF_DS_ID": str(self.gf_cfg.get("influx_ds_id", 3)),
                      "WA_GF_DB": self.gf_cfg.get("influx_db", "telegraf")}

        draft = {"issue_id": iid, "subject": t.get("subject", ""), "kind": "alert",
                 "status": "running", "analysis": "", "sql": "",
                 "screenshots": [{"sid": s["sid"],
                                  "file": os.path.relpath(s["path"], self.root),
                                  "title": s["title"], "approved": False} for s in shots],
                 "comment": "", "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                 "session_id": None}
        if relaunches:
            draft["relaunches"] = int(relaunches)
        save_draft(self.root, iid, draft)
        self.journal.record(key, "alert_agent_started", subject=t.get("subject", ""),
                            issue_id=iid, interim=True,
                            note="агент-разбор запущен в фоне (скринов %d, метрик %s, "
                                 "граф=%s)%s" % (len(shots), len(measurements),
                                                 graph_project or "нет",
                                                 " [повтор сироты]" if relaunches else ""))


        url, keytok = self._rm_url, self._rm_key
        run_model = acfg.get("model", "claude-opus-4-8")
        run_effort = acfg.get("effort", "high")
        timeout = int(acfg.get("cli_timeout_sec", 900))
        claude_bin = self.llm_cfg.get("claude_bin", "claude")
        search_limit = int(self.default_cfg.get("search_limit", 40))
        add_dirs = [draft_dir(self.root, iid)] + ([dfl.PLAYBOOK_DIR] if playbooks else [])
        subj = t.get("subject", "")

        def _run_once():
            return analyze_alert(prompt, iid, url, keytok, contours,
                                 sql_env=sql_env, influx_env=influx_env,
                                 graph=bool(graph_project), model=run_model,
                                 effort=run_effort, timeout=timeout, add_dirs=add_dirs,
                                 search_limit=search_limit, log=self.log.info,
                                 claude_bin=claude_bin)

        self._spawn_draft_worker(iid, key, subj, _run_once,
                                 prefix="alert-agent", err_verdict="alert_agent_error",
                                 defer_note="агент-разбор алерта запущен в фоне",
                                 run_model=run_model, run_effort=run_effort, timeout=timeout)

    def _spawn_draft_worker(self, iid, key, subj, run_once, prefix, err_verdict, defer_note,
                            run_model="?", run_effort="?", timeout=0):


        def _work():
            try:


                t0 = time.monotonic()
                r = run_once()
                run_seconds = time.monotonic() - t0
                if not r.get("ok") and "post_private_note" not in (r.get("tool_log") or ""):


                    self.log.warning("%s #%d: пасс не удался (%s) - повторяю один раз",
                                     prefix, iid, r.get("error"))
                    t1 = time.monotonic()
                    r = run_once()
                    run_seconds += time.monotonic() - t1
                if r.get("tool_log"):
                    self.log.info("%s #%d: аудит тул-вызовов:\n%s", prefix, iid, r["tool_log"])
                d2 = r.get("draft")
                if d2 and d2.get("note"):
                    fin = finalize_draft(self.root, iid, d2["note"],
                                         session_id=r.get("session_id"),
                                         approved=d2.get("approved_screenshots"),
                                         analysis_seconds=run_seconds)
                    conf = d2.get("confidence") or "не указана"
                    napp = sum(1 for s in fin.get("screenshots", []) if s.get("approved"))
                    sid_s = (", session=%s" % r["session_id"]) if r.get("session_id") else ""
                    self.journal.record(key, "draft_ready", subject=subj, issue_id=iid,
                                        interim=True, detail=fin.get("analysis"),
                                        note="черновик разбора готов (confidence=%s, скринов "
                                             "одобрено %d/%d) - ждёт одобрения в чате%s"
                                             % (conf, napp, len(fin.get("screenshots", [])),
                                                sid_s))
                    self.log.info("%s #%d: черновик готов (confidence=%s) - жду "
                                  "одобрения в чате", prefix, iid, conf)

                    notify.emit(self, "draft_ready", iid, subj,
                                "черновик разбора готов (confidence=%s) - ждёт "
                                "одобрения в чате" % conf)
                else:

                    clear_draft(self.root, iid)
                    self.journal.record(key, err_verdict, subject=subj, issue_id=iid,
                                        detail=r.get("result") or None,
                                        note="агент не подготовил черновик (ok=%s, %s) - "
                                             "ручной разбор" % (r.get("ok"),
                                                                r.get("error") or "без ошибки"))
                    self.log.warning("%s #%d: черновика нет (ok=%s, %s) - ручной разбор",
                                     prefix, iid, r.get("ok"), r.get("error"))
            except Exception:


                self.log.exception("%s #%d: фоновый разбор упал", prefix, iid)

        self._alert_agent_threads = [th for th in self._aa_threads() if th.is_alive()]
        th = threading.Thread(target=_work, name="%s-%d" % (prefix, iid), daemon=True)
        self._alert_agent_threads.append(th)
        th.start()
        self.log.info("%s #%d: запущен в фоне (модель %s, effort=%s, таймаут %dс, "
                      "фоновых теперь %d)", prefix, iid, run_model, run_effort, timeout,
                      len(self._alert_agent_threads))

        raise _TicketDefer(iid, defer_note, quiet=True)
