/* ==========================================================================
   Settings → Network (routes/netcfg.py, core/netcfg.py): interfaces, Wi-Fi scan / join / hotspot, saved
   NetworkManager connections and their editor. Every change comes back "pending": this page confirms it when the
   panel is still reachable a few seconds later; otherwise NetworkManager rolls it back after the timeout.
   ========================================================================== */

const NetCfg = {
    data: null,
    networks: [],
    pend: null,
    _shown: false,
    _tick: null,
    _mine: false,          // the pending change was made from this page (auto-confirm allowed)
    _lost: false,
    _newAddr: '',
    modal: null,

    $(id) { return document.getElementById(id); },

    visible(on) {
        this._shown = on;
        if (on) { this.load(); this.scan(false); }
    },

    load() {
        return App.api('/api/netcfg').then(d => {
            this.data = d;
            this.$('nc-rb-sec').textContent = d.rollback_seconds;
            this.$('nc-host').textContent = 'host ' + d.hostname;
            this.renderDevs();
            this.renderConns();
            const r = this.$('nc-radio');
            r.checked = !!d.wifi_enabled;
            r.disabled = d.wifi_enabled === null;
            const wifi = d.devices.filter(x => x.type === 'wifi');
            const sel = this.$('nc-wdev'), cur = sel.value;
            sel.innerHTML = wifi.map(x => `<option value="${esc(x.device)}">${esc(x.device)}</option>`).join('') || '<option value="">no Wi-Fi adapter</option>';
            if (cur) sel.value = cur;
            sel.hidden = wifi.length < 2;
            this.setPending(d.pending, false);
        }).catch(e => { this.$('nc-devs').innerHTML = `<div class="text-error">✗ ${esc(e.message)}</div>`; });
    },

    renderDevs() {
        const d = this.data;
        this.$('nc-devs').innerHTML = d.devices.map(x => {
            const you = x.device === d.client_device;
            const rows = [
                ['State', `<span class="${x.connected ? 'text-ok' : 'muted'}">${esc(x.state)}</span>`],
                ['Connection', esc(x.connection || '—')],
                ['IPv4', x.ip4.map(esc).join('<br>') || '—'],
                ['Gateway', esc(x.gateway || '—')],
                ['DNS', esc(x.dns.join(', ') || '—')],
                ['MAC', esc(x.mac)],
            ];
            const n = esc(JSON.stringify(x.uuid));
            return `<div class="nc-dev${x.connected ? ' on' : ''}">
                <div class="nc-dev-head"><i class="fa-solid ${x.type === 'wifi' ? 'fa-wifi' : 'fa-ethernet'}"></i>
                    <b class="mono">${esc(x.device)}</b>
                    ${you ? '<span class="badge badge-info" title="This page reaches the panel through this interface">you are here</span>' : ''}
                    <span class="spacer"></span>
                    ${x.uuid ? `<button class="btn btn-ghost btn-sm" type="button" onclick="NetCfg.edit(${n})"><i class="fa-solid fa-pen"></i> Configure</button>` : ''}
                </div>
                <div class="nc-kv">${rows.map(([k, v]) => `<span class="muted">${k}</span><span class="mono">${v}</span>`).join('')}</div>
            </div>`;
        }).join('') || '<div class="muted">No Ethernet / Wi-Fi interfaces found.</div>';
    },

    renderConns() {
        const d = this.data;
        this.$('nc-conns').innerHTML = d.connections.map(c => {
            const n = esc(JSON.stringify(c.uuid));
            const you = c.active && c.device === d.client_device;
            return `<tr${c.active ? ' class="nc-active"' : ''}>
                <td><i class="fa-solid ${c.active ? 'fa-circle text-ok' : 'fa-circle muted'} nc-dot"></i> ${esc(c.name)}</td>
                <td>${c.type === 'wifi' ? '<i class="fa-solid fa-wifi"></i> Wi-Fi' : '<i class="fa-solid fa-ethernet"></i> Ethernet'}</td>
                <td class="mono">${esc(c.device || '—')}</td>
                <td>${c.autoconnect ? 'yes' : 'no'}</td>
                <td class="mono">${c.priority}</td>
                <td class="nc-acts">
                    <button class="btn btn-ghost btn-sm" type="button" onclick="NetCfg.edit(${n})"><i class="fa-solid fa-pen"></i> Edit</button>
                    ${c.active
                        ? `<button class="btn btn-ghost btn-sm" type="button" onclick="NetCfg.act('deactivate', {uuid: ${n}}, ${you})"${you ? ' title="You are connected through it — rolled back if the page loses the panel"' : ''}><i class="fa-solid fa-link-slash"></i> Disconnect</button>`
                        : `<button class="btn btn-ghost btn-sm" type="button" onclick="NetCfg.act('activate', {uuid: ${n}})"><i class="fa-solid fa-link"></i> Connect</button>`}
                    <button class="btn-icon git-danger" type="button" onclick="NetCfg.forget(${n})" title="Forget (delete this profile)"><i class="fa-regular fa-trash-can"></i></button>
                </td></tr>`;
        }).join('') || '<tr><td colspan="6" class="tbl-empty">No saved connections.</td></tr>';
    },

    scan(rescan) {
        const btn = this.$('nc-scan');
        if (rescan) btn.disabled = true;
        const ifn = this.$('nc-wdev').value;
        return App.api(`/api/netcfg/wifi?rescan=${rescan ? 1 : 0}${ifn ? '&ifname=' + encodeURIComponent(ifn) : ''}`)
            .then(d => { this.networks = d.networks; this.renderWifi(); })
            .catch(e => { this.$('nc-wifi').innerHTML = `<tr><td colspan="5" class="tbl-empty text-error">${esc(e.message)}</td></tr>`; })
            .finally(() => { btn.disabled = false; });
    },

    renderWifi() {
        const bars = s => `<span class="nc-bars" title="${s}%">${[20, 45, 70, 90].map(t => `<i class="${s >= t ? 'on' : ''}"></i>`).join('')}</span>`;
        this.$('nc-wifi').innerHTML = this.networks.map((w, i) => `<tr${w.in_use ? ' class="nc-active"' : ''}>
                <td><b>${esc(w.ssid)}</b>${w.in_use ? ' <span class="badge badge-ok">connected</span>' : w.known ? ' <span class="badge badge-muted">saved</span>' : ''}</td>
                <td>${bars(w.signal)} <span class="muted small">${w.signal}%</span></td>
                <td>${w.security === 'open' ? '<span class="text-warn">open</span>' : '<i class="fa-solid fa-lock muted"></i> ' + esc(w.security)}</td>
                <td class="mono small">${esc(w.band)} · ${esc(w.channel)}</td>
                <td class="nc-acts">${w.in_use ? '' : `<button class="btn btn-primary btn-sm" type="button" onclick="NetCfg.openJoin(${i})"><i class="fa-solid fa-plug"></i> Connect</button>`}</td>
            </tr>`).join('') || '<tr><td colspan="5" class="tbl-empty">No networks found — press Scan.</td></tr>';
    },

    // ── Changes + pending confirmation ─────────────────────────

    act(action, body, mayCut) {
        if (action === 'deactivate' && mayCut && !confirm('You are connected through this connection. Disconnect anyway?\nIf the page loses the panel, NetworkManager restores it automatically.')) return Promise.resolve();
        return this._post('/api/netcfg/' + action, body);
    },

    forget(uuid) {
        const c = this.data.connections.find(x => x.uuid === uuid);
        if (!confirm(`Forget "${c ? c.name : uuid}"? The profile (and its saved password) is deleted.`)) return;
        this._post('/api/netcfg/delete', { uuid });
    },

    radio(on) { this._post('/api/netcfg/radio', { on }); },

    _post(url, body, newAddr) {
        this._newAddr = newAddr || '';
        return App.api(url, { json: body }).then(p => {
            this._mine = true;
            this._lost = false;
            this.setPending(p, true);
            this.close();
            setTimeout(() => this.load(), 1500);
            setTimeout(() => this.scan(false), 3000);
        }).catch(e => {
            if (this.modal) this.$('nc-m-err').textContent = e.message; else toast(e.message, true);
            this.load();
        });
    },

    /** Show the pending change; when it was made here, confirm it once the panel answers a few seconds later. */
    setPending(p, fresh) {
        this.pend = p && p.path ? p : null;
        clearInterval(this._tick);
        const box = this.$('nc-pending');
        if (!this.pend) {
            const last = p && p.last;
            box.hidden = !last;
            if (last) box.innerHTML = `<i class="fa-solid ${last.result === 'kept' ? 'fa-circle-check text-ok' : 'fa-rotate-left text-warn'}"></i>
                <span><b>${esc(last.label)}</b> — ${esc(last.result)}</span>
                <span class="spacer"></span><button class="btn-icon" type="button" onclick="NetCfg.$('nc-pending').hidden = true"><i class="fa-solid fa-xmark"></i></button>`;
            this._mine = false;
            return;
        }
        const deadline = Date.now() + this.pend.left * 1000;
        const started = Date.now();
        let oks = 0, busy = false;
        const draw = () => {
            const left = Math.max(0, Math.round((deadline - Date.now()) / 1000));
            box.hidden = false;
            box.className = 'nc-pending' + (this._lost ? ' lost' : '');
            const url = this._newAddr ? `${location.protocol}//${this._newAddr}${location.port ? ':' + location.port : ''}/settings#network` : '';
            const where = url ? ` Open <a href="${esc(url)}">${esc(this._newAddr)}</a> and keep it there.` : '';
            box.innerHTML = `<i class="fa-solid ${this._lost ? 'fa-triangle-exclamation' : 'fa-hourglass-half'}"></i>
                <span><b>${esc(this.pend.label)}</b> — ${this._lost
                    ? `this page lost the panel. The previous settings come back in <b>${left} s</b> unless confirmed from the new address.${where}`
                    : this._mine ? `checking that the panel is still reachable… (rollback in ${left} s)`
                    : `waiting for confirmation — rolled back in <b>${left} s</b>`}</span>
                <span class="spacer"></span>
                <button class="btn btn-success btn-sm" type="button" onclick="NetCfg.decide('confirm')"><i class="fa-solid fa-check"></i> Keep</button>
                <button class="btn btn-ghost btn-sm" type="button" onclick="NetCfg.decide('revert')"><i class="fa-solid fa-rotate-left"></i> Revert</button>`;
            if (left <= 0) { clearInterval(this._tick); setTimeout(() => this.load(), 4000); }
        };
        draw();
        this._tick = setInterval(() => {
            draw();
            if (!this._mine || busy || Date.now() - started < 3000) return;
            busy = true;
            this._reach().then(ok => {
                busy = false;
                this._lost = !ok;
                oks = ok ? oks + 1 : 0;
                if (oks >= 2) this.decide('confirm');
            });
        }, 1000);
    },

    _reach() {
        const ctl = new AbortController();
        const t = setTimeout(() => ctl.abort(), 2500);
        return fetch('/api/netcfg/pending', { signal: ctl.signal, cache: 'no-store' })
            .then(r => r.ok).catch(() => false).finally(() => clearTimeout(t));
    },

    decide(what) {
        clearInterval(this._tick);
        App.api('/api/netcfg/' + what, { json: {} })
            .then(r => { this.setPending(r, true); if (what === 'confirm') toast('Network settings kept'); this.load(); this.scan(false); })
            .catch(e => { toast(e.message, true); this.load(); });
    },

    // ── Dialogs ────────────────────────────────────────────────

    _open(title, okLabel, html, mode) {
        this.modal = mode;
        this.$('nc-m-title').innerHTML = title;
        this.$('nc-m-ok').innerHTML = okLabel;
        this.$('nc-m-body').innerHTML = html;
        this.$('nc-m-err').textContent = '';
        this.$('nc-overlay').classList.add('open');
    },

    close() { this.modal = null; this.$('nc-overlay').classList.remove('open'); },

    edit(uuid) {
        App.api('/api/netcfg/connection?uuid=' + encodeURIComponent(uuid)).then(c => {
            const you = this.data && this.data.connections.some(x => x.uuid === uuid && x.active && x.device === this.data.client_device);
            const opt = (list, cur) => list.map(([v, l]) => `<option value="${v}"${v === cur ? ' selected' : ''}>${l}</option>`).join('');
            const w = c.wifi;
            this._conn = c;
            this._open(`<i class="fa-solid ${c.type === 'wifi' ? 'fa-wifi' : 'fa-ethernet'}"></i> ${esc(c.name)}`, '<i class="fa-solid fa-check"></i> Apply', `
                ${you ? '<div class="nc-warn"><i class="fa-solid fa-triangle-exclamation"></i> You are connected through this connection. If the address changes, open the new one within the rollback time and press Keep there.</div>' : ''}
                <div class="field-row">
                    <div class="field"><label>Name</label><input class="input" id="nc-f-name" value="${esc(c.name)}"></div>
                    <div class="field"><label>Interface</label><input class="input mono" id="nc-f-if" value="${esc(c.interface)}" placeholder="any"></div>
                </div>
                <div class="field-row">
                    <label class="check-row"><input type="checkbox" id="nc-f-auto"${c.autoconnect ? ' checked' : ''}> Connect automatically</label>
                    <div class="field"><label>Priority</label><input class="input mono" type="number" id="nc-f-prio" value="${c.priority}" min="-999" max="999">
                        <span class="hint">Higher connects first when several are available</span></div>
                </div>
                ${w ? `<div class="field-row">
                    <div class="field"><label>SSID</label><input class="input mono" value="${esc(w.ssid)}" disabled>
                        <span class="hint">${esc(w.mode === 'ap' ? 'access point (hotspot)' : 'client')} · ${esc(w.security)}</span></div>
                    <div class="field"><label>New password</label><input class="input" type="password" id="nc-f-psk" autocomplete="new-password" placeholder="unchanged"${w.security === 'none' ? ' disabled' : ''}></div>
                </div>
                <label class="check-row"><input type="checkbox" id="nc-f-hidden"${w.hidden ? ' checked' : ''}> Hidden network</label>` : ''}
                <h4 class="nc-h">IPv4</h4>
                <div class="field"><label>Method</label><select class="input" id="nc-f-m4" onchange="NetCfg._m4()">${opt([
                    ['auto', 'DHCP (automatic)'], ['manual', 'Static (manual)'], ['shared', 'Shared — give addresses to other devices'],
                    ['link-local', 'Link-local only'], ['disabled', 'Disabled']], c.ipv4.method)}</select></div>
                <div class="nc-static">
                    <div class="field"><label>Addresses</label><textarea class="input mono" id="nc-f-addr" rows="2" placeholder="192.168.1.50/24">${esc(c.ipv4.addresses.join('\n'))}</textarea>
                        <span class="hint">One per line, with the prefix (<code>/24</code> = 255.255.255.0)</span></div>
                    <div class="field"><label>Gateway</label><input class="input mono" id="nc-f-gw" value="${esc(c.ipv4.gateway)}" placeholder="192.168.1.1"></div>
                </div>
                <div class="field"><label>DNS servers</label><input class="input mono" id="nc-f-dns" value="${esc(c.ipv4.dns.join(', '))}" placeholder="192.168.1.1, 8.8.8.8">
                    <span class="hint">Comma separated; with DHCP they are added to the received ones unless the box below is ticked</span></div>
                <label class="check-row nc-dhcp"><input type="checkbox" id="nc-f-igdns"${c.ipv4.ignore_auto_dns ? ' checked' : ''}> Use only these DNS servers (ignore DHCP DNS)</label>
                <h4 class="nc-h">IPv6</h4>
                <div class="field"><label>Method</label><select class="input" id="nc-f-m6">${opt([
                    ['auto', 'Automatic (SLAAC / DHCPv6)'], ['dhcp', 'DHCPv6 only'], ['link-local', 'Link-local only'],
                    ['ignore', 'Ignore'], ['disabled', 'Disabled']], c.ipv6.method)}</select></div>`, 'edit');
            this._m4();
        }).catch(e => toast(e.message, true));
    },

    _m4() {
        const m = this.$('nc-f-m4').value;
        this.$('nc-m-body').querySelector('.nc-static').hidden = m !== 'manual';
        this.$('nc-m-body').querySelector('.nc-dhcp').hidden = m !== 'auto';
    },

    openJoin(i) {
        const w = i === null ? null : this.networks[i];
        this._join = w;
        const secured = !w || w.security !== 'open';
        this._open(`<i class="fa-solid fa-wifi"></i> ${w ? esc(w.ssid) : 'Hidden network'}`, '<i class="fa-solid fa-plug"></i> Connect', `
            ${w ? '' : `<div class="field"><label>SSID</label><input class="input mono" id="nc-j-ssid" maxlength="32"></div>
                <div class="field"><label>Security</label><select class="input" id="nc-j-sec"><option>WPA2</option><option>WPA3</option><option value="open">Open</option></select></div>`}
            ${secured ? `<div class="field"><label>Password</label><input class="input" type="password" id="nc-j-psk" autocomplete="new-password"${w && w.known ? ' placeholder="saved — leave empty to use it"' : ''}>
                <label class="check-row small"><input type="checkbox" onchange="NetCfg.$('nc-j-psk').type = this.checked ? 'text' : 'password'"> show</label></div>` : '<div class="nc-warn"><i class="fa-solid fa-lock-open"></i> Open network — traffic is not encrypted.</div>'}
            <div class="hint">Adapter <b class="mono">${esc(this.$('nc-wdev').value)}</b>; the profile is saved and reconnects automatically.
                If this adapter is how you reach the panel, the change is rolled back unless the page still reaches it.</div>`, 'join');
        setTimeout(() => { const f = this.$(w ? 'nc-j-psk' : 'nc-j-ssid'); if (f) f.focus(); }, 50);
    },

    openHotspot() {
        const wifi = (this.data ? this.data.devices : []).filter(x => x.type === 'wifi');
        this._open('<i class="fa-solid fa-tower-broadcast"></i> Hotspot', '<i class="fa-solid fa-tower-broadcast"></i> Start', `
            <div class="nc-warn"><i class="fa-solid fa-triangle-exclamation"></i> The adapter leaves its current Wi-Fi network. Clients get addresses from this board (10.42.0.x) — the panel is then at <b class="mono">10.42.0.1</b>.</div>
            <div class="field-row">
                <div class="field"><label>Network name (SSID)</label><input class="input mono" id="nc-h-ssid" maxlength="32" value="${esc((this.data && this.data.hostname) || 'smms')}"></div>
                <div class="field"><label>Adapter</label><select class="input" id="nc-h-if">${wifi.map(x => `<option>${esc(x.device)}</option>`).join('')}</select></div>
            </div>
            <div class="field"><label>Password</label><input class="input" type="text" id="nc-h-psk" autocomplete="off" minlength="8">
                <span class="hint">WPA2, 8–63 characters</span></div>`, 'hotspot');
    },

    submit() {
        this.$('nc-m-err').textContent = '';
        const v = id => (this.$(id) || {}).value || '';
        if (this.modal === 'edit') {
            const c = this._conn;
            const body = {
                uuid: c.uuid, name: v('nc-f-name').trim(), interface: v('nc-f-if').trim(),
                autoconnect: this.$('nc-f-auto').checked, priority: parseInt(v('nc-f-prio'), 10) || 0,
                ipv4: { method: v('nc-f-m4'), addresses: v('nc-f-addr').split(/[\n,]+/).map(s => s.trim()).filter(Boolean),
                        gateway: v('nc-f-gw').trim(), dns: v('nc-f-dns').split(/[\s,]+/).filter(Boolean),
                        ignore_auto_dns: this.$('nc-f-igdns').checked },
                ipv6: { method: v('nc-f-m6') },
            };
            if (c.wifi) { body.wifi = { hidden: this.$('nc-f-hidden').checked }; if (v('nc-f-psk')) body.password = v('nc-f-psk'); }
            const you = this.data.connections.some(x => x.uuid === c.uuid && x.active && x.device === this.data.client_device);
            const addr = body.ipv4.method === 'manual' && you ? (body.ipv4.addresses[0] || '').split('/')[0] : '';
            return this._post('/api/netcfg/connection', body, addr !== location.hostname ? addr : '');
        }
        if (this.modal === 'join') {
            const w = this._join;
            return this._post('/api/netcfg/join', {
                ssid: w ? w.ssid : v('nc-j-ssid').trim(), password: v('nc-j-psk'), ifname: this.$('nc-wdev').value,
                security: w ? w.security : v('nc-j-sec'), hidden: !w,
            });
        }
        if (this.modal === 'hotspot') {
            return this._post('/api/netcfg/hotspot', { ssid: v('nc-h-ssid').trim(), password: v('nc-h-psk'), ifname: v('nc-h-if') }, '10.42.0.1');
        }
    },
};

App.onEscape(() => NetCfg.close());
