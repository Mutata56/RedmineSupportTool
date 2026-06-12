/**
 * <название> - Shared Menu Component
 *
 * Reusable context menu and submenu classes for all extension pages.
 * No external dependencies. Requires menu.css (or styles.css tokens).
 *
 * Usage:
 *   const menu = new <название>Menu({ dark: isDarkMode() });
 *
 *   // Добавить пункт:
 *   menu.addButton('Label', () => { ... });
 *
 *   // Добавить пункт с иконкой:
 *   menu.addButton('Label', () => { ... }, { icon: 'icon.png' });
 *
 *   // Подменю:
 *   const sub = new <название>Submenu({ dark: isDarkMode() });
 *   sub.addButton('Sub Item', () => { ... });
 */

'use strict';

// ============================================================================
// <название>Menu - base context menu
// ============================================================================

class <название>Menu {
    /**
     * @param {object}  [options]
     * @param {boolean} [options.dark=false]       - Start in dark theme
     * @param {boolean} [options.autoClose=true]   - Close on outside click / Escape
     */
    constructor({ dark = false, autoClose = true } = {}) {
        this._dark       = dark;
        this._autoClose  = autoClose;
        this._el         = this._build();

        this._outsideHandler = null;
        this._keyHandler     = null;
    }

    // ── Private ──────────────────────────────────────────────────────────────

    _build() {
        const el = document.createElement('div');
        el.className = 'ltm-menu';
        if (this._dark) el.classList.add('ltm-menu--dark');
        el.setAttribute('role', 'menu');
        return el;
    }

    // ── Public API ────────────────────────────────────────────────────────────

    /**
     * Add a clickable button item.
     *
     * @param {string}   label
     * @param {Function} [onClick]              - (event, buttonEl) => void
     * @param {object}   [opts]
     * @param {'primary'|'danger'|'success'} [opts.variant]
     * @param {boolean}  [opts.hasSubmenu]      - Adds › arrow and --has-sub class
     * @param {Function} [opts.onHover]         - (buttonEl, event) => void
     * @param {Function} [opts.onHoverLeave]    - (buttonEl, event) => void
     * @returns {HTMLButtonElement}
     */
    addButton(label, onClick, { variant, hasSubmenu, onHover, onHoverLeave } = {}) {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'ltm-menu__item';
        btn.setAttribute('role', 'menuitem');
        btn.textContent = label;

        if (variant)    btn.classList.add(`ltm-menu__item--${variant}`);
        if (hasSubmenu) btn.classList.add('ltm-menu__item--has-sub');

        if (onClick) {
            btn.addEventListener('click', e => {
                e.stopPropagation();
                onClick(e, btn);
            });
        }

        if (onHover)      btn.addEventListener('mouseenter', e => onHover(btn, e));
        if (onHoverLeave) btn.addEventListener('mouseleave', e => onHoverLeave(btn, e));

        this._el.appendChild(btn);
        return btn;
    }

    /**
     * Add a checkbox toggle row.
     *
     * @param {string}   label
     * @param {boolean}  checked
     * @param {Function} onChange   - (newChecked: boolean) => void
     * @returns {{ row: HTMLLabelElement, checkbox: HTMLInputElement }}
     */
    addToggle(label, checked, onChange) {
        const row = document.createElement('label');
        row.className = 'ltm-menu__toggle-row';
        row.setAttribute('role', 'menuitemcheckbox');
        row.setAttribute('aria-checked', String(checked));

        const cb = document.createElement('input');
        cb.type    = 'checkbox';
        cb.checked = Boolean(checked);

        cb.addEventListener('change', e => {
            e.stopPropagation();
            row.setAttribute('aria-checked', String(cb.checked));
            onChange(cb.checked);
        });

        // Clicking the label shouldn't bubble to document (would trigger autoClose)
        row.addEventListener('click', e => e.stopPropagation());

        const span = document.createElement('span');
        span.textContent = label;

        row.appendChild(cb);
        row.appendChild(span);
        this._el.appendChild(row);

        return { row, checkbox: cb };
    }

    /**
     * Add a visual separator between item groups.
     * @returns {HTMLHRElement}
     */
    addSeparator() {
        const sep = document.createElement('hr');
        sep.className = 'ltm-menu__separator';
        sep.setAttribute('role', 'separator');
        this._el.appendChild(sep);
        return sep;
    }

