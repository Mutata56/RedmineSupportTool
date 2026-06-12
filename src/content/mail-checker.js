// src/content/mail-checker.js
// Яндекс Почта (mail.360.yandex.ru) - детектор писем о расхождениях WMS
// Проект определяется двумя способами:
//   1. По aria-label отправителя (SQL Alerts - Верный ..., DEPO.LV)
    //   2. По полю Server: в теле письма (для <email>)

(function () {
    'use strict';

    const TRIGGER_TEXT    = 'Расхождения в пунктах';
    const REDMINE_NEW_URL = '<ссылка>';
    const BTN_ID          = 'ltm-create-issue-btn';
    const EVA_SENDER      = '<email>';

    // ── 1. Маппинг по aria-label отправителя (дефолты, могут быть переопределены из storage) ──
    let SENDER_PROJECT_MAP = [
        { match: '<sender>', id: <project_id>,  label: '<project_name>' },
        { match: '<sender>', id: <project_id>,  label: '<project_name>' },
        { match: '<sender>', id: <project_id>,  label: '<project_name>' },
        { match: '<sender>', id: <project_id>,  label: '<project_name>' },
        { match: '<sender>', id: <project_id>,  label: '<project_name>' },
        { match: '<sender>', id: <project_id>,  label: '<project_name>' },
    ];

    // ── 2. Маппинг по Server: в теле письма (дефолты) ────────────────────────
    let SERVER_PROJECT_MAP = [
        { match: '<server>',  id: <project_id>,  label: '<project_name>' },
        { match: '<server>',  id: <project_id>,  label: '<project_name>' },
        { match: '<server>',  id: <project_id>,  label: '<project_name>' },
        { match: '<server>',  id: <project_id>,  label: '<project_name>' },
        { match: '<server>',  id: <project_id>,  label: '<project_name>' },
        { match: '<server>',  id: <project_id>,  label: '<project_name>' },
    ];

    // ── Получить email отправителя ───────────────────────────────────────────
    function getSenderEmail() {
        // 1. mailto-ссылка
        const mailtoLink = document.querySelector('a[href^="mailto:"][class*="Sender"], a[href^="mailto:"][class*="sender"]');
        if (mailtoLink) return mailtoLink.href.replace('mailto:', '').toLowerCase();

        // 2. span с data-testid="sender-email" (Yandex Mail, реальный DOM)
        const emailSpan = document.querySelector('[data-testid="sender-email"]') ||
                          document.querySelector('[class*="Sender__email"]');
        if (emailSpan) {
            const txt = (emailSpan.textContent || emailSpan.getAttribute('title') || '').trim();
            if (txt.includes('@')) return txt.toLowerCase();
        }

        // 3. aria-label на обёртке отправителя (содержит "ИМЯ, email@domain.ru, ...")
        const senderWrapper = document.querySelector('[data-testid="sender"]');
        const wrapperLabel  = senderWrapper?.getAttribute('aria-label') || '';
        const emailFromWrapper = wrapperLabel.match(/[\w.+-]+@[\w.-]+\.\w+/);
        if (emailFromWrapper) return emailFromWrapper[0].toLowerCase();

        // 4. aria-label на кнопке имени отправителя
        const senderBtn =
            document.querySelector('[class*="SenderName__sender"]') ||
            document.querySelector('[class*="Sender__senderName"]');
        const btnLabel = senderBtn?.getAttribute('aria-label') || '';
        const emailFromBtn = btnLabel.match(/[\w.+-]+@[\w.-]+\.\w+/);
        return emailFromBtn ? emailFromBtn[0].toLowerCase() : '';
    }

    // ── Получить aria-label кнопки отправителя ───────────────────────────────
    function getSenderLabel() {
        const btn =
            document.querySelector('[class*="SenderName__sender"]') ||
            document.querySelector('[class*="Sender__senderName"]') ||
            document.querySelector('[aria-label*="SQL Alerts"]')    ||
            document.querySelector('[aria-label*="DEPO"]');
        return btn?.getAttribute('aria-label') || btn?.innerText || '';
    }

    // ── Извлечь значение Server: из текста письма ────────────────────────────
    function extractServer(text) {
        // Ищем "Server: WIN-ISKR29NVRG8" или "Server: LVIMWMS02" и т.п.
        const m = text.match(/Server:\s*([A-Z0-9_-]+)/i);
        return m ? m[1].trim().toUpperCase() : '';
    }

    // ── Определить проект по Server: (для Евы) ───────────────────────────────
    function detectProjectByServer(serverName) {
        for (const entry of SERVER_PROJECT_MAP) {
            if (serverName.startsWith(entry.match.toUpperCase())) {
                return entry;
            }
        }
        return null;
    }

    // ── Определить проект по aria-label отправителя ──────────────────────────
    function detectProjectBySender(senderLabel) {
        const lower = senderLabel.toLowerCase();
        for (const entry of SENDER_PROJECT_MAP) {
            if (lower.includes(entry.match.toLowerCase())) {
                return entry;
            }
        }
        return null;
    }

    // ── Найти тело текущего открытого письма ────────────────────────────────
    function getMessageBody() {
        return (
            document.querySelector('.react-message-wrapper__body') ||
            document.querySelector('[class*="MessageBody_body"]')   ||
            document.querySelector('[class*="MessageViewerLayout"]')
        );
    }

    // ── Главная логика: проверить письмо и определить проект ─────────────────
    function resolveProject(bodyText) {
        const senderEmail = getSenderEmail();
        const senderLabel = getSenderLabel();

        // Если отправитель - Ева, парсим Server: из тела
        if (senderEmail.includes('eva.ua') || senderLabel.toLowerCase().includes('eva')) {
            const server = extractServer(bodyText);
            return detectProjectByServer(server);
        }

        // Иначе - по aria-label (SQL Alerts / DEPO)
        return detectProjectBySender(senderLabel);
    }

    // ── Проверить письмо и показать / скрыть кнопку ─────────────────────────
    function checkAndInject() {
        const body = getMessageBody();
        const existingBtn = document.getElementById(BTN_ID);

        if (!body) {
            existingBtn?.remove();
            return;
        }

        const text = body.innerText || body.textContent || '';
        if (!text.includes(TRIGGER_TEXT)) {
            existingBtn?.remove();
            return;
        }

        const project = resolveProject(text);

        if (existingBtn) {
            existingBtn.dataset.projectId = project?.id ?? '';
            updateButtonLabel(existingBtn, project);
            return;
        }

        injectButton(project);
    }

    // ── Текст кнопки ─────────────────────────────────────────────────────────
    function updateButtonLabel(btn, project) {
        btn.textContent = project
            ? `🔴 Создать заявку → ${project.label}`
            : '🔴 Создать заявку';
    }

    // ── URL с предзаполненными полями Redmine ────────────────────────────────
    function buildUrl(project) {
        const params = new URLSearchParams();
        if (project) params.set('issue[project_id]', project.id);
            params.set('issue[tracker_id]', '<tracker_id>');                      // Алерт
        params.set('issue[is_private]',                   '1');                       // Частная
        params.set('issue[subject]',                      'HealthScript Job Notifier');
    params.set('issue[custom_field_values][<field_id>]', 'Превентивные мероприятия');
        return `${REDMINE_NEW_URL}?${params.toString()}`;
    }

    // ── Вставить кнопку ─────────────────────────────────────────────────────
    function injectButton(project) {
        const btn = document.createElement('button');
        btn.id = BTN_ID;
        btn.dataset.projectId = project?.id ?? '';
        updateButtonLabel(btn, project);
        btn.title = 'Открыть форму создания заявки в Redmine';

        Object.assign(btn.style, {
            position:     'fixed',
            bottom:       '24px',
            right:        '24px',
            zIndex:       '99999',
            padding:      '10px 20px',
            background:   '#dc2626',
            color:        '#fff',
            border:       'none',
            borderRadius: '8px',
            fontSize:     '13px',
            fontWeight:   '600',
            cursor:       'pointer',
            boxShadow:    '0 4px 12px rgba(220,38,38,0.4)',
            transition:   'transform 0.15s ease, box-shadow 0.15s ease',
            fontFamily:   'system-ui, sans-serif',
            lineHeight:   '1.4',
            maxWidth:     '340px',
            textAlign:    'center',
        });

        btn.addEventListener('mouseenter', () => {
            btn.style.transform = 'translateY(-2px)';
            btn.style.boxShadow = '0 6px 16px rgba(220,38,38,0.55)';
        });
        btn.addEventListener('mouseleave', () => {
            btn.style.transform = '';
            btn.style.boxShadow = '0 4px 12px rgba(220,38,38,0.4)';
        });

        btn.addEventListener('click', () => {
            const pid  = btn.dataset.projectId;
            const proj = pid ? { id: pid } : null;
            window.open(buildUrl(proj), '_blank');
        });

        document.body.appendChild(btn);
    }

    // ── MutationObserver - SPA-навигация и динамическая подгрузка ────────────
    let debounceTimer = null;
    const observer = new MutationObserver(() => {
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(checkAndInject, 150);
    });

    // Читаем все настройки одним запросом при старте
    chrome.storage.sync.get(['mailCreateBtn', 'senderProjectMap', 'serverProjectMap'], (result) => {
        const enabled = result.mailCreateBtn !== undefined ? result.mailCreateBtn : true;
        if (!enabled) return;

        // Переопределяем маппинги если пользователь их настроил
        if (result.senderProjectMap && result.senderProjectMap.length > 0) {
            SENDER_PROJECT_MAP = result.senderProjectMap;
        }
        if (result.serverProjectMap && result.serverProjectMap.length > 0) {
            SERVER_PROJECT_MAP = result.serverProjectMap;
        }

        observer.observe(document.body, { childList: true, subtree: true });
        checkAndInject();
    });
})();
