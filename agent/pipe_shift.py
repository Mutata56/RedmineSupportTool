# -*- coding: utf-8 -*-


from .agent_base import _load_json, _write_json, tr, RoleMixin


class ShiftMixin(RoleMixin):

    def _load_handoff_stamp(self):

        try:
            return _load_json(self._handoff_stamp_file) or {}
        except (OSError, ValueError):
            return {}

    def _warn_roles_unset(self, now, chief_id, engineer_id):


        today = now.date().isoformat()
        if getattr(self, "_roles_unset_warned", None) == today:
            return
        self._roles_unset_warned = today
        empty = ", ".join(r for r, v in (("@chiefEngineer", chief_id),
                                         ("@engineer", engineer_id)) if not v)
        self.log.warning("свип начала смены: в настройках не задано %s - свип пропущен "
                         "(настройки агента -> Роли)", empty)

    def _warn_handoff_window_missed(self, now, sched):


        today = now.date().isoformat()
        if getattr(self, "_handoff_late_warned", None) == today:
            return
        self._handoff_late_warned = today
        self.log.warning("свип начала смены: окно %s ±%d мин закрыто, сегодня (%s) свипа не "
                         "будет - агента надо поднимать к началу смены",
                         sched.shift_start.strftime("%H:%M"), sched.window_minutes, today)

    def _shift_handoff(self):


        cfg = self.shift_cfg
        if not cfg.get("enabled") or self.schedule is None:
            return
        sched = self.schedule
        now = sched.now()
        mode = "dry" if self.dry_run else "live"
        stamp = self._load_handoff_stamp()


        by_mode = stamp.get("by_mode") if isinstance(stamp.get("by_mode"), dict) else {}
        last_done = by_mode.get(mode) or (stamp.get("date")
                                          if stamp.get("mode") == mode else None)
        state = sched.handoff_state(now, last_done)
        if state != "go":
            if state == "late":
                self._warn_handoff_window_missed(now, sched)
            return


        chief_id, engineer_id, id2name = self._role_ids()
        if not chief_id or not engineer_id:
            self._warn_roles_unset(now, chief_id, engineer_id)
            return
        chief_lbl = self._role_label("chiefEngineer", chief_id, id2name)
        eng_lbl = self._role_label("engineer", engineer_id, id2name)


        second_line = set(cfg.get("second_line_ids") or []) | set(cfg.get("protect_ids") or [])


        _dba = (self.cfg.get("locks") or {}).get("dba_group_id")
        if _dba:
            second_line.add(int(_dba))
        client_a = [str(m).lower() for m in (cfg.get("client_a_clients") or ["Клиент A"])]
        in_work = cfg.get("in_work_status", "В процессе: В работе")
        query_id = cfg.get("query_id", 178)

        tr.status("свип начала смены: тяну дашборд %d (Клиент A -> %s, остальные -> %s)",
                  query_id, chief_lbl, eng_lbl)
        try:
            issues = self.redmine.query_issues(query_id, project=cfg.get("query_project"),
                                               max_pages=int(cfg.get("max_pages", 10)))
        except Exception as e:

            self.log.warning("свип начала смены: дашборд %d не забрался (%s) - повторю", query_id, e)
            return

        moved = skipped = second = 0
        for it in issues:
            if it.get("status") != in_work:
                continue
            aid = it.get("assignee_id")
            aname = it.get("assignee_name") or ""


            if aid is not None and aid in second_line:
                second += 1
                continue


            pname = (it.get("project_name") or "").lower()
            is_client_a = any(pname.startswith(m) for m in client_a)
            target = chief_id if is_client_a else engineer_id
            if aid == target:
                skipped += 1
                continue
            key = "handoff-%d" % it["id"]
            tgt_lbl = chief_lbl if is_client_a else eng_lbl
            if self.dry_run:
                self.journal.record(key, "handoff_dry_run", subject=it.get("subject", ""),
                                    issue_id=it["id"],
                                    note="переназначил бы #%d (%s, «%s») -> %s"
                                         % (it["id"], it.get("project_name", ""),
                                            (it.get("subject") or "")[:40], tgt_lbl))
                moved += 1
                continue
            try:
                self.redmine.reassign(it["id"], target)
                self.journal.record(key, "handoff_reassigned", subject=it.get("subject", ""),
                                    issue_id=it["id"],
                                    note="начало смены: переназначена на %s (было: %s)"
                                         % (tgt_lbl, aname or "никого"))
                moved += 1
            except Exception as e:
                self.log.warning("свип: #%d не переназначилась (%s) - пропускаю", it["id"], e)


        by_mode = dict(by_mode)
        by_mode[mode] = now.date().isoformat()
        _write_json(self._handoff_stamp_file,
                    {"date": now.date().isoformat(), "mode": mode, "by_mode": by_mode,
                     "at": now.strftime("%Y-%m-%d %H:%M:%S"),
                     "moved": moved, "chief": chief_lbl, "engineer": eng_lbl})
        self.log.info("свип начала смены (%s): переназначено %d, уже верных %d, 2-я линия %d "
                      "(из %d в работе)%s", now.date().isoformat(), moved, skipped, second,
                      len(issues), " [DRY]" if self.dry_run else "")
