// content-loader.js
console.log("Content Loader init");

const MODERN_STYLE_ID = 'ltm-modern-style-link';
const ISSUES_STYLE_ID = 'ltm-issues-style-link';

let currentState = {
    style: 'legacy',
    darkMode: false
};

// === ФУНКЦИЯ: Поиск старых задач (Stale Issues) ===
function highlightStaleIssues() {
    if (currentState.style !== 'modern') return;

    const rows = document.querySelectorAll('table.list.issues tbody tr.issue');
    const now = new Date();
    const HOURS_48 = 48 * 60 * 60 * 1000;
    const dateRegex = /(\d{2})\.(\d{2})\.(\d{4}).*?(\d{2}):(\d{2})/;

    let count = 0;

    rows.forEach(row => {
        const dateCell = row.querySelector('td.updated_on') || row.querySelector('td.created_on');

        if (dateCell) {
            const existingFlag = dateCell.querySelector('.ltm-stale-flag');
            if (existingFlag) existingFlag.remove();

            const dateText = dateCell.innerText.trim();
            const parts = dateText.match(dateRegex);

            if (parts) {
                const issueDate = new Date(parts[3], parts[2] - 1, parts[1], parts[4], parts[5]);
                const diff = now - issueDate;

                if (diff > HOURS_48) {
                    const flag = document.createElement('span');
                    flag.className = 'ltm-stale-flag';
                    flag.title = 'Обновлено более 48 часов назад';
                    flag.textContent = '🚩';

                    dateCell.appendChild(flag);
                    dateCell.classList.add('ltm-stale-date');
                    count++;
                }
            }
        }
    });
}

// === ФУНКЦИЯ: Внедрение кнопок копирования кода ===
function injectCopyButtons() {
    const blocks = document.querySelectorAll('pre');

    blocks.forEach(pre => {
        // Не добавлять дважды
        if (pre.parentElement && pre.parentElement.classList.contains('ltm-code-wrapper')) return;

        // Оборачиваем pre в div с position:relative -
        // это надёжнее чем position:relative на самом pre (он может иметь overflow:auto)
        const wrapper = document.createElement('div');
        wrapper.className = 'ltm-code-wrapper';
        wrapper.style.cssText = 'position:relative !important; display:block;';

        pre.parentNode.insertBefore(wrapper, pre);
        wrapper.appendChild(pre);

        const copyBtn = document.createElement('button');
        copyBtn.className = 'ltm-copy-btn';
        copyBtn.innerHTML = '📋';
        copyBtn.title = 'Скопировать код';

        copyBtn.addEventListener('click', (e) => {
            e.preventDefault();
            const codeElement = pre.querySelector('code') || pre;
            const text = codeElement.innerText;

            navigator.clipboard.writeText(text).then(() => {
                copyBtn.innerHTML = '✅';
                setTimeout(() => { copyBtn.innerHTML = '📋'; }, 2000);
            });
        });

        // Кнопка идёт в wrapper, а не внутрь pre
        wrapper.appendChild(copyBtn);
    });
}

// === ФУНКЦИЯ: Split-редактор с использованием встроенного Preview Redmine ===
function initSplitEditor() {
    if (currentState.style !== 'modern') return;

    const textareas = document.querySelectorAll('textarea.wiki-edit');

    textareas.forEach(textarea => {
        const editor = textarea.closest('.jstEditor');
        const preview = editor?.parentElement?.querySelector('.wiki-preview');
        const previewTab = editor?.parentElement?.querySelector('.tab-preview');

        if (!editor || !preview || editor.parentElement.classList.contains('ltm-split-container')) return;

        // 1. Создаем контейнер-обертку для нижней части
        const container = document.createElement('div');
        container.className = 'ltm-split-container';

        // 2. Перестраиваем DOM: вставляем контейнер ПОСЛЕ панели инструментов
        // Оставляем кнопки сверху, а textarea и preview кладем в ряд
        editor.parentNode.insertBefore(container, editor.nextSibling);
        container.appendChild(textarea);
        container.appendChild(preview);

        // Показываем превью
        preview.classList.remove('hidden');
        preview.style.display = 'block';
        textarea.style.display = 'block';

        let debounceTimer;
        let abortController;

        textarea.addEventListener('input', () => {
            clearTimeout(debounceTimer);
            abortController?.abort();
            preview.style.opacity = '0.6';

            debounceTimer = setTimeout(() => {
                const previewUrl = previewTab?.dataset?.url;
                if (!previewUrl) return;

                const token =
                    document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') ||
                    document.querySelector('input[name="authenticity_token"]')?.value ||
                    '';

                const body = new URLSearchParams({ text: textarea.value });
                if (token) body.append('authenticity_token', token);

                abortController = new AbortController();

                fetch(previewUrl, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                    body: body.toString(),
                    signal: abortController.signal
                })
                .then(r => r.text())
                .then(html => {
                    preview.innerHTML = html;
                    preview.style.opacity = '1';
                })
                .catch(err => {
                    if (err.name !== 'AbortError') preview.style.opacity = '1';
                });
            }, 800);
        });
    });
}

