// dashboard.js
// --- ДОБАВИТЬ К ГЛОБАЛЬНЫМ ПЕРЕМЕННЫМ (ВВЕРХУ) ---
let GMAIL_TOKEN = null;
let ACKNOWLEDGED_MAILS = [];
let ALARM_AUDIO = new Audio(chrome.runtime.getURL('assets/alarm.mp3'));
ALARM_AUDIO.loop = true;
let IS_ALARM_PLAYING = false;
let ALARM_SOURCE     = '';   // 'redmine' | 'gmail' | 'messenger'
let ALARM_ENABLED    = false;

let ACKNOWLEDGED_ISSUES = [];
let LAST_GMAIL_DATA = [];    // Хранит последние загруженные письма для кнопки Стоп
let TRULY_NEW_GMAIL = false; // Есть ли прямо сейчас непрочитанные (не подтверждённые) письма
// === СПИСОК ПРОЕКТОВ REDMINE (из <select id="issue_project_id">) ===
const REDMINE_PROJECTS = [
    { id: <project_id>,  label: '<project_name>' },
    { id: <project_id>,  label: '<project_name>' },
    { id: <project_id>,  label: '<project_name>' },
    { id: <project_id>,  label: '<project_name>' },
    { id: <project_id>,  label: '<project_name>' },
    { id: <project_id>,  label: '<project_name>' },
    { id: <project_id>,  label: '<project_name>' },
    { id: <project_id>,  label: '<project_name>' },
    { id: <project_id>,  label: '<project_name>' },
    { id: <project_id>,  label: '<project_name>' },
    { id: <project_id>,  label: '<project_name>' },
    { id: <project_id>,  label: '<project_name>' },
    { id: <project_id>,  label: '<project_name>' },
    { id: <project_id>,  label: '<project_name>' },
    { id: <project_id>,  label: '<project_name>' },
    { id: <project_id>,  label: '<project_name>' },
    { id: <project_id>,  label: '<project_name>' },
    { id: <project_id>,  label: '<project_name>' },
    { id: <project_id>,  label: '<project_name>' },
    { id: <project_id>,  label: '<project_name>' },
    { id: <project_id>,  label: '<project_name>' },
    { id: <project_id>,  label: '<project_name>' },
    { id: <project_id>,  label: '<project_name>' },
    { id: <project_id>,  label: '<project_name>' },
    { id: <project_id>,  label: '<project_name>' },
    { id: <project_id>,  label: '<project_name>' },
    { id: <project_id>,  label: '<project_name>' },
    { id: <project_id>,  label: '<project_name>' },
    { id: <project_id>,  label: '<project_name>' },
    { id: <project_id>,  label: '<project_name>' },
    { id: <project_id>,  label: '<project_name>' },
    { id: <project_id>,  label: '<project_name>' },
    { id: <project_id>,  label: '<project_name>' },
    { id: <project_id>,  label: '<project_name>' },
    { id: <project_id>,  label: '<project_name>' },
    { id: <project_id>,  label: '<project_name>' },
    { id: <project_id>,  label: '<project_name>' },
    { id: <project_id>,  label: '<project_name>' },
    { id: <project_id>,  label: '<project_name>' },
    { id: <project_id>,  label: '<project_name>' },
    { id: <project_id>,  label: '<project_name>' },
    { id: <project_id>,  label: '<project_name>' },
    { id: <project_id>,  label: '<project_name>' },
    { id: <project_id>,  label: '<project_name>' },
    { id: <project_id>,  label: '<project_name>' },
    { id: <project_id>,  label: '<project_name>' },
    { id: <project_id>,  label: '<project_name>' },
    { id: <project_id>,  label: '<project_name>' },
    { id: <project_id>,  label: '<project_name>' },
    { id: <project_id>,  label: '<project_name>' },
    { id: <project_id>,  label: '<project_name>' },
    { id: <project_id>,  label: '<project_name>' },
    { id: <project_id>,  label: '<project_name>' },
    { id: <project_id>,  label: '<project_name>' },
    { id: <project_id>,  label: '<project_name>' },
    { id: <project_id>,  label: '<project_name>' },
    { id: <project_id>,  label: '<project_name>' },
    { id: <project_id>,  label: '<project_name>' },
    { id: <project_id>,  label: '<project_name>' },
    { id: <project_id>,  label: '<project_name>' },
    { id: <project_id>,  label: '<project_name>' },
    { id: <project_id>,  label: '<project_name>' },
    { id: <project_id>,  label: '<project_name>' },
];

// Дефолтные маппинги (совпадают с захардкоженными в mail-checker.js)
const DEFAULT_SENDER_MAP = [
    { match: '<sender>', id: <project_id> },
    { match: '<sender>', id: <project_id> },
    { match: '<sender>', id: <project_id> },
    { match: '<sender>', id: <project_id> },
    { match: '<sender>', id: <project_id> },
    { match: '<sender>', id: <project_id> },
];
const DEFAULT_SERVER_MAP = [
    { match: '<server>', id: <project_id> },
    { match: '<server>', id: <project_id> },
    { match: '<server>', id: <project_id> },
    { match: '<server>', id: <project_id> },
    { match: '<server>', id: <project_id> },
    { match: '<server>', id: <project_id> },
];

function buildProjectSelect(selectedId) {
    const sel = document.createElement('select');
    sel.className = 'mapping-project';
    const blank = document.createElement('option');
    blank.value = '';
    blank.textContent = '- выбрать проект -';
    sel.appendChild(blank);
    REDMINE_PROJECTS.forEach(p => {
        const opt = document.createElement('option');
        opt.value = p.id;
        opt.textContent = p.label;
        if (String(p.id) === String(selectedId)) opt.selected = true;
        sel.appendChild(opt);
    });
    return sel;
}

function createMappingRow(matchValue, projectId) {
    const row = document.createElement('div');
    row.className = 'mapping-row';

    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'mapping-match settings-input';
    input.placeholder = 'Ключевая фраза / префикс сервера';
    input.value = matchValue || '';

    const delBtn = document.createElement('button');
    delBtn.className = 'mapping-del-btn';
    delBtn.title = 'Удалить строку';
    delBtn.textContent = '✕';
    delBtn.addEventListener('click', () => row.remove());

    row.appendChild(input);
    row.appendChild(buildProjectSelect(projectId));
    row.appendChild(delBtn);
    return row;
}

function renderMappingList(containerId, items) {
    const container = document.getElementById(containerId);
    container.innerHTML = '';
    items.forEach(item => container.appendChild(createMappingRow(item.match, item.id)));
}

function collectMappingRows(containerId) {
    return [...document.getElementById(containerId).querySelectorAll('.mapping-row')]
        .map(row => {
            const match = row.querySelector('.mapping-match').value.trim();
            const sel   = row.querySelector('.mapping-project');
            const id    = parseInt(sel.value);
            const label = sel.selectedIndex > 0
                ? sel.options[sel.selectedIndex].text.replace(/^[\s»]+/, '').trim()
                : '';
            return { match, id, label };
        })
        .filter(r => r.match && r.id);
}

// === НАСТРОЙКИ ИСТОЧНИКОВ (дефолты, переопределяются из chrome.storage) ===
const SOURCES = {
    redmineUrls: [
        '<ссылка>/projects/pr-001/issues?query_id=<query_id>&limit=100',
        '<ссылка>/projects/wms2_sp_mystesd/issues?limit=100'
    ],
    mailUrl: 'https://mail.yandex.ru/lite'
};

// === НАСТРОЙКИ КОЛОНОК (дефолты) ===
const COLUMN_MAPPING = {
    new:  ['Новая', 'Новая информация', 'New', 'Уточнение', 'Назначена', 'Assigned'],
    work: ['В работе', 'В процессе', 'In Progress', 'Разработка'],
    wait: ['Ожидание', 'Согласование', 'Feedback', 'Hold', 'Отложена', 'Приостановлено']
};

let GMAIL_QUERY = 'subject:(HealthScript OR HS OR "Проверка логов планировщика" OR Notifier) is:unread -subject:"(Закрыта)"';

// Глобальные переменные
let CACHED_ISSUES = [];
let REFRESH_TIMER = null;

// Тихие заявки Redmine - не запускают будильник (видны в канбане обычно).
// Правило: (issue.project содержит хотя бы один SILENT_PROJECTS)
//       И (issue.subject содержит хотя бы один SILENT_SUBJECT или список пуст).
let SILENT_ENABLED  = true;
let SILENT_PROJECTS = ['Магнит'];
let SILENT_SUBJECT  = ['Проверка HS', 'Проверка НS'];

function parseCsvList(s) {
    return String(s || '').split(',').map(x => x.trim()).filter(Boolean);
}

function isSilentIssue(issue) {
    if (!SILENT_ENABLED) return false;
    if (SILENT_PROJECTS.length === 0) return false;
    const proj = (issue.project || '').toLowerCase();
    const subj = (issue.subject || '').toLowerCase();
    const projMatch = SILENT_PROJECTS.some(p => proj.includes(p.toLowerCase()));
    if (!projMatch) return false;
    // Если subject-фильтр пустой - достаточно совпадения по проекту
    if (SILENT_SUBJECT.length === 0) return true;
    return SILENT_SUBJECT.some(s => subj.includes(s.toLowerCase()));
}

// === Хелперы для chrome.storage.sync (write-if-changed, защита от throttling) ===
// chrome.storage.sync лимитит ~120 записей/мин на ключ. Acknowledged-списки
// чистятся каждый тик до текущих ID, поэтому "пустая" запись частая - пишем
// только при реальном изменении.
let _ackMailsSerialized   = '[]';
let _ackIssuesSerialized  = '[]';

function saveAckMails() {
    const s = JSON.stringify(ACKNOWLEDGED_MAILS);
    if (s === _ackMailsSerialized) return;
    _ackMailsSerialized = s;
    chrome.storage.sync.set({ acknowledgedMails: ACKNOWLEDGED_MAILS });
}

function saveAckIssues() {
    const s = JSON.stringify(ACKNOWLEDGED_ISSUES);
    if (s === _ackIssuesSerialized) return;
    _ackIssuesSerialized = s;
    chrome.storage.sync.set({ acknowledgedIssues: ACKNOWLEDGED_ISSUES });
}

// === Передача счётчиков в service-worker для бейджа на иконке ===
function notifyBadge(patch) {
    chrome.runtime.sendMessage({ action: 'dashboard_counts', ...patch }, () => {
        void chrome.runtime.lastError;
    });
}

document.addEventListener('DOMContentLoaded', () => {

    // 0. Загружаем настройки из chrome.storage, потом инициализируем дашборд
    loadSettings(() => initDashboard());

    // 1.1. Слушаем изменения настроек в реальном времени (если переключили в попапе)
        chrome.storage.onChanged.addListener((changes, namespace) => {
            if (changes.alarmEnabled) {
                ALARM_ENABLED = changes.alarmEnabled.newValue;
                // Если выключили настройку, а звук играл - выключаем сразу
                if (!ALARM_ENABLED && IS_ALARM_PLAYING) {
                    stopAlarm();
                }
            }
        });

    // 2. Восстановление настройки авто-обновления - теперь в loadSettings()
    //    (см. чтение result.refreshInterval), т.к. chrome.storage.sync асинхронен.

    // 2а. Независимый чек Gmail - каждые 2 минуты приходит тик от
    //     service-worker (chrome.alarms 'gmailCheck'). Это надёжнее setInterval:
    //     переживает выгрузку дашборда и Chrome-усыпление страницы расширения.
    chrome.runtime.onMessage.addListener((req) => {
        if (req?.action === 'gmail_tick') checkGmailMessages(false);
    });
    // Первая проверка сразу при загрузке (не ждём первый alarm-тик)
    checkGmailMessages(false);

    // 3. Обработчик ручного обновления
    document.getElementById('refreshBtn').addEventListener('click', () => {
        animateRefreshIcon();
        initDashboard(false); // false = показывать лоадер (ручное обновление)
    });

    // 4. Обработчики фильтров (мгновенные, локальные)
    document.getElementById('sortSelect').addEventListener('change', updateDashboardView);
    document.getElementById('hoursFilter').addEventListener('input', updateDashboardView);

    // 5. Обработчик настройки авто-обновления
    document.getElementById('refreshInterval').addEventListener('change', (e) => {
        const seconds = parseInt(e.target.value);
        if (seconds && seconds >= 10) {
            chrome.storage.sync.set({ refreshInterval: seconds });
            startAutoRefresh(seconds);
        } else {
            chrome.storage.sync.remove('refreshInterval');
            stopAutoRefresh();
        }
    });

    // 6. Табы (ОБНОВЛЕННЫЙ КОД)
        document.querySelectorAll('.nav-item[data-tab]').forEach(btn => {
            btn.addEventListener('click', (e) => {
                document.querySelectorAll('.nav-item').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');

                const tab = btn.dataset.tab;
                if (tab === 'overview') {
                    toggleView('overview');
                } else if (tab === 'mail') {
                    toggleView('mail');
                    checkGmailMessages(true);
                } else if (tab === 'settings') {
                    toggleView('settings');
                } else if (tab === 'scripts') {
                    toggleView('scripts');
                } else if (tab === 'logs') {
                    toggleView('logs');
                    initLogViewer();
                }
            });
        });

    // 7
    // Обработчик кнопки "ОСТАНОВИТЬ ЗВУК" (ИСПРАВЛЕННЫЙ)
        document.getElementById('stopAlarmBtn').addEventListener('click', () => {
            stopAlarm();

            // 1. Подтверждаем заявки Redmine (как и было)
            const currentNewIds = CACHED_ISSUES
                .filter(issue => matchesStatus(issue.status.toLowerCase(), COLUMN_MAPPING.new))
                .map(issue => issue.id);

            ACKNOWLEDGED_ISSUES = [...new Set([...ACKNOWLEDGED_ISSUES, ...currentNewIds])];
            saveAckIssues();

            // 2. Подтверждаем письма (Gmail) - БЕЗ ЛИШНИХ ЗАПРОСОВ
            // Берем данные из переменной, которую мы наполнили при загрузке писем
            if (LAST_GMAIL_DATA.length > 0) {
                const currentMailIds = LAST_GMAIL_DATA.map(m => m.id);
                ACKNOWLEDGED_MAILS = [...new Set([...ACKNOWLEDGED_MAILS, ...currentMailIds])];
                saveAckMails();

                // Сразу обновляем вид списка (чтобы красные точки стали серыми)
                renderGmailResult(LAST_GMAIL_DATA);
            }

            updateDashboardView(); // Перерисовываем Redmine
        });
});

// === ЛОГИКА ТАЙМЕРА ===
function startAutoRefresh(seconds) {
    stopAutoRefresh(); // Сначала очищаем старый, чтобы не дублировать
    console.log(`Авто-обновление включено: каждые ${seconds} сек.`);

    REFRESH_TIMER = setInterval(() => {
        console.log('Выполняется авто-обновление...');
        animateRefreshIcon(); // Крутим иконку для индикации жизни
        initDashboard(true);  // true = "тихий" режим (без очистки экрана)
    }, seconds * 1000);
}

function stopAutoRefresh() {
    if (REFRESH_TIMER) {
        clearInterval(REFRESH_TIMER);
        REFRESH_TIMER = null;
        console.log('Авто-обновление остановлено.');
    }
}

function animateRefreshIcon() {
    const icon = document.querySelector('#refreshBtn .icon');
    if (icon) {
        icon.style.transition = 'transform 1s';
        icon.style.transform = 'rotate(360deg)';
        setTimeout(() => {
            icon.style.transition = 'none';
            icon.style.transform = 'none';
        }, 1000);
    }
}

async function initDashboard(isBackgroundRefresh = false) {
    // 1. Обновляем Redmine (всегда)
    await fetchRedmineData(isBackgroundRefresh);

    // 2. Обновляем Почту (всегда, но в "тихом" режиме)
    // isBackgroundRefresh - true, если это вызов от таймера.
    // false - если мы нажали F5 или кнопку "Обновить".

    // Если это авто-обновление (таймер), мы не хотим, чтобы внезапно вылезало окно логина,
    // поэтому передаем false (не интерактивно).
    // Если это ручное нажатие кнопки "Обновить", можно попробовать интерактивно,
    // но лучше тоже тихо, чтобы не бесило. Интерактивно только по клику на таб.

    checkGmailMessages(false); // <--- Всегда проверяем почту в фоновом режиме

    updateTime();
}

function updateTime() {
    const now = new Date();
    document.getElementById('lastUpdated').innerText = `Обновлено: ${now.toLocaleTimeString()}`;
}

// === 1. ПОЛУЧЕНИЕ ДАННЫХ (FETCH) ===
async function fetchRedmineData(isBackgroundRefresh) {
    // Если это ручное обновление - показываем "Загрузка..."
    // Если авто-обновление - не трогаем интерфейс, пока данные не придут
    if (!isBackgroundRefresh) {
        ['list-new', 'list-work', 'list-wait'].forEach(id => {
            document.getElementById(id).innerHTML = '<div class="loading-placeholder">Загрузка данных...</div>';
        });
    }

    try {
        const responses = await Promise.all(
            SOURCES.redmineUrls.map(url =>
                fetch(url).then(res => {
                    if (!res.ok) throw new Error(`HTTP ${res.status}`);
                    return res.text();
                }).catch(err => {
                    console.error(`Ошибка загрузки ${url}:`, err);
                    return null;
                })
            )
        );

        let parsedIssues = [];
        const parser = new DOMParser();

        responses.forEach(htmlText => {
            if (!htmlText) return;
            const doc = parser.parseFromString(htmlText, 'text/html');
            const tableRows = doc.querySelectorAll('table.list.issues tbody tr');
            let currentGroupStatus = '';

            tableRows.forEach(row => {
                if (row.classList.contains('group')) {
                    const nameSpan = row.querySelector('.name');
                    if (nameSpan) {
                        currentGroupStatus = nameSpan.innerText.trim().split('(')[0].trim();
                    }
                } else if (row.classList.contains('issue')) {
                    const issueData = parseIssueRow(row, currentGroupStatus);
                    if (issueData) parsedIssues.push(issueData);
                }
            });
        });

        // Сохраняем и обновляем вид
        CACHED_ISSUES = parsedIssues;
        updateDashboardView();

    } catch (e) {
        console.error('Ошибка:', e);
        if (!isBackgroundRefresh) {
            document.querySelector('.kanban-board').innerHTML =
                `<div style="color:red; padding:20px; text-align:center;">Ошибка: ${e.message}</div>`;
        }
    }
}

