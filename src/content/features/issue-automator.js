// issue-automator.js - Автоматизация создания задач v2.2
console.log("Issue Automator запущен");

const CONFIG = {
    trackerId: '<tracker_id>', // Алерт
    presets: [
        "HealthScript Job Notifier",
        "Проверка логов планировщика WMS Infor"
    ],
    // ID поля и нужное значение
    causeFieldId: 'issue_custom_field_values_<field_id>',
    causeValue: "Превентивные мероприятия"
};

// === ХЕЛПЕРЫ ===
function detectCurrentUserId() {
    const link = document.querySelector('#loggedas a');
    if (link) {
        const match = link.getAttribute('href').match(/\/people\/(\d+)$/);
        return match ? match[1] : null;
    }
    return null;
}

// === 1. УМНЫЙ ПОИСК ПРОЕКТА ===
function transformProjectSelect() {
    const originalSelect = document.getElementById('issue_project_id');
    if (!originalSelect || document.getElementById('ltm_project_search_wrapper')) return;

    const wrapper = document.createElement('div');
    wrapper.id = 'ltm_project_search_wrapper';
    wrapper.className = 'ltm-search-select-wrapper';

    const searchInput = document.createElement('input');
    searchInput.type = 'text';
    searchInput.className = 'ltm-search-input';
    searchInput.placeholder = 'Поиск проекта...';
    searchInput.autocomplete = 'off';

    const dropdown = document.createElement('div');
    dropdown.className = 'ltm-search-dropdown hidden';

    let options = [];
    Array.from(originalSelect.options).forEach(opt => {
        if (opt.value) {
            options.push({
                value: opt.value,
                textRaw: opt.text,
                textClean: opt.text.replace(/»|&nbsp;|\u00a0/g, '').trim().toLowerCase(),
                selected: opt.selected
            });
        }
    });

    const currentSelected = options.find(o => o.selected);
    if (currentSelected) {
        searchInput.value = currentSelected.textRaw.trim();
    }

    function renderList(filter = '') {
        dropdown.innerHTML = '';
        const lowerFilter = filter.toLowerCase();
        const filtered = options.filter(opt => opt.textClean.includes(lowerFilter));

        if (filtered.length === 0) {
            const noRes = document.createElement('div');
            noRes.className = 'ltm-search-option no-results';
            noRes.textContent = 'Ничего не найдено';
            dropdown.appendChild(noRes);
            return;
        }

        filtered.forEach(opt => {
            const item = document.createElement('div');
            item.className = 'ltm-search-option';
            item.textContent = opt.textRaw;
            if (opt.value === originalSelect.value) item.classList.add('selected');

            item.addEventListener('click', () => {
                originalSelect.value = opt.value;
                searchInput.value = opt.textRaw.trim();
                dropdown.classList.add('hidden');
                // Важно: событие change заставит Redmine обновить форму (AJAX)
                originalSelect.dispatchEvent(new Event('change', { bubbles: true }));
            });

            dropdown.appendChild(item);
        });
    }

    searchInput.addEventListener('focus', () => {
        renderList('');
        dropdown.classList.remove('hidden');
    });

    searchInput.addEventListener('input', (e) => {
        renderList(e.target.value);
        dropdown.classList.remove('hidden');
    });

    document.addEventListener('click', (e) => {
        if (!wrapper.contains(e.target)) {
            dropdown.classList.add('hidden');
            const selected = options.find(o => o.value === originalSelect.value);
            if (selected && document.activeElement !== searchInput) {
                searchInput.value = selected.textRaw.trim();
            }
        }
    });

    originalSelect.style.display = 'none';
    originalSelect.parentNode.insertBefore(wrapper, originalSelect);
    wrapper.appendChild(searchInput);
    wrapper.appendChild(dropdown);
}