// === MAIN APPLY FUNCTION ===
// === MAIN APPLY FUNCTION ===
function applySettings(style, isDark) {
    currentState.style = style;
    currentState.darkMode = isDark;

    const html = document.documentElement;
    const existingLink = document.getElementById(MODERN_STYLE_ID);
    const existingIssuesLink = document.getElementById(ISSUES_STYLE_ID);

    // 1. LEGACY
    if (style === 'legacy') {
        html.classList.remove('ltm-modern-ui', 'ltm-dark-mode');
        if (existingLink) existingLink.remove();
        if (existingIssuesLink) existingIssuesLink.remove();
        return;
    }

    // 2. MODERN
    if (style === 'modern') {
        html.classList.add('ltm-modern-ui');

        if (!existingLink) {
            const link = document.createElement('link');
            link.id = MODERN_STYLE_ID;
            link.rel = 'stylesheet';
            link.href = chrome.runtime.getURL('assets/styles/modern.css');
            document.head.appendChild(link);
        }

        // КОРРЕКТИРОВКА: Проверяем и Wiki, и Задачи
        const isTargetPage = window.location.pathname.includes('/issues/') ||
                             window.location.pathname.includes('/wiki/');

        if (isTargetPage) {
            if (!existingIssuesLink) {
                const link = document.createElement('link');
                link.id = ISSUES_STYLE_ID;
                link.rel = 'stylesheet';
                link.href = chrome.runtime.getURL('assets/styles/issues.css');
                document.head.appendChild(link);
            }
            // Внедряем кнопки копирования и тулбары
            setTimeout(() => {
                injectCopyButtons();
                initSplitEditor();
                injectSqlToolbarButtons();
            }, 600);
        }

        if (isDark) html.classList.add('ltm-dark-mode');
        else html.classList.remove('ltm-dark-mode');

        setTimeout(highlightStaleIssues, 500);
    }
}

// Инициализация
chrome.storage.sync.get(['darkMode', 'uiStyle'], (res) => {
    applySettings(res.uiStyle || 'legacy', res.darkMode || false);
});

chrome.runtime.onMessage.addListener((req) => {
    if (req.action === 'updateSettings' && req.settings) {
        const newStyle = req.settings.uiStyle !== undefined ? req.settings.uiStyle : currentState.style;
        const newDarkMode = req.settings.darkMode !== undefined ? req.settings.darkMode : currentState.darkMode;
        applySettings(newStyle, newDarkMode);
    }
});

const observer = new MutationObserver(() => {
    if (currentState.style === 'modern') {
        highlightStaleIssues();
        const isTargetPage = window.location.pathname.includes('/issues/') ||
                             window.location.pathname.includes('/wiki/');
        if (isTargetPage) {
            injectCopyButtons();
            initSplitEditor();
        }
    }
});

const contentDiv = document.getElementById('content');
if (contentDiv) {
    observer.observe(contentDiv, { childList: true, subtree: true });
}

// === Вспомогательная функция для вставки текста в позицию курсора ===
function insertAtCursor(textarea, text) {
    const start = textarea.selectionStart;
    const end = textarea.selectionEnd;
    const currentVal = textarea.value;

    textarea.value = currentVal.substring(0, start) + text + currentVal.substring(end);
    textarea.focus();
    textarea.selectionStart = textarea.selectionEnd = start + text.length;

    // Триггерим обновление предпросмотра
    textarea.dispatchEvent(new Event('input', { bubbles: true }));
}

// === Функция получения только текста из буфера ===
async function getClipboardText() {
    try {
        const items = await navigator.clipboard.read();
        for (const item of items) {
            if (item.types.includes('text/plain')) {
                const blob = await item.getType('text/plain');
                return await blob.text();
            }
        }
    } catch (err) {
        console.error('Ошибка доступа к буферу:', err);
    }
    return null;
}

// === Добавление кнопок в тулбар ===
function injectSqlToolbarButtons() {
    const toolbars = document.querySelectorAll('.jstElements');

    toolbars.forEach(toolbar => {
        if (toolbar.querySelector('.ltm-sql-btns-group')) return;

        const textarea = toolbar.closest('.jstBlock')?.querySelector('textarea.wiki-edit');
        if (!textarea) return;

        const group = document.createElement('div');
        group.className = 'ltm-sql-btns-group';
        group.style.display = 'contents';

        // 1. Кнопка с Collapse
        const btnCollapse = document.createElement('button');
        btnCollapse.type = 'button';
        btnCollapse.className = 'ltm-sql-insert-btn';
        btnCollapse.title = 'Вставить SQL в collapse';
        btnCollapse.innerHTML = 'SQL+';
        btnCollapse.onclick = async (e) => {
            e.preventDefault();
            const text = await getClipboardText();
            if (text) insertAtCursor(textarea, `{{collapse()\n<pre><code class="sql">\n${text}\n</code></pre>\n}}`);
        };

        // 2. Кнопка просто Code
        const btnSimple = document.createElement('button');
        btnSimple.type = 'button';
        btnSimple.className = 'ltm-sql-insert-btn simple';
        btnSimple.title = 'Вставить SQL блок';
        btnSimple.innerHTML = 'SQL';
        btnSimple.onclick = async (e) => {
            e.preventDefault();
            const text = await getClipboardText();
            if (text) insertAtCursor(textarea, `<pre><code class="sql">\n${text}\n</code></pre>`);
        };

        group.appendChild(btnCollapse);
        group.appendChild(btnSimple);
        toolbar.appendChild(group);
    });
}