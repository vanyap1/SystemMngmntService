/* ==========================================================================
   HW Utils → CAN: analyser of one ID (popup over the CAN tab).
   Live: every frame of the ID from the server's watch buffer (/api/net/can/watch,
   polled every POLL_MS while the popup is open — the CAN tab stops its own list
   meanwhile, other IDs are ignored). File: the frames of the ID from a trace file.
   Views: bit grid (click = plot the bit), HEX / ASCII, all 64 bits over time, signals
   (bit, u / s 8 – 64 LSB or MSB first) with charts (kept per ID in localStorage), frame list.
   ========================================================================== */

const CanAnalyzer = {
    POLL_MS: 100,
    MAX: 20000,             // frames kept in the browser
    HEAT: 240,              // frames in the "all bits" picture
    LIST: 200,              // rows in the frame list
    frames: [],             // {t, dir, dlc, b: [bytes], n}
    src: null,              // {kind: 'live'|'file', iface|path, key, label}
    since: 0,
    paused: false,
    win: 10,                // chart window, seconds (0 = everything)
    signals: [],
    changedAt: [],          // per bit (0..63): Date.now() of its last change
    _timer: null,

    $(id) { return document.getElementById(id); },

    isOpen() { return !!this.src; },

    /** Open for a live ID ({iface, key, label}) or a file ({path, key, label}). */
    open(src) {
        this.close(true);
        this.src = src;
        this.frames = [];
        this.since = 0;
        this.paused = false;
        this.changedAt = new Array(64).fill(0);
        this.signals = this._loadSignals();
        this.$('can-an').hidden = false;
        this.$('can-an-title').innerHTML = `<i class="fa-solid fa-microscope"></i> ID <b class="mono">${esc(src.label)}</b>` +
            `<span class="muted small">${src.kind === 'live' ? 'live on ' + esc(src.iface) + ' — other IDs are ignored'
                                                              : 'file ' + esc(src.path)}</span>`;
        this.$('can-an-pause').hidden = src.kind !== 'live';
        this._pauseUi();
        this._bind();
        this.render();
        if (src.kind === 'live') {
            this._poll();
            this._timer = setInterval(() => this._poll(), this.POLL_MS);
        } else {
            this._loadFile();
        }
    },

    close(silent) {
        if (!this.src) return;
        clearInterval(this._timer);
        this._timer = null;
        if (this.src.kind === 'live') {
            App.api('/api/net/can/watch', { json: { iface: this.src.iface } }).catch(() => {});
        }
        this.src = null;
        this.$('can-an').hidden = true;
        if (!silent && typeof Devices !== 'undefined') Devices.tabs.can.analyzerClosed();
    },

    togglePause() {
        this.paused = !this.paused;
        this._pauseUi();
        if (!this.paused) this.render();
    },

    _pauseUi() {
        const b = this.$('can-an-pause');
        b.innerHTML = this.paused ? '<i class="fa-solid fa-play"></i> Resume' : '<i class="fa-solid fa-pause"></i> Pause';
        b.classList.toggle('btn-warning', this.paused);
    },

    clear() {
        this.frames = [];
        this.changedAt.fill(0);
        this.render();
    },

    setWin(v) {
        this.win = +v;
        this._renderSignals();
    },

    // ── data ───────────────────────────────────────────────────────────────

    _poll() {
        if (this._busy || !this.src || this.src.kind !== 'live') return;
        this._busy = true;
        const src = this.src;
        App.api(`/api/net/can/watch?iface=${encodeURIComponent(src.iface)}&key=${encodeURIComponent(src.key)}&since=${this.since}`)
            .then(d => {
                if (this.src !== src) return;
                if (d.next < this.since) this.since = 0;
                this.since = d.next;
                this._add(d.frames);
                this.$('can-an-err').textContent = d.error || '';
                if (!this.paused) this.render();
            })
            .catch(e => { this.$('can-an-err').textContent = e.message; })
            .finally(() => { this._busy = false; });
    },

    async _loadFile() {
        const src = this.src;
        let start = 0, total = Infinity;
        this.$('can-an-err').textContent = 'Reading…';
        try {
            while (start < total && start < this.MAX && this.src === src) {
                const d = await App.api(`/api/can/traces/frames?path=${encodeURIComponent(src.path)}&key=${encodeURIComponent(src.key)}&start=${start}&limit=2000`);
                total = d.total;
                if (!d.frames.length) break;
                this._add(d.frames.map(f => Object.assign({}, f, { t: f.rel })));
                start += d.frames.length;
            }
            if (this.src !== src) return;
            this.$('can-an-err').textContent = total > this.MAX ? `first ${this.MAX} of ${total} frames` : '';
            this.render();
        } catch (e) {
            this.$('can-an-err').textContent = e.message;
        }
    },

    _add(list) {
        if (!list.length) return;
        const now = Date.now();
        let prev = this.frames[this.frames.length - 1];
        for (const f of list) {
            const b = [];
            for (let i = 0; i < f.data.length / 2; i++) b.push(parseInt(f.data.substr(i * 2, 2), 16));
            const fr = { t: f.t, dir: f.dir, dlc: f.dlc, b, data: f.data };
            if (prev) {
                for (let i = 0; i < 8; i++) {
                    const x = (b[i] || 0) ^ (prev.b[i] || 0);
                    if (x) for (let k = 0; k < 8; k++) if (x & (1 << k)) this.changedAt[i * 8 + k] = now;
                }
            }
            this.frames.push(fr);
            prev = fr;
        }
        if (this.frames.length > this.MAX) this.frames.splice(0, this.frames.length - this.MAX);
    },

    // ── decoding ───────────────────────────────────────────────────────────

    TYPES: {
        bit: { size: 0, label: 'bit' },
        u8: { size: 1, signed: false }, s8: { size: 1, signed: true },
        u16: { size: 2, signed: false }, s16: { size: 2, signed: true },
        u32: { size: 4, signed: false }, s32: { size: 4, signed: true },
        u64: { size: 8, signed: false },
        ascii: { size: 0, label: 'ASCII' },
    },

    /** Value of a signal in a frame's bytes, or null when the frame is too short. */
    decode(b, sig) {
        if (sig.type === 'bit') {
            const v = b[sig.byte];
            return v == null ? null : (v >> sig.bit) & 1;
        }
        if (sig.type === 'ascii') return null;
        const T = this.TYPES[sig.type], n = T.size;
        if (sig.byte + n > b.length) return null;
        let v = 0;
        for (let i = 0; i < n; i++) {
            const byte = b[sig.byte + (sig.order === 'be' ? i : n - 1 - i)];
            v = v * 256 + byte;
        }
        if (T.signed && v >= 2 ** (8 * n - 1)) v -= 2 ** (8 * n);
        return v * (sig.scale ?? 1) + (sig.offset ?? 0);
    },

    _fmt(v, sig) {
        if (v == null) return '—';
        if (sig.type === 'bit') return String(v);
        const scaled = (sig.scale ?? 1) !== 1 || (sig.offset ?? 0) !== 0;
        return scaled ? (+v.toFixed(6)).toString() : String(v);
    },

    _sigName(s) {
        if (s.name) return s.name;
        if (s.type === 'bit') return `byte ${s.byte} bit ${s.bit}`;
        return `${s.type}${this.TYPES[s.type].size > 1 ? (s.order === 'be' ? ' MSB' : ' LSB') : ''} @${s.byte}`;
    },

    // ── signals (per ID, localStorage) ──────────────────────────────────────

    _sigKey() { return 'can.sig.' + this.src.key; },

    _loadSignals() {
        try { return JSON.parse(localStorage.getItem('can.sig.' + this.src.key) || '[]') || []; } catch (e) { return []; }
    },

    _saveSignals() {
        try { localStorage.setItem(this._sigKey(), JSON.stringify(this.signals)); } catch (e) { /* private mode */ }
    },

    addSignal(sig) {
        sig = Object.assign({ name: '', byte: 0, bit: 0, order: 'le', scale: 1, offset: 0 }, sig);
        if (this.signals.some(s => s.type === sig.type && s.byte === sig.byte && s.bit === sig.bit && s.order === sig.order)) {
            return toast('Already plotted');
        }
        this.signals.push(sig);
        this._saveSignals();
        this._renderSignals();
    },

    addFromForm() {
        const type = this.$('can-an-type').value;
        const sig = { type, byte: +this.$('can-an-byte').value, bit: +this.$('can-an-bit').value,
                      order: this.$('can-an-order').value, scale: parseFloat(this.$('can-an-scale').value) || 1,
                      offset: parseFloat(this.$('can-an-offset').value) || 0, name: this.$('can-an-name').value.trim() };
        const T = this.TYPES[type];
        if (T.size && sig.byte + T.size > 8) return toast(`${type} at byte ${sig.byte} does not fit into 8 bytes`, true);
        this.$('can-an-name').value = '';
        this.addSignal(sig);
    },

    removeSignal(i) {
        this.signals.splice(i, 1);
        this._saveSignals();
        this._renderSignals();
    },

    _formUi() {
        const t = this.$('can-an-type').value;
        this.$('can-an-bitwrap').hidden = t !== 'bit';
        this.$('can-an-order').hidden = !(this.TYPES[t].size > 1);
    },

    // ── rendering ──────────────────────────────────────────────────────────

    _bind() {
        if (this._bound) return;
        this._bound = true;
        this.$('can-an-bits').addEventListener('click', e => {
            const c = e.target.closest('[data-k]');
            if (c) this.addSignal({ type: 'bit', byte: +c.dataset.byte, bit: +c.dataset.k });
        });
        this.$('can-an-sigs').addEventListener('click', e => {
            const b = e.target.closest('[data-del]');
            if (b) this.removeSignal(+b.dataset.del);
        });
        this.$('can-an-type').addEventListener('change', () => this._formUi());
        this._formUi();
        // Escape closes only the analyser (capture phase, before the HW Utils popup sees it)
        document.addEventListener('keydown', e => {
            if (e.key === 'Escape' && this.isOpen()) {
                e.stopImmediatePropagation();
                e.preventDefault();
                this.close();
            }
        }, true);
    },

    render() {
        if (!this.src) return;
        this._renderHead();
        this._renderBits();
        this._renderInterp();
        this._renderHeat();
        this._renderSignals();
        this._renderList();
    },

    _renderHead() {
        const f = this.frames, n = f.length;
        let txt = `${n} frames`;
        if (n > 1) {
            const last = f[n - 1].t;
            const rate = f.filter(x => x.t > last - 1).length;
            const k = Math.min(n - 1, 500);
            let sum = 0, mn = Infinity, mx = 0;
            for (let i = n - k; i < n; i++) {
                const d = f[i].t - f[i - 1].t;
                sum += d; mn = Math.min(mn, d); mx = Math.max(mx, d);
            }
            const ms = v => (v * 1000).toFixed(v < 0.1 ? 2 : 1);
            txt += ` · ${this.src.kind === 'live' ? rate + ' fps · ' : ''}cycle ${ms(sum / k)} ms ` +
                   `<span class="faint">(min ${ms(mn)} · max ${ms(mx)} · last ${ms(f[n - 1].t - f[n - 2].t)}, over ${k})</span>`;
        }
        this.$('can-an-stats').innerHTML = txt;
    },

    _renderBits() {
        const last = this.frames[this.frames.length - 1];
        const b = last ? last.b : [];
        const now = Date.now();
        let html = '<table class="can-an-bits"><thead><tr><th></th>' +
            [7, 6, 5, 4, 3, 2, 1, 0].map(k => `<th>${k}</th>`).join('') + '<th>hex</th><th>dec</th></tr></thead><tbody>';
        for (let i = 0; i < 8; i++) {
            const v = b[i];
            html += `<tr><th>B${i}</th>`;
            for (let k = 7; k >= 0; k--) {
                const bit = v == null ? null : (v >> k) & 1;
                const fresh = now - this.changedAt[i * 8 + k] < 1000;
                html += `<td class="can-an-bit${bit ? ' on' : ''}${bit == null ? ' none' : ''}${fresh ? ' chg' : ''}" data-byte="${i}" data-k="${k}"` +
                        ` title="byte ${i} bit ${k} (bit ${i * 8 + k} LSB-first) — click to plot">${bit == null ? '·' : bit}</td>`;
            }
            html += `<td class="mono">${v == null ? '' : v.toString(16).toUpperCase().padStart(2, '0')}</td><td class="mono faint">${v == null ? '' : v}</td></tr>`;
        }
        this.$('can-an-bits').innerHTML = html + '</tbody></table>';
    },

    /** The whole payload as one line: ASCII and HEX. */
    _renderInterp() {
        const last = this.frames[this.frames.length - 1];
        const b = last ? last.b : [];
        const ascii = b.map(c => c >= 32 && c < 127 ? String.fromCharCode(c) : '·').join('');
        const hex = b.map(c => c.toString(16).toUpperCase().padStart(2, '0')).join(' ');
        this.$('can-an-interp').innerHTML = `<div class="can-an-str"><span class="muted">HEX</span><span class="mono">${hex || '—'}</span>
            <span class="muted">ASCII</span><span class="mono can-an-ascii">${esc(ascii) || '—'}</span></div>`;
    },

    _css(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); },

    _canvas(el) {
        const dpr = window.devicePixelRatio || 1, w = el.clientWidth, h = el.clientHeight;
        if (el.width !== Math.round(w * dpr) || el.height !== Math.round(h * dpr)) {
            el.width = Math.round(w * dpr);
            el.height = Math.round(h * dpr);
        }
        const ctx = el.getContext('2d');
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        ctx.clearRect(0, 0, w, h);
        return { ctx, w, h };
    },

    /** All 64 bits of the last HEAT frames: x = frame (newest right), y = byte 0 bit 7 … byte 7 bit 0. */
    _renderHeat() {
        const el = this.$('can-an-heat');
        if (!el.clientWidth) return;
        const { ctx, w, h } = this._canvas(el);
        const list = this.frames.slice(-this.HEAT);
        const on = this._css('--accent'), grid = this._css('--border'), chg = this._css('--warn');
        const cw = w / this.HEAT, rh = h / 64;
        list.forEach((f, x) => {
            const p = list[x - 1];
            for (let i = 0; i < 8; i++) {
                const v = f.b[i];
                if (v == null) continue;
                for (let k = 7; k >= 0; k--) {
                    const y = (i * 8 + 7 - k) * rh;
                    const bit = (v >> k) & 1;
                    const changed = p && p.b[i] != null && ((p.b[i] >> k) & 1) !== bit;
                    if (bit || changed) {
                        ctx.fillStyle = changed ? chg : on;
                        ctx.fillRect(w - (list.length - x) * cw, y, Math.max(1, cw), Math.max(1, rh - 0.5));
                    }
                }
            }
        });
        ctx.fillStyle = grid;
        for (let i = 1; i < 8; i++) ctx.fillRect(0, i * 8 * rh - 0.5, w, 1);
    },

    _renderSignals() {
        const box = this.$('can-an-sigs');
        if (!this.signals.length) {
            box.innerHTML = '<div class="muted small can-an-hint">Click a bit in the grid to plot it, or add a signal (u8 … u64, LSB / MSB first) above.</div>';
            return;
        }
        const last = this.frames[this.frames.length - 1];
        if (box.children.length !== this.signals.length || box.dataset.sig !== JSON.stringify(this.signals)) {
            box.dataset.sig = JSON.stringify(this.signals);
            box.innerHTML = this.signals.map((s, i) => `<div class="can-an-sig">
                <div class="can-an-sig-head"><b>${esc(this._sigName(s))}</b>
                    <span class="faint small">${s.name ? esc(this._sigName(Object.assign({}, s, { name: '' }))) : ''}${(s.scale ?? 1) !== 1 || (s.offset ?? 0) !== 0 ? ` ×${s.scale} ${s.offset >= 0 ? '+' : ''}${s.offset}` : ''}</span>
                    <span class="spacer"></span><span class="mono can-an-val" data-val="${i}"></span>
                    <span class="faint small mono" data-mm="${i}"></span>
                    <button type="button" class="btn-icon" data-del="${i}" title="Remove"><i class="fa-solid fa-xmark"></i></button></div>
                <canvas class="can-an-chart${s.type === 'bit' ? ' bit' : ''}" data-chart="${i}"></canvas></div>`).join('');
        }
        const col = this._css('--info'), axis = this._css('--text-mute'), grid = this._css('--border');
        this.signals.forEach((s, i) => {
            box.querySelector(`[data-val="${i}"]`).textContent = last ? this._fmt(this.decode(last.b, s), s) : '—';
            const el = box.querySelector(`[data-chart="${i}"]`);
            if (!el.clientWidth) return;
            const { ctx, w, h } = this._canvas(el);
            const end = last ? last.t : 0, start = this.win ? end - this.win : (this.frames[0] ? this.frames[0].t : 0);
            const pts = [];
            for (let k = this.frames.length - 1; k >= 0; k--) {
                const f = this.frames[k];
                if (f.t < start) { const v = this.decode(f.b, s); if (v != null) pts.unshift([start, v]); break; }
                const v = this.decode(f.b, s);
                if (v != null) pts.unshift([f.t, v]);
            }
            if (!pts.length) return;
            let mn = Math.min(...pts.map(p => p[1])), mx = Math.max(...pts.map(p => p[1]));
            box.querySelector(`[data-mm="${i}"]`).textContent = s.type === 'bit' ? '' : `${this._fmt(mn, s)} … ${this._fmt(mx, s)}`;
            if (s.type === 'bit') { mn = 0; mx = 1; }
            if (mx === mn) { mx += 1; mn -= 1; }
            const pad = 4, span = Math.max(1e-9, end - start);
            const X = t => (t - start) / span * (w - 2) + 1, Y = v => h - pad - (v - mn) / (mx - mn) * (h - 2 * pad);
            ctx.strokeStyle = grid;
            ctx.lineWidth = 1;
            ctx.beginPath(); ctx.moveTo(0, Y(mn) + 0.5); ctx.lineTo(w, Y(mn) + 0.5); ctx.stroke();
            ctx.strokeStyle = col;
            ctx.lineWidth = 1.5;
            ctx.beginPath();
            pts.forEach(([t, v], k) => {
                const x = X(t), y = Y(v);
                if (!k) ctx.moveTo(x, y);
                else { ctx.lineTo(x, Y(pts[k - 1][1])); ctx.lineTo(x, y); }     // steps: a value holds until the next frame
            });
            ctx.lineTo(X(end), Y(pts[pts.length - 1][1]));
            ctx.stroke();
            ctx.fillStyle = axis;
            ctx.font = '10px ' + this._css('--mono');
            if (s.type !== 'bit') {
                ctx.fillText(this._fmt(mx, s), 3, 10);
                ctx.fillText(this._fmt(mn, s), 3, h - 3);
            }
        });
    },

    _renderList() {
        const list = this.frames.slice(-this.LIST).reverse();
        const live = this.src.kind === 'live';
        this.$('can-an-list').innerHTML = list.length ? `<table class="tbl dev-tbl can-tbl"><thead><tr>
            <th style="width:100px">${live ? 'Time' : 'Time, s'}</th><th class="num" style="width:70px">Δt, ms</th><th style="width:40px">Dir</th>
            <th>Data</th></tr></thead><tbody>` + list.map((f, k) => {
                const p = list[k + 1];
                const bytes = f.b.map((v, i) => {
                    const h = v.toString(16).toUpperCase().padStart(2, '0');
                    return p && p.b[i] !== v ? `<b class="can-chg">${h}</b>` : h;
                }).join(' ');
                return `<tr><td class="mono small">${live ? Devices.fmtMs(f.t) : f.t.toFixed(3)}</td>
                    <td class="mono small num">${p ? ((f.t - p.t) * 1000).toFixed(1) : ''}</td>
                    <td class="small">${f.dir.toUpperCase()}</td><td class="mono">${bytes}</td></tr>`;
            }).join('') + '</tbody></table>' : '<div class="tbl-empty">Waiting for frames of this ID…</div>';
    },
};