// === 2. ВЫПАДАЮЩАЯ ТЕМА ===
function injectSubjectDropdown() {

const isNewIssue = window.location.pathname.includes('/issues/new')

if (!isNewIssue) { return;}
    const originalInput = document.getElementById('issue_subject');
    if (!originalInput || document.getElementById('ltm_subject_select')) return;

    const wrapper = document.createElement('div');
    wrapper.className = 'ltm-subject-wrapper';

    const select = document.createElement('select');
    select.id = 'ltm_subject_select';
    select.className = 'ltm-custom-select';

    const defaultOpt = document.createElement('option');
    defaultOpt.text = "-- Выберите тему задачи --";
    defaultOpt.value = "";
    select.appendChild(defaultOpt);

    CONFIG.presets.forEach(text => {
        const opt = document.createElement('option');
        opt.value = text;
        opt.text = text;
        select.appendChild(opt);
    });

    const customOpt = document.createElement('option');
    customOpt.value = "custom";
    customOpt.text = "Написать вручную...";
    select.appendChild(customOpt);

    select.addEventListener('change', () => {
        if (select.value === 'custom') {
            originalInput.style.display = 'inline-block';
            originalInput.value = '';
            originalInput.focus();
            originalInput.placeholder = "Введите тему...";
        } else {
            originalInput.style.display = 'none';
            originalInput.value = select.value;
        }
        originalInput.dispatchEvent(new Event('change', { bubbles: true }));
    });

    originalInput.parentNode.insertBefore(wrapper, originalInput);
    wrapper.appendChild(select);
    wrapper.appendChild(originalInput);
    originalInput.style.display = 'none';
}

// === 3. АВТОЗАПОЛНЕНИЕ ПОЛЕЙ ===
function applyDefaults() {
    // Проверяем, что это именно страница создания НОВОЙ задачи
    const isNewIssue = window.location.pathname.includes('/issues/new')

    if (!isNewIssue) {
        console.log("Это редактирование существующей задачи. Автозаполнение пропущено.");
        return;
    }

    console.log("Применяю автозаполнение полей для новой задачи...");

    // 1. Трекер -> Алерт
    const trackerSelect = document.getElementById('issue_tracker_id');
    if (trackerSelect && trackerSelect.value !== CONFIG.trackerId) {
        trackerSelect.value = CONFIG.trackerId;
        trackerSelect.dispatchEvent(new Event('change', { bubbles: true }));
    }

    // 2. Назначена -> Мне
    const currentUserId = detectCurrentUserId();
    const assigneeSelect = document.getElementById('issue_assigned_to_id');
    if (assigneeSelect && currentUserId && assigneeSelect.value !== currentUserId) {
        assigneeSelect.value = currentUserId;
        assigneeSelect.dispatchEvent(new Event('change', { bubbles: true }));
    }

    // 3. Частная -> Да
    const privateCheckbox = document.getElementById('issue_is_private');
    if (privateCheckbox && !privateCheckbox.checked) {
        privateCheckbox.checked = true;
        privateCheckbox.dispatchEvent(new Event('change', { bubbles: true }));
    }

    // 4. Причина обращения (CF 109) -> Превентивные мероприятия
    const causeSelect = document.getElementById(CONFIG.causeFieldId);
    if (causeSelect && causeSelect.value !== CONFIG.causeValue) {
        causeSelect.value = CONFIG.causeValue;
        causeSelect.dispatchEvent(new Event('change', { bubbles: true }));
        console.log(`Поле 'Причина' установлено в '${CONFIG.causeValue}'`);
    }
}

// === INIT ===
function init() {
    transformProjectSelect();
    applyDefaults();
    injectSubjectDropdown();

    // Защита от AJAX (Redmine перерисовывает форму при смене трекера или проекта)
    const observer = new MutationObserver((mutations) => {
        const subjectInput = document.getElementById('issue_subject');

        // Если инпут темы есть, а нашего селекта нет - значит форма обновилась
        if (subjectInput && !document.getElementById('ltm_subject_select')) {
            console.log("Обнаружено обновление формы Redmine!");

            // Ждем завершения рендера
            setTimeout(() => {
                injectSubjectDropdown();
                // Принудительно вызываем applyDefaults, чтобы проставить "Причину" и другие поля
                applyDefaults();
            }, 100);
        }

        // Восстановление поиска проекта (если Redmine вдруг перерисовал весь контейнер целиком)
        if (document.getElementById('issue_project_id') && !document.getElementById('ltm_project_search_wrapper')) {
             transformProjectSelect();
        }
    });

    const formAttributes = document.getElementById('all_attributes');
    if (formAttributes) {
        observer.observe(formAttributes, { childList: true, subtree: true });
    }

    const mainContent = document.getElementById('content');
    if(mainContent) {
         observer.observe(mainContent, { childList: true, subtree: true });
    }
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}