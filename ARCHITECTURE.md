# Архитектура расширения

Тут описано как всё устроено внутри. Без воды, по делу.

---

## Общая структура

```
manifest.json              -- точка входа, permissions, content_scripts
src/
  background/
    service-worker.js      -- фоновый воркер: будильники, бейдж на иконке
  dashboard/
    dashboard.html         -- главная страница (дашборд)
    dashboard.js           -- вся логика дашборда (~3800 строк)
    dashboard.css          -- стили дашборда
    lv-mappings.js         -- маппинг RF-процедур WMS
  content/
    issues-menu.js         -- контекстное меню на страницах заявок
    similar-issues.js      -- поиск похожих заявок
    mail-checker.js        -- floating button на Яндекс Почте
    messenger-checker.js   -- детектор непрочитанных в Мессенджере
    magnit-checker.js      -- сканер ключевых слов в корп. мессенджере
    content-loader.js      -- инжектор стилей и кнопок
    features/
      issue-automator.js   -- автозаполнение формы создания заявки
  shared/
    menu.js                -- переиспользуемое контекстное меню
    modal.js               -- переиспользуемое модальное окно
    menu.css / modal.css   -- стили
  popup/
    popup.html/js/css      -- всплывающее окно расширения
  old_extension/
    shared.js              -- утилиты (clipboard, тема, форматирование смены)
    activity.js            -- управление сменами
    sync.js                -- синхронизация заявок
assets/
  icons/                   -- иконки расширения
  styles/                  -- глобальные CSS (main, modern, issues, similar-issues)
  alarm.mp3                -- звук будильника
```

---

## Канбан-дашборд

Доска в `dashboard.html` разбита на 5 вкладок: Board (kanban), Mail, Scripts, LogViewer, Settings. Переключение через `switchView()` (`dashboard.js:700`) -- просто скрывает/показывает div'ы.

### Как рисуется Kanban

Данные приходят из нескольких Redmine URL (настраиваются в Settings). Каждый URL -- это Redmine Query. Запросы идут через `fetch()` с credentials: 'same-origin' (чтобы cookies подхватывались):

```js
// dashboard.js:160
const SOURCES = {
    redmineUrls: [
        '<ссылка>/projects/pr-001/issues?query_id=<query_id>&limit=100',
        '<ссылка>/projects/wms2_sp_mystesd/issues?limit=100'
    ],
    mailUrl: 'https://mail.yandex.ru/lite'
};
```

Ответ парсится, результат складывается в `CACHED_ISSUES`. Колонки маппятся по статусу через `COLUMN_MAPPING`:

```js
// dashboard.js:169
const COLUMN_MAPPING = {
    new:  ['Новая', 'Новая информация', 'New', 'Уточнение', 'Назначена', 'Assigned'],
    work: ['В работе', 'В процессе', 'In Progress', 'Разработка'],
    wait: ['Ожидание', 'Согласование', 'Feedback', 'Hold', 'Отложена', 'Приостановлено']
};
```

Рендер -- обычный innerHTML в 각 колонку. KPI-карточки (общее, высокий приоритет, на удержании) считаются из `CACHED_ISSUES`.

### Автообновление

`setInterval` каждые N секунд (настраивается). Вызывает `initDashboard(true)` в тихом режиме -- без очистки экрана, просто обновляет данные:

```js
// dashboard.js:333
function startAutoRefresh(seconds) {
    stopAutoRefresh();
    REFRESH_TIMER = setInterval(() => {
        animateRefreshIcon();
        initDashboard(true);
    }, seconds * 1000);
}
```

### Wake Lock

Чтобы вкладка не засыпала и автообновление работало, используется Screen Wake Lock API:

```js
// dashboard.js:1014
async function requestWakeLock() {
    try {
        wakeLock = await navigator.wakeLock.request('screen');
        wakeLock.addEventListener('release', () => { wakeLock = null; });
    } catch (err) {
        console.error('Ошибка Wake Lock:', err.name, err.message);
    }
}
```

---

## Мониторинг Gmail

Интеграция через Gmail API + Chrome Identity.

### Получение токена

Токен не кешируется в JS -- `chrome.identity.getAuthToken()` сам обновляет протухший:

```js
// dashboard.js:735
chrome.identity.getAuthToken({ interactive: isInteractive }, function(token) {
    if (chrome.runtime.lastError || !token) return;
    GMAIL_TOKEN = token;
    fetchGmailData(token);
});
```

### Запросы к Gmail API

Два запроса: список сообщений и детали каждого. Запрос формируется из настроечной строки:

