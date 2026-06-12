// service-worker.js - Сердце расширения в фоновом режиме

// ============================================================================
// АЛАРМЫ: периодические "пинки" чекерам
// ============================================================================
// Зачем: setInterval в content scripts замирает, когда Chrome усыпляет фоновую
// вкладку. chrome.alarms переживает выгрузку SW и активирует чекер в любой
// момент - даже если вкладка спала.

const ALARMS = {
    messenger: { name: 'messengerCheck', minutes: 1, action: 'messenger_tick',
                 urls: ['https://messenger.360.yandex.ru/*', 'https://messenger.yandex.ru/*'] },
    magnit:    { name: 'magnitCheck',    minutes: 1, action: 'magnit_tick',
                 urls: ['<корпоративный мессенджер>'] },
    gmail:     { name: 'gmailCheck',     minutes: 2, action: 'gmail_tick',
                 urls: null /* широковещательно через runtime.sendMessage в дашборд */ },
};

function ensureAlarms() {
    Object.values(ALARMS).forEach(({ name, minutes }) => {
        chrome.alarms.get(name, (existing) => {
            if (!existing) {
                chrome.alarms.create(name, { periodInMinutes: minutes });
            }
        });
    });
}

chrome.runtime.onInstalled.addListener((details) => {
    if (details.reason === 'install') {
        console.log('<название> Support Pro установлен впервые. Применяю настройки по умолчанию.');
        chrome.storage.sync.set({
            darkMode: false,
            uiStyle:  'modern'
        }, () => console.log('Дефолтные настройки сохранены.'));
    }
    ensureAlarms();
});

chrome.runtime.onStartup.addListener(ensureAlarms);

// На случай "холодного" старта SW после выгрузки - гарантируем что будильники есть
ensureAlarms();

// ============================================================================
// РАЗДАЧА ТИКОВ
// ============================================================================

chrome.alarms.onAlarm.addListener((alarm) => {
    const cfg = Object.values(ALARMS).find(a => a.name === alarm.name);
    if (!cfg) return;

    if (cfg.urls) {
        // Пинаем все подходящие вкладки
        chrome.tabs.query({ url: cfg.urls }, (tabs) => {
            tabs.forEach(tab => {
                chrome.tabs.sendMessage(tab.id, { action: cfg.action }, () => {
                    // Заглатываем lastError: вкладка может быть discarded -
                    // тогда обработчика нет, и это нормально.
                    void chrome.runtime.lastError;
                });
            });
        });
    } else {
        // Широковещательно для страниц расширения (дашборд)
        chrome.runtime.sendMessage({ action: cfg.action }, () => {
            void chrome.runtime.lastError; // дашборд может быть закрыт
        });
    }
});

// ============================================================================
// БЕЙДЖ НА ИКОНКЕ
// ============================================================================
// Источники - messenger / <Плейсхолдер> (приходят от чекеров) и redmine / gmail
// (приходят от дашборда). Храним в chrome.storage.session - переживёт выгрузку
// SW, но обнулится при перезапуске Chrome (что и нужно).

const BADGE_KEY = 'badgeCounts';

async function readCounts() {
    const { [BADGE_KEY]: c } = await chrome.storage.session.get(BADGE_KEY);
    return c || { messenger: 0, magnit: 0, redmine: 0, gmail: 0, urgent: false };
}

async function writeCounts(counts) {
    await chrome.storage.session.set({ [BADGE_KEY]: counts });
    const total = counts.messenger + counts.magnit + counts.redmine + counts.gmail;
    if (total > 0) {
        chrome.action.setBadgeText({ text: total > 99 ? '99+' : String(total) });
        chrome.action.setBadgeBackgroundColor({
            color: counts.urgent ? '#ef4444' : '#3b82f6'
        });
    } else {
        chrome.action.setBadgeText({ text: '' });
    }
}

chrome.runtime.onMessage.addListener((req) => {
    if (!req?.action) return;

    (async () => {
        const counts = await readCounts();
        let changed = false;

        switch (req.action) {
            case 'messenger_new_message':
                counts.messenger = req.count || 1; changed = true; break;
            case 'messenger_cleared':
                if (counts.messenger !== 0) { counts.messenger = 0; changed = true; }
                break;
            case 'magnit_new_message':
                counts.magnit = req.count || 1; changed = true; break;
            case 'dashboard_counts':
                // {redmine, gmail, urgent} - дашборд шлёт после каждого рендера
                if (typeof req.redmine === 'number') counts.redmine = req.redmine;
                if (typeof req.gmail   === 'number') counts.gmail   = req.gmail;
                if (typeof req.urgent  === 'boolean') counts.urgent = req.urgent;
                changed = true;
                break;
        }

        if (changed) await writeCounts(counts);
    })();
});

// Первичная отрисовка при старте SW (если что-то лежит в session)
readCounts().then(writeCounts);
