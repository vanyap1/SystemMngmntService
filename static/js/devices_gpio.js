/* ==========================================================================
   Devices popup tab "GPIO": line overview like `gpioinfo` + manual control.
   Lines are claimed on demand and released when the tab is left (see core/gpio_ctl.py).
   ========================================================================== */

Devices.register({
    id: 'gpio',
    autoMs: 2000,
    CTL_MS: 1000,           // value polling + lease heartbeat
    data: null,
    prev: {},               // "chip:offset" -> JSON of the line
    changedAt: {},
    expanded: new Set(),    // chips are collapsed by default
    client: Date.now().toString(36) + Math.random().toString(36).slice(2, 10),
    held: {},               // "chip:offset" -> {direction, value, error}
    ctlTimer: null,

    load() {
        return App.api('/api/devices/gpio').then(data => {
            const now = Date.now();
            const first = !this.data;
            (data.chips || []).forEach(chip => chip.lines.forEach(l => {
                const key = chip.path + ':' + l.offset;
                const json = JSON.stringify(l);
                if (!first && this.prev[key] !== undefined && this.prev[key] !== json) this.changedAt[key] = now;
                this.prev[key] = json;
            }));
            this.data = data;
            const chips = data.chips || [];
            const lines = chips.reduce((s, c) => s + c.lines.length, 0);
            const used = chips.reduce((s, c) => s + c.lines.filter(l => l.used).length, 0);
            Devices.summary(`${chips.length} chips · ${lines} lines · ${used} used`, this.id);
            this.render();
        });
    },

    onShow() {
        if (!this.ctlTimer) {
            this.ctlTimer = setInterval(() => this._pollCtl(), this.CTL_MS);
            this._pollCtl();
        }
    },

    onHide() {
        clearInterval(this.ctlTimer);
        this.ctlTimer = null;
        this.releaseAll();
    },

    toggleChip(path) {
        if (this.expanded.has(path)) this.expanded.delete(path);
        else this.expanded.add(path);
        this.render();
    },

    expandAll(open) {
        this.expanded = open && this.data && this.data.chips ? new Set(this.data.chips.map(c => c.path)) : new Set();
        this.render();
    },

    render() {
        const n = Object.keys(this.held).length;
        const badge = document.getElementById('gpio-held-count');
        badge.textContent = n + ' claimed';
        badge.className = 'badge ' + (n ? 'badge-info' : 'badge-muted');
        document.getElementById('gpio-release-all').hidden = !n;

        const pane = document.getElementById('gpio-pane');
        const data = this.data;
        if (!data) return;
        if (data.raw !== undefined) {
            pane.innerHTML = `<div class="tbl-empty text-warn">${esc(data.error)}</div>
                <pre class="gpio-raw">${esc(data.raw || 'gpioinfo is not available')}</pre>`;
            return;
        }
        if (!data.chips.length) {
            pane.innerHTML = '<div class="tbl-empty">No GPIO chips found (/dev/gpiochip*)</div>';
            return;
        }
        const q = document.getElementById('gpio-filter').value.trim().toLowerCase();
        const usedOnly = document.getElementById('gpio-used-only').checked;
        const now = Date.now();

        pane.innerHTML = data.chips.map(chip => {
            const base = chip.base != null ? chip.base : null;
            const used = chip.lines.filter(l => l.used).length;
            const lines = chip.lines.filter(l => {
                if (usedOnly && !l.used) return false;
                if (!q) return true;
                const num = base != null ? String(base + l.offset) : '';
                return String(l.offset) === q || num === q ||
                       l.name.toLowerCase().includes(q) || l.consumer.toLowerCase().includes(q);
            });
            if ((q || usedOnly) && !lines.length) return '';
            const collapsed = !this.expanded.has(chip.path) && !q && !usedOnly;
            const head = `<div class="gpio-chip-head" onclick='Devices.tabs.gpio.toggleChip(${esc(JSON.stringify(chip.path))})'>
                <i class="fa-solid fa-caret-${collapsed ? 'right' : 'down'} dev-caret"></i>
                <i class="fa-solid fa-plug text-ok"></i>
                <b class="mono">${esc(chip.name)}</b>
                <span class="mono muted">[${esc(chip.label)}]</span>
                <span class="small faint">${chip.lines.length} lines${base != null ? ' · base ' + base : ''} · ${esc(chip.path)}</span>
                <span class="spacer"></span>
                <span class="badge ${used ? 'badge-info' : 'badge-muted'}">${used} used</span>
            </div>`;
            if (chip.error) return `<div class="gpio-chip">${head}<div class="tbl-empty text-error">${esc(chip.error)}</div></div>`;
            if (collapsed) return `<div class="gpio-chip">${head}</div>`;

            const rows = lines.map(l => {
                const key = chip.path + ':' + l.offset;
                const changed = now - (this.changedAt[key] || 0) < Devices.HIGHLIGHT_MS;
                const flags = [l.bias !== 'as-is' && l.bias !== 'unknown' ? l.bias : '',
                               l.drive !== 'push-pull' ? l.drive : ''].filter(Boolean).join(', ');
                return `<tr class="${l.used ? 'gpio-used' : ''}${changed ? ' dev-new' : ''}${this.held[key] ? ' gpio-held' : ''}">
                    <td class="mono num">${l.offset}</td>
                    <td class="mono num faint">${base != null ? base + l.offset : ''}</td>
                    <td class="mono">${l.name ? esc(l.name) : '<span class="faint">unnamed</span>'}</td>
                    <td class="mono gpio-consumer">${l.consumer ? '"' + esc(l.consumer) + '"' : '<span class="faint">unused</span>'}</td>
                    <td><span class="badge ${l.direction === 'output' ? 'badge-info' : 'badge-muted'}">${esc(l.direction)}</span></td>
                    <td class="${l.active === 'low' ? 'text-warn' : 'muted'}">active-${esc(l.active)}</td>
                    <td class="small muted">${esc(flags)}</td>
                    <td>${this._ctlCell(chip.path, l)}</td>
                </tr>`;
            }).join('');
            return `<div class="gpio-chip">${head}
                <table class="tbl gpio-tbl">
                    <thead><tr><th class="num" style="width:50px">Line</th><th class="num" style="width:60px">GPIO #</th>
                        <th>Name</th><th>Consumer</th><th style="width:70px">Direction</th><th style="width:90px">Active</th>
                        <th>Flags</th><th style="width:190px">Control</th></tr></thead>
                    <tbody>${rows}</tbody>
                </table></div>`;
        }).join('') || '<div class="tbl-empty">Nothing matches the filter</div>';
    },

    // ── control ──

    _pollCtl() {
        App.api('/api/devices/gpio/ctl?client=' + encodeURIComponent(this.client))
            .then(state => this._applyHeld(state)).catch(() => {});
    },

    _applyHeld(state) {
        const held = {};
        (state.held || []).forEach(h => { held[h.chip + ':' + h.offset] = h; });
        const changed = JSON.stringify(held) !== JSON.stringify(this.held);
        this.held = held;
        if (changed && Devices.tab === 'gpio') this.render();
    },

    ctl(action, chip, offset, value) {
        App.api('/api/devices/gpio/ctl', { json: { client: this.client, action, chip, offset, value } })
            .then(state => {
                this._applyHeld(state);
                // Claim/release change the "used" flag of the line: reload the line list.
                if (action === 'claim' || action === 'release' || action === 'release_all') Devices.refresh();
            })
            .catch(e => toast(e.message, true));
    },

    releaseAll() {
        if (!Object.keys(this.held).length) return;
        this.held = {};
        App.api('/api/devices/gpio/ctl', { json: { client: this.client, action: 'release_all' } })
            .catch(() => {});
    },

    /** Called on page unload: fetch() may be cancelled, a beacon is not. */
    releaseOnUnload() {
        if (!Object.keys(this.held).length) return;
        const body = JSON.stringify({ client: this.client, action: 'release_all' });
        navigator.sendBeacon('/api/devices/gpio/ctl', new Blob([body], { type: 'application/json' }));
    },

    _ctlCell(chipPath, l) {
        const h = this.held[chipPath + ':' + l.offset];
        const args = (...rest) => esc([JSON.stringify(chipPath), l.offset, ...rest].join(', '));
        const call = 'Devices.tabs.gpio.ctl';
        if (!h) {
            if (l.used) return '<span class="badge badge-ok">used</span>';
            return `<button type="button" class="btn btn-ghost btn-sm gpio-claim" onclick="${call}('claim', ${args()})" title="Request this line (its state is not changed)"><i class="fa-solid fa-hand"></i> Claim</button>`;
        }
        const out = h.direction === 'output';
        const v = h.value;
        const val = h.error
            ? `<span class="text-error small" title="${esc(h.error)}">error</span>`
            : out
                ? `<button type="button" class="gpio-val v${v}" onclick="${call}('set', ${args(v ? 0 : 1)})" title="Click to set ${v ? 0 : 1}">${v}</button>`
                : `<span class="gpio-val v${v}" title="Input level">${v}</span>`;
        return `<div class="gpio-ctl">
            <div class="gpio-seg">
                <button type="button" class="${out ? '' : 'active'}" onclick="${call}('input', ${args()})">IN</button>
                <button type="button" class="${out ? 'active' : ''}" onclick="${call}('output', ${args()})" title="Switch to output keeping the current level">OUT</button>
            </div>
            ${val}
            <button type="button" class="btn-icon" onclick="${call}('release', ${args()})" title="Release line"><i class="fa-solid fa-xmark"></i></button>
        </div>`;
    },
});

window.addEventListener('pagehide', () => Devices.tabs.gpio.releaseOnUnload());
