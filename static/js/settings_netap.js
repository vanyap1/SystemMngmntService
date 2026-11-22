/* ==========================================================================
   Settings → Network → Access point & DHCP (routes/netcfg.py /api/netcfg/ap*, core/netap.py):
   Wi-Fi client ↔ access point switch, AP settings, DHCP pool, connected clients and MAC → IP reservations.
   Mode switches and AP / pool saves come back pending — handed to NetCfg.track() (shared confirm / rollback box).
   ========================================================================== */

const NetAP = {
    data: null,
    _shown: false,
    _timer: null,
    _resEdit: -1,

    $(id) { return document.getElementById(id); },

    visible(on) {
        this._shown = on;
        clearInterval(this._timer);
        if (!on) return;
        this.load();
        this._timer = setInterval(() => {
            if (this.data && this.data.active && this.$('ap-cl-live').checked) this.loadClients();
        }, 5000);
    },

    load() {
        return App.api('/api/netcfg/ap').then(d => { this.data = d; this.render(); })
            .catch(e => { this.$('ap-mode').innerHTML = `<div class="text-error">✗ ${esc(e.message)}</div>`; });
    },

    loadClients() {
        return App.api('/api/netcfg/ap/clients').then(r => { this.data.clients = r.clients; this.renderClients(); }).catch(() => {});
    },

    render() {
        this.renderWarn();
        this.renderMode();
        this.renderForm();
        this.renderClients();
        this.renderRes();
    },

    // ── IPv4 helpers ───────────────────────────────────────────

    _n(ip) {
        const p = String(ip).trim().split('.');
        if (p.length !== 4 || p.some(x => !/^\d{1,3}$/.test(x) || +x > 255)) return null;
        return ((+p[0] << 24) >>> 0) + (+p[1] << 16) + (+p[2] << 8) + +p[3];
    },
    _s(n) { return [n >>> 24, (n >>> 16) & 255, (n >>> 8) & 255, n & 255].join('.'); },
    _net(addr, prefix) {
        const a = this._n(addr), p = +prefix;
        if (a === null || !(p >= 8 && p <= 30)) return null;
        const mask = (0xffffffff << (32 - p)) >>> 0, base = (a & mask) >>> 0;
        return { base, bcast: (base | (~mask >>> 0)) >>> 0, addr: a };
    },

    // ── Warnings + mode ────────────────────────────────────────

    renderWarn() {
        const d = this.data, w = [];
        if (!d.dnsmasq) w.push(['danger', 'fa-circle-xmark', '<b>dnsmasq-base</b> is not installed — the access point cannot hand out addresses. Install it: <code>sudo ./install-network.sh</code> (or the <i>network</i> item of <code>sudo ./install.sh</code>).']);
        if (!d.nm_ok) w.push(['warn', 'fa-triangle-exclamation', `NetworkManager ${esc(d.nm_version || '?')}: the pool range and lease time need 1.42 or newer (older versions use 10.x.x.10 – .254 and 1 h).`]);
        if (!d.wifi_devices.length) w.push(['warn', 'fa-wifi', 'No Wi-Fi adapter found (NetworkManager sees none). Plug one in and press refresh.']);
        d.wifi_devices.filter(x => x.ap_capable === false).forEach(x => w.push(['warn', 'fa-triangle-exclamation', `<b class="mono">${esc(x.device)}</b> does not support access point mode (iw: no "AP" in its interface modes).`]));
        if (!d.stations) w.push(['info', 'fa-circle-info', '<code>iw</code> is not installed — the client list has no signal / association details (install with <code>sudo ./install-network.sh</code>).']);
        this.$('ap-warn').innerHTML = w.map(([k, i, t]) => `<div class="ap-alert ${k}"><i class="fa-solid ${i}"></i><span>${t}</span></div>`).join('');
    },

    _ifname() {
        const sel = this.$('ap-f-if');
        return (sel && sel.value) || this.data.settings.ifname || (this.data.wifi_devices[0] || {}).device || '';
    },

    renderMode() {
        const d = this.data, s = d.settings;
        const box = this.$('ap-mode');
        if (!d.wifi_devices.length) { box.innerHTML = '<div class="muted">No Wi-Fi adapter.</div>'; this.$('ap-mode-meta').textContent = ''; return; }
        const ifn = this._ifname();
        const dev = d.wifi_devices.find(x => x.device === ifn) || d.wifi_devices[0];
        const mode = dev.mode === 'ap' ? 'ap' : dev.mode === 'starting' ? 'ap' : 'client';
        const you = d.client_device === dev.device;
        const st = dev.mode === 'ap'
            ? `<i class="fa-solid fa-tower-broadcast text-ok"></i> Access point <b>${esc(s.ssid)}</b> at <b class="mono">${esc(s.address)}</b> · ${d.clients.filter(c => c.online).length} client(s)`
            : dev.mode === 'starting' ? `<i class="fa-solid fa-hourglass-half text-warn"></i> Access point starting… (${esc(dev.state)})`
            : dev.connected ? `<i class="fa-solid fa-wifi text-ok"></i> Client of <b>${esc(dev.connection)}</b> · <span class="mono">${esc(dev.ip4.join(', ') || '—')}</span>`
            : `<i class="fa-solid fa-wifi muted"></i> <span class="muted">${esc(dev.state)}</span>`;
        this.$('ap-mode-meta').innerHTML = `adapter <b class="mono">${esc(dev.device)}</b>${d.wifi_enabled === false ? ' · <span class="text-warn">radio off</span>' : ''}`;
        const nets = d.client_networks.map(c => `<option value="${esc(c.uuid)}">${esc(c.name)}</option>`).join('');
        box.innerHTML = `
            <div class="ap-mode-row">
                <div class="ap-seg" role="group">
                    <button type="button" class="${mode === 'client' ? 'on' : ''}" onclick="NetAP.switchMode('client')"><i class="fa-solid fa-wifi"></i> Client</button>
                    <button type="button" class="${mode === 'ap' ? 'on' : ''}" onclick="NetAP.switchMode('ap')"><i class="fa-solid fa-tower-broadcast"></i> Access point</button>
                </div>
                <div class="ap-state">${st}${you ? ' <span class="badge badge-info" title="This page reaches the panel through this adapter">you are here</span>' : ''}</div>
                <span class="spacer"></span>
                ${dev.mode === 'ap' ? '<button class="btn btn-ghost btn-sm" type="button" onclick="NetAP.restart()" title="Restart the access point (clients reconnect)"><i class="fa-solid fa-rotate"></i> Restart AP</button>' : ''}
            </div>
            <div class="field-row ap-client-opts">
                <div class="field"><label>In client mode connect to</label>
                    <select class="input" id="ap-m-net"><option value="">best known network in range (automatic)</option>${nets}</select>
                    <span class="hint">Saved Wi-Fi networks — add new ones in <a href="#network-conn">Interfaces &amp; Wi-Fi</a></span></div>
                <div class="hint ap-mode-hint">Access point mode uses the settings below (unsaved edits included) and starts again after a reboot;
                    client mode stops it and lets NetworkManager join a saved network.</div>
            </div>`;
    },

    switchMode(mode) {
        const d = this.data;
        const ifn = this._ifname();
        const you = d.client_device === ifn;
        let body = { mode, ifname: ifn }, newAddr = '';
        if (mode === 'ap') {
            const f = this._formValues();
            if (f.error) return toast(f.error, true);
            body.settings = f.settings;
            if (f.password) body.password = f.password;
            if (!d.settings.has_password && f.settings.security !== 'none' && !f.password) return toast('Set the access point password first', true);
            if (you && !confirm(`You reach the panel through ${ifn}. It leaves its Wi-Fi network and becomes the access point "${f.settings.ssid}".\n\nJoin that network and open http://${f.settings.address}/ within the rollback time and press Keep there — otherwise the client connection comes back.`)) return;
            if (you) newAddr = f.settings.address;
        } else {
            body.uuid = (this.$('ap-m-net') || {}).value || '';
            if (you && !confirm(`You reach the panel through the access point on ${ifn}. Switching to client mode disconnects you.\n\nIf the page cannot reach the panel afterwards, the access point comes back after the rollback time.`)) return;
        }
        App.api('/api/netcfg/ap/mode', { json: body }).then(p => {
            NetCfg.track(p, newAddr);
            if (p.result && p.result.note) toast(p.result.note);
            setTimeout(() => this.load(), 2500);
        }).catch(e => { toast(e.message, true); this.load(); });
    },

    restart() {
        if (!confirm('Restart the access point? Connected clients drop and reconnect.')) return;
        App.api('/api/netcfg/ap/restart', { json: {} }).then(p => { NetCfg.track(p); setTimeout(() => this.load(), 2500); })
            .catch(e => toast(e.message, true));
    },

    // ── AP + DHCP form ─────────────────────────────────────────

    renderForm() {
        const d = this.data, s = d.settings;
        const opt = (list, cur) => list.map(([v, l]) => `<option value="${esc(String(v))}"${String(v) === String(cur) ? ' selected' : ''}>${esc(l)}</option>`).join('');
        const devs = d.wifi_devices.map(x => [x.device, x.device + (x.ap_capable === false ? ' (no AP mode)' : '')]);
        if (s.ifname && !devs.some(x => x[0] === s.ifname)) devs.unshift([s.ifname, s.ifname + ' (not present)']);
        this.$('ap-form').innerHTML = `
            <div class="field-row">
                <div class="field"><label>Network name (SSID)</label><input class="input mono" id="ap-f-ssid" maxlength="32" value="${esc(s.ssid)}"></div>
                <div class="field"><label>Adapter</label><select class="input" id="ap-f-if" onchange="NetAP.renderMode()">${opt(devs, s.ifname || (devs[0] || [])[0])}</select></div>
            </div>
            <div class="field-row">
                <div class="field"><label>Security</label><select class="input" id="ap-f-sec" onchange="NetAP._sec()">${opt([['wpa-psk', 'WPA2 (password)'], ['none', 'Open (no password)']], s.security)}</select></div>
                <div class="field ap-psk"><label>Password</label><input class="input" type="password" id="ap-f-psk" autocomplete="new-password"
                    placeholder="${s.has_password ? 'saved — leave empty to keep' : '8–63 characters'}">
                    <label class="check-row small"><input type="checkbox" onchange="NetAP.$('ap-f-psk').type = this.checked ? 'text' : 'password'"> show</label></div>
            </div>
            <div class="field-row">
                <div class="field"><label>Band</label><select class="input" id="ap-f-band" onchange="NetAP._chan()">${opt(Object.entries(d.bands), s.band)}</select></div>
                <div class="field"><label>Channel</label><select class="input" id="ap-f-ch"></select></div>
            </div>
            <label class="check-row"><input type="checkbox" id="ap-f-hidden"${s.hidden ? ' checked' : ''}> Hidden network (SSID not broadcast)</label>`;
        const lease = [[600, '10 minutes'], [3600, '1 hour'], [43200, '12 hours'], [86400, '1 day'], [604800, '7 days']];
        if (!lease.some(x => x[0] === s.lease)) lease.push([s.lease, s.lease + ' s']);
        this.$('ap-dhcp').innerHTML = `
            <div class="field-row">
                <div class="field"><label>Access point address</label><input class="input mono" id="ap-f-addr" value="${esc(s.address)}" onchange="NetAP._fitPool()">
                    <span class="hint">The panel is reachable at this address from the AP's clients; it is also their gateway and DNS</span></div>
                <div class="field"><label>Prefix</label><select class="input mono" id="ap-f-prefix" onchange="NetAP._fitPool()">${opt([16, 20, 22, 23, 24, 25, 26, 27, 28].concat([s.prefix]).filter((v, i, a) => a.indexOf(v) === i).sort((a, b) => a - b).map(p => [p, '/' + p + ' — ' + this._mask(p)]), s.prefix)}</select></div>
            </div>
            <div class="field-row">
                <div class="field"><label>Pool start</label><input class="input mono" id="ap-f-start" value="${esc(s.start)}"></div>
                <div class="field"><label>Pool end</label><input class="input mono" id="ap-f-end" value="${esc(s.end)}"></div>
            </div>
            <div class="field-row">
                <div class="field"><label>Lease time</label><select class="input" id="ap-f-lease">${opt(lease, s.lease)}</select></div>
                <div class="field"><label>&nbsp;</label><button class="btn btn-ghost" type="button" onclick="NetAP.defaults()"><i class="fa-solid fa-rotate-left"></i> Default 10.10.10.1 · .2 – .254</button></div>
            </div>
            <div class="hint" id="ap-pool-info"></div>`;
        this._chan(s.channel);
        this._sec();
        ['ap-form', 'ap-dhcp'].forEach(id => {
            this.$(id).oninput = () => this._dirty();
            this.$(id).onchange = () => this._dirty();
        });
        this._dirty();
    },

    _mask(p) { return this._s((0xffffffff << (32 - p)) >>> 0); },

    _chan(cur) {
        const band = this.$('ap-f-band').value, sel = this.$('ap-f-ch');
        const keep = cur !== undefined ? cur : +sel.value;
        const list = this.data.channels[band] || [];
        sel.innerHTML = '<option value="0">automatic</option>' + list.map(c => `<option value="${c}"${c === keep ? ' selected' : ''}>${c}</option>`).join('');
    },

    _sec() { this.$('ap-form').querySelector('.ap-psk').hidden = this.$('ap-f-sec').value === 'none'; },

    /** Address / prefix changed: move the pool into the new network when it no longer fits. */
    _fitPool() {
        const n = this._net(this.$('ap-f-addr').value, this.$('ap-f-prefix').value);
        if (!n) return this._dirty();
        const st = this._n(this.$('ap-f-start').value), en = this._n(this.$('ap-f-end').value);
        const inside = x => x !== null && x > n.base && x < n.bcast;
        if (!inside(st) || !inside(en) || (st <= n.addr && n.addr <= en)) {
            let a = n.base + 1, b = n.bcast - 1;
            if (n.addr === a) a++; else if (n.addr === b) b--; else if (n.addr > a && n.addr < b) a = n.addr + 1;
            this.$('ap-f-start').value = this._s(a);
            this.$('ap-f-end').value = this._s(b);
        }
        this._dirty();
    },

    defaults() {
        this.$('ap-f-addr').value = '10.10.10.1';
        this.$('ap-f-prefix').value = '24';
        this.$('ap-f-start').value = '10.10.10.2';
        this.$('ap-f-end').value = '10.10.10.254';
        this._dirty();
    },

    _formValues() {
        const v = id => (this.$(id) || {}).value || '';
        const settings = {
            ssid: v('ap-f-ssid').trim(), ifname: v('ap-f-if'), security: v('ap-f-sec'), band: v('ap-f-band'),
            channel: parseInt(v('ap-f-ch'), 10) || 0, hidden: this.$('ap-f-hidden').checked,
            address: v('ap-f-addr').trim(), prefix: parseInt(v('ap-f-prefix'), 10), start: v('ap-f-start').trim(),
            end: v('ap-f-end').trim(), lease: parseInt(v('ap-f-lease'), 10),
        };
        const password = settings.security === 'none' ? '' : v('ap-f-psk');
        let error = '';
        if (!settings.ssid) error = 'SSID is empty';
        else if (password && (password.length < 8 || password.length > 64)) error = 'Wi-Fi password: 8–63 characters';
        return { settings, password, error };
    },

    _dirty() {
        if (!this.data) return;
        const s = this.data.settings, f = this._formValues();
        const keys = Object.keys(f.settings).filter(k => String(f.settings[k]) !== String(s[k]));
        const changed = keys.length > 0 || !!f.password || !s.configured;
        this.$('ap-dirty').innerHTML = !s.configured ? 'Not saved yet — defaults shown'
            : changed ? `<span class="text-warn">Unsaved changes</span>${this.data.active ? ' — saving restarts the access point' : ''}` : 'Saved';
        this.$('ap-save').disabled = !changed;
        const n = this._net(f.settings.address, f.settings.prefix), a = this._n(f.settings.start), b = this._n(f.settings.end);
        const info = this.$('ap-pool-info');
        if (!n || a === null || b === null) { info.innerHTML = '<span class="text-error">Invalid address</span>'; return; }
        const bad = a > b ? 'start is after the end' : (a <= n.base || b >= n.bcast) ? 'outside the network ' + this._s(n.base) + '/' + f.settings.prefix
            : (a <= n.addr && n.addr <= b) ? 'contains the access point address' : '';
        info.innerHTML = bad ? `<span class="text-error">Pool ${esc(bad)}</span>`
            : `Network <span class="mono">${this._s(n.base)}/${f.settings.prefix}</span> · pool of <b>${b - a + 1}</b> addresses · broadcast <span class="mono">${this._s(n.bcast)}</span>`;
    },

    save() {
        const f = this._formValues();
        if (f.error) return toast(f.error, true);
        const d = this.data;
        const you = d.active && d.client_device === d.settings.ifname;
        const moved = f.settings.address !== d.settings.address;
        if (you && !confirm('You are connected through this access point; it restarts with the new settings and your device has to reconnect.' +
            (moved ? `\n\nThe panel moves to http://${f.settings.address}/ — open it and press Keep there within the rollback time.` : ''))) return;
        const body = { settings: f.settings };
        if (f.password) body.password = f.password;
        App.api('/api/netcfg/ap', { json: body }).then(p => {
            if (p.path) NetCfg.track(p, you && moved ? f.settings.address : '');
            else toast(d.active ? 'Saved' : 'Access point settings saved — switch to Access point mode to start it');
            setTimeout(() => this.load(), p.path ? 2500 : 0);
        }).catch(e => toast(e.message, true));
    },

    // ── Clients ────────────────────────────────────────────────

    _dur(s) {
        if (s === null || s === undefined) return '—';
        if (s < 60) return s + ' s';
        if (s < 3600) return Math.floor(s / 60) + ' min';
        if (s < 86400) return Math.floor(s / 3600) + ' h ' + Math.floor(s % 3600 / 60) + ' min';
        return Math.floor(s / 86400) + ' d ' + Math.floor(s % 86400 / 3600) + ' h';
    },

    _sig(dbm) {
        if (dbm === null || dbm === undefined) return '<span class="muted">—</span>';
        const pct = Math.max(0, Math.min(100, 2 * (dbm + 100)));
        return `<span class="nc-bars" title="${dbm} dBm">${[20, 45, 70, 90].map(t => `<i class="${pct >= t ? 'on' : ''}"></i>`).join('')}</span> <span class="muted small">${dbm} dBm</span>`;
    },

    renderClients() {
        const d = this.data, list = d.clients || [];
        this.$('ap-cl-meta').textContent = d.active ? `${list.filter(c => c.online).length} online · ${list.length} known` : 'access point is not running';
        const res = d.reservations;
        this.$('ap-clients').innerHTML = list.map(c => {
            const r = res.find(x => x.mac === c.mac);
            const ri = r ? res.indexOf(r) : -1;
            const ipNote = r ? (r.ip === c.ip ? ' <span class="badge badge-ok" title="Reserved address">reserved</span>'
                                              : ` <span class="badge badge-warn" title="Gets the reserved address at the next renewal">→ ${esc(r.ip)}</span>`) : '';
            const name = (r && r.name) || c.hostname;
            return `<tr${c.online ? '' : ' class="ap-off"'}>
                <td><i class="fa-solid fa-circle ${c.online ? 'text-ok' : 'muted'} nc-dot"></i> ${name ? esc(name) : '<span class="muted">unknown</span>'}
                    ${c.hostname && r && r.name && r.name !== c.hostname ? `<span class="muted small">(${esc(c.hostname)})</span>` : ''}</td>
                <td class="mono">${esc(c.ip || '—')}${ipNote}</td>
                <td class="mono small">${esc(c.mac)}</td>
                <td>${this._sig(c.signal)}${c.bitrate ? ` <span class="muted small">${esc(c.bitrate)}</span>` : ''}</td>
                <td class="small">${c.online ? this._dur(c.connected) : '<span class="muted">offline</span>'}</td>
                <td class="small">${c.expires_in !== null ? this._dur(c.expires_in) : '<span class="muted">—</span>'}</td>
                <td class="nc-acts">${ri >= 0
                    ? `<button class="btn btn-ghost btn-sm" type="button" onclick="NetAP.editRes(${ri})"><i class="fa-solid fa-pen"></i> Reservation</button>`
                    : `<button class="btn btn-ghost btn-sm" type="button" onclick="NetAP.reserve(${esc(JSON.stringify(c.mac))})" title="Always give this device the same address"><i class="fa-solid fa-thumbtack"></i> Reserve IP</button>`}</td>
            </tr>`;
        }).join('') || `<tr><td colspan="7" class="tbl-empty">${d.active ? 'No clients yet.' : 'Start the access point to see its clients.'}</td></tr>`;
    },

    // ── Reservations ───────────────────────────────────────────

    renderRes() {
        const d = this.data;
        this.$('ap-res').innerHTML = d.reservations.map((r, i) => {
            const c = (d.clients || []).find(x => x.mac === r.mac);
            const st = !c ? '<span class="muted">not seen</span>'
                : c.online ? (c.ip === r.ip ? '<span class="text-ok">online</span>' : `<span class="text-warn">online at ${esc(c.ip)}</span> <span class="muted small">— reconnect to apply</span>`)
                : '<span class="muted">offline</span>';
            return `<tr><td>${esc(r.name || '—')}</td><td class="mono small">${esc(r.mac)}</td><td class="mono">${esc(r.ip)}</td><td class="small">${st}</td>
                <td class="nc-acts"><button class="btn btn-ghost btn-sm" type="button" onclick="NetAP.editRes(${i})"><i class="fa-solid fa-pen"></i> Edit</button>
                <button class="btn-icon git-danger" type="button" onclick="NetAP.delRes(${i})" title="Remove the reservation"><i class="fa-regular fa-trash-can"></i></button></td></tr>`;
        }).join('') || '<tr><td colspan="5" class="tbl-empty">No reservations — press <b>Reserve IP</b> next to a client or <b>Add</b>.</td></tr>';
    },

    /** First free address of the network that is neither the AP, reserved nor leased (outside the pool first). */
    _freeIp() {
        const s = this.data.settings, n = this._net(s.address, s.prefix);
        if (!n) return '';
        const used = new Set([s.address, ...this.data.reservations.map(r => r.ip), ...(this.data.clients || []).map(c => c.ip)]);
        const a = this._n(s.start), b = this._n(s.end);
        for (const pass of [0, 1]) {
            for (let x = n.base + 1; x < n.bcast; x++) {
                if ((pass === 0) === (x >= a && x <= b)) continue;
                if (!used.has(this._s(x))) return this._s(x);
            }
        }
        return '';
    },

    reserve(mac) {
        const c = (this.data.clients || []).find(x => x.mac === mac) || {};
        this._resDialog(-1, { mac, ip: c.ip || this._freeIp(), name: (c.hostname || '').replace(/[^A-Za-z0-9-]/g, '-').replace(/^-+|-+$/g, '').slice(0, 63) });
    },

    editRes(i) {
        this._resDialog(i, i >= 0 ? this.data.reservations[i] : { mac: '', ip: this._freeIp(), name: '' });
    },

    _resDialog(i, r) {
        this._resEdit = i;
        const known = (this.data.clients || []).filter(c => !this.data.reservations.some((x, j) => j !== i && x.mac === c.mac));
        this.$('ap-m-title').innerHTML = `<i class="fa-solid fa-thumbtack"></i> ${i >= 0 ? 'Edit reservation' : 'Reserve an address'}`;
        this.$('ap-m-body').innerHTML = `
            <div class="field"><label>MAC address</label><input class="input mono" id="ap-r-mac" value="${esc(r.mac)}" list="ap-r-macs" placeholder="aa:bb:cc:dd:ee:ff">
                <datalist id="ap-r-macs">${known.map(c => `<option value="${esc(c.mac)}">${esc((c.hostname || '') + ' ' + (c.ip || ''))}</option>`).join('')}</datalist></div>
            <div class="field"><label>IP address</label><input class="input mono" id="ap-r-ip" value="${esc(r.ip)}">
                <span class="hint">Inside <span class="mono">${esc(this.data.settings.address)}/${this.data.settings.prefix}</span>; inside or outside the pool
                    <span class="mono">${esc(this.data.settings.start)} – ${esc(this.data.settings.end)}</span> (dnsmasq gives a reserved address to nobody else)</span></div>
            <div class="field"><label>Name</label><input class="input mono" id="ap-r-name" value="${esc(r.name || '')}" maxlength="63" placeholder="optional, e.g. scope-1">
                <span class="hint">Host name the device gets (and that resolves through the AP's DNS); letters, digits, "-"</span></div>`;
        this.$('ap-m-err').textContent = '';
        this.$('ap-overlay').classList.add('open');
        setTimeout(() => this.$(r.mac ? 'ap-r-ip' : 'ap-r-mac').focus(), 50);
    },

    closeRes() { this.$('ap-overlay').classList.remove('open'); },

    submitRes() {
        const r = { mac: this.$('ap-r-mac').value.trim(), ip: this.$('ap-r-ip').value.trim(), name: this.$('ap-r-name').value.trim() };
        const list = this.data.reservations.slice();
        if (this._resEdit >= 0) list[this._resEdit] = r; else list.push(r);
        this._saveRes(list).then(ok => { if (ok) this.closeRes(); });
    },

    delRes(i) {
        const r = this.data.reservations[i];
        if (!confirm(`Remove the reservation ${r.ip} for ${r.mac}?`)) return;
        this._saveRes(this.data.reservations.filter((_, j) => j !== i));
    },

    _saveRes(list) {
        return App.api('/api/netcfg/dhcp/reservations', { json: { reservations: list } }).then(r => {
            this.data.reservations = r.reservations;
            this.renderRes();
            this.renderClients();
            toast(r.reloaded ? 'Reservations applied' : r.restart_needed ? 'Saved — restart the access point once to apply (the DHCP server predates the reservation file)' : 'Reservations saved');
            return true;
        }).catch(e => {
            if (this.$('ap-overlay').classList.contains('open')) this.$('ap-m-err').textContent = e.message; else toast(e.message, true);
            return false;
        });
    },
};

App.onEscape(() => NetAP.closeRes());
document.addEventListener('netcfg-changed', () => { if (NetAP._shown) NetAP.load(); });
