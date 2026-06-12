// messenger-checker.js
// Тики приходят из service-worker через chrome.alarms (см. background/service-worker.js).
// Это надёжнее чем setInterval, который замирает у выгруженных фоновых вкладок.

chrome.storage.sync.get(['messengerWatcher'], ({ messengerWatcher = true }) => {
    if (!messengerWatcher) {
        console.log('Messenger Checker отключён в настройках');
        return;
    }

    console.log('Messenger Checker запущен');

    let lastUnreadCount = 0;

    function checkUnread() {
        const badges = document.querySelectorAll('.ui-badge.ui-badge_primary[id$="_unread"]');
        let currentUnreadCount = 0;

        badges.forEach(badge => {
            // Пропускаем скрытые элементы (display:none / visibility:hidden)
            if (badge.offsetHeight === 0 && badge.offsetWidth === 0) return;

            const raw = (badge.innerText || '').trim();
            const num = parseInt(raw, 10);
            if (!isNaN(num) && num > 0) currentUnreadCount += num;
        });

        if (currentUnreadCount > 0) {
            chrome.runtime.sendMessage({
                action: 'messenger_new_message',
                count:  currentUnreadCount
            });
        } else if (lastUnreadCount > 0) {
            // Перешли из "есть непрочитанные" в "всё прочитано" - мгновенно гасим
            chrome.runtime.sendMessage({ action: 'messenger_cleared' });
        }

        lastUnreadCount = currentUnreadCount;
    }

    // Слушаем тики от service-worker
    chrome.runtime.onMessage.addListener((req) => {
        if (req?.action === 'messenger_tick') checkUnread();
    });

    // Первая проверка сразу при загрузке страницы (не ждём первый alarm)
    checkUnread();
});