// === 2. ФИЛЬТРАЦИЯ И ОТРИСОВКА (VIEW) ===
// === 2. ФИЛЬТРАЦИЯ И ОТРИСОВКА (VIEW) ===
function updateDashboardView() {
    const sortType = document.getElementById('sortSelect').value;
    const hoursFilterValue = document.getElementById('hoursFilter').value;
    const hoursLimit = hoursFilterValue ? parseFloat(hoursFilterValue) : null;
    const alarmEnabled = ALARM_ENABLED;
    const now = new Date();
    const columns = { new: [], work: [], wait: [] };
    let urgentCount = 0;

    CACHED_ISSUES.forEach(issue => {
        // 1. Фильтр Lamoda
        if (issue.project.includes('Lamoda') || issue.project.includes('mystesd')) {
            const allowedStatuses = ['Новая', 'Новая информация'];
            if (!allowedStatuses.some(s => issue.status.includes(s))) return;
        }

        // 2. Фильтр по времени
        if (hoursLimit !== null && hoursLimit > 0) {
            const diffMs = now - issue.dateObj;
            const diffHours = diffMs / (1000 * 60 * 60);
            if (diffHours > hoursLimit) return;
        }

        if (issue.isUrgent) urgentCount++;

        const statusLower = issue.status.toLowerCase();
        if (matchesStatus(statusLower, COLUMN_MAPPING.new)) {
            columns.new.push(issue);
        } else if (matchesStatus(statusLower, COLUMN_MAPPING.work)) {
            columns.work.push(issue);
        } else if (matchesStatus(statusLower, COLUMN_MAPPING.wait)) {
            columns.wait.push(issue);
        }
    });

// // // // // // // // // // // Будильник // // // // // // //  // // // // // // // // // // // //  // // // // // // // // // // // //
const currentNewIds = columns.new.map(issue => issue.id);

    // 1. Очистка списка подтвержденных: если заявки больше нет в колонке "Новые",
        // удаляем её из списка игнорирования (чтобы сработало при возврате в статус)
        ACKNOWLEDGED_ISSUES = ACKNOWLEDGED_ISSUES.filter(id => currentNewIds.includes(id));
        saveAckIssues();

        // 2. Проверка на наличие "действительно новых" (которых нет в списке подтвержденных)
        const trulyNewIssues = columns.new.filter(issue => !ACKNOWLEDGED_ISSUES.includes(issue.id));

        // Из них фильтруем «тихие» - они видны в канбане, но будильник по ним не звенит.
        // Пример: тикеты «Проверка HS» в проектах Магнит / Магнит Т/П.
        const alarmableNew = trulyNewIssues.filter(issue => !isSilentIssue(issue));

        if (alarmableNew.length > 0 && alarmEnabled && !IS_ALARM_PLAYING) {
            startAlarm('redmine');
        } else if (alarmableNew.length === 0 && !TRULY_NEW_GMAIL && IS_ALARM_PLAYING
                   && (ALARM_SOURCE === 'redmine' || ALARM_SOURCE === 'gmail')) {
            // Авто-стоп ТОЛЬКО для redmine/gmail источников: если задачу взяли
            // в работу (ушла из колонки new) и в Gmail тоже чисто - гасим.
            // ВАЖНО: messenger/<Плейсхолдер>-источники этим путём НЕ гасим, иначе
            // обновление пустого Redmine задушит активный будильник от мессенджера.
            stopAlarm();
        }

// // // // // // //  // // // // // // // // // // // //  // // // // // // // // // // // // // // // // // // //  // // // // // // // // // // // //  // // // // // // // // // // // //
    renderColumn('list-new', 'count-new', columns.new, sortType);
    renderColumn('list-work', 'count-work', columns.work, sortType);
    renderColumn('list-wait', 'count-wait', columns.wait, sortType);

    document.getElementById('kpiTotal').innerText = columns.work.length + columns.new.length;
    document.getElementById('kpiUrgent').innerText = urgentCount;
    document.getElementById('kpiWait').innerText = columns.wait.length;

    // === НОВОЕ: УПРАВЛЕНИЕ БЕЙДЖЕМ В МЕНЮ ===
    const navBadge = document.getElementById('navBadgeNew');
    const newCount = columns.new.length;

    if (newCount > 0) {
        navBadge.style.display = 'inline-block'; // Показываем
        navBadge.innerText = newCount;           // Обновляем число

        // (Опционально) Меняем цвет, если есть срочные
        if (urgentCount > 0) {
            navBadge.style.backgroundColor = '#ef4444'; // Красный
        } else {
            navBadge.style.backgroundColor = '#3b82f6'; // Синий (если просто новые, но не срочные)
        }
    } else {
        navBadge.style.display = 'none'; // Скрываем, если 0
    }
    // =========================================

    // Бейдж на иконке расширения - суммарный счётчик с цветом по urgent
    notifyBadge({ redmine: newCount, urgent: urgentCount > 0 });
}

// === ПАРСЕРЫ И ХЕЛПЕРЫ ===
function parseRedmineDate(dateStr) {
    if (!dateStr) return new Date(0);
    const parts = dateStr.trim().split(' ');
    if (parts.length < 2) return new Date(0);
    const [day, month, year] = parts[0].split('.');
    const [hour, minute] = parts[1].split(':');
    return new Date(year, month - 1, day, hour, minute);
}

function matchesStatus(statusText, keywords) {
    if (!statusText) return false;
    return keywords.some(key => statusText.includes(key.toLowerCase()));
}

function parseIssueRow(tr, fallbackStatus = '') {
    try {
        const idLink = tr.querySelector('.id a');
        const subjectLink = tr.querySelector('.subject a');
        if (!idLink || !subjectLink) return null;

        const priority = tr.querySelector('.priority')?.innerText || '';
        let status = tr.querySelector('.status')?.innerText || '';
        if (!status || status.trim() === '') status = fallbackStatus;

        const project = tr.querySelector('.project')?.innerText || '';
        const assigned = tr.querySelector('.assigned_to a')?.innerText || tr.querySelector('.assigned_to')?.innerText || '';

        const updatedStr = tr.querySelector('.updated_on')?.innerText || '';
        const dateObj = parseRedmineDate(updatedStr);

        const isUrgent = ['Высокий', 'Авария', 'Critical', 'High', 'Критичный'].some(k => priority.includes(k));

        return {
            id: idLink.innerText,
            url: `<ссылка>${idLink.getAttribute('href')}`,
            subject: subjectLink.innerText,
            status: status,
            priority: priority,
            project: project,
            assigned: assigned,
            updated: updatedStr,
            dateObj: dateObj,
            isUrgent: isUrgent
        };
    } catch (e) { return null; }
}

function renderColumn(containerId, countId, issues, sortType) {
    const container = document.getElementById(containerId);
    const counter = document.getElementById(countId);

    // ВАЖНО: При обновлении мы полностью перезаписываем HTML колонки.
    // Это нормально, браузеры делают это очень быстро.
    container.innerHTML = '';
    counter.innerText = issues.length;

    issues.sort((a, b) => {

        if (sortType === 'newest') return b.dateObj - a.dateObj;
        if (sortType === 'oldest') return a.dateObj - b.dateObj;
        return parseInt(b.id) - parseInt(a.id);
    });

    if (issues.length === 0) {
        container.innerHTML = `<div class="empty-state">Нет задач</div>`;
        return;
    }

    issues.forEach(issue => {
        const isNew = matchesStatus(issue.status.toLowerCase(), COLUMN_MAPPING.new);
        const card = document.createElement('div');
        card.className = `kanban-card ${issue.isUrgent ? 'card-urgent' : ''} ${isNew ? 'card-new' : ''}`;

        card.innerHTML = `
            <div class="card-top">
                <a href="${issue.url}" target="_blank" class="card-id">#${issue.id}</a>
                <span class="card-prio">${issue.priority}</span>
            </div>
            <a href="${issue.url}" target="_blank" class="card-subject" title="${issue.subject}">
                ${issue.isUrgent ? '🔥 ' : ''}${issue.subject}
            </a>
            <div class="card-meta">
                <div class="card-row">
                    <span class="icon">📂</span> ${issue.project}
                </div>
                ${issue.assigned ? `<div class="card-row"><span class="icon">👤</span> ${issue.assigned}</div>` : ''}
                <div class="card-footer">
                    <span class="card-status">${issue.status}</span>
                    <span class="card-date">${issue.updated}</span>
                </div>
            </div>
        `;
        container.appendChild(card);
    });
}

// Заглушка почты
async function fetchMailData() {
    const mailList = document.getElementById('mailList');
    mailList.innerHTML = '<li class="loading-placeholder">Загрузка...</li>';
    setTimeout(() => {
        mailList.innerHTML = `
            <li class="mail-item">
                <div class="mail-dot"></div>
                <div class="mail-content-wrap">
                    <span class="mail-subject">Уведомление системы</span>
                    <span class="mail-sender">System</span>
                </div>
            </li>
            <li class="mail-item" style="justify-content:center; margin-top:20px;">
                <a href="${SOURCES.mailUrl}" target="_blank" class="btn-primary" style="text-decoration:none; padding:8px 16px; border-radius:4px;">
                    Перейти в Почту
                </a>
            </li>
        `;
    }, 500);
}

function startAlarm(source = '') {
    IS_ALARM_PLAYING = true;
    ALARM_SOURCE     = source;
    ALARM_AUDIO.play().catch(e => console.log("Нужно взаимодействие с документом для звука"));
    const btn = document.getElementById('stopAlarmBtn');
    btn.classList.remove('hidden');
    const label = source === 'messenger' ? '🔕 ЯМ! Стоп' :
                  source === 'magnit'    ? '🔕 <Плейсхолдер> Стоп' :
                  source === 'gmail'     ? '🔕 Gmail Стоп' :
                  source === 'redmine'   ? '🔕 Redmine Стоп' : '🔕 Стоп';
    btn.textContent = label;
}

function stopAlarm() {
    IS_ALARM_PLAYING = false;
    ALARM_SOURCE     = '';
    ALARM_AUDIO.pause();
    ALARM_AUDIO.currentTime = 0;
    const btn = document.getElementById('stopAlarmBtn');
    btn.classList.add('hidden');
    btn.textContent = 'Stop Alarm';
}



// ==========================================
// === ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ И GMAIL ===
// ==========================================

function toggleView(view) {
    const board = document.querySelector('.kanban-board');
    const kpi = document.querySelector('.kpi-grid');
    const controls = document.querySelector('.controls-bar');
    const mailContainer = document.getElementById('mailContainer');
    const settingsContainer = document.getElementById('settingsContainer');
    const title = document.getElementById('pageTitle');

    const scriptsContainer = document.getElementById('scriptsContainer');
    const logsContainer = document.getElementById('logsContainer');

    board.style.display             = 'none';
    kpi.style.display               = 'none';
    controls.style.display          = 'none';
    mailContainer.style.display     = 'none';
    settingsContainer.style.display = 'none';
    scriptsContainer.style.display  = 'none';
    if (logsContainer) logsContainer.style.display = 'none';

    if (view === 'overview') {
        board.style.display    = 'flex';
        kpi.style.display      = 'grid';
        controls.style.display = 'flex';
        title.innerText        = 'Мониторинг заявок';
    } else if (view === 'mail') {
        mailContainer.style.display = 'block';
        title.innerText             = 'Почтовый ящик';
    } else if (view === 'settings') {
        settingsContainer.style.display = 'block';
        title.innerText                 = 'Настройки';
        populateSettingsForm();
    } else if (view === 'scripts') {
        scriptsContainer.style.display = 'flex';
        title.innerText                = 'База скриптов';
        initScriptsPage();
    } else if (view === 'logs') {
        logsContainer.style.display = 'flex';
        title.innerText             = 'LogViewer';
    }
}

// === ЛОГИКА GMAIL ===

function checkGmailMessages(isInteractive = false) {
    // Всегда идём через getAuthToken - Chrome сам обновляет истёкший токен.
    // НЕ кешируем токен в JS: старый кеш - главная причина того, что через ~1 час
    // Gmail перестаёт проверяться (токен истёк, JS-переменная осталась старой).
    chrome.identity.getAuthToken({ interactive: isInteractive }, function(token) {
        if (chrome.runtime.lastError || !token) {
            if (isInteractive) {
                console.warn("Gmail Auth Error:", chrome.runtime.lastError);
                updateMailStatus(`<span style="color:red">Ошибка авторизации.</span>`);
            } else {
                console.log("Gmail: фоновая проверка пропущена (нет авторизации)");
            }
            return;
        }
        GMAIL_TOKEN = token;
        fetchGmailData(token);
    });
}

async function fetchGmailData(token) {
    // 1. Сначала ищем список ID нужных сообщений
    const query = GMAIL_QUERY;
    const listUrl = `https://gmail.googleapis.com/gmail/v1/users/me/messages?q=${encodeURIComponent(query)}`;

    try {
        const listResponse = await fetch(listUrl, {
            headers: { 'Authorization': `Bearer ${token}` }
        });

        // 401 = токен истёк. Сбрасываем кеш Chrome и пробуем ещё раз.
        if (listResponse.status === 401) {
            console.warn('Gmail: токен истёк (401), сбрасываем и получаем новый...');
            GMAIL_TOKEN = null;
            chrome.identity.removeCachedAuthToken({ token }, () => {
                checkGmailMessages(false); // тихий повтор со свежим токеном
            });
            return;
        }

        const listData = await listResponse.json();
        const messages = listData.messages || [];

        if (messages.length === 0) {
            renderGmailResult([]);
            return;
        }

        // 2. ТЕПЕРЬ ЗАГРУЖАЕМ ДЕТАЛИ (Тему и Текст)
        // Берем только первые 10 писем, чтобы не спамить API запросами
        const messagesToFetch = messages.slice(0, 10);

        // Загружаем полный формат чтобы иметь тело письма для фильтрации пунктов
        const detailsPromises = messagesToFetch.map(msg =>
            fetch(`https://gmail.googleapis.com/gmail/v1/users/me/messages/${msg.id}?format=full`, {
                headers: { 'Authorization': `Bearer ${token}` }
            }).then(r => r.json())
        );

        const detailsData = await Promise.all(detailsPromises);

        // СОХРАНЯЕМ В ГЛОБАЛЬНУЮ ПЕРЕМЕННУЮ (для кнопки Стоп)
        LAST_GMAIL_DATA = detailsData;

        renderGmailResult(detailsData);

    } catch (error) {
        console.error("Gmail API Error:", error);
        updateMailStatus("Ошибка соединения с Gmail");
    }
}
// === ФИЛЬТРАЦИЯ ПИСЕМ ПО ПУНКТАМ РАСХОЖДЕНИЙ ===
// Пункты, которые НЕ должны будить будильник если они единственные в письме
// Дефолт; перезаписывается из chrome.storage.sync.gmailIgnoredPoints в loadSettings()
let GMAIL_IGNORED_POINTS = new Set([11, 30]);

function parseIgnoredPoints(raw) {
    if (Array.isArray(raw)) return new Set(raw.map(Number).filter(n => !isNaN(n)));
    if (typeof raw === 'string') {
        return new Set(raw.split(/[,\s]+/).map(s => parseInt(s, 10)).filter(n => !isNaN(n)));
    }
    return null;
}

function decodeBase64Url(data) {
    try {
        const binary = atob(data.replace(/-/g, '+').replace(/_/g, '/'));
        return decodeURIComponent(binary.split('').map(c =>
            '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2)
        ).join(''));
    } catch {
        return '';
    }
}

function extractGmailBody(message) {
    const payload = message.payload;
    if (!payload) return message.snippet || '';

    // Простое сообщение - тело сразу в payload.body
    if (payload.body?.data) return decodeBase64Url(payload.body.data);

    // Multipart - ищем text/plain рекурсивно
    function findPart(parts) {
        if (!parts) return '';
        for (const part of parts) {
            if (part.mimeType === 'text/plain' && part.body?.data) {
                return decodeBase64Url(part.body.data);
            }
            const nested = findPart(part.parts);
            if (nested) return nested;
        }
        return '';
    }
    return findPart(payload.parts) || message.snippet || '';
}

/**
 * Возвращает true если письмо должно запустить будильник.
 * Логика для писем с "Расхождения в пунктах:":
 *   - пункт <11> в одиночку → НЕ будить
 *   - пункт <30> в одиночку → НЕ будить
 *   - несколько пунктов (включая 11/30 вперемешку с другими) → БУДИТЬ
 *   - любой пункт не из списка игнорируемых → БУДИТЬ
 * Письма без "Расхождения в пунктах" → всегда будить.
 */
function shouldAlarmForEmail(message) {
    const text = extractGmailBody(message) || message.snippet || '';

    if (!text.includes('Расхождения в пунктах')) return true; // другой тип - реагируем

    const points = [...text.matchAll(/<(\d+)>/g)].map(m => parseInt(m[1], 10));
    if (points.length === 0) return true; // нет номеров → реагируем

    // Будим только если есть хотя бы один пункт НЕ из игнорируемого списка
    const hasRealPoint = points.some(p => !GMAIL_IGNORED_POINTS.has(p));
    if (!hasRealPoint) {
        console.log(`письмо ${message.id} пропущено - только пункты ${points.join(', ')} (все в списке игнорирования)`);
    }
    return hasRealPoint;
}

// === ОБНОВЛЕННАЯ ФУНКЦИЯ ОТРИСОВКИ (С БЕЙДЖЕМ) ===
function renderGmailResult(messages) {
    const list = document.getElementById('mailList');
    list.innerHTML = '';

    // Если писем нет
    if (!messages || messages.length === 0) {
        list.innerHTML = '<li class="loading-placeholder">Нет важных писем</li>';
        if (ACKNOWLEDGED_MAILS.length > 0) {
            ACKNOWLEDGED_MAILS = [];
            saveAckMails();
        }
        updateMailBadge(0, false);
        notifyBadge({ gmail: 0 });
        return;
    }

    // 1. Очистка памяти
    const currentIds = messages.map(m => m.id);
    ACKNOWLEDGED_MAILS = ACKNOWLEDGED_MAILS.filter(id => currentIds.includes(id));
    saveAckMails();

    // 2. Проверка новых (только те что реально должны будить - фильтр по пунктам)
    const hasNewMail = messages.some(m =>
        !ACKNOWLEDGED_MAILS.includes(m.id) && shouldAlarmForEmail(m)
    );

    // Для бейджа - показываем все непрочитанные (включая «тихие» пункты 11/30)
    const hasAnyNew = messages.some(m => !ACKNOWLEDGED_MAILS.includes(m.id));

    TRULY_NEW_GMAIL = hasNewMail;

    // Обновляем бейдж в навигации дашборда
    updateMailBadge(messages.length, hasAnyNew);
    // И бейдж на иконке расширения - число реально непрочитанных писем
    const unreadGmailCount = messages.filter(m => !ACKNOWLEDGED_MAILS.includes(m.id)).length;
    notifyBadge({ gmail: unreadGmailCount });

    // 3. Будильник - только для писем с «реальными» пунктами
    if (hasNewMail && ALARM_ENABLED && !IS_ALARM_PLAYING) {
        startAlarm('gmail');
    }

    // Авто-подтверждение для кнопки стоп
    if (!IS_ALARM_PLAYING && hasAnyNew) {
         const newIds = messages.map(m => m.id);
         ACKNOWLEDGED_MAILS = [...new Set([...ACKNOWLEDGED_MAILS, ...newIds])];
         saveAckMails();
         updateMailBadge(messages.length, false);
    }

    // 4. Отрисовка
    messages.forEach(msg => {
        const isNew = !ACKNOWLEDGED_MAILS.includes(msg.id);
        const dotColor = isNew ? '#ef4444' : '#9ca3af';

        const headers = msg.payload?.headers || [];
        const subjectHeader = headers.find(h => h.name === 'Subject');
        const subjectText = subjectHeader ? subjectHeader.value : '(Без темы)';
        const snippetText = msg.snippet || '';
        const createIssueUrl = "<ссылка>/projects/pr-001/issues/new";

        const item = document.createElement('li');
        item.className = 'mail-item';

        item.innerHTML = `
            <div class="mail-dot" style="background: ${dotColor};" title="${isNew ? 'Новое' : 'Просмотрено'}"></div>
            <div class="mail-content-wrap">
                <span class="mail-subject" style="display:block; font-weight:700; margin-bottom:2px;">${subjectText}</span>
                <span class="mail-desc" style="display:block; font-size:12px; color:#64748b; margin-bottom:4px; line-height:1.3;">${snippetText}</span>
                <span class="mail-sender">
                    <a href="${createIssueUrl}" target="_blank" style="color:#10b981; font-weight:700; font-size:12px; text-decoration:none; display:inline-flex; align-items:center; gap:4px;">
                        ➕ Создать заявку
                    </a>
                    <span style="color:#cbd5e1; margin:0 5px;">|</span>
                    <a href="https://mail.google.com/mail/u/0/#inbox/${msg.id}" target="_blank" style="color:#3b82f6; font-size:11px;">Gmail</a>
                </span>
            </div>
        `;
        list.appendChild(item);
    });

    // === 5. ЛОГИКА "ПОМЕТИТЬ ПРОЧИТАННЫМ" ===
    // Проверяем:
    // 1. Вкладка Почты открыта (display != none)
    // 2. Окно браузера активно (пользователь смотрит на него)
    // 3. Есть письма
    const isMailTabVisible = document.getElementById('mailContainer').style.display !== 'none';
    const isWindowVisible = document.visibilityState === 'visible';

    if (isMailTabVisible && isWindowVisible && messages.length > 0) {
        // Запускаем пометку прочитанным (асинхронно, не блокируя интерфейс)
        markMessagesAsRead(currentIds);
    }
}

// === НОВАЯ ФУНКЦИЯ ДЛЯ БЕЙДЖА ПОЧТЫ ===
function updateMailBadge(count, hasNew) {
    const badge = document.getElementById('navBadgeMail');
    if (!badge) return;

    if (count > 0) {
        badge.style.display = 'inline-block';
        badge.innerText = count;
        // Красный (#ef4444) если есть новые, Синий (#3b82f6) если просто висят в списке
        badge.style.backgroundColor = hasNew ? '#ef4444' : '#3b82f6';
    } else {
        badge.style.display = 'none';
    }
}

function updateMailStatus(html) {
    const list = document.getElementById('mailList');
    if (list) list.innerHTML = `<li class="loading-placeholder">${html}</li>`;
}

// === ФУНКЦИЯ ПОМЕТКИ КАК ПРОЧИТАННОЕ ===
async function markMessagesAsRead(ids) {
    if (!GMAIL_TOKEN || !ids || ids.length === 0) return;

    try {
        await fetch(`https://gmail.googleapis.com/gmail/v1/users/me/messages/batchModify`, {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${GMAIL_TOKEN}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                ids: ids,
                removeLabelIds: ['UNREAD'] // Снимаем метку "Непрочитано"
            })
        });
        console.log(`Пометил ${ids.length} писем как прочитанные.`);
    } catch (e) {
        console.error("Ошибка при пометке прочитанным:", e);
    }
}

