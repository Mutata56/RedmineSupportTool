// similar-issues.js - поиск похожих тикетов через встроенный Redmine /search.json
// MVP: на странице тикета или формы создания показываем боковой блок
// «Похожие случаи» с топ-N результатами и сниппетами «решения».

(function () {
    'use strict';

    const PANEL_ID       = 'ltm-similar-issues';
    const CACHE          = new Map();
    const CACHE_TTL_MS   = 10 * 60 * 1000;
    const MIN_SUBJECT    = 5;            // минимум символов в subject, чтобы запрашивать
    const SEARCH_LIMIT   = 10;
    const SHOW_LIMIT     = 8;
    const SOLUTION_TOP   = 3;            // для скольких результатов подгружать сниппет решения
    const KEYWORDS_TOP   = 4;            // сколько ключевых слов отправлять в search
    const ANCHORS_TOP    = 3;            // сколько якорных паттернов (ORA-XXX, GUID и т.п.)
    const DESC_MAX       = 2000;         // сколько символов description парсить на ключевые слова
    const DEBOUNCE_MS    = 800;
    const DEBUG          = true;         // консоль-логи в DevTools под тегом [Similar]

    // Якорные паттерны - уникальные сигнатуры, которые почти не бывают случайно
    // одинаковыми у разных тикетов. Если такой токен совпал - почти точно «то же».
    const ANCHOR_PATTERNS = [
        /\bORA-\d+\b/g,                                                                 // Oracle errors: ORA-20001
        /\bSQL[\s-]?\d{3,}\b/gi,                                                        // SQL-codes
        /\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b/gi,           // GUID с дефисами
        /\b[0-9A-F]{32}\b/g,                                                            // GUID без дефисов (UPPER hex длины 32)
        /\b[A-Z]{2,}[_-][A-Z0-9_]{2,}\b/g                                               // CONSTANT_NAMES, kebab-Cases
    ];

    // Стоп-слова и общая «вода», которые не несут смысла для поиска похожих тикетов
    const STOP_WORDS = new Set([
        // RU служебные
        'и','в','во','не','что','он','на','я','с','со','как','а','то','все','она','так','его','но','да',
        'ты','к','у','же','вы','за','бы','по','только','ее','мне','было','вот','от','меня','еще','нет',
        'о','из','ему','когда','если','уже','или','ни','быть','был','него','до','вас','для','мы','их',
        'чем','была','без','чего','раз','тоже','под','будет','тогда','кто','этот','того','этого',
        'какой','этом','один','при','об','другой','после','над','больше','тот','через','эти','нас','про',
        // RU частые в IT-тикетах (мусор, везде встречается)
        'ошибка','ошибки','ошибку','проблема','проблемы','проблему','вопрос','помогите','прошу',
        'пожалуйста','работает','работают','нужно','надо','можно','есть','делать','сделать',
        'добрый','день','здравствуйте','спасибо','клиент','задача',
        // EN
        'the','a','an','is','are','was','were','be','been','have','has','had','do','does','did','will',
        'would','could','should','can','this','that','these','those','it','we','they','what','which',
        'where','when','why','how','all','any','no','not','only','of','on','in','at','to','for','with',
        'by','as','from','but','or','if','and','error','issue','bug','please','help'
    ]);

    let pendingSearchController = null;
    let debounceTimer           = null;
    let API_KEY                 = '';     // подгрузим из chrome.storage.sync
    let ENABLED                 = true;
    let SCOPE_ALL_PROJECTS      = false;  // false = только клиентский корень + дети

    // ID корневого проекта «ТЕХПОДДЕРЖКА» - прямые дети считаются «клиентами».
    // Для другого инстанса Redmine можно поменять / вынести в настройки.
    const SUPPORT_ROOT_ID  = 2;
    const PROJECTS_KEY     = 'ltm_redmine_projects';
    const PROJECTS_TTL_MS  = 24 * 60 * 60 * 1000;

    let _projectsCache    = null;   // { id, name, identifier, parent: {id} }[]
    let _projectsLoading  = null;   // promise когда идёт загрузка

    // ── Определяем тип страницы ──────────────────────────────────────────────
    function getPageContext() {
        const m = location.pathname.match(/^\/issues\/(new|\d+)/);
        if (!m) return null;
        if (m[1] === 'new') return { mode: 'new' };
        return { mode: 'view', issueId: parseInt(m[1], 10) };
    }

    // ── Извлечение subject + description из DOM ──────────────────────────────
    function extractFields(ctx) {
        if (ctx.mode === 'new') {
            const subj = document.getElementById('issue_subject')?.value || '';
            const desc = document.getElementById('issue_description')?.value || '';
            return { subject: subj.trim(), description: desc.trim() };
        }
        // Просмотр тикета: <div class="subject"><div><h3>...</h3>
        const subj = document.querySelector('.issue .subject h3')?.textContent
                  || document.querySelector('.issue h3')?.textContent
                  || '';
        const desc = document.querySelector('.issue .description .wiki')?.innerText
                  || document.querySelector('.issue .description')?.innerText
                  || '';
        return {
            subject:     subj.replace(/^#\d+\s*[:.\-]?\s*/, '').trim(),
            description: desc.trim()
        };
    }

    // ── Хедеры с API-key (если задан) ───────────────────────────────────────
    // X-Requested-With заставляет Redmine отвечать JSON 401 вместо browser
    // basic-auth диалога. X-Redmine-API-Key - собственно авторизация.
    function apiHeaders() {
        const h = {
            'Accept':           'application/json',
            'X-Requested-With': 'XMLHttpRequest'
        };
        if (API_KEY) h['X-Redmine-API-Key'] = API_KEY;
        return h;
    }

    // Спец-ошибка для случая «нет ключа / неправильный ключ»
    class AuthError extends Error {}

    function log(...args) { if (DEBUG) console.log('[Similar]', ...args); }

    // ── Извлечение якорных паттернов (коды ошибок, GUID, константы) ──────────
    // Эти токены почти не бывают случайно одинаковыми → дают «снайперский» матч.
    function extractAnchors(text) {
        if (!text) return [];
        const set = new Set();
        for (const pat of ANCHOR_PATTERNS) {
            const matches = text.match(pat) || [];
            matches.forEach(m => set.add(m.trim()));
        }
        return [...set];
    }

    // ── Извлечение обычных ключевых слов ─────────────────────────────────────
    // Только слова длиной ≥4, не стоп-слова, не чисто числа.
    // Принимает уже «очищенный» от якорей текст, чтобы не дублировать.
    function extractKeywords(text) {
        const tokens = (text || '')
            .toLowerCase()
            .replace(/[«»"'`(){}\[\]<>.,;:!?\\\/|*+=#@$%^&~]/g, ' ')
            .split(/\s+/)
            .filter(Boolean);

        const seen = new Set();
        const out  = [];
        for (const t of tokens) {
            if (t.length < 4) continue;
            if (/^\d+$/.test(t)) continue;       // голые числа
            if (STOP_WORDS.has(t)) continue;
            if (seen.has(t)) continue;
            seen.add(t);
            out.push(t);
        }
        // Сортируем по длине убыв. (длинные слова обычно более характерны)
        return out.sort((a, b) => b.length - a.length);
    }

    function dedupeById(arr) {
        const seen = new Set();
        return arr.filter(r => {
            if (!r?.id || seen.has(r.id)) return false;
            seen.add(r.id);
            return true;
        });
    }

    // ── Список всех проектов (с кешем 24ч в chrome.storage.local) ────────────
    async function loadAllProjects() {
        if (_projectsCache) return _projectsCache;
        if (_projectsLoading) return _projectsLoading;

        _projectsLoading = (async () => {
            const cached = await new Promise(r =>
                chrome.storage.local.get([PROJECTS_KEY], v => r(v[PROJECTS_KEY])));
            if (cached && Date.now() - cached.ts < PROJECTS_TTL_MS) {
                log('projects: cache hit (', cached.data.length, 'шт)');
                _projectsCache = cached.data;
                return cached.data;
            }

            const all = [];
            let offset = 0, total = 1;
            while (offset < total) {
                const url = `/projects.json?include=parent&limit=100&offset=${offset}`;
                log('GET', url);
                const r = await fetch(url, { credentials: 'same-origin', headers: apiHeaders() });
                if (r.status === 401 || r.status === 403) throw new AuthError(`HTTP ${r.status}`);
                if (!r.ok) throw new Error(`HTTP ${r.status}`);
                const data = await r.json();
                all.push(...(data.projects || []));
                total  = data.total_count || all.length;
                offset += 100;
            }

            // Оставляем только то что нужно (компактно для кеша)
            const compact = all.map(p => ({
                id:         p.id,
                name:       p.name,
                identifier: p.identifier,
                parent:     p.parent ? { id: p.parent.id } : null
            }));
            chrome.storage.local.set({ [PROJECTS_KEY]: { ts: Date.now(), data: compact } });
            log('projects: загружено', compact.length, 'шт, кеш на 24ч');
            _projectsCache = compact;
            return compact;
        })();

        try { return await _projectsLoading; }
        finally { _projectsLoading = null; }
    }

    // ── Найти «клиентский корень»: подняться от текущего вверх до прямого
    //    ребёнка SUPPORT_ROOT_ID. Если проект сам корневой / вне иерархии
    //    ТЕХПОДДЕРЖКИ - вернём сам.                                          ──
    function findClientRoot(projectId, projects) {
        const byId = new Map(projects.map(p => [p.id, p]));
        let current = byId.get(projectId);
        if (!current) return null;

        // Если current уже сам корень или вне иерархии ТП - вернём его
        let safetyDepth = 20;
        while (current.parent?.id && safetyDepth-- > 0) {
            if (current.parent.id === SUPPORT_ROOT_ID) return current;
            const parent = byId.get(current.parent.id);
            if (!parent) break;
            current = parent;
        }
        return current;
    }

    // ── Определить ID текущего проекта (на странице тикета или формы) ────────
    async function getCurrentProjectId(ctx) {
        // Форма: select#issue_project_id с selected option
        if (ctx.mode === 'new') {
            const sel = document.getElementById('issue_project_id');
            if (sel?.value) return parseInt(sel.value, 10);
            return null;
        }
        // Просмотр тикета: наиболее надёжно - body class "project-<slug>"
        const m = document.body.className.match(/\bproject-([\w-]+)\b/);
        if (m) {
            const slug = m[1];
            try {
                const projects = await loadAllProjects();
                const p = projects.find(x => x.identifier === slug);
                if (p) return p.id;
            } catch (e) { log('projects load failed:', e.message); }
        }
        // Запасной вариант - через REST
        try {
            const r = await fetch(`/issues/${ctx.issueId}.json`, {
                credentials: 'same-origin', headers: apiHeaders()
            });
            if (r.ok) {
                const data = await r.json();
                return data.issue?.project?.id || null;
            }
        } catch {}
        return null;
    }

    // ── Получить scope-проект (клиентский корень) для текущего тикета ────────
    async function getScopeProject(ctx) {
        if (SCOPE_ALL_PROJECTS) return null;
        try {
            const [pid, projects] = await Promise.all([
                getCurrentProjectId(ctx),
                loadAllProjects()
            ]);
            if (!pid) return null;
            const root = findClientRoot(pid, projects);
            if (root) log('scope: проект «' + root.name + '» (#' + root.id + ')');
            return root;
        } catch (e) {
            if (e instanceof AuthError) throw e;
            log('scope detection failed:', e.message);
            return null;
        }
    }

    // ── Запрос к /search.json (полнотекст) ───────────────────────────────────
    // scopeProject != null → ограничиваем поиск проектом и его подпроектами
    async function querySearchJson(query, signal, scopeProject) {
        const base   = scopeProject
            ? `/projects/${encodeURIComponent(scopeProject.identifier)}/search.json`
            : `/search.json`;
        const scopeP = scopeProject ? '&scope=subprojects' : '&scope=all';
        const url    = `${base}?q=${encodeURIComponent(query)}&issues=1&open_issues=0`
                     + `${scopeP}&all_words=0&titles_only=0&limit=${SEARCH_LIMIT}`;
        log('GET', url);
        const r = await fetch(url, { signal, credentials: 'same-origin', headers: apiHeaders() });
        if (r.status === 401 || r.status === 403) throw new AuthError(`HTTP ${r.status}`);
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const data = await r.json();
        log('search.json →', data.results?.length || 0, 'results');
        return (data.results || []).map(r => ({
            id:       r.id,
            url:      r.url,
            title:    r.title,
            datetime: r.datetime
        }));
    }

    // ── Fallback: /issues.json?subject=~ (работает всегда - независимо от
    //              настроек полнотекстового поиска)                          ──
    async function queryIssuesByKeyword(keyword, signal, scopeProject) {
        // status_id=* = в любом статусе (включая закрытые), sort=updated_on:desc - свежие сверху
        // project_id + subproject_id=* - ограничение по клиентскому корню и его детям
        const projectFilter = scopeProject
            ? `&project_id=${encodeURIComponent(scopeProject.identifier)}&subproject_id=*`
            : '';
        const url = `/issues.json?subject=${encodeURIComponent('~' + keyword)}`
                  + `&status_id=*&sort=updated_on:desc&limit=10${projectFilter}`;
        log('GET', url);
        const r = await fetch(url, { signal, credentials: 'same-origin', headers: apiHeaders() });
        if (r.status === 401 || r.status === 403) throw new AuthError(`HTTP ${r.status}`);
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const data   = await r.json();
        const issues = data.issues || [];
        log('issues.json by ~' + keyword + ' →', issues.length, 'results');
        return issues.map(i => ({
            id:       i.id,
            url:      `${location.origin}/issues/${i.id}`,
            title:    `${i.tracker?.name || 'Issue'} #${i.id} (${i.status?.name || ''}): ${i.subject || ''}`,
            datetime: i.updated_on
        }));
    }

    // ── Главный поиск: anchors → search.json → fallback к issues.json ────────
    async function searchSimilar(subject, description, scopeProject) {
        if (!subject || subject.length < MIN_SUBJECT) return [];

        // Парсим subject полностью + первые DESC_MAX символов description.
        // Description часто содержит самое ценное (коды ошибок, GUID, имена джобов).
        const corpus  = subject + ' ' + (description || '').substring(0, DESC_MAX);
        const anchors = extractAnchors(corpus).slice(0, ANCHORS_TOP);

        // Из текста для keywords УБИРАЕМ якорные совпадения, чтобы не дублировать.
        // Параллельно anchor'ы попадают в q как точные подстроки (с кавычками
        // их Redmine лучше матчит).
        let cleanText = corpus;
        for (const a of anchors) cleanText = cleanText.split(a).join(' ');
        const keywords = extractKeywords(cleanText).slice(0, KEYWORDS_TOP);

        log('anchors:', anchors);
        log('keywords:', keywords);

        if (anchors.length === 0 && keywords.length === 0) {
            log('пусто - нечего искать');
            return [];
        }

        // Якоря в кавычках, чтобы Redmine искал точную подстроку
        const queryParts = [
            ...anchors.map(a => `"${a}"`),
            ...keywords
        ];
        const query     = queryParts.join(' ');
        const scopeId   = scopeProject?.id ?? 'all';
        const cacheKey  = `q:${scopeId}:${query}`;
        const cached    = CACHE.get(cacheKey);
        if (cached && Date.now() - cached.ts < CACHE_TTL_MS) {
            log('cache hit');
            return cached.data;
        }

        pendingSearchController?.abort();
        pendingSearchController = new AbortController();
        const signal = pendingSearchController.signal;

        try {
            // Этап 1: полнотекстовый search.json со всем что нашли
            let results = await querySearchJson(query, signal, scopeProject);

            // Этап 2: если пусто - fallback к /issues.json.
            //         Сначала по якорям (точные строки), потом по keywords.
            if (results.length === 0) {
                log('search.json пусто → fallback к /issues.json');
                const fallbackHits = [];
                const probes = [...anchors, ...keywords].slice(0, 3); // не больше 3 fallback-запросов
                for (const probe of probes) {
                    const hit = await queryIssuesByKeyword(probe, signal, scopeProject);
                    fallbackHits.push(...hit);
                    if (fallbackHits.length >= SHOW_LIMIT) break;
                }
                results = dedupeById(fallbackHits);
            }

            CACHE.set(cacheKey, { ts: Date.now(), data: results });
            return results;
        } catch (e) {
            if (e.name === 'AbortError') return [];
            if (e instanceof AuthError) throw e;
            console.warn('[Similar]', e);
            return [];
        }
    }

    // ── Подгрузка «решения» - последний коммент сапортера ───────────────────
    async function fetchSolution(issueId) {
        try {
            const r = await fetch(`/issues/${issueId}.json?include=journals`, {
                credentials: 'same-origin',
                headers:     apiHeaders()
            });
            if (!r.ok) return null;
            const data     = await r.json();
            const journals = data.issue?.journals || [];

            // Сначала ищем коммент со ссылкой на код / SQL / pre-блок
            const reversed = [...journals].reverse();
            const codeJ    = reversed.find(j => j.notes && /<pre>|```|\bsql\b/i.test(j.notes));
            const lastJ    = reversed.find(j => j.notes && j.notes.trim());
            const journal  = codeJ || lastJ;
            if (!journal) return null;

            const text = journal.notes
                .replace(/<pre[\s\S]*?<\/pre>/gi, ' [SQL/код] ')
                .replace(/<[^>]+>/g, ' ')
                .replace(/\s+/g, ' ')
                .trim();
            return text.length > 200 ? text.substring(0, 200) + '…' : text;
        } catch {
            return null;
        }
    }

    // ── Рендер боковой панели ────────────────────────────────────────────────
    function escapeHtml(s) {
        return String(s).replace(/[&<>"']/g, c => (
            { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
        ));
    }

    function ensurePanel(ctx) {
        let p = document.getElementById(PANEL_ID);
        if (p) return p;

        p = document.createElement('div');
        p.id = PANEL_ID;
        p.className = 'ltm-similar-panel';
        p.innerHTML = `
            <div class="ltm-similar-header">
                <span class="ltm-similar-title">Похожие случаи</span>
                <span class="ltm-similar-count"></span>
            </div>
            <div class="ltm-similar-search">
                <input type="text" class="ltm-similar-search-input"
                       placeholder="Свой запрос - Enter для поиска"
                       title="Работает как поиск в Redmine: можно вписать ORA-код, GUID, ключевые слова">
                <button type="button" class="ltm-similar-search-btn" title="Найти">Найти</button>
                <button type="button" class="ltm-similar-search-reset" title="Вернуть авто-результаты">↺</button>
            </div>
            <label class="ltm-similar-scope-toggle" title="Снять - искать по всем проектам Redmine">
                <input type="checkbox" class="ltm-similar-scope-cb" ${SCOPE_ALL_PROJECTS ? '' : 'checked'}>
                <span>только этот клиент и его подпроекты</span>
            </label>
            <div class="ltm-similar-body"></div>
        `;

        // Обработчики ручного поиска
        const input    = p.querySelector('.ltm-similar-search-input');
        const btn      = p.querySelector('.ltm-similar-search-btn');
        const resetBtn = p.querySelector('.ltm-similar-search-reset');

        const doManual = () => {
            const q = input.value.trim();
            if (!q) return;
            manualSearch(p, ctx, q);
        };

        btn.addEventListener('click', doManual);
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') { e.preventDefault(); doManual(); }
        });
        resetBtn.addEventListener('click', () => {
            input.value = '';
            run(ctx);   // перезапуск авто-поиска
        });

        // Переключатель scope: «только этот клиент» ↔ «по всем проектам»
        const scopeCb = p.querySelector('.ltm-similar-scope-cb');
        scopeCb.addEventListener('change', () => {
            SCOPE_ALL_PROJECTS = !scopeCb.checked;
            log('SCOPE_ALL_PROJECTS =', SCOPE_ALL_PROJECTS);
            run(ctx);  // полностью перезапускаем поиск с новым scope
        });

        if (ctx.mode === 'view') {
            // Сайдбар Redmine - справа от тикета
            const sidebar = document.getElementById('sidebar');
            if (sidebar) sidebar.prepend(p);
            else (document.querySelector('.issue') || document.getElementById('content'))?.appendChild(p);
        } else {
            // На форме создания - после формы
            const form = document.getElementById('issue-form');
            if (form) form.after(p);
            else document.getElementById('content')?.appendChild(p);
        }
        return p;
    }

    // ── Ручной поиск: пользователь сам ввёл строку, отправляем как-есть ──
    async function manualSearch(panel, ctx, queryText) {
        const body = panel.querySelector('.ltm-similar-body');
        body.innerHTML = '<div class="ltm-similar-loading">Ищу по запросу…</div>';
        log('manual search:', queryText);

        pendingSearchController?.abort();
        pendingSearchController = new AbortController();
        const signal = pendingSearchController.signal;

        // Ручной поиск тоже уважает выбранный scope (этот клиент / по всем)
        const scopeProject = await getScopeProject(ctx).catch(() => null);

        try {
            // Отправляем строку как есть - пользователь сам знает что вбил
            let results = await querySearchJson(queryText, signal, scopeProject);

            // Тот же fallback на /issues.json по самому длинному «слову» из запроса
            if (results.length === 0) {
                const probes = queryText.split(/\s+/).filter(w => w.length >= 3)
                    .sort((a, b) => b.length - a.length)
                    .slice(0, 2);
                log('manual: fallback к /issues.json по', probes);
                const fb = [];
                for (const p of probes) {
                    fb.push(...await queryIssuesByKeyword(p, signal, scopeProject));
                    if (fb.length >= SHOW_LIMIT) break;
                }
                results = dedupeById(fb);
            }
            renderResults(panel, results, ctx.issueId);
        } catch (e) {
            if (e.name === 'AbortError') return;
            if (e instanceof AuthError) {
                body.innerHTML = '<div class="ltm-similar-empty">Нет API-ключа Redmine - задайте его в настройках.</div>';
            } else {
                console.warn('[Similar]', e);
                body.innerHTML = '<div class="ltm-similar-empty">Ошибка поиска</div>';
            }
        }
    }

    function renderResults(panel, results, currentIssueId) {
        const body  = panel.querySelector('.ltm-similar-body');
        const count = panel.querySelector('.ltm-similar-count');

        const filtered = results.filter(r => r.id !== currentIssueId).slice(0, SHOW_LIMIT);
        count.textContent = filtered.length ? `(${filtered.length})` : '';

        if (!filtered.length) {
            body.innerHTML = '<div class="ltm-similar-empty">Похожих не найдено</div>';
            return;
        }

        body.innerHTML = filtered.map(r => {
            const date = r.datetime ? new Date(r.datetime).toLocaleDateString('ru-RU') : '';
            return `
                <a class="ltm-similar-item" href="${escapeHtml(r.url)}" target="_blank" data-id="${r.id}">
                    <div class="ltm-similar-item-top">
                        <span class="ltm-similar-item-id">#${r.id}</span>
                        <span class="ltm-similar-item-date">${escapeHtml(date)}</span>
                    </div>
                    <div class="ltm-similar-item-title">${escapeHtml(r.title || '')}</div>
                    <div class="ltm-similar-item-solution" data-loading="1">загрузка решения…</div>
                </a>
            `;
        }).join('');

        // Подгружаем «решения» только для топ-N результатов
        filtered.slice(0, SOLUTION_TOP).forEach(async (r) => {
            const sol = await fetchSolution(r.id);
            const el  = body.querySelector(`.ltm-similar-item[data-id="${r.id}"] .ltm-similar-item-solution`);
            if (!el) return;
            if (sol) {
                el.removeAttribute('data-loading');
                el.textContent = '→ ' + sol;
            } else {
                el.remove();
            }
        });
        // Для остальных просто скрываем placeholder
        filtered.slice(SOLUTION_TOP).forEach(r => {
            body.querySelector(`.ltm-similar-item[data-id="${r.id}"] .ltm-similar-item-solution`)?.remove();
        });
    }

    // ── Главная логика запуска ───────────────────────────────────────────────
    async function run(ctx) {
        if (!ENABLED) return;
        const { subject, description } = extractFields(ctx);
        if (!subject || subject.length < MIN_SUBJECT) return;

        const panel = ensurePanel(ctx);
        const body  = panel.querySelector('.ltm-similar-body');
        body.innerHTML = '<div class="ltm-similar-loading">Ищу похожие…</div>';

        // Параллельно: определяем scope-проект (клиентский корень)
        let scopeProject = null;
        try { scopeProject = await getScopeProject(ctx); }
        catch (e) {
            if (e instanceof AuthError) { renderAuthError(body); return; }
        }
        updateScopeLabel(panel, scopeProject);

        try {
            const results = await searchSimilar(subject, description, scopeProject);
            renderResults(panel, results, ctx.issueId);
        } catch (e) {
            if (e instanceof AuthError) renderAuthError(body);
            else body.innerHTML = '<div class="ltm-similar-empty">Ошибка поиска</div>';
        }
    }

    function renderAuthError(body) {
        body.innerHTML = `
            <div class="ltm-similar-empty">
                Redmine просит авторизацию. Укажите ваш
                <b>Redmine API key</b> в настройках расширения
                (Дашборд → Настройки → «Похожие тикеты»).<br>
                <small>Где взять ключ: Redmine → Моя учётная запись → блок «Доступ к API» → «Показать».</small>
            </div>
        `;
    }

    function updateScopeLabel(panel, scopeProject) {
        const titleEl = panel.querySelector('.ltm-similar-title');
        if (!titleEl) return;
        if (SCOPE_ALL_PROJECTS || !scopeProject) {
            titleEl.textContent = 'Похожие случаи (все проекты)';
        } else {
            titleEl.textContent = `Похожие случаи · ${scopeProject.name}`;
            titleEl.title       = `Поиск ограничен проектом "${scopeProject.name}" и его подпроектами`;
        }
    }

    function debouncedRun(ctx) {
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(() => run(ctx), DEBOUNCE_MS);
    }

    function destroyPanel() {
        document.getElementById(PANEL_ID)?.remove();
    }

    // ── Init ─────────────────────────────────────────────────────────────────
    const ctx = getPageContext();
    if (!ctx) return;

    chrome.storage.sync.get(['similarIssuesEnabled', 'redmineApiKey'], (result) => {
        ENABLED = result.similarIssuesEnabled !== undefined ? result.similarIssuesEnabled : true;
        API_KEY = result.redmineApiKey || '';
        if (!ENABLED) return;
        startListeners(ctx);
    });

    // Подхватываем смену настроек на лету (без перезагрузки страницы)
    chrome.storage.onChanged.addListener((changes, area) => {
        if (area !== 'sync') return;
        if (changes.redmineApiKey) {
            API_KEY = changes.redmineApiKey.newValue || '';
            CACHE.clear();   // старый ключ мог давать пустые ответы - кеш невалиден
        }
        if (changes.similarIssuesEnabled) {
            const wasEnabled = ENABLED;
            ENABLED = !!changes.similarIssuesEnabled.newValue;
            if (!ENABLED) {
                destroyPanel();
            } else if (!wasEnabled) {
                startListeners(ctx);
                if (ctx.mode === 'view') run(ctx);
            }
        }
        if (changes.redmineApiKey && ENABLED) {
            // ключ обновили - повторим запрос
            run(ctx);
        }
    });

    function startListeners(ctx) {
        if (ctx.mode === 'view') {
            run(ctx);
        } else {
            const subjectInput = document.getElementById('issue_subject');
            const descInput    = document.getElementById('issue_description');

            subjectInput?.addEventListener('blur',  () => debouncedRun(ctx));
            subjectInput?.addEventListener('input', () => debouncedRun(ctx));
            descInput?.addEventListener('blur',     () => debouncedRun(ctx));

            // Если поля уже заполнены при загрузке (prefill из mail-checker) -
            // запускаем сразу
            if (subjectInput?.value?.length >= MIN_SUBJECT) run(ctx);
        }
    }
})();
