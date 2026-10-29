/* ==========================================================================
   Devices popup tab "Network": interfaces (state, addresses, traffic rates,
   routes) and a SocketCAN tool (open with bitrate, frame trace, send, cyclic send).
   The CAN socket and cyclic transmissions live only while the CAN view is open.
   ========================================================================== */

Devices.register({
    id: 'net',
    autoMs: 2000,
    FRAMES_MS: 300,
    MAX_TRACE: 1000,
    RENDER_ROWS: 300,
    view: 'ifaces',
    data: null,
    prev: {},               // iface -> {rx, tx, time} for rate calculation
    rates: {},
    expanded: new Set(),    // interfaces with details open (collapsed by default)
    routesOpen: false,
    // CAN
    canIface: '',
    since: 0,
    trace: [],
    byId: new Map(),
    mode: 'trace',
    frTimer: null,
    jobs: [],
    counts: { rx: 0, tx: 0, err: 0 },
    lastError: null,

    onShow() {
        this.setView(this.view, true);
        if (this._bound) return;
        this._bound = true;
        ['can-id', 'can-data'].forEach(id => document.getElementById(id).addEventListener('keydown', e => {
            if (e.key === 'Enter') this.send();
        }));
        document.getElementById('ni-body').addEventListener('click', e => {
            const tr = e.target.closest('tr[data-iface]');
            if (!tr || e.target.closest('button')) return;
            const name = tr.dataset.iface;
            if (this.expanded.has(name)) this.expanded.delete(name);
            else this.expanded.add(name);
            this.renderIfaces();
        });
    },

    onHide() { this._leaveCan(); },

    setView(view, force) {
        if (view === this.view && !force) return;
        if (this.view === 'can' && view !== 'can') this._leaveCan();
        this.view = view;
        document.querySelectorAll('.net-views button').forEach(b => b.classList.toggle('active', b.dataset.view === view));
        document.querySelectorAll('#devpane-net .ud-view').forEach(v => { v.hidden = v.dataset.view !== view; });
        document.querySelectorAll('#devpane-net .ud-ctrl').forEach(c => { c.hidden = c.dataset.for !== view; });
        document.querySelectorAll('.can-modes button').forEach(b => b.classList.toggle('active', b.dataset.mode === this.mode));
        if (view === 'can' && !this.frTimer) {
            this.frTimer = setInterval(() => this._pollFrames(), this.FRAMES_MS);
        }
        this.render();
    },

    load() {
        return App.api('/api/net/interfaces').then(data => {
            data.interfaces.forEach(i => {
                const p = this.prev[i.name];
                if (p && i.time > p.time) {
                    const dt = i.time - p.time;
                    this.rates[i.name] = { rx: Math.max(0, (i.rx.bytes - p.rx) / dt),
                                           tx: Math.max(0, (i.tx.bytes - p.tx) / dt) };
                }
                this.prev[i.name] = { rx: i.rx.bytes || 0, tx: i.tx.bytes || 0, time: i.time };
            });
            this.data = data;
            this._fillCanSelect();
            const up = data.interfaces.filter(i => i.up).length;
            const can = data.interfaces.filter(i => i.can).length;
            Devices.summary(`${data.interfaces.length} interfaces · ${up} up · ${can} CAN`, this.id);
            this.render();
        });
    },

    render() {
        if (this.view === 'ifaces') this.renderIfaces();
        else { this._renderCanStatus(); this.renderFrames(true); }
    },

    // ── interfaces ─────────────────────────────────────────────────────────

    _rate(b) { return b == null ? '' : App.fmtBytes(Math.round(b)) + '/s'; },

    renderIfaces() {
        const body = document.getElementById('ni-body');
        if (!this.data) return;
        const q = document.getElementById('ni-filter').value.trim().toLowerCase();
        const list = this.data.interfaces.filter(i => !q || [i.name, i.kind, i.mac, i.driver, i.operstate,
            ...i.addrs.map(a => a.addr)].some(v => (v || '').toLowerCase().includes(q)));
        const kindIcon = { ether: 'fa-ethernet', wlan: 'fa-wifi', can: 'fa-bus', vcan: 'fa-bus',
                           loopback: 'fa-rotate', bridge: 'fa-diagram-project' };
        const rows = list.map(i => {
            const open = this.expanded.has(i.name);
            const r = this.rates[i.name] || {};
            const state = i.up ? (i.carrier ? `<span class="text-ok">UP</span>` : `<span class="text-warn">NO-CARRIER</span>`)
                               : '<span class="text-error">DOWN</span>';
            const v4 = i.addrs.filter(a => a.family === 'inet').map(a => esc(a.addr));
            const v6 = i.addrs.filter(a => a.family === 'inet6').length;
            const info = i.can
                ? `<span class="mono">${i.can.bitrate ? (i.can.bitrate / 1000) + ' kbit/s' : (i.can.configurable ? 'bitrate not set' : 'virtual')}</span>` +
                  (i.can.state ? ` · <span class="${this._canStateCls(i.can.state)}">${esc(i.can.state)}</span>` : '')
                : v4.join('<br>') + (v6 ? ` <span class="faint small">+${v6} IPv6</span>` : '');
            const canBtn = i.can ? ` <button type="button" class="btn btn-ghost btn-sm" onclick='Devices.tabs.net.openCanTool(${esc(JSON.stringify(i.name))})'><i class="fa-solid fa-bus"></i> CAN tool</button>` : '';
            let html = `<tr class="dev-row" data-iface="${esc(i.name)}">
                <td class="dev-name nowrap"><i class="fa-solid fa-caret-${open ? 'down' : 'right'} dev-caret"></i><i class="fa-solid ${kindIcon[i.kind] || 'fa-network-wired'} dev-ico"></i>${esc(i.name)}</td>
                <td class="small muted">${esc(i.kind)}</td>
                <td class="small">${state}</td>
                <td class="small">${info}${canBtn}</td>
                <td class="mono small faint">${esc(i.mac)}</td>
                <td class="mono small num">${i.can ? (i.rx.packets || 0) + ' fr' : this._rate(r.rx)}</td>
                <td class="mono small num">${i.can ? (i.tx.packets || 0) + ' fr' : this._rate(r.tx)}</td>
                <td class="small num ${(i.rx.errors || i.tx.errors) ? 'text-error' : 'faint'}">${(i.rx.errors || 0) + (i.tx.errors || 0)}</td>
            </tr>`;
            if (open) html += `<tr class="ni-detail"><td colspan="8">${this._details(i)}</td></tr>`;
            return html;
        }).join('');

        const rt = this.data.routes.map(r => `<tr>
            <td class="mono">${esc(r.dst)}</td><td class="mono">${esc(r.gateway)}</td><td class="mono">${esc(r.dev)}</td>
            <td class="small muted">${esc(r.proto)}</td><td class="mono small">${esc(r.src)}</td><td class="small num">${esc(r.metric)}</td></tr>`).join('');
        body.innerHTML = (rows
            ? `<table class="tbl dev-tbl"><thead><tr><th style="width:160px">Interface</th><th style="width:80px">Type</th>
                <th style="width:100px">State</th><th>Addresses / bus</th><th style="width:140px">MAC</th>
                <th class="num" style="width:100px">RX</th><th class="num" style="width:100px">TX</th>
                <th class="num" style="width:60px">Errors</th></tr></thead><tbody>${rows}</tbody></table>`
            : '<div class="tbl-empty">No interfaces match the filter</div>') +
            `<div class="dl-group">
                <div class="dl-group-head" onclick="Devices.tabs.net.toggleRoutes()">
                    <i class="fa-solid fa-caret-${this.routesOpen ? 'down' : 'right'} dev-caret"></i>
                    <i class="fa-solid fa-route text-ok"></i><b>Routes &amp; DNS</b>
                    <span class="badge badge-muted">${this.data.routes.length}</span>
                    <span class="faint small">DNS: ${this.data.dns.map(esc).join(', ') || '—'}</span>
                </div>
                ${this.routesOpen ? `<table class="tbl dev-tbl"><thead><tr><th>Destination</th><th>Gateway</th><th>Device</th>
                    <th>Proto</th><th>Source</th><th class="num">Metric</th></tr></thead><tbody>${rt}</tbody></table>` : ''}
            </div>`;
    },

    toggleRoutes() {
        this.routesOpen = !this.routesOpen;
        this.renderIfaces();
    },

    _details(i) {
        const kv = (k, v) => v === '' || v == null ? '' : `<tr><td class="dev-k">${esc(k)}</td><td class="mono">${v}</td></tr>`;
        const st = (s) => `${s.packets || 0} packets · ${App.fmtBytes(s.bytes || 0)} · ${s.errors || 0} errors · ${s.dropped || 0} dropped`;
        let rows = kv('Operstate', esc(i.operstate)) + kv('Flags', esc(i.flags.join(' '))) + kv('MTU', esc(i.mtu)) +
            kv('Driver', esc(i.driver)) + kv('Device', esc(i.parent)) +
            kv('Link speed', i.speed && i.speed !== '-1' ? esc(i.speed) + ' Mb/s' : '') +
            kv('Addresses', i.addrs.map(a => esc(a.addr) + ` <span class="faint">${esc(a.scope)}</span>`).join('<br>')) +
            kv('RX', esc(st(i.rx))) + kv('TX', esc(st(i.tx)));
        if (i.can) {
            const c = i.can;
            rows += kv('CAN state', esc(c.state)) + kv('Bitrate', c.bitrate ? esc(c.bitrate) : '') +
                kv('Sample point', c.sample_point ? esc(c.sample_point) : '') + kv('Restart ms', c.restart_ms != null ? esc(c.restart_ms) : '') +
                kv('Controller mode', esc((c.ctrlmode || []).join(' '))) + kv('Clock', c.clock ? esc(c.clock) + ' Hz' : '') +
                kv('Error counters', c.berr.tx != null ? `tx ${esc(c.berr.tx)} · rx ${esc(c.berr.rx)}` : '');
        }
        return `<table class="tbl dev-kv ni-kv">${rows}</table>`;
    },

    // ── CAN ────────────────────────────────────────────────────────────────

    _canStateCls(state) {
        return /BUS-OFF|STOPPED/.test(state) ? 'text-error' : /PASSIVE|WARNING/.test(state) ? 'text-warn' : 'text-ok';
    },

    canIfaces() { return this.data ? this.data.interfaces.filter(i => i.can) : []; },

    _fillCanSelect() {
        const sel = document.getElementById('can-iface');
        const list = this.canIfaces();
        const names = list.map(i => i.name).join(',');
        if (sel.dataset.names !== names) {
            sel.dataset.names = names;
            sel.innerHTML = list.length ? list.map(i => `<option value="${esc(i.name)}">${esc(i.name)} (${esc(i.kind)})</option>`).join('')
                                        : '<option value="">no CAN interfaces</option>';
            const bsel = document.getElementById('can-bitrate');
            if (!bsel.options.length) {
                bsel.innerHTML = this.data.bitrates.map(b =>
                    `<option value="${b}">${b >= 1000000 ? b / 1000000 + ' Mbit/s' : b / 1000 + ' kbit/s'}</option>`).join('');
                bsel.value = '500000';
            }
        }
        if (!this.canIface || !list.some(i => i.name === this.canIface)) {
            if (list.length) this.selectCan(list[0].name);
        } else {
            sel.value = this.canIface;
        }
    },

    openCanTool(name) {
        this.setView('can');
        this.selectCan(name);
    },

    selectCan(name) {
        if (name === this.canIface) return;
        if (this.canIface) this._stopJobs(this.canIface);
        this.canIface = name;
        document.getElementById('can-iface').value = name;
        this.since = 0;
        this.trace = [];
        this.byId = new Map();
        this.jobs = [];
        this.counts = { rx: 0, tx: 0, err: 0 };
        const i = this.canIfaces().find(x => x.name === name);
        if (i && i.can) {
            if (i.can.bitrate) document.getElementById('can-bitrate').value = String(i.can.bitrate);
            if (i.can.restart_ms != null) document.getElementById('can-restart').value = i.can.restart_ms;
            document.getElementById('can-listen').checked = (i.can.ctrlmode || []).includes('LISTEN-ONLY');
            document.querySelectorAll('#can-config select, #can-config input')
                .forEach(el => { el.disabled = !i.can.configurable; });
        }
        this.render();
    },

    _renderCanStatus() {
        const i = this.canIfaces().find(x => x.name === this.canIface);
        const badge = document.getElementById('can-state');
        const status = document.getElementById('can-status');
        if (!i) {
            badge.innerHTML = '';
            status.innerHTML = '<span class="muted">No CAN interface (can0, vcan0…) found</span>';
            return;
        }
        const c = i.can;
        badge.innerHTML = i.up
            ? `<span class="${this._canStateCls(c.state)}"><i class="fa-solid fa-circle"></i> ${esc(c.state || 'UP')}</span>`
            : '<span class="text-error"><i class="fa-solid fa-circle"></i> DOWN</span>';
        status.innerHTML = [
            c.configurable ? (c.bitrate ? `${c.bitrate / 1000} kbit/s` + (c.sample_point ? ` @ ${c.sample_point}` : '') : 'bitrate not set')
                           : 'virtual CAN (no bit timing)',
            c.berr.tx != null ? `TEC ${c.berr.tx} · REC ${c.berr.rx}` : '',
            `rx ${i.rx.packets || 0} · tx ${i.tx.packets || 0}`,
            (i.rx.errors || i.tx.errors) ? `<span class="text-error">err ${(i.rx.errors || 0) + (i.tx.errors || 0)}</span>` : '',
        ].filter(Boolean).join(' · ');
    },

    link(action) {
        const iface = this.canIface;
        if (!iface) return;
        const i = this.canIfaces().find(x => x.name === iface);
        const json = { iface, action };
        if (action === 'open' && i && i.can.configurable) {
            Object.assign(json, {
                bitrate: +document.getElementById('can-bitrate').value,
                sample_point: document.getElementById('can-sp').value.trim(),
                restart_ms: document.getElementById('can-restart').value.trim(),
                listen_only: document.getElementById('can-listen').checked,
            });
        }
        App.api('/api/net/can/link', { json })
            .then(() => { toast(`${iface} ${action === 'open' ? 'opened' : 'closed'}`); Devices.refresh(); })
            .catch(e => toast(e.message, true));
    },

    _post(json) {
        return App.api('/api/net/can/send', { json: Object.assign({ iface: this.canIface }, json) });
    },

    _form() {
        return {
            id: document.getElementById('can-id').value.trim(),
            ext: document.getElementById('can-ext').checked,
            rtr: document.getElementById('can-rtr').checked,
            data: document.getElementById('can-data').value,
        };
    },

    send() {
        if (!this.canIface) return;
        this._post(Object.assign({ action: 'send' }, this._form())).catch(e => toast(e.message, true));
    },

    startCyclic() {
        if (!this.canIface) return;
        const period_ms = +document.getElementById('can-period').value;
        this._post(Object.assign({ action: 'cyclic', period_ms }, this._form()))
            .then(() => this._pollFrames()).catch(e => toast(e.message, true));
    },

    stopJob(job) {
        this._post({ action: 'stop', job }).then(() => this._pollFrames()).catch(e => toast(e.message, true));
    },

    _stopJobs(iface) {
        if (!this.jobs.length) return;
        this.jobs = [];
        App.api('/api/net/can/send', { json: { iface, action: 'stop_all' } }).catch(() => {});
    },

    /** Leaving the CAN view: stop polling (the server closes the socket) and every cyclic send. */
    _leaveCan() {
        clearInterval(this.frTimer);
        this.frTimer = null;
        if (this.canIface) this._stopJobs(this.canIface);
    },

    releaseOnUnload() {
        if (!this.jobs.length) return;
        const body = JSON.stringify({ iface: this.canIface, action: 'stop_all' });
        navigator.sendBeacon('/api/net/can/send', new Blob([body], { type: 'application/json' }));
    },

    clearFrames() {
        this.trace = [];
        this.byId = new Map();
        this.counts = { rx: 0, tx: 0, err: 0 };
        if (this.canIface) this._post({ action: 'clear' }).catch(() => {});
        this.renderFrames(true);
    },

    setMode(mode) {
        this.mode = mode;
        document.querySelectorAll('.can-modes button').forEach(b => b.classList.toggle('active', b.dataset.mode === mode));
        this.renderFrames(true);
    },

    _pollFrames() {
        if (!this.canIface || this._polling) return;
        this._polling = true;
        const iface = this.canIface;
        App.api(`/api/net/can/frames?iface=${encodeURIComponent(iface)}&since=${this.since}`).then(d => {
            if (iface !== this.canIface) return;
            if (d.next < this.since) this.since = 0;
            d.frames.forEach(f => this._addFrame(f));
            if (d.frames.length) {
                this.since = d.next;
                this.trace = d.frames.slice().reverse().concat(this.trace).slice(0, this.MAX_TRACE);
            }
            this.lastError = d.error;
            const jobs = JSON.stringify(d.jobs);
            if (jobs !== JSON.stringify(this.jobs)) {
                this.jobs = d.jobs;
                this._renderJobs();
            }
            if (Devices.tab === 'net' && this.view === 'can') this.renderFrames(false);
        }).catch(e => { this.lastError = e.message; }).finally(() => { this._polling = false; });
    },

    _addFrame(f) {
        this.counts[f.dir] = (this.counts[f.dir] || 0) + 1;
        const key = `${f.dir}:${f.ext ? 'x' : 's'}:${f.can_id}:${f.dir === 'err' ? f.error : ''}`;
        const row = this.byId.get(key);
        if (!row) {
            this.byId.set(key, { f, count: 1, period: null, changed: 0 });
            return;
        }
        let changed = 0;
        for (let b = 0; b < f.data.length / 2; b++) {
            if (f.data.substr(b * 2, 2) !== row.f.data.substr(b * 2, 2)) changed |= 1 << b;
        }
        row.period = f.t - row.f.t;
        row.changed = changed;
        row.changedAt = changed ? Date.now() : row.changedAt;
        row.f = f;
        row.count++;
    },

    _id(f) {
        if (f.dir === 'err') return 'ERR';
        return f.can_id.toString(16).toUpperCase().padStart(f.ext ? 8 : 3, '0');
    },

    _bytes(hex, changed = 0, fresh = false) {
        const out = [];
        for (let b = 0; b < hex.length / 2; b++) {
            const byte = hex.substr(b * 2, 2).toUpperCase();
            out.push(fresh && changed & (1 << b) ? `<b class="can-chg">${byte}</b>` : byte);
        }
        return out.join(' ');
    },

    _ascii(hex) {
        let s = '';
        for (let b = 0; b < hex.length / 2; b++) {
            const c = parseInt(hex.substr(b * 2, 2), 16);
            s += c >= 32 && c < 127 ? String.fromCharCode(c) : '·';
        }
        return esc(s);
    },

    _match(f, q) {
        if (!q) return true;
        return this._id(f).toLowerCase().includes(q) || f.dir === q ||
               f.data.includes(q.replace(/\s/g, '')) || (f.error || '').toLowerCase().includes(q);
    },

    renderFrames(force) {
        const box = document.getElementById('can-frames');
        const paused = document.getElementById('can-pause').checked;
        document.getElementById('can-counts').innerHTML =
            `RX ${this.counts.rx || 0} · TX ${this.counts.tx || 0}` +
            (this.counts.err ? ` · <span class="text-error">ERR ${this.counts.err}</span>` : '') +
            (this.lastError ? ` · <span class="text-error">${esc(this.lastError)}</span>` : '') + (paused ? ' · paused' : '');
        if (paused && !force) return;
        if (!this.canIface) {
            box.innerHTML = '<div class="tbl-empty">No CAN interface. On hardware it appears as can0 when the driver/overlay is enabled.</div>';
            return;
        }
        const q = document.getElementById('can-filter').value.trim().toLowerCase();
        const dirBadge = d => `<span class="badge ${d === 'rx' ? 'badge-ok' : d === 'tx' ? 'badge-info' : 'badge-error'}">${d.toUpperCase()}</span>`;
        const flags = f => [f.ext ? 'EXT' : '', f.rtr ? 'RTR' : ''].filter(Boolean).join(' ');
        const time = t => Devices.fmtMs(t);

        if (this.mode === 'byid') {
            const rows = [...this.byId.values()].filter(r => this._match(r.f, q))
                .sort((a, b) => a.f.dir.localeCompare(b.f.dir) || a.f.can_id - b.f.can_id);
            const now = Date.now();
            box.innerHTML = rows.length ? `<table class="tbl dev-tbl can-tbl"><thead><tr>
                <th style="width:60px">Dir</th><th style="width:100px">ID</th><th style="width:70px">Flags</th><th style="width:50px">DLC</th>
                <th>Data</th><th style="width:110px">ASCII</th><th class="num" style="width:80px">Count</th>
                <th class="num" style="width:90px">Period</th><th style="width:110px">Last</th></tr></thead><tbody>` +
                rows.map(r => `<tr>
                    <td>${dirBadge(r.f.dir)}</td>
                    <td class="mono">${this._id(r.f)}</td>
                    <td class="small muted">${flags(r.f)}</td>
                    <td class="mono">${r.f.dlc}</td>
                    <td class="mono">${r.f.dir === 'err' ? '<span class="text-error">' + esc(r.f.error) + '</span> ' : ''}${this._bytes(r.f.data, r.changed, now - (r.changedAt || 0) < 1500)}</td>
                    <td class="mono faint">${this._ascii(r.f.data)}</td>
                    <td class="mono num">${r.count}</td>
                    <td class="mono num">${r.period != null ? Math.round(r.period * 1000) + ' ms' : ''}</td>
                    <td class="mono small faint">${time(r.f.t)}</td></tr>`).join('') + '</tbody></table>'
                : '<div class="tbl-empty">No frames yet</div>';
            return;
        }
        const list = this.trace.filter(f => this._match(f, q)).slice(0, this.RENDER_ROWS);
        box.innerHTML = list.length ? `<table class="tbl dev-tbl can-tbl"><thead><tr>
            <th style="width:110px">Time</th><th style="width:60px">Dir</th><th style="width:100px">ID</th>
            <th style="width:70px">Flags</th><th style="width:50px">DLC</th><th>Data</th><th style="width:110px">ASCII</th></tr></thead><tbody>` +
            list.map(f => `<tr>
                <td class="mono small">${time(f.t)}</td>
                <td>${dirBadge(f.dir)}</td>
                <td class="mono">${this._id(f)}</td>
                <td class="small muted">${flags(f)}</td>
                <td class="mono">${f.dlc}</td>
                <td class="mono">${f.dir === 'err' ? '<span class="text-error">' + esc(f.error) + '</span> ' : ''}${this._bytes(f.data)}</td>
                <td class="mono faint">${this._ascii(f.data)}</td></tr>`).join('') + '</tbody></table>'
            : `<div class="tbl-empty">${this.trace.length ? 'No frames match the filter' : 'Waiting for frames…'}</div>`;
    },

    _renderJobs() {
        const box = document.getElementById('can-jobs');
        box.hidden = !this.jobs.length;
        box.innerHTML = '<span class="small muted"><i class="fa-solid fa-repeat"></i> Repeating:</span>' + this.jobs.map(j => {
            const f = { dir: 'tx', can_id: j.can_id, ext: j.ext };
            return `<span class="can-job" title="${esc(j.last_error)}">
                <span class="mono">${this._id(f)}${j.rtr ? ' RTR' : ''} [${this._bytes(j.data) || '—'}]</span>
                <span class="faint">every ${j.period_ms} ms · sent ${j.sent}</span>
                ${j.errors ? `<span class="text-error">· ${j.errors} errors</span>` : ''}
                <button type="button" class="btn-icon" onclick="Devices.tabs.net.stopJob(${j.job})" title="Stop"><i class="fa-solid fa-stop"></i></button>
            </span>`;
        }).join('') + (this.jobs.length > 1
            ? `<button type="button" class="btn btn-ghost btn-sm" onclick="Devices.tabs.net._stopJobs(Devices.tabs.net.canIface)">Stop all</button>` : '');
    },
});

window.addEventListener('pagehide', () => Devices.tabs.net.releaseOnUnload());