// ==========================================
// === ЗАЩИТА ОТ УСЫПЛЕНИЯ (WAKE LOCK) ===
// ==========================================
let wakeLock = null;

async function requestWakeLock() {
    try {
        // Запрашиваем блокировку "усыпания" экрана/системы
        wakeLock = await navigator.wakeLock.request('screen');
        console.log('Wake Lock активен: вкладка защищена от выгрузки');

        wakeLock.addEventListener('release', () => {
            console.log('Wake Lock сброшен');
        });
    } catch (err) {
        console.error(`Ошибка Wake Lock: ${err.name}, ${err.message}`);
    }
}

// Перезапрашиваем блокировку, если вкладка стала видимой (например, вы вернулись на неё)
document.addEventListener('visibilitychange', async () => {
    if (wakeLock !== null && document.visibilityState === 'visible') {
        await requestWakeLock();
    }
});
// === СЛУШАТЕЛЬ УВЕДОМЛЕНИЙ ИЗ МЕССЕНДЖЕРОВ ===
// Принципиально: будильник играет пока пользователь сам не нажмёт Стоп
// (или не прочитает сообщения в источнике - тогда чекер пришлёт *_cleared).
// Никаких heartbeat-таймеров и автопогасаний по таймауту.

chrome.runtime.onMessage.addListener((req) => {
    if (req?.action === 'messenger_new_message') {
        if (ALARM_ENABLED && !IS_ALARM_PLAYING) startAlarm('messenger');
    }
    else if (req?.action === 'magnit_new_message') {
        if (ALARM_ENABLED && !IS_ALARM_PLAYING) startAlarm('magnit');
    }
    else if (req?.action === 'messenger_cleared') {
        // Все непрочитанные в Мессенджере прочитаны - гасим, если он был источником
        if (IS_ALARM_PLAYING && ALARM_SOURCE === 'messenger') stopAlarm();
    }
});
// Запускаем сразу при загрузке
requestWakeLock();

// ==========================================
// === БАЗА СКРИПТОВ (SCRIPTS DB) ===
// ==========================================

let SCRIPTS_DB            = [];
let SCRIPTS_FILTER_CLIENT = 'all';
let SCRIPTS_SEARCH        = '';
let SCRIPTS_EDIT_ID       = null;
let SCRIPTS_VIEW_ID       = null;
let scriptsPageReady      = false;

function loadScriptsDB() {
    return new Promise(resolve =>
        chrome.storage.local.get(['ltm_scripts'], ({ ltm_scripts }) => {
            SCRIPTS_DB = ltm_scripts || [];
            resolve();
        })
    );
}

function saveScriptsDB() {
    return new Promise(resolve =>
        chrome.storage.local.set({ ltm_scripts: SCRIPTS_DB }, resolve)
    );
}

