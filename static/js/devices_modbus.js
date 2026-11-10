/* ==========================================================================
   HW Utils tab "Modbus" (core/modbus.py, /api/modbus/*): two tables of editable request rows — manual (run with ▶)
   and timer rows (each with its own period, run by one scheduler while "Start timers" is on, ▶ any time);
   unit-id scan; TX/RX frame log on top; a quick request line; notes where [[fn addr count|=values format uN]] tags
   are buttons that fill / run the quick request. Profiles (connection + rows + period)
   are saved per host in config.json. Registers travel as raw u16 — formats are converted here.
   ========================================================================== */

Devices.register({
    id: 'modbus',
    autoMs: 0,
    info: null,              // /api/modbus/info
    profiles: [],
    cur: '',
    results: [],             // per row of the current profile: {ok, values, error, ms, at}
    cycleOn: false, cycleTimer: null, cycleCount: 0, busy: false,
    scanning: false,
    log: [],
    found: [],               // last scan hits
    session: '',             // name of the session loaded / saved last
    sessions: [],
    _saveT: null,

    FUNCS: [[3, '03 Read holding'], [4, '04 Read input'], [1, '01 Read coils'], [2, '02 Read discrete'],
            [6, '06 Write register'], [16, '16 Write registers'], [5, '05 Write coil'], [15, '15 Write coils']],
    FORMATS: [['u16', 'u16'], ['s16', 's16'], ['hex', 'hex'], ['bin', 'binary'], ['ascii', 'ascii'],
              ['u32', 'u32'], ['s32', 's32'], ['f32', 'float32'], ['u32sw', 'u32 swap'], ['s32sw', 's32 swap'], ['f32sw', 'float32 swap']],

    $(id) { return document.getElementById(id); },

    load() {
        return App.api('/api/modbus/info').then(d => {
            const first = !this.info;
            this.info = d;
            if (first) {
                this.profiles = d.profiles.length ? d.profiles : [this._newProfile('Default')];
                this.profiles.forEach(p => p.macros.forEach(m => { if (m.auto === undefined && m.cycle) m.auto = true; }));
                this.cur = d.current || this.profiles[0].name;
                this.$('mb-baud').innerHTML = d.bauds.map(b => `<option>${b}</option>`).join('');
                this.$('mbq-fn').innerHTML = this.FUNCS.map(([k, l]) => `<option value="${k}">${esc(l)}</option>`).join('');
                this.$('mbq-fmt').innerHTML = this.FORMATS.map(([k, l]) => `<option value="${k}">${esc(l)}</option>`).join('');
                ['mbq-unit', 'mbq-addr', 'mbq-cnt'].forEach(id => this.$(id).addEventListener('keydown', e => { if (e.key === 'Enter') this.runQuick(); }));
                const ta = this.$('mb-note');
                ta.addEventListener('input', () => this._noteSave());
                ta.addEventListener('keydown', e => { if (e.key === 'Escape') { e.stopPropagation(); this.noteToggle(false); } });
                this.quickFn();
            }
            this._ports();
            this.$('mb-blocked').textContent = d.blocked || '';
            if (first) this.render();
            return this.listSessions();
        });
    },

    onHide() { this.stopCycle(); this.scanning = false; },

    _newProfile(name) {
        const port = this.info && this.info.ports.find(p => /USB|ACM/.test(p.device));
        return { name, period: 1000, conn: { transport: 'rtu', port: port ? port.device : '/dev/ttyUSB0', baud: '9600', parity: 'N', bytesize: '8',
                 stopbits: '1', host: '', netport: '502', timeout: '300' },
                 macros: [{ name: 'Holding 0…9', unit: '1', fn: '3', addr: '0', count: '10', values: '', fmt: 'u16', note: '' }] };
    },

    prof() { return this.profiles.find(p => p.name === this.cur) || this.profiles[0]; },

    _ports() {
        const c = this.prof().conn, list = this.info.ports.slice();
        if (c.port && !list.some(p => p.device === c.port)) list.push({ device: c.port, description: 'not present' });
        this.$('mb-port').innerHTML = list.map(p => `<option value="${esc(p.device)}"${p.device === c.port ? ' selected' : ''}>` +
            `${esc(p.device)}${p.description ? ' · ' + esc(p.description) : ''}</option>`).join('') || '<option value="">no serial port</option>';
    },

    // ── Render ─────────────────────────────────────────────

    render() {
        if (!this.info) return;
        const p = this.prof(), c = p.conn;
        this.cur = p.name;
        this.$('mb-prof').innerHTML = this.profiles.map(x => `<option${x.name === p.name ? ' selected' : ''}>${esc(x.name)}</option>`).join('');
        this.$('mb-transport').value = c.transport || 'rtu';
        this._ports();
        this.$('mb-baud').value = String(c.baud || 9600);
        this.$('mb-frame').value = `${c.bytesize || 8}${c.parity || 'N'}${c.stopbits || 1}`;
        this.$('mb-host').value = c.host || '';
        this.$('mb-netport').value = c.netport || 502;
        this.$('mb-timeout').value = c.timeout || 300;
        this.$('mb-period').value = p.period || 1000;
        this._connVisibility();
        this.renderRows();
        this._cycleUi();
        this._setNote(p.note);
        this._renderLog();
    },

    _connVisibility() {
        const serial = this.$('mb-transport').value === 'rtu';
        document.querySelector('#devpane-modbus .mb-serial').hidden = !serial;
        document.querySelector('#devpane-modbus .mb-net').hidden = serial;
    },

    _isRead(fn) { return [1, 2, 3, 4].includes(+fn); },
    _isBits(fn) { return [1, 2, 5, 15].includes(+fn); },

    /** Rows of a section with their global index: auto = the timer table below, else the manual table. */
    _section(auto) {
        return this.prof().macros.map((m, i) => [m, i]).filter(([m]) => !!m.auto === auto);
    },

    _rowHtml(m, i) {
        const opt = (list, v) => list.map(([k, l]) => `<option value="${k}"${String(k) === String(v) ? ' selected' : ''}>${esc(l)}</option>`).join('');
        const read = this._isRead(m.fn), bits = this._isBits(m.fn), auto = !!m.auto;
        return `<tr data-i="${i}">` +
            (auto ? `<td><input type="checkbox" data-f="cycle"${m.cycle ? ' checked' : ''} title="Timer on for this row"></td>` : '') +
            `<td><input class="input input-sm mb-name" data-f="name" value="${esc(m.name)}" placeholder="name"></td>` +
            `<td><input class="input input-sm mono mb-unit" data-f="unit" value="${esc(m.unit)}"></td>` +
            `<td><select class="input input-sm mb-fn" data-f="fn">${opt(this.FUNCS, m.fn)}</select></td>` +
            `<td><input class="input input-sm mono mb-addr" data-f="addr" value="${esc(m.addr)}"></td>` +
            `<td>${read ? `<input class="input input-sm mono mb-count" data-f="count" value="${esc(m.count)}" title="Registers / bits to read">`
                        : `<input class="input input-sm mono mb-vals" data-f="values" value="${esc(m.values)}" placeholder="${esc(this._placeholder(m))}">`}</td>` +
            `<td>${bits ? '<span class="faint small">bits</span>' : `<select class="input input-sm mb-fmt" data-f="fmt">${opt(this.FORMATS, m.fmt || 'u16')}</select>`}</td>` +
            (auto ? `<td><input class="input input-sm mono mb-every" data-f="period" type="number" min="50" step="50" value="${esc(m.period || this.prof().period || 1000)}" title="Period of this row, ms"></td>` : '') +
            `<td class="mb-act"><button class="btn-icon text-ok" data-a="run" title="Run now"><i class="fa-solid fa-play"></i></button>` +
            `<button class="btn-icon" data-a="up" title="Up"><i class="fa-solid fa-arrow-up"></i></button>` +
            `<button class="btn-icon" data-a="down" title="Down"><i class="fa-solid fa-arrow-down"></i></button>` +
            `<button class="btn-icon" data-a="dup" title="Duplicate"><i class="fa-regular fa-clone"></i></button>` +
            `<button class="btn-icon" data-a="move" title="${auto ? 'Move to the manual table' : 'Move to the automatic (timer) table'}">` +
            `<i class="fa-solid ${auto ? 'fa-hand-pointer' : 'fa-clock'}"></i></button>` +
            `<button class="btn-icon" data-a="del" title="Delete"><i class="fa-solid fa-xmark"></i></button></td>` +
            `<td class="mb-res" id="mb-res-${i}">${this._resultHtml(m, this.results[i])}</td></tr>`;
    },

    renderRows() {
        const man = this._section(false), auto = this._section(true);
        this.$('mb-rows').innerHTML = man.map(([m, i]) => this._rowHtml(m, i)).join('') ||
            '<tr><td colspan="9" class="tbl-empty">No manual rows — “+ Row” adds one.</td></tr>';
        this.$('mb-auto-rows').innerHTML = auto.map(([m, i]) => this._rowHtml(m, i)).join('') ||
            '<tr><td colspan="11" class="tbl-empty">No timer rows — “+ Timer row”, or move a manual row here with <i class="fa-solid fa-clock"></i>.</td></tr>';
        for (const id of ['mb-rows', 'mb-auto-rows']) {
            const body = this.$(id);
            body.oninput = e => this._rowInput(e);
            body.onchange = e => this._rowInput(e, true);
            body.onclick = e => this._rowClick(e);
        }
        Devices.summary(`${man.length} manual · ${auto.length} timer row(s) · ${this._connText()}`, this.id);
    },

    _connText() {
        const c = this.prof().conn;
        return c.transport === 'rtu' ? `${c.port} ${c.baud} ${c.bytesize}${c.parity}${c.stopbits}` : `${c.transport} ${c.host}:${c.netport}`;
    },

    _rowInput(e, change) {
        const t = e.target, tr = t.closest('tr[data-i]');
        if (!tr || !t.dataset.f) return;
        const m = this.prof().macros[+tr.dataset.i], f = t.dataset.f;
        m[f] = t.type === 'checkbox' ? t.checked : f === 'period' ? Math.max(50, parseInt(t.value, 10) || 1000) : t.value;
        if (f === 'period' || f === 'cycle') this._due[+tr.dataset.i] = 0;          // re-plan this row now
        if (change && f === 'fn') { this.results[+tr.dataset.i] = null; this.renderRows(); }
        else if (change && f === 'fmt') {
            this.$('mb-res-' + tr.dataset.i).innerHTML = this._resultHtml(m, this.results[+tr.dataset.i]);
            const v = tr.querySelector('.mb-vals');
            if (v) v.placeholder = this._placeholder(m);
        }
        this.save();
    },

    _rowClick(e) {
        const b = e.target.closest('[data-a]'), tr = e.target.closest('tr[data-i]');
        if (!b || !tr) return;
        const i = +tr.dataset.i, rows = this.prof().macros, m = rows[i];
        const same = this._section(!!m.auto).map(([, k]) => k), pos = same.indexOf(i);
        const swap = (a, c) => { [rows[a], rows[c]] = [rows[c], rows[a]]; [this.results[a], this.results[c]] = [this.results[c], this.results[a]]; };
        switch (b.dataset.a) {
            case 'run': return this.runRows([i]);
            case 'up': if (pos > 0) swap(i, same[pos - 1]); break;              // within its own table
            case 'down': if (pos < same.length - 1) swap(i, same[pos + 1]); break;
            case 'dup': rows.splice(i + 1, 0, Object.assign({}, m, { name: m.name + ' copy' })); this.results.splice(i + 1, 0, null); break;
            case 'move': m.auto = !m.auto; if (m.auto) { m.cycle = true; m.period = m.period || this.prof().period || 1000; } break;
            case 'del': rows.splice(i, 1); this.results.splice(i, 1); break;
        }
        this._due = {};
        this.renderRows(); this.save();
    },

    addRow(auto = false) {
        const rows = this.prof().macros, sec = this._section(auto), last = sec.length ? sec[sec.length - 1][0] : null;
        rows.push(last ? Object.assign({}, last, { name: '' }) :
                         { name: '', unit: '1', fn: '3', addr: '0', count: '1', values: '', fmt: 'u16', note: '',
                           auto, cycle: auto, period: auto ? (this.prof().period || 1000) : undefined });
        this.renderRows(); this.save();
        const inputs = this.$(auto ? 'mb-auto-rows' : 'mb-rows').querySelectorAll('.mb-name');
        if (inputs.length) inputs[inputs.length - 1].focus();
    },

    // ── Formats ────────────────────────────────────────────

    /** Example of the values to write for the row's function and format (placeholder of the values field). */
    _placeholder(m) {
        const fn = +m.fn, one = fn === 5 || fn === 6;
        if (this._isBits(fn)) return one ? '1  (or 0, on, off)' : '1 0 1 1  (on / off)';
        const ex = {
            u16: ['100', '100, 0x10, 65535'], s16: ['-5', '-5, 120, -32768'], hex: ['0x00FF', '0x00FF, 0x1234'],
            bin: ['0b1010', '0b1010, 0b1'], ascii: ['AB', 'text (2 chars per register)'],
            u32: ['70000', '70000, 0x10000'], s32: ['-100000', '-100000, 42'], f32: ['12.5', '12.5, -0.75'],
            u32sw: ['70000', '70000, 0x10000'], s32sw: ['-100000', '-100000, 42'], f32sw: ['12.5', '12.5, -0.75'],
        }[m.fmt || 'u16'] || ['100', '100, 0x10'];
        if (one && /32/.test(m.fmt || '')) return '32-bit needs 2 registers → use 16';
        return one ? ex[0] : ex[1];
    },

    _num(s) {
        s = String(s).trim().toLowerCase();
        if (/^-?0x[0-9a-f]+$/.test(s)) return parseInt(s, 16);
        if (/^-?0b[01]+$/.test(s)) return (s[0] === '-' ? -1 : 1) * parseInt(s.replace(/^-?0b/, ''), 2);
        if (/^-?\d+$/.test(s)) return parseInt(s, 10);
        return NaN;
    },

    /** Raw registers -> [{addr, text}] in the row format. */
    decode(m, vals) {
        const a0 = this._num(m.addr) || 0;
        if (this._isBits(m.fn)) return vals.map((v, i) => ({ addr: a0 + i, text: String(v) }));
        const fmt = m.fmt || 'u16';
        if (fmt === 'ascii') {
            const s = vals.map(v => String.fromCharCode(v >> 8, v & 255)).join('').replace(/[^\x20-\x7e]/g, '·');
            return [{ addr: a0, text: '"' + s + '"' }];
        }
        if (['u16', 's16', 'hex', 'bin'].includes(fmt)) {
            return vals.map((v, i) => ({ addr: a0 + i, text: fmt === 's16' ? String(v > 32767 ? v - 65536 : v)
                : fmt === 'hex' ? '0x' + v.toString(16).toUpperCase().padStart(4, '0')
                : fmt === 'bin' ? v.toString(2).padStart(16, '0').replace(/(\d{4})(?=\d)/g, '$1 ') : String(v) }));
        }
        const out = [], sw = fmt.endsWith('sw'), base = fmt.replace('sw', '');
        const dv = new DataView(new ArrayBuffer(4));
        for (let i = 0; i + 1 < vals.length; i += 2) {
            const hi = sw ? vals[i + 1] : vals[i], lo = sw ? vals[i] : vals[i + 1];
            dv.setUint16(0, hi); dv.setUint16(2, lo);
            const v = base === 'f32' ? +dv.getFloat32(0).toPrecision(7) : base === 's32' ? dv.getInt32(0) : dv.getUint32(0);
            out.push({ addr: a0 + i, text: String(v) });
        }
        if (vals.length % 2) out.push({ addr: a0 + vals.length - 1, text: 'odd count' });
        return out;
    },

    /** Row values text -> raw u16 / bit list for a write (throws on a bad value). */
    encode(m) {
        const fn = +m.fn, text = String(m.values || '');
        if (this._isBits(fn)) {
            const bits = text.split(/[\s,;]+/).filter(Boolean).map(t => {
                const s = t.toLowerCase();
                if (['1', 'on', 'true'].includes(s)) return 1;
                if (['0', 'off', 'false'].includes(s)) return 0;
                throw new Error(`"${t}" is not a bit (1 0 on off)`);
            });
            if (!bits.length) throw new Error('no values');
            return bits;
        }
        const fmt = m.fmt || 'u16';
        if (fmt === 'ascii') {
            const s = text.length % 2 ? text + '\0' : text, regs = [];
            for (let i = 0; i < s.length; i += 2) regs.push((s.charCodeAt(i) & 255) << 8 | (s.charCodeAt(i + 1) & 255));
            return regs;
        }
        const toks = text.split(/[\s,;]+/).filter(Boolean);
        if (!toks.length) throw new Error('no values');
        const regs = [], dv = new DataView(new ArrayBuffer(4)), base = fmt.replace('sw', ''), sw = fmt.endsWith('sw');
        for (const t of toks) {
            if (['u16', 's16', 'hex', 'bin'].includes(fmt)) {
                const v = this._num(t);
                if (isNaN(v) || v < -32768 || v > 65535) throw new Error(`"${t}" is not a 16-bit value`);
                regs.push(v & 0xFFFF);
                continue;
            }
            if (base === 'f32') { const f = parseFloat(t); if (isNaN(f)) throw new Error(`"${t}" is not a number`); dv.setFloat32(0, f); }
            else {
                const v = this._num(t);
                if (isNaN(v) || v < -2147483648 || v > 4294967295) throw new Error(`"${t}" is not a 32-bit value`);
                dv.setUint32(0, v >>> 0);
            }
            const hi = dv.getUint16(0), lo = dv.getUint16(2);
            regs.push(...(sw ? [lo, hi] : [hi, lo]));
        }
        return regs;
    },

    _op(m) {
        const fn = +m.fn, op = { unit: this._num(m.unit), fn, addr: this._num(m.addr) };
        if (isNaN(op.unit)) throw new Error('unit id is not a number');
        if (isNaN(op.addr)) throw new Error('address is not a number');
        if (this._isRead(fn)) {
            op.count = this._num(m.count);
            if (isNaN(op.count) || op.count < 1) throw new Error('count is not a number');
        } else {
            op.values = this.encode(m);
            if (fn === 6 && op.values.length !== 1) throw new Error('function 06 writes one register — use 16 for more');
            if (fn === 5 && op.values.length !== 1) throw new Error('function 05 writes one coil — use 15 for more');
        }
        return op;
    },

    _resultHtml(m, r) {
        if (!r) return '';
        const when = `<span class="mb-ms" title="${esc(new Date(r.at).toLocaleTimeString())}">${r.ms != null ? r.ms + ' ms' : ''}</span>`;
        if (!r.ok) return `<span class="text-error mb-err" title="${esc(r.error)}">${esc(r.error)}</span> ${when}`;
        if (!r.values) return `<span class="text-ok">${r.broadcast ? 'sent (broadcast)' : 'written'}</span> ${when}`;
        const items = this.decode(m, r.values);
        const shown = items.slice(0, 48).map(x => `<span class="mb-v" title="address ${x.addr} (0x${x.addr.toString(16).toUpperCase()})">` +
            (items.length > 1 ? `<i>${x.addr}</i>` : '') + `${esc(x.text)}</span>`).join('');
        return shown + (items.length > 48 ? `<span class="faint small">+${items.length - 48}</span>` : '') + ' ' + when;
    },

    // ── Running ────────────────────────────────────────────

    _conn() {
        const c = this.prof().conn;
        return { transport: c.transport, port: c.port, baud: c.baud, parity: c.parity, bytesize: c.bytesize, stopbits: c.stopbits,
                 host: c.host, netport: c.netport, timeout: c.timeout };
    },

    /** Run rows by index in one request; ``quiet`` = cycle (log only when "log cycles" is on). */
    runRows(idx, quiet) {
        const rows = this.prof().macros, ops = [], map = [];
        for (const i of idx) {
            try { ops.push(this._op(rows[i])); map.push(i); }
            catch (e) { this.results[i] = { ok: false, error: e.message, at: Date.now() }; this.$('mb-res-' + i).innerHTML = this._resultHtml(rows[i], this.results[i]); }
        }
        if (!ops.length) return Promise.resolve();
        this.busy = true;
        this.$('mb-port-state').textContent = '';
        return App.api('/api/modbus/request', { json: { conn: this._conn(), ops } }).then(d => {
            d.results.forEach((r, k) => {
                const i = map[k];
                r.at = Date.now();
                this.results[i] = r;
                const cell = this.$('mb-res-' + i);
                if (cell) cell.innerHTML = this._resultHtml(rows[i], r);
                if (!quiet || this.$('mb-log-cycle').checked) this._logAdd(rows[i], ops[k], r);
            });
        }).catch(e => {
            if (!quiet) toast(e.message, true);
            map.forEach(i => { this.results[i] = { ok: false, error: e.message, at: Date.now() }; const c = this.$('mb-res-' + i); if (c) c.innerHTML = this._resultHtml(rows[i], this.results[i]); });
            if (quiet && /locked|busy|Cannot open|connect/i.test(e.message)) { this.stopCycle(); toast('Cycle stopped: ' + e.message, true); }
        }).finally(() => { this.busy = false; });
    },

    /** Stop everything that uses the port; the link is opened per request, so it is free afterwards. */
    release() {
        this.stopCycle();
        this.scanning = false;
        const wait = () => this.busy ? setTimeout(wait, 50) : (this.$('mb-port-state').textContent = 'port closed', toast('Port released'));
        wait();
    },

    runAll() { this.runRows(this.prof().macros.map((_, i) => i)); },

    _due: {},                // row index -> next run time (performance.now), 0 = now

    /** Timer rows that are on. */
    _cycleRows() {
        return this.prof().macros.map((m, i) => m.auto && m.cycle ? i : -1).filter(i => i >= 0);
    },

    toggleCycle() { this.cycleOn ? this.stopCycle() : this.startCycle(); },

    /** One scheduler for all timer rows: rows that are due go out together in one request, the next request only
        after the answer (the bus is never flooded); each row is then planned again after its own period. */
    startCycle() {
        if (!this._cycleRows().length) return toast('No timer rows switched on', true);
        this.cycleOn = true; this.cycleCount = 0; this._due = {};
        const tick = () => {
            if (!this.cycleOn) return;
            const now = performance.now(), rows = this.prof().macros, on = this._cycleRows();
            if (!on.length) { this.stopCycle(); return; }
            const due = on.filter(i => !(this._due[i] > now));
            if (!due.length) {
                const next = Math.min(...on.map(i => this._due[i]));
                this.cycleTimer = setTimeout(tick, Math.max(5, Math.min(250, next - now)));
                return;
            }
            due.forEach(i => { this._due[i] = now + Math.max(50, +rows[i].period || this.prof().period || 1000); });
            this.runRows(due, true).finally(() => {
                this.cycleCount++;
                const dt = Math.round(performance.now() - now);
                this.$('mb-cycle-info').textContent = `#${this.cycleCount} · ${due.length} row(s) · ${dt} ms · ${new Date().toLocaleTimeString()}`;
                if (this.cycleOn) this.cycleTimer = setTimeout(tick, 5);
            });
        };
        tick();
        this._cycleUi();
    },

    stopCycle() {
        this.cycleOn = false;
        clearTimeout(this.cycleTimer);
        this.cycleTimer = null;
        this._cycleUi();
    },

    _cycleUi() {
        const b = this.$('mb-cycle');
        b.classList.toggle('btn-warning', this.cycleOn);
        b.classList.toggle('btn-ghost', !this.cycleOn);
        b.innerHTML = this.cycleOn ? '<i class="fa-solid fa-stop"></i> Stop timers' : '<i class="fa-solid fa-repeat"></i> Start timers';
        const st = this.$('mb-auto-state');
        if (st) st.innerHTML = this.cycleOn ? '<span class="badge badge-ok">running</span>' : '<span class="badge">stopped</span>';
    },

    periodInput() {
        const v = parseInt(this.$('mb-period').value, 10);
        if (v >= 50) { this.prof().period = v; this.save(); }
    },

    connInput() {
        const c = this.prof().conn, f = this.$('mb-frame').value;
        Object.assign(c, { transport: this.$('mb-transport').value, port: this.$('mb-port').value, baud: this.$('mb-baud').value,
                           bytesize: f[0], parity: f[1], stopbits: f[2], host: this.$('mb-host').value.trim(),
                           netport: this.$('mb-netport').value, timeout: this.$('mb-timeout').value });
        if (['tcp', 'udp'].includes(c.transport) && !this.$('mb-netport').value) this.$('mb-netport').value = c.netport = '502';
        this._connVisibility();
        Devices.summary(`${this.prof().macros.length} row(s) · ${this._connText()}`, this.id);
        this.save();
    },

    // ── Scan ───────────────────────────────────────────────

    toggleScan() { this.$('mb-scan').hidden = !this.$('mb-scan').hidden; },

    scan() {
        if (this.scanning) { this.scanning = false; return; }
        const first = +this.$('mbs-first').value || 1, last = Math.min(247, +this.$('mbs-last').value || 247);
        const fn = +this.$('mbs-fn').value, addr = this._num(this.$('mbs-addr').value) || 0, timeout = +this.$('mbs-timeout').value || 80;
        const found = this.found = [], btn = this.$('mbs-go');
        this.scanning = true;
        btn.innerHTML = '<i class="fa-solid fa-stop"></i> Stop';
        const show = (u) => {
            this.$('mbs-info').textContent = this.scanning ? `scanning ${u}…${last}` : `done ${first}…${last}`;
            this._renderFound();
        };
        const step = (u) => {
            if (!this.scanning || u > last) {
                this.scanning = false;
                btn.innerHTML = '<i class="fa-solid fa-magnifying-glass"></i> Start';
                show(last);
                return;
            }
            show(u);
            const to = Math.min(last, u + 15);
            App.api('/api/modbus/scan', { json: { conn: this._conn(), first: u, last: to, fn, addr, timeout } })
                .then(d => { found.push(...d.found.filter(f => !f.noise)); step(to + 1); })
                .catch(e => { toast(e.message, true); this.scanning = false; step(last + 1); });
        };
        step(first);
    },

    _renderFound() {
        const el = this.$('mbs-found');
        el.innerHTML = this.found.length ? this.found.map(f => `<span class="mb-unit-chip${f.ok ? '' : ' exc'}" title="${esc(f.error || 'answered')}">` +
            `unit <b>${f.unit}</b>${f.ms ? ` · ${f.ms} ms` : ''}${f.error ? ' · ' + esc(f.error) : ''}` +
            ` <button class="btn-icon" data-unit="${f.unit}" title="Add a read row for this unit"><i class="fa-solid fa-plus"></i></button></span>`).join('')
            : '<span class="hint">no device answered yet</span>';
        el.onclick = e => {
            const b = e.target.closest('[data-unit]');
            if (!b) return;
            const fn = this.$('mbs-fn').value, addr = this.$('mbs-addr').value || '0';
            this.prof().macros.push({ name: `unit ${b.dataset.unit}`, unit: b.dataset.unit, fn, addr, count: '10', values: '', fmt: 'u16', cycle: false, note: '' });
            this.renderRows(); this.save();
        };
    },

    // ── Quick request line ─────────────────────────────────

    /** The quick request as a row object (same shape as the table rows). */
    _quick() {
        const fn = this.$('mbq-fn').value, read = this._isRead(fn), cnt = this.$('mbq-cnt').value.trim();
        return { name: 'quick', unit: this.$('mbq-unit').value.trim() || '1', fn, addr: this.$('mbq-addr').value.trim() || '0',
                 count: read ? cnt : '', values: read ? '' : cnt, fmt: this.$('mbq-fmt').value };
    },

    quickFn() {
        const fn = this.$('mbq-fn').value, read = this._isRead(fn), cnt = this.$('mbq-cnt');
        cnt.title = read ? 'Registers / bits to read' : 'Values to write';
        cnt.placeholder = read ? 'count' : this._placeholder({ fn, fmt: this.$('mbq-fmt').value });
        if (read && !/^\s*(0x[0-9a-f]+|\d+)\s*$/i.test(cnt.value)) cnt.value = '1';
        this.$('mbq-fmt').disabled = this._isBits(fn);
    },

    /** Put a row (or a parsed tag) into the quick request line. */
    fillQuick(m) {
        this.$('mbq-unit').value = m.unit || '1';
        this.$('mbq-fn').value = String(m.fn);
        this.$('mbq-addr').value = m.addr;
        this.$('mbq-fmt').value = m.fmt || 'u16';
        this.$('mbq-cnt').value = this._isRead(m.fn) ? (m.count || '1') : (m.values || '');
        this.quickFn();
    },

    runQuick() {
        const m = this._quick(), res = this.$('mbq-res');
        let op;
        try { op = this._op(m); } catch (e) { res.innerHTML = `<span class="text-error">${esc(e.message)}</span>`; return Promise.resolve(); }
        res.innerHTML = '<span class="faint">…</span>';
        return App.api('/api/modbus/request', { json: { conn: this._conn(), ops: [op] } }).then(d => {
            const r = Object.assign(d.results[0], { at: Date.now() });
            res.innerHTML = this._resultHtml(m, r);
            this._logAdd(m, op, r);
        }).catch(e => { res.innerHTML = `<span class="text-error">${esc(e.message)}</span>`; });
    },

    quickToRow() {
        const m = this._quick();
        this.prof().macros.push(Object.assign(m, { name: '', auto: false, note: '' }));
        this.renderRows(); this.save();
        toast('Added to the manual table');
    },

    // ── Notes with [[register]] tags ───────────────────────
    // [[03 4 3 ascii]]  [[03 20 2 s32sw u2]]  [[06 100 =1]]  [[16 200 =12.5 f32]]  [[05 3 =on]]  [[15 0 =1 0 1]]

    /** Tag text -> row object, or {error}. Tokens: function, address, count (reads) or =values (writes),
        optional format and uN (unit, default 1). */
    parseTag(text) {
        const toks = text.trim().split(/\s+/), fmts = this.FORMATS.map(f => f[0]);
        const fn = this._num(toks[0]);
        if (!this.FUNCS.some(f => f[0] === fn)) return { error: `unknown function "${toks[0]}" (01–06, 15, 16)` };
        if (toks.length < 2 || isNaN(this._num(toks[1]))) return { error: 'address missing' };
        const m = { name: '', unit: '1', fn: String(fn), addr: toks[1], count: '', values: '', fmt: 'u16' };
        const vals = [];
        let inVals = false;
        for (const t of toks.slice(2)) {
            if (/^u\d+$/i.test(t)) m.unit = t.slice(1);
            else if (fmts.includes(t.toLowerCase())) m.fmt = t.toLowerCase();
            else if (t.startsWith('=')) { inVals = true; if (t.length > 1) vals.push(t.slice(1)); }
            else if (inVals) vals.push(t);
            else if (this._isRead(fn) && !m.count && !isNaN(this._num(t))) m.count = t;
            else return { error: `unexpected "${t}"` };
        }
        if (this._isRead(fn)) m.count = m.count || '1';
        else if (!vals.length) return { error: 'values missing: =…' };
        m.values = vals.join(' ');
        return m;
    },

    _tagText(m) {
        const fn = String(m.fn).padStart(2, '0'), read = this._isRead(m.fn);
        return `[[${fn} ${m.addr} ${read ? m.count || 1 : '=' + m.values}` + (this._isBits(m.fn) || (m.fmt || 'u16') === 'u16' ? '' : ' ' + m.fmt) +
               (String(m.unit || '1') !== '1' ? ' u' + m.unit : '') + ']]';
    },

    _tagTitle(m) {
        const fn = (this.FUNCS.find(f => String(f[0]) === String(m.fn)) || [0, ''])[1];
        return `${fn} · unit ${m.unit} · address ${m.addr}` + (this._isRead(m.fn) ? ` · count ${m.count}` : ` · values ${m.values}`) +
               (this._isBits(m.fn) ? '' : ` · ${m.fmt}`);
    },

    renderNote() {
        const text = this.$('mb-note').value, view = this.$('mb-note-view'), tags = [];
        const html = esc(text).replace(/\[\[([\s\S]+?)\]\]/g, (all, c) => {
            const raw = c.replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&#39;/g, "'");
            const m = this.parseTag(raw);
            if (m.error) return `<span class="tt-cmdtag mb-badtag" title="${esc(m.error)}">${esc(raw)} ⚠</span>`;
            tags.push(m);
            return `<span class="tt-cmdtag" data-tag="${tags.length - 1}" title="${esc(this._tagTitle(m))}"><span>${esc(raw.trim())}</span>` +
                `<button class="btn-icon" data-na="fill" title="Fill the request line"><i class="fa-solid fa-arrow-down"></i></button>` +
                `<button class="btn-icon text-ok" data-na="run" title="Run now (with the connection above)"><i class="fa-solid fa-play"></i></button></span>`;
        });
        view.innerHTML = html || '<span class="faint">No notes yet — Edit (or double-click) to write the register map. ' +
            'Registers in [[ ]] become buttons, e.g. [[03 4 3 ascii]] or [[06 100 =1]] — see Examples.</span>';
        view.onclick = e => {
            const tag = e.target.closest('[data-tag]');
            if (!tag) return;
            this.fillQuick(tags[+tag.dataset.tag]);
            const b = e.target.closest('[data-na]');
            if (b && b.dataset.na === 'run') this.runQuick();
        };
        view.ondblclick = e => { if (!e.target.closest('[data-tag]')) this.noteToggle(true); };
    },

    noteToggle(edit) {
        const ta = this.$('mb-note'), view = this.$('mb-note-view');
        const editing = edit === undefined ? ta.hidden : edit;
        ta.hidden = !editing; view.hidden = editing;
        this.$('mb-note-edit').innerHTML = editing ? '<i class="fa-solid fa-check"></i> Done' : '<i class="fa-solid fa-pen"></i> Edit';
        if (editing) ta.focus(); else { this.renderNote(); this._noteSave(); }
    },

    noteInsert() {
        const ta = this.$('mb-note'), m = this._quick();
        try { this._op(m); } catch (e) { return toast(e.message, true); }
        ta.value = (ta.value && !ta.value.endsWith('\n') ? ta.value + '\n' : ta.value) + this._tagText(m);
        this.renderNote(); this._noteSave();
    },

    noteExamples() {
        Devices.showText('Modbus tags in the notes', Promise.resolve([
            'Write [[function address count format uN]] to read, [[function address =values format uN]] to write.',
            'Format (u16 if omitted): u16 s16 hex bin ascii u32 s32 f32 u32sw s32sw f32sw.  uN = unit id (u1 if omitted).',
            'In the notes view: ⇩ fills the request line, ▶ runs it with the connection above.',
            '',
            '  firmware version     [[03 4 3 ascii]]         3 holding registers from 4 as text',
            '  status block         [[03 0 4]]               holding 0…3 as u16',
            '  status in hex        [[03 0 12 hex]]',
            '  power (float)        [[04 10 2 f32]]          input registers 10–11 as float32',
            '  energy, unit 2       [[03 20 2 s32sw u2]]     signed 32-bit, word order CDAB',
            '  coils 0…7            [[01 0 8]]',
            '  start charging       [[06 100 =1]]            write one register',
            '  set current limit    [[16 200 =12.5 f32]]     a float = 2 registers',
            '  set two registers    [[16 300 =10, 0x20]]',
            '  relay 3 on           [[05 3 =on]]',
            '  four coils           [[15 0 =1 0 1 1]]',
            '  device name          [[16 50 =EVSE-01 ascii]]',
            '',
            'Example notes:',
            '  Charger J1772 (unit 1, 115200 8N1). Only function 03 is supported.',
            '  Firmware [[03 4 3 ascii]], model [[03 7 5 ascii]], state block [[03 0 4]].',
        ].join('\n')));
    },

    _noteSave() { this.prof().note = this.$('mb-note').value; this.save(); },

    _setNote(text) { this.$('mb-note').value = text || ''; this.noteToggle(false); },

    // ── Sessions (files on the controller) ─────────────────

    listSessions() {
        return App.api('/api/modbus/sessions').then(d => { this.sessions = d.sessions; this._renderSessions(); });
    },

    _renderSessions() {
        const fmt = t => new Date(t * 1000).toLocaleString([], { dateStyle: 'short', timeStyle: 'short' });
        this.$('mb-sess').innerHTML = `<option value="">${this.sessions.length ? '— open a session —' : '— no saved sessions —'}</option>` +
            this.sessions.map(s => `<option value="${esc(s.name)}"${s.name === this.session ? ' selected' : ''}>${esc(s.name)} · ${s.rows} row(s) · ${esc(fmt(s.saved))}</option>`).join('');
    },

    saveSession() {
        const def = this.session || `${this.prof().name} ${new Date().toISOString().slice(0, 10)}`;
        const name = (prompt('Session name:', def) || '').trim();
        if (!name) return;
        const p = this.prof();
        const data = { profile: { conn: p.conn, macros: p.macros, period: p.period }, results: this.results, found: this.found,
                       note: this.$('mb-note').value, log: this.log.map(x => Object.assign({}, x, { t: +x.t })) };
        p.note = this.$('mb-note').value;
        const send = overwrite => App.api('/api/modbus/session/save', { json: { name, data, overwrite } }).then(r => {
            this.session = r.name; this.sessions = r.sessions; this._renderSessions();
            toast(`Session "${r.name}" saved`);
        });
        send(false).catch(e => {
            if (/already exists/.test(e.message) && confirm(`Session "${name}" exists. Overwrite it?`)) return send(true).catch(x => toast(x.message, true));
            toast(e.message, true);
        });
    },

    loadSession(name) {
        if (!name) return;
        App.api('/api/modbus/session?name=' + encodeURIComponent(name)).then(d => {
            this.stopCycle();
            const prof = Object.assign({ name: d.name, period: 1000, conn: {}, macros: [] }, d.profile, { name: d.name });
            const i = this.profiles.findIndex(p => p.name === prof.name);
            if (i >= 0) this.profiles[i] = prof; else this.profiles.push(prof);
            this.cur = prof.name;
            this.results = Array.isArray(d.results) ? d.results : [];
            this.log = (d.log || []).map(x => Object.assign({}, x, { t: new Date(x.t) })).sort((a, b) => a.t - b.t);
            this.found = d.found || [];
            prof.note = d.note || prof.note || '';
            this.session = d.name;
            this.render(); this._renderLog(); this._renderSessions();
            if (this.found.length) { this.$('mb-scan').hidden = false; this._renderFound(); }
            this.save();
            toast(`Session "${d.name}" opened (profile "${prof.name}")`);
        }).catch(e => { toast(e.message, true); this._renderSessions(); });
    },

    deleteSession() {
        const name = this.$('mb-sess').value;
        if (!name) return toast('Choose a session in the list first', true);
        if (!confirm(`Delete session "${name}"?`)) return;
        App.api('/api/modbus/session/delete', { json: { name } }).then(r => {
            if (this.session === name) this.session = '';
            this.sessions = r.sessions; this._renderSessions();
            toast('Session deleted');
        }).catch(e => toast(e.message, true));
    },

    // ── Log ────────────────────────────────────────────────

    _logAdd(m, op, r) {
        this.log.push({ t: new Date(), name: m.name || `unit ${op.unit}`, fn: op.fn, addr: op.addr, r });
        if (this.log.length > 500) this.log.splice(0, this.log.length - 500);
        this._renderLog();
    },

    _renderLog() {
        const el = this.$('mb-log');
        el.innerHTML = this.log.map(x => {
            const t = esc(Devices.fmtMs(x.t / 1000)), head = `<span class="tt-t">${t}</span>`;
            const who = `<span class="mb-lname">${esc(x.name)}</span><span class="mb-lfn">fn ${x.fn} @ ${x.addr}</span>`;
            const tx = x.r.tx ? `<div class="tt-l tx">${head}<span class="tt-dir">›</span>${who}<span class="tt-hex">${esc(x.r.tx)}</span></div>` : '';
            const rx = x.r.rx || !x.r.ok
                ? `<div class="tt-l rx${x.r.ok ? '' : ' err'}">${head}<span class="tt-dir">‹</span>${x.r.tx ? '' : who}<span class="tt-hex">${esc(x.r.rx || '')}</span>` +
                  ` <span class="mb-ms">${x.r.ok ? (x.r.ms != null ? x.r.ms + ' ms' : '') : esc(x.r.error)}</span></div>` : '';
            return tx + rx;
        }).join('') || '<div class="tbl-empty">Run a request: the TX / RX frames appear here.</div>';
        if (this.$('mb-log-scroll').checked) el.scrollTop = el.scrollHeight;
    },

    clearLog() { this.log = []; this._renderLog(); },

    // ── Profiles ───────────────────────────────────────────

    pickProfile(name) {
        this.stopCycle();
        this.cur = name; this.results = [];
        this.render(); this.save();
    },

    _uniqueName(base) {
        let n = base, k = 2;
        while (this.profiles.some(p => p.name === n)) n = `${base} ${k++}`;
        return n;
    },

    profileCmd(cmd) {
        const p = this.prof();
        if (cmd === 'new' || cmd === 'dup') {
            const name = (prompt('Profile name:', this._uniqueName(cmd === 'dup' ? p.name + ' copy' : 'Device')) || '').trim();
            if (!name) return;
            if (this.profiles.some(x => x.name === name)) return toast('Name already used', true);
            const np = cmd === 'dup' ? JSON.parse(JSON.stringify(p)) : this._newProfile(name);
            np.name = name;
            if (cmd === 'new') np.conn = Object.assign({}, p.conn);        // same port by default
            this.profiles.push(np);
            return this.pickProfile(name);
        }
        if (cmd === 'rename') {
            const name = (prompt('New name:', p.name) || '').trim();
            if (!name || name === p.name) return;
            if (this.profiles.some(x => x.name === name)) return toast('Name already used', true);
            p.name = name; this.cur = name;
            this.render(); return this.save();
        }
        if (cmd === 'delete') {
            if (this.profiles.length < 2) return toast('The last profile cannot be deleted', true);
            if (!confirm(`Delete profile "${p.name}" with ${p.macros.length} row(s)?`)) return;
            this.profiles = this.profiles.filter(x => x !== p);
            return this.pickProfile(this.profiles[0].name);
        }
        if (cmd === 'export') {
            const a = document.createElement('a');
            a.href = URL.createObjectURL(new Blob([JSON.stringify(p, null, 2)], { type: 'application/json' }));
            a.download = `modbus_${p.name.replace(/[^\w.-]+/g, '_')}.json`;
            document.body.append(a); a.click();
            setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
        }
    },

    importFile(input) {
        const f = input.files[0];
        input.value = '';
        if (!f) return;
        f.text().then(t => {
            const p = JSON.parse(t);
            if (!p || !Array.isArray(p.macros) || typeof p.conn !== 'object') throw new Error('not a Modbus profile');
            p.name = this._uniqueName(String(p.name || 'Imported'));
            this.profiles.push(p);
            this.pickProfile(p.name);
            toast(`Imported "${p.name}"`);
        }).catch(e => toast('Import failed: ' + e.message, true));
    },

    /** Debounced save of all profiles to config.json of this host. */
    save() {
        clearTimeout(this._saveT);
        this._saveT = setTimeout(() => {
            App.api('/api/modbus/profiles', { json: { profiles: this.profiles, current: this.cur } })
                .catch(e => toast('Modbus profiles not saved: ' + e.message, true));
        }, 1200);
    },
});
