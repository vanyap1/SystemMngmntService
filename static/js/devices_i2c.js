/* ==========================================================================
   HW Utils tab "I²C" (core/i2c.py, /api/i2c/*): address grid like `i2cdetect`, register read / write like
   `i2ctransfer`, device names per bus. The bus is touched only by Scan / Read / Write — opening the tab only
   lists the adapters and the clients the kernel knows about.
   ========================================================================== */

Devices.register({
    id: 'i2c',
    autoMs: 0,
    data: null,              // /api/i2c/buses
    bus: null,               // selected bus number
    scans: {},               // bus -> {found: Set, busy: Set, at: Date}
    sel: null,               // selected address
    form: {},                // addr -> {reg, width, len, data, force} (remembered per address)
    last: {},                // addr -> last read result {data, reg, width}
    log: [],

    load() {
        return App.api('/api/i2c/buses').then(d => {
            this.data = d;
            const buses = d.buses || [];
            if (this.bus === null || !buses.some(b => b.bus === this.bus)) this.bus = buses.length ? buses[0].bus : null;
            const sel = document.getElementById('i2c-bus');
            sel.innerHTML = buses.length
                ? buses.map(b => `<option value="${b.bus}"${b.bus === this.bus ? ' selected' : ''}>i2c-${b.bus} · ${esc(b.name)}</option>`).join('')
                : '<option value="">No I²C buses</option>';
            document.getElementById('i2c-scan').disabled = !buses.length || !d.tools;
            this.render();
        });
    },

    busInfo() {
        return this.data && (this.data.buses || []).find(b => b.bus === this.bus);
    },

    selectBus(v) {
        this.bus = v === '' ? null : Number(v);
        this.sel = null;
        this.render();
    },

    hex(n, w = 2) { return '0x' + n.toString(16).padStart(w, '0'); },

    /** What we know about an address: {state, name, source}. */
    info(addr) {
        const b = this.busInfo(), scan = this.scans[this.bus];
        const label = b && b.labels[this.hex(addr)];
        const client = b && b.clients.find(c => c.addr === addr);
        const name = label || (client ? client.name + (client.driver ? ` (${client.driver})` : '') : '');
        let state = 'idle';
        if (scan) {
            if (scan.busy.has(addr)) state = 'busy';
            else if (scan.found.has(addr)) state = name ? 'known' : 'unknown';
            else if (name) state = 'missing';
        } else if (name) {
            state = 'declared';
        }
        return { state, name, label: label || '', client };
    },

    hint(addr) {
        const h = this.data && (this.data.hints || []).find(([lo, hi]) => addr >= lo && addr <= hi);
        return h ? h[2] : '';
    },

    render() {
        const grid = document.getElementById('i2c-grid');
        if (!this.data) return;
        if (!this.data.tools) {
            grid.innerHTML = '<div class="tbl-empty">i2c-tools are not installed — <code>sudo apt install i2c-tools</code> or <code>./install.sh</code> (component devices).</div>';
            return;
        }
        if (this.bus === null) {
            grid.innerHTML = '<div class="tbl-empty">No I²C bus with a /dev/i2c-N node (load the <code>i2c-dev</code> module).</div>';
            this._summary();
            return;
        }
        const [lo, hi] = this.data.range;
        let html = '<span></span>' + [...Array(16).keys()].map(c => `<span class="i2c-colh">${c.toString(16).toUpperCase()}</span>`).join('');
        for (let row = 0; row < 0x80; row += 16) {
            html += `<span class="i2c-rowh">${row.toString(16).padStart(2, '0').toUpperCase()}</span>`;
            for (let a = row; a < row + 16; a++) {
                if (a < lo || a > hi) { html += '<span class="i2c-cell out"></span>'; continue; }
                const inf = this.info(a);
                const title = `${this.hex(a)}${inf.name ? ' · ' + inf.name : ''} · ${this._stateText(inf.state)}`;
                html += `<button type="button" class="i2c-cell ${inf.state}${a === this.sel ? ' sel' : ''}" data-addr="${a}"
                    title="${esc(title)}" onclick="Devices.tabs.i2c.pick(${a})">${a.toString(16).padStart(2, '0').toUpperCase()}</button>`;
            }
        }
        grid.innerHTML = html;
        this._summary();
        if (this.sel !== null) this._pop(); else document.getElementById('i2c-pop').hidden = true;
    },

    _stateText(s) {
        return { known: 'answers', unknown: 'answers (unknown chip)', busy: 'used by a kernel driver (UU)',
                 missing: 'configured, no answer', declared: 'declared — not scanned yet', idle: 'not scanned / no answer' }[s];
    },

    _summary() {
        const scan = this.scans[this.bus], info = document.getElementById('i2c-scan-info');
        const b = this.busInfo();
        if (!b) { Devices.summary('', this.id); info.textContent = ''; return; }
        if (!scan) {
            info.textContent = 'not scanned yet';
            Devices.summary(`i2c-${b.bus} · ${b.clients.length} kernel client(s) · press Scan to probe the bus`, this.id);
            return;
        }
        const missing = [...Array(128).keys()].filter(a => this.info(a).state === 'missing').length;
        info.textContent = `${scan.found.size} device(s), ${scan.busy.size} UU${missing ? `, ${missing} missing` : ''} · ${App.fmtTime(scan.at)}`;
        Devices.summary(`i2c-${b.bus} · scanned ${App.fmtTime(scan.at)} (${scan.mode})`, this.id);
    },

    scan() {
        if (this.bus === null) return;
        const btn = document.getElementById('i2c-scan'), mode = document.getElementById('i2c-mode').value;
        btn.disabled = true;
        btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Scanning…';
        const bus = this.bus;
        App.api('/api/i2c/scan', { json: { bus, mode } }).then(d => {
            this.scans[bus] = { found: new Set(d.found), busy: new Set(d.busy), at: new Date(), mode };
            this._log({ op: 'scan', bus, text: `found ${d.found.map(a => this.hex(a)).join(' ') || '—'}${d.busy.length ? ` · UU ${d.busy.map(a => this.hex(a)).join(' ')}` : ''}` });
            this.render();
        }).catch(e => { toast(e.message, true); this._log({ op: 'scan', bus, error: e.message }); })
          .finally(() => { btn.disabled = false; btn.innerHTML = '<i class="fa-solid fa-magnifying-glass"></i> Scan'; });
    },

    pick(addr) {
        this.sel = this.sel === addr ? null : addr;
        this.render();
        if (this.sel !== null) {
            const r = document.getElementById('i2c-reg');
            if (r) r.focus();
        }
    },

    close() { this.sel = null; this.render(); },

    _f(addr) {
        if (!this.form[addr]) this.form[addr] = { reg: '00', width: addr >= 0x50 && addr <= 0x57 ? 2 : 1, len: 1, data: '', force: false };
        return this.form[addr];
    },

    _pop() {
        const a = this.sel, pop = document.getElementById('i2c-pop'), inf = this.info(a), f = this._f(a);
        const hint = !inf.name ? this.hint(a) : '';
        const res = this.last[a];
        pop.innerHTML = `
            <div class="i2c-pop-head">
                <b class="mono">${this.hex(a)}</b>
                <span class="i2c-pop-name">${esc(inf.name || 'unnamed device')}</span>
                <span class="i2c-pop-state ${inf.state}">${esc(this._stateText(inf.state))}</span>
                <button type="button" class="btn-icon" onclick="Devices.tabs.i2c.rename()" title="Name this device (saved for this host)"><i class="fa-solid fa-pen"></i></button>
                <span class="spacer"></span>
                <button type="button" class="modal-close" onclick="Devices.tabs.i2c.close()" title="Close">&#215;</button>
            </div>
            ${hint ? `<div class="i2c-hint"><i class="fa-regular fa-lightbulb"></i> maybe: ${esc(hint)}</div>` : ''}
            <div class="i2c-form">
                <label>Reg</label>
                <input class="input input-sm mono" id="i2c-reg" value="${esc(f.reg)}" ${f.width ? '' : 'disabled'} placeholder="00" title="Register address (hex)">
                <select class="input input-sm" id="i2c-width" title="Register address size" onchange="Devices.tabs.i2c._width(this.value)">
                    <option value="1"${f.width === 1 ? ' selected' : ''}>8-bit reg</option>
                    <option value="2"${f.width === 2 ? ' selected' : ''}>16-bit reg</option>
                    <option value="0"${f.width === 0 ? ' selected' : ''}>no reg</option>
                </select>
                <label>Len</label>
                <input class="input input-sm mono i2c-len" id="i2c-len" type="number" min="1" max="256" value="${f.len}">
                <button type="button" class="btn btn-info btn-sm" onclick="Devices.tabs.i2c.read()"><i class="fa-solid fa-download"></i> Read</button>
            </div>
            <div class="i2c-form">
                <label>Data</label>
                <input class="input input-sm mono i2c-data" id="i2c-data" value="${esc(f.data)}" placeholder="hex bytes: C3,83 or 0xc3 0x83">
                <button type="button" class="btn btn-warning btn-sm" onclick="Devices.tabs.i2c.write()"><i class="fa-solid fa-upload"></i> Write</button>
            </div>
            ${inf.state === 'busy' ? `<label class="check-row small i2c-force"><input type="checkbox" id="i2c-force" ${f.force ? 'checked' : ''}>
                Force — access although a kernel driver owns this address (may confuse the driver)</label>` : ''}
            <div class="i2c-result" id="i2c-result">${res ? this._result(res) : '<span class="muted">Read a register to see its bytes.</span>'}</div>`;
        pop.hidden = false;
        pop.querySelectorAll('input').forEach(i => i.addEventListener('keydown', e => {
            if (e.key === 'Enter') { e.preventDefault(); i.id === 'i2c-data' ? this.write() : this.read(); }
        }));
        this._place();
    },

    _place() {   // under the selected cell (above it when there is no room below)
        const wrap = document.getElementById('i2c-grid-wrap'), pop = document.getElementById('i2c-pop');
        const cell = wrap.querySelector(`.i2c-cell[data-addr="${this.sel}"]`);
        if (!cell) return;
        const w = wrap.getBoundingClientRect(), c = cell.getBoundingClientRect();
        const left = Math.max(0, Math.min(c.left - w.left - 20, w.width - pop.offsetWidth));
        let top = c.bottom - w.top + 8;
        if (top + pop.offsetHeight > w.height + 140 && c.top - w.top - pop.offsetHeight - 8 > 0) top = c.top - w.top - pop.offsetHeight - 8;
        pop.style.left = left + 'px';
        pop.style.top = top + 'px';
        pop.style.setProperty('--arrow', (c.left - w.left - left + c.width / 2) + 'px');
    },

    _width(v) {
        const f = this._f(this.sel);
        this._keep();
        f.width = Number(v);
        this._pop();
    },

    _keep() {   // remember the form of the selected address
        const f = this._f(this.sel), v = id => document.getElementById(id);
        if (v('i2c-reg')) f.reg = v('i2c-reg').value.trim();
        if (v('i2c-len')) f.len = Math.max(1, Math.min(256, parseInt(v('i2c-len').value, 10) || 1));
        if (v('i2c-data')) f.data = v('i2c-data').value.trim();
        f.force = !!(v('i2c-force') && v('i2c-force').checked);
        return f;
    },

    _req(f) {
        const reg = f.width ? '0x' + (f.reg || '0').replace(/^0x/i, '') : 0;
        return { bus: this.bus, addr: this.sel, reg, width: f.width, force: f.force };
    },

    read() {
        const f = this._keep(), addr = this.sel, req = { ...this._req(f), length: f.len };
        App.api('/api/i2c/read', { json: req }).then(d => {
            this.last[addr] = d;
            this._log({ op: 'read', bus: d.bus, addr, reg: d.reg, width: d.width, data: d.data });
            if (this.sel === addr) document.getElementById('i2c-result').innerHTML = this._result(d);
        }).catch(e => this._fail('read', addr, req, e));
    },

    write() {
        const f = this._keep(), addr = this.sel, req = { ...this._req(f), data: f.data };
        if (!f.data) return toast('Enter the bytes to write', true);
        if (f.force && !confirm(`Write to ${this.hex(addr)} although a kernel driver owns it?`)) return;
        App.api('/api/i2c/write', { json: req }).then(d => {
            this._log({ op: 'write', bus: d.bus, addr, reg: d.reg, width: d.width, text: `${d.written} byte(s): ${f.data}` });
            toast(`Wrote ${d.written} byte(s) to ${this.hex(addr)}`);
        }).catch(e => this._fail('write', addr, req, e));
    },

    _fail(op, addr, req, e) {
        this._log({ op, bus: req.bus, addr, reg: req.width ? Number(req.reg) : null, width: req.width, error: e.message });
        if (this.sel === addr) document.getElementById('i2c-result').innerHTML = `<span class="text-error"><i class="fa-solid fa-circle-xmark"></i> ${esc(e.message)}</span>`;
    },

    _result(d) {
        const bytes = d.data;
        const hexs = bytes.map(b => b.toString(16).padStart(2, '0').toUpperCase());
        const ascii = bytes.map(b => b >= 32 && b < 127 ? String.fromCharCode(b) : '·').join('');
        let extra = '';
        if (bytes.length === 2) {
            const be = bytes[0] << 8 | bytes[1], le = bytes[1] << 8 | bytes[0];
            extra = `<div class="i2c-vals"><span>u16 BE <b>${be}</b> (${this.hex(be, 4)})</span><span>u16 LE <b>${le}</b> (${this.hex(le, 4)})</span>
                     <span>s16 BE <b>${be > 32767 ? be - 65536 : be}</b></span></div>`;
        } else if (bytes.length === 1) {
            extra = `<div class="i2c-vals"><span>dec <b>${bytes[0]}</b></span><span>bin <b>${bytes[0].toString(2).padStart(8, '0')}</b></span></div>`;
        } else if (bytes.length === 4) {
            const be = ((bytes[0] << 24) >>> 0) + (bytes[1] << 16) + (bytes[2] << 8) + bytes[3];
            extra = `<div class="i2c-vals"><span>u32 BE <b>${be}</b></span></div>`;
        }
        const start = d.width ? d.reg : 0;
        const rows = [];
        for (let i = 0; i < bytes.length; i += 16) {
            rows.push(`<span class="i2c-off">${d.width ? this.hex(start + i, d.width * 2) : '+' + i}</span>` +
                `<span>${hexs.slice(i, i + 16).join(' ')}</span><span class="i2c-ascii">${esc(ascii.slice(i, i + 16))}</span>`);
        }
        return `<div class="i2c-dump">${rows.join('')}</div>${extra}`;
    },

    rename() {
        const a = this.sel, inf = this.info(a);
        const name = prompt(`Name of ${this.hex(a)} on i2c-${this.bus} (empty = remove):`, inf.label || (inf.client ? inf.client.name : ''));
        if (name === null) return;
        App.api('/api/i2c/label', { json: { bus: this.bus, addr: a, label: name } }).then(d => {
            const b = this.busInfo();
            if (d.label) b.labels[this.hex(a)] = d.label; else delete b.labels[this.hex(a)];
            this.render();
        }).catch(e => toast(e.message, true));
    },

    _log(entry) {
        entry.at = new Date();
        this.log.unshift(entry);
        this.log.length = Math.min(this.log.length, 100);
        this._renderLog();
    },

    clearLog() { this.log = []; this._renderLog(); },

    _renderLog() {
        const el = document.getElementById('i2c-log');
        if (!this.log.length) { el.innerHTML = '<div class="tbl-empty">No transactions yet.</div>'; return; }
        el.innerHTML = this.log.map(e => {
            const where = e.addr !== undefined ? `${this.hex(e.addr)}${e.width && e.reg !== null && e.reg !== undefined ? ' @' + this.hex(e.reg, e.width * 2) : ''}` : `i2c-${e.bus}`;
            const body = e.error ? `<span class="text-error">${esc(e.error)}</span>`
                : e.data ? `<span class="mono">${e.data.map(b => b.toString(16).padStart(2, '0').toUpperCase()).join(' ')}</span>`
                : esc(e.text || '');
            return `<div class="i2c-log-row ${e.error ? 'err' : ''}"><span class="faint">${App.fmtTime(e.at)}</span>
                <span class="i2c-op ${e.op}">${e.op}</span><span class="mono">${esc(where)}</span><div class="i2c-log-body">${body}</div></div>`;
        }).join('');
    },
});
