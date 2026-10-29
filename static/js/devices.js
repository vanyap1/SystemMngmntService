/* ==========================================================================
   Devices popup (partials/devices_modal.html): /dev tree with udev details
   and a GPIO line overview like `gpioinfo`. Logged-in only.
   ========================================================================== */

const Devices = {
    AUTO_MS: 2000,
    CTL_MS: 1000,           // GPIO control: value polling + lease heartbeat
    HIGHLIGHT_MS: 10000,
    // Device groups for the "All devices" selector, matched against the full path.
    GROUPS: {
        serial: n => /^\/dev\/(tty(S|USB|ACM|AMA|FIQ|GS)\d+|serial\/.+)$/.test(n.path),
        usb:    n => /^\/dev\/(bus\/usb\/.+|ttyUSB\d+|ttyACM\d+|serial\/.+)$/.test(n.path),
        video:  n => /^\/dev\/(video\d+|media\d+|v4l\/.+|dri\/.+)$/.test(n.path),
        i2c:    n => /^\/dev\/i2c-\d+$/.test(n.path),
        spi:    n => /^\/dev\/spidev/.test(n.path),
        gpio:   n => /^\/dev\/gpiochip\d+$/.test(n.path),
        block:  n => n.type === 'block' || n.path.startsWith('/dev/disk/'),
        input:  n => /^\/dev\/(input\/.+|hidraw\d+)$/.test(n.path),
        sound:  n => n.path.startsWith('/dev/snd/'),
    },
    // Paths that come and go on their own (terminals, shared memory): highlighted, no toast.
    QUIET: /^\/dev\/(pts|shm|mqueue)\//,

    tab: 'dev',
    timer: null,
    busy: false,
    tree: [],
    nodes: {},              // path -> node
    known: null,            // Set of paths from the previous refresh
    addedAt: {},            // path -> timestamp (row highlight)
    changes: [],            // recent {sign, path}
    expanded: new Set(),
    selected: null,
    gpio: null,
    gpioPrev: {},           // "chip:offset" -> JSON of the line
    gpioChangedAt: {},
    gpioCollapsed: new Set(),
    // GPIO control: lines are claimed on demand and released when the GPIO tab is left.
    client: Date.now().toString(36) + Math.random().toString(36).slice(2, 10),
    held: {},               // "chip:offset" -> {direction, value, error}
    ctlTimer: null,

    open() {
        document.getElementById('devices-overlay').classList.add('open');
        Devices.refresh();
        Devices.setAuto();
        Devices._syncCtl();
    },

    close() {
        const ov = document.getElementById('devices-overlay');
        if (!ov || !ov.classList.contains('open')) return;
        ov.classList.remove('open');
        clearInterval(Devices.timer);
        Devices.timer = null;
        Devices._syncCtl();
    },

    isOpen() {
        return document.getElementById('devices-overlay').classList.contains('open');
    },

    setTab(tab) {
        Devices.tab = tab;
        document.querySelectorAll('.dev-tab').forEach(b => b.classList.toggle('active', b.dataset.tab === tab));
        document.getElementById('dev-pane').hidden = tab !== 'dev';
        document.getElementById('gpio-pane').hidden = tab !== 'gpio';
        document.getElementById('dev-group').hidden = tab !== 'dev';
        document.getElementById('gpio-used-wrap').hidden = tab !== 'gpio';
        Devices.render();
        Devices.refresh();
        Devices._syncCtl();
    },

    setAuto() {
        clearInterval(Devices.timer);
        Devices.timer = null;
        if (document.getElementById('dev-auto').checked && Devices.isOpen()) {
            Devices.timer = setInterval(Devices.refresh, Devices.AUTO_MS);
        }
    },

    refresh() {
        if (Devices.busy) return;
        Devices.busy = true;
        const ico = document.getElementById('dev-refresh-ico');
        ico.classList.add('fa-spin');
        const req = Devices.tab === 'dev'
            ? App.api('/api/devices/dev').then(Devices._applyDev)
            : App.api('/api/devices/gpio').then(Devices._applyGpio);
        req.then(() => {
            document.getElementById('dev-updated').textContent = 'Updated ' + App.fmtTime();
        }).catch(e => {
            document.getElementById('dev-updated').innerHTML = `<span class="text-error">${esc(e.message)}</span>`;
        }).finally(() => {
            Devices.busy = false;
            ico.classList.remove('fa-spin');
        });
    },

    render() {
        if (Devices.tab === 'dev') Devices._renderDev();
        else Devices._renderGpio();
    },

    // ── /dev tree ─────────────────────────────────────────────────────────

    _applyDev(data) {
        Devices.tree = data.tree || [];
        Devices.nodes = {};
        const walk = list => list.forEach(n => {
            Devices.nodes[n.path] = n;
            if (n.children) walk(n.children);
        });
        walk(Devices.tree);

        const now = Date.now();
        const current = new Set(Object.keys(Devices.nodes));
        if (Devices.known) {
            const added = [...current].filter(p => !Devices.known.has(p));
            const removed = [...Devices.known].filter(p => !current.has(p));
            added.forEach(p => { Devices.addedAt[p] = now; });
            Devices._logChanges(added, removed);
        }
        Devices.known = current;

        const counts = { char: 0, block: 0, link: 0, dir: 0 };
        Object.values(Devices.nodes).forEach(n => { if (n.type in counts) counts[n.type]++; });
        document.getElementById('dev-summary').textContent =
            `${data.count} entries · ${counts.char} char · ${counts.block} block · ` +
            `${counts.link} links · ${counts.dir} dirs` + (data.truncated ? ' · list truncated' : '');
        Devices._renderDev();
    },

    _logChanges(added, removed) {
        const items = added.map(p => ({ sign: '+', path: p })).concat(removed.map(p => ({ sign: '−', path: p })));
        if (!items.length) return;
        Devices.changes = items.concat(Devices.changes).slice(0, 4);
        document.getElementById('dev-changes').innerHTML = Devices.changes.map(c =>
            `<span class="${c.sign === '+' ? 'text-ok' : 'text-error'}">${c.sign}${esc(c.path)}</span>`).join(' ');

        const loud = items.filter(c => !Devices.QUIET.test(c.path));
        if (loud.length === 1) {
            toast((loud[0].sign === '+' ? 'Device added: ' : 'Device removed: ') + loud[0].path, loud[0].sign !== '+');
        } else if (loud.length > 1) {
            toast(`Devices changed: +${added.length} / −${removed.length}`);
        }
    },

    _match(n, q, group) {
        if (group && !Devices.GROUPS[group](n)) return false;
        if (!q) return true;
        return n.path.toLowerCase().includes(q) || (n.target || '').toLowerCase().includes(q) ||
               (n.dev || '') === q;
    },

    /** Flatten the tree into [node, depth, open] rows honouring filter and expanded dirs. */
    _rows(nodes, depth, q, group, out) {
        const filtering = q || group;
        for (const n of nodes) {
            const isDir = n.type === 'dir';
            if (!filtering) {
                const open = isDir && Devices.expanded.has(n.path);
                out.push([n, depth, open]);
                if (open) Devices._rows(n.children, depth + 1, q, group, out);
                continue;
            }
            const self = Devices._match(n, q, group);
            // A matching directory shows its whole subtree; otherwise only matching descendants.
            const sub = isDir ? Devices._rows(n.children, depth + 1, self ? '' : q, self ? '' : group, []) : [];
            if (self || sub.length) {
                out.push([n, depth, isDir]);
                out.push(...sub);
            }
        }
        return out;
    },

    _icon(n) {
        if (n.type === 'dir') return 'fa-folder';
        if (n.type === 'link') return 'fa-link';
        if (n.type === 'block') return 'fa-hard-drive';
        if (n.type === 'socket') return 'fa-network-wired';
        if (n.type === 'fifo') return 'fa-right-left';
        if (n.type !== 'char') return 'fa-file';
        const name = n.name;
        if (/^tty/.test(name)) return 'fa-terminal';
        if (/^(video|media)/.test(name)) return 'fa-video';
        if (/^gpiochip/.test(name)) return 'fa-plug';
        if (/^(i2c|spidev)/.test(name)) return 'fa-microchip';
        if (/^(hidraw|event|mouse|mice|js)/.test(name)) return 'fa-keyboard';
        if (n.path.startsWith('/dev/snd/')) return 'fa-volume-high';
        return 'fa-cube';
    },

    _renderDev() {
        const tbody = document.getElementById('dev-tbody');
        if (!Devices.known) return;
        const q = document.getElementById('dev-filter').value.trim().toLowerCase();
        const group = document.getElementById('dev-group').value;
        const rows = Devices._rows(Devices.tree, 0, q, group, []);
        if (!rows.length) {
            tbody.innerHTML = '<tr><td colspan="5" class="tbl-empty">Nothing matches the filter</td></tr>';
            return;
        }
        const now = Date.now();
        tbody.innerHTML = rows.map(([n, depth, open]) => {
            const isDir = n.type === 'dir';
            const fresh = now - (Devices.addedAt[n.path] || 0) < Devices.HIGHLIGHT_MS;
            const cls = ['dev-row', 'dev-' + n.type, fresh ? 'dev-new' : '',
                         n.path === Devices.selected ? 'sel' : ''].join(' ');
            const caret = isDir
                ? `<i class="fa-solid fa-caret-${open ? 'down' : 'right'} dev-caret"></i>`
                : '<span class="dev-caret"></span>';
            const icon = isDir && open ? 'fa-folder-open' : Devices._icon(n);
            const target = n.type === 'link'
                ? ` <span class="dev-target${n.broken ? ' text-error' : ''}">→ ${esc(n.target)}</span>` : '';
            const count = isDir ? ` <span class="faint small">(${n.children.length})</span>` : '';
            return `<tr class="${cls}" data-path="${esc(n.path)}">
                <td class="dev-name" style="padding-left:${10 + depth * 18}px">${caret}<i class="fa-solid ${icon} dev-ico"></i>${esc(n.name)}${count}${target}</td>
                <td><span class="dev-type">${esc(n.type)}</span></td>
                <td class="mono">${esc(n.dev || '')}</td>
                <td class="mono faint">${esc(n.mode)}</td>
                <td class="small muted">${esc(n.owner)}:${esc(n.group)}</td>
            </tr>`;
        }).join('');
    },

    _onRowClick(e) {
        const tr = e.target.closest('tr[data-path]');
        if (!tr) return;
        const n = Devices.nodes[tr.dataset.path];
        if (!n) return;
        if (n.type === 'dir') {
            if (document.getElementById('dev-filter').value || document.getElementById('dev-group').value) return;
            if (Devices.expanded.has(n.path)) Devices.expanded.delete(n.path);
            else Devices.expanded.add(n.path);
            Devices._renderDev();
            return;
        }
        Devices.selected = n.path;
        Devices._renderDev();
        Devices.showInfo(n);
    },

    showInfo(n) {
        const box = document.getElementById('dev-info');
        box.hidden = false;
        const head = `<div class="dev-info-head">
            <i class="fa-solid ${Devices._icon(n)} text-ok"></i>
            <span class="mono">${esc(n.path)}</span>
            <span class="spacer"></span>
            <button type="button" class="modal-close" onclick="Devices.hideInfo()" title="Close details">&#215;</button>
        </div>`;
        box.innerHTML = head + '<div class="tbl-empty">Loading…</div>';
        App.api('/api/devices/dev/info?path=' + encodeURIComponent(n.path)).then(info => {
            if (Devices.selected !== n.path) return;
            const kv = (k, v) => `<tr><td class="dev-k">${esc(k)}</td><td class="mono">${v}</td></tr>`;
            let rows = kv('Type', esc(n.type) + (n.dev ? ' ' + esc(n.dev) : '')) +
                       kv('Mode', esc(`${n.mode} ${n.owner}:${n.group}`));
            if (info.real !== n.path) rows += kv('Resolves to', esc(info.real));
            if (info.devpath) rows += kv('Sysfs', esc('/sys' + info.devpath));
            if (info.symlinks.length) rows += kv('Symlinks', info.symlinks.map(esc).join('<br>'));
            const props = Object.entries(info.props).map(([k, v]) => kv(k, esc(v))).join('');
            box.innerHTML = head +
                `<table class="tbl dev-kv">${rows}</table>` +
                (props ? `<div class="dev-info-sub">udev properties</div><table class="tbl dev-kv">${props}</table>`
                       : `<div class="tbl-empty">${esc(info.error || 'No udev properties')}</div>`);
        }).catch(e => {
            box.innerHTML = head + `<div class="tbl-empty text-error">${esc(e.message)}</div>`;
        });
    },

    hideInfo() {
        Devices.selected = null;
        document.getElementById('dev-info').hidden = true;
        Devices._renderDev();
    },

    // ── GPIO ──────────────────────────────────────────────────────────────

    _applyGpio(data) {
        const now = Date.now();
        const first = !Devices.gpio;
        (data.chips || []).forEach(chip => chip.lines.forEach(l => {
            const key = chip.path + ':' + l.offset;
            const json = JSON.stringify(l);
            if (!first && Devices.gpioPrev[key] !== undefined && Devices.gpioPrev[key] !== json) {
                Devices.gpioChangedAt[key] = now;
            }
            Devices.gpioPrev[key] = json;
        }));
        Devices.gpio = data;

        const chips = data.chips || [];
        const lines = chips.reduce((s, c) => s + c.lines.length, 0);
        const used = chips.reduce((s, c) => s + c.lines.filter(l => l.used).length, 0);
        document.getElementById('dev-summary').textContent =
            `${chips.length} chips · ${lines} lines · ${used} used`;
        Devices._renderGpio();
    },

    toggleChip(path) {
        if (Devices.gpioCollapsed.has(path)) Devices.gpioCollapsed.delete(path);
        else Devices.gpioCollapsed.add(path);
        Devices._renderGpio();
    },

    _renderGpio() {
        const pane = document.getElementById('gpio-pane');
        const data = Devices.gpio;
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
        const q = document.getElementById('dev-filter').value.trim().toLowerCase();
        const usedOnly = document.getElementById('gpio-used-only').checked;
        const now = Date.now();

        pane.innerHTML = Devices._ctlBar() + (data.chips.map(chip => {
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
            const collapsed = Devices.gpioCollapsed.has(chip.path) && !q;
            const head = `<div class="gpio-chip-head" onclick='Devices.toggleChip(${esc(JSON.stringify(chip.path))})'>
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
                const changed = now - (Devices.gpioChangedAt[chip.path + ':' + l.offset] || 0) < Devices.HIGHLIGHT_MS;
                const flags = [l.bias !== 'as-is' && l.bias !== 'unknown' ? l.bias : '',
                               l.drive !== 'push-pull' ? l.drive : ''].filter(Boolean).join(', ');
                return `<tr class="${l.used ? 'gpio-used' : ''}${changed ? ' dev-new' : ''}${Devices.held[chip.path + ':' + l.offset] ? ' gpio-held' : ''}">
                    <td class="mono num">${l.offset}</td>
                    <td class="mono num faint">${base != null ? base + l.offset : ''}</td>
                    <td class="mono">${l.name ? esc(l.name) : '<span class="faint">unnamed</span>'}</td>
                    <td class="mono gpio-consumer">${l.consumer ? '"' + esc(l.consumer) + '"' : '<span class="faint">unused</span>'}</td>
                    <td><span class="badge ${l.direction === 'output' ? 'badge-info' : 'badge-muted'}">${esc(l.direction)}</span></td>
                    <td class="${l.active === 'low' ? 'text-warn' : 'muted'}">active-${esc(l.active)}</td>
                    <td class="small muted">${esc(flags)}</td>
                    <td>${Devices._ctlCell(chip.path, l)}</td>
                </tr>`;
            }).join('');
            return `<div class="gpio-chip">${head}
                <table class="tbl gpio-tbl">
                    <thead><tr><th class="num" style="width:50px">Line</th><th class="num" style="width:60px">GPIO #</th>
                        <th>Name</th><th>Consumer</th><th style="width:70px">Direction</th><th style="width:90px">Active</th>
                        <th>Flags</th><th style="width:190px">Control</th></tr></thead>
                    <tbody>${rows}</tbody>
                </table></div>`;
        }).join('') || '<div class="tbl-empty">Nothing matches the filter</div>');
    },

    // ── GPIO control ──────────────────────────────────────────────────────

    /** Poll held lines only while the GPIO tab is visible; otherwise release everything. */
    _syncCtl() {
        const active = Devices.isOpen() && Devices.tab === 'gpio';
        if (active && !Devices.ctlTimer) {
            Devices.ctlTimer = setInterval(Devices._pollCtl, Devices.CTL_MS);
            Devices._pollCtl();
        } else if (!active && Devices.ctlTimer) {
            clearInterval(Devices.ctlTimer);
            Devices.ctlTimer = null;
            Devices.releaseAll();
        }
    },

    _pollCtl() {
        App.api('/api/devices/gpio/ctl?client=' + encodeURIComponent(Devices.client))
            .then(Devices._applyHeld).catch(() => {});
    },

    _applyHeld(state) {
        const held = {};
        (state.held || []).forEach(h => { held[h.chip + ':' + h.offset] = h; });
        const changed = JSON.stringify(held) !== JSON.stringify(Devices.held);
        Devices.held = held;
        if (changed && Devices.tab === 'gpio') Devices._renderGpio();
    },

    ctl(action, chip, offset, value) {
        App.api('/api/devices/gpio/ctl', { json: { client: Devices.client, action, chip, offset, value } })
            .then(state => {
                Devices._applyHeld(state);
                // Claim/release change the "used" flag of the line: reload the line list.
                if (action === 'claim' || action === 'release' || action === 'release_all') Devices.refresh();
            })
            .catch(e => toast(e.message, true));
    },

    releaseAll() {
        if (!Object.keys(Devices.held).length) return;
        Devices.held = {};
        App.api('/api/devices/gpio/ctl', { json: { client: Devices.client, action: 'release_all' } })
            .catch(() => {});
    },

    /** Called on page unload: fetch() may be cancelled, a beacon is not. */
    releaseOnUnload() {
        if (!Object.keys(Devices.held).length) return;
        const body = JSON.stringify({ client: Devices.client, action: 'release_all' });
        navigator.sendBeacon('/api/devices/gpio/ctl', new Blob([body], { type: 'application/json' }));
    },

    _ctlBar() {
        const n = Object.keys(Devices.held).length;
        return `<div class="gpio-ctl-bar">
            <i class="fa-solid fa-circle-info"></i>
            <span>Claimed lines are held only while this tab is open — leaving the tab, closing the popup or the page releases them.
                Lines used by the kernel or other programs cannot be claimed.</span>
            <span class="spacer"></span>
            <span class="badge ${n ? 'badge-info' : 'badge-muted'}">${n} claimed</span>
            ${n ? `<button type="button" class="btn btn-ghost btn-sm" onclick="Devices.ctl('release_all')"><i class="fa-solid fa-hand-sparkles"></i> Release all</button>` : ''}
        </div>`;
    },

    _ctlCell(chipPath, l) {
        const h = Devices.held[chipPath + ':' + l.offset];
        const args = (...rest) => esc([JSON.stringify(chipPath), l.offset, ...rest].join(', '));
        if (!h) {
            if (l.used) return '<span class="badge badge-ok">used</span>';
            return `<button type="button" class="btn btn-ghost btn-sm gpio-claim" onclick="Devices.ctl('claim', ${args()})" title="Request this line (its state is not changed)"><i class="fa-solid fa-hand"></i> Claim</button>`;
        }
        const out = h.direction === 'output';
        const v = h.value;
        const val = h.error
            ? `<span class="text-error small" title="${esc(h.error)}">error</span>`
            : out
                ? `<button type="button" class="gpio-val v${v}" onclick="Devices.ctl('set', ${args(v ? 0 : 1)})" title="Click to set ${v ? 0 : 1}">${v}</button>`
                : `<span class="gpio-val v${v}" title="Input level">${v}</span>`;
        return `<div class="gpio-ctl">
            <div class="gpio-seg">
                <button type="button" class="${out ? '' : 'active'}" onclick="Devices.ctl('input', ${args()})">IN</button>
                <button type="button" class="${out ? 'active' : ''}" onclick="Devices.ctl('output', ${args()})" title="Switch to output keeping the current level">OUT</button>
            </div>
            ${val}
            <button type="button" class="btn-icon" onclick="Devices.ctl('release', ${args()})" title="Release line"><i class="fa-solid fa-xmark"></i></button>
        </div>`;
    },
};

document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('dev-tbody').addEventListener('click', Devices._onRowClick);
});
App.onEscape(() => Devices.close());
window.addEventListener('pagehide', Devices.releaseOnUnload);
