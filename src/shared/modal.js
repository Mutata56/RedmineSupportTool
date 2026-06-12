/**
 * <название> - Shared Modal Component
 *
 * Reusable Promise-based modal dialog for any extension page.
 * No external dependencies. Requires modal.css (or styles.css tokens).
 *
 * Usage:
 *   const modal = new <название>Modal({
 *       title:       'Ввести трудозатраты',
 *       dark:        isDarkMode(),
 *       confirmText: 'Добавить',
 *   });
 *   modal.addInput({ id: 'minutes', label: 'Время (в минутах)', placeholder: '70', hint: '70 мин → 1:10' });
 *
 *   const result = await modal.show();   // null если отменили
 *   if (result) console.log(result.minutes);
 *
 * @version 1.0.0
 * @author  KKRLL56
 */

'use strict';

class <название>Modal {
    /**
     * @param {object}  [options]
     * @param {string}  [options.title]
     * @param {boolean} [options.dark=false]
     * @param {string}  [options.confirmText='OK']
     * @param {string}  [options.cancelText='Отмена']
     */
    constructor({ title = '', dark = false, confirmText = 'OK', cancelText = '\u041e\u0442\u043c\u0435\u043d\u0430' } = {}) {
        this._title       = title;
        this._dark        = dark;
        this._confirmText = confirmText;
        this._cancelText  = cancelText;
        this._infos       = [];   // Array<{ text, maxHeight }>
        this._fields      = [];   // Array<{ id, label, placeholder, type, hint, presets, value }>
        this._overlay     = null;
        this._inputs      = {};   // id → HTMLInputElement
        this._resolve     = null;
        this._keyHandler  = null;
    }

    // ── Public API ────────────────────────────────────────────────────────────

    /**
     * Add a labelled input field to the modal.
     *
     * @param {object} opts
     * @param {string} opts.id           - Unique key; used to retrieve value from result object.
     * @param {string} [opts.label]      - Label text shown above the input.
     * @param {string} [opts.placeholder]
     * @param {string} [opts.type='text'] - HTML input type.
     * @param {string} [opts.hint]        - Optional small hint below the input.
     * @returns {<название>Modal}  (chainable)
     */
    /**
     * Add a read-only info block (scrollable text) above the input fields.
     * @param {object} opts
     * @param {string} opts.text       - Text content to display.
     * @param {string} [opts.maxHeight='120px'] - Max CSS height before scrolling.
     * @returns {<название>Modal}
     */
    addInfo({ text = '', maxHeight = '120px' } = {}) {
        this._infos.push({ text, maxHeight });
        return this;
    }

    addInput({ id, label = '', placeholder = '', type = 'text', hint = '', presets = [], value = '' } = {}) {
        this._fields.push({ id, label, placeholder, type, hint, presets, value });
        return this;
    }

    /**
     * Render and show the modal.
     * @returns {Promise<Object|null>}
     *   Resolves with `{ id: value, … }` on confirm, or `null` on cancel / Escape / outside click.
     */
    show() {
        return new Promise(resolve => {
            this._resolve = resolve;
            this._build();
            document.body.appendChild(this._overlay);

            // Trigger CSS transition on next frame
            requestAnimationFrame(() => {
                this._overlay.classList.add('ltm-modal-overlay--visible');
                // Focus the first input for immediate keyboard input
                const first = Object.values(this._inputs)[0];
                if (first) first.focus();
            });
        });
    }

    /**
     * Switch dark / light theme on the fly.
     * @param {boolean} dark
     */
    setDark(dark) {
        this._dark = Boolean(dark);
        this._overlay?.querySelector('.ltm-modal')?.classList.toggle('ltm-modal--dark', this._dark);
    }

    /**
     * Close and remove the modal without resolving (resolves with null if pending).
     */
    destroy() {
        document.removeEventListener('keydown', this._keyHandler);
        if (!this._overlay) return;

        const overlay = this._overlay;
        this._overlay = null;

        overlay.classList.remove('ltm-modal-overlay--visible');
        setTimeout(() => overlay.remove(), 180);
    }

    // ── Private ───────────────────────────────────────────────────────────────