function escapeHtml(t) {
    return (t || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

// ── SQL Syntax Highlighter ────────────────────────────────────────────────────
function highlightSQL(code) {
    if (!code) return '';

    const KEYWORDS  = 'SELECT|FROM|WHERE|JOIN|LEFT|RIGHT|INNER|OUTER|FULL|CROSS|ON|GROUP\\s+BY|ORDER\\s+BY|PARTITION\\s+BY|HAVING|INSERT|UPDATE|DELETE|CREATE|DROP|ALTER|TABLE|INDEX|VIEW|WITH|UNION|ALL|INTERSECT|EXCEPT|DISTINCT|AS|AND|OR|NOT|IN|IS|NULL|LIKE|BETWEEN|EXISTS|CASE|WHEN|THEN|ELSE|END|LIMIT|OFFSET|TOP|SET|VALUES|INTO|DECLARE|BEGIN|COMMIT|ROLLBACK|TRUNCATE|MERGE|OVER|BY|ASC|DESC|PRIMARY|KEY|FOREIGN|REFERENCES|DEFAULT|CONSTRAINT|UNIQUE|CHECK|EXEC|EXECUTE|RETURN|IF|ELSE|WHILE|GOTO|PRINT|GO|USE';
    const FUNCTIONS = 'COUNT|SUM|AVG|MAX|MIN|COALESCE|ISNULL|NVL|NULLIF|CAST|CONVERT|CONCAT|UPPER|LOWER|TRIM|LTRIM|RTRIM|SUBSTRING|SUBSTR|LEN|LENGTH|REPLACE|STUFF|CHARINDEX|INSTR|DATEADD|DATEDIFF|DATEPART|DATENAME|GETDATE|GETUTCDATE|NOW|DATE_FORMAT|TO_DATE|TO_CHAR|FORMAT|ROUND|FLOOR|CEILING|ABS|POWER|SQRT|MOD|SIGN|DECODE|IIF|CHOOSE|YEAR|MONTH|DAY|HOUR|MINUTE|SECOND|ROW_NUMBER|RANK|DENSE_RANK|NTILE|LEAD|LAG|FIRST_VALUE|LAST_VALUE|CUME_DIST|PERCENT_RANK|STRING_AGG|LISTAGG|GROUP_CONCAT|PIVOT|UNPIVOT';

    const TOKEN_RE = new RegExp(
        '(--[^\\n]*)'                      +  // 1 однострочный комментарий
        '|(\\/\\*[\\s\\S]*?\\*\\/)'        +  // 2 многострочный комментарий
        "|('(?:[^'\\\\]|\\\\.)*')"         +  // 3 строка в одинарных кавычках
        '|(\\b\\d+(?:\\.\\d+)?\\b)'        +  // 4 число
        '|\\b(' + KEYWORDS  + ')\\b'       +  // 5 ключевые слова
        '|\\b(' + FUNCTIONS + ')(?=\\s*\\()', // 6 функции
        'gi'
    );

    let out = '';
    let last = 0;
    let m;
    TOKEN_RE.lastIndex = 0;

    while ((m = TOKEN_RE.exec(code)) !== null) {
        // текст до совпадения
        out += escapeHtml(code.slice(last, m.index));
        const [full, cmt1, cmt2, str, num, kw, fn] = m;

        if      (cmt1 !== undefined) out += `<span class="sql-comment">${escapeHtml(cmt1)}</span>`;
        else if (cmt2 !== undefined) out += `<span class="sql-comment">${escapeHtml(cmt2)}</span>`;
        else if (str  !== undefined) out += `<span class="sql-string">${escapeHtml(str)}</span>`;
        else if (num  !== undefined) out += `<span class="sql-number">${escapeHtml(num)}</span>`;
        else if (kw   !== undefined) out += `<span class="sql-keyword">${escapeHtml(kw)}</span>`;
        else if (fn   !== undefined) out += `<span class="sql-function">${escapeHtml(fn)}</span>`;
        else                         out += escapeHtml(full);

        last = m.index + full.length;
    }
    out += escapeHtml(code.slice(last));
    return out;
}

// ── Script View Modal ─────────────────────────────────────────────────────────
function openViewModal(item) {
    SCRIPTS_VIEW_ID = item.id;

    const color   = getClientColor(item.client);
    const bgAlpha = color + '18';
    const badge   = document.getElementById('scriptViewClient');
    badge.textContent   = item.client || '-';
    badge.style.background = bgAlpha;
    badge.style.color      = color;

    document.getElementById('scriptViewName').textContent = item.name || 'Без названия';
    document.getElementById('scriptViewDesc').value       = item.description || '';

    const editor    = document.getElementById('scriptViewEditor');
    const highlight = document.getElementById('scriptViewHighlight');

    editor.value        = item.script || '';
    highlight.innerHTML = highlightSQL(item.script || '');

    // Синхронизация скролла
    editor.onscroll = () => {
        highlight.scrollTop  = editor.scrollTop;
        highlight.scrollLeft = editor.scrollLeft;
    };
    // Подсветка при вводе
    editor.oninput = () => {
        highlight.innerHTML = highlightSQL(editor.value);
    };

    document.getElementById('scriptViewModal').style.display = 'flex';
}

function closeViewModal() {
    document.getElementById('scriptViewModal').style.display = 'none';
    SCRIPTS_VIEW_ID = null;
}

async function saveViewModal() {
    if (!SCRIPTS_VIEW_ID) return;
    const idx = SCRIPTS_DB.findIndex(s => s.id === SCRIPTS_VIEW_ID);
    if (idx === -1) return;

    SCRIPTS_DB[idx] = {
        ...SCRIPTS_DB[idx],
        description: document.getElementById('scriptViewDesc').value.trim(),
        script:      document.getElementById('scriptViewEditor').value.trim()
    };

    await saveScriptsDB();
    renderScriptsPage();

    const btn = document.getElementById('scriptViewSave');
    const old = btn.textContent;
    btn.textContent = '✓ Сохранено';
    setTimeout(() => { btn.textContent = old; }, 1500);
}

function getClientColor(client) {
    const map = {
        'DEPO':   '#2563eb',
        'ТСП':    '#ea580c',
        'Верный': '#16a34a',
    };
    // Для остальных - стабильный цвет по хэшу строки
    if (map[client]) return map[client];
    let h = 0;
    for (let i = 0; i < (client||'').length; i++) h = (h * 31 + client.charCodeAt(i)) & 0xffffff;
    const colors = ['#7c3aed','#0891b2','#be123c','#0f766e','#a16207'];
    return colors[h % colors.length];
}

function renderScriptFilters() {
    const container = document.getElementById('scriptClientFilters');
    const clients = [...new Set(SCRIPTS_DB.map(s => s.client).filter(Boolean))].filter(c => c.toLowerCase() !== 'все').sort();
    container.innerHTML = '';

    const makeChip = (label, value) => {
        const btn = document.createElement('button');
        btn.className = 'script-chip' + (SCRIPTS_FILTER_CLIENT === value ? ' active' : '');
        btn.textContent = label;
        btn.onclick = () => { SCRIPTS_FILTER_CLIENT = value; renderScriptsPage(); };
        container.appendChild(btn);
    };
    makeChip('Все', 'all');
    clients.forEach(c => makeChip(c, c));
}

function renderScriptsGrid() {
    const grid = document.getElementById('scriptsGrid');
    let list = SCRIPTS_DB;
    if (SCRIPTS_FILTER_CLIENT !== 'all') list = list.filter(s => s.client === SCRIPTS_FILTER_CLIENT);
    if (SCRIPTS_SEARCH) {
        const q = SCRIPTS_SEARCH.toLowerCase();
        list = list.filter(s =>
            (s.name   || '').toLowerCase().includes(q) ||
            (s.client || '').toLowerCase().includes(q) ||
            (s.script || '').toLowerCase().includes(q)
        );
    }

    grid.innerHTML = '';
    if (!list.length) {
        grid.innerHTML = '<div class="scripts-empty">Нет скриптов - добавьте первый или импортируйте JSON</div>';
        return;
    }

    list.forEach(item => {
        const preview  = (item.script || '').slice(0, 150).replace(/\s+/g, ' ').trimStart();
        const color    = getClientColor(item.client);
        const bgAlpha  = color + '18'; // ~10% opacity

        const card = document.createElement('div');
        card.className = 'script-card';
        card.innerHTML = `
            <div class="script-card-header">
                <span class="script-client-badge" style="background:${bgAlpha};color:${color};">${escapeHtml(item.client || '-')}</span>
                <span class="script-name" title="${escapeHtml(item.name)}">${escapeHtml(item.name || 'Без названия')}</span>
            </div>
            <pre class="script-preview">${escapeHtml(preview)}${item.script?.length > 150 ? '…' : ''}</pre>
            <div class="script-card-footer">
                <button class="script-copy-btn">📋 Копировать</button>
                <button class="script-edit-btn" title="Редактировать">✎</button>
                <button class="script-delete-btn" title="Удалить">🗑</button>
            </div>`;

        card.querySelector('.script-copy-btn').onclick = function(e) {
            e.stopPropagation();
            navigator.clipboard.writeText(item.script || '');
            this.textContent = '✓ Скопировано';
            setTimeout(() => { this.textContent = '📋 Копировать'; }, 1500);
        };
        card.querySelector('.script-edit-btn').onclick = (e) => { e.stopPropagation(); openScriptModal(item); };
        card.querySelector('.script-delete-btn').onclick = (e) => { e.stopPropagation(); deleteScript(item.id); };

        // Клик по карточке (не по кнопкам) → открыть просмотр
        card.addEventListener('click', (e) => {
            if (!e.target.closest('.script-card-footer')) openViewModal(item);
        });

        grid.appendChild(card);
    });
}

function renderScriptsPage() {
    renderScriptFilters();
    renderScriptsGrid();
    // Обновляем датлист клиентов в модале
    updateClientDatalist();
}

function updateClientDatalist() {
    const dl = document.getElementById('scriptClientsList');
    if (!dl) return;
    const existing = [...new Set(SCRIPTS_DB.map(s => s.client).filter(Boolean))];
    const defaults = ['DEPO', 'ТСП', 'Верный'];
    const all = [...new Set([...defaults, ...existing])];
    dl.innerHTML = all.map(c => `<option value="${escapeHtml(c)}">`).join('');
}

async function initScriptsPage() {
    await loadScriptsDB();
    SCRIPTS_FILTER_CLIENT = 'all';
    SCRIPTS_SEARCH        = '';
    document.getElementById('scriptsSearch').value = '';
    renderScriptsPage();

    if (scriptsPageReady) return;
    scriptsPageReady = true;

    document.getElementById('scriptsSearch').oninput = e => {
        SCRIPTS_SEARCH = e.target.value;
        renderScriptsGrid();
    };
    document.getElementById('addScriptBtn').onclick    = () => openScriptModal(null);
    document.getElementById('importScriptsBtn').onclick = () => openImportModal();
    document.getElementById('exportScriptsBtn').onclick = () => exportScripts();

    // Script modal buttons
    document.getElementById('scriptModalSave').onclick   = saveScriptModal;
    document.getElementById('scriptModalCancel').onclick = closeScriptModal;
    document.getElementById('scriptModal').onclick = e => {
        if (e.target === document.getElementById('scriptModal')) closeScriptModal();
    };

    // Import modal buttons
    document.getElementById('importModalConfirm').onclick = doImport;
    document.getElementById('importModalCancel').onclick  = closeImportModal;
    document.getElementById('importModal').onclick = e => {
        if (e.target === document.getElementById('importModal')) closeImportModal();
    };

    // View modal buttons
    document.getElementById('scriptViewClose').onclick  = closeViewModal;
    document.getElementById('scriptViewCancel').onclick = closeViewModal;
    document.getElementById('scriptViewSave').onclick   = saveViewModal;
    document.getElementById('scriptViewCopy').onclick   = function() {
        const val = document.getElementById('scriptViewEditor').value;
        navigator.clipboard.writeText(val);
        this.textContent = '✓ Скопировано';
        setTimeout(() => { this.textContent = '📋 Копировать'; }, 1500);
    };
    document.getElementById('scriptViewModal').onclick = e => {
        if (e.target === document.getElementById('scriptViewModal')) closeViewModal();
    };

    // ESC closes modals
    document.addEventListener('keydown', e => {
        if (e.key === 'Escape') { closeScriptModal(); closeImportModal(); closeViewModal(); }
    });
}

// ── Script modal ────────────────────────────────────────────────────────────
function openScriptModal(item) {
    SCRIPTS_EDIT_ID = item ? item.id : null;
    document.getElementById('scriptModalTitle').textContent = item ? 'Редактировать скрипт' : 'Добавить скрипт';
    document.getElementById('scriptModalClient').value  = item?.client      || '';
    document.getElementById('scriptModalName').value    = item?.name        || '';
    document.getElementById('scriptModalDesc').value    = item?.description || '';
    document.getElementById('scriptModalContent').value = item?.script      || '';
    document.getElementById('scriptModal').style.display = 'flex';
    setTimeout(() => document.getElementById('scriptModalName').focus(), 50);
}

function closeScriptModal() {
    document.getElementById('scriptModal').style.display = 'none';
    SCRIPTS_EDIT_ID = null;
}

async function saveScriptModal() {
    const client      = document.getElementById('scriptModalClient').value.trim();
    const name        = document.getElementById('scriptModalName').value.trim();
    const description = document.getElementById('scriptModalDesc').value.trim();
    const script      = document.getElementById('scriptModalContent').value.trim();

    if (!name) { document.getElementById('scriptModalName').focus(); return; }

    if (SCRIPTS_EDIT_ID) {
        const idx = SCRIPTS_DB.findIndex(s => s.id === SCRIPTS_EDIT_ID);
        if (idx !== -1) SCRIPTS_DB[idx] = { ...SCRIPTS_DB[idx], client, name, description, script };
    } else {
        SCRIPTS_DB.push({ id: `${Date.now()}-${Math.random().toString(36).slice(2)}`, client, name, description, script, createdAt: new Date().toISOString() });
    }
    await saveScriptsDB();
    closeScriptModal();
    renderScriptsPage();
}

async function deleteScript(id) {
    if (!confirm('Удалить скрипт?')) return;
    SCRIPTS_DB = SCRIPTS_DB.filter(s => s.id !== id);
    await saveScriptsDB();
    renderScriptsPage();
}

// ── Import modal ─────────────────────────────────────────────────────────────
function openImportModal() {
    document.getElementById('importModal').style.display = 'flex';
    document.getElementById('importModalText').value = '';
    setTimeout(() => document.getElementById('importModalText').focus(), 50);
}

function closeImportModal() {
    document.getElementById('importModal').style.display = 'none';
}

async function doImport() {
    const raw = document.getElementById('importModalText').value.trim();
    try {
        const parsed = JSON.parse(raw);
        const arr = Array.isArray(parsed) ? parsed : [parsed];
        let added = 0;
        arr.forEach(item => {
            if (item.name !== undefined && item.script !== undefined) {
                SCRIPTS_DB.push({
                    id: `${Date.now()}-${Math.random().toString(36).slice(2)}`,
                    client:    item.client    || '',
                    name:      item.name      || '',
                    script:    item.script    || '',
                    createdAt: new Date().toISOString()
                });
                added++;
            }
        });
        await saveScriptsDB();
        closeImportModal();
        renderScriptsPage();
        alert(`Импортировано: ${added} скрипт(ов)`);
    } catch (e) {
        alert('Ошибка разбора JSON:\n' + e.message);
    }
}

// ── Export ────────────────────────────────────────────────────────────────────
function exportScripts() {
    const clean = SCRIPTS_DB.map(({ id, createdAt, ...rest }) => rest);
    navigator.clipboard.writeText(JSON.stringify(clean, null, 2));
    const btn = document.getElementById('exportScriptsBtn');
    btn.textContent = '✓ Скопировано';
    setTimeout(() => { btn.textContent = '↓ Экспорт'; }, 2000);
}

// ==========================================
// === НАСТРОЙКИ (SETTINGS) ===
// ==========================================

function loadSettings(callback) {
    chrome.storage.sync.get(
        ['alarmEnabled', 'redmineUrls', 'columnNew', 'columnWork', 'columnWait', 'gmailQuery',
         'activityTodayOnly', 'ctxMenuActivity', 'ctxMenuIssues', 'mailCreateBtn',
         'acknowledgedMails', 'acknowledgedIssues', 'refreshInterval',
         'gmailIgnoredPoints', 'magnitUrgentChannel',
         'silentEnabled', 'silentProjects', 'silentSubject'],
        (result) => {
            ALARM_ENABLED = result.alarmEnabled || false;

            if (result.redmineUrls && result.redmineUrls.length > 0) {
                SOURCES.redmineUrls = result.redmineUrls;
            }
            if (result.columnNew)  COLUMN_MAPPING.new  = result.columnNew.split(',').map(s => s.trim()).filter(Boolean);
            if (result.columnWork) COLUMN_MAPPING.work = result.columnWork.split(',').map(s => s.trim()).filter(Boolean);
            if (result.columnWait) COLUMN_MAPPING.wait = result.columnWait.split(',').map(s => s.trim()).filter(Boolean);
            if (result.gmailQuery) GMAIL_QUERY = result.gmailQuery;

            const parsedPoints = parseIgnoredPoints(result.gmailIgnoredPoints);
            if (parsedPoints) GMAIL_IGNORED_POINTS = parsedPoints;

            // Тихие заявки Redmine
            SILENT_ENABLED  = result.silentEnabled  !== undefined ? result.silentEnabled  : true;
            SILENT_PROJECTS = result.silentProjects !== undefined ? parseCsvList(result.silentProjects) : ['Магнит'];
            SILENT_SUBJECT  = result.silentSubject  !== undefined ? parseCsvList(result.silentSubject)  : ['Проверка HS', 'Проверка НS'];

            // Восстанавливаем подтверждённые ID и интервал авто-обновления
            ACKNOWLEDGED_MAILS  = Array.isArray(result.acknowledgedMails)  ? result.acknowledgedMails  : [];
            ACKNOWLEDGED_ISSUES = Array.isArray(result.acknowledgedIssues) ? result.acknowledgedIssues : [];
            _ackMailsSerialized  = JSON.stringify(ACKNOWLEDGED_MAILS);
            _ackIssuesSerialized = JSON.stringify(ACKNOWLEDGED_ISSUES);

            const interval = result.refreshInterval;
            if (interval && interval >= 10) {
                const input = document.getElementById('refreshInterval');
                if (input) input.value = interval;
                startAutoRefresh(interval);
            }

            if (callback) callback();
        }
    );
}

function populateSettingsForm() {
    chrome.storage.sync.get(
        ['alarmEnabled', 'redmineUrls', 'columnNew', 'columnWork', 'columnWait', 'gmailQuery',
         'activityTodayOnly', 'ctxMenuActivity', 'ctxMenuIssues', 'mailCreateBtn',
         'senderProjectMap', 'serverProjectMap', 'sqlAutoPrivate', 'messengerWatcher', 'magnitWatcher',
         'gmailIgnoredPoints', 'magnitUrgentChannel',
         'similarIssuesEnabled', 'redmineApiKey',
         'silentEnabled', 'silentProjects', 'silentSubject'],
        (result) => {
            document.getElementById('settingAlarm').checked = result.alarmEnabled || false;
            document.getElementById('settingActivityTodayOnly').checked =
                result.activityTodayOnly !== undefined ? result.activityTodayOnly : true;
            document.getElementById('settingCtxMenuActivity').checked =
                result.ctxMenuActivity !== undefined ? result.ctxMenuActivity : true;
            document.getElementById('settingCtxMenuIssues').checked =
                result.ctxMenuIssues !== undefined ? result.ctxMenuIssues : true;
            document.getElementById('settingMailCreateBtn').checked =
                result.mailCreateBtn !== undefined ? result.mailCreateBtn : true;
            document.getElementById('settingSqlAutoPrivate').checked =
                result.sqlAutoPrivate !== undefined ? result.sqlAutoPrivate : true;
            document.getElementById('settingMessengerWatcher').checked =
                result.messengerWatcher !== undefined ? result.messengerWatcher : true;
            document.getElementById('settingMagnitWatcher').checked =
                result.magnitWatcher !== undefined ? result.magnitWatcher : true;

            // Маппинги проектов
            renderMappingList('senderMappingList', result.senderProjectMap || DEFAULT_SENDER_MAP);
            renderMappingList('serverMappingList', result.serverProjectMap || DEFAULT_SERVER_MAP);
            document.getElementById('addSenderRowBtn').onclick = () =>
                document.getElementById('senderMappingList').appendChild(createMappingRow('', ''));
            document.getElementById('addServerRowBtn').onclick = () =>
                document.getElementById('serverMappingList').appendChild(createMappingRow('', ''));

            const urls = result.redmineUrls || SOURCES.redmineUrls;
            document.getElementById('settingRedmineUrls').value = urls.join('\n');

            document.getElementById('settingColNew').value  = (result.columnNew  || COLUMN_MAPPING.new.join(', '));
            document.getElementById('settingColWork').value = (result.columnWork || COLUMN_MAPPING.work.join(', '));
            document.getElementById('settingColWait').value = (result.columnWait || COLUMN_MAPPING.wait.join(', '));
            document.getElementById('settingGmailQuery').value = result.gmailQuery || GMAIL_QUERY;

            const ignoredArr = [...(parseIgnoredPoints(result.gmailIgnoredPoints) || GMAIL_IGNORED_POINTS)];
            document.getElementById('settingGmailIgnoredPoints').value = ignoredArr.join(', ');
            document.getElementById('settingMagnitUrgentChannel').value =
                result.magnitUrgentChannel || '<ID канала>';

            document.getElementById('settingSimilarIssues').checked =
                result.similarIssuesEnabled !== undefined ? result.similarIssuesEnabled : true;
            document.getElementById('settingRedmineApiKey').value = result.redmineApiKey || '';

            document.getElementById('settingSilentEnabled').checked =
                result.silentEnabled !== undefined ? result.silentEnabled : true;
            document.getElementById('settingSilentProjects').value =
                result.silentProjects !== undefined ? result.silentProjects : 'Магнит';
            document.getElementById('settingSilentSubject').value =
                result.silentSubject  !== undefined ? result.silentSubject  : 'Проверка HS, Проверка НS';
        }
    );

    // Кнопка сохранения
    const saveBtn = document.getElementById('settingsSaveBtn');
    saveBtn.onclick = saveSettings;
}

function saveSettings() {
    const alarm             = document.getElementById('settingAlarm').checked;
    const activityTodayOnly = document.getElementById('settingActivityTodayOnly').checked;
    const ctxMenuActivity   = document.getElementById('settingCtxMenuActivity').checked;
    const ctxMenuIssues     = document.getElementById('settingCtxMenuIssues').checked;
    const mailCreateBtn     = document.getElementById('settingMailCreateBtn').checked;
    const sqlAutoPrivate      = document.getElementById('settingSqlAutoPrivate').checked;
    const messengerWatcher    = document.getElementById('settingMessengerWatcher').checked;
    const magnitWatcher       = document.getElementById('settingMagnitWatcher').checked;
    const senderProjectMap  = collectMappingRows('senderMappingList');
    const serverProjectMap  = collectMappingRows('serverMappingList');
    const urlsRaw    = document.getElementById('settingRedmineUrls').value;
    const colNew     = document.getElementById('settingColNew').value.trim();
    const colWork    = document.getElementById('settingColWork').value.trim();
    const colWait    = document.getElementById('settingColWait').value.trim();
    const gmailQuery = document.getElementById('settingGmailQuery').value.trim();

    const urls = urlsRaw.split('\n').map(s => s.trim()).filter(Boolean);
    const gmailIgnoredPointsRaw = document.getElementById('settingGmailIgnoredPoints').value.trim();
    const gmailIgnoredPoints    = [...(parseIgnoredPoints(gmailIgnoredPointsRaw) || new Set())];
    const magnitUrgentChannel   = document.getElementById('settingMagnitUrgentChannel').value.trim();
    const similarIssuesEnabled  = document.getElementById('settingSimilarIssues').checked;
    const redmineApiKey         = document.getElementById('settingRedmineApiKey').value.trim();
    const silentEnabled         = document.getElementById('settingSilentEnabled').checked;
    const silentProjects        = document.getElementById('settingSilentProjects').value.trim();
    const silentSubject         = document.getElementById('settingSilentSubject').value.trim();

    chrome.storage.sync.set({
        alarmEnabled:        alarm,
        redmineUrls:         urls,
        columnNew:           colNew,
        columnWork:          colWork,
        columnWait:          colWait,
        gmailQuery:          gmailQuery || GMAIL_QUERY,
        activityTodayOnly:   activityTodayOnly,
        ctxMenuActivity:     ctxMenuActivity,
        ctxMenuIssues:       ctxMenuIssues,
        mailCreateBtn:       mailCreateBtn,
        senderProjectMap:    senderProjectMap,
        serverProjectMap:    serverProjectMap,
        sqlAutoPrivate:      sqlAutoPrivate,
        messengerWatcher:    messengerWatcher,
        magnitWatcher:       magnitWatcher,
        gmailIgnoredPoints:   gmailIgnoredPoints,
        magnitUrgentChannel:  magnitUrgentChannel,
        similarIssuesEnabled: similarIssuesEnabled,
        redmineApiKey:        redmineApiKey,
        silentEnabled:        silentEnabled,
        silentProjects:       silentProjects,
        silentSubject:        silentSubject
    }, () => {
        // Применяем сразу без перезагрузки
        ALARM_ENABLED = alarm;
        if (urls.length > 0) SOURCES.redmineUrls = urls;
        if (colNew)  COLUMN_MAPPING.new  = colNew.split(',').map(s => s.trim()).filter(Boolean);
        if (colWork) COLUMN_MAPPING.work = colWork.split(',').map(s => s.trim()).filter(Boolean);
        if (colWait) COLUMN_MAPPING.wait = colWait.split(',').map(s => s.trim()).filter(Boolean);
        if (gmailQuery) GMAIL_QUERY = gmailQuery;
        if (gmailIgnoredPoints.length > 0) GMAIL_IGNORED_POINTS = new Set(gmailIgnoredPoints);

        // Применяем тихие заявки сразу
        SILENT_ENABLED  = silentEnabled;
        SILENT_PROJECTS = parseCsvList(silentProjects);
        SILENT_SUBJECT  = parseCsvList(silentSubject);

        // Показываем подтверждение
        const msg = document.getElementById('settingsSavedMsg');
        msg.textContent = '✓ Сохранено';
        msg.classList.add('visible');
        setTimeout(() => msg.classList.remove('visible'), 2500);
    });
}

// ============================================================================
// LogViewer - парсер log4j и виртуализированный рендер
// ============================================================================

const LV = {
    inited: false,
    events: [],
    filteredIds: [],
    filteredSet: new Set(),
    flatRows: [],                 // плоский список для рендера: { type:'event'|'tx-header', ... }
    rowHeight: 28,
    bufferRows: 10,
    selectedId: -1,
    // фильтры
    searchQuery: '',
    disabledLevels: new Set(),    // если в Set - level скрыт
    selectedThreads: new Set(),   // пустой Set = «все»
    selectedUsers: new Set(),     // пустой Set = «все»
    threadList: [],
    userList: [],
    searchDebounce: null,
    // время
    minTimestamp: 0,
    maxTimestamp: 0,
    timeFrom: null,               // ms (фильтр)
    timeTo: null,
    // группировка
    groupTx: false,
    groups: [],                   // массив транзакций
    eventToGroup: [],             // eventId -> groupIdx (или -1 если не в группе)
    openGroups: new Set(),        // groupIdx, открытые группы
    // закладки
    bookmarks: new Set(),         // eventId
    fileKey: '',                  // ключ для persist'а закладок (filename + size)
    // ProcedureMapping.csv: nspRFXXX → массив именованных бизнес-полей
    procMappings: {},
};

// Паттерны, которые подсвечиваются как «аномалии» (известные проблемы Forte)
const LV_ANOMALY_PATTERNS = [
    /\bIndexOutOfBoundsException\b/,
    /\bNullPointerException\b/,
    /\bIllegalStateException\b/,
    /\bClassCastException\b/,
    /\bConcurrentModificationException\b/,
    /Exception\s+thrown!?/i,
    /\bqqThrowable\b/,
    /Не\s+Сагрегировано/i,
    /Нет\s+связи\s+с/i,
    /Неверный\s+штрихкод/i,
];

// Паттерны «результата» - сервер шлёт что-то обратно клиенту.
// Самые важные строки для разбора инцидента.
const LV_RESULT_PATTERNS = [
    /\bpResult\s*=/,                          // BuildRFMandatoryResultString / BuildRFResultFromEDO
    /\[process\]::exiting,?\s*data\s*=/,      // финальная отправка в сокет
    /Writing\s+response\s+to\s+socket/i,      // Voice
    /back\s+from\s+remote\s+edo\s*=/i,        // ответ от EJB (промежуточный, но важный)
];

const VSIGN_TIMEOUT_MS = 7 * 60 * 1000; // 7 минут - после этого считаем «нет ответа»

// Парсер ответа V-Sign: одна большая multiline строка вида
//   MarkCodeResponse  validForDelivery=true  errorCode=0  error=null
//   Mark cis=...  normalizedCis=...  gtin=...  status=INTRODUCED
//       productName=...  ownerInn=...  ownerName=...
//       packingVID=Короб  includes=24  group=beer
//           UIT_1
//           UIT_2
//           ...
//   Отработало за N миллисекунд.
function lvParseMarkCodeResponse(msg) {
    if (!msg) return null;
    if (!/MarkCodeResponse/.test(msg)) return null;
    const cisMatch = msg.match(/\bcis\s*=\s*(\S+)/);
    if (!cisMatch) return null;
    const errCode = (msg.match(/errorCode\s*=\s*(\S+)/) || [])[1] || '';
    const errorStr = (msg.match(/error\s*=\s*(\S+)/) || [])[1] || '';
    const validFor = (msg.match(/validForDelivery\s*=\s*(\S+)/) || [])[1] || '';
    const status = (msg.match(/\bstatus\s*=\s*(\S+)/) || [])[1] || '';
    const packingMatch = msg.match(/packingVID\s*=\s*([^\t\r\n]+?)(?=\s\s|\t|$)/);
    const packingVID = packingMatch ? packingMatch[1].trim() : '';
    const incMatch = msg.match(/includes\s*=\s*(\d+)/);
    const includes = incMatch ? parseInt(incMatch[1], 10) : 0;
    const durMatch = msg.match(/Отработало\s+за\s+(\d+)\s+миллисекунд/);
    const duration = durMatch ? parseInt(durMatch[1], 10) : 0;

    // Извлекаем строки UIT (строки после includes=N, со многими отступами,
    // не содержащие "=" и нормальной длины)
    const items = [];
    const lines = msg.split(/\r?\n/);
    let pastIncludes = false;
    for (const line of lines) {
        const t = line.trim();
        if (!t) continue;
        if (/includes\s*=/.test(t)) { pastIncludes = true; continue; }
        if (!pastIncludes) continue;
        if (t.startsWith('Отработало')) break;
        if (/=/.test(t)) continue; // другая meta-строка
        // UIT обычно: 16+ символов, без = , без пробелов
        if (t.length >= 8 && !/\s/.test(t)) items.push(t);
    }

    return {
        cis: cisMatch[1],
        packingVID,
        includes,
        items,
        duration,
        errorCode: errCode,
        error: errorStr,
        validForDelivery: validFor,
        status,
    };
}

// Анализ V-Sign: для каждого CheckMark cis = X должен быть MarkCodeResponse
// с тем же cis в течение 7 минут. Если ответ - Паллета/Короб, то её content
// (вложенные UITs) тоже должен быть проверен - рекурсивно.
function lvAnalyzeVSign() {
    const events = LV.events;
    if (!events.length) return;

    // 1) Сканируем все события, собираем requests и responses
    const requests = [];                    // { cis, eventId, timestamp }
    const responsesByCis = new Map();       // cis → { eventId, timestamp, packingVID, includes, items, ... }

    for (let i = 0; i < events.length; i++) {
        const ev = events[i];
        const msg = ev.message || '';

        // Запрос
        const reqM = /^\s*CheckMark\s+.*?cis\s*=\s*(\S+)/m.exec(msg);
        if (reqM && /MarkCodeResponse/.test(msg) === false) {
            requests.push({ cis: reqM[1], eventId: i, timestamp: ev.timestamp });
        }

        // Ответ
        if (/MarkCodeResponse/.test(msg)) {
            const parsed = lvParseMarkCodeResponse(msg);
            if (parsed && parsed.cis) {
                // Если несколько ответов для одного cis - берём первый (по времени)
                if (!responsesByCis.has(parsed.cis)) {
                    responsesByCis.set(parsed.cis, {
                        ...parsed,
                        eventId: i,
                        timestamp: ev.timestamp,
                    });
                }
            }
        }
    }

    // 2) Для каждого request - найти response, проверить
    const validations = [];
    for (const req of requests) {
        const resp = responsesByCis.get(req.cis);
        const v = {
            cis: req.cis,
            requestEventId: req.eventId,
            responseEventId: resp ? resp.eventId : -1,
            response: resp || null,
            alerts: [],
            ok: true,
        };

        if (!resp) {
            v.alerts.push({ severity: 'error', code: 'NO_RESPONSE', message: 'Нет MarkCodeResponse для cis = ' + req.cis });
            v.ok = false;
        } else {
            // Надёжные проверки:
            //  1) timeout: ответ позже 7 минут после запроса
            //  2) COUNT_MISMATCH: includes != count(items) - главная проверка целостности
            //  3) CHILDREN_NOT_CHECKED - рекурсивно для ЛЮБОГО ответа с items.
            //     Если у child нет своего CheckMark/Response - алерт.
            //     Severity зависит от тайм-окна: если уже прошло > 7 мин
            //     с момента parent-ответа до конца лога - это точно ERROR,
            //     если меньше - WARNING (могло не успеть/лог обрезан).
            // Не проверяем error / errorCode - они могут не заполняться даже в норме.
            const dt = (resp.timestamp || 0) - (req.timestamp || 0);
            if (dt > VSIGN_TIMEOUT_MS || dt < 0) {
                v.alerts.push({ severity: 'error', code: 'TIMEOUT', message: 'Ответ позже чем 7 мин (Δ=' + Math.round(dt / 1000) + ' с)' });
                v.ok = false;
            }
            if (resp.includes !== resp.items.length) {
                v.alerts.push({
                    severity: 'error',
                    code: 'COUNT_MISMATCH',
                    message: 'includes=' + resp.includes + ', но в теле ответа ' + resp.items.length + ' UIT - расхождение',
                });
                v.ok = false;
            }
            // Рекурсивная проверка children:
            //  - Короб содержит листовые марки (UIT), которые отдельно через
            //    V-Sign не сканируются → пропускаем рекурсию.
            //  - Паллета или packingVID не задан → проверяем, что для каждого
            //    вложенного UIT есть свой CheckMark+Response в логе.
            const isBox = /(короб|box)/i.test(resp.packingVID || '');
            if (!isBox && resp.items.length > 0) {
                const missing = [];
                for (const childCis of resp.items) {
                    if (!responsesByCis.has(childCis)) missing.push(childCis);
                }
                if (missing.length) {
                    // Если прошло > 7 мин от parent-ответа до конца лога -
                    // точно ошибка. Иначе предупреждение (лог обрезан/не успели).
                    const respTs = resp.timestamp || 0;
                    const lastTs = LV.maxTimestamp || respTs;
                    const elapsed = lastTs - respTs;
                    const isHardError = elapsed > VSIGN_TIMEOUT_MS;
                    v.alerts.push({
                        severity: isHardError ? 'error' : 'warning',
                        code: 'CHILDREN_NOT_CHECKED',
                        message: (isHardError ? '7 минут прошло, но ' : '') +
                            'для ' + missing.length + ' из ' + resp.items.length +
                            ' вложенных UIT не нашлось CheckMark+Response в логе' +
                            (isHardError ? '' : ' (возможно, лог обрезан или ещё не успели проверить)'),
                        missing,
                    });
                    v.ok = false;
                }
            }
        }

        validations.push(v);

        // Помечаем события с проблемами
        if (!v.ok) {
            const reqEv = events[req.eventId];
            if (reqEv) {
                reqEv._vsignAlert = {
                    severity: v.alerts.some(a => a.severity === 'error') ? 'error' : 'warning',
                    cis: req.cis,
                    alerts: v.alerts,
                };
            }
            if (resp && resp.eventId >= 0) {
                events[resp.eventId]._vsignAlert = {
                    severity: v.alerts.some(a => a.severity === 'error') ? 'error' : 'warning',
                    cis: req.cis,
                    alerts: v.alerts,
                    isResponse: true,
                };
            }
        }
    }

    // Также проверим: есть ли response без request (странно, но возможно)
    for (const [cis, resp] of responsesByCis) {
        const hasReq = requests.some(r => r.cis === cis);
        if (!hasReq) {
            events[resp.eventId]._vsignAlert = {
                severity: 'warning',
                cis,
                alerts: [{ severity: 'warning', code: 'NO_REQUEST', message: 'MarkCodeResponse без предшествующего CheckMark' }],
                isResponse: true,
            };
        }
    }

    // Сохраняем в LV для использования в detail panel
    LV.vsignValidations = validations;
    LV.vsignResponses = responsesByCis;

    // Краткая статистика для лога
    const errCount = validations.filter(v => v.alerts.some(a => a.severity === 'error')).length;
    const warnCount = validations.filter(v => v.alerts.some(a => a.severity === 'warning') && !v.alerts.some(a => a.severity === 'error')).length;
    if (validations.length) {
        try { console.log('[LV V-Sign] requests:', validations.length, 'errors:', errCount, 'warnings:', warnCount); } catch (e) {}
    }
}

// ── Storage helpers ──────────────────────────────────────────────────
const LV_STORAGE_KEY = 'lvSettings';

function lvLoadSettings() {
    return new Promise((resolve) => {
        try {
            chrome.storage.local.get([LV_STORAGE_KEY], (data) => resolve(data[LV_STORAGE_KEY] || {}));
        } catch (e) { resolve({}); }
    });
}

function lvSaveSetting(key, value) {
    try {
        chrome.storage.local.get([LV_STORAGE_KEY], (data) => {
            const s = data[LV_STORAGE_KEY] || {};
            s[key] = value;
            chrome.storage.local.set({ [LV_STORAGE_KEY]: s });
        });
    } catch (e) { /* no-op */ }
}

let lvSaveSettingsDebounce = null;
function lvSaveSettingDebounced(key, value) {
    clearTimeout(lvSaveSettingsDebounce);
    lvSaveSettingsDebounce = setTimeout(() => lvSaveSetting(key, value), 300);
}

function lvLoadBookmarks(fileKey) {
    return new Promise((resolve) => {
        try {
            const k = 'lvBookmarks_' + fileKey;
            chrome.storage.local.get([k], (data) => {
                LV.bookmarks = new Set(data[k] || []);
                resolve();
            });
        } catch (e) { resolve(); }
    });
}

function lvSaveBookmarks() {
    if (!LV.fileKey) return;
    try {
        chrome.storage.local.set({ ['lvBookmarks_' + LV.fileKey]: Array.from(LV.bookmarks) });
    } catch (e) { /* no-op */ }
}

// Парсер ProcedureMapping.csv. Структура каждой строки:
//   nspRFXXX;package;class;step;...;sendArgs(comma-separated)
// Из sendArgs пропускаем первые 8 mandatory (sendDelimiter, ptcid, userid, taskId,
// databasename, appflag, recordType, server) - остальное это бизнес-поля,
// которые мы хотим показывать как имена аргументов EXEC.
function lvParseProcMappingsCsv(csv) {
    const map = {};
    const lines = csv.split(/\r?\n/);
    for (const line of lines) {
        if (!line.trim() || line.startsWith('#')) continue;
        const fields = line.split(';');
        if (fields.length < 8) continue;
        const procName = (fields[0] || '').trim().toUpperCase();
        if (!procName.startsWith('NSPRF') && !procName.startsWith('nspRF')) continue;
        const argsStr = fields[7] || '';
        const allArgs = argsStr.split(',').map(s => s.trim()).filter(Boolean);
        // Берём только бизнес-поля (после 8 mandatory)
        const businessArgs = allArgs.length > 8 ? allArgs.slice(8) : [];
        map[procName] = businessArgs;
    }
    return map;
}

function lvLoadProcMappings() {
    return new Promise((resolve) => {
        try {
            chrome.storage.local.get(['lvProcMappings'], (data) => {
                LV.procMappings = data.lvProcMappings || {};
                resolve();
            });
        } catch (e) { resolve(); }
    });
}

function lvSaveProcMappings(map) {
    try {
        chrome.storage.local.set({ lvProcMappings: map });
    } catch (e) { /* no-op */ }
}

function lvUpdateMappingLabel() {
    const label = document.getElementById('lvMappingLabel');
    const btn = document.getElementById('lvLoadMappingBtn');
    if (!label || !btn) return;
    const count = Object.keys(LV.procMappings || {}).length;
    if (count > 0) {
        label.textContent = 'Mapping ✓ ' + count;
        btn.classList.add('active');
        btn.title = 'Загружено ' + count + ' процедур из ProcedureMapping.csv. Кликни чтобы заменить.';
    } else {
        label.textContent = 'Mapping';
        btn.classList.remove('active');
        btn.title = 'Загрузить ProcedureMapping.csv';
    }
}

async function initLogViewer() {
    if (LV.inited) return;
    LV.inited = true;

    // Восстанавливаем сохранённые настройки (ширины, groupTx, выключенные levels)
    const saved = await lvLoadSettings();
    if (saved.colWidths) {
        const root = document.getElementById('lvTableWrap');
        for (const [col, w] of Object.entries(saved.colWidths)) {
            root.style.setProperty('--lv-w-' + col, w + 'px');
        }
    }
    if (saved.groupTx) {
        LV.groupTx = true;
        document.getElementById('lvGroupTx').checked = true;
    }
    if (Array.isArray(saved.disabledLevels)) {
        LV.disabledLevels = new Set(saved.disabledLevels);
        for (const lvl of saved.disabledLevels) {
            const btn = document.querySelector('.lv-lvl-btn[data-level="' + lvl + '"]');
            if (btn) btn.classList.remove('active');
        }
    }

    const loadBtn = document.getElementById('lvLoadBtn');
    const fileInput = document.getElementById('lvFileInput');
    const scroll = document.getElementById('lvScroll');
    const detailClose = document.getElementById('lvDetailClose');

    loadBtn.addEventListener('click', () => fileInput.click());
    fileInput.addEventListener('change', (e) => {
        const f = e.target.files && e.target.files[0];
        if (f) lvLoadFile(f);
        fileInput.value = '';
    });

    // ── Drag-and-drop загрузка файла ─────────────────────────────────
    const dropZone = document.getElementById('logsContainer');
    let dragCounter = 0;
    dropZone.addEventListener('dragenter', (e) => {
        if (!e.dataTransfer || !e.dataTransfer.types.includes('Files')) return;
        e.preventDefault();
        dragCounter++;
        dropZone.classList.add('lv-drag-over');
    });
    dropZone.addEventListener('dragleave', (e) => {
        dragCounter = Math.max(0, dragCounter - 1);
        if (dragCounter === 0) dropZone.classList.remove('lv-drag-over');
    });
    dropZone.addEventListener('dragover', (e) => {
        if (!e.dataTransfer || !e.dataTransfer.types.includes('Files')) return;
        e.preventDefault();
    });
    dropZone.addEventListener('drop', (e) => {
        e.preventDefault();
        dragCounter = 0;
        dropZone.classList.remove('lv-drag-over');
        const f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
        if (f) lvLoadFile(f);
    });

    scroll.addEventListener('scroll', () => {
        lvRenderRows();
        lvUpdateStickyHeader();
    });
    window.addEventListener('resize', () => { lvRenderRows(); lvDrawTimeline(); });

    // Клик на sticky-заголовок - toggle той же группы
    document.getElementById('lvStickyHeader').addEventListener('click', () => {
        const sticky = document.getElementById('lvStickyHeader');
        const gid = parseInt(sticky.dataset.group, 10);
        if (!isNaN(gid)) lvToggleGroup(gid);
    });
    detailClose.addEventListener('click', () => {
        document.getElementById('lvDetail').style.display = 'none';
        LV.selectedId = -1;
        lvRenderRows();
    });

    // Клик на ссылку «→ строка #N» в V-Sign секции - переход
    document.getElementById('lvDetail').addEventListener('click', (e) => {
        const link = e.target.closest('.lv-vsign-link');
        if (!link) return;
        const id = parseInt(link.dataset.jump, 10);
        if (!isNaN(id)) lvJumpToEvent(id);
    });

    // ── Фильтры ────────────────────────────────────────────────────────
    const search = document.getElementById('lvSearch');
    const searchClear = document.getElementById('lvSearchClear');
    search.addEventListener('input', () => {
        searchClear.style.display = search.value ? 'flex' : 'none';
        clearTimeout(LV.searchDebounce);
        LV.searchDebounce = setTimeout(() => {
            LV.searchQuery = search.value.trim().toLowerCase();
            lvApplyFilters();
        }, 180);
    });
    search.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && search.value) {
            search.value = '';
            searchClear.style.display = 'none';
            LV.searchQuery = '';
            lvApplyFilters();
        }
    });
    searchClear.addEventListener('click', () => {
        search.value = '';
        searchClear.style.display = 'none';
        LV.searchQuery = '';
        lvApplyFilters();
        search.focus();
    });

    // Level toggles
    document.getElementById('lvLevelFilters').addEventListener('click', (e) => {
        const btn = e.target.closest('.lv-lvl-btn');
        if (!btn) return;
        const lvl = btn.dataset.level;
        if (LV.disabledLevels.has(lvl)) {
            LV.disabledLevels.delete(lvl);
            btn.classList.add('active');
        } else {
            LV.disabledLevels.add(lvl);
            btn.classList.remove('active');
        }
        lvSaveSetting('disabledLevels', Array.from(LV.disabledLevels));
        lvApplyFilters();
    });

    // Thread dropdown
    const threadBtn = document.getElementById('lvThreadBtn');
    const threadPopup = document.getElementById('lvThreadPopup');
    const threadSearch = document.getElementById('lvThreadSearch');
    const threadAll = document.getElementById('lvThreadAll');
    const threadNone = document.getElementById('lvThreadNone');
    const threadList = document.getElementById('lvThreadList');

    threadBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        const opening = threadPopup.style.display === 'none';
        threadPopup.style.display = opening ? 'flex' : 'none';
        if (opening) {
            threadSearch.value = '';
            lvRenderThreadList('');
            setTimeout(() => threadSearch.focus(), 0);
        }
    });
    document.addEventListener('click', (e) => {
        if (!threadPopup.contains(e.target) && e.target !== threadBtn && !threadBtn.contains(e.target)) {
            threadPopup.style.display = 'none';
        }
    });
    threadSearch.addEventListener('input', () => lvRenderThreadList(threadSearch.value));
    threadAll.addEventListener('click', () => {
        LV.selectedThreads.clear();
        lvUpdateThreadLabel();
        lvRenderThreadList(threadSearch.value);
        lvApplyFilters();
    });
    threadNone.addEventListener('click', () => {
        // «Сбросить» = ничего не выбрано - показывать пустоту? Лучше сделать: переключить в режим «всё»
        LV.selectedThreads.clear();
        lvUpdateThreadLabel();
        lvRenderThreadList(threadSearch.value);
        lvApplyFilters();
    });
    threadList.addEventListener('change', (e) => {
        const cb = e.target.closest('input[type=checkbox]');
        if (!cb) return;
        const t = cb.value;
        if (cb.checked) {
            LV.selectedThreads.add(t);
        } else {
            LV.selectedThreads.delete(t);
        }
        lvUpdateThreadLabel();
        lvApplyFilters();
    });

    // Reset all
    document.getElementById('lvFilterReset').addEventListener('click', () => {
        search.value = '';
        searchClear.style.display = 'none';
        LV.searchQuery = '';
        LV.disabledLevels.clear();
        LV.selectedThreads.clear();
        LV.selectedUsers.clear();
        LV.timeFrom = null;
        LV.timeTo = null;
        document.getElementById('lvTimeFrom').value = '';
        document.getElementById('lvTimeTo').value = '';
        document.querySelectorAll('.lv-lvl-btn').forEach(b => b.classList.add('active'));
        lvUpdateThreadLabel();
        lvRenderThreadList('');
        lvUpdateUserLabel();
        lvRenderUserList('');
        lvSaveSetting('disabledLevels', []);
        lvApplyFilters();
    });

    // Group transactions toggle
    document.getElementById('lvGroupTx').addEventListener('change', (e) => {
        LV.groupTx = e.target.checked;
        if (LV.groupTx && LV.groups.length === 0) {
            lvBuildGroups();
        }
        LV.openGroups.clear();
        lvSaveSetting('groupTx', LV.groupTx);
        lvApplyFilters();
    });

    // ── User dropdown (как Thread, но по userId) ────────────────────
    const userBtn = document.getElementById('lvUserBtn');
    const userPopup = document.getElementById('lvUserPopup');
    const userSearch = document.getElementById('lvUserSearch');
    const userAll = document.getElementById('lvUserAll');
    const userListEl = document.getElementById('lvUserList');

    userBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        const opening = userPopup.style.display === 'none';
        userPopup.style.display = opening ? 'flex' : 'none';
        if (opening) {
            userSearch.value = '';
            lvRenderUserList('');
            setTimeout(() => userSearch.focus(), 0);
        }
    });
    document.addEventListener('click', (e) => {
        if (!userPopup.contains(e.target) && e.target !== userBtn && !userBtn.contains(e.target)) {
            userPopup.style.display = 'none';
        }
    });
    userSearch.addEventListener('input', () => lvRenderUserList(userSearch.value));
    userAll.addEventListener('click', () => {
        LV.selectedUsers.clear();
        lvUpdateUserLabel();
        lvRenderUserList(userSearch.value);
        lvApplyFilters();
    });
    userListEl.addEventListener('change', (e) => {
        const cb = e.target.closest('input[type=checkbox]');
        if (!cb) return;
        const u = cb.value;
        if (cb.checked) LV.selectedUsers.add(u); else LV.selectedUsers.delete(u);
        lvUpdateUserLabel();
        lvApplyFilters();
    });

    // ── Time range filter ──────────────────────────────────────────
    const timeFromInput = document.getElementById('lvTimeFrom');
    const timeToInput = document.getElementById('lvTimeTo');
    let timeDebounce = null;
    const onTimeChange = () => {
        clearTimeout(timeDebounce);
        timeDebounce = setTimeout(() => {
            LV.timeFrom = lvParseTime(timeFromInput.value);
            LV.timeTo = lvParseTime(timeToInput.value);
            lvApplyFilters();
        }, 250);
    };
    timeFromInput.addEventListener('input', onTimeChange);
    timeToInput.addEventListener('input', onTimeChange);

    // ── Bookmarks popup ────────────────────────────────────────────
    const bmBtn = document.getElementById('lvBookmarksBtn');
    const bmPopup = document.getElementById('lvBookmarksPopup');
    const bmList = document.getElementById('lvBookmarksList');
    const bmClear = document.getElementById('lvBookmarksClear');
    bmBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        const opening = bmPopup.style.display === 'none';
        bmPopup.style.display = opening ? 'flex' : 'none';
        if (opening) lvRenderBookmarksList();
    });
    document.addEventListener('click', (e) => {
        if (!bmPopup.contains(e.target) && e.target !== bmBtn && !bmBtn.contains(e.target)) {
            bmPopup.style.display = 'none';
        }
    });
    bmClear.addEventListener('click', () => {
        LV.bookmarks.clear();
        lvSaveBookmarks();
        lvUpdateBookmarksCount();
        lvRenderBookmarksList();
        lvRenderRows();
    });
    bmList.addEventListener('click', (e) => {
        const item = e.target.closest('.lv-bm-item');
        if (!item) return;
        const id = parseInt(item.dataset.id, 10);
        if (e.target.closest('.lv-bm-remove')) {
            LV.bookmarks.delete(id);
            lvSaveBookmarks();
            lvUpdateBookmarksCount();
            lvRenderBookmarksList();
            lvRenderRows();
            return;
        }
        lvJumpToEvent(id);
        bmPopup.style.display = 'none';
    });

    // ── Hotkeys ─────────────────────────────────────────────────────
    document.addEventListener('keydown', (e) => {
        if (document.getElementById('logsContainer').style.display === 'none') return;
        // Не вмешиваемся, если фокус в input
        const inInput = e.target.matches('input, textarea');
        if (e.key === 'b' && !inInput && LV.selectedId >= 0) {
            lvToggleBookmark(LV.selectedId);
            e.preventDefault();
        }
    });

    // ── Resize колонок ──────────────────────────────────────────────
    lvSetupResizers();

    // Горизонтальный скролл - синхронизируем header с контентом
    scroll.addEventListener('scroll', () => {
        const header = document.getElementById('lvTableHeader');
        header.style.transform = 'translateX(' + (-scroll.scrollLeft) + 'px)';
    });

    // ── Mini-timeline ───────────────────────────────────────────────
    lvSetupTimeline();
}

