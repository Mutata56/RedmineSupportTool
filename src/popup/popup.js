document.addEventListener('DOMContentLoaded', () => {
    const themeToggle = document.getElementById('themeToggle');
    const styleRadios = document.getElementsByName('uiStyle');
    const themeGroup = document.getElementById('themeControlGroup');
    const statusMsg = document.getElementById('statusMessage');
    // Добавляем получение элемента чекбокса
    const alarmToggle = document.getElementById('alarmEnabledToggle');

    const URLS = {
        dashboard: '<ссылка>/projects/pr-001/issues?query_id=<query_id>',
        lamoda: '<ссылка>/projects/wms2_sp_mystesd/issues'
    };

    // --- ЛОГИКА ОТКРЫТИЯ НОВОГО ДАШБОРДА ---
    document.getElementById('openCustomDashboard').addEventListener('click', () => {
        chrome.tabs.create({ url: 'src/dashboard/dashboard.html' });
    });

    // --- ЗАГРУЗКА НАСТРОЕК ---
    chrome.storage.sync.get(['darkMode', 'uiStyle', 'alarmEnabled'], (result) => {
        // Восстанавливаем состояние чекбокса звука
        alarmToggle.checked = result.alarmEnabled || false;

        const savedStyle = result.uiStyle || 'modern';
        const isDark = result.darkMode || false;

        for (const radio of styleRadios) {
            if (radio.value === savedStyle) radio.checked = true;
        }
        themeToggle.checked = isDark;
        updatePopupVisuals(savedStyle, isDark);
    });

    // --- ОБРАБОТЧИКИ СОБЫТИЙ ---

    // 1. Смена стиля
    styleRadios.forEach(radio => {
        radio.addEventListener('change', (e) => {
            const style = e.target.value;
            saveSetting('uiStyle', style);
            updatePopupVisuals(style, themeToggle.checked);
        });
    });

    // 2. Смена темы (Dark/Light)
    themeToggle.addEventListener('change', () => {
        const isDark = themeToggle.checked;
        saveSetting('darkMode', isDark);
        updatePopupVisuals(getSelectedStyle(), isDark);
    });

    // 3. ВКЛ/ВЫКЛ Звукового сигнала (ИСПРАВЛЕНО: теперь внутри функции)
    alarmToggle.addEventListener('change', (e) => {
        saveSetting('alarmEnabled', e.target.checked);
    });

    // 4. Кнопки ссылок
    document.getElementById('openOldDashboard').addEventListener('click', () => {
        chrome.tabs.create({ url: URLS.dashboard });
    });

    document.getElementById('openLamoda').addEventListener('click', () => {
        chrome.tabs.create({ url: URLS.lamoda });
    });

    // --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

    function getSelectedStyle() {
        for (const radio of styleRadios) {
            if (radio.checked) return radio.value;
        }
        return 'modern';
    }

    function updatePopupVisuals(style, isDark) {
        if (style === 'legacy') {
            themeGroup.style.opacity = '0.5';
            themeGroup.style.pointerEvents = 'none';
            document.body.className = '';
        } else {
            themeGroup.style.opacity = '1';
            themeGroup.style.pointerEvents = 'auto';
            document.body.className = isDark ? 'dark-theme' : '';
        }
    }

    function saveSetting(key, value) {
        chrome.storage.sync.set({ [key]: value }, () => {
            showStatus();
            // Отправляем сообщение на открытые вкладки Redmine (для стилей)
            chrome.tabs.query({ url: "*://<ссылка>/*" }, (tabs) => {
                tabs.forEach(tab => {
                    chrome.tabs.sendMessage(tab.id, {
                        action: 'updateSettings',
                        settings: { [key]: value }
                    });
                });
            });
        });
    }

    function showStatus() {
        statusMsg.classList.remove('hidden');
        setTimeout(() => statusMsg.classList.add('hidden'), 1000);
    }
});