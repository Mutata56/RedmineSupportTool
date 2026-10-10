/* Alpine-компонент dashboard. Данные - REST /api/*, live - WebSocket /ws/events. */
"use strict";

/* Карта вердикт -> [css-класс, русская подпись] (перенесена из tools/control_center.py). */
const V = {
    routed: ["step", "распознано и замаршрутизировано"],
    created: ["ok", "создана заявка"], dry_run_create: ["dry", "создал бы заявку (dry-run)"],
    issue_taken: ["ok", "взята в работу"], taken_in_work: ["ok", "взята в работу"],
    note_posted: ["ok", "написан приватный комментарий"],
    duplicate: ["skip", "дубль: уже есть в дашборде"], stale_skipped: ["skip", "устарело - не берём"],
    no_marker: ["mute", "нет маркера - не наше письмо"], blacklisted: ["mute", "чёрный список"],
    healthscript_p11_only: ["skip", "HealthScript: только п.11 — не создаём"],
    healthscript_ignored: ["skip", "HealthScript: только игнорируемые пункты (11/30) — не создаём"],
    unknown_server: ["warn", "сервер не распознан"], error: ["err", "ошибка обработки"],
    grafana_attached: ["ok", "приложены графики"], grafana_dry_run: ["dry", "взял бы (dry-run)"],
    grafana_error: ["warn", "в работе, графики не приложились"],
    ticket_taken: ["ok", "взята в работу (без графиков)"], ticket_no_match: ["mute", "не наш алерт"],
    ticket_stale: ["skip", "старый алерт - не берём"], ticket_status_skip: ["skip", "статус не берём"],
    ticket_no_date: ["skip", "дата не распозналась"],
    storm_grouped: ["warn", "шторм: взята и связана"], storm_dry_run: ["dry", "шторм (dry-run)"],
    llm_analysis: ["ai", "написан разбор Sonnet"],
    llm_low_confidence: ["veto", "ИИ не уверен - в Redmine не писали"],
    default_dispatched: ["ai", "Opus-анализ запущен"], default_done: ["ai", "Opus-анализ готов"],
    default_low_confidence: ["veto", "Opus не уверен - коммент не публиковался"],
    default_error: ["err", "Opus-анализ упал"], default_dry: ["dry", "default (dry-run)"],
    approval_requested: ["warn", "ждёт твоего решения"],
    // ── схема одобрений (Opus-эскалация + игнор) ──
    approved: ["ok", "запись одобрена"],
    opus_requested: ["ai", "запрос на запуск Opus"],
    opus_launched: ["ai", "Opus запущен"],
    opus_launched_dry: ["dry", "одобрено, DRY - Opus не запускался"],
    opus_declined: ["mute", "Opus не запускать"],
    opus_draft_ready: ["ai", "черновик Opus готов - одобрить публикацию"],
    opus_post_declined: ["mute", "публикация черновика отклонена"],
    approval_review: ["warn", "запущен ИИ-ревью"],
    ignored: ["mute", "игнор - помечено обработанным"],
    manual_decision: ["mute", "решение: вручную, ничего не делаем"]
};

function vinfo(v) { return V[v] || ["mute", v || "—"]; }

/* Model/effort, доступные per-заявка для запертого Opus-анализа (agent/default_flow.py).
   Значения model — то, что понимает claude -p --model; effort — --effort. */
const OPUS_MODELS = [
    { v: "claude-opus-4-8", t: "Opus 4.8" },
    { v: "sonnet",          t: "Sonnet" },
    { v: "claude-haiku-4-5", t: "Haiku" },
];
const OPUS_EFFORTS = ["low", "medium", "high", "xhigh", "max"];
const DEF_MODEL = "claude-opus-4-8";
const DEF_EFFORT = "high";

