/**
 * <название> - Issues Page Context Menu
 * Активируется только на страницах тикетов: /issues/{id}
 *
 * Зависит от: src/shared/menu.js      (<название>Menu, <название>Submenu)
 *             src/old_extension/shared.js (isDarkMode, toggleDarkMode,
 *                                          getStoredShift, saveStorage,
 *                                          getCategoryByStatus)
 * @version 1.1.0
 * @author  KKRLL56
 */

(function () {
    'use strict';

    // Срабатываем только на страницах конкретного тикета /issues/12345
    if (!/^\/issues\/\d+/.test(location.pathname)) return;

    // =========================================================================
    // Helpers - идентификация тикета
    // =========================================================================

    /**
     * Возвращает числовой ID тикета из текущего URL или null.
     * @returns {string|null}
     */
    function getCurrentIssueId() {
        const m = location.pathname.match(/^\/issues\/(\d+)/);
        return m ? m[1] : null;
    }

    /**
     * Проверяет, добавлен ли тикет в текущую смену.
     * @param {string} issueId
     * @returns {boolean}
     */
    function isIssueInShift(issueId) {
        try {
            const shift = getStoredShift();
            return Object.values(shift).some(arr =>
                arr.some(line => line.includes('/issues/' + issueId))
            );
        } catch {
            return false;
        }
    }

    // =========================================================================
    // Helpers - данные тикета из DOM текущей страницы
    // =========================================================================

    /**
     * Считывает данные тикета с открытой страницы.
     * @returns {{ issueId, url, clientName, subject, status, category, line }|null}
     */
    function getIssueDataFromPage() {
        try {
            const issueId = getCurrentIssueId();
            if (!issueId) return null;

            const url = location.origin + '/issues/' + issueId;

            // Клиент / проект
            const clientEl  = document.querySelector('span.current-project');
            const clientName = clientEl ? clientEl.innerText.trim() : '';

            // Тема тикета (без вложенных span'ов - они содержат ID и прочий мусор)
            const subjectEl = document.querySelector('.subject h3');
            let subject = '';
            if (subjectEl) {
                const cloned = subjectEl.cloneNode(true);
                cloned.querySelectorAll('span').forEach(s => s.remove());
                subject = cloned.textContent.trim();
            }

            // Статус
            const statusEl = document.querySelector('#content .status.attribute .value');
            const status   = statusEl ? statusEl.innerText.trim() : '';

            // Категория смены по статусу; по умолчанию - «В работе»
            const category = getCategoryByStatus(status) || '\u0412 \u0440\u0430\u0431\u043e\u0442\u0435';

            // Итоговая строка в формате смены: URL – Клиент: Тема
            const line = url + ' \u2013 ' + clientName + ': ' + subject;

            return { issueId, url, clientName, subject, status, category, line };
        } catch (e) {
            console.error('<название> issues-menu: getIssueDataFromPage failed', e);
            return null;
        }
    }

    // =========================================================================
    // Helpers - операции со сменой
    // =========================================================================

    /**
     * Добавляет тикет в смену.
     * Если тикет уже есть - ничего не делает и возвращает false.
     * @param {{ issueId, category, line }} data
     * @returns {boolean} true если добавлен
     */
    function addIssueToShift(data) {
        const shift = getStoredShift();

        // Защита от дубликатов
        const alreadyIn = Object.values(shift).some(arr =>
            arr.some(line => line.includes('/issues/' + data.issueId))
        );
        if (alreadyIn) return false;

        if (!Array.isArray(shift[data.category])) shift[data.category] = [];
        shift[data.category].push(data.line);
        saveStorage(shift);
        return true;
    }

    /**
     * Удаляет все записи с данным issueId из смены.
     * @param {string} issueId
     * @returns {boolean} true если хоть одна запись удалена
     */
    function removeIssueFromShift(issueId) {
        const shift   = getStoredShift();
        let   removed = false;

        Object.keys(shift).forEach(cat => {
            const before = shift[cat].length;
            shift[cat]   = shift[cat].filter(line => !line.includes('/issues/' + issueId));
            if (shift[cat].length !== before) removed = true;
        });

        if (removed) saveStorage(shift);
        return removed;
    }

    // =========================================================================
    // Helpers - проверки перед добавлением в смену
    // =========================================================================

    /**
     * Проверяет, заполнена ли причина обращения (.cf_109.attribute .value).
     * @returns {{ ok: boolean, message: string }}
     */
    function checkReason() {
        const el = document.querySelector('.cf_109.attribute .value');
        const ok = !!(el && el.textContent.trim());
        return {
            ok,
            message: ok ? '' : 'Не указана причина обращения'
        };
    }

    /**
     * Проверяет, есть ли трудозатраты (.spent-time.attribute .value a).
     * Считается пустым если элемента нет или значение начинается с "0:00".
     * @returns {{ ok: boolean, message: string }}
     */
    function checkTimeSpent() {
        const el   = document.querySelector('.spent-time.attribute .value a');
        const text = el ? el.textContent.trim() : '';
        const ok   = !!(text && !text.startsWith('0:00'));
        return {
            ok,
            message: ok ? '' : 'Нет трудозатрат'
        };
    }

    /**
     * Запускает все проверки и возвращает список сообщений об ошибках.
     * Пустой массив означает, что все проверки пройдены.
     * @returns {string[]}
     */
    function runShiftChecks() {
        return [checkReason(), checkTimeSpent()]
            .filter(r => !r.ok)
            .map(r => r.message);
    }

    // =========================================================================
    // Helpers - DOM / async
    // =========================================================================

    /**
     * Возвращает Promise, который резолвится через ms миллисекунд.
     * @param {number} ms
     */
    const delay = ms => new Promise(r => setTimeout(r, ms));

    /**
     * Ждёт появления элемента в DOM (MutationObserver + timeout).
     * @param {string}  selector
     * @param {number}  [timeout=4000]
     * @returns {Promise<Element|null>}
     */
    function waitForElement(selector, timeout = 4000) {
        const el = document.querySelector(selector);
        if (el) return Promise.resolve(el);

        return new Promise(resolve => {
            const obs = new MutationObserver(() => {
                const found = document.querySelector(selector);
                if (found) { obs.disconnect(); resolve(found); }
            });
            obs.observe(document.body, { childList: true, subtree: true });
            setTimeout(() => { obs.disconnect(); resolve(null); }, timeout);
        });
    }

    // =========================================================================
    // «Взять в работу»
    // =========================================================================

    /**
     * Имитирует нажатие «Редактировать», выставляет статус «В процессе: В работе»
     * и назначает тикет на текущего пользователя («мне»), затем сабмитит форму.
     */
    async function takeInWork() {
        // 1. Открыть форму редактирования
        const editLink = document.querySelector('a.icon.icon-edit');
        if (!editLink) {
            showToast('\u041a\u043d\u043e\u043f\u043a\u0430 "\u0420\u0435\u0434\u0430\u043a\u0442\u0438\u0440\u043e\u0432\u0430\u0442\u044c" \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d\u0430 \u043d\u0430 \u0441\u0442\u0440\u0430\u043d\u0438\u0446\u0435', 'error');
            return;
        }
        editLink.click();

        // 2. Дождаться появления select статуса
        const statusSel = await waitForElement('#issue_status_id', 4000);
        if (!statusSel) {
            showToast('\u0424\u043e\u0440\u043c\u0430 \u0440\u0435\u0434\u0430\u043a\u0442\u0438\u0440\u043e\u0432\u0430\u043d\u0438\u044f \u043d\u0435 \u043e\u0442\u043a\u0440\u044b\u043b\u0430\u0441\u044c (timeout)', 'error');
            return;
        }

        // 2b. Скрыть блок редактирования - автоматизация должна быть невидимой
        const updateBlock = document.querySelector('#update');
        if (updateBlock) updateBlock.style.display = 'none';

        await delay(150); // небольшая пауза после появления формы

        // 3. Выставить статус «В процессе: В работе»
        const workOpt = Array.from(statusSel.options).find(o =>
            o.text.toLowerCase().includes('\u0432 \u0440\u0430\u0431\u043e\u0442\u0435')
        );
        if (!workOpt) {
            if (updateBlock) updateBlock.style.display = '';
            showToast('\u0421\u0442\u0430\u0442\u0443\u0441 "\u0412 \u0440\u0430\u0431\u043e\u0442\u0435" \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d \u0432 \u0441\u043f\u0438\u0441\u043a\u0435 (\u0432\u043e\u0437\u043c\u043e\u0436\u043d\u043e \u0442\u0438\u043a\u0435\u0442 \u0443\u0436\u0435 \u0432 \u0440\u0430\u0431\u043e\u0442\u0435?)', 'error');
            return;
        }
        statusSel.value = workOpt.value;
        // Redmine слушает onchange: updateIssueFrom(...)
        statusSel.dispatchEvent(new Event('change', { bubbles: true }));

        // 4. Дождаться завершения AJAX-обновления формы Redmine
        await delay(1500);

        // 5. Назначить на «мне» - опция с текстом «<< мне >>»
        const assignSel = document.querySelector('#issue_assigned_to_id');
        if (!assignSel) {
            if (updateBlock) updateBlock.style.display = '';
            showToast('"\u041d\u0430\u0437\u043d\u0430\u0447\u0435\u043d\u0430" \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d\u0430 \u043f\u043e\u0441\u043b\u0435 \u043e\u0431\u043d\u043e\u0432\u043b\u0435\u043d\u0438\u044f \u0444\u043e\u0440\u043c\u044b', 'error');
            return;
        }
        const meOpt = Array.from(assignSel.options).find(o => o.text.includes('<<'));
        if (!meOpt) {
            if (updateBlock) updateBlock.style.display = '';
            showToast('\u041e\u043f\u0446\u0438\u044f "\u043c\u043d\u0435" \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d\u0430 \u0432 \u0441\u043f\u0438\u0441\u043a\u0435 \u043d\u0430\u0437\u043d\u0430\u0447\u0435\u043d\u0438\u044f', 'error');
            return;
        }
        assignSel.value = meOpt.value;
        assignSel.dispatchEvent(new Event('change', { bubbles: true }));

        // 6. Нажать «Принять» - строго внутри form#issue-form
        await delay(200);
        const submitBtn = document.querySelector('form#issue-form input[type="submit"][name="commit"]');
        if (!submitBtn) {
            if (updateBlock) updateBlock.style.display = '';
            showToast('\u041a\u043d\u043e\u043f\u043a\u0430 "\u041f\u0440\u0438\u043d\u044f\u0442\u044c" \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d\u0430', 'error');
            return;
        }
        submitBtn.click();
    }

    // =========================================================================
    // Helpers - форматирование времени
    // =========================================================================

    /**
     * Переводит минуты в формат H:MM, который принимает Redmine.
     * Примеры: 70 → "1:10", 30 → "0:30", 125 → "2:05"
     * @param {number} totalMinutes
     * @returns {string}
     */
    function minutesToHours(totalMinutes) {
        const h = Math.floor(totalMinutes / 60);
        const m = totalMinutes % 60;
        return h + ':' + String(m).padStart(2, '0');
    }

    // =========================================================================
    // Toast-уведомление (не блокирующее, в отличие от alert)
    // =========================================================================

    /**
     * Показывает небольшое всплывающее уведомление в правом нижнем углу.
     *
     * @param {string}                    message
     * @param {'ok'|'error'|'loading'}    [type='ok']
     * @param {number}                    [duration=2200]  мс до исчезновения;
     *                                    для type='loading' игнорируется (скрывается через dismiss)
     * @returns {{ dismiss: Function }}   вызов dismiss() мгновенно скрывает тост
     */
    function showToast(message, type = 'ok', duration = 2200) {
        const bgMap = {
            ok:      '#16a34a',
            error:   '#dc2626',
            loading: '#2563eb',
        };
        const toast = document.createElement('div');
        toast.style.cssText = [
            'position:fixed',
            'bottom:18px',
            'right:18px',
            'z-index:99999',
            'max-width:320px',
            'padding:9px 14px',
            'border-radius:8px',
            'font:500 12px/1.4 "Inter","Segoe UI",sans-serif',
            'color:#fff',
            'box-shadow:0 4px 16px rgba(0,0,0,.18)',
            'pointer-events:none',
            'opacity:0',
            'transform:translateY(6px)',
            'transition:opacity .18s ease,transform .18s ease',
            'background:' + (bgMap[type] || bgMap.ok),
        ].join(';');
        toast.textContent = message;
        document.body.appendChild(toast);

        // Двойной rAF гарантирует, что браузер успел отрисовать начальное
        // состояние (opacity:0) до запуска CSS-перехода
        requestAnimationFrame(() => requestAnimationFrame(() => {
            toast.style.opacity = '1';
            toast.style.transform = 'translateY(0)';
        }));

        const hide = () => {
            toast.style.opacity = '0';
            toast.style.transform = 'translateY(6px)';
            setTimeout(() => toast.remove(), 220);
        };

        if (type !== 'loading') {
            setTimeout(hide, duration);
        }

        return { dismiss: hide };
    }

    // =========================================================================
    // «ЯМ Запрос» - копирование в буфер обмена
    // =========================================================================

    /**
     * Формирует и копирует в буфер обмена текст для ЯМ-запроса:
     *   1) Чистая ссылка на тикет (без query-параметров)
     *   2) Ссылка на задачу в Я-трекере (поле cf_27)
     *   [пустая строка]
     *   3) Текст описания тикета (.description .wiki)
     */
    async function copyYMRequest() {
        // 1. Чистый URL тикета - без query-параметров
        const issueId = getCurrentIssueId();
        if (!issueId) {
            showToast('\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u043e\u043f\u0440\u0435\u0434\u0435\u043b\u0438\u0442\u044c ID \u0442\u0438\u043a\u0435\u0442\u0430', 'error');
            return;
        }
        const issueUrl = location.origin + '/issues/' + issueId;

        // 2. Ссылка на задачу в Я-трекере (поле «Я-трекер», custom field 27)
        const trackerEl  = document.querySelector('.cf_27.attribute .value a');
        const trackerUrl = trackerEl ? trackerEl.href.trim() : '';

        // 3. Описание тикета - берём только вики-блок, без кнопки «Цитировать»
        const wikiEl   = document.querySelector('.description .wiki');
        const descText = wikiEl ? wikiEl.innerText.trim() : '';

        if (!trackerUrl && !descText) {
            showToast('\u041d\u0435\u0442 \u0434\u0430\u043d\u043d\u044b\u0445 \u0434\u043b\u044f \u043a\u043e\u043f\u0438\u0440\u043e\u0432\u0430\u043d\u0438\u044f', 'error');
            return;
        }

        // Собираем итоговый текст
        const parts = [issueUrl];
        if (trackerUrl) parts.push(trackerUrl);
        parts.push(''); // пустая строка-разделитель
        if (descText)  parts.push(descText);

        const clipboardText = parts.join('\n');

        try {
            await navigator.clipboard.writeText(clipboardText);
            showToast('\u0421\u043a\u043e\u043f\u0438\u0440\u043e\u0432\u0430\u043d\u043e \u0432 \u0431\u0443\u0444\u0435\u0440 \u043e\u0431\u043c\u0435\u043d\u0430 \u2713');
        } catch (err) {
            console.error('<название> copyYMRequest: clipboard error', err);
            showToast('\u041e\u0448\u0438\u0431\u043a\u0430 \u043a\u043e\u043f\u0438\u0440\u043e\u0432\u0430\u043d\u0438\u044f \u0432 \u0431\u0443\u0444\u0435\u0440', 'error');
        }
    }

    // =========================================================================
    // HS - «Ева»: получить SQL-скрипт с вики-страницы и скопировать в буфер
    // =========================================================================

    /**
     * Загружает страницу HealthScript ЕВА v2.3 из вики Redmine,
     * извлекает содержимое первого <pre> внутри div.wiki.wiki-page
     * и копирует текст скрипта в буфер обмена БЕЗ ИЗМЕНЕНИЙ.
     */
    /**
     * Универсальная функция: загружает вики-страницу Redmine,
     * извлекает текст первого <pre> внутри div.wiki.wiki-page
     * и копирует в буфер обмена без изменений.
     *
     * @param {string} url   - Полный URL вики-страницы
     * @param {string} label - Название скрипта для toast-уведомлений (напр. «ЕВА»)
     */
    async function fetchWikiScript(url, label) {
        const loading = showToast('\u0417\u0430\u0433\u0440\u0443\u0437\u043a\u0430 \u0441\u043a\u0440\u0438\u043f\u0442\u0430 ' + label + '\u2026', 'loading');

        try {
            const resp = await fetch(url, { credentials: 'include' });
            if (!resp.ok) throw new Error('HTTP ' + resp.status);

            const html = await resp.text();
            const doc  = new DOMParser().parseFromString(html, 'text/html');

            // <pre> или <pre><code> - textContent стриппит все span-теги подсветки
            const preEl = doc.querySelector('div.wiki.wiki-page pre');
            if (!preEl) throw new Error('\u042d\u043b\u0435\u043c\u0435\u043d\u0442 <pre> \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d \u043d\u0430 \u0441\u0442\u0440\u0430\u043d\u0438\u0446\u0435');

            await navigator.clipboard.writeText(preEl.textContent);

            loading.dismiss();
            showToast('\u0421\u043a\u0440\u0438\u043f\u0442 ' + label + ' \u0441\u043a\u043e\u043f\u0438\u0440\u043e\u0432\u0430\u043d \u2713');

        } catch (err) {
            console.error('<название> fetchWikiScript [' + label + ']:', err);
            loading.dismiss();
            showToast('\u041e\u0448\u0438\u0431\u043a\u0430 ' + label + ': ' + err.message, 'error', 4000);
        }
    }

    const fetchHSEva     = () => fetchWikiScript(
        '<ссылка>',
        '\u0415\u0412\u0410'
    );

    const fetchHSMolniya = () => fetchWikiScript(
        '<ссылка>',
        '\u041c\u043e\u043b\u043d\u0438\u044f'
    );

    // =========================================================================
    // HS - «Остальные клиенты»: хардкодный HEALTH_MSSQL.SQL
    // =========================================================================

    /* eslint-disable */
    const HS_OTHER_SCRIPT =
`/* HEALTH_MSSQL.SQL */

/* Compare different inventory tables to see if we got a problem with data integrity */

/* 07/14/98 DS Updated for Exceed.cs 2.03 */
/* 06/04/01 DS Updated for Exceed.cs 3 SR6 */
/* 05/04/2006 SS Removed ID Check for WM40 */
/* 01/31/2012 JK Removed xorderdetail, xpickdetail 10.0*/

set nocount on
print '************************************************************************'
print ' '
select  'Server' = convert(char(20), @@servername),
    'Database'= convert(char(20), db_name()),
    'Current date' = getdate()
print '************************************************************************'
print '************************************************************************'

select '<1> comparing sum(Qty by Storerkey,Sku) of SKUxLOC and sum(Qty by Storerkey,Sku) in LOTxLOCxID '

select sku, storerkey, qty = sum(qty) into #temp_sum
from skuxloc (nolock)
where qty > 0
group by storerkey,sku

select sku, storerkey, qty = sum(qty) into #temp_sum1
from lotxlocxid (nolock)
where qty > 0
group by storerkey,sku

select a_storerkey = a.storerkey, a_sku = a.sku, b_storerkey = b.storerkey, b_sku = b.sku,
     sum_skuxloc =a.qty, sum_lotxlocxid = b.qty into #info
from #temp_sum a FULL OUTER JOIN #temp_sum1 b on a.sku = b.sku and a.storerkey = b.storerkey
where  a.qty <> b.qty
   or a.sku is null or b.sku is null
   or a.storerkey is null or b.storerkey is null
go
if exists (select 1 from #info)
  select * from #info
drop table #info
drop table #temp_sum
drop table #temp_sum1
go

select '<2> comparing sum(Qty by Loc) of SKUxLOC and sum(Qty by Loc) in LOTxLOCxID '

select loc, qty = sum(qty) into #temp_sum
from skuxloc (nolock)
where qty > 0
group by loc

select loc, qty = sum(qty) into #temp_sum1
from lotxlocxid (nolock)
where qty > 0
group by loc

select a_loc = a.loc, b_loc = b.loc, sum_skuxloc = a.qty, sum_lotxlocxid = b.qty into #info
from #temp_sum a FULL OUTER JOIN #temp_sum1 b ON a.loc = b.loc
where a.qty <> b.qty
   or a.loc is null or b.loc is null
go
if exists (select 1 from #info)
   select * from #info
drop table #info
drop table #temp_sum
drop table #temp_sum1
go

select '<3> comparing sum (Qty by Storerkey,Sku) of LOT and sum(Qty by Storerkey,Sku) in SKUxLOC '

select sku, storerkey, qty = sum(qty) into #temp_sum
from lot (nolock)
where qty > 0
group by storerkey, sku

select sku, storerkey, qty = sum(qty) into #temp_sum1
from skuxloc (nolock)
where qty > 0
group by storerkey,sku

select a_storerkey = a.storerkey, a_sku = a.sku, b_storerkey = b.storerkey, b_sku = b.sku,
     sum_lot = a.qty, sum_skuxloc = b.qty into #info
from #temp_sum a FULL OUTER JOIN #temp_sum1 b ON a.sku = b.sku and a.storerkey = b.storerkey
where a.qty <> b.qty
or a.sku is null or b.sku is null or a.storerkey is null or b.storerkey is null
go
if exists (select 1 from #info)
     select * from #info
drop table #info
drop table #temp_sum
drop table #temp_sum1
go

select '<4> comparing LOT and sum(Qty by Lot) in LOTxLOCxID '

select lot, qty = sum(qty) into #temp_sum
from lotxlocxid (nolock)
where qty > 0
group by lot

select a_lot = b.lot, b_lot = a.lot,  lot_qty =  b.qty , sum_lotxlocxid = a.qty into #info
from #temp_sum a FULL OUTER JOIN lot b (nolock) ON a.lot = b.lot
where b.qty > 0 and ( a.qty <> b.qty
  or a.lot is null or b.lot is null)
go
if exists (select 1 from #info)
     select * from #info
drop table #info
drop table #temp_sum
go

select '<6> comparing lot and sum(QtyAllocated by lot) in lotxlocxid '

select lot, QtyAllocated = sum(QtyAllocated) into #temp_sum
from lotxlocxid (nolock)
where QtyAllocated > 0
group by lot

select a_lot = b.lot, b_lot = a.lot,  lot_QtyAllocated = b.QtyAllocated,  sum_lotxlocxid = a.QtyAllocated into #info
from #temp_sum a FULL OUTER JOIN lot b (nolock) ON a.lot = b.lot
where b.QtyAllocated > 0 and (a.QtyAllocated <> b.QtyAllocated or a.lot is null or b.lot is null)
go
if exists (select 1 from #info)
     select * from #info
drop table #info
drop table #temp_sum
go

select '<7> comparing lot (QtyAllocated by storerkey, sku) and sum( QtyAllocated by storerkey, sku) skuxloc '

select storerkey, sku, QtyAllocated = sum(QtyAllocated) into #temp_sum
from lot (nolock)
where QtyAllocated > 0
group by storerkey, sku

select storerkey, sku, QtyAllocated = sum(QtyAllocated) into #temp_sum1
from skuxloc (nolock)
where QtyAllocated > 0
group by storerkey, sku

select a_storerkey = a.storerkey, a_sku = a.sku, b_storerkey = b.storerkey, b_sku = b.sku,
   sum_lot = a.QtyAllocated,  sum_skuxloc = b.QtyAllocated into #info
from #temp_sum a FULL OUTER JOIN #temp_sum1 b ON a.storerkey = b.storerkey and a.sku = b.sku
where a.QtyAllocated <> b.QtyAllocated
   or a.storerkey is null or b.storerkey is null
   or a.sku is null or b.sku is null
go
if exists (select 1 from #info)
     select * from #info
drop table #info
drop table #temp_sum
drop table #temp_sum1
go

select '<8> comparing sum( QtyAllocated by storer,sku ) of lotxlocxid and sum( QtyAllocated by storer,sku) skuxloc '

select storerkey, sku, QtyAllocated = sum(QtyAllocated) into #temp_sum
from lotxlocxid (nolock)
where QtyAllocated > 0
group by storerkey, sku

select storerkey, sku, QtyAllocated = sum(QtyAllocated) into #temp_sum1
from skuxloc (nolock)
where QtyAllocated > 0
group by storerkey, sku

select a_storerkey = a.storerkey, a_sku = a.sku, b_storerkey = b.storerkey, b_sku = b.sku,
sum_lotxlocxid = a.QtyAllocated, sum_skuxloc = b.QtyAllocated  into #info
from #temp_sum a FULL OUTER JOIN #temp_sum1 b ON a.storerkey = b.storerkey and a.sku = b.sku
where a.QtyAllocated <> b.QtyAllocated
   or a.storerkey is null or b.storerkey is null
   or a.sku is null or b.sku is null
go
if exists (select 1 from #info)
     select * from #info
drop table #info
drop table #temp_sum
drop table #temp_sum1
go

select '<9> comparing lot and sum(QtyPicked by lot) in lotxlocxid '

select lot, QtyPicked = sum(QtyPicked) into #temp_sum
from lotxlocxid (nolock)
where QtyPicked > 0
group by lot

select a_lot = b.lot, b_lot = a.lot, sum_lot = b.QtyPicked ,  sum_lotxlocxid = a.QtyPicked  into #info
from #temp_sum a FULL OUTER JOIN lot b (nolock) ON a.lot = b.lot
where b.QtyPicked > 0
  and (a.QtyPicked <> b.QtyPicked or a.lot is null or b.lot is null)
go
if exists (select 1 from #info)
     select * from #info
drop table #info
drop table #temp_sum
go

select '<10> comparing sum( QtyPicked by storerkey, sku ) lotxlocxid and sum( QtyPicked by storerkey, sku ) skuxloc '

select storerkey, sku, QtyPicked = sum(QtyPicked) into #temp_sum
from lotxlocxid (nolock)
where QtyPicked > 0
group by storerkey, sku

select storerkey, sku, Qtypicked = sum(qtypicked) into #temp_sum1
from skuxloc (nolock)
where QtyPicked > 0
group by storerkey, sku

select a_storerkey = a.storerkey, a_sku = a.sku, b_storerkey = b.storerkey, b_sku = b.sku,
  sum_lotxlocxid = a.QtyPicked , sum_skuxloc = b.QtyPicked  into #info
from #temp_sum a FULL OUTER JOIN #temp_sum1 b ON a.storerkey = b.storerkey and a.sku = b.sku
where a.QtyPicked <> b.QtyPicked
   or a.storerkey is null or b.storerkey is null or a.sku is null or b.sku is null
go
if exists (select 1 from #info)
     select * from #info
drop table #info
drop table #temp_sum
drop table #temp_sum1
go

select '<11> comparing  sum(QtyExpected by storer,sku) of skuxloc and sum(QtyExpected by storer,sku) of lotxlocxid '

select storerkey, sku, QtyExpected = sum(QtyExpected) into #temp_sum
from skuxloc (nolock)
where QtyExpected > 0
group by storerkey, sku

select storerkey, sku, QtyExpected = sum(QtyExpected) into #temp_sum1
from lotxlocxid (nolock)
where QtyExpected > 0
group by storerkey, sku

select a_storerkey = a.storerkey, a_sku = a.sku, b_storerkey = b.storerkey, b_sku = b.sku,
  sum_skuxloc = a.QtyExpected , sum_lotxlocxid = b.QtyExpected into #info
from #temp_sum a FULL OUTER JOIN #temp_sum1 b ON a.storerkey = b.storerkey and a.sku = b.sku
where a.QtyExpected <> b.QtyExpected
   or a.storerkey is null or b.storerkey is null or a.sku is null or b.sku is null
go
if exists (select 1 from #info)
     select * from #info
drop table #info
drop table #temp_sum
drop table #temp_sum1
go

select '<12> comparing  sum(Qty by storer,sku) of pickdetail (status = 0..4) and sum(QtyAllocated by storer,sku) of lotxlocxid '

select storerkey, sku, QtyAllocated = sum(Qty), 'wms' "Type" into #temp_sum
from pickdetail (nolock)
where status in ('0', '1', '2', '3', '4') and qty > 0
group by storerkey, sku
--UNION
--select storerkey, sku, sum(qty), 'xdock'
--from xpickdetail (nolock)
--where status in ('0', '1', '2', '3', '4') and qty > 0
--group by storerkey, sku

select storerkey, sku, QtyAllocated = sum(QtyAllocated) into #temp_sum1
from lotxlocxid (nolock)
where QtyAllocated > 0
group by storerkey, sku

select a_storerkey = a.storerkey, a_sku = a.sku, b_storerkey = b.storerkey, b_sku = b.sku,
  sum_pickdetail = a.QtyAllocated, sum_lotxlocxid = b.QtyAllocated, a.type into #info
from #temp_sum a FULL OUTER JOIN #temp_sum1 b ON a.storerkey = b.storerkey and a.sku = b.sku
where a.QtyAllocated <> b.QtyAllocated
   or a.storerkey is null or b.storerkey is null or a.sku is null or b.sku is null
go
if exists (select 1 from #info)
     select * from #info
drop table #info
drop table #temp_sum
drop table #temp_sum1
go

select '<13> comparing  sum(Qty by storer,sku) of pickdetail (status = 0..4) and sum(QtyAllocated by storer,sku) of skuxloc '

select storerkey, sku, QtyAllocated = sum(Qty), 'wms' "Type" into #temp_sum
from pickdetail (nolock)
where status in ('0', '1', '2', '3', '4') and qty > 0
group by storerkey, sku
--UNION
--select storerkey, sku, QtyAllocated = sum(Qty), 'xdock'
--from xpickdetail (nolock)
--where status in ('0', '1', '2', '3', '4') and qty > 0
--group by storerkey, sku

select storerkey, sku, QtyAllocated = sum(QtyAllocated) into #temp_sum1
from skuxloc (nolock)
where QtyAllocated > 0
group by storerkey, sku

select a_storerkey = a.storerkey, a_sku = a.sku, b_storerkey = b.storerkey, b_sku = b.sku,
  sum_pickdetail = a.QtyAllocated, sum_skuxloc = b.QtyAllocated, type  into #info
from #temp_sum a FULL OUTER JOIN #temp_sum1 b ON a.storerkey = b.storerkey and a.sku = b.sku
where a.QtyAllocated <> b.QtyAllocated
   or a.storerkey is null or b.storerkey is null or a.sku is null or b.sku is null
go
if exists (select 1 from #info)
     select * from #info
drop table #info
drop table #temp_sum
drop table #temp_sum1
go

select '<14> comparing  sum(Qty by storer,sku) of pickdetail (status = 0..4) and sum(QtyAllocated by storer,sku) of lot '

select storerkey, sku, QtyAllocated = sum(Qty), 'wms' "Type" into #temp_sum
from pickdetail (nolock)
where status in ('0', '1', '2', '3', '4') and qty > 0
group by storerkey, sku
--UNION
--select storerkey, sku, QtyAllocated = sum(Qty), 'xdock'
--from xpickdetail (nolock)
--where status in ('0', '1', '2', '3', '4') and qty > 0
--group by storerkey, sku

select storerkey, sku, QtyAllocated = sum(QtyAllocated) into #temp_sum1
from lot (nolock)
where QtyAllocated > 0
group by storerkey, sku

select a_storerkey = a.storerkey, a_sku = a.sku, b_storerkey = b.storerkey, b_sku = b.sku,
  sum_pickdetial =  a.QtyAllocated ,sum_lot = b.QtyAllocated, a.type into #info
from #temp_sum a FULL OUTER JOIN #temp_sum1 b ON a.storerkey = b.storerkey and a.sku = b.sku
where a.QtyAllocated <> b.QtyAllocated
   or a.storerkey is null or b.storerkey is null or a.sku is null or b.sku is null
go
if exists (select 1 from #info)
     select * from #info
drop table #info
drop table #temp_sum
drop table #temp_sum1
go

select '<15> comparing  sum(Qty by storer,sku) of pickdetail (status = 5..8) and sum(QtyPicked by storer,sku) of lotxlocxid and sum(Qty by storer,sku) of lotxlocxid'

select storerkey, sku, QtyPicked = sum(Qty), 'wms' "Type"  into #temp_sum
from pickdetail (nolock)
where status in ('5', '6', '7', '8') and qty > 0
group by storerkey, sku
--UNION
--select storerkey, sku, QtyPicked = sum(Qty), 'xdock'
--from xpickdetail (nolock)
--where status in ('5', '6', '7', '8') and qty > 0
--group by storerkey, sku

select storerkey, sku, QtyPicked = sum(QtyPicked),qty = sum(qty)  into #temp_sum1
from lotxlocxid (nolock)
where QtyPicked > 0
group by storerkey, sku

select a_storerkey = a.storerkey, a_sku = a.sku, b_storerkey = b.storerkey, b_sku = b.sku,
  sum_pickdetail = sum(a.QtyPicked), sum_lotxlocxid_qtypicked = b.QtyPicked, sum_lotxlocxid_qty = b.qty  into #info
from #temp_sum a FULL OUTER JOIN #temp_sum1 b ON a.storerkey = b.storerkey and a.sku = b.sku
where a.QtyPicked <> b.QtyPicked or b.qty < a.qtypicked
   or a.storerkey is null or b.storerkey is null or a.sku is null or b.sku is null
group by a.storerkey, a.sku, b.storerkey, b.sku, b.qtypicked,b.qty
having sum(a.QtyPicked) is null or b.QtyPicked is null or sum(a.QtyPicked) <> b.QtyPicked or b.qty < sum(a.QtyPicked)
go
if exists (select 1 from #info)
     select * from #info
drop table #info
drop table #temp_sum
drop table #temp_sum1
go

select '<16> comparing  sum(Qty by storer,sku) of pickdetail (status = 5..8) and sum(QtyPicked by storer,sku) of skuxloc and sum(Qty by storer,sku) of skuxloc '

select storerkey, sku, QtyPicked = sum(Qty), 'wms' "Type" into #temp_sum
from pickdetail (nolock)
where status in ('5', '6', '7', '8') and qty > 0
group by storerkey, sku
--UNION
--select storerkey, sku, QtyPicked = sum(Qty), 'xdock'
--from xpickdetail (nolock)
--where status in ('5', '6', '7', '8') and qty > 0
--group by storerkey, sku

select storerkey, sku, QtyPicked = sum(QtyPicked),qty = sum(qty) into #temp_sum1
from skuxloc (nolock)
where QtyPicked > 0
group by storerkey, sku

select a_storerkey = a.storerkey, a_sku = a.sku, b_storerkey = b.storerkey, b_sku = b.sku,
  sum_pickdetail = sum(a.QtyPicked), sum_skuxloc_picked = b.QtyPicked, sum_skuxloc_qty = b.Qty  into #info
from #temp_sum a FULL OUTER JOIN #temp_sum1 b ON a.storerkey = b.storerkey and a.sku = b.sku
where a.QtyPicked <> b.QtyPicked or b.qty < a.qtypicked
   or a.storerkey is null or b.storerkey is null or a.sku is null or b.sku is null
group by a.storerkey, a.sku, b.storerkey, b.sku, b.qtypicked, b.qty
having sum(a.QtyPicked) is null or b.QtyPicked is null or sum(a.QtyPicked) <> b.QtyPicked or b.qty < sum(a.QtyPicked)
go
if exists (select 1 from #info)
     select * from #info
drop table #info
drop table #temp_sum
drop table #temp_sum1
go

select '<17> comparing  sum(Qty by storer,sku) of pickdetail (status = 5..8) and sum(QtyPicked by storer,sku) of lot'

select storerkey, sku, QtyPicked = sum(Qty), 'wms' "Type" into #temp_sum
from pickdetail (nolock)
where status in ('5', '6', '7', '8') and Qty > 0
group by storerkey, sku
--UNION
--select storerkey, sku, QtyPicked = sum(Qty), 'xdock'
--from xpickdetail (nolock)
--where status in ('5', '6', '7', '8') and Qty > 0
--group by storerkey, sku

select storerkey, sku, QtyPicked = sum(QtyPicked) into #temp_sum1
from lot (nolock)
where QtyPicked > 0
group by storerkey, sku

select a_storerkey = a.storerkey, a_sku = a.sku, b_storerkey = b.storerkey, b_sku = b.sku,
  sum_pickdetail = sum(a.QtyPicked), sum_lot_picked = b.QtyPicked   into #info
from #temp_sum a FULL OUTER JOIN #temp_sum1 b ON a.storerkey = b.storerkey and a.sku = b.sku
where a.QtyPicked <> b.QtyPicked
   or a.storerkey is null or b.storerkey is null or a.sku is null or b.sku is null
group by a.storerkey, a.sku, b.storerkey, b.sku, b.qtypicked
having sum(a.QtyPicked) is null or b.QtyPicked is null or sum(a.QtyPicked) <> b.QtyPicked
go
if exists (select 1 from #info)
     select * from #info
drop table #info
drop table #temp_sum
drop table #temp_sum1
go

select '<18 HA> comparing sum(qty by orderkey) in pickdetail (status = 0..4) with sum(qtyallocated by orderkey) in orderdetail'

select Orderkey, QtyAllocated = sum(Qty), 'wms' "Type" into #temp_sum
from pickdetail (nolock)
where status in ('0', '1', '2', '3', '4') and Qty > 0
group by orderkey

select Orderkey, QtyAllocated = sum(QtyAllocated), 'wms' "Type" into #temp_sum1
from orderdetail (nolock)
where QtyAllocated > 0
and allocatestrategytype <> '0'
group by orderkey

select a_orderkey = a.orderkey, b_orderkey = b.orderkey,
   sum_pickdetail_allocated = a.Qtyallocated , sum_orderdetail = b.Qtyallocated, Type=isnull(a.type,b.type) into #info
from #temp_sum a FULL OUTER JOIN #temp_sum1 b ON a.orderkey = b.orderkey
where a.Qtyallocated <> b.Qtyallocated
   or a.orderkey is null or b.orderkey is null
go
if exists (select 1 from #info)
     select * from #info
drop table #info
drop table #temp_sum
drop table #temp_sum1
go

select '<18 DA> comparing sum(qty by orderkey) in pickdetail (status = 0..4) with sum(qtyallocated by orderkey) in orderdetail'

select Orderkey, QtyAllocated = sum(QtyAllocated) into #temp_sum
from demandallocation (nolock)
group by orderkey

select Orderkey, QtyAllocated = sum(QtyAllocated) into #temp_sum1
from orderdetail (nolock)
where QtyAllocated > 0
and allocatestrategytype = '0'
group by orderkey

select a_orderkey = a.orderkey, b_orderkey = b.orderkey,
   sum_pickdetail_allocated = a.Qtyallocated , sum_orderdetail = b.Qtyallocated into #info
from #temp_sum a FULL OUTER JOIN #temp_sum1 b ON a.orderkey = b.orderkey
where a.Qtyallocated <> b.Qtyallocated
   or a.orderkey is null or b.orderkey is null
go
if exists (select 1 from #info)
     select * from #info
drop table #info
drop table #temp_sum
drop table #temp_sum1
go

select '<19> comparing sum(qty by orderkey) in pickdetail (status = 5..8) with sum(qtypicked by orderkey) in orderdetail'

select Orderkey, qtypicked = sum(Qty) into #temp_sum
from pickdetail (nolock)
where status in ('5', '6', '7', '8') and qty > 0
group by orderkey

select orderkey, qtypicked = sum(qtypicked) into #temp_sum1
from orderdetail (nolock)
where QtyPicked > 0
group by orderkey

select a_orderkey = a.orderkey,  b_orderkey = b.orderkey,
  sum_pickdetail_picked = a.qtypicked, sum_orderdetail = b.qtypicked  into #info
from #temp_sum a FULL OUTER JOIN #temp_sum1 b ON a.orderkey = b.orderkey
where a.qtypicked <> b.qtypicked
   or a.orderkey is null or b.orderkey is null
go
if exists (select 1 from #info)
     select * from #info
drop table #info
drop table #temp_sum
drop table #temp_sum1
go

select '<20> comparing sum(qty by orderkey) in pickdetail (status = 9) with sum(qtyshipped by orderkey) in orderdetail'

select Orderkey, QtyShipped = sum(Qty) into #temp_sum
from pickdetail (nolock)
where status ='9' and Qty > 0
group by orderkey

select  Orderkey, QtyShipped = sum(ShippedQty) into #temp_sum1
from orderdetail (nolock)
where ShippedQty > 0
group by orderkey

select a_orderkey = a.orderkey, b_orderkey = b.orderkey,
   sum_pickdetail_shipped = a.qtyShipped, sum_orderdetail = b.qtyShipped into #info
from #temp_sum a FULL OUTER JOIN #temp_sum1 b ON a.orderkey = b.orderkey
where a.QtyShipped <> b.QtyShipped
   or a.orderkey is null or b.orderkey is null
go
if exists (select 1 from #info)
     select * from #info
drop table #info
drop table #temp_sum
drop table #temp_sum1
go

select '<21> comparing sum(qtypreallocated by orderkey) in preallocatepickdetail with sum(qtypreallocated by orderkey) in orderdetail'

select Orderkey, qtypreallocated = sum(Qty) into #temp_sum
from preallocatepickdetail (nolock)
where Qty > 0
group by orderkey

select orderkey, qtypreallocated = sum(qtypreallocated) into #temp_sum1
from orderdetail (nolock)
where qtypreallocated > 0
group by orderkey

select a_orderkey = a.orderkey, b_orderkey = b.orderkey,
  sum_preallocatepickdetail = a.qtypreallocated, sum_orderdetail = b.qtypreallocated  into #info
from #temp_sum a FULL OUTER JOIN #temp_sum1 b ON a.orderkey = b.orderkey
where a.qtypreallocated <> b.qtypreallocated
   or a.orderkey is null or b.orderkey is null
go
if exists (select 1 from #info)
     select * from #info
drop table #info
drop table #temp_sum
drop table #temp_sum1
go

select '<22> comparing LOT and sum(qtypreallocated by Lot) in PreallocatePickdetail'

select lot, qtypreallocated = sum(Qty) into #temp_sum
from preallocatepickdetail (nolock)
where qty > 0
group by lot

select lot, qtypreallocated into #temp_sum1
from lot (nolock)
where qtypreallocated > 0

select PreallocatePickDetail_Lot = a.lot, LOT_Lot = b.lot,
  lot_qtypreallocated = b.qtypreallocated, sum_preallocatepickdetail = a.qtypreallocated into #info
from #temp_sum a FULL OUTER JOIN #temp_sum1 b ON a.lot = b.lot
where a.qtypreallocated <> b.qtypreallocated
 or a.lot is null or b.lot is null

if exists (select 1 from #info)
     select * from #info
drop table #info
drop table #temp_sum
drop table #temp_sum1
go

select '<23> comparing LOT.QtyOnHold and sum(Qty) in LotxLocxId that corresponds to Holds - <название> v01'

select l.lot l_lot, l.qtyonhold l_qtyonhold, lli.lot lli_lot, sum(CASE WHEN lli.status = 'HOLD' THEN lli.qty-lli.qtyallocated-lli.qtypicked ELSE 0 END) lli_qtyonhold --19122019 VO added -lli.qtyallocated
from lot l
full outer join lotxlocxid lli on l.lot = lli.lot
GROUP BY l.lot, lli.lot, l.qtyonhold
having isnull(l.qtyonhold,0) <> isnull( sum(CASE WHEN lli.status = 'HOLD' THEN lli.qty-lli.qtyallocated-lli.qtypicked ELSE 0 END) ,0)
order by l.lot

select '<24> checking on Status in LotxLocxId '

select Lot, Loc, Id, status 'WrongStatus', Qty, 'loc' 'Source' into #info from lotxlocxid a
where status = 'OK' and exists (select 1 from loc where loc = a.loc and (status = 'HOLD' or locationflag in ('HOLD','DAMAGE'))) and qty <> 0
UNION ALL
select lot,loc,id, status, qty, 'id' from lotxlocxid a
where status = 'OK' and exists (select 1 from id where id = a.id and status = 'HOLD') and qty <> 0
UNION ALL
select lot,loc,id, status, qty, 'lot' from lotxlocxid a
where status = 'OK' and exists (select 1 from lot where lot = a.lot and status = 'HOLD') and qty <> 0

if exists (select 1 from #info)
     select * from #info
drop table #info
go

--select '<25> comparing LOT.NetWgt and sum(Wgt by Lot) in LotxIdDetail'

--select a.Lot, sum(case when a.ioflag = 'I' then wgt when a.ioflag = 'O' then -wgt else 0 end) 'NetWgt'
--into #temp_sum
--from lotxidheader a, lotxiddetail b
--where a.lotxidkey = b.lotxidkey
--group by a.Lot

--select lot, NetWgt into #temp_sum1
--from lot (nolock)
--where NetWgt > 0

--select LOTxIDHeader_Lot = a.lot, LOT_Lot = b.lot,
--  lot_netwgt = b.NetWgt, sum_wgt = a.NetWgt into #info
--from #temp_sum a FULL OUTER JOIN #temp_sum1 b ON a.lot = b.lot
--where convert(dec(22,6), a.netwgt) <> convert(dec(22,6), b.netwgt)
-- or a.lot is null or b.lot is null
--go
--if exists (select 1 from #info)
--     select * from #info
--drop table #info
--drop table #temp_sum
--drop table #temp_sum1
--go

select '<26> Проверка упаковок по lotattribute.lottable01 и pack. Если записи найдены, надо сообщить стокам партию, для проверки упаковки.- <название> v01'

select lot, lottable01 from lotattribute where lottable01 <> '' and lottable01 not in (select packkey from pack)
-- OL, 20160211: íàäî âûâîäèòü òîëüêî ñòðîêè, êîòîðûå åñòü íà áàëàíñàõ
and LOT in (select LOT from LOT where qty > 0)
go

--select '<27> Проверка корректности проставления DROPID - <название> v02'
--select        distinct DROPID, status, 'notInDropId' as type
--from        PICKDETAIL pd
--where        not exists (SELECT 1 from DROPID where pd.DROPID = DROPID.DROPID)
--            and DROPID != ''
--union all
--select        distinct DROPID, status, 'notInTransmitLog'
--from        PICKDETAIL pd
--where
--            not exists (SELECT 1 from TRANSMITLOG t where pd.DROPID = t.KEY1 and TABLENAME = 'DROPSHIPPED')
--            and DROPID != ''
--            and STATUS = '9'
--            and EDITDATE >= (select min(editdate) from transmitlog)
--            and pickdetailkey >=
--            (SELECT        top 1 pickdetailkey
--            from        PICKDETAIL
--            where        dropid =
--                        (SELECT top 1 key1 from TRANSMITLOG where TABLENAME = 'DROPSHIPPED' order by 1)
--            )
--go

select '<28> comparing lotxlocxid and sum(Qty by lot, loc, id) in serialinventory'

IF (select NSQLVALUE from NSQLCONFIG where CONFIGKEY = 'ALLOWCATCHWEIGHTDATA') = '1'
BEGIN
    select lli.storerkey as [STORERKEY], lli.lot, loc, id, lli.sku as [SKU], qty into #temp_lli
    from lotxlocxid lli (nolock)
    inner join (
        select storerkey, sku from sku (nolock)
        where SNUM_ENDTOEND = '1'
        ) s on lli.storerkey = s.storerkey and lli.sku = s.sku
    inner join (
        select distinct lot from serialinventory (nolock)
        ) si on lli.lot = si.lot
    and qty > 0

    select storerkey, lot, loc, id, sum(qty) as qty into #temp_si
    from serialinventory (nolock)
    group by storerkey, lot, loc, id

    select lli.storerkey as [STORERKEY], lli.sku as [SKU], lli.lot as [LOT], lli.loc as [LOC], lli.id as [ID], lli.qty as [LLI_QTY], si.qty as [SERIAL_QTY], si.lot as [SERIAL_LOT] into #info
    from #temp_lli lli
    full outer join #temp_si si
    on lli.storerkey = si.storerkey and lli.lot = si.lot and lli.loc = si.loc and lli.id = si.id
    where ISNULL(lli.qty, 0) <> ISNULL(si.qty, 0)

    if exists (select 1 from #info)
         select * from #info
    drop table #info
    drop table #temp_lli
    drop table #temp_si
END
ELSE
    select 'ALLOWCATCHWEIGHTDATA disabled'

select '<29> WAVEINPROCESS, delete if exists'

SELECT * FROM WAVEINPROCESS WHERE ADDDATE < DATEADD(MINUTE, -5, GETUTCDATE())

select '<30> ORDERINPROCESS, delete if exists'

SELECT * FROM ORDERINPROCESS WHERE ADDDATE < DATEADD(MINUTE, -5, GETUTCDATE())

select '<31> VoiceUserPrintTask, delete if exists'

SELECT * FROM VoiceUserPrintTask WHERE ADDDATE < DATEADD(MINUTE, -5, GETUTCDATE())

/* Clean it up just in case */
IF EXISTS(select id from tempdb..sysobjects where name like '#temp_sum%' and SUBSTRING(name, 10, 1) <> '1')
     drop table #temp_sum

IF EXISTS(select id from tempdb..sysobjects where name like '#temp_sum%' and SUBSTRING(name, 10, 1) = '1')
     drop table #temp_sum1
go

print ' '
print '************************************************************************'
print ' '
select  'Server' = convert(char(20), @@servername),
    'Database'= convert(char(20), db_name()),
    'Completed at ' = getdate()
print '************************************************************************'
print '************************************************************************'
set nocount off
go`;
    /* eslint-enable */

    async function copyHSOtherScript() {
        try {
            await navigator.clipboard.writeText(HS_OTHER_SCRIPT);
            showToast('Скрипт HS Остальные скопирован ✓');
        } catch (err) {
            console.error('<название> copyHSOtherScript:', err);
            showToast('Ошибка копирования', 'error');
        }
    }

    // =========================================================================
    // HS - «Скрипт Расхождений БД»: копирование хардкодного SQL в буфер
    // =========================================================================

    /* eslint-disable */
    const DB_DISCREPANCY_SCRIPT = `--2.1 CHECK LLI
select lli.storerkey, lli.sku, lli.lot, lli.loc, lli.id, lli.qty as [lli_qty], isnull(lli.qtyallocated, 0) as [lli_qtyallocated], isnull(lli.qtypicked, 0) as [lli_qtypicked], isnull(pda.qty, 0) as [pd_qtyallocated], isnull(pdp.qty, 0) as [pd_qtypicked]
--, pda.storerkey, pda.sku, pda.lot, pda.loc, pda.id, pdp.storerkey, pdp.sku, pdp.lot, pdp.loc, pdp.id
from lotxlocxid lli
full outer join (select storerkey, sku, lot, loc, id, sum(qty) as qty from pickdetail pd where status between '0' and '4' group by storerkey, sku, lot, loc, id) pda
on lli.storerkey = pda.storerkey and lli.lot = pda.lot and lli.loc = pda.loc and lli.id = pda.id
full outer join (select storerkey, sku, lot, loc, id, sum(qty) as qty from pickdetail pd where status between '5' and '8' group by storerkey, sku, lot, loc, id) pdp
on lli.storerkey = pdp.storerkey and lli.lot = pdp.lot and lli.loc = pdp.loc and lli.id = pdp.id
where isnull(lli.qtyallocated, 0) <> isnull(pda.qty, 0)
OR isnull(lli.qtypicked, 0) <> isnull(pdp.qty, 0)

--2.2 NO LLI PRESENT
INSERT INTO [wmwhse1].[LOTXLOCXID]([LOT],[LOC],[ID],[STORERKEY],[SKU],[QTY],[QTYPICKED]) VALUES ('lot','loc','id','storerkey','sku', qty, qtypicked)

--2.3 UPDATE LLI
select lli.storerkey, lli.sku, lli.lot, lli.loc, lli.id, isnull(lli.qtyallocated, 0) as [lli_qtyallocated], isnull(lli.qtypicked, 0) as [lli_qtypicked], isnull(pda.qty, 0) as [pd_qtyallocated], isnull(pdp.qty, 0) as [pd_qtypicked]
into #tmp_1 from lotxlocxid lli
-- Через полминуты записать еще один результат в #tmp_2
full outer join (select storerkey, lot, loc, id, sum(qty) as qty from pickdetail pd where status between '0' and '4' group by storerkey, lot, loc, id) pda
on lli.storerkey = pda.storerkey and lli.lot = pda.lot and lli.loc = pda.loc and lli.id = pda.id
full outer join (select storerkey, lot, loc, id, sum(qty) as qty from pickdetail pd where status between '5' and '8' group by storerkey, lot, loc, id) pdp
on lli.storerkey = pdp.storerkey and lli.lot = pdp.lot and lli.loc = pdp.loc and lli.id = pdp.id
where isnull(lli.qtyallocated, 0) <> isnull(pda.qty, 0)
OR isnull(lli.qtypicked, 0) <> isnull(pdp.qty, 0)

select lli.storerkey, lli.sku, lli.lot, lli.loc, lli.id, isnull(lli.qtyallocated, 0) as [lli_qtyallocated], isnull(lli.qtypicked, 0) as [lli_qtypicked], isnull(pda.qty, 0) as [pd_qtyallocated], isnull(pdp.qty, 0) as [pd_qtypicked]
into #tmp_2 from lotxlocxid lli
-- Через полминуты записать еще один результат в #tmp_2
full outer join (select storerkey, lot, loc, id, sum(qty) as qty from pickdetail pd where status between '0' and '4' group by storerkey, lot, loc, id) pda
on lli.storerkey = pda.storerkey and lli.lot = pda.lot and lli.loc = pda.loc and lli.id = pda.id
full outer join (select storerkey, lot, loc, id, sum(qty) as qty from pickdetail pd where status between '5' and '8' group by storerkey, lot, loc, id) pdp
on lli.storerkey = pdp.storerkey and lli.lot = pdp.lot and lli.loc = pdp.loc and lli.id = pdp.id
where isnull(lli.qtyallocated, 0) <> isnull(pda.qty, 0)
OR isnull(lli.qtypicked, 0) <> isnull(pdp.qty, 0)

-- Сбор совпадающих строк из двух таблиц в одну
select a.* into #tmp
from #tmp_1 a
inner join #tmp_2 b
on a.storerkey = b.storerkey and a.lot = b.lot and a.loc = b.loc and a.id = b.id
and a.lli_qtyallocated = b.lli_qtyallocated and a.pd_qtyallocated = b.pd_qtyallocated
and a.lli_qtypicked = b.lli_qtypicked and a.pd_qtypicked = b.pd_qtypicked

select * from #tmp

-- Сохраняем информацию об апдейте во временную таблицу
select lli.qtyallocated as [old_qtyallocated], lli.qtypicked as [old_qtypicked],
tmp.pd_qtyallocated, tmp.pd_qtypicked,
lli.qtyallocated - (tmp.lli_qtyallocated - tmp.pd_qtyallocated) as [new qtyallocated],
lli.qtypicked - (tmp.lli_qtypicked - tmp.pd_qtypicked) as [new qtypicked],
'LOTXLOCXID before update --->' as [ ], lli.* into tmp_rm_НОМЕР_ЗАДАЧИ_lli
from lotxlocxid lli
inner join #tmp tmp on lli.storerkey = tmp.storerkey and lli.lot = tmp.lot and lli.loc = tmp.loc and lli.id = tmp.id

-- Проверяем
select * from tmp_rm_НОМЕР_ЗАДАЧИ_lli

-- Апдейт QTYALLOCATED и QTYPICKED
--update lli set lli.qtyallocated = lli.qtyallocated - (tmp.lli_qtyallocated - tmp.pd_qtyallocated), lli.qtypicked = lli.qtypicked - (tmp.lli_qtypicked - tmp.pd_qtypicked), EDITDATE = GETUTCDATE(), EDITWHO = '<Имя>'
from lotxlocxid lli
inner join #tmp tmp on lli.storerkey = tmp.storerkey and lli.lot = tmp.lot and lli.loc = tmp.loc and lli.id = tmp.id

-- Удаление временных таблиц
drop table #tmp_1
drop table #tmp_2
drop table #tmp

-- 3.1 CHECK SKUXLOC
select sl.storerkey, sl.sku, sl.loc, isnull(sl.qty, 0) as [sl_qty], isnull(sl.qtyallocated, 0) as [sl_qtyallocated], isnull(sl.qtypicked, 0) as [sl_qtypicked],
lli.storerkey as lli_storerkey, lli.sku as lli_sku, lli.loc as lli_loc, isnull(lli.qty, 0) as [lli_qty], isnull(lli.qtyallocated, 0) as [lli_qtyallocated], isnull(lli.qtypicked, 0) as [lli_qtypicked]
from skuxloc sl
full outer join (select storerkey, sku, loc, sum(qty) qty, sum(qtyallocated) qtyallocated, sum(qtypicked) qtypicked from lotxlocxid group by storerkey, sku, loc) lli
on sl.storerkey = lli.storerkey and sl.sku = lli.sku and sl.loc = lli.loc
where isNull(sl.qty, 0) <> isNull(lli.qty, 0)
OR isNull(sl.qtyallocated, 0) <> isNull(lli.qtyallocated, 0)
OR isNull(sl.qtypicked, 0) <> isNull(lli.qtypicked, 0)

-- 3.2 NO SKUXLOC PRESENT
INSERT INTO [wmwhse1].[SKUXLOC] ([STORERKEY],[SKU],[LOC],[QTY],[QTYPICKED]) VALUES ('storerkey', 'sku', 'loc', qty, qtypicked)

--3.3 UPDATE SKUXLOC

select sl.storerkey, sl.sku, sl.loc, isnull(sl.qty, 0) as [sl_qty], isnull(sl.qtyallocated, 0) as [sl_qtyallocated], isnull(sl.qtypicked, 0) as [sl_qtypicked],
lli.storerkey as lli_storerkey, lli.sku as lli_sku, lli.loc as lli_loc, isnull(lli.qty, 0) as [lli_qty], isnull(lli.qtyallocated, 0) as [lli_qtyallocated], isnull(lli.qtypicked, 0) as [lli_qtypicked]
into #tmp_1 from skuxloc sl
-- через полминуты записать еще один результат в #tmp_2
full outer join (select storerkey, sku, loc, sum(qty) qty, sum(qtyallocated) qtyallocated, sum(qtypicked) qtypicked from lotxlocxid group by storerkey, sku, loc) lli
on sl.storerkey = lli.storerkey and sl.sku = lli.sku and sl.loc = lli.loc
where isNull(sl.qty, 0) <> isNull(lli.qty, 0)
OR isNull(sl.qtyallocated, 0) <> isNull(lli.qtyallocated, 0)
OR isNull(sl.qtypicked, 0) <> isNull(lli.qtypicked, 0)

select sl.storerkey, sl.sku, sl.loc, isnull(sl.qty, 0) as [sl_qty], isnull(sl.qtyallocated, 0) as [sl_qtyallocated], isnull(sl.qtypicked, 0) as [sl_qtypicked],
lli.storerkey as lli_storerkey, lli.sku as lli_sku, lli.loc as lli_loc, isnull(lli.qty, 0) as [lli_qty], isnull(lli.qtyallocated, 0) as [lli_qtyallocated], isnull(lli.qtypicked, 0) as [lli_qtypicked]
into #tmp_2 from skuxloc sl
-- через полминуты записать еще один результат в #tmp_2
full outer join (select storerkey, sku, loc, sum(qty) qty, sum(qtyallocated) qtyallocated, sum(qtypicked) qtypicked from lotxlocxid group by storerkey, sku, loc) lli
on sl.storerkey = lli.storerkey and sl.sku = lli.sku and sl.loc = lli.loc
where isNull(sl.qty, 0) <> isNull(lli.qty, 0)
OR isNull(sl.qtyallocated, 0) <> isNull(lli.qtyallocated, 0)
OR isNull(sl.qtypicked, 0) <> isNull(lli.qtypicked, 0)

-- Сбор совпадающих строк из двух таблиц в одну
select a.* into #tmp
from #tmp_1 a inner join #tmp_2 b
on a.storerkey = b.storerkey and a.sku = b.sku and a.loc = b.loc
and a.sl_qty = b.sl_qty and a.sl_qtyallocated = b.sl_qtyallocated and a.sl_qtypicked = b.sl_qtypicked
and a.lli_qty = b.lli_qty and a.lli_qtyallocated = b.lli_qtyallocated and a.lli_qtypicked = b.lli_qtypicked

select * from #tmp

-- Сохраняем информацию об апдейте во временную таблицу
select sl.qty as [old_qty], sl.qtyallocated as [old_qtyallocated], sl.qtypicked as [old_qtypicked],
sl.qty - (tmp.sl_qty - tmp.lli_qty) as [new_qty], sl.qtyallocated - (tmp.sl_qtyallocated - tmp.lli_qtyallocated) as [new_qtyallocated], sl.qtypicked - (tmp.sl_qtypicked - tmp.lli_qtypicked) as [new_qtypicked],
'SKUXLOC before update --->' as [ ], sl.* into tmp_rm_НОМЕР_ЗАДАЧИ_sl
from skuxloc sl
inner join #tmp tmp on sl.storerkey = tmp.storerkey and sl.sku = tmp.sku and sl.loc = tmp.loc

-- Проверяем
select * from tmp_rm_НОМЕР_ЗАДАЧИ_sl

-- Апдейт QTY, QTYALLOCATED, QTYPICKED
--update sl set sl.qty = sl.qty - (tmp.sl_qty - tmp.lli_qty), sl.qtyallocated = sl.qtyallocated - (tmp.sl_qtyallocated - tmp.lli_qtyallocated), sl.qtypicked = sl.qtypicked - (tmp.sl_qtypicked - tmp.lli_qtypicked), EDITDATE = GETUTCDATE(), EDITWHO = '<Имя>'
from skuxloc sl
inner join #tmp tmp on sl.storerkey = tmp.storerkey and sl.sku = tmp.sku and sl.loc = tmp.loc

-- Удаление временных таблиц
drop table #tmp_1
drop table #tmp_2
drop table #tmp

--4.1 CHECK LOT

select l.storerkey, l.lot, isnull(l.qty, 0) as [l_qty], isnull(l.qtyallocated, 0) as [l_qtyallocated], isnull(l.qtypicked, 0) as [l_qtypicked],
lli.storerkey as lli_storerkey, lli.lot as lli_lot, isnull(lli.qty, 0) as [lli_qty], isnull(lli.qtyallocated, 0) as [lli_qtyallocated], isnull(lli.qtypicked, 0) as [lli_qtypicked]
into #tmp_1 from lot l
-- Через полминуты записать еще один результат в #tmp_2
full outer join (select storerkey, lot, sum(qty) qty, sum(qtyallocated) qtyallocated, sum(qtypicked) qtypicked from lotxlocxid group by storerkey, lot) lli
on l.storerkey = lli.storerkey and l.lot = lli.lot
where isNull(l.qty, 0) <> isNull(lli.qty, 0)
OR isNull(l.qtyallocated, 0) <> isNull(lli.qtyallocated, 0)
OR isNull(l.qtypicked, 0) <> isNull(lli.qtypicked, 0)

select l.storerkey, l.lot, isnull(l.qty, 0) as [l_qty], isnull(l.qtyallocated, 0) as [l_qtyallocated], isnull(l.qtypicked, 0) as [l_qtypicked],
lli.storerkey as lli_storerkey, lli.lot as lli_lot, isnull(lli.qty, 0) as [lli_qty], isnull(lli.qtyallocated, 0) as [lli_qtyallocated], isnull(lli.qtypicked, 0) as [lli_qtypicked]
into #tmp_2 from lot l
-- Через полминуты записать еще один результат в #tmp_2
full outer join (select storerkey, lot, sum(qty) qty, sum(qtyallocated) qtyallocated, sum(qtypicked) qtypicked from lotxlocxid group by storerkey, lot) lli
on l.storerkey = lli.storerkey and l.lot = lli.lot
where isNull(l.qty, 0) <> isNull(lli.qty, 0)
OR isNull(l.qtyallocated, 0) <> isNull(lli.qtyallocated, 0)
OR isNull(l.qtypicked, 0) <> isNull(lli.qtypicked, 0)
-- Сбор совпадающих строк из двух таблиц в одну
select a.* into #tmp
from #tmp_1 a inner join #tmp_2 b
on a.storerkey = b.storerkey and a.lot = b.lot
and a.l_qty = b.l_qty and a.l_qtyallocated = b.l_qtyallocated and a.l_qtypicked = b.l_qtypicked
and a.lli_qty = b.lli_qty and a.lli_qtyallocated = b.lli_qtyallocated and a.lli_qtypicked = b.lli_qtypicked

select * from #tmp

-- 4.3 UDPDATE LOT

-- Сохраняем информацию об апдейте во временную таблицу
select l.qty as [old_qty], l.qtyallocated as [old_qtyallocated], l.qtypicked as [old_qtypicked],
l.qty - (tmp.l_qty - tmp.lli_qty) as [new_qty], l.qtyallocated - (tmp.l_qtyallocated - tmp.lli_qtyallocated) as [new_qtyallocated], l.qtypicked - (tmp.l_qtypicked - tmp.lli_qtypicked) as [new_qtypicked],
'LOT before update --->' as [ ], l.* into tmp_rm_НОМЕР_ЗАДАЧИ_lot --указать СВОЙ НОМЕР ЗАДАЧИ и добавить краткое название обновляемой таблицы
from lot l
inner join #tmp tmp on l.storerkey = tmp.storerkey and l.lot = tmp.lot

-- Проверяем
select * from tmp_rm_НОМЕР_ЗАДАЧИ_lot -
-- Апдейт QTY, QTYALLOCATED, QTYPICKED
--update l set l.qty = l.qty - (tmp.l_qty - tmp.lli_qty), l.qtyallocated = l.qtyallocated - (tmp.l_qtyallocated - tmp.lli_qtyallocated), l.qtypicked = l.qtypicked - (tmp.l_qtypicked - tmp.lli_qtypicked), EDITDATE = GETUTCDATE(), EDITWHO = '<Имя>'
from lot l
inner join #tmp tmp on l.storerkey = tmp.storerkey and l.lot = tmp.lot

-- Удаление временных таблиц
drop table #tmp_1
drop table #tmp_2
drop table #tmp`;
    /* eslint-enable */

    async function copyDBDiscrepancyScript() {
        try {
            const n = getCurrentIssueId() || 'НОМЕР_ЗАДАЧИ';
            const sql = DB_DISCREPANCY_SCRIPT.replace(/НОМЕР_ЗАДАЧИ/g, n);
            await navigator.clipboard.writeText(sql);
            showToast('\u0421\u043a\u0440\u0438\u043f\u0442 \u0440\u0430\u0441\u0445\u043e\u0436\u0434\u0435\u043d\u0438\u0439 \u0411\u0414 \u0441\u043a\u043e\u043f\u0438\u0440\u043e\u0432\u0430\u043d \u2713');
        } catch (err) {
            console.error('<название> copyDBDiscrepancyScript:', err);
            showToast('\u041e\u0448\u0438\u0431\u043a\u0430 \u043a\u043e\u043f\u0438\u0440\u043e\u0432\u0430\u043d\u0438\u044f', 'error');
        }
    }

    // =========================================================================
    // HS - «DEPO»: удаление застрявших pickdetail status 3 + расхождения БД
    // =========================================================================

    /* eslint-disable */
    const DEPO_SCRIPT_TEMPLATE =
`select pickdetailkey,pd.orderkey from ORDERDETAIL od INNER JOIN
PICKDETAIL pd ON od.orderlinenumber = pd.ORDERLINENUMBER AND
pd.ORDERKEY = od.ORDERKEY
where pd.status = '3' and (od.status = '95' or od.status = '55')

select * into tmp_rmНОМЕР from PICKDETAIL where PICKDETAILKEY in (
    select pickdetailkey from ORDERDETAIL od INNER JOIN
    PICKDETAIL pd ON od.orderlinenumber = pd.ORDERLINENUMBER AND
    pd.ORDERKEY = od.ORDERKEY
    where pd.status = '3' and (od.status = '95' or od.status = '55')
)

select *
--delete
from PICKDETAIL where PICKDETAILKEY in (
    select pickdetailkey from tmp_rmНОМЕР
)`;
    /* eslint-enable */

    async function copyDepoScript() {
        try {
            const n = getCurrentIssueId() || 'НОМЕР';
            const depoSql = DEPO_SCRIPT_TEMPLATE.replace(/НОМЕР/g, n);
            await navigator.clipboard.writeText(depoSql);
            showToast('DEPO скрипт скопирован ✓');
        } catch (err) {
            console.error('<название> copyDepoScript:', err);
            showToast('\u041e\u0448\u0438\u0431\u043a\u0430 \u043a\u043e\u043f\u0438\u0440\u043e\u0432\u0430\u043d\u0438\u044f', 'error');
        }
    }

    // =========================================================================
    // DBA - «Апдейт статистики»: копирование хардкодного SQL в буфер
    // =========================================================================

    /* eslint-disable */
    const UPDATE_STATISTICS_SCRIPT =
`msdb.dbo.sp_whoisactive
dbo.sp_whoisactive
sp_whoisactive

UPDATE STATISTICS wmwhse1.LOTXLOCXID WITH FULLSCAN;
UPDATE STATISTICS wmwhse1.SKUXLOC    WITH FULLSCAN;
UPDATE STATISTICS wmwhse1.ORDERS     WITH FULLSCAN;
UPDATE STATISTICS wmwhse1.LOTATTRIBUTE WITH FULLSCAN;
UPDATE STATISTICS wmwhse1.PACK WITH FULLSCAN;
UPDATE STATISTICS wmwhse1.LOT  WITH FULLSCAN;
UPDATE STATISTICS wmwhse1.loc WITH FULLSCAN;
UPDATE STATISTICS wmwhse1.areadetail WITH FULLSCAN;
UPDATE STATISTICS wmwhse1.putawayzone WITH FULLSCAN;
UPDATE STATISTICS wmwhse1.taskmanageruserdetail WITH FULLSCAN;
-- \u0412\u044b\u043f\u043e\u043b\u043d\u0438\u043b\u0441\u044f \u0437\u0430

UPDATE STATISTICS wmwhse1.GISMT WITH FULLSCAN;
UPDATE STATISTICS wmwhse1.LOTXIDDETAIL WITH FULLSCAN;
-- \u0412\u044b\u043f\u043e\u043b\u043d\u0438\u043b\u0441\u044f \u0437\u0430

UPDATE STATISTICS wmwhse1.ORDERDETAIL     WITH FULLSCAN; -- \u0412\u044b\u043f\u043e\u043b\u043d\u0438\u043b\u0441\u044f \u0437\u0430
UPDATE STATISTICS wmwhse1.PICKDETAIL     WITH FULLSCAN; -- \u0412\u044b\u043f\u043e\u043b\u043d\u0438\u043b\u0441\u044f \u0437\u0430
UPDATE STATISTICS wmwhse1.TASKDETAIL     WITH FULLSCAN; -- \u0412\u044b\u043f\u043e\u043b\u043d\u0438\u043b\u0441\u044f \u0437\u0430`;
    /* eslint-enable */

    async function copyUpdateStatisticsScript() {
        try {
            await navigator.clipboard.writeText(UPDATE_STATISTICS_SCRIPT);
            showToast('\u0421\u043a\u0440\u0438\u043f\u0442 \u0430\u043f\u0434\u0435\u0442\u0430 \u0441\u0442\u0430\u0442\u0438\u0441\u0442\u0438\u043a\u0438 \u0441\u043a\u043e\u043f\u0438\u0440\u043e\u0432\u0430\u043d \u2713');
        } catch (err) {
            console.error('<название> copyUpdateStatisticsScript:', err);
            showToast('\u041e\u0448\u0438\u0431\u043a\u0430 \u043a\u043e\u043f\u0438\u0440\u043e\u0432\u0430\u043d\u0438\u044f', 'error');
        }
    }

    // =========================================================================
    // DBA - «Запрос для LOCK»: копирование хардкодного SQL в буфер
    // =========================================================================

    /* eslint-disable */
    const LOCK_QUERY_SCRIPT =
`-- \u041f\u0430\u0440\u0430\u043c\u0435\u0442\u0440, \u043a\u043e\u0442\u043e\u0440\u044b\u0439 \u043f\u0440\u0438\u0445\u043e\u0434\u0438\u0442 \u0438\u0437 \u0437\u0430\u044f\u0432\u043a\u0438 \u0441\u044e\u0434\u0430
DECLARE @wait_duration_ms INT = 1;


SELECT
    CONCAT('| **', ColumnName, '** | ', ISNULL(Value, 'NULL'), ' |') AS MarkdownFormattedRow
FROM
    (
        -- \u0417\u0434\u0435\u0441\u044c \u0432\u044b\u0442\u0430\u0441\u043a\u0438\u0432\u0430\u0435\u043c \u043d\u0443\u0436\u043d\u044b\u0435 \u043a\u043e\u043b\u043e\u043d\u043a\u0438, \u0437\u0430\u043c\u0435\u043d\u044f\u044f NULL \u043d\u0430 'NULL', \u0447\u0442\u043e\u0431\u044b \u043d\u0435 \u043e\u0441\u0442\u0430\u0432\u043b\u044f\u0442\u044c \u043f\u0443\u0441\u0442\u044b\u0435 \u044f\u0447\u0435\u0439\u043a\u0438
        SELECT
            CAST(text_blocked AS VARCHAR(MAX)) AS text_blocked,
            CAST(text_blocking AS VARCHAR(MAX)) AS text_blocking,
            CAST(ISNULL(resource_type, 'NULL') AS VARCHAR(MAX)) AS resource_type,
            CAST(ISNULL(object_name, 'NULL') AS VARCHAR(MAX)) AS object_name
        FROM
            scprd.dbo.t_admLockBlock
        WHERE
            wait_duration_ms = @wait_duration_ms
    ) AS SourceTable
UNPIVOT
    (Value FOR ColumnName IN
        (text_blocked, text_blocking, resource_type, object_name)  -- \u041f\u0440\u0435\u043e\u0431\u0440\u0430\u0437\u0443\u0435\u043c \u0434\u0430\u043d\u043d\u044b\u0435 \u0432 \u043d\u0443\u0436\u043d\u044b\u0439 \u0444\u043e\u0440\u043c\u0430\u0442
    ) AS UnpivotedResult
ORDER BY
    ColumnName;`;
    /* eslint-enable */

    async function copyLockQueryScript() {
        try {
            await navigator.clipboard.writeText(LOCK_QUERY_SCRIPT);
            showToast('\u0417\u0430\u043f\u0440\u043e\u0441 LOCK \u0441\u043a\u043e\u043f\u0438\u0440\u043e\u0432\u0430\u043d \u2713');
        } catch (err) {
            console.error('<название> copyLockQueryScript:', err);
            showToast('\u041e\u0448\u0438\u0431\u043a\u0430 \u043a\u043e\u043f\u0438\u0440\u043e\u0432\u0430\u043d\u0438\u044f', 'error');
        }
    }

    // =========================================================================
    // «Ввести трудозатраты»
    // =========================================================================

    /**
     * Открывает модальное окно с полем ввода минут, конвертирует в H:MM
     * и программно заполняет поле time_entry_hours в форме Redmine.
     */
    async function logTimeSpent() {
        // 1. Показать модалку
        const modal = new <название>Modal({
            title:       '\u23F1\uFE0F \u0412\u0432\u0435\u0441\u0442\u0438 \u0442\u0440\u0443\u0434\u043e\u0437\u0430\u0442\u0440\u0430\u0442\u044b',
            dark:        isDarkMode(),
            confirmText: '\u0414\u043e\u0431\u0430\u0432\u0438\u0442\u044c',
        });
        modal.addInput({
            id:          'minutes',
            label:       '\u0412\u0440\u0435\u043c\u044f (\u0432 \u043c\u0438\u043d\u0443\u0442\u0430\u0445)',
            placeholder: '\u043d\u0430\u043f\u0440\u0438\u043c\u0435\u0440, 70',
            type:        'number',
            hint:        '70 \u043c\u0438\u043d \u2192 1:10,  \u00a090 \u043c\u0438\u043d \u2192 1:30,  \u00a0125 \u043c\u0438\u043d \u2192 2:05',
            presets:     [5, 10, 15, 30],
        });

        const result = await modal.show();
        if (!result) return; // отмена

        const mins = parseInt(result.minutes, 10);
        if (!mins || mins <= 0 || isNaN(mins)) {
            showToast('\u0412\u0432\u0435\u0434\u0438\u0442\u0435 \u043a\u043e\u0440\u0440\u0435\u043a\u0442\u043d\u043e\u0435 \u043a\u043e\u043b\u0438\u0447\u0435\u0441\u0442\u0432\u043e \u043c\u0438\u043d\u0443\u0442', 'error');
            return;
        }

        const formatted = minutesToHours(mins);

        // 2. Открыть форму редактирования
        const editLink = document.querySelector('a.icon.icon-edit');
        if (!editLink) {
            showToast('\u041a\u043d\u043e\u043f\u043a\u0430 "\u0420\u0435\u0434\u0430\u043a\u0442\u0438\u0440\u043e\u0432\u0430\u0442\u044c" \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d\u0430', 'error');
            return;
        }
        editLink.click();

        // 3. Дождаться поля трудозатрат
        const timeInput = await waitForElement('#time_entry_hours', 4000);
        if (!timeInput) {
            showToast('\u0424\u043e\u0440\u043c\u0430 \u043d\u0435 \u043e\u0442\u043a\u0440\u044b\u043b\u0430\u0441\u044c (timeout)', 'error');
            return;
        }

        // 4. Скрыть блок редактирования
        const updateBlock = document.querySelector('#update');
        if (updateBlock) updateBlock.style.display = 'none';

        await delay(150);

        // 5. Записать время в инпут Redmine
        timeInput.value = formatted;
        timeInput.dispatchEvent(new Event('input',  { bubbles: true }));
        timeInput.dispatchEvent(new Event('change', { bubbles: true }));

        // 6. Нажать «Принять»
        await delay(200);
        const submitBtn = document.querySelector('form#issue-form input[type="submit"][name="commit"]');
        if (!submitBtn) {
            if (updateBlock) updateBlock.style.display = '';
            showToast('\u041a\u043d\u043e\u043f\u043a\u0430 "\u041f\u0440\u0438\u043d\u044f\u0442\u044c" \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d\u0430', 'error');
            return;
        }
        submitBtn.click();
    }

    // =========================================================================
    // «Поменять ГБ»
    // =========================================================================

    /**
     * Ищет вхождения вида «GB xxx» / «ГБ xxx» в тексте и пытается определить
     * по контексту, какой корректный, а какой - нет.
     * @param {string} text
     * @returns {{ correctGB: string, incorrectGB: string }}
     */
    function parseGBNumbers(text) {
        const gbRegex = /(?:GB|\u0413\u0411)\s*([a-zA-Z0-9]+)/gi;
        const matches = [];
        let match;

        while ((match = gbRegex.exec(text)) !== null) {
            matches.push({ full: match[0], value: 'GB' + match[1].toUpperCase(), index: match.index });
        }

        if (matches.length === 0) return { correctGB: '', incorrectGB: '' };
        if (matches.length === 1) return { correctGB: '', incorrectGB: matches[0].value };

        let correctGBs   = [];
        let incorrectGBs = [];

        for (let i = 0; i < matches.length; i++) {
            const cur       = matches[i];
            const prevEnd   = i > 0 ? matches[i - 1].index + matches[i - 1].full.length : 0;
            const winStart  = Math.max(prevEnd, cur.index - 50);
            const prefix    = text.substring(winStart, cur.index).toLowerCase();

            const badRegex  = /\u043d\u0435\u043a\u043e\u0440\u0440|\u043d\u0435 \u043a\u043e\u0440\u0440|\u043d\u0435\u0432\u0435\u0440|\u043d\u0435 \u0432\u0435\u0440|\u043e\u0448\u0438\u0431|\u043d\u0435\u043f\u0440\u0430\u0432\u0438\u043b|\u043d\u0435 \u043f\u0440\u0430\u0432\u0438\u043b|\u0432\u043c\u0435\u0441\u0442\u043e/i;
            const isBad     = badRegex.test(prefix);

            const cleanPfx  = prefix.replace(/\u043d\u0435\u043a\u043e\u0440\u0440\w*|\u043d\u0435 \u043a\u043e\u0440\u0440\w*|\u043d\u0435\u0432\u0435\u0440\w*|\u043d\u0435 \u0432\u0435\u0440\w*|\u043e\u0448\u0438\u0431\w*|\u043d\u0435\u043f\u0440\u0430\u0432\u0438\u043b\w*|\u043d\u0435 \u043f\u0440\u0430\u0432\u0438\u043b\w*|\u0432\u043c\u0435\u0441\u0442\u043e/gi, '');
            const goodRegex = /\u043a\u043e\u0440\u0440|\u0432\u0435\u0440\u043d|\u043f\u0440\u0430\u0432\u0438\u043b|\u043d\u0443\u0436\u043d|\u043d\u0430\s*$/i;
            const isGood    = goodRegex.test(cleanPfx);

            if (isBad && !isGood)        incorrectGBs.push(cur.value);
            else if (isGood && !isBad)   correctGBs.push(cur.value);
        }

        // Метод исключения при двух ГБ
        if (matches.length === 2) {
            if (incorrectGBs.length === 1 && correctGBs.length === 0) {
                const missing = matches.find(m => m.value !== incorrectGBs[0]);
                if (missing) correctGBs.push(missing.value);
            } else if (correctGBs.length === 1 && incorrectGBs.length === 0) {
                const missing = matches.find(m => m.value !== correctGBs[0]);
                if (missing) incorrectGBs.push(missing.value);
            }
        }

        if (correctGBs.length > 0 || incorrectGBs.length > 0) {
            return { correctGB: correctGBs.join(', '), incorrectGB: incorrectGBs.join(', ') };
        }

        // Жёсткий fallback (нет контекстных слов)
        return {
            correctGB:   matches[1] ? matches[1].value : '',
            incorrectGB: matches[0] ? matches[0].value : '',
        };
    }

    /**
     * Открывает модал с описанием тикета и двумя инпутами (корректный / некорректный ГБ).
     * На подтверждение генерирует SQL-скрипт и копирует в буфер.
     */
    async function changeGB() {
        // ── Парсим данные со страницы ─────────────────────────────────────────
        const h2Text      = document.querySelector('#content h2')?.innerText || '';
        const ticketMatch = h2Text.match(/#(\d+)/) || h2Text.match(/(\d+)/);
        const ticketNumber = ticketMatch ? ticketMatch[1] : '\u041d\u041e\u041c\u0415\u0420_\u0417\u0410\u042f\u0412\u041a\u0418';

        const descEl      = document.querySelector('.description .wiki');
        const descText    = descEl ? descEl.innerText.trim() : '\u0422\u0435\u043a\u0441\u0442 \u0437\u0430\u044f\u0432\u043a\u0438 \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d \u043d\u0430 \u0441\u0442\u0440\u0430\u043d\u0438\u0446\u0435';

        const { correctGB, incorrectGB } = parseGBNumbers(descText);

        // ── Показываем модал ──────────────────────────────────────────────────
        const modal = new <название>Modal({
            title:       '\uD83D\uDD04 \u041f\u043e\u043c\u0435\u043d\u044f\u0442\u044c \u0413\u0411 - \u0422\u0438\u043a\u0435\u0442 #' + ticketNumber,
            dark:        isDarkMode(),
            confirmText: '\u0421\u043a\u043e\u043f\u0438\u0440\u043e\u0432\u0430\u0442\u044c SQL',
        });

        modal.addInfo({ text: descText, maxHeight: '110px' });

        modal.addInput({
            id:          'incorrectGB',
            label:       '\u041d\u0435\u043a\u043e\u0440\u0440\u0435\u043a\u0442\u043d\u044b\u0439 \u0413\u0411',
            placeholder: 'GB...',
            value:       incorrectGB,
        });

        modal.addInput({
            id:          'correctGB',
            label:       '\u041a\u043e\u0440\u0440\u0435\u043a\u0442\u043d\u044b\u0439 \u0413\u0411',
            placeholder: 'GB...',
            value:       correctGB,
        });

        const result = await modal.show();
        if (!result) return;

        const inc = result.incorrectGB.trim();
        const cor = result.correctGB.trim();

        if (!inc) {
            showToast('\u0423\u043a\u0430\u0436\u0438\u0442\u0435 \u043d\u0435\u043a\u043e\u0440\u0440\u0435\u043a\u0442\u043d\u044b\u0439 \u0413\u0411', 'error');
            return;
        }

        // ── Разбиваем на пары (поддержка нескольких ГБ через запятую) ─────────
        const n       = ticketNumber;
        const incList = inc.split(/\s*,\s*/).filter(Boolean);
        const corList = cor.split(/\s*,\s*/).filter(Boolean);
        const count   = incList.length;
        const multi   = count > 1;

        // Генерируем блок SQL для одной пары
        const buildBlock = (incVal, corVal, idx) => {
            // При нескольких парах добавляем суффикс _1, _2, ... к именам таблиц
            const sfx = multi ? `_${idx + 1}` : '';
            return (
`select * into wms_temp.tmp_rm${n}_dropid${sfx} from dropid where dropid = '${incVal}'

select * into wms_temp.tmp_rm${n}_dropiddetail${sfx} from dropiddetail where dropid = '${incVal}'

select * into wms_temp.tmp_rm${n}_pickdetail${sfx} from pickdetail where dropid = '${incVal}' or id = '${incVal}'

select * into wms_temp.tmp_rm${n}_lotxlocxid${sfx} from lotxlocxid where id = '${incVal}'



--update dropid set dropid = '${corVal}' where dropid = '${incVal}'
--update dropiddetail set dropid = '${corVal}' where dropid = '${incVal}'
--update pickdetail set id = '${corVal}', dropid = '${corVal}' where id = '${incVal}'
--update lotxlocxid set id = '${corVal}' where id = '${incVal}'`
            );
        };

        const separator = '\n\n\n-- ' + '\u2550'.repeat(60) + '\n\n\n';
        const sql = incList
            .map((incVal, i) => buildBlock(incVal, corList[i] || '', i))
            .join(separator);

        try {
            await navigator.clipboard.writeText(sql);
            showToast('SQL \u043f\u043e\u043c\u0435\u043d\u044f\u0442\u044c \u0413\u0411 \u0441\u043a\u043e\u043f\u0438\u0440\u043e\u0432\u0430\u043d \u2713');
        } catch (err) {
            console.error('<название> changeGB:', err);
            showToast('\u041e\u0448\u0438\u0431\u043a\u0430 \u043a\u043e\u043f\u0438\u0440\u043e\u0432\u0430\u043d\u0438\u044f', 'error');
        }
    }

    // =========================================================================
    // SQL Toolbar Buttons - вставка SQL-обёрток в редактор по курсору
    // =========================================================================

    /**
     * Вставляет text в textarea по текущей позиции курсора.
     * Если есть выделение - заменяет его.
     */
    function insertAtCursor(textarea, text) {
        const start = textarea.selectionStart;
        const end   = textarea.selectionEnd;
        textarea.value =
            textarea.value.substring(0, start) +
            text +
            textarea.value.substring(end);
        const newPos = start + text.length;
        textarea.selectionStart = newPos;
        textarea.selectionEnd   = newPos;
        textarea.dispatchEvent(new Event('input',  { bubbles: true }));
        textarea.dispatchEvent(new Event('change', { bubbles: true }));
        textarea.focus();
    }

    /**
     * Инжектирует кнопки «SQL» и «SQL ▾» после кнопки jstb_macros
     * во всех тулбарах .jstElements на странице.
     * Безопасен для повторного вызова - дубликаты не добавляются.
     */
    function injectSQLToolbarButtons() {
        document.querySelectorAll('.jstElements').forEach(toolbar => {
            if (toolbar.querySelector('.ltm-sql-insert-btn')) return; // уже есть

            const macrosBtn = toolbar.querySelector('.jstb_macros');
            if (!macrosBtn) return;

            // Находим textarea в том же .jstBlock
            const jstBlock = toolbar.closest('.jstBlock');
            if (!jstBlock) return;
            const textarea = jstBlock.querySelector('textarea.wiki-edit');
            if (!textarea) return;

            // ── Кнопка «SQL» - обёртка <pre><code class="sql"> ───────────────
            const sqlBtn = document.createElement('button');
            sqlBtn.type      = 'button';
            sqlBtn.tabIndex  = 200;
            sqlBtn.className = 'ltm-sql-insert-btn';
            sqlBtn.title     = 'Вставить SQL из буфера';
            sqlBtn.textContent = 'SQL';

            sqlBtn.addEventListener('click', async () => {
                let clip = '';
                try { clip = await navigator.clipboard.readText(); } catch { /* нет разрешения */ }
                insertAtCursor(textarea, `<pre><code class="sql">\n${clip}\n</code></pre>`);
                chrome.storage.sync.get(['sqlAutoPrivate'], ({ sqlAutoPrivate = true }) => {
                    const privateChk = document.getElementById('issue_private_notes');
                    if (privateChk && sqlAutoPrivate) privateChk.checked = true;
                });
            });

            // ── Кнопка «SQL ▾» - свёрнутый блок {{collapse}} ─────────────────
            const sqlHiddenBtn = document.createElement('button');
            sqlHiddenBtn.type      = 'button';
            sqlHiddenBtn.tabIndex  = 200;
            sqlHiddenBtn.className = 'ltm-sql-insert-btn simple';
            sqlHiddenBtn.title     = 'Вставить SQL из буфера (свёрнуто)';
            sqlHiddenBtn.textContent = 'SQL ▾';

            sqlHiddenBtn.addEventListener('click', async () => {
                let clip = '';
                try { clip = await navigator.clipboard.readText(); } catch { /* нет разрешения */ }
                insertAtCursor(textarea, `{{collapse(SQL)\n<pre><code class="sql">\n${clip}\n</code></pre>\n\n}}`);
                chrome.storage.sync.get(['sqlAutoPrivate'], ({ sqlAutoPrivate = true }) => {
                    const privateChk = document.getElementById('issue_private_notes');
                    if (privateChk && sqlAutoPrivate) privateChk.checked = true;
                });
            });

            // Вставляем сразу после jstb_macros
            macrosBtn.after(sqlHiddenBtn);
            macrosBtn.after(sqlBtn);
        });
    }

    // =========================================================================
    // Menu builder
    // =========================================================================

    let menu = null;

    function removeIssueMenu() {
        if (menu) { menu.destroy(); menu = null; }
    }

    /**
     * Строит и показывает контекстное меню для страницы тикета.
     * @param {number} x
     * @param {number} y
     */
    function createIssueMenu(x, y) {
        removeIssueMenu();

        const issueId = getCurrentIssueId();
        const inShift = issueId ? isIssueInShift(issueId) : false;
        const isDark  = isDarkMode();

        menu = new <название>Menu({ dark: isDark });

        // ── Тёмный режим ──────────────────────────────────────────────────────
        menu.addToggle('\uD83C\uDF19 \u0422\u0451\u043c\u043d\u044b\u0439 \u0440\u0435\u0436\u0438\u043c', isDark, (checked) => {
            toggleDarkMode(checked);
            menu.setDark(checked);
            if (activeSub) activeSub.setDark(checked);
        });

        menu.addSeparator();

        // ── Взять в работу ────────────────────────────────────────────────────
        menu.addButton('\uD83D\uDFE2 \u0412\u0437\u044f\u0442\u044c \u0432 \u0440\u0430\u0431\u043e\u0442\u0443', () => {
            removeIssueMenu();
            takeInWork();
        });

        menu.addSeparator();

        // ── Submenu infrastructure ────────────────────────────────────────────
        let activeSub = null;
        let activeBtn = null;

        const scheduleSubHide = () => activeSub?.scheduleHide();
        const cancelSubHide   = () => activeSub?.cancelHide();

        const openSubmenu = (btn, buildFn) => {
            if (activeSub?.element) {
                if (activeBtn === btn) { cancelSubHide(); return; }
                activeSub.destroy();
                activeSub = null;
            }
            activeBtn = btn;
            activeSub = new <название>Submenu({ dark: isDarkMode() });
            buildFn(activeSub);
            activeSub.element.addEventListener('mouseenter', cancelSubHide);
            activeSub.element.addEventListener('mouseleave', scheduleSubHide);
            activeSub.showAt(btn);
        };

        // helper: закрыть подменю + главное меню после действия
        const closeAll = () => {
            activeSub?.destroy(); activeSub = null;
            removeIssueMenu();
        };

        // ── Смена (подменю) ───────────────────────────────────────────────────
        menu.addButton('\uD83D\uDCCB \u0421\u043c\u0435\u043d\u0430', null, {
            hasSubmenu: true,
            onHover: (btn) => openSubmenu(btn, (sub) => {

                if (!inShift) {
                    // ── Добавить с проверками ──────────────────────────────────
                    sub.addButton('\u2705 \u0414\u043e\u0431\u0430\u0432\u0438\u0442\u044c \u0432 \u0441\u043c\u0435\u043d\u0443 (\u0441 \u043f\u0440\u043e\u0432\u0435\u0440\u043a\u0430\u043c\u0438)', () => {
                        const errors = runShiftChecks();
                        if (errors.length) {
                            closeAll();
                            showToast('\u0422\u0438\u043a\u0435\u0442 \u043d\u0435 \u0434\u043e\u0431\u0430\u0432\u043b\u0435\u043d: ' + errors.join('; '), 'error', 3500);
                            return;
                        }
                        const data = getIssueDataFromPage();
                        if (!data) { closeAll(); return; }
                        const added = addIssueToShift(data);
                        closeAll();
                        showToast(added
                            ? '\u0422\u0438\u043a\u0435\u0442 #' + data.issueId + ' \u0434\u043e\u0431\u0430\u0432\u043b\u0435\u043d \u0432 \u0441\u043c\u0435\u043d\u0443 (\u043a\u0430\u0442\u0435\u0433\u043e\u0440\u0438\u044f: ' + data.category + ')'
                            : '\u0422\u0438\u043a\u0435\u0442 \u0443\u0436\u0435 \u0435\u0441\u0442\u044c \u0432 \u0441\u043c\u0435\u043d\u0435');
                    });

                    // ── Добавить без проверок ──────────────────────────────────
                    sub.addButton('\u2795 \u0414\u043e\u0431\u0430\u0432\u0438\u0442\u044c \u0432 \u0441\u043c\u0435\u043d\u0443 (\u0431\u0435\u0437 \u043f\u0440\u043e\u0432\u0435\u0440\u043e\u043a)', () => {
                        const data = getIssueDataFromPage();
                        if (!data) { closeAll(); return; }
                        const added = addIssueToShift(data);
                        closeAll();
                        showToast(added
                            ? '\u0422\u0438\u043a\u0435\u0442 #' + data.issueId + ' \u0434\u043e\u0431\u0430\u0432\u043b\u0435\u043d \u0432 \u0441\u043c\u0435\u043d\u0443 (\u043a\u0430\u0442\u0435\u0433\u043e\u0440\u0438\u044f: ' + data.category + ')'
                            : '\u0422\u0438\u043a\u0435\u0442 \u0443\u0436\u0435 \u0435\u0441\u0442\u044c \u0432 \u0441\u043c\u0435\u043d\u0435');
                    });

                } else {
                    // ── Удалить из смены ───────────────────────────────────────
                    sub.addButton('\uD83D\uDDD1\uFE0F \u0423\u0434\u0430\u043b\u0438\u0442\u044c \u0438\u0437 \u0441\u043c\u0435\u043d\u044b', () => {
                        const removed = issueId ? removeIssueFromShift(issueId) : false;
                        closeAll();
                        showToast(removed
                            ? '\u0422\u0438\u043a\u0435\u0442 #' + issueId + ' \u0443\u0434\u0430\u043b\u0451\u043d \u0438\u0437 \u0441\u043c\u0435\u043d\u044b'
                            : '\u0422\u0438\u043a\u0435\u0442 \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d \u0432 \u0441\u043c\u0435\u043d\u0435',
                            removed ? 'ok' : 'error');
                    }, { variant: 'danger' });
                }
            }),
            onHoverLeave: () => scheduleSubHide()
        });

        // ── HS (подменю) ──────────────────────────────────────────────────────
        menu.addButton('\u26A1 HS', null, {
            hasSubmenu: true,
            onHover: (btn) => openSubmenu(btn, (sub) => {
                sub.addButton('Ева',                        () => { closeAll(); fetchHSEva(); });
                sub.addButton('Остальные',                  () => { closeAll(); copyHSOtherScript(); });
                sub.addButton('Скрипт расхождений БД',      () => { closeAll(); copyDBDiscrepancyScript(); });
                sub.addButton('DEPO',                       () => { closeAll(); copyDepoScript(); });
            }),
            onHoverLeave: () => scheduleSubHide()
        });

        // ── DBA (подменю) ─────────────────────────────────────────────────────
        menu.addButton('\uD83D\uDDC4\uFE0F DBA', null, {
            hasSubmenu: true,
            onHover: (btn) => openSubmenu(btn, (sub) => {
                sub.addButton('\u0413\u0440\u0430\u0444\u0430\u043d\u0430',            () => { closeAll(); window.open('<IP графаны>', '_blank'); });
                sub.addButton('\u0417\u0430\u043f\u0440\u043e\u0441 \u0434\u043b\u044f LOCK',   () => { closeAll(); copyLockQueryScript(); });
                sub.addButton('\u0410\u043f\u0434\u0435\u0442 \u0441\u0442\u0430\u0442\u0438\u0441\u0442\u0438\u043a\u0438', () => { closeAll(); copyUpdateStatisticsScript(); });
            }),
            onHoverLeave: () => scheduleSubHide()
        });

        menu.addSeparator();

        // ── Одиночные кнопки ──────────────────────────────────────────────────
        menu.addButton('\u23F1\uFE0F \u0412\u0432\u0435\u0441\u0442\u0438 \u0442\u0440\u0443\u0434\u043e\u0437\u0430\u0442\u0440\u0430\u0442\u044b', () => { removeIssueMenu(); logTimeSpent(); });
        menu.addButton('\uD83D\uDD04 \u041f\u043e\u043c\u0435\u043d\u044f\u0442\u044c \u0413\u0411',          () => { removeIssueMenu(); changeGB(); });
        menu.addButton('\uD83D\uDCDD \u042F\u041C \u0417\u0430\u043f\u0440\u043e\u0441',            () => { removeIssueMenu(); copyYMRequest(); });

        menu.show(x, y);
    }

    // =========================================================================
    // Event listener
    // =========================================================================

    chrome.storage.sync.get(['ctxMenuIssues'], ({ ctxMenuIssues = true }) => {
        if (!ctxMenuIssues) return;
        window.addEventListener('contextmenu', (e) => {
            e.preventDefault();
            createIssueMenu(e.clientX, e.clientY);
        });
    });

    // =========================================================================
    // Init - SQL toolbar buttons
    // =========================================================================

    // Инжектируем сразу (тулбары уже в DOM при document_idle)
    injectSQLToolbarButtons();

    // MutationObserver - на случай если тулбар появился позже
    // (например, редактор описания открывается кликом)
    new MutationObserver(() => injectSQLToolbarButtons())
        .observe(document.body, { childList: true, subtree: true });

})();
