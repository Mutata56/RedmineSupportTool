# -*- coding: utf-8 -*-


import email.utils
import http.client
import imaplib
import json
import logging
import os
import re
import time
import urllib.error
from datetime import datetime, timezone

from .agent_base import (
    MSK, DESCRIPTION_TEMPLATE, _TicketDefer, _load_json, _write_json,
    Journal, MailClient, RedmineClient, normalize_subject, classify_server,
    approvals, ccli, gfs, tr,
    clean_subject, extract_route, load_markers, load_routing, match_marker, sender_blacklisted,
)
from .rules import load_pings, match_ping
from .redmine_client import resolve_account
from . import alert_agent
from . import notify
from . import router
from .config_schema import validate as _validate_config
from .pipe_grafana import GrafanaMixin
from .pipe_default import DefaultMixin
from .pipe_shift import ShiftMixin
from . import shifts as shift_sched


class Agent(GrafanaMixin, DefaultMixin, ShiftMixin):
    def __init__(self, root, dry_run_override=None):
        self.root = root
        self.log = logging.getLogger("agent")
        _cfg_path = os.path.join(root, "config", "config.json")
        self.cfg = _load_json(_cfg_path)


        try:
            self._cfg_mtime = os.stat(_cfg_path).st_mtime
        except OSError:
            self._cfg_mtime = None
        _validate_config(self.cfg, self.log)
        secrets = _load_json(os.path.join(root, "config", "secrets.local.json"))

        self.dry_run = self.cfg.get("dry_run", True)
        if dry_run_override is not None:
            self.dry_run = dry_run_override
        self.mode = "DRY-RUN" if self.dry_run else "LIVE"

        self.markers = load_markers(self.cfg)

        self.pings = load_pings(self.cfg)
        self.routing = load_routing(self.cfg)
        self.blacklist = self.cfg.get("sender_blacklist", [])
        self.dedup_cfg = self.cfg.get("dedup", {})
        self.llm_cfg = self.cfg.get("llm", {})
        self.anthropic_key = (secrets.get("anthropic_api_key") or "").strip()

        self._llm_calls_route = []
        self._llm_neg = {}
        self._deferred_mail = {}


        self._deferred_178 = {}


        self.journal = Journal(os.path.join(root, "state", "processed.jsonl"),
                               count_dry=self.dry_run)

        self.notifier = notify.Notifier(self.cfg, secrets, os.path.join(root, "state"),
                                        dry_run=self.dry_run, log=self.log)
        self._poll178_status_file = os.path.join(root, "state", "poll178_status.json")


        self.rm_account = resolve_account(secrets)
        self.redmine = RedmineClient(self.rm_account["url"], self.rm_account["api_key"])
        self.mailer = MailClient(
            self.cfg["imap"]["host"], self.cfg["imap"]["port"],
            secrets["imap_login"], secrets["imap_password"],
            self.cfg["imap"].get("folder", "INBOX"),
        )
        self._cursor_file = os.path.join(root, "state", "last_uid.json")
        self._projects_file = os.path.join(root, "state", "projects_cache.json")
        self._llm_cache_file = os.path.join(root, "state", "llm_routes.json")
        self.projects = self._load_projects()
        self._merge_llm_cache_into_routing()
        self.cursor = self._init_cursor()


        self.default_cfg = self.cfg.get("default_flow", {})


        self._rm_url = self.rm_account["url"]
        self._rm_key = self.rm_account["api_key"]
        self._all_projects_cache = None
        self._default_threads = []


        self.shift_cfg = self.cfg.get("shift_handoff", {})
        self._handoff_stamp_file = os.path.join(root, "state", "last_handoff.json")
        self.schedule = None
        if self.shift_cfg.get("enabled"):
            self.schedule = shift_sched.Schedule.load(
                os.path.join(root, self.shift_cfg.get("schedule_file",
                                                       os.path.join("config", "shift_schedule.json"))))
            if self.schedule is None:
                self.log.warning("смены: график не загрузился (%s) - свип начала смены выключен",
                                 self.shift_cfg.get("schedule_file"))
            else:
                self.log.info("смены: график загружен (%d рабочих дней)", len(self.schedule.workdays))


        self.gf_cfg = self.cfg.get("grafana", {})
        self.gf_user = (secrets.get("grafana_user") or "").strip()
        self.gf_password = (secrets.get("grafana_password") or "").strip()
        self.gf_sets = []
        self._ticket_cursor_file = os.path.join(root, "state", "tickets_cursor.json")
        self.ticket_cursor = None
        if self.gf_cfg.get("enabled"):
            try:
                self.gf_sets = gfs.load_sets(os.path.join(root, self.gf_cfg.get(
                    "sets_file", os.path.join("config", "grafana_sets.yml"))))
                self.log.info("grafana: наборов загружено %d", len(self.gf_sets))
            except Exception as e:
                self.log.error("grafana: наборы не загрузились (%s) - труба выключена", e)
                self.gf_sets = []
            if self.gf_sets:
                self.ticket_cursor = self._init_ticket_cursor()
        self._svc_gf = None

        self.table_analysis = {}
        ap = os.path.join(root, "config", "table_analysis.json")
        if os.path.exists(ap):
            try:
                self.table_analysis = _load_json(ap)
                self.log.info("grafana: годовой анализ таблиц загружен (%d площадок)",
                              len(self.table_analysis))
            except (json.JSONDecodeError, ValueError):
                pass


    def _load_projects(self):
        projects = {}
        if os.path.exists(self._projects_file):
            try:
                projects = {int(k): v for k, v in _load_json(self._projects_file).items()}
            except (json.JSONDecodeError, ValueError):
                projects = {}
        for spec in self.routing.values():
            projects.setdefault(spec["project_id"], spec.get("client", ""))
        return projects


    def _merge_projects(self, dashboard):
        changed = False
        for issue in dashboard:
            pid, name = issue.get("project_id"), issue.get("project_name", "")
            if pid and (pid not in self.projects or (name and not self.projects[pid])):
                self.projects[pid] = name
                changed = True
        if changed:
            _write_json(self._projects_file,
                        {str(k): v for k, v in self.projects.items()}, indent=1)


    def _merge_llm_cache_into_routing(self):
        if not os.path.exists(self._llm_cache_file):
            return
        try:
            cache = _load_json(self._llm_cache_file)
        except (json.JSONDecodeError, ValueError):
            return
        added = 0
        for key, spec in cache.items():
            key = key.upper()

            if isinstance(spec, dict) and spec.get("project_id") and key not in self.routing:
                self.routing[key] = spec
                added += 1
        if added:
            self.log.info("из LLM-кэша подгружено маршрутов: %d (state/llm_routes.json)", added)


    def _cache_llm_route(self, key, route):
        data = {}
        if os.path.exists(self._llm_cache_file):
            try:
                data = _load_json(self._llm_cache_file)
            except (json.JSONDecodeError, ValueError):
                data = {}
        data[key] = {
            "project_id": route["project_id"],
            "client": route["client"],
            "resolved_at": datetime.now(MSK).strftime("%Y-%m-%d %H:%M"),
            "note": "определено LLM - проверь и перенеси в config.json -> routing",
        }
        _write_json(self._llm_cache_file, data, indent=1)


    def _init_cursor(self):
        self._uidvalidity = None
        if os.path.exists(self._cursor_file):
            try:
                data = _load_json(self._cursor_file)
                self._uidvalidity = data.get("uidvalidity")
                return int(data.get("last_uid", 0))
            except (json.JSONDecodeError, ValueError):
                pass
        uid = self.mailer.uidnext() - 1
        self._save_cursor(uid, first=True)
        self.log.info("первый запуск: точка старта UID=%d, всё что старше - игнорируется", uid)
        return uid


    def _save_cursor(self, uid, first=False):
        payload = {"last_uid": uid}
        if self._uidvalidity:
            payload["uidvalidity"] = self._uidvalidity
        if first:
            payload["started_at"] = datetime.now(MSK).strftime("%Y-%m-%d %H:%M:%S %z")
        else:
            try:
                payload["started_at"] = _load_json(self._cursor_file).get("started_at", "")
            except Exception:
                pass
        _write_json(self._cursor_file, payload)


    def _blocked_by_dashboard(self, project_id, marker, subject, dashboard):
        blocking = set(self.dedup_cfg.get("blocking_statuses",
                                          ["В процессе: В работе", "Ожидание ответа от клиента"]))
        norm = normalize_subject(subject)
        for issue in dashboard:
            if issue["project_id"] != project_id:
                continue
            if issue["status"] not in blocking:
                continue
            if marker.dedup_by == "subject":
                hit = normalize_subject(issue["subject"]) == norm
            else:


                hit = (bool(marker.rx.search(issue["subject"]))
                       or normalize_subject(issue["subject"]) == norm)
            if hit:
                return f"#{issue['id']} '{issue['subject'][:60]}' [{issue['status']}]"
        return None


    def _get_dashboard(self, cache):
        if "dash" not in cache:
            dash = self.redmine.dashboard_issues(
                self.dedup_cfg.get("query_id", 178),
                self.dedup_cfg.get("query_project", "example-project-001"))


            new_tid = self.dedup_cfg.get("also_new_tracker_id", 65)
            if new_tid and "Новая" in self.dedup_cfg.get("blocking_statuses", []):
                try:
                    dash += self.redmine.new_issues(new_tid)
                except (urllib.error.URLError, urllib.error.HTTPError, OSError,
                        json.JSONDecodeError, http.client.HTTPException) as e:
                    self.log.warning("дозапрос 'Новая' (трекер %s) не удался (%s) - "
                                     "дедуп только по 178", new_tid, e)
            cache["dash"] = dash
            self._merge_projects(cache["dash"])
        return cache["dash"]


    def _llm_route(self, mail, token=None):

        if not self.llm_cfg.get("enabled"):
            return None, "LLM-фолбэк выключен", None
        backend = self.llm_cfg.get("backend", "cli")
        now = time.time()
        nkey = (token or "").strip(". \\").upper() or None


        neg_min = self.llm_cfg.get("neg_cache_minutes", 60)
        if neg_min and nkey:
            self._llm_neg = {k: exp for k, exp in self._llm_neg.items() if exp > now}
            exp = self._llm_neg.get(nkey)
            if exp:
                return None, "негатив-кэш: %s недавно не определился (ещё ~%d мин), модель не зову" % (
                    nkey, int((exp - now) / 60) + 1), None

        def _remember_miss():
            if neg_min and nkey:
                self._llm_neg[nkey] = now + neg_min * 60


        cap = self.llm_cfg.get("max_calls_route", 15)
        self._llm_calls_route = [t for t in self._llm_calls_route if now - t < 3600]
        if cap and len(self._llm_calls_route) >= cap:
            return None, "лимит LLM-вызовов маршрутизации в час (%d) исчерпан - пропускаю" % cap, None
        try:
            if backend == "cli":
                self._llm_calls_route.append(now)
                res = ccli.classify_server(
                    self.projects, mail.subject, mail.body,
                    model=self.llm_cfg.get("model", "sonnet"),
                    effort=self.llm_cfg.get("effort", "low"),
                    timeout=self.llm_cfg.get("cli_timeout", 25),
                    claude_bin=self.llm_cfg.get("claude_bin", "claude"))
            elif backend == "api":
                if not self.anthropic_key:
                    return None, "нет anthropic_api_key в secrets (backend=api)", None
                self._llm_calls_route.append(now)
                res = classify_server(
                    self.anthropic_key,
                    self.llm_cfg.get("api_model", "claude-haiku-4-5"),
                    self.projects, mail.subject, mail.body)
            else:
                return None, "неизвестный llm.backend=%r" % backend, None
        except Exception as e:
            return None, f"LLM ({backend}) недоступен: {e}", None
        if not res:
            _remember_miss()
            return None, "LLM не определил (или низкая уверенность)", None
        pid = res["project_id"]
        if pid not in self.projects:
            _remember_miss()
            return None, f"LLM назвал проект вне списка ({pid}) - отклонено", None
        if nkey:
            self._llm_neg.pop(nkey, None)
        server = (res.get("server") or "").strip(". \\").upper() or None
        sid = res.get("session_id")
        note = ("server=%s" % (server or "?")) + ((", session=%s" % sid) if sid else "")
        return ({"project_id": pid, "client": self.projects[pid]}, note, server)


    def _check_uidvalidity(self):


        try:
            uv = self.mailer.uidvalidity()
        except Exception:
            return
        if not uv or uv == self._uidvalidity:
            return
        if self._uidvalidity:
            self.log.error("UIDVALIDITY ящика сменился (%s -> %s) - нумерация UID новая, "
                           "переставляю точку старта на конец ящика (старые письма не трогаю)",
                           self._uidvalidity, uv)
            self.cursor = self.mailer.uidnext() - 1
        self._uidvalidity = uv
        self._save_cursor(self.cursor)


    def reload_config(self):


        path = os.path.join(self.root, "config", "config.json")
        try:
            mtime = os.stat(path).st_mtime
        except OSError:
            return False
        if mtime == getattr(self, "_cfg_mtime", None):
            return False

        self._cfg_mtime = mtime
        try:
            fresh = _load_json(path)
            if not isinstance(fresh, dict):
                raise ValueError("config.json не объект")
            _validate_config(fresh, self.log)
        except (OSError, ValueError, json.JSONDecodeError) as e:
            self.log.error("config.json изменился, но применить его нельзя (%s) - "
                           "продолжаю на прошлом конфиге", e)
            return False

        changed = sorted(k for k in set(fresh) | set(self.cfg)
                         if fresh.get(k) != self.cfg.get(k))
        if not changed:
            return False
        self.cfg.clear()
        self.cfg.update(fresh)
        self.markers = load_markers(self.cfg)
        self.pings = load_pings(self.cfg)
        self.routing = load_routing(self.cfg)
        self._merge_llm_cache_into_routing()
        self.blacklist = self.cfg.get("sender_blacklist", [])
        self.dedup_cfg = self.cfg.get("dedup", {})
        self.llm_cfg = self.cfg.get("llm", {})
        self.log.warning("config.json перечитан на ходу, изменились ключи: %s",
                         ", ".join(changed))
        tr.trace("конфиг перечитан: %s", ", ".join(changed))
        return True


    def poll(self):
        tr.status("кручусь в poll(): опрашиваю IMAP (курсор UID=%d, режим %s)",
                  self.cursor, self.mode)

        try:
            self._shift_handoff()
        except Exception:
            self.log.exception("свип начала смены упал, продолжаю обычным флоу")


        if not self.cfg.get("mail_enabled", True):
            tr.trace("poll: почта выключена (mail_enabled=false) - IMAP пропущен, только 178")
            mails = []
        else:
            self._check_uidvalidity()
            try:
                mails = self.mailer.fetch_new(
                    self.cursor,
                    body_limit=self.cfg.get("body_excerpt_chars", 4000),
                    max_bytes=self.cfg.get("max_mail_bytes", 2_000_000))
            except (imaplib.IMAP4.abort, imaplib.IMAP4.error, OSError) as e:


                self.log.warning("почта недоступна (%s) - письма этого прохода пропускаю, "
                                 "продолжаю тикет-сторону (178)", e)
                mails = []
        if mails:
            tr.trace("poll: новых писем %d (UID %d..%d)", len(mails),
                     mails[0].uid, mails[-1].uid)
        stats = {"new": len(mails), "created": 0, "dry": 0, "dup": 0, "stale": 0,
                 "unknown_srv": 0, "llm_routed": 0, "no_marker": 0, "blacklisted": 0,
                 "skipped": 0, "pinged": 0}
        cache = {}

        advanced = self.cursor
        for idx, mail in enumerate(mails):
            try:
                done = self._process(mail, stats, cache)
            except Exception:


                self.log.exception("UID %d: краш обработки, пропускаю", mail.uid)
                self.journal.record(mail.message_id, "error", subject=getattr(mail, "subject", ""),
                                    note="краш обработки письма (пропущено)")
                self._deferred_mail.pop(mail.message_id, None)
                advanced = mail.uid
                continue
            if not done:


                now = time.time()
                for m2 in mails[idx:]:
                    self._deferred_mail.setdefault(m2.message_id, now)
                self.log.warning("UID %d отложен (Redmine недоступен или лимит) - повторим "
                                 "следующим проходом (за ним в очереди ещё %d)",
                                 mail.uid, len(mails) - idx - 1)
                break
            self._deferred_mail.pop(mail.message_id, None)
            advanced = mail.uid

        if advanced > self.cursor:
            tr.trace("poll: курсор почты %d -> %d", self.cursor, advanced)
            self.cursor = advanced
            self._save_cursor(advanced)


        try:
            self._poll_178(stats)
        except Exception:
            self.log.exception("178-труба: проход упал, продолжаем")

        if stats["new"]:
            self.log.info("проход (%s): новых %d | создано %d | создал бы %d | дубль-дашборд %d | "
                          "устаревших %d | LLM-маршрут %d | неизв. сервер %d | пингов %d | "
                          "без маркера %d | redmine@ %d",
                          self.mode, stats["new"], stats["created"], stats["dry"], stats["dup"],
                          stats["stale"], stats["llm_routed"], stats["unknown_srv"],
                          stats["pinged"], stats["no_marker"], stats["blacklisted"])
        tr.status("проход завершён: писем %d (создано %d, dry %d, дублей %d), "
                  "заявок 178: default %d",
                  stats["new"], stats["created"], stats["dry"], stats["dup"],
                  stats.get("default", 0))
        return stats


    def _mail_age_minutes(self, mail, ref=None):


        if getattr(mail, "internal_ts", None):
            mdt = datetime.fromtimestamp(mail.internal_ts, timezone.utc)
        else:
            try:
                mdt = email.utils.parsedate_to_datetime(mail.date)
            except (TypeError, ValueError):
                return None
            if mdt is not None and mdt.tzinfo is None:
                mdt = mdt.replace(tzinfo=timezone.utc)
        if mdt is None:
            return None
        return ((ref or datetime.now(timezone.utc)) - mdt).total_seconds() / 60

    def _mail_ping(self, mail, stats):


        ping, count = match_ping(mail, self.pings)
        if ping is None:
            return False
        limit = self.cfg.get("max_mail_age_minutes", 60)
        age = self._mail_age_minutes(mail)
        if limit and age is not None and age > limit:
            self.journal.record(mail.message_id, "ping_stale", subject=mail.subject,
                                note="пинг «%s»: письму %d мин (лимит %d) - не шлю"
                                     % (ping.text, int(age), limit))
            stats["stale"] += 1
            self.log.info("UID %d '%.60s': пинг «%s» пропущен - письму %d мин",
                          mail.uid, mail.subject, ping.text, int(age))
            return True
        notify.emit(self, "mail_ping", None, ping.text,
                    "%s (алертов: %d)" % (clean_subject(mail.subject)[:160], count))
        self.journal.record(mail.message_id, "mail_ping", rule=ping.key, subject=mail.subject,
                            note="пинг в мессенджеры: «%s» (алертов %d, заявка не создаётся)"
                                 % (ping.text, count))
        stats["pinged"] += 1
        self.log.info("UID %d '%.60s': пинг в мессенджеры «%s» (алертов %d)",
                      mail.uid, mail.subject, ping.text, count)
        return True

    def _process(self, mail, stats, cache):

        tr.status("проверяю письмо UID %d '%.50s' (от %s)", mail.uid, mail.subject, mail.from_)
        if self.journal.seen(mail.message_id):
            stats["skipped"] += 1
            tr.trace("UID %d: уже в журнале (message_id повторился) - пропуск", mail.uid)
            self.log.debug("UID %d: message_id уже в журнале - пропуск", mail.uid)
            return True

        if sender_blacklisted(mail, self.blacklist):
            stats["blacklisted"] += 1
            tr.trace("UID %d: отправитель в чёрном списке (%s) - пропуск", mail.uid, mail.from_)

            self.journal.record(mail.message_id, "blacklisted", subject=mail.subject,
                                note="отправитель в чёрном списке: %s" % mail.from_)
            self.log.info("UID %d '%.60s': отправитель в чёрном списке (%s) - пропуск",
                          mail.uid, mail.subject, mail.from_)
            return True

        marker = match_marker(mail, self.markers)
        if marker is None:


            if self._mail_ping(mail, stats):
                return True
            stats["no_marker"] += 1
            tr.trace("UID %d: маркер не найден - не наше письмо, пропуск", mail.uid)
            self.journal.record(mail.message_id, "no_marker", subject=mail.subject,
                                note="маркер не найден - не наше письмо; from=%s" % mail.from_)
            self.log.info("UID %d '%.60s' (от %s): маркер не найден - пропуск",
                          mail.uid, mail.subject, mail.from_)
            return True
        tr.trace("UID %d: письмо попало в ветку «%s»", mail.uid, marker.key)


        if marker.key == "healthscript":

            if self.cfg.get("healthscript_cld_off"):
                cld = (self.cfg.get("healthscript_cld_sender") or "sender-014@example.invalid").lower()
                if cld and cld in (mail.from_ or "").lower():
                    stats["skipped"] += 1
                    self.journal.record(mail.message_id, "healthscript_cld_off", rule=marker.key,
                                        subject=mail.subject,
                                        note="HealthScript CLD (%s) выключен тумблером - пропуск"
                                             % mail.from_)
                    self.log.info("UID %d '%.60s' (от %s): HealthScript CLD выключен - пропуск",
                                  mail.uid, mail.subject, mail.from_)
                    return True
            ignored = {str(x) for x in self.cfg.get("healthscript_ignore_points", (11, 30))}
            pts = set(re.findall(r"<(\d+)>", mail.body or ""))
            if pts and pts <= ignored:
                stats["skipped"] += 1
                lbl = "+".join(sorted(pts, key=int))
                self.journal.record(mail.message_id, "healthscript_ignored", rule=marker.key,
                                    subject=mail.subject,
                                    note="расхождения только в игнорируемых пунктах ХС (%s) - не создаём" % lbl)
                self.log.info("UID %d '%.60s': HealthScript только п.%s - пропуск",
                              mail.uid, mail.subject, lbl)
                return True


        age_limit = self.cfg.get("max_mail_age_minutes", 60)
        if age_limit:
            ref_ts = self._deferred_mail.get(mail.message_id)
            ref = (datetime.fromtimestamp(ref_ts, timezone.utc) if ref_ts else None)
            age_min = self._mail_age_minutes(mail, ref)
            if age_min is not None:
                tr.trace("UID %d: возраст письма %.0f мин (лимит %d%s)", mail.uid, age_min,
                         age_limit, ", возраст заморожен - было отложено" if ref_ts else "")
                if age_min > age_limit:
                    self.journal.record(mail.message_id, "stale_skipped", rule=marker.key,
                                        subject=mail.subject,
                                        note=f"письму {int(age_min)} мин (лимит {age_limit})")
                    stats["stale"] += 1
                    self.log.info("UID %d '%.60s': письму %d мин (лимит %d) - устарело, пропуск",
                                  mail.uid, mail.subject, int(age_min), age_limit)
                    return True


        via_llm = ""
        token, candidate = extract_route(mail, self.routing)
        tr.trace("UID %d: маршрутизация: токен=%s, кандидат сервера=%s",
                 mail.uid, token or "не найден", candidate or "нет")
        if token is not None:
            route = self.routing[token]
            if route.get("note", "").startswith("определено LLM"):
                via_llm = " [маршрут из LLM-кэша, бесплатно]"
        else:
            tr.status("UID %d: сервер не распознан - зову LLM-фолбэк маршрутизации", mail.uid)
            route, llm_note, llm_server = self._llm_route(mail, token=candidate)
            tr.trace("UID %d: LLM-маршрутизация: %s (%s)", mail.uid,
                     "проект %s" % route["project_id"] if route else "не определил", llm_note)
            if route is None:
                self.journal.record(mail.message_id, "unknown_server", rule=marker.key,
                                    subject=mail.subject,
                                    note=f"кандидат сервера: {candidate or 'не найден'}; "
                                         f"{llm_note}; from={mail.from_}")
                stats["unknown_srv"] += 1
                self.log.warning("маркер '%s' есть, но сервер не распознан (кандидат: %s; %s)",
                                 marker.key, candidate, llm_note)
                return True

            cache_key = (candidate or llm_server or "").strip(". \\").upper()
            if cache_key and cache_key not in self.routing:
                self.routing[cache_key] = {"project_id": route["project_id"],
                                           "client": route["client"],
                                           "note": "определено LLM - проверь и перенеси в config"}
                self._cache_llm_route(cache_key, route)
                self.log.warning("LLM определил НОВЫЙ сервер: %s -> %s (проект %d). "
                                 "Закэшировано в state/llm_routes.json - проверь и перенеси "
                                 "в config.json -> routing",
                                 cache_key, route["client"], route["project_id"])
            token = cache_key or f"LLM:{'?'}"
            via_llm = f" [маршрут от LLM, {llm_note}]"
            stats["llm_routed"] += 1

        project_id = route["project_id"]


        if mail.message_id not in self._deferred_mail:
            self.journal.record(mail.message_id, "routed", rule=marker.key, subject=mail.subject,
                                project_id=project_id, interim=True,
                                note="попало в ветку «%s»; сервер %s -> проект %d (%s)%s"
                                     % (marker.key, token, project_id, route["client"], via_llm))
        subject = clean_subject(mail.subject)


        if getattr(marker, "issue_subject", None):
            label = token if (token and not str(token).startswith("LLM:")) else route.get("client", "")
            subject = clean_subject(marker.issue_subject.format(token=label, client=route.get("client", "")))


        subject = subject[:250]


        tr.status("UID %d: дедуп по дашборду 178 (проект %d, «%.40s»)",
                  mail.uid, project_id, subject)
        try:
            dashboard = self._get_dashboard(cache)
        except (urllib.error.URLError, urllib.error.HTTPError, OSError,
                json.JSONDecodeError, http.client.HTTPException) as e:
            self.log.error("Redmine недоступен/битый ответ при чтении дашборда: %s", e)
            tr.trace("UID %d: дедуп не удался (Redmine: %s) - письмо отложено", mail.uid, e)
            return False
        reason = self._blocked_by_dashboard(project_id, marker, subject, dashboard)
        tr.trace("UID %d: дедуп: %s", mail.uid,
                 ("дубль - %s" % reason) if reason else "дублей нет, можно создавать")
        if reason:
            self.journal.record(mail.message_id, "duplicate", rule=marker.key, subject=subject,
                                project_id=project_id,
                                note=f"{token} -> {route['client']}: в дашборде {reason}{via_llm}")
            stats["dup"] += 1
            self.log.info("UID %d '%.60s': дубль - в дашборде уже висит %s", mail.uid, subject, reason)
            return True

        cap_hour = self.cfg.get("max_issues_per_hour", 15)
        if self.journal.created_last_hour() >= cap_hour:
            self.log.warning("лимит заявок в час (%d) достигнут - '%s' подождёт", cap_hour, subject)
            tr.trace("UID %d: лимит заявок в час (%d) - письмо отложено", mail.uid, cap_hour)
            return False


        hs_note = None
        if marker.key == "healthscript":
            description = ""
            hs_note = DESCRIPTION_TEMPLATE.format(body=mail.body, from_=mail.from_, date=mail.date)
        elif self.cfg.get("description_mode", "empty") == "mail_body":
            description = DESCRIPTION_TEMPLATE.format(body=mail.body, from_=mail.from_, date=mail.date)
        else:
            description = ""


        client = route.get("client") or ""
        take_ok = self._auto_take_enabled(client)
        if take_ok:
            assignee_id, assignee_lbl = self._role_for_client(client)
        else:
            assignee_id = None
            assignee_lbl = "никого (%s)" % self._take_off_note(client)
        reason_cf = self.cfg.get("reason_custom_field") or {}
        custom_fields = ([{"id": int(reason_cf["id"]), "value": reason_cf.get("value", "")}]
                         if reason_cf.get("id") else None)

        if self.dry_run:
            tr.trace("UID %d: DRY-RUN - заявку НЕ создаю, только журналирую «создал бы»", mail.uid)
            self.journal.record(mail.message_id, "dry_run_create", rule=marker.key, subject=subject,
                                project_id=project_id,
                                note=f"{token} -> проект {project_id} ({route['client']}), "
                                     f"приватная, на {assignee_lbl}, причина «{reason_cf.get('value', '-')}», "
                                     f"потом в работу{via_llm}")
            stats["dry"] += 1
            self.log.info("СОЗДАЛ БЫ: '%s' | %s -> %s (проект %d)%s",
                          subject, token, route["client"], project_id, via_llm)


            notify.emit(self, "new_ticket", None, subject,
                        "почтовая труба создала бы заявку (%s)" % route["client"])

            dashboard.append({"id": 0, "project_id": project_id, "subject": subject,
                              "status": (self.dedup_cfg.get("blocking_statuses")
                                         or ["В процессе: В работе"])[0]})
            return True


        tr.status("создаю заявку «%.50s» в проекте %d (%s)", subject, project_id, route["client"])
        try:
            issue_id = self.redmine.create_issue(
                project_id, self.cfg["tracker_id"], subject, description,
                priority_id=self.cfg.get("priority_id"),
                assigned_to_id=assignee_id,
                is_private=self.cfg.get("is_private", True),
                custom_fields=custom_fields)
        except urllib.error.HTTPError as e:
            if 400 <= e.code < 500 and e.code != 429:


                self.log.error("Redmine отклонил заявку '%s' (%s) - пропускаю письмо", subject, e)
                self.journal.record(mail.message_id, "error", rule=marker.key, subject=subject,
                                    project_id=project_id,
                                    note="Redmine отклонил создание (HTTP %d), письмо пропущено" % e.code)
                return True
            self.log.error("не удалось создать заявку '%s': %s - повторим", subject, e)
            return False
        except (urllib.error.URLError, OSError, http.client.HTTPException,
                json.JSONDecodeError) as e:


            self.log.error("не удалось создать заявку '%s': %s - повторим", subject, e)
            return False

        note = ""
        work_status = self.cfg.get("work_status_id", 2)
        taken = not work_status
        if work_status and take_ok:
            try:
                self.redmine.update_status(issue_id, work_status)
                taken = True
            except (urllib.error.URLError, urllib.error.HTTPError, OSError,
                    http.client.HTTPException, json.JSONDecodeError) as e:


                note = (f"создана, но НЕ взята в работу ({e}) - переведи руками, "
                        f"иначе дедуп по дашборду её не увидит")
                self.log.warning("заявка #%d создана, но перевод в работу не удался: %s", issue_id, e)
        elif not take_ok:


            note = "взятие выключено тумблером — оставлена в «Новая», без назначенца"
            self.log.info("заявка #%d создана в «Новая»: %s", issue_id, self._take_off_note(client))


        dashboard.append({"id": issue_id, "project_id": project_id, "subject": subject,
                          "status": (self.dedup_cfg.get("blocking_statuses")
                                     or ["В процессе: В работе"])[0]})


        if hs_note:
            try:
                self.redmine.add_note(issue_id, hs_note, private=False)
                self.log.info("заявка #%d: контент HealthScript приложен комментом", issue_id)
            except Exception as e:
                self.log.warning("заявка #%d: контент HealthScript не приложился комментом (%s)",
                                 issue_id, e)

        self.journal.record(mail.message_id, "created", rule=marker.key, subject=subject,
                            issue_id=issue_id, project_id=project_id,
                            note=f"{token} -> {route['client']}.{via_llm} {note}".strip())
        if taken:
            self.journal.record(mail.message_id, "issue_taken", subject=subject,
                                issue_id=issue_id, project_id=project_id, interim=True,
                                note="заявка #%d переведена «В процессе: В работе» (на %s)"
                                     % (issue_id, assignee_lbl))
        stats["created"] += 1

        notify.emit(self, "new_ticket", issue_id, subject,
                    "почтовая труба создала заявку (%s)" % route["client"])
        self.log.info("создана заявка #%d '%s' | %s -> %s%s%s",
                      issue_id, subject, token, route["client"], via_llm,
                      f" ({note})" if note else "")
        tr.trace("UID %d: создана заявка #%d, взята в работу: %s", mail.uid, issue_id, taken)
        return True


    def _clear_alert_override(self, issue_id):


        ap = approvals.load(self.root, issue_id)
        if ap and ap.get("pipe") == "alert":
            approvals.clear(self.root, issue_id)

    def _poll_178(self, stats):


        cfg = self.cfg.get("ticket_poll", {})


        default_on = bool(self.default_cfg.get("enabled"))
        if self.ticket_cursor is None and self.gf_sets:


            self.ticket_cursor = self._init_ticket_cursor()
        alerts_on = (self.ticket_cursor is not None and cfg.get("route_alerts_from_178", True))
        if not (default_on or alerts_on):
            return
        tr.status("кручусь в _poll_178: тяну дашборд 178 (ветки: алерты=%s default=%s)",
                  alerts_on, default_on)
        trig = set(cfg.get("trigger_statuses", [1, 49, 2]))
        fresh = cfg.get("fresh_minutes", 10)
        req_tracker = cfg.get("tracker_id", 1)
        gf_tracker = self.gf_cfg.get("tracker_id", 65)
        try:
            alert_re = re.compile(cfg.get("alert_subject_re", r"\[alerting\]"), re.I)
        except re.error:
            alert_re = re.compile(r"\[alerting\]", re.I)
        alert_excl = cfg.get("alert_exclude_projects", ["Клиент A Т/П"])
        self._svc_gf = None


        self._alert_overrides = approvals.alert_overrides(self.root)


        self._approval_held = approvals.held_ids(self.root) | alert_agent.held_draft_ids(self.root)
        now_ts = time.time()


        self._deferred_178 = {k: v for k, v in self._deferred_178.items() if now_ts - v < 86400}


        try:
            raw = self.redmine.paged("/issues.json", {
                "query_id": cfg.get("query_id", 178),
                "project_id": cfg.get("query_project", "example-project-001")}, max_pages=5)
        except Exception as e:
            self.log.warning("178: не забрал дашборд (%s) - пропускаю проход", e)
            tr.trace("178: дашборд не забрался (%s) - проход пропущен", e)
            return


        issues, seen_ids = [], set()
        for it in raw:
            if it.get("id") not in seen_ids:
                seen_ids.add(it.get("id"))
                issues.append(it)
        tr.trace("178: в дашборде %d заявок", len(issues))


        try:
            for it in notify.poll178_new_info(self._poll178_status_file, issues):
                notify.emit(self, "new_info", it.get("id"),
                            (it.get("subject") or ""),
                            "заявка перешла в статус «Новая информация»")
        except Exception:
            self.log.exception("178: дифф new_info упал, продолжаю")


        ctx = router.Ctx(
            root=self.root,
            alert_overrides=self._alert_overrides, approval_held=self._approval_held,
            trig=trig, fresh=fresh, alert_re=alert_re,
            req_tracker=req_tracker, gf_tracker=gf_tracker, alert_excl=alert_excl,
            alerts_on=alerts_on, default_on=default_on,
            deferred_178=self._deferred_178, ticket_created=self._ticket_created)


        if alerts_on:
            try:
                self._maybe_handle_storm(
                    [self._issue_to_ticket(i) for i in issues if router.is_alert(i, ctx)], stats)
            except Exception:
                self.log.exception("178: детект шторма упал, продолжаю поштучно")

        for i in issues:


            oap = approvals.load(self.root, i["id"])
            decision = router.classify_ticket(i, ctx, oap)
            branch = decision.branch


            if branch == "opus":
                try:
                    self._handle_opus_request(i, oap, stats)
                    self._deferred_178.pop(i["id"], None)
                except _TicketDefer as d:
                    self._deferred_178.setdefault(i["id"], time.time())
                    (self.log.debug if d.quiet else self.log.warning)(
                        "opus #%d отложен (%s)", i["id"], d.err)
                except Exception:
                    self.log.exception("opus #%d: краш, пропускаю", i["id"])
                    self.journal.record("opus-%d" % i["id"], "error", subject=i.get("subject", ""),
                                        issue_id=i["id"], note="краш обработки opus-запроса")
                    approvals.clear(self.root, i["id"])
                continue


            if branch == "alert":
                key = decision.key
                manual_alert = decision.force
                if not manual_alert and self.journal.seen(key):
                    continue
                tr.status("проверяю заявку #%d на ветку «алерт Grafana»%s ('%.40s')",
                          i["id"], " [ручной дисптач]" if manual_alert else "", i.get("subject", ""))
                try:

                    self._process_ticket(self._issue_to_ticket(i), key, stats, force=manual_alert)
                    self._deferred_178.pop(i["id"], None)
                    if manual_alert:
                        self._clear_alert_override(i["id"])
                except _TicketDefer as d:
                    self._deferred_178.setdefault(i["id"], time.time())


                    (self.log.debug if d.quiet else self.log.warning)(
                        "178/алерт #%d отложен (%s) - повторим", i["id"], d.err)
                    continue
                except Exception:
                    self.log.exception("178/алерт #%d: краш, пропускаю", i["id"])
                    self.journal.record(key, "error", subject=i.get("subject", ""),
                                        issue_id=i["id"], note="краш обработки алерта из 178")
                    if manual_alert:
                        self._clear_alert_override(i["id"])
                continue

            if branch == "skip":
                continue


            subj = i.get("subject", "")
            key = decision.key
            if self.journal.seen(key):
                continue
            tr.status("проверяю заявку #%d на ветку «default» (незнакомая -> Opus)", i["id"])
            try:
                self._process_default(i, key, stats)
                self._deferred_178.pop(i["id"], None)
            except _TicketDefer as d:
                self._deferred_178.setdefault(i["id"], time.time())


                (self.log.debug if d.quiet else self.log.warning)(
                    "default #%d отложена (%s) - повторим проходом", i["id"], d.err)
            except Exception:
                self.log.exception("default #%d: краш обработки, пропускаю", i["id"])
                self.journal.record(key, "error", subject=subj, issue_id=i["id"],
                                    note="краш обработки default (пропущено)")


    def close(self):
        self.mailer.close()