    _build() {
        // ── Overlay ───────────────────────────────────────────────────────────
        const overlay = document.createElement('div');
        overlay.className = 'ltm-modal-overlay';
        overlay.setAttribute('role', 'presentation');

        // Click outside → cancel
        overlay.addEventListener('mousedown', e => {
            if (e.target === overlay) this._cancel();
        });
        this._overlay = overlay;

        // ── Card ──────────────────────────────────────────────────────────────
        const card = document.createElement('div');
        card.className = 'ltm-modal' + (this._dark ? ' ltm-modal--dark' : '');
        card.setAttribute('role', 'dialog');
        card.setAttribute('aria-modal', 'true');
        if (this._title) card.setAttribute('aria-label', this._title);

        // Title
        if (this._title) {
            const h = document.createElement('div');
            h.className = 'ltm-modal__title';
            h.textContent = this._title;
            card.appendChild(h);
        }

        // Info blocks (read-only)
        this._infos.forEach(info => {
            const block = document.createElement('div');
            block.className = 'ltm-modal__info';
            block.style.maxHeight = info.maxHeight;
            block.textContent = info.text;
            card.appendChild(block);
        });

        // Fields
        this._fields.forEach(f => {
            const row = document.createElement('div');
            row.className = 'ltm-modal__field';

            if (f.label) {
                const lbl = document.createElement('label');
                lbl.className = 'ltm-modal__label';
                lbl.htmlFor = 'ltm-modal-inp-' + f.id;
                lbl.textContent = f.label;
                row.appendChild(lbl);
            }

            const inp = document.createElement('input');
            inp.type        = f.type;
            inp.id          = 'ltm-modal-inp-' + f.id;
            inp.className   = 'ltm-modal__input';
            inp.placeholder = f.placeholder;
            inp.autocomplete = 'off';
            if (f.value) inp.value = f.value;
            inp.addEventListener('keydown', e => {
                if (e.key === 'Enter')  { e.preventDefault(); this._confirm(); }
                if (e.key === 'Escape') { e.stopPropagation(); this._cancel(); }
            });
            row.appendChild(inp);
            this._inputs[f.id] = inp;

            if (f.presets && f.presets.length) {
                const presetsRow = document.createElement('div');
                presetsRow.className = 'ltm-modal__presets';
                f.presets.forEach(val => {
                    const btn = document.createElement('button');
                    btn.type = 'button';
                    btn.className = 'ltm-modal__preset-btn';
                    btn.textContent = val;
                    btn.addEventListener('click', () => {
                        inp.value = val;
                        inp.focus();
                    });
                    presetsRow.appendChild(btn);
                });
                row.appendChild(presetsRow);
            }

            if (f.hint) {
                const hint = document.createElement('div');
                hint.className = 'ltm-modal__hint';
                hint.textContent = f.hint;
                row.appendChild(hint);
            }

            card.appendChild(row);
        });

        // Buttons row
        const btns = document.createElement('div');
        btns.className = 'ltm-modal__buttons';

        const cancelBtn = document.createElement('button');
        cancelBtn.type = 'button';
        cancelBtn.className = 'ltm-modal__btn ltm-modal__btn--cancel';
        cancelBtn.textContent = this._cancelText;
        cancelBtn.addEventListener('click', () => this._cancel());

        const confirmBtn = document.createElement('button');
        confirmBtn.type = 'button';
        confirmBtn.className = 'ltm-modal__btn ltm-modal__btn--confirm';
        confirmBtn.textContent = this._confirmText;
        confirmBtn.addEventListener('click', () => this._confirm());

        btns.appendChild(cancelBtn);
        btns.appendChild(confirmBtn);
        card.appendChild(btns);

        overlay.appendChild(card);

        // Global Escape handler
        this._keyHandler = e => { if (e.key === 'Escape') this._cancel(); };
        document.addEventListener('keydown', this._keyHandler, { once: true });
    }

    _confirm() {
        if (!this._resolve) return;
        const values = {};
        Object.entries(this._inputs).forEach(([id, inp]) => { values[id] = inp.value; });
        this._resolve(values);
        this._resolve = null;
        this.destroy();
    }

    _cancel() {
        if (!this._resolve) return;
        this._resolve(null);
        this._resolve = null;
        this.destroy();
    }
}
