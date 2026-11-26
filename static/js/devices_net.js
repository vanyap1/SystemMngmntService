/* ==========================================================================
   HW Utils tab "Network": interfaces (state, addresses, traffic rates, routes).
   CAN interfaces get a "CAN tool" button that opens the CAN tab (devices_can.js).
   ========================================================================== */

Devices.register({
    id: 'net',
    autoMs: 2000,
    data: null,
    prev: {},               // iface -> {rx, tx, time} for rate calculation
    rates: {},
    expanded: new Set(),    // interfaces with details open (collapsed by default)
    routesOpen: false,

    onShow() {
        if (this._bound) return;
        this._bound = true;
        document.getElementById('ni-body').addEventListener('click', e => {
            const tr = e.target.closest('tr[data-iface]');
            if (!tr || e.target.closest('button')) return;
            const name = tr.dataset.iface;
            if (this.expanded.has(name)) this.expanded.delete(name);
            else this.expanded.add(name);
            this.renderIfaces();
        });
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
            const up = data.interfaces.filter(i => i.up).length;
            const can = data.interfaces.filter(i => i.can).length;
            Devices.summary(`${data.interfaces.length} interfaces · ${up} up · ${can} CAN`, this.id);
            this.render();
        });
    },

    render() { this.renderIfaces(); },

    _canStateCls(state) {
        return /BUS-OFF|STOPPED/.test(state) ? 'text-error' : /PASSIVE|WARNING/.test(state) ? 'text-warn' : 'text-ok';
    },

    openCanTool(name) {
        Devices.tabs.can.want = name;
        Devices.setTab('can');
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
});