```js
// dashboard.js:754
const listUrl = `https://gmail.googleapis.com/gmail/v1/users/me/messages?q=${encodeURIComponent(query)}`;
```

Письма фильтруются: пропускаются те, которые уже в `ACKNOWLEDGED_MAILS`. Для остальных проверяется наличие триггерного текста ("Расхождения в пунктах") и номеров расхождений.

### Тихие пункты

Если в письме встречаются ТОЛЬКО номера из списка `gmailIgnoredPoints` -- будильник не запускается. Это нужно чтобы не тревожиться по мелочам:

```js
// dashboard.js:867
console.log(`письмо ${message.id} пропущено - только пункты ${points.join(', ')}`);
```

### Создание заявки из письма

Кнопка "Создать заявку" открывает URL вида `<ссылка>/projects/pr-001/issues/new` с предзаполненными полями через query params.

---

## Мониторинг Яндекс Почты

Content script `mail-checker.js` грузится на страницах `mail.yandex.ru` и `mail.360.yandex.ru`.

### Как работает

1. `MutationObserver` следит за изменениями DOM (SPA, подгрузка писем)
2. При каждом изменении `checkAndInject()` ищет текст "Расхождения в пунктах" в теле письма
3. Если найден -- определяется проект через `resolveProject()`:
   - Сначала ищет отправителя по `aria-label` в `SENDER_PROJECT_MAP`
   - Если отправитель -- Ева, парсит поле `Server:` из тела письма через `extractServer()`
4. Создаётся красная кнопка поверх письма, которая открывает форму создания заявки

```js
// mail-checker.js:172
function injectButton(url, label) {
    const btn = document.createElement('a');
    btn.href = url;
    btn.target = '_blank';
    btn.className = 'ltm-mail-btn';
    btn.textContent = label;
    // ... вставка в DOM
}
```

---

## Мониторинг Яндекс Мессенджера

Самый простой чекер -- 48 строк.

### Как работает

Приходит тик от service-worker (каждую минуту). Считает непрочитанные бейджи:

```js
// messenger-checker.js:15
function checkUnread() {
    const badges = document.querySelectorAll('.ui-badge.ui-badge_primary[id$="_unread"]');
    let currentUnreadCount = 0;
    badges.forEach(badge => {
        if (badge.offsetWidth === 0 || badge.offsetHeight === 0) return;
        const n = parseInt(badge.textContent, 10);
        if (!isNaN(n) && n > 0) currentUnreadCount += n;
    });
    // отправляем результат в background
}
```

Если count > 0 -- шлём `messenger_new_message`, иначе `messenger_cleared`. Background обновляет бейдж на иконке.

---

## Мониторинг корпоративного мессенджера

`magnit-checker.js` -- более сложный чекер. Тоже тиковый (от service-worker).

### Сканирование канала

Ищет свежие посты (менее 10 минут) в определённом канале. Посты ищутся по селектору `div[role="listitem"].item_measurer`:

```js
// magnit-checker.js:84
const posts = document.querySelectorAll('div[role="listitem"].item_measurer');
posts.forEach(post => {
    const timeEl = post.querySelector('time[datetime]');
    if (!timeEl) return;
    const postAge = Date.now() - new Date(timeEl.getAttribute('datetime')).getTime();
    if (postAge > TEN_MINUTES) return; // старые посты пропускаем
    // проверяем на ключевые слова
});
```

### Ключевые слова-триггеры

```js
// magnit-checker.js:27
const KEYWORDS = ['ЧС', 'ЧП', 'Зависани', '<team_name>', 'критик', 'критичн', 'массов'];
```

Поиск регистронезависимый. Если пост содержит хотя бы одно слово -- ставим маркер и шлём сигнал.

### Маркировка постов

На каждый свежий пост вешается атрибут `data-ltm-marked`, чтобы не метить дважды. К посту добавляется красный бейдж.

### Срочный канал

ID канала настраивается в Settings и хранится в `chrome.storage.sync`. Подхватывается на лету без перезагрузки вкладки:

```js
// magnit-checker.js:18
chrome.storage.onChanged.addListener((changes, area) => {
    if (area === 'sync' && changes.magnitUrgentChannel) {
        URGENT_CHANNEL = (changes.magnitUrgentChannel.newValue || DEFAULT_MAGNIT_URGENT_CHANNEL).trim();
    }
});
```

---

## Звуковой будильник

Обычный HTML5 `Audio` с зацикливанием:

```js
// dashboard.js:5
let ALARM_AUDIO = new Audio(chrome.runtime.getURL('assets/alarm.mp3'));
ALARM_AUDIO.loop = true;
```

Запускается при срабатывании любого триггера (Redmine, Gmail, Messenger, <Плейсхолдер>). Останавливается кнопкой "Стоп" или при подтверждении заявок/писем. При остановке -- все текущие заявки и письма добавляются в `ACKNOWLEDGED_ISSUES` / `ACKNOWLEDGED_MAILS`.

---

## Счётчик на иконке

Ведётся в `chrome.storage.session`. Агрегирует counts из 4 источников. Обновляется при каждом сообщении от content scripts или dashboard.

```js
// service-worker.js:86
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
```

---

## SQL-библиотека

Хранится в `chrome.storage.local` под ключом `ltm_scripts`. Массив объектов `{id, name, client, content}`.

### Основные операции

- Загрузка: `loadScriptsDB()` -- читает из storage
- Сохранение: `saveScriptsDB()` -- пишет в storage
- Рендер: `renderScriptsList()` -- фильтрует по клиенту и поисковому запросу, рисует карточки

### Подсветка SQL

Свой мини-парсер на regex. Токенизирует комментарии, строки, числа, ключевые слова и функции:

```js
// dashboard.js:1086
function highlightSQL(code) {
    const KEYWORDS = 'SELECT|FROM|WHERE|JOIN|...';
    const TOKEN_RE = new RegExp(
        '(--[^\\n]*)'              +  // комментарий
        "|('(?:[^'\\\\]|\\\\.)*')" +  // строка
        '|(\\b\\d+(?:\\.\\d+)?\\b)' + // число
        '|\\b(' + KEYWORDS + ')\\b',   // ключевое слово
        'gi'
    );
    // ...
}
```

### Импорт/экспорт

Экспорт -- `JSON.stringify(SCRIPTS_DB)`, копируется в буфер. Импорт -- парсинг JSON, проверка на дубликаты по `name + content`, добавление новых.

---

## Контекстное меню на заявках

`issues-menu.js` -- самый большой файл (~2000 строк). Работает только на страницах `/issues/\d+`.

### Перехват контекстного меню

Браузерное контекстное меню перехватывается через `contextmenu` event. Вместо него рисуется кастомный `Menu` из `src/shared/menu.js`:

```js
// issues-menu.js:1994
window.addEventListener('contextmenu', (e) => {
    // проверяем что мы на странице заявки
    // показываем кастомное меню
});
```

### Действия

- **Взять в работу** (`takeInWork()`, line 218): эмулирует клик "Редактировать", выставляет статус, назначает на себя, сабмитит форму. Использует `waitForElement()` с MutationObserver для ожидания DOM-элементов.
- **Добавить в смену** (`addIssueToShift()`, line 103): пушит данные в массив в `chrome.storage.local`, с проверками (причина обязательна, время обязательно).
- **Копировать запрос ЯМ**: собирает URL + описание + ссылку на Y-Tracker в одну строку.
- **SQL-скрипты**: `fetchWikiScript()` (line 426) делает fetch на wiki-страницу Redmine, парсит `<pre>` блок, копирует текст в буфер.

### Тулбар SQL-кнопок

`injectSQLToolbarButtons()` (line 1783) добавляет кнопки "SQL" и "SQL (вставка)" в тулбар редактора Redmine. При нажатии -- копирует скрипт в буфер или вставляет в textarea.

---

## Автозаполнение формы создания заявки

`issue-automator.js` -- грузится на `/issues/new`.

### Замена select проекта

Стандартный `<select>` Redmine прячется, вместо него рисуется текстовый инпут с выпадающим списком:

```js
// issue-automator.js:26
function transformProjectSelect() {
    const originalSelect = document.querySelector('#issue_project_id');
    if (!originalSelect) return;
    originalSelect.style.display = 'none';
    // создаем кастомный input + dropdown
}
```

При выборе проекта -- диспатчится `change` event, чтобы Redmine обновил форму (AJAX).

### Пресеты тем

Выпадающий список с фиксированными вариантами + опция "Написать вручную":

```js
// issue-automator.js:6
const CONFIG = {
    trackerId: '<tracker_id>',
    presets: [
        "HealthScript Job Notifier",
        "Проверка логов планировщика WMS Infor"
    ],
    causeFieldId: 'issue_custom_field_values_<field_id>',
    causeValue: "Превентивные мероприятия"
};
```

### Автозаполнение

`applyDefaults()` (line 170) ставит трекер, исполнителя (берет из `#loggedas a`), приватность и причину. `MutationObserver` следит за `#all_attributes` и переприменяет дефолты после AJAX-перерисовки формы.