    /**
     * Add a non-interactive section header label.
     * @param {string} text
     * @returns {HTMLDivElement}
     */
    addHeader(text) {
        const h = document.createElement('div');
        h.className = 'ltm-menu__header';
        h.textContent = text;
        this._el.appendChild(h);
        return h;
    }

    /**
     * Show the menu at (x, y), repositioning if it would overflow the viewport.
     * @param {number} x
     * @param {number} y
     */
    show(x, y) {
        if (!this._el) return;

        document.body.appendChild(this._el);

        // Measure rendered size before positioning
        const w  = this._el.offsetWidth;
        const h  = this._el.offsetHeight;
        const vw = window.innerWidth;
        const vh = window.innerHeight;

        const left = (x + w > vw) ? Math.max(0, vw - w - 8) : x;
        const top  = (y + h > vh) ? Math.max(0, vh - h - 8) : y;

        this._el.style.left = `${left}px`;
        this._el.style.top  = `${top}px`;

        // Trigger CSS transition on the next frame
        requestAnimationFrame(() => {
            this._el?.classList.add('ltm-menu--visible');
        });

        // Auto-close handlers
        if (this._autoClose) {
            setTimeout(() => {
                this._outsideHandler = e => {
                    if (!this._el?.contains(e.target)) this.destroy();
                };
                this._keyHandler = e => {
                    if (e.key === 'Escape') this.destroy();
                };
                document.addEventListener('mousedown', this._outsideHandler, { once: true });
                document.addEventListener('keydown',   this._keyHandler,     { once: true });
            });
        }
    }

    /**
     * Switch dark / light theme on the fly.
     * @param {boolean} dark
     */
    setDark(dark) {
        this._dark = Boolean(dark);
        this._el?.classList.toggle('ltm-menu--dark', this._dark);
    }

    /**
     * Remove the menu from the DOM (with fade-out transition).
     */
    destroy() {
        if (!this._el) return;

        document.removeEventListener('mousedown', this._outsideHandler);
        document.removeEventListener('keydown',   this._keyHandler);

        const el = this._el;
        this._el = null;

        el.classList.remove('ltm-menu--visible');

        // Wait for CSS transition to finish before removing
        setTimeout(() => el.remove(), 120);
    }

    /** @returns {HTMLDivElement|null} The root menu DOM element. */
    get element() {
        return this._el;
    }
}


// ============================================================================
// <название>Submenu - flyout submenu anchored to a button
// ============================================================================

class <название>Submenu extends <название>Menu {
    /**
     * @param {object}  [options]
     * @param {boolean} [options.dark=false]
     * @param {number}  [options.hideDelay=180]  - ms to wait before hiding on mouseleave
     */
    constructor({ dark = false, hideDelay = 180 } = {}) {
        super({ dark, autoClose: false });
        this._hideDelay = hideDelay;
        this._hideTimer = null;
    }

    /**
     * Show to the right of anchorEl (flips left if no viewport room).
     * @param {HTMLElement} anchorEl
     */
    showAt(anchorEl) {
        if (!this._el) return;

        document.body.appendChild(this._el);

        const rect = anchorEl.getBoundingClientRect();
        const vw   = window.innerWidth;
        const vh   = window.innerHeight;
        const w    = this._el.offsetWidth;
        const h    = this._el.offsetHeight;
        const gap  = 6;

        // Prefer right side; flip left if overflow
        let left = rect.right + gap;
        if (left + w > vw) left = rect.left - w - gap;

        // Align top with anchor; shift up if overflow
        let top = rect.top;
        if (top + h > vh) top = Math.max(0, vh - h - 8);

        this._el.style.left = `${left}px`;
        this._el.style.top  = `${top}px`;

        requestAnimationFrame(() => {
            this._el?.classList.add('ltm-menu--visible');
        });
    }

    /**
     * Schedule hiding after hideDelay ms.
     * Call cancelHide() if the cursor re-enters the submenu or parent button.
     */
    scheduleHide() {
        this.cancelHide();
        this._hideTimer = setTimeout(() => {
            this.destroy();
        }, this._hideDelay);
    }

    /** Cancel a pending scheduled hide. */
    cancelHide() {
        if (this._hideTimer) {
            clearTimeout(this._hideTimer);
            this._hideTimer = null;
        }
    }

    destroy() {
        this.cancelHide();
        super.destroy();
    }
}