// Парсит "HH:MM:SS" / "HH:MM" в timestamp на ту же дату что minTimestamp файла.
function lvParseTime(str) {
    if (!str) return null;
    str = str.trim();
    if (!str) return null;
    const m = str.match(/^(\d{1,2}):(\d{2})(?::(\d{2}))?(?:\.(\d{1,3}))?$/);
    if (!m || !LV.minTimestamp) return null;
    const base = new Date(LV.minTimestamp);
    base.setHours(parseInt(m[1], 10), parseInt(m[2], 10), m[3] ? parseInt(m[3], 10) : 0, m[4] ? parseInt(m[4].padEnd(3, '0'), 10) : 0);
    return base.getTime();
}

// Минимальные ширины колонок (нельзя ужать сильнее)
const LV_COL_MIN = { num: 50, time: 90, level: 70, thread: 80, cat: 100, msg: 200 };

function lvSetupResizers() {
    const root = document.getElementById('lvTableWrap');
    let dragging = null;
    let startX = 0;
    let startW = 0;

    document.querySelectorAll('.lv-resizer').forEach(rs => {
        rs.addEventListener('mousedown', (e) => {
            e.preventDefault();
            e.stopPropagation();
            dragging = rs.dataset.col;
            startX = e.clientX;
            const v = getComputedStyle(root).getPropertyValue('--lv-w-' + dragging);
            startW = parseInt(v, 10) || 100;
            document.body.classList.add('lv-resizing-active');
            rs.classList.add('lv-resizing');
        });
    });

    document.addEventListener('mousemove', (e) => {
        if (!dragging) return;
        const min = LV_COL_MIN[dragging] || 40;
        const w = Math.max(min, startW + (e.clientX - startX));
        root.style.setProperty('--lv-w-' + dragging, w + 'px');
        lvUpdateLayout();
        // Re-render rows: ширины ячеек обновятся автоматически (CSS variables),
        // но чтобы absolute-rows растянулись по новой ширине spacer'а - рендерим заново.
        lvRenderRows();
    });

    document.addEventListener('mouseup', () => {
        if (!dragging) return;
        document.querySelectorAll('.lv-resizer.lv-resizing').forEach(rs => rs.classList.remove('lv-resizing'));
        document.body.classList.remove('lv-resizing-active');
        dragging = null;
        // Persist ширины
        const root = document.getElementById('lvTableWrap');
        const cs = getComputedStyle(root);
        const widths = {};
        for (const c of ['num','time','level','thread','cat','msg']) {
            widths[c] = parseInt(cs.getPropertyValue('--lv-w-' + c), 10) || 0;
        }
        lvSaveSettingDebounced('colWidths', widths);
    });
}

// Считает суммарную ширину колонок и применяет её на header + spacer,
// чтобы появлялся горизонтальный скролл при недостатке места.
function lvUpdateLayout() {
    const root = document.getElementById('lvTableWrap');
    if (!root) return;
    const cs = getComputedStyle(root);
    const cols = ['num', 'time', 'level', 'thread', 'cat', 'msg'];
    let total = 0;
    for (const c of cols) total += parseInt(cs.getPropertyValue('--lv-w-' + c), 10) || 0;

    const header = document.getElementById('lvTableHeader');
    const spacer = document.getElementById('lvSpacer');
    if (header) header.style.width = total + 'px';
    if (spacer) spacer.style.width = total + 'px';
}

// ── Группировка событий в транзакции ─────────────────────────────────
//
// Маркер начала: [processInput]::readBuffer = EXEC nsp...
// Маркер конца:  [process]::exiting, data = ...
// Привязка событий: rfListenerAgent_NN (если упомянут в сообщении или thread)
// либо просто thread name. Между маркерами все события одного исполнителя
// складываются в одну транзакцию.
// Извлекаем taskId из любых служебных строк лога: EXEC nsp..., pResult = ..., theArgs = ...
// Структура: ` 12`<userid>`<taskId>`<sessionId>`<appflag>`...
function lvExtractTaskId(msg) {
    if (!msg) return null;
    const m = msg.match(/(?:EXEC\s+nsp\w+|pResult\s*=|theArgs\s*=|sqlStatemet\s*=\s*EXEC\s+nsp\w+|readBuffer\s*=\s*EXEC\s+nsp\w+)\s*`?\s*\d+`[^`]+`(\d{1,8})`/i);
    return m ? m[1] : null;
}

// Извлекает {userId, taskId} из служебных строк, если они там есть.
function lvExtractTxMeta(msg) {
    if (!msg) return { userId: '', taskId: '' };
    const m = msg.match(/(?:EXEC\s+nsp\w+|pResult\s*=|theArgs\s*=|sqlStatemet\s*=\s*EXEC\s+nsp\w+|readBuffer\s*=\s*EXEC\s+nsp\w+)\s*`?\s*\d+`([^`]+)`(\d{1,8})`/i);
    if (!m) return { userId: '', taskId: '' };
    return { userId: m[1].trim(), taskId: m[2].trim() };
}