---

## Поиск похожих заявок

`similar-issues.js` -- грузится на страницах просмотра и создания заявок.

### Извлечение ключей

Из темы и описания извлекаются два типа ключей:

1. **Якорные паттерны** (line 23) -- уникальные сигнатуры: ORA-коды ошибок, GUID, константы вида `NSPRF*`:

```js
const ANCHOR_PATTERNS = /\b(ORA-\d{5}|GUID|NSPRF\w+|[A-Z]{2,}\d{4,})\b/gi;
```

2. **Ключевые слова** (line 125) -- слова длиннее 4 букв, после фильтрации стоп-слов:

```js
const STOP_WORDS = ['который', 'которые', 'которая', 'которое', 'также', 'такого', ...];
```

### Поиск

`searchSimilar()` (line 318) делает запрос к `/search.json` (полный текст Redmine). Если пусто -- fallback на `/issues.json?subject=~keyword`.

Опционально сужает поиск до подпроектов клиента через `findClientRoot()` (line 203), который поднимается по дереву проектов Redmine до корня.

### Решения

Для топ-3 результатов подтягивается последний комментарий саппорта через `fetchSolution()` (line 388). Результаты кешируются в `Map` с TTL 10 минут.

---

## LogViewer

Парсер лог-файлов прямо в браузере. Поддерживает .log4j, .log, .xml форматы.

