# -*- coding: utf-8 -*-


import http.client
import os
import threading
import time
import urllib.error

from . import alert_agent as aa
from . import notify
from .agent_base import _TicketDefer, approvals, dfl, tr, RoleMixin


class DefaultMixin(RoleMixin):

    def _all_projects(self):


        if self._all_projects_cache is not None:
            return self._all_projects_cache
        self._all_projects_cache = [
            {"id": p["id"], "name": p.get("name", "")}
            for p in self.redmine.paged("/projects.json", item_key="projects", max_pages=50)]
        return self._all_projects_cache


    def _process_default(self, issue, key, stats):


        iid = issue["id"]
        subj = issue.get("subject", "")
        proj = (issue.get("project") or {}).get("name", "")
        stats["default"] = stats.get("default", 0) + 1
        if not self._auto_take_enabled(proj):
            self.journal.record(key, "take_disabled", subject=subj, issue_id=iid,
                                note=self._take_off_note(proj) + " - заявку не трогаю")
            self.log.info("default #%d: %s - пропускаю", iid, self._take_off_note(proj))
            return
        tid, tlbl = self._role_for_client(proj)
        if self.dry_run:
            self.journal.record(key, "default_dry", subject=subj, issue_id=iid,
                                note="DRY-RUN: взял бы в работу (%s)" % tlbl)
            self.log.info("ВЗЯЛ БЫ default #%d '%.60s' -> %s (DRY)", iid, subj, tlbl)
            return

        if issue.get("status", {}).get("id") == 2 and issue.get("assigned_to"):
            self.journal.record(key, "ticket_taken", subject=subj, issue_id=iid,
                                note="уже в работе на «%s» - назначение не трогаем"
                                     % ((issue.get("assigned_to") or {}).get("name") or "ком-то"))
            return
        try:
            self.redmine.take_issue(iid, tid, self.cfg.get("work_status_id", 2))
        except urllib.error.HTTPError as e:
            if e.code == 429 or e.code >= 500:
                raise _TicketDefer(iid, e)
            self.journal.record(key, "error", subject=subj, issue_id=iid,
                                note="не взял в работу (HTTP %d): %s" % (e.code, e))
            self.log.error("default #%d: не взял в работу (HTTP %d): %s", iid, e.code, e)
            return
        except (urllib.error.URLError, OSError, http.client.HTTPException) as e:
            raise _TicketDefer(iid, e)
        self.journal.record(key, "ticket_taken", subject=subj, issue_id=iid,
                            note="взята в работу (%s, статус «В работе»)" % tlbl)
        notify.emit(self, "new_ticket", iid, subj, "заявка взята в работу (%s)" % tlbl)
        self.log.info("default #%d '%.60s' взята в работу (%s)", iid, subj, tlbl)


    def _maybe_escalate_alert_to_opus(self, t, verdict, key):


        atype = verdict.get("type")
        types = self.default_cfg.get("escalate_alert_types") or []
        if not (self.default_cfg.get("enabled") and atype in types):
            return
        ex = approvals.load(self.root, t["id"])
        if ex and ex.get("status") == "pending":
            return
        prompt = (
            "Это заявка-алерт типа «%s». Агент уже приложил приватным комментарием готовый "
            "диагностический SQL, дежурный выполнил его и приложил РЕЗУЛЬТАТЫ в комментарии "
            "заявки — ОБЯЗАТЕЛЬНО посмотри их через get_issue (там журналы/комменты). "
            "Проанализируй: что показывают результаты, вероятная причина алерта и что делать "
            "дежурному по шагам. Для контекста через search_similar найди 3-4 похожие РЕШЁННЫЕ "
            "заявки этого же типа. Итог — одним приватным комментом (post_private_note), честно "
            "укажи confidence." % atype)

        series = verdict.get("influx_series")
        if series:
            prompt += ("\n\nДАННЫЕ ГРАФИКА НА МОМЕНТ АЛЕРТА (ряд метрики из InfluxDB — замена "
                       "скриншоту; это ТРЕНД на момент срабатывания, для оценки динамики. Текущие "
                       "цифры бери из результатов SQL в комментах заявки, они свежее):\n" + series)
        self._request_opus(t["id"], t["subject"], t.get("description", ""),
                           t.get("project", ""), origin_key=key,
                           reason="alert_analysis", prompt=prompt)


    def _request_opus(self, iid, subj, body, proj, origin_key, reason, prompt=None):


        ex = approvals.load(self.root, iid)
        busy = approvals._busy(ex)
        if busy and (ex or {}).get("pipe") != "opus":
            self.log.debug("opus #%d (%s): у заявки живой approval ветки «%s» (%s) — НЕ "
                           "перезатираю opus-запросом", iid, reason, (ex or {}).get("pipe"), busy)
            return
        preview = {
            "default": "Незнакомая заявка «Запрос от клиента». Разрешить запуск Opus для анализа "
                       "(похожие решённые заявки по контурам клиента + документация/код)?",
            "alert": "Разбор алерта вышел НЕуверенным (low confidence). Разрешить запуск Opus для "
                     "углублённого анализа?",
            "alert_analysis": "Алерт разобран, готовый SQL приложен. СНАЧАЛА прогони SQL и приложи "
                              "результаты в заявку, ЗАТЕМ одобри — Opus 4.8 прочитает результаты и "
                              "сделает анализ (что показывают данные, причина, что делать).",
            "manual": "Ручной запуск Opus по этой заявке.",
        }.get(reason, "Разрешить запуск Opus?")
        if prompt:
            preview += "\n\nТвоя инструкция Opus:\n" + prompt


        approvals.save(self.root, iid, {
            "pipe": "opus", "issue_id": iid, "subject": subj, "reason": reason,
            "origin_key": origin_key, "prompt": prompt or "", "proposal": preview,
            "model": self.default_cfg.get("model", "claude-opus-4-8"),
            "effort": self.default_cfg.get("effort", "high"),
            "status": "pending", "created_at": time.strftime("%Y-%m-%d %H:%M:%S")})
        self.journal.record(origin_key, "opus_requested", subject=subj, issue_id=iid,
                            interim=True, detail=preview,
                            note="запрос на запуск Opus (%s) ждёт одобрения в GUI" % reason)
        self.log.info("opus #%d: запрос на запуск (%s) отправлен в GUI", iid, reason)
        tr.status("жду одобрения на запуск Opus по заявке #%d (%s)", iid, reason)


    def _handle_opus_request(self, i, ap, stats):


        iid = i["id"]
        subj = i.get("subject", "")
        body = i.get("description", "")
        proj = i.get("project", {}).get("name", "")
        origin_key = ap.get("origin_key") or ("opus-%d" % iid)
        st = ap.get("status")
        if ap.get("stage") == "post":
            return self._handle_opus_post(ap, iid, subj, origin_key, st)
        if ap.get("stage") == "running":


            alive = any(getattr(t, "name", "") == "default-%d" % iid and t.is_alive()
                        for t in self._default_threads)
            if alive:
                raise _TicketDefer(iid, "Opus-анализ выполняется в фоне", quiet=True)
            if int(ap.get("relaunches") or 0) >= 1:

                approvals.clear(self.root, iid)
                self.journal.record(origin_key, "default_error", subject=subj, issue_id=iid,
                                    note="Opus-анализ дважды прервался (рестарт/краш) - "
                                         "ручной разбор")
                self.log.error("opus #%d: анализ дважды осиротел - сдаюсь (ручной разбор)", iid)
                return
            ap["relaunches"] = int(ap.get("relaunches") or 0) + 1
            self.log.warning("opus #%d: анализ осиротел (рестарт агента посреди Opus) - "
                             "перезапускаю (попытка %d)", iid, ap["relaunches"])
            st = "approved"
        if st == "pending":
            raise _TicketDefer(iid, "ждёт одобрения запуска Opus", quiet=True)
        if st in ("manual", "ignore"):
            approvals.clear(self.root, iid)
            v = "ignored" if st == "ignore" else "opus_declined"
            note = ("«Игнор» в GUI - заявка помечена обработанной, агент к ней не возвращается"
                    if st == "ignore" else
                    "решение в GUI: вручную - Opus не запускаем, заявка остаётся в работе")
            self.journal.record(origin_key, v, subject=subj, issue_id=iid, note=note)
            self.log.info("opus #%d: решение GUI «%s» - Opus не запускаю", iid, st)
            return

        if self.dry_run:
            approvals.clear(self.root, iid)
            self.journal.record(origin_key, "opus_launched_dry", subject=subj, issue_id=iid,
                                note="ОДОБРЕНО, но DRY-RUN: Opus НЕ запускался (симуляция)")
            self.log.info("opus #%d: одобрено, но DRY - Opus не зову", iid)
            return
        try:
            contours = dfl.contour_project_ids(proj, self._all_projects(),
                                               self.default_cfg.get("contour_overrides"))
        except Exception as e:
            raise _TicketDefer(iid, e, quiet=True)

        self._default_threads = [t for t in self._default_threads if t.is_alive()]
        cap = int(self.default_cfg.get("max_concurrent", 2))
        if cap and len(self._default_threads) >= cap:
            raise _TicketDefer(iid, "занято: %d Opus-анализов (кап %d)"
                                    % (len(self._default_threads), cap), quiet=True)


        ap.update(stage="running", status="approved",
                  started_at=time.strftime("%Y-%m-%d %H:%M:%S"))


        ok, err = approvals.save(self.root, iid, ap, if_rev=ap.get("rev", 0))
        if not ok:
            raise _TicketDefer(iid, "approval изменился под нами (%s)" % err, quiet=True)
        self.journal.record(origin_key, "opus_launched", subject=subj, issue_id=iid,
                            interim=True,
                            note="запуск Opus одобрен в GUI (%s), контуры=%s"
                                 % (ap.get("decided_at", "?"), contours))

        if not (i.get("status", {}).get("id") == 2 and i.get("assigned_to")):
            try:
                self.redmine.take_issue(iid, self._default_assignee(),
                                        self.cfg.get("work_status_id", 2))
            except Exception as e:
                self.log.warning("opus #%d: не взял в работу (%s) - запускаю анализ всё равно", iid, e)
        self._dispatch_default_bg(iid, subj, body, proj, contours, prompt=ap.get("prompt") or None,
                                  model=ap.get("model"), effort=ap.get("effort"),
                                  origin_key=origin_key)


    def _handle_opus_post(self, ap, iid, subj, origin_key, st):


        if st == "pending":
            raise _TicketDefer(iid, "черновик коммента ждёт одобрения публикации", quiet=True)
        if st in ("manual", "ignore"):
            approvals.clear(self.root, iid)
            note = ("«Игнор» в GUI - черновик НЕ опубликован, заявка помечена обработанной"
                    if st == "ignore" else
                    "отклонено (пока): черновик НЕ публикуем, заявка остаётся в работе; чат "
                    "по заявке открыт — можно дописать замечания и попросить переделать")
            self.journal.record(origin_key, "opus_post_declined", subject=subj, issue_id=iid, note=note)
            self.log.info("opus #%d: публикация черновика отклонена в GUI («%s»)", iid, st)
            return

        draft = (ap.get("draft") or "").strip()
        if not draft:
            approvals.clear(self.root, iid)
            self.journal.record(origin_key, "default_error", subject=subj, issue_id=iid,
                                note="одобрена публикация, но черновик пуст - публиковать нечего")
            self.log.warning("opus #%d: одобрена публикация, но черновик пуст", iid)
            return
        if self.dry_run:
            approvals.clear(self.root, iid)
            self.journal.record(origin_key, "opus_launched_dry", subject=subj, issue_id=iid,
                                note="одобрено, но DRY-RUN: коммент НЕ публиковался (симуляция)")
            self.log.info("opus #%d: одобрено, но DRY - коммент не публикую", iid)
            return
        try:
            self.redmine.add_note(iid, draft, private=True)
        except Exception as e:
            raise _TicketDefer(iid, "публикация коммента не удалась: %s" % e)
        approvals.clear(self.root, iid)
        self.journal.record(origin_key, "default_done", subject=subj, issue_id=iid, detail=draft,
                            note="разбор Opus ОПУБЛИКОВАН приватным комментом по одобрению в GUI (%s)"
                                 % ap.get("decided_at", "?"))
        self.log.info("opus #%d: разбор Opus опубликован приватным комментом (по одобрению)", iid)
        tr.status("разбор Opus по заявке #%d опубликован по одобрению", iid)


    def _docs_dir_for(self, proj):


        dd = self.default_cfg.get("docs_dirs") or {}
        if not dd:
            return None
        pref = dfl.client_prefix(proj)
        if pref in dd:
            return dd[pref]
        name = proj or ""
        for k, v in dd.items():
            if name.startswith(k) or pref.startswith(k):
                return v
        return None


    def _dispatch_default_bg(self, iid, subj, body, proj, contours, prompt=None,
                             model=None, effort=None, origin_key=None):


        okey = origin_key or ("default-%d" % iid)
        dcfg = self.default_cfg
        docs_dir = self._docs_dir_for(proj)
        url, keytok = self._rm_url, self._rm_key
        run_model = model or dcfg.get("model", "claude-opus-4-8")
        run_effort = effort or dcfg.get("effort", "high")

        claude_bin = self.llm_cfg.get("claude_bin", "claude")

        def _run_once():
            return dfl.analyze(subj, body, iid, url, keytok, contours,
                               model=run_model, effort=run_effort,
                               timeout=int(dcfg.get("cli_timeout_sec", 600)),
                               dry=True, docs_dir=docs_dir,
                               search_limit=int(dcfg.get("search_limit", 40)),
                               custom_prompt=prompt, log=self.log.info, stage_draft=True,
                               claude_bin=claude_bin,

                               attachments=bool(dcfg.get("attachments", True)),
                               attach_max_files=int(dcfg.get("attach_max_files", 6)),
                               attach_max_mb=float(dcfg.get("attach_max_mb", 15)))

        def _work():
            t0 = time.time()
            try:
                tr.trace("default #%d: фоновый Opus-анализ стартовал (черновик -> одобрение публикации)",
                         iid)
                r = _run_once()
                if not r.get("ok") and "post_private_note" not in (r.get("tool_log") or ""):


                    self.log.warning("default #%d: пасс не удался (%s) - повторяю один раз",
                                     iid, r.get("error"))
                    r = _run_once()
                self.log.info("default #%d: анализ завершён ok=%s пассов=%s (Opus сам НЕ постит — "
                              "черновик на одобрение)", iid, r.get("ok"), r.get("passes"))
                if r.get("tool_log"):
                    self.log.info("default #%d: аудит тул-вызовов:\n%s", iid, r["tool_log"])
                if r.get("result"):
                    self.log.info("default #%d: сводка модели:\n%s", iid, r["result"])
                full = ((r.get("result") or "") +
                        ("\n\n=== аудит тул-вызовов (включая черновик коммента) ===\n"
                         + r["tool_log"] if r.get("tool_log") else "")).strip()
                sid_note = (", session=%s" % r["session_id"]) if r.get("session_id") else ""
                draft = r.get("draft")
                if draft and draft.get("note"):


                    note_txt = draft["note"]
                    conf = draft.get("confidence") or "не указана"
                    aa.save_draft(self.root, iid, {
                        "issue_id": iid, "subject": subj, "kind": "default", "status": "pending",
                        "analysis": note_txt, "comment": "h3. Разбор:\n\n" + note_txt,
                        "sql": "", "screenshots": [],
                        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "session_id": r.get("session_id"), "confidence": conf,
                        "analysis_seconds": round(time.time() - t0, 2)})
                    approvals.clear(self.root, iid)
                    self.journal.record(okey, "opus_draft_ready", subject=subj,
                                        issue_id=iid, interim=True, detail=full or note_txt,
                                        note="Opus подготовил разбор (confidence=%s) — черновик-"
                                             "карточка в GUI ждёт публикации кнопкой%s" % (conf, sid_note))
                    self.log.info("default #%d: черновик разбора готов (confidence=%s) — карточка "
                                  "в GUI (Humanize + Опубликовать)", iid, conf)

                    notify.emit(self, "draft_ready", iid, subj,
                                "Opus подготовил разбор (confidence=%s) - ждёт публикации" % conf)
                    tr.status("черновик разбора Opus по заявке #%d готов (карточка в GUI)", iid)
                else:

                    outcome = "default_error" if not r.get("ok") else "default_done"
                    tr.trace("default #%d: фоновый Opus-анализ завершён: %s (без черновика)", iid, outcome)
                    self.journal.record(okey, outcome, subject=subj, issue_id=iid,
                                        detail=full or None,
                                        note="ok=%s пассов=%s; Opus НЕ подготовил коммент "
                                             "(публиковать нечего)%s; полный ответ ИИ ниже"
                                             % (r.get("ok"), r.get("passes"), sid_note))
                    approvals.clear(self.root, iid)
            except Exception:


                self.log.exception("default #%d: фоновый анализ упал", iid)

        self._default_threads = [t for t in self._default_threads if t.is_alive()]
        self.log.info("default #%d: Opus-анализ запущен в фоне (черновик->одобрение, таймаут %dс, "
                      "контуры=%s, фоновых теперь %d)", iid,
                      int(dcfg.get("cli_timeout_sec", 600)), contours,
                      len(self._default_threads) + 1)
        th = threading.Thread(target=_work, name="default-%d" % iid, daemon=True)
        self._default_threads.append(th)
        th.start()
