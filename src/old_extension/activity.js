/**
 * Скрипт управления сменами <название>
 * Обрабатывает управление сменами, операции с тикетами и контекстные меню
 * @version 2.0.0
 * @author KKRLL56
 */

(function () {
    'use strict';

    /**
     * Глобальные переменные модуля
     */
    const STORAGE_KEY = '_ticketShiftStorage'; // Ключ хранилища для данных смены

    /** Лёгкий toast - не зависит от issues-menu.js */
    function showToast(message, type = 'success', duration = 3000) {
        const toast = document.createElement('div');
        const bg = type === 'error' ? '#ef4444' : type === 'warning' ? '#f59e0b' : '#22c55e';
        toast.style.cssText = `
            position:fixed; bottom:24px; left:50%; transform:translateX(-50%) translateY(20px);
            z-index:9999999; background:${bg}; color:#fff;
            padding:10px 20px; border-radius:8px; font-size:13px; font-weight:600;
            font-family:system-ui,sans-serif; box-shadow:0 4px 16px rgba(0,0,0,0.25);
            opacity:0; transition:opacity 0.2s ease, transform 0.2s ease; pointer-events:none;
        `;
        toast.textContent = message;
        document.body.appendChild(toast);
        requestAnimationFrame(() => {
            toast.style.opacity = '1';
            toast.style.transform = 'translateX(-50%) translateY(0)';
        });
        setTimeout(() => {
            toast.style.opacity = '0';
            toast.style.transform = 'translateX(-50%) translateY(10px)';
            setTimeout(() => toast.remove(), 220);
        }, duration);
    }
    let previewBox      = null; // Элемент подсказки (tooltip)
    let overlayBox      = null; // Модальное окно просмотра смены
    let issuePreviewPanel    = null; // Панель предпросмотра заявки (iframe)
    let issuePreviewShowTimer = null;
    let issuePreviewHideTimer = null;

    /**
     * Функция задержки выполнения
     * @param {number} ms - Количество миллисекунд для задержки
     * @returns {Promise} Promise, который разрешается после указанного времени
     */
    function sleep(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
    }

    // =========================================================================
    // Issue preview panel - iframe-предпросмотр заявки при наведении
    // =========================================================================

    /**
     * Показывает всплывающее окно с iframe для предпросмотра заявки.
     * Позиционируется над элементом, на который навёл курсор.
     * @param {string}  url     - URL заявки для загрузки в iframe
     * @param {Element} anchorEl - Элемент, над которым показывать окно
     */
    function showIssuePreview(url, anchorEl) {
        clearTimeout(issuePreviewHideTimer);
        clearTimeout(issuePreviewShowTimer);

        issuePreviewShowTimer = setTimeout(() => {
            // Если уже открыта та же ссылка - не перезагружаем
            if (issuePreviewPanel && issuePreviewPanel.dataset.url === url) return;

            if (issuePreviewPanel) issuePreviewPanel.remove();

            const W = 560;  // ширина окна
            const H = 420;  // высота окна
            const GAP = 8;  // отступ от строки вверх

            const rect = anchorEl.getBoundingClientRect();

            // Горизонтально: центрируем по строке, не выходим за края экрана
            let left = rect.left + rect.width / 2 - W / 2;
            left = Math.max(8, Math.min(left, window.innerWidth - W - 8));

            // Вертикально: пробуем показать над строкой
            let top = rect.top - H - GAP;
            if (top < 8) top = rect.bottom + GAP; // не влезает сверху - показываем снизу

            issuePreviewPanel = document.createElement('div');
            issuePreviewPanel.className = 'ltm-issue-preview-panel';
            issuePreviewPanel.dataset.url = url;

            Object.assign(issuePreviewPanel.style, {
                position:      'fixed',
                top:           `${top}px`,
                left:          `${left}px`,
                width:         `${W}px`,
                height:        `${H}px`,
                zIndex:        '10000000',
                background:    '#fff',
                border:        '1px solid #d1d5db',
                borderRadius:  '10px',
                boxShadow:     '0 8px 32px rgba(0,0,0,0.22), 0 2px 8px rgba(0,0,0,0.10)',
                display:       'flex',
                flexDirection: 'column',
                overflow:      'hidden',
                animation:     'ltm-preview-slide-in 0.15s ease',
            });

            // ── Шапка панели ─────────────────────────────────────────────────
            const header = document.createElement('div');
            Object.assign(header.style, {
                display:        'flex',
                alignItems:     'center',
                justifyContent: 'space-between',
                padding:        '8px 12px',
                background:     '#1e40af',
                color:          '#fff',
                fontSize:       '12px',
                flexShrink:     '0',
                gap:            '8px',
            });

            const issueId = (url.match(/\/issues\/(\d+)/) || [])[1] || '';
            const headerTitle = document.createElement('span');
            headerTitle.textContent = issueId ? `Заявка #${issueId}` : 'Предпросмотр';
            headerTitle.style.cssText = 'font-weight:600; opacity:0.95;';

            const headerLink = document.createElement('a');
            headerLink.href   = url;
            headerLink.target = '_blank';
            headerLink.textContent = '↗ Открыть';
            headerLink.style.cssText = 'color:#93c5fd; text-decoration:none; font-size:11px;';

            const closeBtn = document.createElement('button');
            closeBtn.textContent = '✕';
            closeBtn.title = 'Закрыть предпросмотр (Esc)';
            Object.assign(closeBtn.style, {
                background:   'transparent',
                border:       'none',
                color:        '#fff',
                fontSize:     '16px',
                cursor:       'pointer',
                lineHeight:   '1',
                padding:      '0 2px',
                opacity:      '0.8',
            });
            closeBtn.onmouseenter = () => { closeBtn.style.opacity = '1'; };
            closeBtn.onmouseleave = () => { closeBtn.style.opacity = '0.8'; };
            closeBtn.onclick = () => destroyIssuePreview();

            header.appendChild(headerTitle);
            header.appendChild(headerLink);
            header.appendChild(closeBtn);

            // ── iframe ────────────────────────────────────────────────────────
            const iframe = document.createElement('iframe');
            iframe.src = url;
            Object.assign(iframe.style, {
                flex:   '1',
                border: 'none',
                width:  '100%',
            });

            issuePreviewPanel.appendChild(header);
            issuePreviewPanel.appendChild(iframe);
            document.body.appendChild(issuePreviewPanel);

            // Пока курсор в панели - не скрываем
            issuePreviewPanel.addEventListener('mouseenter', () => {
                clearTimeout(issuePreviewHideTimer);
                clearTimeout(issuePreviewShowTimer);
            });
            issuePreviewPanel.addEventListener('mouseleave', () => scheduleHideIssuePreview());

        }, 350);
    }

    /** Запускает таймер скрытия панели (даёт 220ms чтобы курсор мог перейти в панель) */
    function scheduleHideIssuePreview() {
        clearTimeout(issuePreviewHideTimer);
        issuePreviewHideTimer = setTimeout(() => destroyIssuePreview(), 220);
    }

    /** Немедленно убирает панель и чистит таймеры */
    function destroyIssuePreview() {
        clearTimeout(issuePreviewShowTimer);
        clearTimeout(issuePreviewHideTimer);
        if (issuePreviewPanel) { issuePreviewPanel.remove(); issuePreviewPanel = null; }
    }

    // =========================================================================
    // Redmine API helpers - PATCH issue без перехода на страницу
    // =========================================================================

    const REASON_OPTIONS = [
        'Превентивные мероприятия',
        'Запрос на правку данных',
        'Консультация',
        'Нарушение целостности БД',
        'Проблема с ПО WMS',
        'Проблема с инфраструктурой',
        'Проблема с ПО Voice',
        'Прочее',
    ];

    async function getRedmineCsrf(issueId) {
        const res = await fetch(`/issues/${issueId}/edit`, { credentials: 'include' });
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const doc = new DOMParser().parseFromString(await res.text(), 'text/html');
        const el  = doc.querySelector('input[name="authenticity_token"]');
        if (!el) throw new Error('CSRF not found');
        return el.value;
    }

    async function patchIssue(issueId, fields) {
        const token = await getRedmineCsrf(issueId);
        const body  = new URLSearchParams({ authenticity_token: token, _method: 'patch', ...fields });
        const res   = await fetch(`/issues/${issueId}`, {
            method: 'POST', credentials: 'include',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: body.toString(),
        });
        if (!res.ok) throw new Error('HTTP ' + res.status);
    }

    function minsToHoursStr(mins) {
        return Math.floor(mins / 60) + ':' + String(mins % 60).padStart(2, '0');
    }

    /**
     * Простое выделение текста смены - подсвечивает URL, имена клиентов и описания
     * @param {string} text - Исходный текст смены
     * @returns {string} - Текст с HTML-подсветкой
     */
    function highlightShiftText(text) {
        if (!text || typeof text !== 'string') {
            return text || '';
        }

        // Escape HTML first to prevent XSS
        let escapedText = text
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');

        // Pattern: {url} – {clientname}: {ticketdescr}
        const lines = escapedText.split('\n');
        const highlightedLines = lines.map(line => {
            if (!line.trim() || (line.includes(':') && !line.includes('https'))) {
                return line;
            }

            const fullPattern = /^(https?:\/\/\S+?)\s+([–-])\s*([^:]+?)\s*:\s*(.+)$/;
            const match = line.match(fullPattern);

            if (match) {
                const [, url, dash, client, description] = match;
                return `<span class="shift-line-entry" data-issue-url="${url}"><span class="highlight-url">${url}</span> ${dash} <span class="highlight-client">${client}</span>: <span class="highlight-description">${description}</span></span>`;
            }

            return line;
        });

        return highlightedLines.join('\n');
    }

    // =========================================================================
    // renderShiftBody - богатый рендеринг смены с инлайн-действиями
    // =========================================================================

    function renderShiftBody(container, shiftObj, onRefresh) {
        const isDark   = isDarkMode();
        const PROBLEM  = { 'Нет трудозатрат': 'time', 'Нет причины обращения': 'reason' };
        const ALL_CATS = ['В работе', 'Ожидание ответа от клиента', 'Решена', 'Новая',
                          'Нет трудозатрат', 'Нет причины обращения'];

        container.innerHTML = '';
        container.style.cssText = 'font-family:monospace; font-size:12px; line-height:1.6; padding:2px 0;';

        const intro = document.createElement('div');
        intro.textContent = 'Доброе утро! По смене:';
        intro.style.cssText = 'margin-bottom:8px; font-weight:600;';
        container.appendChild(intro);

        ALL_CATS.forEach(cat => {
            const entries    = sortCategoryByUrl(shiftObj[cat] || []);
            const actionType = PROBLEM[cat] || null;

            const catHeader = document.createElement('div');
            catHeader.style.cssText = `margin-top:12px; font-weight:700; color:${isDark ? '#93c5fd' : '#1e40af'};`;
            catHeader.textContent = cat + ':';
            container.appendChild(catHeader);

            if (entries.length === 0) {
                const empty = document.createElement('div');
                empty.style.cssText = 'opacity:0.4; font-size:11px; padding-left:8px;';
                empty.textContent = '(нет)';
                container.appendChild(empty);
                return;
            }

            entries.forEach(line => {
                const urlMatch = line.match(/^(https?:\/\/[^\s]+)/);
                const issueUrl = urlMatch ? urlMatch[1] : null;
                const issueId  = issueUrl ? (issueUrl.match(/\/issues\/(\d+)/) || [])[1] : null;

                const lineWrap = document.createElement('div');
                lineWrap.style.cssText = 'margin:1px 0 0 8px;';

                // ── Строка текста ──────────────────────────────────────────────
                const lineRow = document.createElement('div');
                lineRow.style.cssText = 'display:flex; align-items:center; padding:2px 4px; border-radius:4px; transition:background 0.12s; gap:6px;';

                const lineText = document.createElement('span');
                lineText.style.cssText = 'flex:1; white-space:pre-wrap; word-break:break-all;';
                lineText.innerHTML = highlightShiftText(line);
                lineRow.appendChild(lineText);

                if (issueUrl) {
                    lineRow.style.cursor = 'pointer';
                    lineRow.addEventListener('mouseenter', () => {
                        lineRow.style.background = isDark ? 'rgba(96,165,250,0.1)' : 'rgba(59,130,246,0.08)';
                        showIssuePreview(issueUrl, lineRow);
                    });
                    lineRow.addEventListener('mouseleave', () => {
                        lineRow.style.background = '';
                        scheduleHideIssuePreview();
                    });
                }
                lineWrap.appendChild(lineRow);

                // ── Панель быстрых действий для проблемных категорий ──────────
                if (actionType && issueId) {
                    const actionRow = document.createElement('div');
                    actionRow.style.cssText = `
                        display:flex; align-items:center; flex-wrap:wrap; gap:4px;
                        padding:3px 4px 6px 8px;
                        border-left:2px solid ${isDark ? '#334155' : '#e5e7eb'};
                        margin-left:4px;
                    `;

                    // Вспомогательные функции ───────────────────────────────────
                    const makeBtn = (label, primary = false) => {
                        const b = document.createElement('button');
                        b.textContent = label;
                        const bg    = primary ? '#2563eb' : (isDark ? '#1e293b' : '#f3f4f6');
                        const clr   = primary ? '#fff'    : (isDark ? '#94a3b8' : '#374151');
                        const bdr   = primary ? '#2563eb' : (isDark ? '#334155' : '#d1d5db');
                        b.style.cssText = `
                            background:${bg}; color:${clr}; border:1px solid ${bdr};
                            border-radius:${primary ? '6px' : '999px'};
                            padding:2px ${primary ? '10px' : '7px'};
                            font-size:11px; cursor:pointer; font-family:monospace; transition:all 0.12s;
                        `;
                        b.addEventListener('mouseenter', () => { b.style.background='#2563eb'; b.style.color='#fff'; b.style.borderColor='#2563eb'; });
                        b.addEventListener('mouseleave', () => { b.style.background=bg; b.style.color=clr; b.style.borderColor=bdr; });
                        return b;
                    };

                    const setLoading = v => actionRow.querySelectorAll('button,input,select').forEach(el => {
                        el.disabled = v; el.style.opacity = v ? '0.45' : '1';
                    });

                    const showActionError = msg => {
                        const e = document.createElement('span');
                        e.textContent = '❌ ' + msg;
                        e.style.cssText = 'color:#dc2626; font-size:11px;';
                        actionRow.appendChild(e);
                        setTimeout(() => e.remove(), 3000);
                    };

                    const commitAndRefresh = async (fields) => {
                        setLoading(true);
                        try {
                            await patchIssue(issueId, fields);

                            // Перечитываем тикет и пересчитываем категорию
                            const res  = await fetch(`/issues/${issueId}`, { credentials: 'include' });
                            const doc  = res.ok ? new DOMParser().parseFromString(await res.text(), 'text/html') : null;

                            const statusEl  = doc && [...doc.querySelectorAll('#content .status.attribute .value')].pop();
                            const status    = statusEl ? statusEl.innerText.trim() : '';
                            const newCat    = getCategoryByStatus(status);

                            const reasonEl  = doc && doc.querySelector('.cf_109.attribute .value');
                            const hasReason = !!(reasonEl && reasonEl.textContent.trim());
                            const hasTime   = !!(doc && doc.querySelector('#tab-time_entries'));

                            // Определяем итоговую категорию
                            let targetCat;
                            if (!hasReason)      targetCat = 'Нет причины обращения';
                            else if (!hasTime)   targetCat = 'Нет трудозатрат';
                            else if (newCat)     targetCat = newCat;
                            else                 targetCat = null;

                            // Убираем строку из всех категорий смены
                            const ALL = ['В работе','Ожидание ответа от клиента','Решена','Новая',
                                         'Нет трудозатрат','Нет причины обращения'];
                            ALL.forEach(k => {
                                if (shiftObj[k]) shiftObj[k] = shiftObj[k].filter(l => l !== line);
                            });

                            // Кладём в новую категорию (если строки там ещё нет)
                            if (targetCat) {
                                if (!shiftObj[targetCat]) shiftObj[targetCat] = [];
                                if (!shiftObj[targetCat].includes(line)) shiftObj[targetCat].push(line);
                            }

                            saveStorage(shiftObj);
                            onRefresh();
                        } catch (err) {
                            console.error('<название> patchIssue:', err);
                            setLoading(false);
                            showActionError('Ошибка сохранения');
                        }
                    };

                    // ── Трудозатраты ───────────────────────────────────────────
                    if (actionType === 'time') {
                        [5, 10, 15, 30].forEach(mins => {
                            const btn = makeBtn(`${mins}м`);
                            btn.addEventListener('click', e => {
                                e.stopPropagation();
                                commitAndRefresh({
                                    'time_entry[hours]': minsToHoursStr(mins),
                                    'time_entry[activity_id]': '35',
                                });
                            });
                            actionRow.appendChild(btn);
                        });

                        const customInput = document.createElement('input');
                        customInput.type = 'number'; customInput.placeholder = 'мин'; customInput.min = '1';
                        customInput.style.cssText = `
                            width:52px; padding:2px 5px; font-size:11px; font-family:monospace;
                            border:1px solid ${isDark ? '#334155' : '#d1d5db'};
                            border-radius:6px;
                            background:${isDark ? '#1e293b' : '#f9fafb'};
                            color:${isDark ? '#e2e8f0' : '#111827'};
                        `;
                        customInput.addEventListener('click', e => e.stopPropagation());

                        const saveBtn = makeBtn('✓ Добавить', true);
                        saveBtn.addEventListener('click', e => {
                            e.stopPropagation();
                            const mins = parseInt(customInput.value);
                            if (!mins || mins <= 0) { customInput.focus(); return; }
                            commitAndRefresh({
                                'time_entry[hours]': minsToHoursStr(mins),
                                'time_entry[activity_id]': '35',
                            });
                        });

                        actionRow.appendChild(customInput);
                        actionRow.appendChild(saveBtn);

                    // ── Причина обращения ──────────────────────────────────────
                    } else if (actionType === 'reason') {
                        const select = document.createElement('select');
                        select.style.cssText = `
                            padding:2px 6px; font-size:11px; font-family:monospace; cursor:pointer;
                            border:1px solid ${isDark ? '#334155' : '#d1d5db'};
                            border-radius:6px;
                            background:${isDark ? '#1e293b' : '#f9fafb'};
                            color:${isDark ? '#e2e8f0' : '#111827'};
                        `;
                        select.addEventListener('click', e => e.stopPropagation());

                        const ph = document.createElement('option');
                        ph.value = ''; ph.textContent = 'Причина…'; ph.disabled = true; ph.selected = true;
                        select.appendChild(ph);
                        REASON_OPTIONS.forEach(r => {
                            const opt = document.createElement('option');
                            opt.value = r; opt.textContent = r;
                            select.appendChild(opt);
                        });

                        const saveBtn = makeBtn('✓ Сохранить', true);
                        saveBtn.addEventListener('click', e => {
                            e.stopPropagation();
                            const reason = select.value;
                            if (!reason) { select.focus(); return; }
                            commitAndRefresh({ 'issue[custom_field_values][<field_id>]': reason });
                        });

                        actionRow.appendChild(select);
                        actionRow.appendChild(saveBtn);
                    }

                    lineWrap.appendChild(actionRow);
                }

                container.appendChild(lineWrap);
            });
        });
    }

    /**
     * Показывает модальное окно с текстом смены
     * @param {string} text     - Текст смены для кнопки «Скопировать»
     * @param {Object} shiftObj - Объект смены для богатого рендеринга (опционально)
     */
    function showOverlayBox(text, shiftObj = null) {
        if (overlayBox) {
            overlayBox.remove();
        }

        const isDark = isDarkMode();

        overlayBox = document.createElement('div');
        overlayBox.className = isDark ? 'shift-modal dark-theme' : 'shift-modal';

        overlayBox.style.cssText = `
            position: fixed !important;
            top: 0 !important;
            left: 0 !important;
            width: 100vw !important;
            height: 100vh !important;
            z-index: 999999 !important;
            background: rgba(0, 0, 0, 0.8) !important;
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
            opacity: 1 !important;
            visibility: visible !important;
            pointer-events: auto !important;
        `;

        const modalContent = document.createElement('div');
        modalContent.className = 'shift-modal-content';

        modalContent.style.cssText = `
            background: ${isDark ? '#1a202c' : '#ffffff'} !important;
            color: ${isDark ? '#f7fafc' : '#1a202c'} !important;
            padding: 20px !important;
            border-radius: 12px !important;
            max-width: 600px !important;
            max-height: 80vh !important;
            overflow-y: auto !important;
            box-shadow: 0 20px 40px rgba(0,0,0,0.3) !important;
            opacity: 1 !important;
            transform: none !important;
            visibility: visible !important;
            pointer-events: auto !important;
            position: relative !important;
            z-index: 1 !important;
        `;

        const header = document.createElement('div');
        header.className = 'shift-modal-header';

        const title = document.createElement('h2');
        title.className = 'shift-modal-title';
        title.innerHTML = '📋 Текущая смена';

        const closeBtn = document.createElement('button');
        closeBtn.className = 'shift-modal-close';
        closeBtn.innerHTML = '✕';
        closeBtn.setAttribute('aria-label', 'Закрыть модальное окно');
        closeBtn.onclick = () => overlayBox.remove();

        const handleKeydown = (e) => {
            if (e.key === 'Escape') {
                overlayBox.remove();
                document.removeEventListener('keydown', handleKeydown);
            }
        };
        document.addEventListener('keydown', handleKeydown);

        overlayBox.onclick = (e) => {
            if (e.target === overlayBox) {
                overlayBox.remove();
                document.removeEventListener('keydown', handleKeydown);
            }
        };

        modalContent.onclick = (e) => e.stopPropagation();

        header.appendChild(title);
        header.appendChild(closeBtn);

        const actions = document.createElement('div');
        actions.className = 'shift-modal-actions';

        const copyBtn = document.createElement('button');
        copyBtn.className = 'shift-modal-copy-btn';
        copyBtn.innerHTML = '📄 Скопировать';
        copyBtn.onclick = async () => {
            try {
                await navigator.clipboard.writeText(text);
                copyBtn.innerHTML = '✅ Скопировано!';
                setTimeout(() => {
                    copyBtn.innerHTML = '📄 Скопировать';
                }, 1500);
            } catch (e) {
                alert('Ошибка копирования');
            }
        };

        actions.appendChild(copyBtn);

        const content = document.createElement('div');
        content.className = 'shift-modal-body';

        // rebuild - перерисовывает тело модала (вызывается после каждого сохранения)
        const rebuild = () => {
            content.innerHTML = '';
            if (shiftObj) {
                renderShiftBody(content, shiftObj, rebuild);
            } else {
                const pre = document.createElement('pre');
                pre.style.cssText = 'margin:0; white-space:pre-wrap; font-family:monospace; font-size:12px;';
                pre.innerHTML = highlightShiftText(text);
                content.appendChild(pre);
                pre.querySelectorAll('.shift-line-entry[data-issue-url]').forEach(lineEl => {
                    const url = lineEl.dataset.issueUrl;
                    lineEl.style.cursor = 'pointer';
                    lineEl.addEventListener('mouseenter', () => {
                        lineEl.style.background = 'rgba(59,130,246,0.12)';
                        showIssuePreview(url, lineEl);
                    });
                    lineEl.addEventListener('mouseleave', () => {
                        lineEl.style.background = '';
                        scheduleHideIssuePreview();
                    });
                });
            }
        };

        rebuild();

        modalContent.appendChild(header);
        modalContent.appendChild(actions);
        modalContent.appendChild(content);
        overlayBox.appendChild(modalContent);
        document.body.appendChild(overlayBox);

        overlayBox.offsetHeight; // force repaint

        // При закрытии overlay - убираем превью
        const origOnClick = overlayBox.onclick;
        overlayBox.onclick = (e) => {
            if (origOnClick) origOnClick(e);
            destroyIssuePreview();
        };
        closeBtn.addEventListener('click', () => destroyIssuePreview(), { once: true });
    }


    let menu; // Ссылка на текущий <название>Menu

    /**
     * Удаляет контекстное меню и все связанные элементы
     */
    function removeMenu() {
        if (menu) { menu.destroy(); menu = null; }
        if (previewBox) { previewBox.remove(); previewBox = null; }
    }

    /**
     * Получает данные текущей смены из localStorage
     * @returns {Object} Объект с данными смены по категориям
     */
    function getStoredShift() {
        return JSON.parse(localStorage.getItem(STORAGE_KEY)) || {
            "В работе": [], "Ожидание ответа от клиента": [], "Решена": [],
            "Новая": [], "Нет трудозатрат": [], "Нет причины обращения": []
        };
    }

    /**
     * Сохраняет данные смены в localStorage
     * @param {Object} data - Объект с данными смены для сохранения
     */
    function saveStorage(data) {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(data));
    }

    /**
     * Определяет категорию по статусу тикета
     * @param {string} status - Статус тикета из Redmine
     * @returns {string|null} Название категории или null если не определена
     */
    function getCategoryByStatus(status) {
        if (status.includes('В процессе') || status.includes('В работе')) return "В работе";
        if (status.includes('Ожидание')) return "Ожидание ответа от клиента";
        if (status.includes('Решена') || status.includes('Закрыта')) return "Решена";
        if (status.includes('Новая')) return "Новая";
        return null;
    }

    /**
     * Получает видимый текст из элемента DOM (без скрытых элементов)
     * @param {Element} el - DOM-элемент
     * @returns {string} Очищенный текст
     */
    function getVisibleText(el) {
        const clone = el.cloneNode(true);
        clone.style.all = 'unset';
        clone.style.position = 'absolute';
        clone.style.left = '-9999px';
        document.body.appendChild(clone);
        const text = clone.innerText.trim();
        document.body.removeChild(clone);
        return text;
    }

    /**
     * Сортирует записи по URL в алфавитном порядке
     * @param {string[]} entries - Массив строк записей
     * @returns {string[]} Отсортированный массив
     */
    function sortCategoryByUrl(entries) {
        return entries.slice().sort((a, b) => a.localeCompare(b));
    }

    /**
     * Форматирует текст смены для отображения и экспорта
     * @param {Object} s - Объект смены с категориями
     * @returns {string} Отформатированный текст смены
     */
    function formatShiftText(s) {
        const sortedWork     = sortCategoryByUrl(s["В работе"] || []);
        const sortedWait     = sortCategoryByUrl(s["Ожидание ответа от клиента"] || []);
        const sortedDone     = sortCategoryByUrl(s["Решена"] || []);
        const sortedNew      = sortCategoryByUrl(s["Новая"] || []);
        const sortedNoTime   = sortCategoryByUrl(s["Нет трудозатрат"] || []);
        const sortedNoReason = sortCategoryByUrl(s["Нет причины обращения"] || []);

        return (
            'Доброе утро! По смене:\n\n' +
            'В работе:\n\n'                       + sortedWork.join('\n')     + '\n\n' +
            'Ожидание ответа от клиента:\n\n'     + sortedWait.join('\n')     + '\n\n' +
            'Решена:\n\n'                         + sortedDone.join('\n')     + '\n\n' +
            'Новая:\n\n'                          + sortedNew.join('\n')      + '\n\n' +
            'Нет трудозатрат:\n\n'                + sortedNoTime.join('\n')   + '\n\n' +
            'Нет причины обращения:\n\n'          + sortedNoReason.join('\n')
        );
    }

    /**
     * Создаёт блок предварительного просмотра текста смены
     * @param {Element} anchorEl    - Элемент-якорь для позиционирования
     * @param {string}  fullText    - Полный текст для отображения
     * @param {string}  highlightLine - Строка для подсветки
     * @param {string}  highlightStyle - Цвет подсветки
     */
    function createPreviewBox(anchorEl, fullText, highlightLine, highlightStyle) {
        if (previewBox) previewBox.remove();
        previewBox = document.createElement('pre');
        previewBox.className = isDarkMode() ? 'ticket-preview dark-theme' : 'ticket-preview light-theme';

        if (!highlightStyle) {
            highlightStyle = isDarkMode() ? '#444b2c' : '#ffeeba';
        }

        const rect = anchorEl.getBoundingClientRect();
        Object.assign(previewBox.style, {
            top:  `${rect.top}px`,
            left: `${rect.right + 10}px`
        });

        const lines = fullText.split('\n').map(l => {
            const isHighlight = l === highlightLine;
            const safeLine = l.trim() === '' ? '&nbsp;' : l;
            return `<div class="${isHighlight ? 'highlight-line' : ''}">${safeLine}</div>`;
        }).join('');

        previewBox.innerHTML = lines;
        document.body.appendChild(previewBox);
    }

    /**
     * Извлекает ID задач из DOM страницы activity
     * @returns {string[]} Массив уникальных ID задач
     */
    /**
     * Возвращает true, если текст заголовка h3 соответствует сегодня или вчера.
     * Redmine показывает: "Сегодня", "Вчера", "13.04.2026", "April 13, 2026" и т.п.
     */
    function isH3TodayOrYesterday(h3) {
        const text = (h3.innerText || h3.textContent || '').trim();

        const today = new Date();
        const yesterday = new Date();
        yesterday.setDate(today.getDate() - 1);

        const sameDay = (a, b) =>
            a.getFullYear() === b.getFullYear() &&
            a.getMonth()    === b.getMonth()    &&
            a.getDate()     === b.getDate();

        // Русские/английские метки
        if (/^сегодня$/i.test(text) || /^today$/i.test(text))     return true;
        if (/^вчера$/i.test(text)   || /^yesterday$/i.test(text)) return true;

        // Формат DD.MM.YYYY - проверяем ПЕРВЫМ, до new Date(),
        // иначе Chrome может неверно распарсить "12.04.2026"
        const dmyMatch = text.match(/^(\d{1,2})\.(\d{1,2})\.(\d{4})$/);
        if (dmyMatch) {
            const d = new Date(+dmyMatch[3], +dmyMatch[2] - 1, +dmyMatch[1]);
            return sameDay(d, today) || sameDay(d, yesterday);
        }

        // Другие форматы (YYYY-MM-DD, "April 13, 2026" и т.п.)
        const parsed = new Date(text);
        if (!isNaN(parsed.getTime())) {
            return sameDay(parsed, today) || sameDay(parsed, yesterday);
        }

        return false;
    }

    async function getIssueIdsFromDOM() {
        let issueIds = [];

        const { activityTodayOnly = true } = await new Promise(resolve =>
            chrome.storage.sync.get(['activityTodayOnly'], resolve)
        );

        const h3s = Array.from(document.querySelectorAll('#activity h3'));
        const relevantH3s = activityTodayOnly
            ? h3s.filter(h3 => isH3TodayOrYesterday(h3))
            : h3s;

        relevantH3s.forEach(h3 => {
            let next = h3.nextElementSibling;
            if (next && next.tagName === 'DL') {
                const links = next.querySelectorAll('dt > a[href*="/issues/"]');
                links.forEach(a => {
                    if (!a.textContent.includes('зависший lotxlocxid.PENDINGMOVEIN')) {
                        const match = a.href.match(/\/issues\/(\d+)/);
                        if (match) issueIds.push(match[1]);
                    }
                });

                const timeEntryLinks = next.querySelectorAll('dt > a[href*="issue_id="]');
                timeEntryLinks.forEach(a => {
                    if (!a.textContent.includes('зависший lotxlocxid.PENDINGMOVEIN')) {
                        const match = a.href.match(/issue_id=(\d+)/);
                        if (match) issueIds.push(match[1]);
                    }
                });

                const generalIssueLinks = next.querySelectorAll('dt a[href*="/issues/"]');
                generalIssueLinks.forEach(a => {
                    if (!a.textContent.includes('зависший lotxlocxid.PENDINGMOVEIN')) {
                        const match = a.href.match(/\/issues\/(\d+)/);
                        if (match) issueIds.push(match[1]);
                    }
                });
            }
        });

        return [...new Set(issueIds)];
    }

    /**
     * Создаёт и показывает прогресс-бар в модальном окне
     * @param {number} total - Общее количество элементов
     * @returns {Object} Контроллер прогресс-бара { update, close }
     */
    function createProgressBar(total) {
        const isDark = isDarkMode();

        // ── Инжектим CSS один раз ────────────────────────────────────────────
        if (!document.getElementById('ltm-pb-styles')) {
            const style = document.createElement('style');
            style.id = 'ltm-pb-styles';
            style.textContent = `
                @keyframes ltm-pb-shimmer {
                    0%   { transform: translateX(-100%) skewX(-15deg); }
                    100% { transform: translateX(250%)  skewX(-15deg); }
                }
                @keyframes ltm-pb-pulse {
                    0%, 100% { opacity: 1; }
                    50%       { opacity: 0.6; }
                }
                @keyframes ltm-pb-fadein {
                    from { opacity: 0; transform: scale(0.92) translateY(12px); }
                    to   { opacity: 1; transform: scale(1)    translateY(0);    }
                }
                @keyframes ltm-pb-spin {
                    to { transform: rotate(360deg); }
                }
                .ltm-pb-overlay {
                    position: fixed !important;
                    inset: 0 !important;
                    z-index: 999999 !important;
                    background: rgba(0,0,0,0.55) !important;
                    backdrop-filter: blur(4px) !important;
                    display: flex !important;
                    align-items: center !important;
                    justify-content: center !important;
                }
                .ltm-pb-card {
                    animation: ltm-pb-fadein 0.28s cubic-bezier(.22,.68,0,1.2) both !important;
                    min-width: 420px !important;
                    max-width: 520px !important;
                    padding: 32px 36px !important;
                    border-radius: 18px !important;
                    text-align: center !important;
                    font-family: system-ui, -apple-system, sans-serif !important;
                }
                .ltm-pb-spinner {
                    display: inline-block !important;
                    width: 28px !important; height: 28px !important;
                    border-radius: 50% !important;
                    border: 3px solid transparent !important;
                    border-top-color: #63e6be !important;
                    border-right-color: #74c0fc !important;
                    animation: ltm-pb-spin 0.75s linear infinite !important;
                    vertical-align: middle !important;
                    margin-right: 10px !important;
                }
                .ltm-pb-title {
                    margin: 0 0 24px !important;
                    font-size: 17px !important;
                    font-weight: 600 !important;
                    display: flex !important;
                    align-items: center !important;
                    justify-content: center !important;
                    gap: 8px !important;
                }
                .ltm-pb-track {
                    width: 100% !important;
                    height: 10px !important;
                    border-radius: 999px !important;
                    overflow: hidden !important;
                    position: relative !important;
                    margin-bottom: 14px !important;
                }
                .ltm-pb-fill {
                    height: 100% !important;
                    border-radius: 999px !important;
                    background: linear-gradient(90deg, #63e6be, #74c0fc, #a9e34b) !important;
                    background-size: 200% 100% !important;
                    transition: width 0.35s cubic-bezier(.4,0,.2,1) !important;
                    position: relative !important;
                    overflow: hidden !important;
                    min-width: 0% !important;
                }
                .ltm-pb-fill::after {
                    content: '' !important;
                    position: absolute !important;
                    inset: 0 !important;
                    width: 40% !important;
                    background: rgba(255,255,255,0.35) !important;
                    animation: ltm-pb-shimmer 1.6s ease-in-out infinite !important;
                }
                .ltm-pb-row {
                    display: flex !important;
                    justify-content: space-between !important;
                    align-items: center !important;
                    font-size: 13px !important;
                    margin-bottom: 6px !important;
                }
                .ltm-pb-percent {
                    font-size: 28px !important;
                    font-weight: 700 !important;
                    letter-spacing: -1px !important;
                    line-height: 1 !important;
                    margin-bottom: 18px !important;
                    background: linear-gradient(135deg, #63e6be, #74c0fc) !important;
                    -webkit-background-clip: text !important;
                    -webkit-text-fill-color: transparent !important;
                    background-clip: text !important;
                }
                .ltm-pb-status {
                    font-size: 12px !important;
                    opacity: 0.65 !important;
                    margin-top: 10px !important;
                    min-height: 16px !important;
                    transition: opacity 0.2s !important;
                    white-space: nowrap !important;
                    overflow: hidden !important;
                    text-overflow: ellipsis !important;
                }
            `;
            document.head.appendChild(style);
        }

        // ── Разметка ─────────────────────────────────────────────────────────
        const overlay = document.createElement('div');
        overlay.className = 'ltm-pb-overlay';

        const card = document.createElement('div');
        card.className = 'ltm-pb-card';
        card.style.cssText = isDark
            ? 'background:#1a1f2e !important; color:#e2e8f0 !important; box-shadow:0 24px 60px rgba(0,0,0,0.6),0 0 0 1px rgba(255,255,255,0.06) !important;'
            : 'background:#ffffff !important; color:#1e293b !important; box-shadow:0 24px 60px rgba(0,0,0,0.18),0 0 0 1px rgba(0,0,0,0.06) !important;';

        const title = document.createElement('div');
        title.className = 'ltm-pb-title';
        title.innerHTML = '<span class="ltm-pb-spinner"></span> Обработка тикетов';

        const percentEl = document.createElement('div');
        percentEl.className = 'ltm-pb-percent';
        percentEl.textContent = '0%';

        const track = document.createElement('div');
        track.className = 'ltm-pb-track';
        track.style.background = isDark ? '#2d3748' : '#e2e8f0';

        const fill = document.createElement('div');
        fill.className = 'ltm-pb-fill';
        fill.style.width = '0%';

        const row = document.createElement('div');
        row.className = 'ltm-pb-row';

        const countEl = document.createElement('span');
        countEl.textContent = `0 из ${total}`;

        const etaEl = document.createElement('span');
        etaEl.style.opacity = '0.55';
        etaEl.textContent = '';

        const statusEl = document.createElement('div');
        statusEl.className = 'ltm-pb-status';
        statusEl.textContent = 'Подготовка...';

        row.appendChild(countEl);
        row.appendChild(etaEl);
        track.appendChild(fill);
        card.appendChild(title);
        card.appendChild(percentEl);
        card.appendChild(track);
        card.appendChild(row);
        card.appendChild(statusEl);
        overlay.appendChild(card);
        document.body.appendChild(overlay);

        // ── Замер времени для ETA ─────────────────────────────────────────────
        const startTime = Date.now();

        return {
            update(current, status) {
                const percent = total > 0 ? Math.round((current / total) * 100) : 0;
                fill.style.width = percent + '%';
                percentEl.textContent = percent + '%';
                countEl.textContent = `${current} из ${total}`;
                statusEl.textContent = status || 'Обработка...';

                // ETA
                if (current > 0 && current < total) {
                    const elapsed = (Date.now() - startTime) / 1000;
                    const remaining = Math.round((elapsed / current) * (total - current));
                    etaEl.textContent = remaining < 60
                        ? `~${remaining} сек`
                        : `~${Math.ceil(remaining / 60)} мин`;
                } else {
                    etaEl.textContent = '';
                }

                // Финальное состояние
                if (current >= total) {
                    fill.style.background = 'linear-gradient(90deg, #63e6be, #a9e34b) !important';
                    percentEl.textContent = '✓';
                    statusEl.textContent = 'Готово!';
                    etaEl.textContent = '';
                }
            },
            close() {
                overlay.style.transition = 'opacity 0.25s ease';
                overlay.style.opacity = '0';
                setTimeout(() => overlay.remove(), 260);
            }
        };
    }

    /**
     * Получает данные задач из Redmine и распределяет по категориям смены
     * @param {string[]} issueIds  - Массив ID задач
     * @param {Object}   shiftBase - Базовый объект смены с категориями
     * @returns {Promise<Object>}   Обновлённый объект смены
     */
    async function fetchIssuesToShift(issueIds, shiftBase) {
        const progressBar = createProgressBar(issueIds.length);
        progressBar.update(0, 'Подготовка данных...');

        try {
            const newShift = JSON.parse(JSON.stringify(shiftBase));
            ["В работе", "Ожидание ответа от клиента", "Решена", "Новая",
             "Нет трудозатрат", "Нет причины обращения"].forEach(k => {
                if (!newShift[k]) newShift[k] = [];
            });

            const existingIds = new Set();
            Object.values(newShift).forEach(arr => {
                arr.forEach(line => {
                    const match = line.match(/\/issues\/(\d+)/);
                    if (match) existingIds.add(match[1]);
                });
            });

            let processed = 0, added = 0, skipped = 0;

            for (const id of issueIds) {
                try {
                    processed++;
                    progressBar.update(processed, `Обработка тикета ${id}...`);

                    if (existingIds.has(id)) { skipped++; continue; }

                    const res = await fetch(`/issues/${id}`);
                    if (!res.ok) { skipped++; continue; }

                    const html = await res.text();
                    const doc  = new DOMParser().parseFromString(html, 'text/html');

                    const statusElement = [...doc.querySelectorAll('#content .status.attribute .value')].pop();
                    if (!statusElement) { skipped++; continue; }

                    const status   = statusElement.innerText.trim();
                    const category = getCategoryByStatus(status);

                    const clientElement = doc.querySelector('span.current-project');
                    const clientName    = getVisibleText(clientElement);

                    const subjectElement = doc.querySelector('.subject h3');
                    const cloned = subjectElement.cloneNode(true);
                    cloned.querySelectorAll('span').forEach(span => span.remove());
                    const subject = cloned.textContent.trim();

                    const url  = location.origin + `/issues/${id}`;
                    const line = `${url} \u2013 ${clientName}: ${subject}`;

                    const bannedPatterns = [
                        'НS','HS','Alert','alert','healthscript',
                        'Lamoda','lamoda','регламентные работы',
                        'Регламентные работы','зависший lotxlocxid.PENDINGMOVEIN'
                    ];
                    if (bannedPatterns.some(p => line.includes(p))) { skipped++; continue; }

                    const reasonElement = doc.querySelector('.cf_109.attribute .value');
                    const hasReason = reasonElement && reasonElement.textContent.trim() !== '';
                    const hasTime   = !!doc.querySelector('#tab-time_entries');

                    if (!hasReason) {
                        newShift["Нет причины обращения"].push(line); added++;
                    } else if (!hasTime) {
                        newShift["Нет трудозатрат"].push(line); added++;
                    } else if (category) {
                        newShift[category].push(line); added++;
                    } else {
                        skipped++;
                    }
                } catch (err) {
                    skipped++;
                }

                if (processed < issueIds.length) {
                    await sleep(3000);
                }
            }

            progressBar.update(processed, `Завершено! Добавлено: ${added}, Пропущено: ${skipped}`);
            setTimeout(() => progressBar.close(), 2000);
            return newShift;

        } catch (error) {
            progressBar.update(issueIds.length, 'Ошибка при обработке!');
            setTimeout(() => progressBar.close(), 3000);
            throw error;
        }
    }


    // =========================================================================
    // Context Menu  -  использует <название>Menu / <название>Submenu из src/shared/menu.js
    // =========================================================================

    /**
     * Создаёт контекстное меню при правом клике
     * @param {number} x - Координата X
     * @param {number} y - Координата Y
     */
    function createContextMenu(x, y) {
        removeMenu();

        menu = new <название>Menu({ dark: isDarkMode() });

        // ── Тёмный режим ──────────────────────────────────────────────────────
        menu.addToggle('\uD83C\uDF19 Тёмный режим', isDarkMode(), (checked) => {
            toggleDarkMode(checked);
            menu.setDark(checked);
            if (activeSub) activeSub.setDark(checked);
        });

        menu.addSeparator();

        // ── Смена (с подменю) ─────────────────────────────────────────────────
        let activeSub = null;
        let activeBtn = null; // кнопка-владелец текущего подменю

        const scheduleSubHide = () => activeSub?.scheduleHide();
        const cancelSubHide   = () => activeSub?.cancelHide();

        menu.addButton('\uD83D\uDC77\uFE0F Смена', null, {
            hasSubmenu: true,

            onHover: (btn) => {
                if (activeSub?.element) {
                    if (activeBtn === btn) { cancelSubHide(); return; }
                    activeSub.destroy();
                    activeSub = null;
                }
                activeBtn = btn;

                const current = getStoredShift();
                activeSub = new <название>Submenu({ dark: isDarkMode() });

                // Просмотр смены
                activeSub.addButton('\uD83D\uDC41\uFE0F Просмотр смены', () => {
                    if (previewBox) { previewBox.remove(); previewBox = null; }
                    activeSub?.destroy(); activeSub = null;
                    removeMenu();
                    showOverlayBox(formatShiftText(current), current);
                }, {
                    onHoverLeave: () => { if (previewBox) { previewBox.remove(); previewBox = null; } }
                });

                // Экспорт смены
                activeSub.addButton('\uD83D\uDCC4 Экспорт смены', () => {
                    const text    = formatShiftText(current);
                    const blob    = new Blob([text], { type: 'text/plain' });
                    const urlBlob = URL.createObjectURL(blob);
                    const a       = document.createElement('a');
                    a.href        = urlBlob;
                    a.download    = '\u0441\u043c\u0435\u043d\u0430_' + new Date().toISOString().slice(0, 10) + '.txt';
                    a.click();
                    URL.revokeObjectURL(urlBlob);
                    if (previewBox) { previewBox.remove(); previewBox = null; }
                    activeSub?.destroy(); activeSub = null;
                    removeMenu();
                }, {
                    onHoverLeave: () => { if (previewBox) { previewBox.remove(); previewBox = null; } }
                });

                // Очистить смену
                activeSub.addButton('\uD83D\uDDD1\uFE0F Очистить смену', () => {
                    if (previewBox) { previewBox.remove(); previewBox = null; }
                    activeSub?.destroy(); activeSub = null;
                    removeMenu();
                    clearStorage();
                }, {
                    onHoverLeave: () => { if (previewBox) { previewBox.remove(); previewBox = null; } }
                });

                activeSub.addSeparator();

                // Добавить все задачи (с синхронизацией)
                activeSub.addButton('\uD83D\uDD01 Добавить все задачи за смену', async () => {
                    if (previewBox) { previewBox.remove(); previewBox = null; }
                    activeSub?.destroy(); activeSub = null;
                    removeMenu();

                    const syncProgressBar = createProgressBar(100);
                    try {
                        await syncAllStatuses?.((progress, message) => {
                            syncProgressBar.update(progress / 2, message);
                        });
                        syncProgressBar.update(50, 'Синхронизация завершена, обработка задач...');
                        const shift   = getStoredShift();
                        const ids     = await getIssueIdsFromDOM();
                        if (!ids.length) {
                            syncProgressBar.close();
                            showToast('Нет подходящих задач', 'error');
                            return;
                        }
                        const updated = await fetchIssuesToShift(ids, shift);
                        saveStorage(updated);
                        syncProgressBar.update(100, 'Все задачи добавлены в смену!');
                        setTimeout(() => {
                            syncProgressBar.close();
                            alert('Все задачи добавлены в смену.');
                        }, 1000);
                    } catch (err) {
                        console.error('Sync error:', err);
                        syncProgressBar.update(100, 'Ошибка синхронизации!');
                        setTimeout(() => {
                            syncProgressBar.close();
                            alert('Ошибка при синхронизации тикетов.');
                        }, 1000);
                    }
                }, {
                    onHoverLeave: () => { if (previewBox) { previewBox.remove(); previewBox = null; } }
                });

                // Добавить все задачи (без синхронизации)
                activeSub.addButton('\uD83D\uDD01 Добавить все задачи (без синх.)', async () => {
                    if (previewBox) { previewBox.remove(); previewBox = null; }
                    activeSub?.destroy(); activeSub = null;
                    removeMenu();

                    const shift   = getStoredShift();
                    const ids     = await getIssueIdsFromDOM();
                    if (!ids.length) {
                        showToast('Нет подходящих задач', 'error');
                        return;
                    }
                    const updated = await fetchIssuesToShift(ids, shift);
                    saveStorage(updated);
                    alert('Все задачи добавлены в смену.');
                }, {
                    onHoverLeave: () => { if (previewBox) { previewBox.remove(); previewBox = null; } }
                });

                // Hover-safe управление видимостью подменю
                activeSub.element.addEventListener('mouseenter', cancelSubHide);
                activeSub.element.addEventListener('mouseleave', scheduleSubHide);

                activeSub.showAt(btn);
            },

            onHoverLeave: () => scheduleSubHide()
        });

        menu.show(x, y);
    }

    // На страницах конкретного тикета используется issues-menu.js
    if (!/^\/issues\/\d+/.test(location.pathname)) {
        chrome.storage.sync.get(['ctxMenuActivity'], ({ ctxMenuActivity = true }) => {
            if (!ctxMenuActivity) return;
            window.addEventListener('contextmenu', (e) => {
                e.preventDefault();
                createContextMenu(e.clientX, e.clientY);
            });
        });
    }

    window.addEventListener('storage', (e) => {
        if (e.key === STORAGE_KEY) {
            // Silent handling for production
        }
    });

})();
