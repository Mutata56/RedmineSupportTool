// magnit-checker.js
// Тики приходят из service-worker через chrome.alarms (см. background/service-worker.js).
// Это надёжнее чем setInterval, который замирает у выгруженных фоновых вкладок.

const DEFAULT_MAGNIT_URGENT_CHANNEL = '<ID канала>';

chrome.storage.sync.get(['magnitWatcher', 'magnitUrgentChannel'], (result) => {
    const magnitWatcher = result.magnitWatcher !== false;
    if (!magnitWatcher) {
        console.log('<Плейсхолдер> Checker отключён в настройках');
        return;
    }

    console.log('<Плейсхолдер> Checker запущен');

    let URGENT_CHANNEL = (result.magnitUrgentChannel || DEFAULT_MAGNIT_URGENT_CHANNEL).trim();
    // Подхватываем смену канала на лету, без перезагрузки вкладки
    chrome.storage.onChanged.addListener((changes, area) => {
        if (area === 'sync' && changes.magnitUrgentChannel) {
            URGENT_CHANNEL = (changes.magnitUrgentChannel.newValue || DEFAULT_MAGNIT_URGENT_CHANNEL).trim();
        }
    });

    // Поиск регистронезависимый - покрывает все формы слова:
    // критик → критика, критикует | критичн → критично, критичная, критичный
    // массов → массовая, массовые, массовое
    const KEYWORDS = ['ЧС', 'ЧП', 'Зависани', '<team_name>', 'критик', 'критичн', 'массов'];
    const TEN_MINUTES = 10 * 60 * 1000;
    const MARKER_ATTR = 'data-ltm-marked';

    function markPost(post) {
        // Не добавляем маркер дважды
        if (post.hasAttribute(MARKER_ATTR)) return;
        post.setAttribute(MARKER_ATTR, '1');

        const badge = document.createElement('span');
        badge.textContent = '<название>';
        badge.style.cssText = [
            'display: inline-flex',
            'align-items: center',
            'gap: 4px',
            'background: #ff4444',
            'color: #fff',
            'font-size: 11px',
            'font-weight: 700',
            'padding: 2px 7px',
            'border-radius: 4px',
            'margin-left: 8px',
            'vertical-align: middle',
            'letter-spacing: 0.5px',
            'pointer-events: none',
            'z-index: 9999',
        ].join(';');

        // Вставляем значок рядом с именем автора
        const nameEl = post.querySelector('.col.col__name');
        if (nameEl) {
            nameEl.appendChild(badge);
        } else {
            // Запасной вариант - в шапку поста
            const header = post.querySelector('.post__header');
            if (header) header.appendChild(badge);
        }
    }

    function tick() {
        // ── 1. Упоминания ────────────────────────────────────────────────────
        const mentionEl = document.querySelector('#unreadMentions .unreadMentions');
        const currentMentions = parseInt(mentionEl?.innerText || '0', 10);

        if (currentMentions > 0) {
            console.log(`Есть упоминания в <Плейсхолдер>! (${currentMentions})`);
            chrome.runtime.sendMessage({
                action: 'magnit_new_message',
                count: currentMentions
            });
        }

        // ── 2. Сканирование постов в срочном канале ──────────────────────────
        if (URGENT_CHANNEL && location.href.includes(URGENT_CHANNEL)) {
            // Раньше тут был принудительный scrollTop = scrollHeight каждую минуту -
            // убрано, потому что это мешало читать историю канала. Сейчас рассчитываем
            // на внешнее автообновление страницы (или ручной скролл пользователя).
            const posts = document.querySelectorAll('div[role="listitem"].item_measurer');
            const now = Date.now();
            let alarmTriggered = false;

            for (const post of posts) {
                // Берём время поста
                const timeEl = post.querySelector('time[datetime]');
                if (!timeEl) continue;

                const postTime = new Date(timeEl.getAttribute('datetime')).getTime();
                if (isNaN(postTime) || now - postTime > TEN_MINUTES) continue;

                // Пост свежий - ставим маркер (независимо от ключевых слов)
                markPost(post);

                // Берём текст и проверяем ключевые слова
                const textEl = post.querySelector('[id^="postMessageText"] .post-message__text');
                if (!textEl) continue;
                const text = (textEl.innerText || '').toLowerCase();

                if (!alarmTriggered && KEYWORDS.some(kw => text.includes(kw.toLowerCase()))) {
                    console.log(`Срочное сообщение в <Плейсхолдер>-канале: "${text.substring(0, 80)}"`);
                    chrome.runtime.sendMessage({
                        action: 'magnit_new_message',
                        count: 1
                    });
                    alarmTriggered = true; // одного сигнала за итерацию достаточно
                }
            }
        }
    }

    // Слушаем тики от service-worker
    chrome.runtime.onMessage.addListener((req) => {
        if (req?.action === 'magnit_tick') tick();
    });

    // Первая проверка сразу при загрузке страницы (не ждём первый alarm)
    tick();
});
