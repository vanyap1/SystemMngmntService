/* ==========================================================================
   HW Utils tab "CAN": SocketCAN tool (open with bitrate, per-ID list with cycle time /
   count — statistics kept by the server, frame trace, send, cyclic send), recording
   to trace files (candump log), a trace player (into the view or onto the bus) and
   the trace files tree on the left (canTraces/: folders, rename, delete, upload).
   TX list (profiles in config.json `can`, like the Terminal's macros): rows sent once
   or cyclically by the server (job tag = row uid); editing a running row updates its
   frame on the fly. Notes with [[ID#data]] frame buttons.
   A file opened from the tree is shown in the "File" mode: its IDs (with the replay
   filter — IDs switched off are not replayed) and its frames page by page.
   The CAN socket, cyclic sends, the recording and the player live only while this
   tab is open (leaving asks first when a recording / replay runs).
   ========================================================================== */

Devices.register({
    id: 'can',
    autoMs: 2000,
    FRAMES_MS: 300,
    MAX_TRACE: 1000,
    RENDER_ROWS: 300,
    data: null,             // /api/net/interfaces
    canIface: '',
    want: '',               // interface to select (set by Network → "CAN tool")
    since: 0,
    trace: [],
    byId: new Map(),        // server per-ID rows (key -> row + changed bytes), like PCAN-View's list
    mode: 'byid',
    page: 'monitor',        // 'monitor' (frames + TX list) | 'traces' (files, player, file view)
    sort: { col: 'id', desc: false },
    skew: 0,                // server clock - browser clock, seconds
    frTimer: null,
    jobs: [],
    counts: { rx: 0, tx: 0, err: 0, rp: 0 },
    lastError: null,
    // traces
    tree: [],
    selected: '',           // file chosen for the player
    folder: '',             // folder for new recordings
    collapsed: new Set(),
    rec: null, recLast: null,
    play: null, playLast: null,
    speeds: [0.1, 0.25, 0.5, 1, 2, 4, 10],
    speed: 1,
    FILE_PAGE: 500,
    file: null,             // opened file: {path, info, start, key (ID filter of the list), page}
    skips: {},              // file path -> [ID keys switched off for the replay]
    profiles: null,         // TX lists: [{name, tx: [{uid, name, id, ext, rtr, data, period, on}], note}]
    cur: '',
    txRes: {},              // row uid -> {ok, text, at} of the last single send
    _upd: {},               // row uid -> pending live-update timer

    onShow() {
        if (!this._bound) this._bind();
        if (!this.frTimer) this.frTimer = setInterval(() => this._pollFrames(), this.FRAMES_MS);
        document.querySelectorAll('.can-modes button').forEach(b => b.classList.toggle('active', b.dataset.mode === this.mode));
        this.setPage(this.page);
        this.loadTree();
        this._renderPlayer();
        if (!this.profiles) this.loadProfiles();
    },

    canLeave() {
        const busy = [this.rec && 'a recording', this.play && 'a replay'].filter(Boolean);
        return !busy.length || confirm(`CAN: ${busy.join(' and ')} is running. Leaving the tab stops it. Leave?`);
    },

    onHide() {
        this.analyzing = false;
        if (typeof CanAnalyzer !== 'undefined') CanAnalyzer.close(true);
        if (typeof CanTxEdit !== 'undefined') CanTxEdit.close();
        clearInterval(this.frTimer);
        this.frTimer = null;
        this._closePop();
        if (!this.canIface) return;
        if (this.rec) this._post('/api/net/can/record', { action: 'stop' }).catch(() => {});
        if (this.play) this._post('/api/net/can/play', { action: 'stop' }).catch(() => {});
        this._stopJobs(this.canIface);
    },

    _bind() {
        this._bound = true;
        try { JSON.parse(localStorage.getItem('can.collapsed') || '[]').forEach(p => this.collapsed.add(p)); } catch (e) { /* none */ }
        try { this.skips = JSON.parse(localStorage.getItem('can.skips') || '{}') || {}; } catch (e) { /* none */ }
        try { if (localStorage.getItem('can.txHidden') === '1') document.getElementById('can-txarea').dataset.off = '1'; } catch (e) { /* none */ }
        this._bindTx();
        try { this.page = localStorage.getItem('can.page') === 'traces' ? 'traces' : 'monitor'; } catch (e) { /* none */ }
        try { if (localStorage.getItem('can.notesHidden') === '1') document.getElementById('can-tx-notes').hidden = true; } catch (e) { /* none */ }
        try { const h = +localStorage.getItem('can.txHeight'); if (h > 80) document.getElementById('can-txarea').style.flexBasis = h + 'px'; } catch (e) { /* none */ }
        try { const w = +localStorage.getItem('can.txWidth'); if (w > 200) document.querySelector('.can-tx-list').style.flexBasis = w + 'px'; } catch (e) { /* none */ }
        this._bindSplit();
        this._bindVSplit();
        if (document.getElementById('can-tx-notes').hidden) {
            document.getElementById('can-vsplit').hidden = true;
            document.querySelector('.can-tx-list').style.flexGrow = '1';
        }
        const fileBox = document.getElementById('can-file');
        fileBox.addEventListener('change', e => {
            const cb = e.target.closest('input[data-skip]');
            if (cb) this.toggleId(cb.dataset.skip, cb.checked);
        });
        fileBox.addEventListener('click', e => {
            const an = e.target.closest('[data-an]');
            if (an) return this.analyze(an.dataset.an, an.dataset.label, an.dataset.file || '');
            const el = e.target.closest('[data-fkey]');
            if (el) this.filterId(el.dataset.fkey);
        });
        const frames = document.getElementById('can-frames');
        frames.addEventListener('change', e => {
            const cb = e.target.closest('input[data-skip]');
            if (cb) this.toggleId(cb.dataset.skip, cb.checked);
        });
        frames.addEventListener('click', e => {
            const an = e.target.closest('[data-an]');
            if (an) return this.analyze(an.dataset.an, an.dataset.label, an.dataset.file || '');
            const el = e.target.closest('[data-fkey]');
            if (el) this.filterId(el.dataset.fkey);
        });
        ['can-id', 'can-data'].forEach(id => document.getElementById(id).addEventListener('keydown', e => {
            if (e.key === 'Enter') this.send();
        }));
        ['can-id', 'can-data', 'can-ext', 'can-rtr'].forEach(id => document.getElementById(id).addEventListener('input', () => this._quickInput()));
        const tree = document.getElementById('can-tree');
        tree.addEventListener('click', e => this._treeClick(e, false));
        tree.addEventListener('dblclick', e => this._treeClick(e, true));
        document.addEventListener('mousedown', e => {
            if (!e.target.closest('.can-rec-wrap')) this._closePop();
            if (!e.target.closest('.can-pop-wrap')) document.getElementById('can-link-pop').hidden = true;
        });
    },

    load() {
        return App.api('/api/net/interfaces').then(data => {
            this.data = data;
            this._fillCanSelect();
            const can = this.canIfaces();
            Devices.summary(`${can.length} CAN interface${can.length === 1 ? '' : 's'}`, this.id);
            this._renderCanStatus();
        });
    },

    render() { this._renderCanStatus(); this.renderFrames(true); },

    setPage(page) {
        this.page = page;
        try { localStorage.setItem('can.page', page); } catch (e) { /* private mode */ }
        document.querySelectorAll('.can-pages button').forEach(b => b.classList.toggle('active', b.dataset.page === page));
        document.querySelectorAll('#devpane-can .can-page').forEach(el => {
            el.hidden = el.dataset.page !== page || (el.id === 'can-split' && document.getElementById('can-txarea').dataset.off === '1') ||
                        (el.id === 'can-txarea' && el.dataset.off === '1');
        });
        if (page === 'traces') this.renderFile();
        else this.renderFrames(true);
    },

    _bindSplit() {
        const split = document.getElementById('can-split'), area = document.getElementById('can-txarea');
        split.addEventListener('mousedown', e => {
            e.preventDefault();
            const y0 = e.clientY, h0 = area.getBoundingClientRect().height;
            const main = area.parentElement.getBoundingClientRect().height;
            const move = ev => { area.style.flexBasis = Math.max(90, Math.min(main - 120, h0 + y0 - ev.clientY)) + 'px'; };
            const up = () => {
                document.removeEventListener('mousemove', move);
                document.removeEventListener('mouseup', up);
                try { localStorage.setItem('can.txHeight', String(parseInt(area.style.flexBasis, 10))); } catch (err) { /* private mode */ }
            };
            document.addEventListener('mousemove', move);
            document.addEventListener('mouseup', up);
        });
    },

    /** Vertical splitter: width of the TX list (the notes take the rest). */
    _bindVSplit() {
        const split = document.getElementById('can-vsplit'), list = document.querySelector('.can-tx-list');
        split.addEventListener('mousedown', e => {
            e.preventDefault();
            const x0 = e.clientX, w0 = list.getBoundingClientRect().width;
            const total = list.parentElement.getBoundingClientRect().width;
            const move = ev => { list.style.flexBasis = Math.max(320, Math.min(total - 210, w0 + ev.clientX - x0)) + 'px'; };
            const up = () => {
                document.removeEventListener('mousemove', move);
                document.removeEventListener('mouseup', up);
                try { localStorage.setItem('can.txWidth', String(parseInt(list.style.flexBasis, 10))); } catch (err) { /* private mode */ }
            };
            document.addEventListener('mousemove', move);
            document.addEventListener('mouseup', up);
        });
    },

    toggleNotes() {
        const el = document.getElementById('can-tx-notes');
        el.hidden = !el.hidden;
        document.getElementById('can-vsplit').hidden = el.hidden;
        document.querySelector('.can-tx-list').style.flexGrow = el.hidden ? '1' : '';
        try { localStorage.setItem('can.notesHidden', el.hidden ? '1' : '0'); } catch (e) { /* private mode */ }
    },

    linkMenu() {
        const pop = document.getElementById('can-link-pop');
        pop.hidden = !pop.hidden;
    },

    /** One button: Open when the link is down, Close when it is up. */
    linkToggle() {
        const i = this.canIfaces().find(x => x.name === this.canIface);
        if (i) this.link(i.up ? 'close' : 'open');
    },

    // ── interface ──────────────────────────────────────────────────────────

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
        if (this.want && list.some(i => i.name === this.want)) {
            const name = this.want;
            this.want = '';
            this.selectCan(name);
        } else if (!this.canIface || !list.some(i => i.name === this.canIface)) {
            if (list.length) this.selectCan(list[0].name);
        } else {
            sel.value = this.canIface;
        }
    },

    selectCan(name) {
        if (name === this.canIface) return;
        if (this.canIface) {
            if ((this.rec || this.play) && !confirm(`Switching the interface stops the recording / replay on ${this.canIface}. Continue?`)) {
                document.getElementById('can-iface').value = this.canIface;
                return;
            }
            if (this.rec) this._post('/api/net/can/record', { action: 'stop' }).catch(() => {});
            if (this.play) this._post('/api/net/can/play', { action: 'stop' }).catch(() => {});
            this._stopJobs(this.canIface);
        }
        if (this.analyzing) { CanAnalyzer.close(true); this.analyzing = false; }
        this.canIface = name;
        document.getElementById('can-iface').value = name;
        this.since = 0;
        this.trace = [];
        this.byId = new Map();
        this.jobs = [];
        this.rec = this.play = this.recLast = this.playLast = null;
        this.counts = { rx: 0, tx: 0, err: 0, rp: 0 };
        const i = this.canIfaces().find(x => x.name === name);
        if (i && i.can) {
            if (i.can.bitrate) document.getElementById('can-bitrate').value = String(i.can.bitrate);
            if (i.can.restart_ms != null) document.getElementById('can-restart').value = i.can.restart_ms;
            document.getElementById('can-listen').checked = (i.can.ctrlmode || []).includes('LISTEN-ONLY');
            document.querySelectorAll('#can-config select:not(#can-iface), #can-config input')
                .forEach(el => { el.disabled = !i.can.configurable; });
        }
        this.render();
        this._renderPlayer();
    },

    _renderCanStatus() {
        const i = this.canIfaces().find(x => x.name === this.canIface);
        const badge = document.getElementById('can-state');
        const status = document.getElementById('can-status');
        if (!i) {
            badge.innerHTML = '';
            status.innerHTML = '<span class="muted">No CAN interface (can0, vcan0…) found</span>';
            document.getElementById('can-link-btn').hidden = true;
            return;
        }
        const c = i.can;
        const lb = document.getElementById('can-link-btn');
        lb.hidden = false;
        lb.innerHTML = i.up ? '<i class="fa-solid fa-stop"></i> Close' : '<i class="fa-solid fa-play"></i> Open';
        lb.className = 'btn btn-sm ' + (i.up ? 'btn-stop' : 'btn-start');
        lb.title = i.up ? `Bring ${i.name} down` : `Bring ${i.name} up` + (c.configurable ? ' with the bit timing of ⚙' : '');
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
        document.getElementById('can-link-pop').hidden = true;
        App.api('/api/net/can/link', { json })
            .then(() => { toast(`${iface} ${action === 'open' ? 'opened' : 'closed'}`); Devices.refresh(); })
            .catch(e => toast(e.message, true));
    },

    _post(url, json) {
        return App.api(url, { json: Object.assign({ iface: this.canIface }, json) });
    },

    // ── send ───────────────────────────────────────────────────────────────

    /** The quick send as a row for the frame editor (uid "quick"; fields + period kept in this browser). */
    quickRow() {
        if (!this.quick) {
            let saved = {};
            try { saved = JSON.parse(localStorage.getItem('can.quick') || '{}') || {}; } catch (e) { /* none */ }
            this.quick = { uid: 'quick', quick: true, name: 'Quick send', period: saved.period || 100, fields: saved.fields || [] };
        }
        return Object.assign(this.quick, this._form(), { data: this._form().data.trim() });
    },

    editQuick(btn) {
        CanTxEdit.open(this.quickRow(), btn);
    },

    /** The quick send fields were typed into: the open editor follows; a running quick send is updated. */
    _quickInput() {
        if (!this.quick) return;
        this.rowChanged(this.quickRow(), 'data');
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
        this._post('/api/net/can/send', Object.assign({ action: 'send' }, this._form())).catch(e => toast(e.message, true));
    },

    _stopJobs(iface) {
        if (!this.jobs.length) return;
        this.jobs = [];
        App.api('/api/net/can/send', { json: { iface, action: 'stop_all' } }).catch(() => {});
    },

    releaseOnUnload() {
        if (!this.canIface || !(this.jobs.length || this.rec || this.play)) return;
        const beacon = (url, json) => navigator.sendBeacon(url,
            new Blob([JSON.stringify(Object.assign({ iface: this.canIface }, json))], { type: 'application/json' }));
        if (this.jobs.length) beacon('/api/net/can/send', { action: 'stop_all' });
        if (this.rec) beacon('/api/net/can/record', { action: 'stop' });
        if (this.play) beacon('/api/net/can/play', { action: 'stop' });
    },

    // ── frames ─────────────────────────────────────────────────────────────

    clearFrames() {
        const reset = () => {
            this.trace = [];
            this.byId = new Map();
            this.counts = { rx: 0, tx: 0, err: 0, rp: 0 };
            this.renderFrames(true);
        };
        reset();
        if (this.canIface) this._post('/api/net/can/send', { action: 'clear' }).then(reset).catch(() => {});
    },

    setMode(mode) {
        this.mode = mode;
        document.querySelectorAll('.can-modes button').forEach(b => b.classList.toggle('active', b.dataset.mode === mode));
        this.renderFrames(true);
    },

    _pollFrames() {
        if (!this.canIface || this._polling || this.analyzing) return;     // the analyser polls its own ID only
        this._polling = true;
        const iface = this.canIface;
        App.api(`/api/net/can/frames?iface=${encodeURIComponent(iface)}&since=${this.since}`).then(d => {
            if (iface !== this.canIface) return;
            if (d.next < this.since) { this.since = 0; this.byId = new Map(); }
            (d.ids || []).forEach(r => this._mergeId(r));
            if (d.totals) this.counts = d.totals;
            if (d.now) this.skew = d.now - Date.now() / 1000;
            if (d.frames.length) {
                this.since = d.next;
                this.trace = d.frames.slice().reverse().concat(this.trace).slice(0, this.MAX_TRACE);
            }
            this.lastError = d.error;
            this.jobs = d.jobs;
            this._renderTxState();
            this._recPlayState(d);
            if (Devices.tab === 'can') this.renderFrames(false);
        }).catch(e => { this.lastError = e.message; }).finally(() => { this._polling = false; });
    },

    /** A per-ID row from the server; remember which bytes changed for a short highlight. */
    _mergeId(r) {
        const old = this.byId.get(r.key);
        r.changed = 0;
        r.changedAt = old ? old.changedAt : 0;
        if (old && old.count !== r.count) {
            for (let b = 0; b < r.data.length / 2; b++) {
                if (r.data.substr(b * 2, 2) !== old.data.substr(b * 2, 2)) r.changed |= 1 << b;
            }
            if (r.changed) r.changedAt = Date.now();
            else r.changed = old.changed;
        }
        this.byId.set(r.key, r);
    },

    setSort(col) {
        this.sort = { col, desc: this.sort.col === col ? !this.sort.desc : col !== 'id' };
        this.renderFrames(true);
    },

    _cycle(s) {
        if (s == null) return '';
        const ms = s * 1000;
        return ms < 10 ? ms.toFixed(2) : ms < 100 ? ms.toFixed(1) : Math.round(ms).toString();
    },

    _id(f) {
        if (f.dir === 'err' || f.error) return 'ERR';
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

    /**
     * Filter text -> predicate. Tokens (space / comma separated):
     *   3FD      ID starting with 3FD (several IDs = any of them)     610-61F  ID range
     *   !200     not this ID (prefix / range too)                     rx tx rp err  direction
     *   #00FF    data contains these bytes (spaces ignored)            other text  in the error description
     */
    _filter(text) {
        if (this._flt && this._flt.text === text) return this._flt.fn;
        const ids = [], not = [], dirs = [], data = [], words = [];
        const idTest = tok => {
            const m = /^([0-9a-f]{1,8})-([0-9a-f]{1,8})$/.exec(tok);
            if (m) { const lo = parseInt(m[1], 16), hi = parseInt(m[2], 16); return f => f.can_id >= lo && f.can_id <= hi; }
            if (!/^[0-9a-f]{1,8}$/.test(tok)) return null;
            // prefix of the ID as shown (0AA) or without leading zeros (AA)
            return f => { const id = this._id(f).toLowerCase(); return id.startsWith(tok) || id.replace(/^0+(?=.)/, '').startsWith(tok); };
        };
        text.toLowerCase().split(/[\s,;]+/).filter(Boolean).forEach(tok => {
            if (['rx', 'tx', 'rp', 'err'].includes(tok)) dirs.push(tok);
            else if (tok.startsWith('#')) { const h = tok.slice(1).replace(/[^0-9a-f]/g, ''); if (h) data.push(h); }
            else if (tok.startsWith('!') && idTest(tok.slice(1))) not.push(idTest(tok.slice(1)));
            else if (idTest(tok)) ids.push(idTest(tok));
            else words.push(tok);
        });
        const fn = !text.trim() ? null : f =>
            (!ids.length || ids.some(t => t(f))) && !not.some(t => t(f)) &&
            (!dirs.length || dirs.includes(f.dir) || (dirs.includes('err') && !!f.error)) &&
            data.every(h => f.data.includes(h)) && words.every(w => (f.error || '').toLowerCase().includes(w));
        this._flt = { text, fn };
        return fn;
    },

    _match(f, q) {
        const fn = this._filter(q);
        return !fn || fn(f);
    },

    renderFrames(force) {
        const box = document.getElementById('can-frames');
        const paused = document.getElementById('can-pause').checked;
        const c = this.counts;
        document.getElementById('can-counts').innerHTML =
            (this.mode === 'byid' ? `${this.byId.size} IDs · ` : '') +
            `RX ${c.rx || 0} · TX ${c.tx || 0}` + (c.rp ? ` · RP ${c.rp}` : '') +
            (c.dropped_ids ? ` · <span class="text-warn" title="ID list is full">${c.dropped_ids} not listed</span>` : '') +
            (c.err ? ` · <span class="text-error">ERR ${c.err}</span>` : '') +
            (this.lastError ? ` · <span class="text-error">${esc(this.lastError)}</span>` : '') + (paused ? ' · paused' : '');
        if (paused && !force) return;
        if (!this.canIface) {
            box.innerHTML = '<div class="tbl-empty">No CAN interface. On hardware it appears as can0 when the driver/overlay is enabled.</div>';
            return;
        }
        const q = document.getElementById('can-filter').value.trim().toLowerCase();
        const badgeCls = { rx: 'badge-ok', tx: 'badge-info', rp: 'badge-muted', err: 'badge-error' };
        const dirBadge = d => `<span class="badge ${badgeCls[d] || 'badge-muted'}"${d === 'rp' ? ' title="Replayed from a trace file (not on the bus)"' : ''}>${d.toUpperCase()}</span>`;
        const flags = f => [f.ext ? 'EXT' : '', f.rtr ? 'RTR' : ''].filter(Boolean).join(' ');
        const time = t => Devices.fmtMs(t);
        const errText = f => f.error ? '<span class="text-error">' + esc(f.error) + '</span> ' : '';

        if (this.mode === 'byid') {
            const dirOrder = { rx: 0, tx: 1, rp: 2, err: 3 };
            const key = {
                id: r => r.can_id + (r.ext ? 0x100000000 : 0),
                count: r => r.count,
                cycle: r => r.avg == null ? Infinity : r.avg,
                last: r => r.t,
            }[this.sort.col] || (r => r.can_id);
            const sgn = this.sort.desc ? -1 : 1;
            const rows = [...this.byId.values()].filter(r => this._match(r, q))
                .sort((a, b) => dirOrder[a.dir] - dirOrder[b.dir] || sgn * (key(a) - key(b)) || a.can_id - b.can_id);
            const now = Date.now(), serverNow = now / 1000 + this.skew;
            const th = (col, label, cls, w) => `<th class="can-sort ${cls}" style="width:${w}px" onclick="Devices.tabs.can.setSort('${col}')">${label}` +
                (this.sort.col === col ? ` <i class="fa-solid fa-caret-${this.sort.desc ? 'down' : 'up'}"></i>` : '') + '</th>';
            const cycleTitle = r => r.avg == null ? '' :
                `last ${this._cycle(r.period)} ms · min ${this._cycle(r.min)} ms · max ${this._cycle(r.max)} ms`;
            const groups = { rx: 'Receive', tx: 'Transmit', rp: 'Replay (from file)', err: 'Errors' };
            let group = null;
            box.innerHTML = rows.length ? `<table class="tbl dev-tbl can-tbl"><thead><tr>
                ${th('id', 'ID', '', 100)}<th style="width:60px">Dir</th><th style="width:70px">Flags</th><th style="width:50px">DLC</th>
                <th>Data</th><th style="width:110px">ASCII</th>${th('cycle', 'Cycle, ms', 'num', 100)}${th('count', 'Count', 'num', 90)}
                ${th('last', 'Last', '', 110)}</tr></thead><tbody>` +
                rows.map(r => {
                    // silent for 3 cycles (at least 1 s): the sender stopped
                    const stale = serverNow - r.t > Math.max(1, 3 * (r.avg || 0));
                    const head = r.dir !== group && (group !== null || r.dir !== 'rx')
                        ? `<tr class="can-group"><td colspan="9">${groups[r.dir]}</td></tr>` : '';
                    group = r.dir;
                    return head + `<tr class="${stale ? 'can-stale' : ''}">
                    <td class="mono">${this._id(r)}${this._anBtn(r)}</td>
                    <td>${dirBadge(r.dir)}</td>
                    <td class="small muted">${flags(r)}</td>
                    <td class="mono">${r.dlc}</td>
                    <td class="mono">${errText(r)}${this._bytes(r.data, r.changed, now - (r.changedAt || 0) < 1500)}</td>
                    <td class="mono faint">${this._ascii(r.data)}</td>
                    <td class="mono num" title="${esc(cycleTitle(r))}">${this._cycle(r.avg)}</td>
                    <td class="mono num">${r.count}</td>
                    <td class="mono small faint">${time(r.t)}</td></tr>`;
                }).join('') + '</tbody></table>'
                : `<div class="tbl-empty">${this.byId.size ? 'No IDs match the filter' : 'Waiting for frames…'}</div>`;
            return;
        }
        const list = this.trace.filter(f => this._match(f, q)).slice(0, this.RENDER_ROWS);
        box.innerHTML = list.length ? `<table class="tbl dev-tbl can-tbl"><thead><tr>
            <th style="width:110px">Time</th><th style="width:60px">Dir</th><th style="width:100px">ID</th>
            <th style="width:70px">Flags</th><th style="width:50px">DLC</th><th>Data</th><th style="width:110px">ASCII</th></tr></thead><tbody>` +
            list.map(f => `<tr>
                <td class="mono small">${time(f.t)}</td>
                <td>${dirBadge(f.dir)}</td>
                <td class="mono">${this._id(f)}${this._anBtn(f)}</td>
                <td class="small muted">${flags(f)}</td>
                <td class="mono">${f.dlc}</td>
                <td class="mono">${errText(f)}${this._bytes(f.data)}</td>
                <td class="mono faint">${this._ascii(f.data)}</td></tr>`).join('') + '</tbody></table>'
            : `<div class="tbl-empty">${this.trace.length ? 'No frames match the filter' : 'Waiting for frames…'}</div>`;
    },

    // ── recording / player state (from the frames poll) ─────────────────────

    _recPlayState(d) {
        const was = { rec: this.rec, play: this.play };
        this.rec = d.rec;
        this.play = d.play;
        if (d.speeds) this.speeds = d.speeds;
        if (was.rec && !d.rec && d.rec_last && d.rec_last.error) toast(`Recording stopped: ${d.rec_last.error}`, true);
        if (was.play && !d.play && d.play_last) {
            if (d.play_last.error) toast(`Replay: ${d.play_last.error}`, true);
            else if (d.play_last.done) toast(`Replay of ${d.play_last.path} finished`);
        }
        if (!!was.rec !== !!d.rec || (was.rec && d.rec && was.rec.path !== d.rec.path)) this.loadTree();
        this._renderPlayer();
    },

    _renderPlayer() {
        const rec = this.rec;
        const btn = document.getElementById('can-rec-btn');
        btn.innerHTML = rec ? '<i class="fa-solid fa-square"></i> Stop rec' : '<i class="fa-solid fa-circle"></i> Record';
        btn.classList.toggle('can-rec-on', !!rec);
        document.getElementById('can-rec-info').innerHTML = rec
            ? `<span class="text-error can-blink"><i class="fa-solid fa-circle"></i></span> ${esc(rec.path)} · ${rec.frames} fr · ` +
              `${App.fmtBytes(rec.bytes)} · ${this._dur(Date.now() / 1000 + this.skew - rec.started)}`
            : '';

        const p = this.play;
        document.getElementById('can-play-ind').innerHTML = p
            ? `<span class="text-ok" title="Replay ${p.mode === 'bus' ? 'onto the bus' : 'into the view'} — controls in Traces"><i class="fa-solid fa-${p.paused ? 'pause' : 'play'}"></i> ${esc(p.path.split('/').pop())} ${Math.round(100 * p.pos / (p.size || 1))}%</span>`
            : '';
        const file = p ? p.path : this.selected;
        document.getElementById('can-play-file').innerHTML = file
            ? `<i class="fa-solid fa-file-lines"></i> ${esc(file)}` : '<span class="muted">select a file in the tree</span>';
        const pbtn = document.getElementById('can-play-btn');
        pbtn.innerHTML = p && !p.paused ? '<i class="fa-solid fa-pause"></i>' : '<i class="fa-solid fa-play"></i>';
        const mode = document.getElementById('can-play-mode');
        mode.disabled = !!p;
        if (p) mode.value = p.mode;
        const speed = p ? p.speed : this.speed;
        document.getElementById('can-speed').textContent = `${speed}×`;
        const loop = document.getElementById('can-loop');
        if (p && document.activeElement !== loop) loop.checked = p.loop;
        document.getElementById('can-play-bar').style.width = p && p.size ? `${Math.min(100, 100 * p.pos / p.size)}%` : '0';
        document.getElementById('can-play-info').innerHTML = p
            ? `${this._dur(p.elapsed)} · ${p.frames} fr` + (p.loops ? ` · loop ${p.loops + 1}` : '') +
              (p.skip && p.skip.length ? ` · <span class="text-warn" title="IDs switched off in the file view are not replayed">${p.skip.length} IDs off</span>` : '') +
            (p.paused ? ' · paused' : '') + (p.errors ? ` · <span class="text-error" title="${esc(p.error)}">${p.errors} errors</span>` : '')
            : '';
        document.querySelectorAll('#can-tree .tree-row[data-file]').forEach(r => {
            r.classList.toggle('can-rec-file', !!rec && rec.path === r.dataset.path);
            r.classList.toggle('can-play-row', !!p && p.path === r.dataset.path);
        });
    },

    _dur(s) {
        s = Math.max(0, s || 0);
        const m = Math.floor(s / 60);
        return m ? `${m}:${(s % 60).toFixed(1).padStart(4, '0')}` : `${s.toFixed(1)} s`;
    },

    // ── recording ──────────────────────────────────────────────────────────

    recButton() {
        if (!this.canIface) return;
        if (this.rec) {
            this._post('/api/net/can/record', { action: 'stop' })
                .then(() => { toast(`Saved ${this.rec ? this.rec.path : ''}`); this._pollFrames(); })
                .catch(e => toast(e.message, true));
            return;
        }
        const pop = document.getElementById('can-rec-pop');
        if (!pop.hidden) return this._closePop();
        this._renderRecPop();
        pop.hidden = false;
        const name = document.getElementById('can-rec-name');
        name.focus();
        name.select();
    },

    _closePop() {
        const pop = document.getElementById('can-rec-pop');
        if (pop) pop.hidden = true;
    },

    _folders() {
        const out = [''];
        const walk = nodes => nodes.forEach(n => { if (n.dir) { out.push(n.path); walk(n.children); } });
        walk(this.tree);
        return out;
    },

    _files() {
        const out = [];
        const walk = nodes => nodes.forEach(n => { if (n.dir) walk(n.children); else out.push(n); });
        walk(this.tree);
        return out.sort((a, b) => b.mtime - a.mtime);
    },

    _renderRecPop() {
        const d = new Date();
        const p = n => String(n).padStart(2, '0');
        const name = `${this.canIface}_${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}_${p(d.getHours())}-${p(d.getMinutes())}-${p(d.getSeconds())}`;
        const files = this._files();
        document.getElementById('can-rec-pop').innerHTML = `
            <div class="can-pop-head">New trace file</div>
            <div class="can-pop-row">
                <select id="can-rec-folder" class="input input-sm" title="Folder">
                    ${this._folders().map(f => `<option value="${esc(f)}"${f === this.folder ? ' selected' : ''}>${f ? esc(f) + '/' : '/ (root)'}</option>`).join('')}
                </select>
                <input id="can-rec-name" class="input input-sm mono" value="${esc(name)}" spellcheck="false"
                       onkeydown="if (event.key === 'Enter') Devices.tabs.can.recStart(); if (event.key === 'Escape') Devices.tabs.can._closePop()">
                <span class="small muted">.log</span>
                <button type="button" class="btn btn-danger btn-sm" onclick="Devices.tabs.can.recStart()"><i class="fa-solid fa-circle"></i> Start</button>
            </div>
            <div class="can-pop-head">…or append to a file</div>
            <div class="can-pop-list">${files.length ? files.map(f => `
                <div class="can-pop-file" onclick='Devices.tabs.can.recStart(${esc(JSON.stringify(f.path))})' title="Append new frames to the end of this file">
                    <i class="fa-solid fa-file-lines"></i><span class="mono">${esc(f.path)}</span>
                    <span class="spacer"></span><span class="faint small">${App.fmtBytes(f.size)} · ${esc(App.fmtDate(f.mtime))}</span>
                </div>`).join('') : '<div class="muted small can-pop-none">No trace files yet</div>'}
            </div>`;
    },

    recStart(appendTo) {
        let path, append = false;
        if (appendTo) {
            path = appendTo;
            append = true;
        } else {
            const name = document.getElementById('can-rec-name').value.trim();
            if (!name) return;
            const folder = document.getElementById('can-rec-folder').value;
            path = folder ? `${folder}/${name}` : name;
        }
        this._post('/api/net/can/record', { action: 'start', path, append }).then(d => {
            this._closePop();
            toast(`${append ? 'Appending to' : 'Recording to'} ${d.path}`);
            this.loadTree();
            this._pollFrames();
        }).catch(e => toast(e.message, true));
    },

    // ── player ─────────────────────────────────────────────────────────────

    playButton() {
        if (!this.canIface) return;
        if (this.play) return this.playCmd(this.play.paused ? 'resume' : 'pause');
        if (!this.selected) return toast('Select a trace file in the tree', true);
        const mode = document.getElementById('can-play-mode').value;
        if (mode === 'bus' && !confirm(`Send the frames of ${this.selected} onto ${this.canIface}? Devices on the bus will receive them.`)) return;
        this._post('/api/net/can/play', { action: 'start', path: this.selected, mode, speed: this.speed,
                                          loop: document.getElementById('can-loop').checked, skip: this._skip(this.selected) })
            .then(() => this._pollFrames()).catch(e => toast(e.message, true));
    },

    playCmd(action) {
        if (!this.play) return;
        this._post('/api/net/can/play', { action }).then(() => this._pollFrames()).catch(e => toast(e.message, true));
    },

    speedStep(dir) {
        const cur = this.play ? this.play.speed : this.speed;
        let i = this.speeds.findIndex(s => s >= cur - 1e-9);
        if (i < 0) i = this.speeds.length - 1;
        else if (this.speeds[i] > cur + 1e-9 && dir > 0) i--;
        const next = this.speeds[Math.max(0, Math.min(this.speeds.length - 1, i + dir))];
        this.speed = next;
        if (this.play) {
            this.play.speed = next;
            this._post('/api/net/can/play', { action: 'set', speed: next }).catch(e => toast(e.message, true));
        }
        this._renderPlayer();
    },

    setLoop() {
        if (this.play) this._post('/api/net/can/play', { action: 'set', loop: document.getElementById('can-loop').checked })
            .catch(e => toast(e.message, true));
    },

    // ── analyser of one ID (can_analyzer.js) ────────────────────────────────

    _anKey(f) { return `${f.ext ? 'x' : 's'}:${f.can_id.toString(16)}`; },

    /** Analyser button of a row: live rows (By ID — their ``key`` is the statistics key "rx:s:123" — and Trace) use the
        ID key built from can_id / ext; rows of a file's ID list (``file``) already carry the ID key ("s:123"). */
    _anBtn(f, file) {
        if (f.dir === 'err' || f.error || (file && f.key === 'err')) return '';
        const key = file ? f.key : this._anKey(f);
        return `<button type="button" class="btn-icon can-an-btn" data-an="${esc(key)}" data-label="${esc(file ? this._keyId(f) : this._id(f))}"` +
               `${file ? ` data-file="${esc(file)}"` : ''} title="Analyse this ID (other IDs are ignored meanwhile)"><i class="fa-solid fa-microscope"></i></button>`;
    },

    analyze(key, label, file) {
        if (file) return CanAnalyzer.open({ kind: 'file', path: file, key, label });
        if (!this.canIface) return;
        this.analyzing = true;
        CanAnalyzer.open({ kind: 'live', iface: this.canIface, key, label });
    },

    analyzerClosed() {
        this.analyzing = false;
        this._pollFrames();
        this.renderFrames(true);
    },

    // ── TX list (profiles) ─────────────────────────────────────────────────

    loadProfiles() {
        return App.api('/api/can/profiles').then(d => {
            this.profiles = d.profiles.length ? d.profiles : [{ name: 'Default', tx: [], note: '' }];
            this.cur = d.current || this.profiles[0].name;
            this._renderProfiles();
        }).catch(e => toast('CAN TX lists: ' + e.message, true));
    },

    prof() { return this.profiles.find(p => p.name === this.cur) || this.profiles[0]; },

    save() {
        clearTimeout(this._saveT);
        this._saveT = setTimeout(() => {
            App.api('/api/can/profiles', { json: { profiles: this.profiles, current: this.cur } })
                .catch(e => toast('CAN TX lists not saved: ' + e.message, true));
        }, 1000);
    },

    _renderProfiles() {
        document.getElementById('can-prof').innerHTML = this.profiles.map(p =>
            `<option value="${esc(p.name)}"${p.name === this.cur ? ' selected' : ''}>${esc(p.name)}</option>`).join('');
        this.renderTx();
        document.getElementById('can-note').value = this.prof().note || '';
        this.noteToggle(false);
    },

    pickProfile(name) {
        if (this._running().length && !confirm('Rows of this list are being sent. Switching the list stops them. Continue?')) {
            document.getElementById('can-prof').value = this.cur;
            return;
        }
        this._stopJobs(this.canIface);
        if (typeof CanTxEdit !== 'undefined') CanTxEdit.close();
        this.cur = name;
        this.txRes = {};
        this._renderProfiles();
        this.save();
    },

    _uniqueName(base) {
        let n = base, k = 2;
        while (this.profiles.some(p => p.name === n)) n = `${base} ${k++}`;
        return n;
    },

    profileCmd(cmd) {
        const p = this.prof();
        if (cmd === 'new' || cmd === 'dup') {
            const name = (prompt('List name:', this._uniqueName(cmd === 'dup' ? p.name + ' copy' : 'TX list')) || '').trim();
            if (!name) return;
            if (this.profiles.some(x => x.name === name)) return toast('Name already used', true);
            const np = cmd === 'dup' ? JSON.parse(JSON.stringify(p)) : { tx: [], note: '' };
            np.name = name;
            if (cmd === 'dup') np.tx.forEach(r => { r.uid = this._uid(); });
            this.profiles.push(np);
            return this.pickProfile(name);
        }
        if (cmd === 'rename') {
            const name = (prompt('New name:', p.name) || '').trim();
            if (!name || name === p.name) return;
            if (this.profiles.some(x => x.name === name)) return toast('Name already used', true);
            p.name = this.cur = name;
        } else if (cmd === 'export') {
            const a = document.createElement('a');
            a.href = URL.createObjectURL(new Blob([JSON.stringify(p, null, 2)], { type: 'application/json' }));
            a.download = `can_${p.name.replace(/[^\w.-]+/g, '_')}.json`;
            a.click();
            setTimeout(() => URL.revokeObjectURL(a.href), 1000);
            return;
        } else if (cmd === 'delete') {
            if (this.profiles.length < 2) return toast('The last list cannot be deleted', true);
            if (!confirm(`Delete TX list "${p.name}"?`)) return;
            this._stopJobs(this.canIface);
            this.profiles = this.profiles.filter(x => x !== p);
            this.cur = this.profiles[0].name;
        }
        this._renderProfiles();
        this.save();
    },

    importFile(input) {
        const f = input.files[0];
        input.value = '';
        if (!f) return;
        f.text().then(t => {
            const p = JSON.parse(t);
            if (!p || !Array.isArray(p.tx)) throw new Error('not a CAN TX list');
            p.name = this._uniqueName(String(p.name || 'Imported'));
            p.note = String(p.note || '');
            p.tx.forEach(r => { r.uid = this._uid(); });
            this.profiles.push(p);
            this.pickProfile(p.name);
            toast(`Imported "${p.name}"`);
        }).catch(e => toast('Import failed: ' + e.message, true));
    },

    _uid() { return 'r' + Date.now().toString(36) + Math.random().toString(36).slice(2, 7); },

    toggleTxArea(show) {
        const el = document.getElementById('can-txarea');
        const off = show === undefined ? el.dataset.off !== '1' : !show;
        el.dataset.off = off ? '1' : '0';
        try { localStorage.setItem('can.txHidden', off ? '1' : '0'); } catch (e) { /* private mode */ }
        this.setPage(this.page);
    },

    /** Row -> {id, ext, rtr, data} for the API, or {error}. */
    _rowFrame(r) {
        const id = String(r.id || '').trim().replace(/^0x/i, '');
        if (!/^[0-9a-f]{1,8}$/i.test(id)) return { error: 'ID: 1–8 hex digits' };
        const n = parseInt(id, 16);
        if (n > 0x1FFFFFFF || (r.ext === false && n > 0x7FF && id.length <= 3)) return { error: 'ID out of range' };
        const data = String(r.data || '').replace(/0x/gi, '').replace(/[\s,:]/g, '');
        if (!r.rtr && (!/^([0-9a-f]{2})*$/i.test(data) || data.length > 16)) return { error: 'Data: up to 8 hex bytes' };
        const out = { id, ext: !!r.ext || n > 0x7FF, rtr: !!r.rtr, data: r.rtr ? '' : data };
        if (r.cs) out.cs = r.cs;                    // checksum / rolling counter: applied by the server per frame
        if (r.cnt) out.cnt = r.cnt;
        return out;
    },

    addTx(empty) {
        if (!this.profiles) return;
        const f = this._form();
        const q = this.quick;
        const row = empty ? { uid: this._uid(), name: '', id: '', ext: false, rtr: false, data: '', period: 100, on: true }
            : { uid: this._uid(), name: '', id: f.id, ext: f.ext, rtr: f.rtr, data: f.data.trim(), period: q ? q.period || 100 : 100, on: true,
                fields: q && q.fields ? JSON.parse(JSON.stringify(q.fields)) : [] };
        this.prof().tx.push(row);
        if (document.getElementById('can-txarea').dataset.off === '1') this.toggleTxArea(true);
        this.renderTx();
        this.save();
        const names = document.querySelectorAll('#can-tx-rows .can-tx-name');
        if (names.length) names[names.length - 1].focus();
    },

    renderTx() {
        const rows = this.prof().tx;
        document.getElementById('can-tx-rows').innerHTML = rows.map((r, i) => {
            const bad = this._rowFrame(r).error;
            return `<tr data-uid="${esc(r.uid)}">
                <td><input type="checkbox" data-f="on"${r.on ? ' checked' : ''}></td>
                <td><input class="input input-sm can-tx-name" data-f="name" value="${esc(r.name)}" placeholder="name"></td>
                <td><input class="input input-sm mono can-tx-id" data-f="id" value="${esc(r.id)}" placeholder="123" spellcheck="false"></td>
                <td class="nowrap"><label class="can-flag" title="29-bit ID"><input type="checkbox" data-f="ext"${r.ext ? ' checked' : ''}>X</label><label class="can-flag" title="Remote frame"><input type="checkbox" data-f="rtr"${r.rtr ? ' checked' : ''}>R</label>` +
                    `${r.cs ? `<span class="can-tag" title="checksum ${esc(r.cs)} in the last byte">CS</span>` : ''}` +
                    `${r.cnt ? `<span class="can-tag" title="rolling counter in B${r.cnt.byte} (bits ${esc(r.cnt.bits || '0-7')})">N</span>` : ''}</td>
                <td><input class="input input-sm mono can-tx-data${bad ? ' can-bad' : ''}" data-f="data" value="${esc(r.data)}" placeholder="11 22 33 44" spellcheck="false" title="${esc(bad || '↑ ↓ on a byte: +1 / −1 (Shift: ±16)')}"></td>
                <td><input class="input input-sm mono can-tx-ms" data-f="period" type="number" min="0" step="10" value="${r.period}"></td>
                <td class="mb-act">
                    <button type="button" class="btn-icon text-ok" data-a="once" title="Send once"><i class="fa-solid fa-play"></i></button>
                    <button type="button" class="btn-icon" data-a="cyc" title="Send every period / stop"><i class="fa-solid fa-repeat"></i></button>
                    <button type="button" class="btn-icon text-info" data-a="edit" title="Frame editor: bits, fields (signed / unsigned numbers), sweep — live while it runs"><i class="fa-solid fa-sliders"></i></button>
                    <span class="can-more">
                    <button type="button" class="btn-icon" data-a="up" title="Up"${i ? '' : ' disabled'}><i class="fa-solid fa-arrow-up"></i></button>
                    <button type="button" class="btn-icon" data-a="down" title="Down"${i < rows.length - 1 ? '' : ' disabled'}><i class="fa-solid fa-arrow-down"></i></button>
                    <button type="button" class="btn-icon" data-a="dup" title="Duplicate"><i class="fa-regular fa-clone"></i></button>
                    <button type="button" class="btn-icon" data-a="del" title="Delete"><i class="fa-solid fa-xmark"></i></button></span>
                </td>
                <td class="can-tx-state" data-state></td></tr>`;
        }).join('') || '<tr><td colspan="8" class="tbl-empty">No rows — type ID / data in the quick send above and press “+ Row”.</td></tr>';
        this._renderTxState();
    },

    _running() {
        if (!this.profiles) return [];
        const uids = new Set(this.prof().tx.map(r => r.uid));
        return (this.jobs || []).filter(j => j.tag && uids.has(j.tag));
    },

    _job(uid) { return (this.jobs || []).find(j => j.tag === uid); },

    _renderTxState() {
        if (!this.profiles) return;
        if (typeof CanTxEdit !== 'undefined') CanTxEdit.renderState();
        const running = this._running();
        document.querySelectorAll('#can-tx-rows tr[data-uid]').forEach(tr => {
            const uid = tr.dataset.uid, j = this._job(uid), res = this.txRes[uid];
            tr.classList.toggle('can-tx-run', !!j);
            const cyc = tr.querySelector('[data-a="cyc"]');
            cyc.innerHTML = j ? '<i class="fa-solid fa-stop"></i>' : '<i class="fa-solid fa-repeat"></i>';
            cyc.classList.toggle('text-warn', !!j);
            const cell = tr.querySelector('[data-state]');
            const html = j
                ? `<span class="text-warn" title="every ${j.period_ms} ms — frames sent"><i class="fa-solid fa-repeat fa-spin can-spin"></i> ${j.sent}</span>` +
                  (j.errors ? ` · <span class="text-error" title="${esc(j.last_error)}">${j.errors} errors</span>` : '')
                : res ? (res.ok ? `<span class="faint" title="sent once">${esc(new Date(res.at).toLocaleTimeString())}</span>`
                                : `<span class="text-error">${esc(res.text)}</span>`) : '';
            if (cell.innerHTML !== html) cell.innerHTML = html;
        });
        const n = running.length;
        document.getElementById('can-tx-sum').textContent = n ? `${n} running` : '';
        const all = document.getElementById('can-tx-all');
        all.innerHTML = n ? '<i class="fa-solid fa-stop"></i> Stop all' : '<i class="fa-solid fa-repeat"></i> Start';
        all.classList.toggle('btn-danger', !!n);
        all.classList.toggle('btn-warning', !n);
    },

    _bindTx() {
        const body = document.getElementById('can-tx-rows');
        body.addEventListener('input', e => this._txInput(e));
        body.addEventListener('change', e => { if (e.target.type === 'checkbox') this._txInput(e); });
        body.addEventListener('click', e => {
            const b = e.target.closest('[data-a]'), tr = e.target.closest('tr[data-uid]');
            if (b && tr) this._txAct(b.dataset.a, tr.dataset.uid);
        });
        body.addEventListener('keydown', e => {
            if (e.target.dataset.f === 'data' && (e.key === 'ArrowUp' || e.key === 'ArrowDown')) {
                e.preventDefault();
                this._stepByte(e.target, (e.key === 'ArrowUp' ? 1 : -1) * (e.shiftKey ? 16 : 1));
            } else if (e.key === 'Enter' && e.target.matches('input.input')) {
                this._txAct('once', e.target.closest('tr').dataset.uid);
            }
        });
        const view = document.getElementById('can-note-view');
        view.addEventListener('click', e => this._noteClick(e));
        view.addEventListener('dblclick', e => { if (!e.target.closest('[data-frame]')) this.noteToggle(true); });
        const ta = document.getElementById('can-note');
        ta.addEventListener('input', () => { this.prof().note = ta.value; this.save(); });
        ta.addEventListener('keydown', e => { if (e.key === 'Escape') { e.stopPropagation(); this.noteToggle(false); } });
    },

    /** ↑ / ↓ in the data field: change the byte under the cursor (wraps 00 ↔ FF), keep the cursor on it. */
    _stepByte(input, delta) {
        const text = input.value, pos = input.selectionStart;
        const re = /[0-9a-f]{2}/gi;
        let m, hit = null;
        while ((m = re.exec(text))) {
            if (pos >= m.index && pos <= m.index + 2) { hit = m; break; }
        }
        if (!hit) return;
        const v = ((parseInt(hit[0], 16) + delta) % 256 + 256) % 256;
        input.value = text.slice(0, hit.index) + v.toString(16).toUpperCase().padStart(2, '0') + text.slice(hit.index + 2);
        input.setSelectionRange(pos, pos);
        input.dispatchEvent(new Event('input', { bubbles: true }));
    },

    _txInput(e) {
        const t = e.target, tr = t.closest('tr[data-uid]');
        if (!tr || !t.dataset.f) return;
        const r = this.prof().tx.find(x => x.uid === tr.dataset.uid);
        if (!r) return;
        const f = t.dataset.f;
        r[f] = t.type === 'checkbox' ? t.checked : f === 'period' ? Math.max(0, parseInt(t.value, 10) || 0) : t.value;
        this.rowChanged(r, f);
    },

    /** A TX row changed (field ``f``; from the table or the frame editor): mark errors, save, update its running
        transmission on the fly. */
    rowChanged(r, f) {
        const fr = this._rowFrame(r);
        if (r.quick) {
            const set = (id, v, chk) => {
                const el = document.getElementById(id);
                if (el === document.activeElement) return;
                if (chk) el.checked = !!v; else if (el.value !== v) el.value = v;
            };
            set('can-id', r.id); set('can-data', r.data); set('can-ext', r.ext, true); set('can-rtr', r.rtr, true);
            try { localStorage.setItem('can.quick', JSON.stringify({ period: r.period, fields: r.fields || [] })); } catch (e) { /* private mode */ }
        }
        if (typeof CanTxEdit !== 'undefined') CanTxEdit.rowChanged(r);
        const tr = document.querySelector(`#can-tx-rows tr[data-uid="${CSS.escape(r.uid)}"]`);
        if (tr) tr.querySelectorAll('[data-f]').forEach(el => {
            const k = el.dataset.f;
            if (el !== document.activeElement && k !== f + '_') {
                if (el.type === 'checkbox') el.checked = !!r[k];
                else if (String(el.value) !== String(r[k])) el.value = r[k];
            }
        });
        if (tr) tr.querySelectorAll('[data-f="id"], [data-f="data"]').forEach(el => {
            el.classList.toggle('can-bad', !!fr.error);
            el.title = fr.error || (el.dataset.f === 'data' ? '↑ ↓ on a byte: +1 / −1 (Shift: ±16)' : '');
        });
        this.save();
        const j = this._job(r.uid);
        if (!j || ['name', 'on'].includes(f)) return;
        if (f === 'period' && !r.period) return this._txAct('cyc', r.uid);     // period 0: stop
        if (fr.error) return;
        // live update of the running transmission: at most one request per 40 ms, carrying the latest state
        // (a throttle, not a debounce — a sweep changing the row faster than the delay must still get through)
        if (this._upd[r.uid]) return;
        this._upd[r.uid] = setTimeout(() => {
            this._upd[r.uid] = null;
            if (this._rowFrame(r).error) return;
            const job = this._job(r.uid);
            if (!job) return;
            this._post('/api/net/can/send', Object.assign({ action: 'update', job: job.job, period_ms: r.period }, this._rowFrame(r)))
                .catch(err => toast(err.message, true));
        }, 40);
    },

    _txAct(a, uid) {
        const rows = this.prof().tx, i = rows.findIndex(x => x.uid === uid), r = rows[i];
        if (!r) return;
        const swap = (x, y) => { [rows[x], rows[y]] = [rows[y], rows[x]]; };
        switch (a) {
            case 'once': return this._sendRow(r);
            case 'edit': return CanTxEdit.open(r, document.querySelector(`#can-tx-rows tr[data-uid="${CSS.escape(uid)}"] [data-a="edit"]`));
            case 'cyc': {
                if (!this.canIface) return;
                const j = this._job(uid);
                if (j) return this._post('/api/net/can/send', { action: 'stop', job: j.job }).then(() => this._pollFrames())
                    .catch(e => toast(e.message, true));
                return this._startRow(r).then(() => this._pollFrames()).catch(e => toast(e.message, true));
            }
            case 'up': if (i > 0) swap(i, i - 1); break;
            case 'down': if (i < rows.length - 1) swap(i, i + 1); break;
            case 'dup': rows.splice(i + 1, 0, Object.assign({}, r, { uid: this._uid(), name: r.name ? r.name + ' copy' : '' })); break;
            case 'del': {
                if (typeof CanTxEdit !== 'undefined' && CanTxEdit.row === r) CanTxEdit.close();
                const j = this._job(uid);
                if (j) this._post('/api/net/can/send', { action: 'stop', job: j.job }).catch(() => {});
                rows.splice(i, 1);
                break;
            }
        }
        this.renderTx();
        this.save();
    },

    _startRow(r) {
        const fr = this._rowFrame(r);
        if (fr.error) return Promise.reject(new Error(`${r.name || r.id || 'row'}: ${fr.error}`));
        if (!r.period) return Promise.reject(new Error(`${r.name || r.id}: set a period (ms) to send it cyclically`));
        return this._post('/api/net/can/send', Object.assign({ action: 'cyclic', period_ms: r.period, tag: r.uid }, fr));
    },

    _sendRow(r) {
        if (!this.canIface) return Promise.resolve();
        const fr = this._rowFrame(r);
        const done = (ok, text) => { this.txRes[r.uid] = { ok, text, at: Date.now() }; this._renderTxState(); };
        if (fr.error) { done(false, fr.error); return Promise.resolve(); }
        return this._post('/api/net/can/send', Object.assign({ action: 'send' }, fr))
            .then(() => done(true, '')).catch(e => done(false, e.message));
    },

    async sendAllOnce() {
        const rows = this.prof().tx.filter(r => r.on);
        if (!rows.length) return toast('No ticked rows', true);
        for (const r of rows) await this._sendRow(r);
    },

    toggleAll() {
        if (!this.canIface) return;
        if (this._running().length) {
            this._stopJobs(this.canIface);
            this._renderTxState();
            return;
        }
        const rows = this.prof().tx.filter(r => r.on && r.period);
        if (!rows.length) return toast('No ticked rows with a period', true);
        Promise.allSettled(rows.map(r => this._startRow(r))).then(res => {
            const bad = res.filter(x => x.status === 'rejected');
            if (bad.length) toast(bad.map(x => x.reason.message).join('; '), true);
            this._pollFrames();
        });
    },

    // ── notes with [[ID#data]] frame buttons ────────────────────────────────

    _parseTag(text) {
        const m = /^\s*([0-9a-f]{1,8})\s*#\s*(R\d?|[0-9a-f\s]*)\s*$/i.exec(text);
        if (!m) return null;
        const rtr = /^R/i.test(m[2]);
        return { id: m[1], ext: m[1].length > 3, rtr, data: rtr ? '' : m[2].trim() };
    },

    renderNote() {
        const text = document.getElementById('can-note').value;
        this._tags = [];
        const html = esc(text).replace(/\[\[([\s\S]+?)\]\]/g, (m, c) => {
            const raw = c.replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&#39;/g, "'").trim();
            const fr = this._parseTag(raw);
            if (!fr) return `<span class="text-error" title="Expected [[ID#data]], e.g. [[123#11 22]]">${m}</span>`;
            this._tags.push(fr);
            return `<span class="tt-cmdtag" data-frame="${this._tags.length - 1}"><span>${esc(raw)}</span>` +
                `<button class="btn-icon" data-na="copy" title="To the send field"><i class="fa-solid fa-arrow-down"></i></button>` +
                `<button class="btn-icon" data-na="add" title="Add to the TX list"><i class="fa-solid fa-plus"></i></button>` +
                `<button class="btn-icon text-ok" data-na="send" title="Send now"><i class="fa-solid fa-play"></i></button></span>`;
        });
        document.getElementById('can-note-view').innerHTML = html ||
            '<span class="faint">No notes yet — Edit (or double-click) to write. Frames in [[ID#data]] become buttons.</span>';
    },

    _noteClick(e) {
        const tag = e.target.closest('[data-frame]');
        if (!tag) return;
        const fr = this._tags[+tag.dataset.frame], b = e.target.closest('[data-na]');
        document.getElementById('can-id').value = fr.id;
        document.getElementById('can-ext').checked = fr.ext;
        document.getElementById('can-rtr').checked = fr.rtr;
        document.getElementById('can-data').value = fr.data;
        if (!b) return;
        if (b.dataset.na === 'send') this.send();
        else if (b.dataset.na === 'add') this.addTx();
    },

    noteToggle(edit) {
        const ta = document.getElementById('can-note'), view = document.getElementById('can-note-view');
        const editing = edit === undefined ? ta.hidden : edit;
        ta.hidden = !editing;
        view.hidden = editing;
        document.getElementById('can-note-edit').innerHTML = editing ? '<i class="fa-solid fa-check"></i> Done' : '<i class="fa-solid fa-pen"></i> Edit';
        if (editing) ta.focus();
        else this.renderNote();
    },

    noteInsert() {
        const f = this._form();
        if (!f.id) return toast('Fill the ID (and data) in the send field first', true);
        const ta = document.getElementById('can-note');
        const data = f.rtr ? 'R' : f.data.trim().toUpperCase();
        ta.value = (ta.value && !ta.value.endsWith('\n') ? ta.value + '\n' : ta.value) + `[[${f.id.toUpperCase()}#${data}]]`;
        this.prof().note = ta.value;
        this.save();
        this.renderNote();
    },

    // ── opened file: IDs (replay filter) + frames ───────────────────────────

    openFile(path) {
        this.selected = path;
        this.file = { path, info: null, start: 0, key: null, page: null, error: '' };
        this._renderTree();
        this.renderFile();
        this.reloadFile();
    },

    closeFile() {
        this.file = null;
        this.renderFile();
    },

    reloadFile() {
        const f = this.file;
        if (!f) return;
        App.api('/api/can/traces/info?path=' + encodeURIComponent(f.path)).then(info => {
            if (this.file !== f) return;
            f.info = info;
            if (f.key && !info.ids.some(r => r.key === f.key)) f.key = null;
            return this._loadPage();
        }).catch(e => { f.error = e.message; this.renderFile(); });
    },

    _loadPage() {
        const f = this.file;
        const q = `path=${encodeURIComponent(f.path)}&start=${f.start}&limit=${this.FILE_PAGE}` + (f.key ? `&key=${encodeURIComponent(f.key)}` : '');
        return App.api('/api/can/traces/frames?' + q).then(page => {
            if (this.file !== f) return;
            f.page = page;
            f.error = '';
            this._pageMoved = true;     // a new page starts at its top
            this.renderFile();
        }).catch(e => { f.error = e.message; this.renderFile(); });
    },

    pageGo(where) {
        const f = this.file;
        if (!f || !f.page) return;
        const total = f.page.total, n = this.FILE_PAGE;
        const last = Math.max(0, Math.floor((total - 1) / n) * n);
        f.start = where === 'first' ? 0 : where === 'last' ? last
            : Math.max(0, Math.min(last, f.start + (where === 'next' ? n : -n)));
        this._loadPage();
    },

    filterId(key) {
        const f = this.file;
        if (!f) return;
        f.key = f.key === key ? null : key;
        f.start = 0;
        this._loadPage();
    },

    _skip(path) { return (this.skips[path] || []).slice(); },

    _setSkip(path, keys) {
        if (keys.length) this.skips[path] = keys;
        else delete this.skips[path];
        try { localStorage.setItem('can.skips', JSON.stringify(this.skips)); } catch (e) { /* private mode */ }
        if (this.play && this.play.path === path) {
            this.play.skip = keys;
            this._post('/api/net/can/play', { action: 'set', skip: keys }).catch(e => toast(e.message, true));
        }
        this._renderPlayer();
        this.renderFile();
    },

    toggleId(key, on) {
        const path = this.file.path;
        const skip = new Set(this._skip(path));
        if (on) skip.delete(key);
        else skip.add(key);
        this._setSkip(path, [...skip]);
    },

    allIds(on) {
        const f = this.file;
        if (!f || !f.info) return;
        this._setSkip(f.path, on ? [] : f.info.ids.map(r => r.key));
    },

    _fileTab() { this.renderFile(); },

    _keyId(r) {
        return r.key === 'err' ? 'ERR' : r.can_id.toString(16).toUpperCase().padStart(r.ext ? 8 : 3, '0');
    },

    renderFile() {
        const box = document.getElementById('can-file');
        const f = this.file;
        if (this.page !== 'traces') return;
        if (!f) {
            box.innerHTML = '<div class="tbl-empty">Click a trace file in the tree to see its IDs and frames — double-click plays it.<br>' +
                'New traces: ● Record (top right).</div>';
            return;
        }
        if (f.error) {
            box.innerHTML = `<div class="tbl-empty text-error">${esc(f.error)}</div>`;
            return;
        }
        if (!f.info || !f.page) {
            box.innerHTML = '<div class="tbl-empty">Reading the file…</div>';
            return;
        }
        const scrolls = [...box.querySelectorAll('.can-file-scroll')].map(el => el.scrollTop);
        const info = f.info, skip = new Set(this._skip(f.path));
        const on = info.ids.filter(r => !skip.has(r.key)).length;
        const ids = info.ids.map(r => `<tr class="${skip.has(r.key) ? 'can-off' : ''}${f.key === r.key ? ' can-fsel' : ''}">
                <td><input type="checkbox" data-skip="${esc(r.key)}"${skip.has(r.key) ? '' : ' checked'} title="Replay this ID"></td>
                <td class="mono"><span class="can-fkey" data-fkey="${esc(r.key)}" title="Show only this ID">${this._keyId(r)}</span>${this._anBtn(r, f.path)}</td>
                <td class="small muted">${r.ext ? 'EXT' : ''}${r.rtr ? ' RTR' : ''}</td>
                <td class="mono num">${r.count}</td>
                <td class="small faint">${r.tx ? 'TX ' + r.tx : ''}${r.rx && r.tx ? ' · ' : ''}${r.rx && r.tx ? 'RX ' + r.rx : ''}</td>
                <td class="mono small">${this._bytes(r.data)}</td></tr>`).join('');
        const page = f.page;
        const from = page.total ? page.start + 1 : 0, to = page.start + page.frames.length;
        const keyRow = f.key && info.ids.find(r => r.key === f.key);
        const pager = `<span class="small muted">${from}–${to} of ${page.total}</span>
            <button type="button" class="btn-icon" onclick="Devices.tabs.can.pageGo('first')" title="First page"${page.start ? '' : ' disabled'}><i class="fa-solid fa-backward-step"></i></button>
            <button type="button" class="btn-icon" onclick="Devices.tabs.can.pageGo('prev')" title="Previous page"${page.start ? '' : ' disabled'}><i class="fa-solid fa-chevron-left"></i></button>
            <button type="button" class="btn-icon" onclick="Devices.tabs.can.pageGo('next')" title="Next page"${to < page.total ? '' : ' disabled'}><i class="fa-solid fa-chevron-right"></i></button>
            <button type="button" class="btn-icon" onclick="Devices.tabs.can.pageGo('last')" title="Last page"${to < page.total ? '' : ' disabled'}><i class="fa-solid fa-forward-step"></i></button>`;
        const dirBadge = d => `<span class="badge ${{ rx: 'badge-ok', tx: 'badge-info', err: 'badge-error' }[d]}">${d.toUpperCase()}</span>`;
        const rows = page.frames.map(fr => `<tr>
                <td class="mono small faint num">${fr.n + 1}</td>
                <td class="mono small num">${fr.rel.toFixed(3)}</td>
                <td class="mono small faint">${Devices.fmtMs(fr.t)}</td>
                <td>${dirBadge(fr.dir)}</td>
                <td class="mono">${fr.dir === 'err' ? 'ERR' : this._id(fr)}</td>
                <td class="small muted">${[fr.ext ? 'EXT' : '', fr.rtr ? 'RTR' : ''].filter(Boolean).join(' ')}</td>
                <td class="mono">${fr.dlc}</td>
                <td class="mono">${this._bytes(fr.data)}</td>
                <td class="mono faint">${this._ascii(fr.data)}</td></tr>`).join('');
        box.innerHTML = `
            <div class="can-file-ids">
                <div class="can-file-head">
                    <b>IDs</b><span class="small muted">${on} of ${info.ids.length} replayed</span><span class="spacer"></span>
                    <button type="button" class="btn btn-ghost btn-sm" onclick="Devices.tabs.can.allIds(true)" title="Replay every ID">All on</button>
                    <button type="button" class="btn btn-ghost btn-sm" onclick="Devices.tabs.can.allIds(false)" title="Replay none">All off</button>
                </div>
                <div class="can-file-scroll">${info.ids.length ? `<table class="tbl dev-tbl can-tbl"><thead><tr>
                    <th style="width:26px"></th><th>ID</th><th></th><th class="num">Count</th><th></th><th>Last data</th></tr></thead>
                    <tbody>${ids}</tbody></table>` : '<div class="tbl-empty">No frames</div>'}
                    ${info.ids_full ? '<div class="small text-warn can-pop-none">Too many IDs — only the first 4096 are listed</div>' : ''}
                </div>
            </div>
            <div class="can-file-frames">
                <div class="can-file-head">
                    <span class="small"><b>${info.frames}</b> frames · ${this._dur(info.duration)}` +
                    `${info.sessions > 1 ? ` · ${info.sessions} recordings` : ''} · ${App.fmtBytes(info.size)}` +
                    `${info.start ? ` · ${esc(App.fmtDate(info.start))}` : ''}</span>
                    ${keyRow ? `<span class="can-chip mono" data-fkey="${esc(keyRow.key)}" title="Show all IDs">${this._keyId(keyRow)} <i class="fa-solid fa-xmark"></i></span>` : ''}
                    <span class="spacer"></span>${pager}
                    <button type="button" class="btn-icon" onclick="Devices.tabs.can.reloadFile()" title="Re-read the file"><i class="fa-solid fa-rotate"></i></button>
                </div>
                <div class="can-file-scroll">${rows ? `<table class="tbl dev-tbl can-tbl"><thead><tr>
                    <th class="num" style="width:70px">#</th><th class="num" style="width:90px">Time, s</th><th style="width:100px">Clock</th>
                    <th style="width:50px">Dir</th><th style="width:90px">ID</th><th style="width:60px">Flags</th><th style="width:40px">DLC</th>
                    <th>Data</th><th style="width:90px">ASCII</th></tr></thead><tbody>${rows}</tbody></table>`
                    : '<div class="tbl-empty">No frames</div>'}</div>
            </div>`;
        const els = box.querySelectorAll('.can-file-scroll');
        if (els[0] && scrolls.length) els[0].scrollTop = scrolls[0];
        if (els[1] && scrolls.length > 1 && !this._pageMoved) els[1].scrollTop = scrolls[1];
        this._pageMoved = false;
    },

    // ── trace files tree ───────────────────────────────────────────────────

    loadTree() {
        return App.api('/api/can/traces').then(d => { this.tree = d.tree; this._renderTree(); })
            .catch(e => { document.getElementById('can-tree').innerHTML = `<div class="tree-note text-error">${esc(e.message)}</div>`; });
    },

    _treeAction(d) {
        if (d && d.tree) {
            this.tree = d.tree;
            this._renderTree();
        }
        return d;
    },

    _renderTree() {
        const files = new Set(this._files().map(f => f.path));
        if (this.selected && !files.has(this.selected)) this.selected = '';
        if (this.file && !files.has(this.file.path)) this.closeFile();
        if (this.folder && !this._folders().includes(this.folder)) this.folder = '';
        const btn = (act, icon, title, cls = '') => `<button type="button" class="faction-btn ${cls}" data-act="${act}" title="${title}"><i class="${icon}"></i></button>`;
        const rows = [];
        const walk = (nodes, depth) => nodes.forEach(n => {
            const pad = `style="padding-left:${8 + depth * 14}px"`;
            if (n.dir) {
                const open = !this.collapsed.has(n.path);
                rows.push(`<div class="tree-row${this.folder === n.path ? ' folder-current' : ''}" data-path="${esc(n.path)}" data-dir="1" ${pad}>
                    <span class="arrow"><i class="fa-solid fa-chevron-${open ? 'down' : 'right'}"></i></span>
                    <span class="ico"><i class="fa-solid fa-folder${open ? '-open' : ''} can-ico-dir"></i></span>
                    <span class="lbl">${esc(n.name)}</span>
                    <span class="faction">${btn('mkdir', 'fa-solid fa-folder-plus', 'New folder inside')}` +
                    `<label class="faction-btn" title="Upload a candump log here"><i class="fa-solid fa-upload"></i><input type="file" accept=".log,text/plain" hidden data-folder="${esc(n.path)}" onchange="Devices.tabs.can.upload(this, this.dataset.folder)"></label>` +
                    `${btn('rename', 'fa-solid fa-pen', 'Rename')}${btn('delete', 'fa-regular fa-trash-can', 'Delete (to .trash)', 'faction-del')}</span>
                </div>`);
                if (open) walk(n.children, depth + 1);
            } else {
                const cls = [this.selected === n.path ? 'selected' : '', this.rec && this.rec.path === n.path ? 'can-rec-file' : '',
                             this.play && this.play.path === n.path ? 'can-play-row' : ''].join(' ');
                rows.push(`<div class="tree-row ${cls}" data-path="${esc(n.path)}" data-file="1" ${pad} title="${esc(n.path)} · ${esc(App.fmtDate(n.mtime))}&#10;Double-click: play">
                    <span class="arrow"></span>
                    <span class="ico"><i class="fa-solid fa-file-lines can-ico-file"></i></span>
                    <span class="lbl">${esc(n.name.replace(/\.log$/i, ''))}</span>
                    <span class="fsize">${App.fmtBytes(n.size)}</span>
                    <span class="faction">${btn('download', 'fa-solid fa-download', 'Download')}${btn('rename', 'fa-solid fa-pen', 'Rename')}` +
                    `${btn('delete', 'fa-regular fa-trash-can', 'Delete (to .trash)', 'faction-del')}</span>
                </div>`);
            }
        });
        walk(this.tree, 0);
        document.getElementById('can-tree').innerHTML = rows.join('') ||
            '<div class="tree-note muted">No traces yet — press Record, or upload a candump log.</div>';
        this._renderPlayer();
    },

    _treeClick(e, dbl) {
        const row = e.target.closest('.tree-row');
        if (!row || e.target.closest('label')) return;
        const path = row.dataset.path;
        const act = e.target.closest('[data-act]');
        if (act) {
            e.stopPropagation();
            if (!dbl) this._fileAct(act.dataset.act, path, !!row.dataset.dir);
            return;
        }
        if (row.dataset.dir) {
            if (dbl) return;
            this.folder = path;
            if (this.collapsed.has(path)) this.collapsed.delete(path);
            else this.collapsed.add(path);
            try { localStorage.setItem('can.collapsed', JSON.stringify([...this.collapsed])); } catch (err) { /* private mode */ }
            this._renderTree();
            return;
        }
        this.folder = path.includes('/') ? path.slice(0, path.lastIndexOf('/')) : '';
        if (dbl) {
            if (!this.play) this.playButton();
            return;
        }
        this.openFile(path);
    },

    _fileAct(act, path, isDir) {
        const name = path.split('/').pop();
        if (act === 'download') {
            location.href = '/api/can/traces/download?path=' + encodeURIComponent(path);
        } else if (act === 'mkdir') {
            this.mkdir(path);
        } else if (act === 'rename') {
            const shown = isDir ? name : name.replace(/\.log$/i, '');
            const next = (prompt(`Rename "${shown}" to:`, shown) || '').trim();
            if (!next || next === shown) return;
            App.api('/api/can/traces', { json: { action: 'rename', path, name: next } }).then(d => {
                const moved = p => p === path ? d.path : isDir && p.startsWith(path + '/') ? d.path + p.slice(path.length) : p;
                this.selected = moved(this.selected);
                if (this.file && moved(this.file.path) !== this.file.path) {
                    const to = moved(this.file.path);
                    if (this.skips[this.file.path]) { this.skips[to] = this.skips[this.file.path]; delete this.skips[this.file.path]; }
                    this.file.path = to;
                    this._fileTab();
                }
                this._treeAction(d);
            }).catch(e => toast(e.message, true));
        } else if (act === 'delete') {
            if (this.rec && (this.rec.path === path || this.rec.path.startsWith(path + '/'))) return toast('Stop the recording first', true);
            if (this.play && (this.play.path === path || this.play.path.startsWith(path + '/'))) return toast('Stop the replay first', true);
            if (!confirm(`Delete ${isDir ? 'folder' : 'file'} "${path}"? It is moved to canTraces/.trash.`)) return;
            App.api('/api/can/traces', { json: { action: 'delete', path } })
                .then(d => { this._treeAction(d); toast(`Deleted ${path}`); }).catch(e => toast(e.message, true));
        }
    },

    mkdir(parent) {
        const name = (prompt(`New folder in ${parent ? parent + '/' : 'canTraces/'}:`) || '').trim();
        if (!name) return;
        const path = parent ? `${parent}/${name}` : name;
        App.api('/api/can/traces', { json: { action: 'mkdir', path } }).then(d => {
            this.collapsed.delete(parent);
            this.folder = d.path;
            this._treeAction(d);
        }).catch(e => toast(e.message, true));
    },

    async upload(input, folder) {
        const file = input.files[0];
        input.value = '';
        if (!file) return;
        const fd = new FormData();
        fd.append('folder', folder || '');
        fd.append('file', file, file.name);
        try {
            const r = await fetch('/api/can/traces/upload', { method: 'POST', body: fd });
            if (r.status === 401) return App.requireLogin();
            const d = await r.json().catch(() => ({ error: 'HTTP ' + r.status }));
            if (!r.ok) throw new Error(d.error || 'Upload failed');
            this.selected = d.path;
            this._treeAction(d);
            toast(`Uploaded ${d.path}`);
        } catch (e) { toast(e.message, true); }
    },
});

window.addEventListener('pagehide', () => Devices.tabs.can.releaseOnUnload());