function dash() {
    return {
        /* ── справочники для шаблонов ── */
        OPUS_MODELS, OPUS_EFFORTS, DEF_MODEL, DEF_EFFORT,

        /* ── состояние ── */
        tab: "dashboard",
        wsOk: false,
        redmineUrl: "",
        agent: { state: "stopped", dry_run: true, status_line: null, uptime_seconds: null,
                 started_at: null, pid: null },
        uptimeText: "—",
        _uptimeBase: null, _uptimeAt: null,
        stats: { mails_24h: 0, tickets_24h: 0, pending: 0, created_24h: 0, errors_24h: 0, ai_calls_24h: 0 },
        busyAgent: false,

        // центр управления
        dlogs: [], dtermAuto: true, _dlogsSeeded: false,
        pick: {},                          // issue_id -> {model, effort} (выбор per-заявка в стеке)
        _appById: {},                      // issue_id -> pending-approval (для стека)

        mails: [], mailQ: "", mailVerdict: "", mailPeriod: "", mailOpen: null,
        tickets: [], tQ: "", tVerdict: "", tPeriod: "",
        ticket: null, ticketLogs: { logs: [], trace: [] }, ticketLogTab: "logs", ticketLogsOpen: false,
        approvals: [], pendingCount: 0,
        opus: { issue_id: null, subject: "", prompt: "", busy: false, model: DEF_MODEL, effort: DEF_EFFORT },
        chat: { messages: [], sessionId: null, busy: false, input: "" },
        logs: { entries: [], src: "logs", level: "", logger: "", q: "", auto: true, n: 400 },
        toast: null,

        /* ── init ── */
        init() {
            const h = location.hash.slice(1);
            const deep = h.match(/^tickets\/(\d+)$/);
            this.go(deep ? "tickets"
                : ["dashboard", "mails", "tickets", "approvals", "chat", "logs"].includes(h) ? h : "dashboard", false);
            if (deep) this.openTicket(+deep[1]);
            window.addEventListener("hashchange", () => {
                const h = location.hash.slice(1);
                const deep = h.match(/^tickets\/(\d+)$/);   // Back/Forward на URL заявки #tickets/5
                if (deep) {
                    const id = +deep[1];
                    if (this.tab !== "tickets" || !this.ticket || this.ticket.issue_id !== id) {
                        this.go("tickets", false);
                        this.openTicket(id);
                    }
                    return;
                }
                // неизвестный хэш -> дашборд (иначе tab='tickets/5' не совпал бы ни с одной секцией)
                const t = ["dashboard", "mails", "tickets", "approvals", "chat", "logs"].includes(h)
                    ? h : "dashboard";
                if (t !== this.tab) this.go(t, false);
            });
            startWS(this);
            setInterval(() => this.tickUptime(), 1000);
            setInterval(() => { if (this.tab === "dashboard") this.loadDashboard(); }, 15000);
        },

        go(tab, push = true) {
            this.tab = tab;
            if (push) location.hash = tab;
            else if (location.hash.slice(1) !== tab) history.replaceState(null, "", "#" + tab);
            if (tab === "dashboard") { this.loadDashboard(); this.$nextTick(() => this.scrollDterm(true)); }
            if (tab === "mails") this.loadMails();
            if (tab === "tickets") { this.ticket = null; this.loadTickets(); }
            if (tab === "approvals") this.loadApprovals();
            if (tab === "logs") this.loadLogs();
            this.$nextTick(() => { if (window.lucide) lucide.createIcons(); });
        },

        /* ── helpers ── */
        vcls(v) { return "vbadge v-" + vinfo(v)[0]; },
        vlbl(v) { return vinfo(v)[1]; },
        issueUrl(id) { return this.redmineUrl && id ? this.redmineUrl + "/issues/" + id : null; },
        notice(text, ok = true) {
            this.toast = { text, ok };
            clearTimeout(this._toastT);
            this._toastT = setTimeout(() => { this.toast = null; }, 4000);
        },
        async getJSON(url) {
            const r = await fetch(url);
            if (!r.ok) throw new Error("HTTP " + r.status);
            return r.json();
        },
        async postJSON(url, body) {
            const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" },
                                         body: body === undefined ? null : JSON.stringify(body) });
            let d = null;
            try { d = await r.json(); } catch (e) { /* пустое/не-JSON тело */ }
            // не-2xx без нашего {ok}: 422 Pydantic отдаёт {detail:[{msg,loc}]}, иначе {detail} —
            // приводим к {ok:false,error}, иначе вызывающие показывали бы «не получилось: undefined»
            if (!r.ok && (!d || d.ok === undefined)) {
                let err = "HTTP " + r.status;
                if (d && Array.isArray(d.detail) && d.detail[0]) {
                    err = d.detail[0].msg + " (" + (d.detail[0].loc || []).join(".") + ")";
                } else if (d && typeof d.detail === "string") err = d.detail;
                else if (d && d.error) err = d.error;
                else if (d && d.message) err = d.message;
                return { ok: false, error: err };
            }
            return d || { ok: r.ok };
        },
        copy(text, what) {
            const done = () => this.notice((what || "скопировано") + " — в буфере");
            if (navigator.clipboard && navigator.clipboard.writeText) {
                navigator.clipboard.writeText(text).then(done).catch(() => this.copyFallback(text, done));
            } else this.copyFallback(text, done);
        },
        copyFallback(text, done) {
            const ta = document.createElement("textarea");
            ta.value = text; document.body.appendChild(ta); ta.select();
            try { document.execCommand("copy"); done(); } catch (e) { this.notice("не скопировалось", false); }
            ta.remove();
        },

        /* ── статус агента / uptime ── */
        heroState() {
            return this.agent.state === "running" ? "running"
                 : this.agent.state === "dry-run" ? "dry" : "stopped";
        },
        agentDotCls() {
            return this.agent.state === "running" ? "status-dot active"
                 : this.agent.state === "dry-run" ? "status-dot dry" : "status-dot error";
        },
        agentLabel() {
            return this.agent.state === "running" ? "Running"
                 : this.agent.state === "dry-run" ? "Dry-run" : "Stopped";
        },
        tickUptime() {
            if (this._uptimeBase == null || this.agent.state === "stopped") { this.uptimeText = "—"; return; }
            let s = this._uptimeBase + Math.round((Date.now() - this._uptimeAt) / 1000);
            const d = Math.floor(s / 86400); s %= 86400;
            const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), sec = s % 60;
            this.uptimeText = (d ? d + "д " : "") + (d || h ? h + "ч " : "") + m + "м " + sec + "с";
        },
        setUptime(seconds) {
            this._uptimeBase = (seconds == null ? null : seconds);
            this._uptimeAt = Date.now();
            this.tickUptime();
        },

        async agentAction(action) {
            // режим берём из config (agent.dry_run) - GUI поднимает агента в уже настроенном режиме
            const mode = this.agent.dry_run ? "DRY-RUN" : "БОЕВОЙ (LIVE — реально пишет в Redmine!)";
            const label = { start: "Включить агента в режиме " + mode + "?",
                            stop: "Выключить агента (SIGTERM по pid из status.json)?",
                            restart: "Перезапустить агента? Поднимется в режиме " + mode + "." }[action];
            if (!confirm(label)) return;
            this.busyAgent = true;
            try {
                const r = await this.postJSON("/api/agent/" + action);
                this.notice(r.message || (r.ok ? "готово" : "не получилось"), r.ok);
            } catch (e) { this.notice("ошибка запроса: " + e, false); }
            this.busyAgent = false;
            setTimeout(() => this.loadDashboard(), 1200);
        },

        async setMode(dry) {
            // переключение режима: dry -> безопасно; боевой -> двойное подтверждение (реальная запись)
            const q = dry
                ? "Вернуть агента в DRY-RUN? Если он работает — перезапущу его в dry-run (перестанет писать в Redmine)."
                : "⚠ ВКЛЮЧИТЬ БОЕВОЙ РЕЖИМ?\nАгент начнёт РЕАЛЬНО создавать заявки и писать в Redmine/БД.\nЕсли работает — перезапущу его боевым.";
            if (!confirm(q)) return;
            if (!dry && !confirm("Точно БОЕВОЙ режим? Это реально пишет в прод. Подтверди ещё раз.")) return;
            this.busyAgent = true;
            try {
                const r = await this.postJSON("/api/agent/mode", { dry_run: dry });
                this.notice(r.message || (r.ok ? "готово" : "не получилось"), r.ok);
            } catch (e) { this.notice("ошибка запроса: " + e, false); }
            this.busyAgent = false;
            setTimeout(() => this.loadDashboard(), 1500);
        },

        /* ── центр управления ── */
        async loadDashboard() {
            try {
                const d = await this.getJSON("/api/dashboard");
                this.applyAgent(d.agent);
                this.stats = d.stats;
                this.pendingCount = d.stats.pending;
                this.redmineUrl = d.redmine_url;
            } catch (e) { /* сервер перезапускается - переживём */ }
            this.loadStack();
            this.seedDlogs();
        },
        applyAgent(a) {
            this.agent = a;
            this.setUptime(a.uptime_seconds);
        },

        // грузим сущности стека без фильтров вкладок (свежие письма + заявки + очередь решений)
        async loadStack() {
            try {
                const [em, tk] = await Promise.all([
                    this.getJSON("/api/emails?limit=120"),
                    this.getJSON("/api/tickets?limit=120"),
                ]);
                this.mails = em.items || [];
                this.tickets = tk.items || [];
                this.redmineUrl = tk.redmine_url || em.redmine_url || this.redmineUrl;
            } catch (e) { /* noop */ }
            this.loadApprovals();
        },

        // приоритетный уровень карточки: attention (ждёт решения) -> error -> progress -> ai -> done (низ)
        tierOf(verdict, awaiting) {
            if (awaiting) return "attention";                          // ждёт МОЕГО решения — верх
            const c = vinfo(verdict)[0];
            if (c === "err") return "error";
            if (c === "warn" || c === "dry" || c === "veto") return "progress";
            if (c === "ai" || c === "step") return "ai";
            if (c === "ok") return "ok";                               // осмысленный результат (создано/в работе)
            return "noise";   // skip/mute (нет маркера / не наш алерт / чёрный список) — в самый низ
        },
        mailDot(v) {
            const c = vinfo(v)[0];
            if (c === "err") return "status-dot error";
            if (c === "warn" || c === "dry" || c === "veto") return "status-dot pending";
            if (c === "ai") return "status-dot ai";
            if (c === "skip" || c === "mute") return "status-dot idle";
            return "status-dot active";
        },
        get workStack() {
            const items = [];
            const rank = { attention: 0, error: 1, progress: 2, ai: 3, ok: 4, noise: 5 };
            for (const t of this.tickets) {
                const ap = this._appById[t.issue_id];
                const opusAp = ap && ap.pipe === "opus" ? ap : null;
                items.push({
                    uid: "t-" + t.key, kind: "ticket", issue_id: t.issue_id,
                    subject: t.subject, note: t.note, verdict: t.verdict,
                    at: t.last_at, ts: t.last_ts, awaiting: !!t.awaiting_decision,
                    opus: opusAp, opusPending: !!opusAp, otherPending: !!(ap && ap.pipe !== "opus"),
                    dot: this.tDot(t), tier: this.tierOf(t.verdict, t.awaiting_decision),
                });
            }
            for (const m of this.mails) {
                items.push({
                    uid: "m-" + m.key, kind: "mail", issue_id: m.issue_id || null,
                    subject: m.subject, note: m.note, verdict: m.verdict,
                    at: m.last_at, ts: m.last_ts, awaiting: false,
                    opus: null, opusPending: false, otherPending: false,
                    dot: this.mailDot(m.verdict), tier: this.tierOf(m.verdict, false),
                });
            }
            items.sort((a, b) => (rank[a.tier] - rank[b.tier]) || (b.ts - a.ts));
            return items;
        },
        stackOpen(w) {
            if (w.kind === "ticket" && w.issue_id) { this.go("tickets"); this.openTicket(w.issue_id); }
            else if (w.kind === "mail") { this.mailQ = w.subject || ""; this.go("mails"); }
        },

        // per-заявка выбор model/effort (дефолт: из pending-opus запроса, иначе Opus 4.8 / high)
        pmodel(w) { return (this.pick[w.issue_id] && this.pick[w.issue_id].model)
                        || (w.opus && w.opus.model) || DEF_MODEL; },
        peffort(w) { return (this.pick[w.issue_id] && this.pick[w.issue_id].effort)
                        || (w.opus && w.opus.effort) || DEF_EFFORT; },
        setPick(id, k, v) {
            const cur = this.pick[id] ? Object.assign({}, this.pick[id]) : {};
            cur[k] = v;
            this.pick = Object.assign({}, this.pick, { [id]: cur });
        },
        async quickOpus(w) {
            const mdl = this.pmodel(w), eff = this.peffort(w);
            if (!confirm("Запустить Opus по заявке #" + w.issue_id + "?\nmodel=" + mdl + ", effort=" + eff)) return;
            try {
                const r = await this.postJSON("/api/tickets/" + w.issue_id + "/invoke_opus",
                    { prompt: "", subject: w.subject || "", model: mdl, effort: eff });
                if (r.ok) { this.notice("Opus по #" + w.issue_id + " запущен (" + mdl + " / " + eff + ")"); this.loadStack(); }
                else this.notice("не получилось: " + r.error, false);
            } catch (e) { this.notice("ошибка запроса: " + e, false); }
        },
        async decideOpus(w, decision) {
            const mdl = this.pmodel(w), eff = this.peffort(w);
            const q = decision === "approved"
                ? "Запустить Opus по заявке #" + w.issue_id + "?\nmodel=" + mdl + ", effort=" + eff
                : "Игнорировать заявку #" + w.issue_id + "? Она будет помечена обработанной.";
            if (!confirm(q)) return;
            try {
                const r = await this.postJSON("/api/approvals/" + w.issue_id,
                    { decision, model: mdl, effort: eff });
                if (!r.ok) return this.notice("не получилось: " + r.error, false);
                this.notice("решение по #" + w.issue_id + " записано");
                this.loadStack();
            } catch (e) { this.notice("ошибка запроса: " + e, false); }
        },

        /* ── живой лог-поток (терминал на дашборде) ── */
        async seedDlogs() {
            if (this._dlogsSeeded) return;
            this._dlogsSeeded = true;
            try {
                const rows = await this.getJSON("/api/logs?src=logs&n=120");
                // не затираем строки, прилетевшие по WS во время фетча (WS стартует в init раньше):
                // историю кладём ПЕРЕД уже накопленными live-строками
                this.dlogs = rows.concat(this.dlogs);
                if (this.dlogs.length > 500) this.dlogs.splice(0, this.dlogs.length - 500);
                this.scrollDterm(true);
            } catch (e) { this._dlogsSeeded = false; }
        },
        pushDlog(rec) {
            this.dlogs.push(rec);
            if (this.dlogs.length > 500) this.dlogs.splice(0, this.dlogs.length - 500);
            this.scrollDterm();
        },
        scrollDterm(force) {
            this.$nextTick(() => {
                const el = this.$refs.dterm;
                if (el && (this.dtermAuto || force)) el.scrollTop = el.scrollHeight;
            });
        },
        onDtermScroll() {
            const el = this.$refs.dterm;
            if (!el) return;
            this.dtermAuto = el.scrollHeight - el.scrollTop - el.clientHeight < 60;
        },

        /* ── письма ── */
        async loadMails() {
            try {
                const p = new URLSearchParams({ q: this.mailQ, period: this.mailPeriod });
                const d = await this.getJSON("/api/emails?" + p);
                this.redmineUrl = d.redmine_url || this.redmineUrl;
                this.mails = d.items;
            } catch (e) { /* noop */ }
        },
        get mailsShown() {
            return this.mailVerdict ? this.mails.filter(m => m.verdict === this.mailVerdict) : this.mails;
        },
        get mailVerdicts() {
            return [...new Set(this.mails.map(m => m.verdict))].sort();
        },

        /* ── заявки ── */
        async loadTickets() {
            try {
                const p = new URLSearchParams({ q: this.tQ, period: this.tPeriod });
                const d = await this.getJSON("/api/tickets?" + p);
                this.redmineUrl = d.redmine_url || this.redmineUrl;
                this.tickets = d.items;
            } catch (e) { /* noop */ }
        },
        get ticketsShown() {
            return this.tVerdict ? this.tickets.filter(t => t.verdict === this.tVerdict) : this.tickets;
        },
        get ticketVerdicts() {
            return [...new Set(this.tickets.map(t => t.verdict))].sort();
        },
        tDot(t) {   // 🔴 ждёт решения / 🟡 в обработке / 🔴 ошибка / 🟢 завершено
            if (t.awaiting_decision) return "status-dot error";
            const c = vinfo(t.verdict)[0];
            if (c === "err") return "status-dot error";
            if (c === "warn" || c === "dry") return "status-dot pending";
            if (c === "skip" || c === "mute") return "status-dot idle";
            return "status-dot active";
        },
        async openTicket(id) {
            try {
                this.ticket = await this.getJSON("/api/tickets/" + id);
                history.replaceState(null, "", "#tickets/" + id);
                this.ticketLogs = { logs: [], trace: [] };
                this.ticketLogTab = "logs";
                this.ticketLogsOpen = false;
                this.getJSON("/api/tickets/" + id + "/logs").then(d => { this.ticketLogs = d; });
                this.$nextTick(() => { if (window.lucide) lucide.createIcons(); });
            } catch (e) { this.notice("заявка #" + id + " в журнале не найдена", false); }
        },
        resumeCmd(sid) { return "claude --resume " + sid; },

        /* ── одобрения ── */
        async loadApprovals() {
            try {
                const d = await this.getJSON("/api/approvals");
                // подстраховка: показываем только pending (build_feed уже фильтрует, но мало ли)
                this.approvals = (d.items || []).filter(a => (a.status || "pending") === "pending");
                this.pendingCount = this.approvals.length;
                const by = {};
                for (const a of this.approvals) if (a.issue_id != null) by[a.issue_id] = a;
                this._appById = by;
                this.redmineUrl = d.redmine_url || this.redmineUrl;
                this.$nextTick(() => { if (window.lucide) lucide.createIcons(); });
            } catch (e) { /* noop */ }
        },
        pipeLabel(p) { return p === "opus" ? "opus" : p === "alert" ? "алерт" : (p || "заявка"); },

        /* тип запроса: reviewing (идёт ИИ-ревью, решать нечего) · post (публикация черновика
           Opus) · branch|write (Клиент C) · opus (эскалация) · legacy. stage главнее pipe. */
        appKind(a) {
            if (!a) return "legacy";
            if (a.stage === "reviewing") return "reviewing";
            if (a.stage === "post") return "post";
            if (a.pipe === "opus") return "opus";
            if (a.stage === "write") return "write";
            if (a.stage === "branch") return "branch";
            return "legacy";
        },
        appTitle(a) {
            const k = this.appKind(a);
            if (k === "reviewing") return "⏳ Идёт ИИ-ревью — решение запросят после него";
            if (k === "post") return "Опубликовать разбор Opus в заявку?";
            if (k === "branch") return "Этап 1 — подтверди ветку";
            if (k === "write") return "Этап 2 — разрешить запись в БД";
            if (k === "opus") return ({
                default: "Незнакомая заявка — запустить Opus?",
                alert: "Разбор алерта неуверенный — запустить Opus?",
                alert_analysis: "Алерт: приложи результаты SQL → анализ Opus 4.8",
                manual: "Ручной запуск Opus"
            })[a.reason] || "Запустить Opus?";
            return "Запрос одобрения";
        },
        appTitleCls(a) {
            const k = this.appKind(a);
            if (k === "reviewing") return "text-slate-400";
            if (k === "post") return "text-purple-400";
            return k === "write" ? "text-red-400" : k === "opus" ? "text-purple-400" : "text-yellow-500";
        },
        appCardCls(a) {
            const k = this.appKind(a);
            if (k === "reviewing") return "!border-slate-700";
            if (k === "post") return "!border-purple-700";
            return k === "write" ? "!border-red-700" : k === "opus" ? "!border-purple-700" : "!border-yellow-700";
        },
        appBadgeV(a) {
            const k = this.appKind(a);
            if (k === "reviewing") return "approval_review";
            if (k === "post") return "opus_draft_ready";
            return k === "branch" ? "approval_branch" : k === "write" ? "approval_write"
                 : k === "opus" ? "opus_requested" : "approval_requested";
        },
        appProposalLabel(a) {
            const k = this.appKind(a);
            if (k === "reviewing") return "Предложенное решение (ИИ проверяет)";
            if (k === "post") return "Черновик приватного комментария";
            if (k === "write") return "Что вернули SELECT'ы + предлагаемая запись";
            if (k === "opus") return "Заявка";
            if (k === "branch") return "Что распознала ветка (предпросмотр)";
            return "Что будет выполнено";
        },
        async decide(iid, decision, confirmMsg, model, effort) {
            const q = confirmMsg || ({
                approved: "Одобрить действие по заявке #" + iid + "?",
                manual: "Решение «вручную»: агент по заявке #" + iid + " ничего делать не будет. Подтвердить?",
                ignore: "Игнорировать заявку #" + iid + "? Она будет помечена обработанной, ничего не выполняем."
            })[decision];
            if (q && !confirm(q)) return;
            try {
                const r = await this.postJSON("/api/approvals/" + iid,
                    { decision, model: model || undefined, effort: effort || undefined });
                if (!r.ok) return this.notice("не получилось: " + r.error, false);
                this.notice("решение по #" + iid + " записано");
            } catch (e) { this.notice("ошибка запроса: " + e, false); }
            this.loadApprovals();
            if (this.tab === "dashboard") this.loadStack();
            if (this.ticket && this.ticket.issue_id === iid) this.openTicket(iid);
        },

        /* ── ручной вызов Opus по заявке (режим «диктую задачу») ── */
        openOpus(id, subject) {
            if (this.opus.issue_id === id) { this.opus.issue_id = null; return; }   // повторный клик — закрыть
            this.opus = { issue_id: id, subject: subject || "", prompt: "", busy: false,
                          model: DEF_MODEL, effort: DEF_EFFORT };
        },
        async sendOpus() {
            const id = this.opus.issue_id;
            if (!id || this.opus.busy) return;
            const has = this.opus.prompt.trim();
            if (!confirm("Вызвать Opus по заявке #" + id + (has ? " с вашей инструкцией" : " (Opus сам подберёт похожие)")
                         + "?\nmodel=" + this.opus.model + ", effort=" + this.opus.effort)) return;
            this.opus.busy = true;
            try {
                const r = await this.postJSON("/api/tickets/" + id + "/invoke_opus",
                    { prompt: this.opus.prompt, subject: this.opus.subject,
                      model: this.opus.model, effort: this.opus.effort });
                if (r.ok) { this.notice("запрос на Opus по #" + id + " создан"); this.opus.issue_id = null; this.loadApprovals(); }
                else this.notice("не получилось: " + r.error, false);
            } catch (e) { this.notice("ошибка запроса: " + e, false); }
            this.opus.busy = false;
        },

        /* ── чат ── */
        async chatSend() {
            const text = this.chat.input.trim();
            if (!text || this.chat.busy) return;
            this.chat.input = "";
            this.chat.messages.push({ role: "user", text, at: new Date().toLocaleTimeString() });
            this.chat.busy = true;
            this.scrollChat();
            try {
                const r = await this.postJSON("/api/claude/chat",
                    { message: text, session_id: this.chat.sessionId });
                if (r.ok) {
                    this.chat.sessionId = r.session_id;
                    const u = r.usage || {};
                    this.chat.messages.push({
                        role: "claude", text: r.text, at: new Date().toLocaleTimeString(),
                        meta: "токены: " + (u.input_tokens ?? "?") + " → " + (u.output_tokens ?? "?") +
                              (u.duration_ms ? " · " + Math.round(u.duration_ms / 1000) + "с" : "")
                    });
                } else {
                    this.chat.messages.push({ role: "claude", text: "⚠ " + r.error,
                                              at: new Date().toLocaleTimeString() });
                }
            } catch (e) {
                this.chat.messages.push({ role: "claude", text: "⚠ ошибка запроса: " + e,
                                          at: new Date().toLocaleTimeString() });
            }
            this.chat.busy = false;
            this.scrollChat();
        },
        scrollChat() {
            this.$nextTick(() => {
                const el = this.$refs.chatbox;
                if (el) el.scrollTop = el.scrollHeight;
            });
        },
        chatNew() { this.chat.sessionId = null; this.chat.messages = []; },

        /* ── логи ── */
        async loadLogs() {
            try {
                const p = new URLSearchParams({ src: this.logs.src, q: this.logs.q,
                                                level: this.logs.level, logger: this.logs.logger,
                                                n: this.logs.n });
                this.logs.entries = await this.getJSON("/api/logs?" + p);
                this.logs.auto = true;
                this.scrollLogs(true);
            } catch (e) { /* noop */ }
        },
        logMatches(r) {
            if (this.logs.src === "logs") {
                if (this.logs.level && String(r.level || "").toUpperCase() !== this.logs.level) return false;
                if (this.logs.logger && !String(r.logger || "").toLowerCase().includes(this.logs.logger.toLowerCase())) return false;
                if (this.logs.q && !(String(r.msg || "") + String(r.exc || "")).toLowerCase().includes(this.logs.q.toLowerCase())) return false;
            } else {
                if (this.logs.q && !String(r.msg || "").toLowerCase().includes(this.logs.q.toLowerCase())) return false;
            }
            return true;
        },
        pushLog(rec) {
            if (!this.logMatches(rec)) return;
            this.logs.entries.push(rec);
            if (this.logs.entries.length > 2000) this.logs.entries.splice(0, this.logs.entries.length - 2000);
            this.scrollLogs();
        },
        scrollLogs(force) {
            this.$nextTick(() => {
                const el = this.$refs.logbox;
                if (el && (this.logs.auto || force)) el.scrollTop = el.scrollHeight;
            });
        },
        onLogScroll() {
            const el = this.$refs.logbox;
            if (!el) return;
            this.logs.auto = el.scrollHeight - el.scrollTop - el.clientHeight < 60;
        },

        /* ── WebSocket ── */
        onWsState(ok) { this.wsOk = ok; },
        onWsMessage(m) {
            if (m.type === "agent_status") {
                this.agent.state = m.status;
                this.agent.status_line = m.status_line;
                this.agent.pid = m.pid;
                this.agent.started_at = m.started_at;
                this.agent.dry_run = m.mode === "dry-run";
                this.agent.paused = m.paused;   // иначе пауза, включённая из расширения, залипала бы
                this.setUptime(m.uptime);
            } else if (m.type === "event") {
                const d = m.data || {};
                if (this.tab === "logs" && this.logs.src === "logs") this.pushLog(d);
                this.pushDlog(d);
            } else if (m.type === "trace") {
                if (this.tab === "logs" && this.logs.src === "trace") this.pushLog(m.data || {});
            } else if (m.type === "approvals") {
                this.pendingCount = m.count;
                this.stats.pending = m.count;
                if (this.tab === "dashboard") this.loadStack();
                else { this.loadApprovals(); if (this.tab === "tickets" && !this.ticket) this.loadTickets(); }
            } else if (m.type === "approval_request") {
                this.notice("новый запрос одобрения: #" + m.issue_id + " (" + this.pipeLabel(m.pipe) + ")", true);
                if (this.tab === "dashboard") this.loadStack(); else this.loadApprovals();
            } else if (m.type === "feed_update") {
                if (this.tab === "dashboard") this.loadStack();
                if (this.tab === "mails") this.loadMails();
                if (this.tab === "tickets" && !this.ticket) this.loadTickets();
            }
        }
    };
}
window.dash = dash;