### Парсинг

Файл читается через `FileReader.readAsText()`. Каждая строка парсится регуляркой, извлекаются: timestamp, level, thread, user, message. Для XML -- через DOMParser.

### Фильтры

Уровень (DEBUG, INFO, WARN, ERROR, FATAL), поток, пользователь, временной диапазон, текстовый поиск. Все фильтры работают на клиенте -- данные уже загружены в память.

### Транзакции

События группируются по `taskId`. Группировка через `Map` -- собираются все записи с одинаковым taskId в цепочку.

### Визуальная шкала

Canvas-элемент с таймлайном. События рисуются как точки/полоски на временной оси. Цвета по уровню: DEBUG -- серый, INFO -- синий, WARN -- жёлтый, ERROR -- красный.

---

## Настройки

Вся конфигурация хранится в `chrome.storage.sync`. Чтение/запись -- стандартный API Chrome.

### Загрузка

```js
// dashboard.js:1480
chrome.storage.sync.get([
    'darkMode', 'uiStyle', 'alarmEnabled',
    'redmineUrls', 'columnMapping', 'autoRefresh',
    'senderProjectMap', 'serverProjectMap',
    'sqlAutoPrivate', 'messengerWatcher', 'magnitWatcher',
    'gmailIgnoredPoints', 'magnitUrgentChannel',
    'similarIssuesEnabled', 'redmineApiKey',
], (result) => { ... });
```

### Сохранение

При нажатии "Сохранить" -- собираются значения из всех input/select/checkbox, пишутся в storage. Если дашборд открыт -- рассылается `updateSettings` через `chrome.tabs.sendMessage()` чтобы вкладки Redmine обновились.

---

## Тёмная тема

Переключение через добавление/удаление класса `ltm-dark-mode` на `<html>`. Все стили написаны с учётом этого класса:

```css
.ltm-dark-mode { background: #1a1a2e; color: #e0e0e0; }
.ltm-dark-mode .settings-input { background: #2d2d44; color: #e0e0e0; }
```

Тема сохраняется в `chrome.storage.sync` и применяется при загрузке.

Два стиля интерфейса (Legacy/Modern) -- это просто разные CSS-файлы: `styles.css` (legacy) и `modern.css` (modern). Подключаются через `content-loader.js` в зависимости от настройки.

---

## Service Worker (фоновый воркер)

Фоновый скрипт -- `service-worker.js`. Запускается Chrome'ом при установке/обновлении расширения и при старте браузера.

### Будильники

```js
// service-worker.js:10
const ALARMS = {
    messenger: { name: 'messengerCheck', minutes: 1, action: 'messenger_tick',
                 urls: ['https://messenger.360.yandex.ru/*', 'https://messenger.yandex.ru/*'] },
    magnit:    { name: 'magnitCheck',    minutes: 1, action: 'magnit_tick',
                 urls: ['<корпоративный мессенджер>'] },
    gmail:     { name: 'gmailCheck',     minutes: 2, action: 'gmail_tick',
                 urls: null },
};
```

При срабатывании будильника -- ищет вкладки с подходящим URL и шлёт им сообщение. Для gmail -- broadcast через `runtime.sendMessage`.

### Бейдж

Агрегирует counts из всех источников. Красный если есть urgent. Сбрасывается при перезапуске Chrome (session storage).

---

## Shared компоненты

### Menu (menu.js)

Контекстное меню с поддержкой кнопок, тоглов, сепараторов, заголовков и подменю.

Ключевые методы:
- `addButton(label, onClick, opts)` -- добавить пункт
- `addToggle(label, checked, onChange)` -- добавить тогл
- `addSeparator()` -- разделитель
- `show(x, y)` -- показать в координатах
- `destroy()` -- удалить с анимацией

`Submenu` наследует `Menu` и добавляет привязку к anchor-элементу с flyout-поведением.

### Modal (modal.js)

Promise-based модальное окно. Резолвится с `{id: value}` при подтверждении или `null` при отмене.

```js
const modal = new Modal({ title: 'Заголовок', width: '420px' });
modal.addInput({ id: 'minutes', label: 'Время', placeholder: '70' });
const result = await modal.show();
if (result) { /* result.minutes -- введенное значение */ }
```