// Полный разбор аргументов EXEC (для detail panel).
// Структура: EXEC nspRFXXX ` 12`userid`taskid`db`appflag`recordType`ip`arg1`arg2`...`CHECKSUM`EOS
function lvParseExecArgs(msg) {
    if (!msg) return null;
    // Берём подстроку начиная с EXEC nspXXX
    const start = msg.search(/EXEC\s+nsp/i);
    if (start === -1) return null;
    const tail = msg.substring(start);
    const procMatch = tail.match(/^EXEC\s+(nsp\w+)\s*`?\s*/i);
    if (!procMatch) return null;
    const after = tail.substring(procMatch[0].length);
    // Удаляем `CHECKSUM`EOS если есть
    const cleaned = after.replace(/`CHECKSUM`EOS\s*$/i, '');
    const parts = cleaned.split('`');
    return {
        procName: procMatch[1],
        msgVer: parts[0] || '',
        userId: parts[1] || '',
        taskId: parts[2] || '',
        database: parts[3] || '',
        appFlag: parts[4] || '',
        recordType: parts[5] || '',
        ip: parts[6] || '',
        rawArgs: parts.slice(7),
    };
}

// Разбор pResult / [process]::exiting data - то, что сервер вернул клиенту.
// Структура: <msgVer>`<userid>`<taskid>`<db>`<appflag>`<recordType>`<ip>`<errorMsg>`<returnCode>`<data1>`<data2>`...
// Например: 1`<userid>`<taskid>`<db>`<appflag>`<recordType>`<ip>`No Error`1`STORER`143498`Макароны Barilla...`14`EA`...
function lvParsePResult(msg) {
    if (!msg) return null;
    // Ищем "pResult = ..." | "data = ..." | "Writing response to socket: ..."
    const m = msg.match(/(?:pResult\s*=|data\s*=|response\s+to\s+socket\s*:)\s*([^\r\n]+?)(?:`CHECKSUM`EOS)?\s*$/i);
    if (!m) return null;
    const body = m[1].trim();
    // Должен начинаться с числа (msgVer)
    if (!/^\d+`/.test(body)) return null;
    const parts = body.split('`');
    if (parts.length < 8) return null;
    return {
        msgVer: parts[0] || '',
        userId: parts[1] || '',
        taskId: parts[2] || '',
        database: parts[3] || '',
        appFlag: parts[4] || '',
        recordType: parts[5] || '',
        ip: parts[6] || '',
        errorMsg: parts[7] || '',
        returnCode: parts[8] || '',
        data: parts.slice(9),
    };
}

// Парсит из строки лога метаданные транзакции. Универсальный матчер:
// ловит EXEC nsp..., processStream::data = EXEC..., pResult = ..., theArgs = ..., [process]::exiting data = ...
// Возвращает { procName, userId, taskId } или null.
function lvExtractFullMeta(msg) {
    if (!msg) return null;
    // Сначала пытаемся выцепить с procName (где есть EXEC nsp...)
    let m = msg.match(/EXEC\s+(nsp\w+)\s*`?\s*\d+`([^`]+)`(\d{1,8})`/i);
    if (m) return { procName: m[1], userId: m[2].trim(), taskId: m[3].trim() };
    // procName нет, но есть «`12`user`taskid`» - например в pResult/theArgs/exiting data
    m = msg.match(/(?:pResult\s*=|theArgs\s*=|data\s*=)\s*\d+`([^`]+)`(\d{1,8})`/i);
    if (m) return { procName: '', userId: m[1].trim(), taskId: m[2].trim() };
    return null;
}

function lvBuildGroups() {
    const events = LV.events;
    const groups = [];
    const eventToGroup = new Array(events.length).fill(-1);

    // Активные группы:
    //  - byTaskKey: 'userId:taskId' → groupIdx (главный ключ - переживает смену thread/agent)
    //  - byExecKey: 'agent-NN' / 'thread-X' → groupIdx (fallback для строк без taskId)
    //  - pending: execKey → массив eventIdx, ждущих привязки к группе.
    //    Случай: транзакция переезжает в новый execKey, и первые служебные строки
    //    в нём (ExecProcessor.constructor, processStream::entered и т.п.)
    //    приходят БЕЗ taskKey раньше, чем строка с EXEC nsp... которая привязала
    //    бы execKey к группе. Эти строки накапливаются в pending и ретроактивно
    //    добавляются к группе, как только приходит первое событие с taskKey.
    const byTaskKey = new Map();
    const byExecKey = new Map();
    const pending = new Map();
    const PENDING_MAX = 50;        // защита от бесконечного буфера
    const TX_TIMEOUT_MS = 60_000;

    const computeExecKey = (ev) => {
        const msg = ev.message || '';
        const a1 = msg.match(/rfListenerAgent_(\d+)/);
        if (a1) return 'agent-' + a1[1];
        const a2 = (ev.thread || '').match(/rfListenerAgent_(\d+)/);
        if (a2) return 'agent-' + a2[1];
        return 'thread-' + (ev.thread || 'unknown');
    };

    const newGroup = (eventIdx, ev, meta, execKey) => {
        const procName = (meta && meta.procName) || '';
        const taskId = (meta && meta.taskId) || '';
        const userId = (meta && meta.userId) || '';
        const grpIdx = groups.length;
        groups.push({
            eventIds: [eventIdx],
            procName: procName || '(unknown)',
            userId,
            taskId,
            sessionId: '',
            startTime: ev.timestamp,
            endTime: ev.timestamp,
            lastSeen: ev.timestamp,
            complete: false,
            hasError: false,
            mismatchCount: 0,
            execKey,
            execKeys: new Set([execKey]),  // ВСЕ execKey'и, в которых группа побывала
            taskKey: userId && taskId ? userId + ':' + taskId : '',
        });
        eventToGroup[eventIdx] = grpIdx;
        if (ev.level === 'ERROR' || ev.level === 'FATAL' || ev.throwable) groups[grpIdx].hasError = true;
        return grpIdx;
    };

    const addToGroup = (grpIdx, eventIdx, ev, meta, execKey) => {
        const grp = groups[grpIdx];
        grp.eventIds.push(eventIdx);
        grp.lastSeen = ev.timestamp || grp.lastSeen;
        grp.endTime = ev.timestamp || grp.endTime;
        if (ev.level === 'ERROR' || ev.level === 'FATAL' || ev.throwable) grp.hasError = true;
        eventToGroup[eventIdx] = grpIdx;
        if (meta && meta.procName && grp.procName === '(unknown)') {
            grp.procName = meta.procName;
        }
        if (execKey) grp.execKeys.add(execKey);
    };

    const closeGroup = (grpIdx, complete) => {
        const grp = groups[grpIdx];
        grp.complete = complete;
        grp.duration = (grp.endTime - grp.startTime) || 0;
        if (grp.taskKey && byTaskKey.get(grp.taskKey) === grpIdx) byTaskKey.delete(grp.taskKey);
        // Стираем ВСЕ execKey-ссылки на эту группу (а не только исходный execKey).
        // Группа за свою жизнь могла быть в нескольких agent-NN/thread-X - каждый
        // из них при закрытии надо отвязать, иначе следующее событие без taskId
        // в этом execKey приклеится к уже закрытой группе.
        if (grp.execKeys) {
            for (const k of grp.execKeys) {
                if (byExecKey.get(k) === grpIdx) byExecKey.delete(k);
            }
        }
    };

    const pushSingle = (eventIdx) => {
        const grpIdx = groups.length;
        eventToGroup[eventIdx] = grpIdx;
        groups.push({ eventIds: [eventIdx], single: true });
    };

    // Прицепить накопленные pending этого execKey к существующей группе grpIdx.
    // Вызывается когда мы наконец-то узнали, в какую группу относятся «бесхозные»
    // строки этого execKey - благодаря пришедшему событию с taskKey.
    const flushPendingToGroup = (execKey, grpIdx) => {
        const arr = pending.get(execKey);
        if (!arr || !arr.length) return;
        const grp = groups[grpIdx];
        for (const eId of arr) {
            grp.eventIds.push(eId);
            eventToGroup[eId] = grpIdx;
            const ev = events[eId];
            if (ev && (ev.level === 'ERROR' || ev.level === 'FATAL' || ev.throwable)) grp.hasError = true;
        }
        // Сортируем по индексу (eventIds должен быть в хронологическом порядке)
        grp.eventIds.sort((a, b) => a - b);
        grp.execKeys.add(execKey);
        pending.delete(execKey);
    };

    // Слить pending в singletons (нет подходящей группы - пусть будут одиночными)
    const flushPendingToSingles = (execKey) => {
        const arr = pending.get(execKey);
        if (!arr || !arr.length) return;
        for (const eId of arr) pushSingle(eId);
        pending.delete(execKey);
    };

    for (let i = 0; i < events.length; i++) {
        const ev = events[i];
        const msg = ev.message || '';
        const execKey = computeExecKey(ev);
        const meta = lvExtractFullMeta(msg);
        const taskKey = meta && meta.userId && meta.taskId ? meta.userId + ':' + meta.taskId : '';
        const isEnd = /^\[process\]::exiting/i.test(msg);

        // 1) Закрытие транзакции - предпочитаем по taskKey, иначе по execKey
        if (isEnd) {
            let target = -1;
            if (taskKey && byTaskKey.has(taskKey)) target = byTaskKey.get(taskKey);
            else if (byExecKey.has(execKey)) target = byExecKey.get(execKey);
            if (target >= 0) {
                addToGroup(target, i, ev, meta, execKey);
                closeGroup(target, true);
                continue;
            }
            pushSingle(i);
            continue;
        }

        // 2) Если у события есть taskKey - это надёжный sign транзакции, склеиваем по нему
        if (taskKey) {
            if (byTaskKey.has(taskKey)) {
                const grpIdx = byTaskKey.get(taskKey);
                const grp = groups[grpIdx];
                if (ev.timestamp && grp.startTime && (ev.timestamp - grp.startTime > TX_TIMEOUT_MS)) {
                    closeGroup(grpIdx, false);
                    // pending в этом execKey - orphan'ы старой эпохи → singletons
                    flushPendingToSingles(execKey);
                    const newIdx = newGroup(i, ev, meta, execKey);
                    byTaskKey.set(taskKey, newIdx);
                    byExecKey.set(execKey, newIdx);
                } else {
                    // Сначала прикрепляем накопленные pending'и к этой группе
                    // (они физически были до текущего события, должны идти первыми).
                    flushPendingToGroup(execKey, grpIdx);
                    addToGroup(grpIdx, i, ev, meta, execKey);
                    byExecKey.set(execKey, grpIdx);
                }
            } else {
                // Открываем новую группу. Pending в этом execKey - orphan'ы прошлой
                // транзакции (если они были) → отдельно, в singletons, до новой группы.
                flushPendingToSingles(execKey);
                const newIdx = newGroup(i, ev, meta, execKey);
                byTaskKey.set(taskKey, newIdx);
                byExecKey.set(execKey, newIdx);
            }
            continue;
        }

        // 3) Нет taskKey - пробуем приклеить по execKey (служебные строки без идентификаторов)
        if (byExecKey.has(execKey)) {
            const grpIdx = byExecKey.get(execKey);
            const grp = groups[grpIdx];
            if (ev.timestamp && grp.startTime && (ev.timestamp - grp.startTime > TX_TIMEOUT_MS)) {
                closeGroup(grpIdx, false);
                pushSingle(i);
            } else {
                addToGroup(grpIdx, i, ev, meta, execKey);
            }
            continue;
        }

        // 4) Нет ни taskKey, ни активного execKey. Откладываем в pending -
        // возможно, следующее событие с taskKey покажет, в какую группу его клеить.
        const arr = pending.get(execKey);
        if (arr && arr.length >= PENDING_MAX) {
            // Защита от неограниченного буфера: всё накопленное → singletons
            flushPendingToSingles(execKey);
            pushSingle(i);
        } else {
            if (arr) arr.push(i);
            else pending.set(execKey, [i]);
        }
    }

    // Закрываем все «висящие»
    for (const grpIdx of byTaskKey.values()) closeGroup(grpIdx, false);
    for (const grpIdx of byExecKey.values()) {
        const grp = groups[grpIdx];
        if (!grp.complete && !grp.single) closeGroup(grpIdx, false);
    }
    // Pending, которые так и не нашли свою группу до конца файла → в singletons
    for (const execKey of Array.from(pending.keys())) flushPendingToSingles(execKey);

    LV.groups = groups;
    LV.eventToGroup = eventToGroup;
}

function lvProcShort(name) {
    // nspRFTPK01A → TPK01A   (для красоты в заголовке)
    return name.replace(/^nspRF/i, '');
}

// Render HTML заголовка транзакции. Используется и в виртуальном скролле
// (с absolute top), и в sticky-плашке (без top).
function lvRenderTxHeaderHtml(row, styleAttr) {
    const grp = LV.groups[row.groupId];
    if (!grp) return '';
    const arrow = row.isOpen ? '▼' : '▶';
    const statusClass = !grp.complete ? ' lv-tx-incomplete' : (grp.hasError ? ' lv-tx-error' : ' lv-tx-ok');
    const openClass = row.isOpen ? ' lv-tx-open' : '';
    const statusBadge = !grp.complete
        ? '<span class="lv-tx-status lv-tx-status-incomplete">⚠ INCOMPLETE</span>'
        : (grp.hasError
            ? '<span class="lv-tx-status lv-tx-status-error">✕ ERROR</span>'
            : '<span class="lv-tx-status lv-tx-status-ok">✓ OK</span>');
    const procName = lvProcShort(grp.procName || '(unknown)');
    const userPart = grp.userId ? '<span class="lv-tx-user">' + lvEscape(grp.userId) + '</span>' : '';
    const sessPart = grp.sessionId ? '<span class="lv-tx-meta">' + lvEscape(grp.sessionId) + '</span>' : '';
    const taskPart = grp.taskId ? '<span class="lv-tx-meta lv-tx-task">tid=' + lvEscape(grp.taskId) + '</span>' : '';
    const dur = grp.duration ? grp.duration + ' ms' : '';
    const matchInfo = (row.matched < row.total)
        ? '<span class="lv-tx-match">(' + row.matched + ' из ' + row.total + ' под фильтром)</span>'
        : '<span class="lv-tx-events">' + row.total + ' событий</span>';
    const mismatchBadge = (grp.mismatchCount > 0)
        ? ' <span class="lv-tx-mismatch" title="При сборке этой группы ' + grp.mismatchCount + ' чужих событий отделено как singleton (taskId не совпал)">⚠ ' + grp.mismatchCount + ' чужих отделено</span>'
        : '';
    const styleStr = styleAttr ? ' style="' + styleAttr + '"' : '';
    return '<div class="lv-row lv-row-tx' + statusClass + openClass + '" data-group="' + row.groupId + '"' + styleStr + '>' +
        '<div class="lv-cell lv-c-num lv-tx-arrow">' + arrow + '</div>' +
        '<div class="lv-cell lv-c-time">' + (grp.startTime ? lvFormatTime(grp.startTime) : '') + '</div>' +
        '<div class="lv-cell lv-c-level">' + statusBadge + '</div>' +
        '<div class="lv-cell lv-c-thread">' + userPart + sessPart + '</div>' +
        '<div class="lv-cell lv-c-cat lv-tx-procname">' + lvEscape(procName) + '</div>' +
        '<div class="lv-cell lv-c-msg">' + taskPart + ' ' + matchInfo + (dur ? ' <span class="lv-tx-meta">' + dur + '</span>' : '') + mismatchBadge + '</div>' +
        '</div>';
}

// Обновить sticky-заголовок открытой транзакции при скролле.
// Логика:
//  - первая видимая строка - это event внутри открытой группы → показать
//    её tx-header в виде sticky-плашки на верху scroll-контейнера;
//  - первая видимая - это сам tx-header или одиночное событие → скрыть.
function lvUpdateStickyHeader() {
    const sticky = document.getElementById('lvStickyHeader');
    if (!sticky) return;
    if (!LV.flatRows.length || !LV.groupTx) {
        sticky.style.display = 'none';
        return;
    }
    const scroller = document.getElementById('lvScroll');
    const scrollTop = scroller.scrollTop;
    if (scrollTop < 1) { sticky.style.display = 'none'; return; }

    const startIdx = Math.floor(scrollTop / LV.rowHeight);
    if (startIdx <= 0 || startIdx >= LV.flatRows.length) {
        sticky.style.display = 'none';
        return;
    }
    const firstVisible = LV.flatRows[startIdx];
    if (firstVisible.type === 'tx-header') {
        // Сам header сейчас на верху viewport - sticky не нужен (и так видно)
        sticky.style.display = 'none';
        return;
    }
    if (firstVisible.type !== 'event' || !firstVisible.indented) {
        sticky.style.display = 'none';
        return;
    }
    // Ищем tx-header выше (это «родитель» открытой группы)
    for (let i = startIdx - 1; i >= 0; i--) {
        const r = LV.flatRows[i];
        if (r.type === 'tx-header') {
            sticky.style.display = 'block';
            sticky.innerHTML = lvRenderTxHeaderHtml(r, '');
            sticky.dataset.group = r.groupId;
            return;
        }
        // Если выше идёт обычное событие без indent - между ними нет header'а (singleton зона)
        if (r.type === 'event' && !r.indented) break;
    }
    sticky.style.display = 'none';
}

// ── User dropdown helpers ────────────────────────────────────────────
function lvUpdateUserLabel() {
    const label = document.getElementById('lvUserBtnLabel');
    const btn = document.getElementById('lvUserBtn');
    if (LV.selectedUsers.size === 0) {
        label.textContent = 'Все users';
        btn.classList.remove('active');
    } else if (LV.selectedUsers.size === 1) {
        label.textContent = LV.selectedUsers.values().next().value;
        btn.classList.add('active');
    } else {
        label.textContent = 'Users: ' + LV.selectedUsers.size;
        btn.classList.add('active');
    }
}

function lvRenderUserList(filterStr) {
    const list = document.getElementById('lvUserList');
    const f = (filterStr || '').toLowerCase();
    const items = LV.userList.filter(u => !f || u.name.toLowerCase().includes(f));
    if (!items.length) {
        list.innerHTML = '<div class="lv-thread-empty">Нет совпадений</div>';
        return;
    }
    let html = '';
    for (const u of items) {
        const checked = LV.selectedUsers.has(u.name) ? ' checked' : '';
        const safe = lvEscape(u.name);
        html += '<label class="lv-thread-item">' +
            '<input type="checkbox" value="' + safe + '"' + checked + '>' +
            '<span class="lv-thread-item-name" title="' + safe + '">' + safe + '</span>' +
            '<span class="lv-thread-item-count">' + u.count + '</span>' +
            '</label>';
    }
    list.innerHTML = html;
}

// ── Bookmarks helpers ────────────────────────────────────────────────
function lvToggleBookmark(eventId) {
    if (LV.bookmarks.has(eventId)) LV.bookmarks.delete(eventId);
    else LV.bookmarks.add(eventId);
    lvSaveBookmarks();
    lvUpdateBookmarksCount();
    lvRenderRows();
}

function lvUpdateBookmarksCount() {
    const el = document.getElementById('lvBookmarksCount');
    if (el) el.textContent = LV.bookmarks.size;
    const btn = document.getElementById('lvBookmarksBtn');
    if (btn) {
        if (LV.bookmarks.size > 0) btn.classList.add('active');
        else btn.classList.remove('active');
    }
}

function lvRenderBookmarksList() {
    const list = document.getElementById('lvBookmarksList');
    if (!list) return;
    if (LV.bookmarks.size === 0) {
        list.innerHTML = '<div class="lv-thread-empty">Нет закладок<br><small>Нажмите B на выделенной строке</small></div>';
        return;
    }
    const ids = Array.from(LV.bookmarks).sort((a, b) => a - b);
    let html = '';
    for (const id of ids) {
        const ev = LV.events[id];
        if (!ev) continue;
        const time = ev.timestamp ? lvFormatTime(ev.timestamp) : '';
        const lvl = ev.level.toLowerCase();
        const msg = (ev.message || '').replace(/\s+/g, ' ').trim().substring(0, 80);
        html += '<div class="lv-bm-item" data-id="' + id + '">' +
            '<span class="lv-bm-num">#' + (id + 1) + '</span>' +
            '<span class="lv-bm-time">' + time + '</span>' +
            '<span class="lv-badge lv-badge-' + lvl + '">' + lvEscape(ev.level) + '</span>' +
            '<span class="lv-bm-msg" title="' + lvEscape(ev.message || '') + '">' + lvEscape(msg) + '</span>' +
            '<button class="lv-bm-remove" title="Удалить">✕</button>' +
            '</div>';
    }
    list.innerHTML = html;
}

// ── Jump к конкретному событию ──────────────────────────────────────
function lvJumpToEvent(eventId) {
    // Нам нужно показать row eventId. Если есть фильтры - событие может быть скрыто.
    // Если оно в свернутой группе - раскроем группу.
    if (LV.groupTx) {
        const gid = LV.eventToGroup[eventId];
        if (gid >= 0 && !LV.openGroups.has(gid)) {
            const grp = LV.groups[gid];
            if (grp && grp.eventIds && grp.eventIds.length > 1) {
                LV.openGroups.add(gid);
                lvRebuildFlatRows();
            }
        }
    }
    // Найти позицию в flatRows
    let flatIdx = -1;
    for (let i = 0; i < LV.flatRows.length; i++) {
        const r = LV.flatRows[i];
        if (r.type === 'event' && r.eventId === eventId) { flatIdx = i; break; }
    }
    if (flatIdx === -1) {
        // Событие отфильтровано - временно подсветим bookmark в попапе и просто откроем detail
        lvShowDetail(eventId);
        return;
    }
    const scroller = document.getElementById('lvScroll');
    const targetTop = flatIdx * LV.rowHeight - scroller.clientHeight / 2 + LV.rowHeight / 2;
    scroller.scrollTop = Math.max(0, targetTop);
    lvShowDetail(eventId);
}

// ── Mini-timeline ────────────────────────────────────────────────────
//
// Два canvas со своими шкалами:
//  - lvTimelineMain - все события (серый), масштаб по их максимуму
//  - lvTimelineErr  - только ERROR/FATAL/WARN, масштаб по своему максимуму
// Так редкие ошибки видны нормально, а не как 1px-полоски рядом с
// фоном из тысячи INFO-событий.
//
// Drag мышью по любому из canvas - выделяет интервал и применяет его
// в качестве time range filter (timeFrom / timeTo). Клик без drag -
// переход к моменту, как раньше.
function lvSetupTimeline() {
    const wrap = document.getElementById('lvTimelineWrap');
    const tooltip = document.getElementById('lvTimelineTooltip');
    const overlay = document.getElementById('lvTimelineOverlay');
    if (!wrap) return;

    let drag = null; // { startX, currentX } - относительно canvas (не wrap)

    const totalRange = () => LV.maxTimestamp - LV.minTimestamp || 1;
    const xToTs = (x, w) => LV.minTimestamp + (x / w) * totalRange();

    // Геометрия canvas-области внутри wrap. Гистограмма рисуется только на
    // canvas (после label 110px + gap 8px + padding 8px), поэтому все
    // координаты курсора и буферы считаем именно от canvas, а не от wrap.
    const canvasGeom = () => {
        const c = document.getElementById('lvTimelineMain');
        const wr = wrap.getBoundingClientRect();
        const cr = c ? c.getBoundingClientRect() : wr;
        return {
            wrapRect: wr,
            canvasRect: cr,
            offsetLeft: cr.left - wr.left, // смещение canvas внутри wrap (для overlay/tooltip)
            width: cr.width,
        };
    };

    const updateOverlay = () => {
        if (!drag) { overlay.style.display = 'none'; return; }
        const g = canvasGeom();
        const left = Math.min(drag.startX, drag.currentX) + g.offsetLeft;
        const width = Math.abs(drag.currentX - drag.startX);
        overlay.style.display = 'block';
        overlay.style.left = left + 'px';
        overlay.style.width = width + 'px';
    };

    const updateTooltip = (clientX, clientY, hovering) => {
        if (!LV.events.length || !LV.minTimestamp || !hovering) {
            tooltip.style.display = 'none';
            return;
        }
        const g = canvasGeom();
        const x = clientX - g.canvasRect.left;
        if (x < 0 || x > g.width) { tooltip.style.display = 'none'; return; }
        const ts = xToTs(x, g.width);
        // Согласовано с lvDrawTimeline: тултип считает по тем же бакетам,
        // которые реально нарисованы на canvas.
        const buckets = Math.min(300, Math.max(60, Math.floor(g.width / 4)));
        const bucketSize = totalRange() / buckets;
        let cnt = 0, errs = 0, warns = 0;
        for (const ev of LV.events) {
            if (Math.abs(ev.timestamp - ts) < bucketSize / 2) {
                cnt++;
                if (ev.level === 'ERROR' || ev.level === 'FATAL') errs++;
                else if (ev.level === 'WARN' || ev.level === 'WARNING') warns++;
            }
        }
        tooltip.style.display = 'block';
        const tipX = x + g.offsetLeft + 8;
        tooltip.style.left = Math.min(g.wrapRect.width - 220, Math.max(0, tipX)) + 'px';
        let html = '<b>' + lvFormatTime(ts, true) + '</b><br>' + cnt + ' событий';
        if (errs) html += ', <span style="color:#ef4444">' + errs + ' ошибок</span>';
        if (warns) html += ', <span style="color:#f59e0b">' + warns + ' warns</span>';
        if (drag && Math.abs(drag.currentX - drag.startX) > 5) {
            const tsFrom = xToTs(Math.min(drag.startX, drag.currentX), g.width);
            const tsTo = xToTs(Math.max(drag.startX, drag.currentX), g.width);
            html += '<br><b style="color:#3b82f6">Интервал:</b> ' + lvFormatTime(tsFrom) + ' → ' + lvFormatTime(tsTo);
        }
        tooltip.innerHTML = html;
    };

    wrap.addEventListener('mousedown', (e) => {
        if (!LV.events.length || !LV.minTimestamp) return;
        // Реагируем только на сами canvas - не на label/hint
        if (!e.target.classList.contains('lv-timeline-canvas')) return;
        const g = canvasGeom();
        const x = e.clientX - g.canvasRect.left;
        drag = { startX: x, currentX: x };
        e.preventDefault();
        updateOverlay();
    });

    document.addEventListener('mousemove', (e) => {
        const g = canvasGeom();
        if (drag) {
            drag.currentX = Math.max(0, Math.min(g.width, e.clientX - g.canvasRect.left));
            updateOverlay();
        }
        // Tooltip - только если курсор над одним из canvas (по горизонтали - canvas, по вертикали - wrap)
        const inside = e.clientX >= g.canvasRect.left && e.clientX <= g.canvasRect.right
            && e.clientY >= g.wrapRect.top && e.clientY <= g.wrapRect.bottom;
        updateTooltip(e.clientX, e.clientY, inside);
    });

    document.addEventListener('mouseup', (e) => {
        if (!drag) return;
        const dist = Math.abs(drag.currentX - drag.startX);
        const g = canvasGeom();
        if (dist < 5) {
            // Click без drag → jump
            const targetTs = xToTs(drag.startX, g.width);
            let bestId = -1;
            for (let i = 0; i < LV.events.length; i++) {
                if (LV.events[i].timestamp >= targetTs) { bestId = i; break; }
            }
            if (bestId >= 0) lvJumpToEvent(bestId);
        } else {
            // Drag → выставляем time range
            const minX = Math.min(drag.startX, drag.currentX);
            const maxX = Math.max(drag.startX, drag.currentX);
            LV.timeFrom = xToTs(minX, g.width);
            LV.timeTo = xToTs(maxX, g.width);
            document.getElementById('lvTimeFrom').value = lvFormatTime(LV.timeFrom);
            document.getElementById('lvTimeTo').value = lvFormatTime(LV.timeTo);
            lvApplyFilters();
        }
        drag = null;
        overlay.style.display = 'none';
    });
}

function lvDrawTimeline() {
    if (!LV.events.length || !LV.minTimestamp) return;
    const mainCanvas = document.getElementById('lvTimelineMain');
    const errCanvas  = document.getElementById('lvTimelineErr');
    if (!mainCanvas || !errCanvas) return;
    // Сбрасываем inline width от прошлого рендера, чтобы flex:1 пересчитал
    // доступную ширину (без неё canvas сохраняет старую width и вылазит за row).
    mainCanvas.style.width = '';
    errCanvas.style.width = '';
    const cssW = mainCanvas.clientWidth;
    if (!cssW) return;

    const total = LV.maxTimestamp - LV.minTimestamp || 1;
    const buckets = Math.min(300, Math.max(60, Math.floor(cssW / 4)));
    const bucketSize = total / buckets;

    const counts = new Array(buckets).fill(0);
    const errCounts = new Array(buckets).fill(0);
    const warnCounts = new Array(buckets).fill(0);
    let maxAll = 0;
    let maxBad = 0;

    for (const ev of LV.events) {
        if (!ev.timestamp) continue;
        const idx = Math.min(buckets - 1, Math.floor((ev.timestamp - LV.minTimestamp) / bucketSize));
        counts[idx]++;
        if (ev.level === 'ERROR' || ev.level === 'FATAL') errCounts[idx]++;
        else if (ev.level === 'WARN' || ev.level === 'WARNING') warnCounts[idx]++;
        if (counts[idx] > maxAll) maxAll = counts[idx];
        const bad = errCounts[idx] + warnCounts[idx];
        if (bad > maxBad) maxBad = bad;
    }

    drawBars('lvTimelineMain', cssW, 38, buckets, (i) => ({
        bars: [{ value: counts[i], color: '#cbd5e1' }],
        max: maxAll,
    }));
    drawBars('lvTimelineErr', cssW, 38, buckets, (i) => ({
        // Errors снизу, warns поверх (стек)
        bars: [
            { value: errCounts[i], color: '#ef4444' },
            { value: warnCounts[i], color: '#f59e0b' },
        ],
        max: maxBad,
    }));
}

function drawBars(canvasId, cssW, cssH, buckets, getter) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = cssW * dpr;
    canvas.height = cssH * dpr;
    canvas.style.width = cssW + 'px';
    canvas.style.height = cssH + 'px';
    const ctx = canvas.getContext('2d');
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, cssW, cssH);

    const barW = cssW / buckets;
    for (let i = 0; i < buckets; i++) {
        const data = getter(i);
        if (!data.max) continue;
        let stackBottom = cssH;
        for (const bar of data.bars) {
            if (!bar.value) continue;
            const h = (bar.value / data.max) * cssH;
            ctx.fillStyle = bar.color;
            ctx.fillRect(i * barW, stackBottom - h, Math.max(1, barW - 0.5), h);
            stackBottom -= h;
        }
    }

    // Подпись с краёв (только на верхнем canvas - по нему ориентируемся)
    if (canvasId === 'lvTimelineMain') {
        ctx.fillStyle = '#94a3b8';
        ctx.font = '10px -apple-system, sans-serif';
        ctx.textBaseline = 'top';
        ctx.fillText(lvFormatTime(LV.minTimestamp), 4, 2);
        const endStr = lvFormatTime(LV.maxTimestamp);
        ctx.fillText(endStr, cssW - ctx.measureText(endStr).width - 4, 2);
    }
}

function lvUpdateThreadLabel() {
    const label = document.getElementById('lvThreadBtnLabel');
    const btn = document.getElementById('lvThreadBtn');
    if (LV.selectedThreads.size === 0) {
        label.textContent = 'Все threads';
        btn.classList.remove('active');
    } else if (LV.selectedThreads.size === 1) {
        const v = LV.selectedThreads.values().next().value;
        label.textContent = v.length > 24 ? v.substring(0, 22) + '…' : v;
        btn.classList.add('active');
    } else {
        label.textContent = 'Threads: ' + LV.selectedThreads.size;
        btn.classList.add('active');
    }
}

function lvRenderThreadList(filterStr) {
    const list = document.getElementById('lvThreadList');
    const f = (filterStr || '').toLowerCase();
    const items = LV.threadList.filter(t => !f || t.name.toLowerCase().includes(f));
    if (!items.length) {
        list.innerHTML = '<div class="lv-thread-empty">Нет совпадений</div>';
        return;
    }
    let html = '';
    for (const t of items) {
        const checked = LV.selectedThreads.has(t.name) ? ' checked' : '';
        const safe = lvEscape(t.name);
        html += '<label class="lv-thread-item">' +
            '<input type="checkbox" value="' + safe + '"' + checked + '>' +
            '<span class="lv-thread-item-name" title="' + safe + '">' + safe + '</span>' +
            '<span class="lv-thread-item-count">' + t.count + '</span>' +
            '</label>';
    }
    list.innerHTML = html;
}

function lvFormatBytes(n) {
    if (n < 1024) return n + ' B';
    if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB';
    if (n < 1024 * 1024 * 1024) return (n / 1024 / 1024).toFixed(1) + ' MB';
    return (n / 1024 / 1024 / 1024).toFixed(2) + ' GB';
}

function lvLoadFile(file) {
    const fileName = document.getElementById('lvFileName');
    const fileSize = document.getElementById('lvFileSize');
    const progress = document.getElementById('lvProgress');
    const progressFill = document.getElementById('lvProgressFill');
    const progressText = document.getElementById('lvProgressText');
    const empty = document.getElementById('lvEmpty');
    const tableWrap = document.getElementById('lvTableWrap');

    fileName.textContent = file.name;
    fileSize.textContent = lvFormatBytes(file.size);
    LV.lastFileName = file.name;
    LV.lastFileSize = file.size;
    empty.style.display = 'none';
    tableWrap.style.display = 'none';
    document.getElementById('lvTimelineWrap').style.display = 'none';
    progress.style.display = 'block';
    progressText.textContent = 'Чтение файла...';
    progressFill.style.width = '0%';

    const reader = new FileReader();
    reader.onprogress = (e) => {
        if (e.lengthComputable) {
            const pct = Math.round((e.loaded / e.total) * 50); // 0..50% - чтение
            progressFill.style.width = pct + '%';
        }
    };
    reader.onerror = () => {
        progressText.textContent = 'Ошибка чтения файла';
    };
    reader.onload = (e) => {
        const text = e.target.result;
        progressFill.style.width = '50%';
        progressText.textContent = 'Парсинг событий...';
        // Даём UI обновиться, потом парсим
        setTimeout(() => lvParseAsync(text, progressFill, progressText), 30);
    };
    reader.readAsText(file);
}

function lvParseAsync(text, progressFill, progressText) {
    // Разбиваем по началам событий, парсим итеративно с yield каждые ~5к событий.
    const events = [];
    const re = /<log4j:event\s+([^>]+)>([\s\S]*?)<[\\\/]log4j:event>/g;
    const total = text.length;
    let lastYield = 0;
    let m;
    let chunkCount = 0;

    function step() {
        const start = Date.now();
        while ((m = re.exec(text)) !== null) {
            const attrs = m[1];
            const body = m[2];
            const category = lvAttr(attrs, 'category');
            const thread = lvAttr(attrs, 'thread');
            const message = lvCData(body, 'log4j:message');
            const throwable = lvCData(body, 'log4j:throwable');
            // Извлекаем userId/taskId если они есть в сообщении (EXEC nsp..., pResult, theArgs)
            const txMeta = lvExtractTxMeta(message);
            // Аномалия - известные «плохие» паттерны
            const fullText = message + ' ' + throwable;
            const isAnomaly = LV_ANOMALY_PATTERNS.some(p => p.test(fullText));
            // Result - сервер вернул что-то клиенту (важная строка для разбора)
            const isResult = LV_RESULT_PATTERNS.some(p => p.test(message));
            events.push({
                id: events.length,
                category,
                timestamp: parseInt(lvAttr(attrs, 'timestamp'), 10) || 0,
                level: (lvAttr(attrs, 'level') || 'INFO').toUpperCase(),
                thread,
                message,
                throwable,
                _search: (message + ' ' + throwable + ' ' + thread + ' ' + category).toLowerCase(),
                _userId: txMeta.userId,
                _taskId: txMeta.taskId,
                _anomaly: isAnomaly,
                _result: isResult,
            });
            chunkCount++;
            if (Date.now() - start > 80) {
                // yield to UI
                const pct = 50 + Math.round((re.lastIndex / total) * 50);
                progressFill.style.width = pct + '%';
                progressText.textContent = `Распарсено ${events.length.toLocaleString('ru-RU')} событий...`;
                setTimeout(step, 0);
                return;
            }
        }
        // Готово
        LV.events = events;
        progressFill.style.width = '100%';
        progressText.textContent = `Готово: ${events.length.toLocaleString('ru-RU')} событий`;
        setTimeout(() => {
            document.getElementById('lvProgress').style.display = 'none';
            lvShowResults();
        }, 200);
    }
    step();
}

function lvAttr(attrs, name) {
    const re = new RegExp(name + '="([^"]*)"');
    const m = attrs.match(re);
    return m ? m[1] : '';
}

function lvCData(body, tag) {
    const re = new RegExp('<' + tag + '\\b[^>]*><!\\[CDATA\\[([\\s\\S]*?)\\]\\]><\\/' + tag + '>');
    const m = body.match(re);
    return m ? m[1] : '';
}

async function lvShowResults() {
    const events = LV.events;
    document.getElementById('lvTableWrap').style.display = 'flex';
    document.getElementById('lvFilters').style.display = 'flex';
    document.getElementById('lvTimelineWrap').style.display = 'block';
    document.getElementById('lvStatEvents').textContent = events.length.toLocaleString('ru-RU');

    let errs = 0, warns = 0;
    let minT = Infinity, maxT = -Infinity;
    const threadCounts = new Map();
    const userCounts = new Map();
    for (const ev of events) {
        if (ev.level === 'ERROR' || ev.level === 'FATAL') errs++;
        else if (ev.level === 'WARN' || ev.level === 'WARNING') warns++;
        if (ev.timestamp) {
            if (ev.timestamp < minT) minT = ev.timestamp;
            if (ev.timestamp > maxT) maxT = ev.timestamp;
        }
        const t = ev.thread || '(none)';
        threadCounts.set(t, (threadCounts.get(t) || 0) + 1);
        if (ev._userId) {
            userCounts.set(ev._userId, (userCounts.get(ev._userId) || 0) + 1);
        }
    }
    document.getElementById('lvStatErrors').textContent = errs.toLocaleString('ru-RU');
    document.getElementById('lvStatWarns').textContent = warns.toLocaleString('ru-RU');
    if (minT !== Infinity) {
        document.getElementById('lvStatRange').textContent =
            lvFormatTime(minT, true) + ' - ' + lvFormatTime(maxT, true);
        LV.minTimestamp = minT;
        LV.maxTimestamp = maxT;
        // Установить placeholder в time range полях
        document.getElementById('lvTimeFrom').placeholder = lvFormatTime(minT);
        document.getElementById('lvTimeTo').placeholder = lvFormatTime(maxT);
    } else {
        document.getElementById('lvStatRange').textContent = '-';
        LV.minTimestamp = 0;
        LV.maxTimestamp = 0;
    }

    LV.threadList = Array.from(threadCounts.entries())
        .map(([name, count]) => ({ name, count }))
        .sort((a, b) => b.count - a.count);
    LV.userList = Array.from(userCounts.entries())
        .map(([name, count]) => ({ name, count }))
        .sort((a, b) => b.count - a.count);

    // Сброс фильтров на новом файле (кроме disabledLevels - там persisted)
    LV.searchQuery = '';
    LV.selectedThreads.clear();
    LV.selectedUsers.clear();
    LV.timeFrom = null;
    LV.timeTo = null;
    LV.groups = [];
    LV.eventToGroup = [];
    LV.openGroups.clear();
    document.getElementById('lvSearch').value = '';
    document.getElementById('lvSearchClear').style.display = 'none';
    document.getElementById('lvTimeFrom').value = '';
    document.getElementById('lvTimeTo').value = '';
    lvUpdateThreadLabel();
    lvRenderThreadList('');
    lvUpdateUserLabel();
    lvRenderUserList('');

    // Загружаем bookmarks для этого файла
    LV.fileKey = LV.lastFileName + '_' + (LV.lastFileSize || 0);
    await lvLoadBookmarks(LV.fileKey);
    lvUpdateBookmarksCount();

    // Если режим группировки уже включён - пересчитываем для нового файла
    if (LV.groupTx) lvBuildGroups();

    // V-Sign автопроверка (CheckMark / MarkCodeResponse)
    lvAnalyzeVSign();

    LV.selectedId = -1;
    document.getElementById('lvDetail').style.display = 'none';
    lvUpdateLayout();
    lvApplyFilters();
    lvDrawTimeline();
}

function lvApplyFilters() {
    const q = LV.searchQuery;
    const dlev = LV.disabledLevels;
    const sthr = LV.selectedThreads;
    const susr = LV.selectedUsers;
    const useThr = sthr.size > 0;
    const useUsr = susr.size > 0;
    const tFrom = LV.timeFrom;
    const tTo = LV.timeTo;
    const events = LV.events;

    const ids = [];
    const filteredSet = new Set();
    for (let i = 0; i < events.length; i++) {
        const ev = events[i];
        if (dlev.has(ev.level)) continue;
        if (useThr && !sthr.has(ev.thread)) continue;
        if (useUsr && !susr.has(ev._userId)) continue;
        if (tFrom && ev.timestamp && ev.timestamp < tFrom) continue;
        if (tTo && ev.timestamp && ev.timestamp > tTo) continue;
        if (q && !ev._search.includes(q)) continue;
        ids.push(i);
        filteredSet.add(i);
    }
    LV.filteredIds = ids;
    LV.filteredSet = filteredSet;

    // Шаг 2: строим flat rows (учитывая текущее состояние openGroups)
    lvRebuildFlatRows();

    // Шаг 3: scroll сбрасывается ТОЛЬКО при изменении фильтров
    document.getElementById('lvScroll').scrollTop = 0;

    // Счётчик
    const counter = document.getElementById('lvFilterCount');
    if (ids.length === events.length) {
        counter.textContent = events.length.toLocaleString('ru-RU') + ' событий';
        if (LV.groupTx) {
            const txCount = LV.groups.reduce((acc, g) => acc + (g.single || g.eventIds.length === 1 ? 0 : 1), 0);
            counter.textContent += ' · ' + txCount.toLocaleString('ru-RU') + ' транзакций';
        }
        counter.classList.remove('lv-filter-active');
    } else {
        counter.textContent = ids.length.toLocaleString('ru-RU') + ' из ' + events.length.toLocaleString('ru-RU');
        counter.classList.add('lv-filter-active');
    }

    lvRenderRows();
}

// Перестраивает плоский список строк под текущие фильтры и состояние openGroups.
// Вызывается из lvApplyFilters (со сбросом scroll) и lvToggleGroup (без сброса).
function lvRebuildFlatRows() {
    const filteredSet = LV.filteredSet || new Set(LV.filteredIds);
    const flat = [];

    if (LV.groupTx && LV.groups.length > 0) {
        for (let g = 0; g < LV.groups.length; g++) {
            const grp = LV.groups[g];
            let matched = 0;
            for (const eId of grp.eventIds) if (filteredSet.has(eId)) matched++;
            if (matched === 0) continue;

            if (grp.single || grp.eventIds.length === 1) {
                for (const eId of grp.eventIds) {
                    if (filteredSet.has(eId)) flat.push({ type: 'event', eventId: eId });
                }
            } else {
                const isOpen = LV.openGroups.has(g);
                const txStatus = !grp.complete ? 'incomplete' : (grp.hasError ? 'error' : 'ok');
                flat.push({ type: 'tx-header', groupId: g, isOpen, matched, total: grp.eventIds.length });
                if (isOpen) {
                    for (let idx = 0; idx < grp.eventIds.length; idx++) {
                        const eId = grp.eventIds[idx];
                        flat.push({
                            type: 'event',
                            eventId: eId,
                            indented: true,
                            dimmed: !filteredSet.has(eId),
                            txStatus,
                            isFirst: idx === 0,
                            isLast: idx === grp.eventIds.length - 1,
                        });
                    }
                }
            }
        }
    } else {
        for (const eId of LV.filteredIds) flat.push({ type: 'event', eventId: eId });
    }

    LV.flatRows = flat;
    document.getElementById('lvSpacer').style.height = (flat.length * LV.rowHeight) + 'px';
    lvUpdateStickyHeader();
}

// Toggle открытие/закрытие группы с сохранением визуальной позиции заголовка.
function lvToggleGroup(gid) {
    const scroller = document.getElementById('lvScroll');
    const rh = LV.rowHeight;

    // Текущая позиция header'а группы относительно viewport
    let oldHeaderTop = -1;
    for (let i = 0; i < LV.flatRows.length; i++) {
        const r = LV.flatRows[i];
        if (r.type === 'tx-header' && r.groupId === gid) {
            oldHeaderTop = i * rh;
            break;
        }
    }
    const headerScreenY = oldHeaderTop - scroller.scrollTop;

    // Toggle
    if (LV.openGroups.has(gid)) LV.openGroups.delete(gid);
    else LV.openGroups.add(gid);

    // Перестраиваем flat rows БЕЗ сброса scroll
    lvRebuildFlatRows();

    // Найти новую позицию того же header'а
    let newHeaderTop = -1;
    for (let i = 0; i < LV.flatRows.length; i++) {
        const r = LV.flatRows[i];
        if (r.type === 'tx-header' && r.groupId === gid) {
            newHeaderTop = i * rh;
            break;
        }
    }

    // Удержать header в той же визуальной позиции - компенсируем сдвиг от вставки/удаления выше
    if (newHeaderTop >= 0 && oldHeaderTop >= 0) {
        scroller.scrollTop = Math.max(0, newHeaderTop - headerScreenY);
    }

    lvRenderRows();
}

function lvFormatTime(ts, withDate) {
    const d = new Date(ts);
    const pad = (n, l) => String(n).padStart(l || 2, '0');
    const time = pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds()) + '.' + pad(d.getMilliseconds(), 3);
    if (!withDate) return time;
    return pad(d.getDate()) + '.' + pad(d.getMonth() + 1) + ' ' + time;
}

function lvShortCat(cat) {
    if (!cat) return '';
    const i = cat.lastIndexOf('.');
    return i === -1 ? cat : cat.substring(i + 1);
}

function lvEscape(s) {
    if (!s) return '';
    return s.replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
}

function lvRenderRows() {
    const flat = LV.flatRows;
    const rowsContainer = document.getElementById('lvRows');
    if (!flat.length) {
        rowsContainer.innerHTML = '<div class="lv-no-results">Ничего не найдено по текущим фильтрам</div>';
        return;
    }
    const scroller = document.getElementById('lvScroll');
    const scrollTop = scroller.scrollTop;
    const viewportH = scroller.clientHeight;

    const rh = LV.rowHeight;
    const startIdx = Math.max(0, Math.floor(scrollTop / rh) - LV.bufferRows);
    const endIdx = Math.min(flat.length, Math.ceil((scrollTop + viewportH) / rh) + LV.bufferRows);

    const q = LV.searchQuery;
    let qRe = null;
    if (q) {
        const escaped = q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        qRe = new RegExp('(' + escaped + ')', 'gi');
    }

    let html = '';
    for (let i = startIdx; i < endIdx; i++) {
        const row = flat[i];
        const top = i * rh;

        if (row.type === 'tx-header') {
            html += lvRenderTxHeaderHtml(row, 'top:' + top + 'px');
        } else {
            const ev = LV.events[row.eventId];
            const lvl = ev.level.toLowerCase();
            const sel = (row.eventId === LV.selectedId) ? ' lv-row-selected' : '';
            const trow = ev.throwable ? ' lv-row-trace' : '';
            const indented = row.indented ? ' lv-row-indented' : '';
            const txContent = (row.indented && row.txStatus) ? ' lv-tx-content-' + row.txStatus : '';
            const lastRow = row.isLast ? ' lv-row-tx-last' : '';
            const dimmed = row.dimmed ? ' lv-row-dimmed' : '';
            const anomaly = ev._anomaly ? ' lv-row-anomaly' : '';
            const result = ev._result ? ' lv-row-result' : '';
            const vsignClass = ev._vsignAlert ? (' lv-row-vsign-' + ev._vsignAlert.severity) : '';
            const bookmarked = LV.bookmarks.has(row.eventId) ? ' lv-row-bookmarked' : '';
            const msg = (ev.message || '').replace(/\s+/g, ' ').trim();
            const msgHtml = qRe ? lvHighlight(msg, qRe) : lvEscape(msg);
            const threadHtml = qRe ? lvHighlight(ev.thread, qRe) : lvEscape(ev.thread);
            const catHtml = qRe ? lvHighlight(lvShortCat(ev.category), qRe) : lvEscape(lvShortCat(ev.category));
            const bmIcon = LV.bookmarks.has(row.eventId) ? '★' : '☆';
            html += '<div class="lv-row lv-lvl-' + lvl + sel + trow + indented + txContent + lastRow + dimmed + anomaly + result + vsignClass + bookmarked + '" data-id="' + row.eventId + '" style="top:' + top + 'px">' +
                '<div class="lv-cell lv-c-num"><span class="lv-row-num">' + (row.eventId + 1) + '</span><button class="lv-row-bm" title="Закладка (B)" data-bm="' + row.eventId + '">' + bmIcon + '</button></div>' +
                '<div class="lv-cell lv-c-time">' + (ev.timestamp ? lvFormatTime(ev.timestamp) : '') + '</div>' +
                '<div class="lv-cell lv-c-level"><span class="lv-badge lv-badge-' + lvl + '">' + lvEscape(ev.level) + '</span></div>' +
                '<div class="lv-cell lv-c-thread" title="' + lvEscape(ev.thread) + '">' + threadHtml + '</div>' +
                '<div class="lv-cell lv-c-cat" title="' + lvEscape(ev.category) + '">' + catHtml + '</div>' +
                '<div class="lv-cell lv-c-msg" title="' + lvEscape(msg) + '">' + msgHtml + '</div>' +
                '</div>';
        }
    }
    rowsContainer.innerHTML = html;

    if (!rowsContainer._lvClickBound) {
        rowsContainer.addEventListener('click', (e) => {
            // Клик на bookmark icon - toggle, не открывая detail
            const bmBtn = e.target.closest('.lv-row-bm');
            if (bmBtn) {
                e.stopPropagation();
                lvToggleBookmark(parseInt(bmBtn.dataset.bm, 10));
                return;
            }
            const txRow = e.target.closest('.lv-row-tx');
            if (txRow) {
                const gid = parseInt(txRow.dataset.group, 10);
                lvToggleGroup(gid);
                return;
            }
            const row = e.target.closest('.lv-row');
            if (!row) return;
            const id = parseInt(row.dataset.id, 10);
            lvShowDetail(id);
        });
        rowsContainer._lvClickBound = true;
    }
}

function lvHighlight(text, re) {
    if (!text) return '';
    return lvEscape(text).replace(re, '<mark>$1</mark>');
}

function lvShowDetail(id) {
    const ev = LV.events[id];
    if (!ev) return;
    LV.selectedId = id;

    document.getElementById('lvDetailNum').textContent = '#' + (id + 1);
    const lvBadge = document.getElementById('lvDetailLevel');
    lvBadge.textContent = ev.level;
    lvBadge.className = 'lv-badge lv-badge-' + ev.level.toLowerCase();
    document.getElementById('lvDetailTime').textContent = ev.timestamp ? lvFormatTime(ev.timestamp, true) : '';
    document.getElementById('lvDetailThread').textContent = ev.thread || '-';
    document.getElementById('lvDetailCat').textContent = ev.category || '-';
    document.getElementById('lvDetailMessage').textContent = ev.message || '';

    // User row + кнопка «только этот юзер» (reconstruct session)
    const userRow = document.getElementById('lvDetailUserRow');
    const userOnlyBtn = document.getElementById('lvDetailUserOnly');
    if (ev._userId) {
        userRow.style.display = 'flex';
        document.getElementById('lvDetailUser').textContent = ev._userId + (ev._taskId ? ' · tid=' + ev._taskId : '');
        userOnlyBtn.onclick = () => {
            LV.selectedUsers.clear();
            LV.selectedUsers.add(ev._userId);
            lvUpdateUserLabel();
            lvRenderUserList('');
            lvApplyFilters();
        };
    } else {
        userRow.style.display = 'none';
    }

    // V-Sign проверка
    const vsignWrap = document.getElementById('lvDetailVSignWrap');
    const vsignLabel = document.getElementById('lvDetailVSignLabel');
    if (ev._vsignAlert) {
        vsignWrap.style.display = 'block';
        const a = ev._vsignAlert;
        vsignLabel.textContent = (a.severity === 'error' ? '✕' : '⚠') + ' V-Sign проверка - ' +
            (a.severity === 'error' ? 'ОШИБКА' : 'предупреждение');
        vsignLabel.className = 'lv-detail-label lv-detail-vsign-' + a.severity;

        let h = '';
        h += '<div class="lv-exec-row"><span class="lv-exec-key">cis</span><span class="lv-exec-val lv-vsign-cis">' + lvEscape(a.cis) + '</span></div>';
        h += '<div class="lv-exec-row"><span class="lv-exec-key">type</span><span class="lv-exec-val">' + (a.isResponse ? 'MarkCodeResponse' : 'CheckMark request') + '</span></div>';

        // Если у нас есть response - показать его сводку
        const resp = LV.vsignResponses && LV.vsignResponses.get(a.cis);
        if (resp) {
            h += '<div class="lv-exec-row"><span class="lv-exec-key">packingVID</span><span class="lv-exec-val">' + lvEscape(resp.packingVID || '-') + '</span></div>';
            h += '<div class="lv-exec-row"><span class="lv-exec-key">includes</span><span class="lv-exec-val">' + resp.includes + ' (в теле: ' + resp.items.length + ')</span></div>';
            if (resp.duration) h += '<div class="lv-exec-row"><span class="lv-exec-key">duration</span><span class="lv-exec-val">' + resp.duration + ' ms</span></div>';
            if (resp.eventId !== undefined) {
                h += '<div class="lv-exec-row"><span class="lv-exec-key">response</span><span class="lv-exec-val"><a class="lv-vsign-link" data-jump="' + resp.eventId + '">→ строка #' + (resp.eventId + 1) + '</a></span></div>';
            }
        } else {
            h += '<div class="lv-exec-row lv-vsign-missing"><span class="lv-exec-key">response</span><span class="lv-exec-val"><i>не найден в логе</i></span></div>';
        }

        // Список алертов
        h += '<div class="lv-vsign-alerts">';
        for (const al of a.alerts) {
            h += '<div class="lv-vsign-alert lv-vsign-alert-' + al.severity + '">' +
                 '<span class="lv-vsign-alert-code">' + al.code + '</span>' +
                 '<span class="lv-vsign-alert-msg">' + lvEscape(al.message) + '</span>';
            if (al.missing && al.missing.length) {
                const showCount = Math.min(5, al.missing.length);
                h += '<div class="lv-vsign-missing-list">Не проверены:<br>';
                for (let mi = 0; mi < showCount; mi++) h += '<code>' + lvEscape(al.missing[mi]) + '</code><br>';
                if (al.missing.length > showCount) h += '<i>… и ещё ' + (al.missing.length - showCount) + '</i>';
                h += '</div>';
            }
            h += '</div>';
        }
        h += '</div>';

        document.getElementById('lvDetailVSign').innerHTML = h;
    } else {
        vsignWrap.style.display = 'none';
    }

    // EXEC arguments - таблица с разобранными аргументами (что клиент прислал)
    const execArgs = lvParseExecArgs(ev.message);
    const execWrap = document.getElementById('lvDetailExecWrap');
    if (execArgs) {
        execWrap.style.display = 'block';
        const fields = [
            ['Procedure', execArgs.procName],
            ['msgVer', execArgs.msgVer],
            ['userId', execArgs.userId],
            ['taskId', execArgs.taskId],
            ['database', execArgs.database],
            ['appFlag', execArgs.appFlag],
            ['recordType', execArgs.recordType],
            ['IP', execArgs.ip],
        ];
        let h = '';
        for (const [k, v] of fields) {
            if (!v) continue;
            h += '<div class="lv-exec-row"><span class="lv-exec-key">' + k + '</span><span class="lv-exec-val">' + lvEscape(v) + '</span></div>';
        }
        if (execArgs.rawArgs && execArgs.rawArgs.length) {
            // Если у нас есть mapping для этой процедуры - показываем
            // именованную таблицу. Иначе - старый формат «капсулами».
            const procKey = execArgs.procName.toUpperCase();
            const builtin = (typeof LV_BUILTIN_MAPPINGS !== 'undefined') ? LV_BUILTIN_MAPPINGS[procKey] : null;
            const labels = (builtin && builtin.send) || LV.procMappings[procKey];
            if (labels && labels.length) {
                h += '<div class="lv-exec-row lv-exec-raw"><span class="lv-exec-key">args</span><span class="lv-exec-val lv-exec-named">';
                for (let i = 0; i < execArgs.rawArgs.length; i++) {
                    const label = labels[i] || ('arg' + (i + 1));
                    const val = execArgs.rawArgs[i];
                    h += '<div class="lv-exec-named-row">' +
                         '<span class="lv-exec-named-key">' + lvEscape(label) + '</span>' +
                         '<span class="lv-exec-named-val">' + (val ? lvEscape(val) : '<i>empty</i>') + '</span>' +
                         '</div>';
                }
                h += '</span></div>';
            } else {
                h += '<div class="lv-exec-row lv-exec-raw"><span class="lv-exec-key">args</span><span class="lv-exec-val">';
                h += execArgs.rawArgs.map((a, i) => '<span class="lv-exec-arg" title="arg' + (i + 1) + '">' + (a ? lvEscape(a) : '<i>empty</i>') + '</span>').join('<span class="lv-exec-sep">`</span>');
                h += '</span></div>';
            }
        }
        document.getElementById('lvDetailExec').innerHTML = h;
    } else {
        execWrap.style.display = 'none';
    }

    // pResult - таблица с разобранными полями ответа (что сервер вернул)
    const pres = lvParsePResult(ev.message);
    const resultWrap = document.getElementById('lvDetailResultWrap');
    if (pres) {
        resultWrap.style.display = 'block';
        const isError = pres.returnCode && pres.returnCode !== '1';
        const errorClass = isError ? ' lv-result-error' : ' lv-result-ok';
        const fields = [
            ['msgVer', pres.msgVer],
            ['userId', pres.userId],
            ['taskId', pres.taskId],
            ['database', pres.database],
            ['appFlag', pres.appFlag],
            ['recordType', pres.recordType],
            ['IP', pres.ip],
        ];
        let h = '';
        for (const [k, v] of fields) {
            if (!v) continue;
            h += '<div class="lv-exec-row"><span class="lv-exec-key">' + k + '</span><span class="lv-exec-val">' + lvEscape(v) + '</span></div>';
        }
        // Status: errorMsg + returnCode (выделяем)
        h += '<div class="lv-exec-row lv-result-status' + errorClass + '">' +
             '<span class="lv-exec-key">status</span>' +
             '<span class="lv-exec-val">' +
                 '<span class="lv-result-code">code=' + lvEscape(pres.returnCode || '?') + '</span> ' +
                 '<span class="lv-result-msg">' + lvEscape(pres.errorMsg || '') + '</span>' +
             '</span></div>';

        // Данные. procName в pResult явно нет - берём из группы транзакции.
        // Если события сгруппированы и текущее в группе - у этой группы
        // парсенный procName (nspRFXXX). По нему ищем receive labels.
        let recvLabels = null;
        let procName = '';
        if (LV.eventToGroup && LV.eventToGroup[id] !== undefined && LV.groups) {
            const grpIdx = LV.eventToGroup[id];
            const grp = LV.groups[grpIdx];
            if (grp && grp.procName && grp.procName !== '(unknown)') {
                procName = grp.procName;
                const procKey = procName.toUpperCase();
                if (typeof LV_BUILTIN_MAPPINGS !== 'undefined' && LV_BUILTIN_MAPPINGS[procKey]) {
                    recvLabels = LV_BUILTIN_MAPPINGS[procKey].receive || null;
                }
            }
        }

        if (pres.data && pres.data.length) {
            if (recvLabels && recvLabels.length) {
                // Именованная таблица с реальными именами полей из RECEIVE-секции экрана
                h += '<div class="lv-exec-row lv-exec-raw"><span class="lv-exec-key">data <span class="lv-exec-proc">(' + lvEscape(procName) + ')</span></span><span class="lv-exec-val lv-exec-named">';
                for (let i = 0; i < pres.data.length; i++) {
                    const label = recvLabels[i] || ('data[' + (i + 1) + ']');
                    const val = pres.data[i];
                    h += '<div class="lv-exec-named-row">' +
                         '<span class="lv-exec-named-key">' + lvEscape(label) + '</span>' +
                         '<span class="lv-exec-named-val">' + (val ? lvEscape(val) : '<i>empty</i>') + '</span>' +
                         '</div>';
                }
                h += '</span></div>';
            } else {
                h += '<div class="lv-exec-row lv-exec-raw"><span class="lv-exec-key">data</span><span class="lv-exec-val">';
                h += pres.data.map((a, i) => '<span class="lv-exec-arg" title="data[' + (i + 1) + ']">' + (a ? lvEscape(a) : '<i>empty</i>') + '</span>').join('<span class="lv-exec-sep">`</span>');
                h += '</span></div>';
            }
        }
        document.getElementById('lvDetailResult').innerHTML = h;
    } else {
        resultWrap.style.display = 'none';
    }

    const trWrap = document.getElementById('lvDetailThrowableWrap');
    if (ev.throwable) {
        trWrap.style.display = 'block';
        document.getElementById('lvDetailThrowable').textContent = ev.throwable.replace(/\t/g, '\n    ');
    } else {
        trWrap.style.display = 'none';
    }
    document.getElementById('lvDetail').style.display = 'flex';
    lvRenderRows();
}
