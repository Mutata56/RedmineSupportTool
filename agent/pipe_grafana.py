# -*- coding: utf-8 -*-


import http.client
import json
import os
import tempfile
import time
import urllib.error
from datetime import datetime, timezone

from .agent_base import (_GrafanaSessionExpired, _TicketDefer, _load_json, _write_json,
                         gfs, sv, tr, tv, RoleMixin)
from . import notify
from .alert_agent import AlertAgentMixin


class GrafanaMixin(AlertAgentMixin, RoleMixin):

    def _service_influx_series(self, gc, site, verdict, subject):


        uid = site.get("uid")
        if not uid:
            return
        dash = gc.dashboard(uid)
        targets = gfs.service_series_targets(dash, verdict.get("type"), subject)
        if not targets:
            self.log.info("influx: панель типа %s на доске %s не найдена - ряд не добавляю",
                          verdict.get("type"), uid)
            return
        blocks = []
        for label, tgt in targets:
            q = gfs.influx_series_query(
                tgt, window=self.gf_cfg.get("influx_window", "30h"),
                every=self.gf_cfg.get("influx_step", "10m"),
                limit=self.gf_cfg.get("influx_points", 200))
            try:
                raw = gc.influx(q, ds_id=self.gf_cfg.get("influx_ds_id", 3),
                                db=self.gf_cfg.get("influx_db", "telegraf"))
            except Exception as e:
                self.log.warning("influx: запрос «%s» упал (%s)", label, e)
                continue
            res = (raw.get("results") or [{}])[0]
            if res.get("error"):
                self.log.warning("influx: «%s» вернул ошибку (%s)", label, res["error"])
                continue
            series = res.get("series") or []
            vals = series[0].get("values") if series else None
            block = gfs.format_series(label, vals) if vals else None
            if block:
                blocks.append(block)
        if blocks:
            verdict["influx_series"] = "\n\n".join(blocks)
            self.log.info("influx: в разбор алерта (%s) добавлено рядов из InfluxDB: %d",
                          verdict.get("type"), len(blocks))


    def _service_grafana(self):


        if self._svc_gf == "dead":
            return None
        if self._svc_gf is None:
            from .grafana_client import GrafanaClient
            if not self.gf_password:
                return None
            gc = GrafanaClient(self.gf_cfg.get("base", "http://service.example.invalid"),
                               self.gf_user or "", self.gf_password)
            try:
                gc.login()
            except Exception as e:
                self.log.warning("grafana: логин не удался (%s) - до конца прохода "
                                 "живость/alert_state не проверяю", e)
                self._svc_gf = "dead"
                return None
            self._svc_gf = gc
        return self._svc_gf


    def _service_metric_fresh(self, gc, site, subject):


        try:
            atype = sv._alert_type(subject)
            if not atype or not site.get("uid"):
                return None
            targets = gfs.service_series_targets(gc.dashboard(site["uid"]), atype, subject,
                                                 limit_panels=3)
            if not targets:
                return None
            ds_id = self.gf_cfg.get("influx_ds_id", 3)
            db = self.gf_cfg.get("influx_db", "telegraf")
            for _label, tgt in targets:
                q = gfs.influx_series_query(tgt, window="20m", every="1m", limit=5)
                r0 = (gc.influx(q, ds_id=ds_id, db=db).get("results") or [{}])[0]
                if r0.get("error"):
                    return None
                series = r0.get("series") or []
                if series and any(v[1] is not None for v in (series[0].get("values") or [])):
                    return True
            return False
        except Exception as e:
            self.log.warning("freshness: проверка «жива ли метрика» не удалась (%s) - "
                             "закрываю по alert_state как раньше", e)
            return None


    @staticmethod
    def _locks_manual_note(verdict):


        base = (verdict.get("comment") or "h3. Разбор").rstrip()
        note = "Выполнить запрос вручную."
        if note.lower() not in base.lower():
            verdict["comment"] = base + "\n\n" + note

    def _make_table_runner(self, code):


        import re as _re
        import socket
        noop = lambda: None
        dbcfg = self.cfg.get("db", {})
        if not dbcfg.get("enabled"):
            return None, noop
        srv = (dbcfg.get("servers") or {}).get(code)
        if not srv or not srv.get("host"):
            return None, noop
        from . import sql_engine as sqle
        login = srv.get("login") or dbcfg.get("login_default") or "wmwhse1"
        pwd = sqle.read_db_pass(login)
        if not pwd:
            self.log.warning("db: нет пароля логина %s (secrets db.logins) - разбор без чисел", login)
            return None, noop
        host, port = srv["host"], int(srv.get("port", 1433))
        try:
            socket.create_connection((host, port), timeout=dbcfg.get("connect_timeout", 4)).close()
        except OSError as e:
            self.log.warning("db: %s (%s:%d) недоступен (%s) - разбор без чисел", code, host, port, e)
            return None, noop
        prev_tdsver = os.environ.get("DBPICK_TDSVER")
        if srv.get("tdsver"):
            os.environ["DBPICK_TDSVER"] = str(srv["tdsver"])
        timeout = int(dbcfg.get("count_timeout", 15))
        state = {"sess": None, "dead": False}

        def close():


            if srv.get("tdsver"):
                if prev_tdsver is None:
                    os.environ.pop("DBPICK_TDSVER", None)
                else:
                    os.environ["DBPICK_TDSVER"] = prev_tdsver
            if state["sess"] is not None:
                try:
                    state["sess"].close()
                except Exception:
                    pass
                state["sess"] = None

        def run(bare_sql):
            if state["dead"]:
                return None
            ok, why = sqle.read_only_guard(bare_sql)
            if not ok:
                self.log.warning("db: запрос отклонён read-only-гардом (%s), пропускаю", why)
                return None
            try:
                if state["sess"] is None:
                    s = sqle.TsqlSession(host, port, login, pwd)
                    s.start(sync_timeout=timeout)
                    state["sess"] = s
                ok2, out = state["sess"].run_batch(bare_sql, timeout=timeout)
                if not ok2:
                    self.log.warning("db: %s - запрос вернул ошибку, разбор без числа", code)
                    return None
                _hdr, rows = sqle._tsql_rows(out)
                if not rows or not rows[0]:
                    return None
                val = rows[0][0].strip()
                if _re.fullmatch(r"-?\d+", val):
                    val = format(int(val), ",").replace(",", " ")
                return val
            except Exception as e:
                self.log.warning("db: %s - сессия оборвалась (%s), дальше разбор без чисел", code, e)
                state["dead"] = True
                close()
                return None

        return run, close


    def _init_ticket_cursor(self):
        if os.path.exists(self._ticket_cursor_file):
            try:
                return int(_load_json(self._ticket_cursor_file).get("last_id", 0))
            except (json.JSONDecodeError, ValueError):
                pass
        try:
            last = self.redmine.newest_issue_id(self.gf_cfg.get("tracker_id", 65))
        except Exception as e:
            self.log.error("grafana: не снял точку старта по заявкам (%s)", e)
            return None
        self._save_ticket_cursor(last)
        self.log.info("grafana: точка старта - заявка #%d, старые не трогаем", last)
        return last


    def _save_ticket_cursor(self, last_id):
        _write_json(self._ticket_cursor_file, {"last_id": last_id})


    @staticmethod
    def _ticket_created(t):

        try:
            return datetime.strptime(t["created_on"][:19], "%Y-%m-%dT%H:%M:%S").replace(
                tzinfo=timezone.utc)
        except (ValueError, KeyError, TypeError):
            return None


    def _maybe_handle_storm(self, new, stats):


        thr = self.gf_cfg.get("storm_threshold", 7)
        if thr <= 0:
            return set()
        fresh_win = self.gf_cfg.get("storm_window_minutes", 10)
        now = datetime.now(timezone.utc)


        fresh = []
        for t in new:
            if not gfs.site_from_subject(t["subject"]):
                continue
            if self.journal.seen("ticket-%d" % t["id"]):
                continue
            cr = self._ticket_created(t)
            if cr is None:
                continue
            if (now - cr).total_seconds() / 60.0 <= fresh_win:
                fresh.append(t)
        if len(fresh) < thr:
            return set()

        grafana = sorted(fresh, key=lambda x: x["id"])
        anchor = grafana[0]["id"]

        handled = set()
        self.log.warning("ШТОРМ заявок: %d графановских за <=%d мин (порог %d) - беру все в "
                         "работу, привязываю к опорной #%d", len(grafana), fresh_win, thr, anchor)
        for t in grafana:
            key = "ticket-%d" % t["id"]
            proj_name = t.get("project") or t.get("project_name") or ""
            if not self._auto_take_enabled(proj_name):


                self.journal.record(key, "take_disabled", subject=t["subject"], issue_id=t["id"],
                                    note=self._take_off_note(proj_name) + " (шторм) - не трогаю")
                handled.add(t["id"])
                continue
            if self.dry_run:
                self.journal.record(key, "storm_dry_run", subject=t["subject"], issue_id=t["id"],
                                    note="ВЗЯЛ БЫ в работу + привязал к #%d (шторм)" % anchor)
                handled.add(t["id"])
                continue
            try:
                tid, _tlbl = self._role_for_client(t.get("project") or t.get("project_name") or "")
                self.redmine.take_issue(t["id"], tid, self.cfg.get("work_status_id", 2))
                if t["id"] != anchor:
                    self.redmine.add_relation(t["id"], anchor)
                self.journal.record(key, "storm_grouped", subject=t["subject"], issue_id=t["id"],
                                    note="взята в работу + привязана к #%d (шторм, НЕ закрыта)" % anchor)
                handled.add(t["id"])
            except Exception as e:


                self._deferred_178.setdefault(t["id"], time.time())
                self.log.error("шторм: #%d не обработана (%s) - повторим", t["id"], e)
        return handled


    @staticmethod
    def _issue_to_ticket(i):

        return {"id": i["id"], "subject": i.get("subject", ""),
                "status": i.get("status", {}).get("name", ""),
                "assigned_to_id": (i.get("assigned_to") or {}).get("id"),
                "assigned_to": (i.get("assigned_to") or {}).get("name", ""),
                "author": (i.get("author") or {}).get("name", ""),
                "created_on": i.get("created_on", ""),
                "description": i.get("description", ""),


                "project": (i.get("project") or {}).get("name", "")}


    def _poll_tickets(self, stats):
        self._svc_gf = None
        new = self.redmine.issues_after(self.gf_cfg.get("tracker_id", 65), self.ticket_cursor)

        try:
            self._maybe_handle_storm(new, stats)
        except Exception:
            self.log.exception("детект шторма упал, продолжаю обычным флоу")
        for t in new:
            key = "ticket-%d" % t["id"]
            if not self.journal.seen(key):
                try:
                    self._process_ticket(t, key, stats)
                    self._deferred_178.pop(t["id"], None)
                except _TicketDefer as d:


                    self._deferred_178.setdefault(t["id"], time.time())
                    self.log.warning("заявка #%d отложена (Redmine/VPN недоступен: %s) - "
                                     "повторим следующим проходом", t["id"], d.err)
                    break
                except Exception:


                    self.log.exception("заявка #%d: краш обработки, пропускаю", t["id"])
                    self.journal.record(key, "error", subject=t.get("subject", ""),
                                        issue_id=t["id"], note="краш обработки заявки (пропущено)")
            self.ticket_cursor = t["id"]
            self._save_ticket_cursor(t["id"])


    def _process_ticket(self, t, key, stats, force=False):


        site = gfs.site_from_subject(t["subject"])
        setdef = gfs.match_set(t["subject"], self.gf_sets)
        tr.trace("алерт #%d: площадка=%s, набор графиков=%s", t["id"],
                 site["code"] if site else "не распознана",
                 setdef["name"] if setdef else "нет")
        take_anyway = bool(site) and self.gf_cfg.get("take_without_set", False)
        if not site or (not setdef and not take_anyway):
            self.journal.record(key, "ticket_no_match", subject=t["subject"],
                                issue_id=t["id"],
                                note="site=%s набор=%s автор=%s" % (
                                    bool(site), setdef["name"] if setdef else None, t["author"]))
            return


        relaunches = self._alert_agent_resume(t, key)
        if relaunches is None:
            return


        max_age = self.gf_cfg.get("max_ticket_age_minutes", 15)


        if max_age and not force and not relaunches:
            cr = self._ticket_created(t)
            if cr is None:
                self.journal.record(key, "ticket_no_date", subject=t["subject"], issue_id=t["id"],
                                    note="не разобрал created_on=%r - не беру (берём только свежие)"
                                         % t.get("created_on"))
                return


            ref_ts = self._deferred_178.get(t["id"])
            ref = (datetime.fromtimestamp(ref_ts, timezone.utc) if ref_ts
                   else datetime.now(timezone.utc))
            age_min = (ref - cr).total_seconds() / 60.0
            if age_min > max_age:
                self.journal.record(key, "ticket_stale", subject=t["subject"], issue_id=t["id"],
                                    note="создана %.0f мин назад (порог %d) - старая, не беру"
                                         % (age_min, max_age))
                self.log.info("заявка #%d пропущена: старше %d мин (%.0f мин назад)",
                              t["id"], max_age, age_min)
                return


        take_statuses = self.gf_cfg.get("take_statuses", ["Новая", "В процессе: В работе"])
        if take_statuses and not force and t["status"] not in take_statuses:
            self.journal.record(key, "ticket_status_skip", subject=t["subject"], issue_id=t["id"],
                                note="статус '%s' не берём (берём %s)" % (t["status"], take_statuses))
            return


        proj_name = t.get("project") or t.get("project_name") or ""
        if not self._auto_take_enabled(proj_name):
            self.journal.record(key, "take_disabled", subject=t["subject"], issue_id=t["id"],
                                note=self._take_off_note(proj_name) + " - заявку не трогаю")
            self.log.info("алерт #%d: %s - пропускаю", t["id"], self._take_off_note(proj_name))
            return

        set_name = setdef["name"] if setdef else "без набора (только в работу)"


        verdict = None
        astate_hint = fresh_hint = None
        tr.status("готовлю разбор алерта #%d (%s)", t["id"],
                  "таблица " + (gfs.table_from_subject(t["subject"]) or "?")
                  if self.table_analysis and gfs.table_from_subject(t["subject"])
                  else "сервисный/без разбора")
        if self.table_analysis and gfs.table_from_subject(t["subject"]):

            gc = None
            astate = None
            try:
                gc = self._service_grafana()
                if gc and site.get("uid"):
                    astate = gc.alert_state(site["uid"], gfs.table_from_subject(t["subject"]))
            except Exception as e:


                self.log.warning("#%d: состояние алерта Grafana не прочитано (%s) - разбор без него",
                                 t["id"], e)
                astate = None
            astate_hint = astate


            run_sql, close_sql = ((None, lambda: None)
                                  if self._aa_cfg().get("enabled", True)
                                  else self._make_table_runner(site["code"]))
            try:
                verdict = tv.build_verdict(t["subject"], self.table_analysis,
                                           alert_state=astate, sql_runner=run_sql)
            finally:
                close_sql()
        elif sv._alert_type(t["subject"]):
            influx_fn = None
            astate = None
            gc = None
            try:
                gc = self._service_grafana()
                if gc:
                    influx_fn = gc.influx
                    if site.get("uid"):
                        astate = gc.alert_state(site["uid"], sv.alert_name_substr(t["subject"]))
            except Exception as e:


                self.log.warning("#%d: Grafana для сервисного разбора недоступна (%s) - "
                                 "без influx-ряда и состояния алерта", t["id"], e)
                influx_fn = None


            metric_fresh = None
            if astate == "ok" and gc:
                metric_fresh = self._service_metric_fresh(gc, site, t["subject"])
            astate_hint, fresh_hint = astate, metric_fresh
            verdict = sv.build_service_verdict(
                t["subject"], site_name=(site.get("warehouse") or site["code"]),
                code=site["code"], influx=influx_fn, alert_state=astate,
                description=t.get("description"), metric_fresh=metric_fresh)


            if verdict and verdict.get("type") == "locks":
                self._locks_manual_note(verdict)


        already_working = (t["status"] == "В процессе: В работе" and t.get("assigned_to_id"))
        take_desc = ("не перевешиваю (уже в работе на '%s')" % (t.get("assigned_to") or "ком-то")
                     if already_working else "взял бы на себя")
        tr.trace("алерт #%d: вердикт=%s, %s", t["id"],
                 verdict["mode"] if verdict else "нет", take_desc)

        if self.dry_run:
            vinfo = ""
            if verdict:
                vinfo = " | разбор: %s (%s)" % (verdict["mode"], verdict["reason"][:50])
            self.journal.record(key, "grafana_dry_run", subject=t["subject"], issue_id=t["id"],
                                note="%s + %s (%s, доска %s)%s" % (
                                    take_desc, set_name, site["code"], site["uid"], vinfo))
            self.log.info("ВЗЯЛ БЫ #%d '%s' -> %s | %s (%s)%s",
                          t["id"], t["subject"][:60], take_desc, set_name, site["code"], vinfo)

            notify.emit(self, "new_ticket", t["id"], t["subject"],
                        "новый алерт-тикет, взял бы в работу (dry-run)")
            if verdict and verdict["mode"] == "deterministic":

                self.log.info("  готов детерминированный разбор (%s) - лёг бы ПЕРЕД графиками",
                              verdict.get("table") or verdict.get("type") or "?")
            return


        if already_working:
            self.log.info("заявка #%d уже в работе на '%s' - назначение не трогаю, только разбор/графики",
                          t["id"], t.get("assigned_to") or "ком-то")
            self.journal.record(key, "taken_in_work", subject=t["subject"], issue_id=t["id"],
                                interim=True,
                                note="уже в работе на «%s» - назначение не трогаем"
                                     % (t.get("assigned_to") or "ком-то"))
            notify.emit(self, "new_ticket", t["id"], t["subject"],
                        "новый алерт-тикет взят в обработку (уже был в работе)")
        else:


            tid, tlbl = self._role_for_client(t.get("project") or t.get("project_name") or "")
            try:
                self.redmine.take_issue(t["id"], tid, self.cfg.get("work_status_id", 2))
                self.log.info("заявка #%d взята в работу (%s)", t["id"], tlbl)
                self.journal.record(key, "taken_in_work", subject=t["subject"], issue_id=t["id"],
                                    interim=True, note="взята в работу (%s, статус «В работе»)" % tlbl)

                notify.emit(self, "new_ticket", t["id"], t["subject"],
                            "новый алерт-тикет взят в работу")
            except urllib.error.HTTPError as e:
                if e.code == 429 or e.code >= 500:
                    raise _TicketDefer(t["id"], e)

                self.journal.record(key, "error", subject=t["subject"], issue_id=t["id"],
                                    note="не взял в работу (HTTP %d): %s" % (e.code, e))
                self.log.error("не взял #%d в работу (HTTP %d): %s", t["id"], e.code, e)
                return
            except (urllib.error.URLError, OSError, http.client.HTTPException) as e:


                raise _TicketDefer(t["id"], e)
            except Exception as e:
                self.journal.record(key, "error", subject=t["subject"], issue_id=t["id"],
                                    note="не взял в работу: %s" % e)
                self.log.error("не взял #%d в работу: %s", t["id"], e)
                return


        is_locks = bool(verdict and verdict.get("type") == "locks")
        if not is_locks and self._aa_cfg().get("enabled", True):
            tr.status("отдаю алерт #%d агент-разбору (запертый CLI)", t["id"])
            self._alert_agent_dispatch(t, key, site, setdef, verdict,
                                       alert_state=astate_hint, metric_fresh=fresh_hint,
                                       relaunches=relaunches)
            return


        if verdict and verdict["mode"] == "deterministic" and verdict["comment"]:
            posted = False
            try:
                self.redmine.add_note(t["id"], verdict["comment"], private=True)
                self.log.info("#%d: приложен детерминированный разбор (%s)",
                              t["id"], verdict.get("table") or verdict.get("type") or "?")
                self.journal.record(key, "note_posted", subject=t["subject"], issue_id=t["id"],
                                    interim=True, detail=verdict["comment"],
                                    note="приватный коммент: детерминированный разбор (%s)"
                                         % (verdict.get("table") or verdict.get("type") or "?"))
                posted = True
            except Exception as e:
                self.log.warning("#%d: разбор не приложился (%s)", t["id"], e)
        elif verdict and verdict["mode"] == "llm":


            self.log.info("#%d: аномальный случай (%s), агент-разбор выключен - в Redmine "
                          "ничего не пишем", t["id"], verdict.get("reason", "?"))


        if verdict and verdict.get("type") == "locks":
            self.journal.record(key, "ticket_taken", subject=t["subject"], issue_id=t["id"],
                                note="LOCKS: приложен запрос «выполнить вручную», графики не "
                                     "снимаем, на DBA не передаём")
            return


        if not setdef:
            self.journal.record(key, "ticket_taken", subject=t["subject"], issue_id=t["id"],
                                note="взята в работу без графиков (набора нет)")
            return
        try:
            try:
                n, note_text = self._grafana_attach(t, site, setdef)
            except _GrafanaSessionExpired as e:


                self.log.warning("#%d: сессия Grafana протухла (%s) - повторяю с новым логином",
                                 t["id"], e)
                n, note_text = self._grafana_attach(t, site, setdef)
            self.journal.record(key, "grafana_attached", subject=t["subject"], issue_id=t["id"],
                                detail=note_text,
                                note="набор «%s», панелей %d%s" % (
                                    setdef["name"], n,
                                    "; +разбор" if (verdict and verdict["mode"] == "deterministic") else ""))
            self.log.info("к #%d прикреплено %d графиков (набор «%s»)", t["id"], n, setdef["name"])
        except Exception as e:
            self.journal.record(key, "grafana_error", subject=t["subject"], issue_id=t["id"],
                                note="в работу взята, графики не приложились: %s" % e)
            self.log.warning("#%d: графики не приложились (%s) - заявка уже в работе", t["id"], e)


    def _gf_period(self):

        frm = self.gf_cfg.get("from", "now-6h")
        return {"now-1h": "1ч", "now-6h": "6ч", "now-24h": "24ч", "now-7d": "7д"}.get(frm, frm)

    def _grafana_render_panels(self, t, site, setdef, dest_dir):


        from .grafana_client import GrafanaClient
        from .grafana_render import HeadlessBrowser, find_browser

        if not self.gf_password:
            raise RuntimeError("нет grafana_password в secrets.local.json")
        base = self.gf_cfg.get("base", "http://service.example.invalid")
        gf = GrafanaClient(base, self.gf_user or "", self.gf_password)
        gf.login()
        dash = gf.dashboard(site["uid"])
        slug = dash.get("meta", {}).get("slug", "x")
        dname = dash["dashboard"].get("title", site["uid"])
        items = gfs.panels_catalog(dash)
        specs = gfs.resolve_panels(setdef, t["subject"])
        sel = gfs.filter_set(items, specs)
        if site["network"] == "cle":

            sel = [it for it in sel
                   if "wmwhse" not in it["title"].lower() or "wmwhse2" in it["title"].lower()]
        if not sel:
            raise RuntimeError("панели набора не нашлись на доске %s" % site["uid"])

        meas_by_id = {str(p.get("id")): (gfs._target_of(p) or {}).get("measurement")
                      for p in gfs._flat_panels(dash)}

        frm = self.gf_cfg.get("from", "now-6h")
        to = self.gf_cfg.get("to", "now")
        period = self._gf_period()
        browser = None
        out = []
        try:
            browser = HeadlessBrowser(find_browser(self.gf_cfg.get("browser_path", "")))
            browser.set_cookie("grafana_session", gf.cookie,
                               self.gf_cfg.get("cookie_domain", "192.0.2.10"))
            for it in sel:
                url = "%s/d-solo/%s/%s?orgId=1&panelId=%s&from=%s&to=%s&theme=dark" % (
                    base, site["uid"], slug, it["id"], frm, to)
                png = os.path.join(dest_dir, "p%s.png" % it["id"])
                tr.status("рендерю панель «%s» (#%s) для заявки #%d", it["title"], it["id"], t["id"])
                try:
                    status = browser.render(
                        url, png,
                        width=self.gf_cfg.get("panel_width", 1100),
                        height=self.gf_cfg.get("panel_height", 520),
                        scale=self.gf_cfg.get("panel_scale", 2),
                        hover=self.gf_cfg.get("hover", True))
                    if status == "login":
                        raise _GrafanaSessionExpired("сессия Grafana протухла при рендере")
                    if status == "timeout" or not os.path.exists(png):
                        self.log.warning("панель «%s» не отрендерилась (%s)", it["title"], status)
                        continue
                    if status == "nodata" and not it.get("always"):
                        continue
                    role = it.get("rolecat", "")
                    label = it["title"] + ((" · " + role) if role and role.lower() not in it["title"].lower() else "")
                    if self.gf_cfg.get("caption", True):
                        from .grafana_caption import caption_png
                        caption_png(png, dname, it["title"], role,
                                    site["warehouse"] or site["code"], period)
                    out.append({"panel_id": it["id"], "png": png,
                                "fname": "grafana_%d_%s.png" % (t["id"], it["id"]),
                                "title": it["title"], "label": label,
                                "why": it.get("why", ""),
                                "measurement": meas_by_id.get(str(it["id"]))})
                except _GrafanaSessionExpired:
                    raise
                except Exception as e:


                    self.log.warning("панель «%s»: краш обработки (%s), пропускаю", it["title"], e)
                    continue
            if not out:
                raise RuntimeError("ни одна панель набора не отрендерилась")
            return out
        finally:
            if browser:
                browser.close()

    def _grafana_attach(self, t, site, setdef):


        tmpdir = tempfile.mkdtemp(prefix="wa_gfpng_")
        try:
            pairs = self._grafana_render_panels(t, site, setdef, tmpdir)
            uploads = []
            for p in pairs:
                with open(p["png"], "rb") as f:
                    uploads.append({"token": self.redmine.upload(f.read(), p["fname"]),
                                    "filename": p["fname"], "content_type": "image/png"})
            head = "Графики Grafana (%s, период %s):" % (site["warehouse"] or site["code"],
                                                         self._gf_period())
            note_text = head + "\n\n" + "\n\n".join(
                "%s\n!%s!" % (p["label"] + ((" - " + p["why"]) if p["why"] else ""), p["fname"])
                for p in pairs)
            self.redmine.add_note(t["id"], note_text, uploads=uploads, private=True)
            pn = setdef.get("private_note")
            if pn:
                self.redmine.add_note(t["id"], pn, private=True)
                note_text += "\n\n--- отдельный приватный коммент-памятка ---\n" + pn
            return len(pairs), note_text
        finally:
            import shutil as _sh
            _sh.rmtree(tmpdir, ignore_errors=True)
