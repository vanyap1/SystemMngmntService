/* ==========================================================================
   HW Utils tab "Terminal" (core/ttyterm.py, /api/tty/*): serial port, TCP client or UDP socket.
   Everything received is shown as text lines (\r\n, \n, \r) or as a hex dump; JSON objects in the stream (one per
   line or spread over lines) are parsed — a badge shows them pretty, numeric fields are collected for the plot popup.
   Send field with line ending, hex mode, history. Not connected, a send is one-shot: open → send → reply → close
   (/api/tty/oneshot, e.g. SCPI over TCP); connected, it goes through the open connection. Macro table with timers,
   profiles per host, sessions saved as files. The connection is polled while open; it is closed by Close, page
   leave, or the server lease (30 s unread).
   ========================================================================== */

Devices.register({
    id: 'tty',
    autoMs: 0,
    info: null,
    profiles: [], cur: '',
    sid: null, state: null, next: 0, pollT: null,
    raw: [],                 // received / sent chunks {t, dir, bytes, src} (for the hex view and re-render)
    lines: [],               // display lines {t, dir, text, src, json}
    open: { rx: null, tx: null },   // line being received per direction (not finished by a line break yet)
    carryCR: { rx: false, tx: false },
    dec: {},
    jsonBuf: null,           // multi-line JSON being collected {start, text, depth}
    series: {},              // path -> {pts: [[t, v]], last}
    plotSel: new Set(),
    paused: false,
    hist: [], histPos: -1,
    timersOn: false, timerT: null, due: {},
    macRes: [],              // per macro: {ok, text, ms, end, at}
    session: '', sessions: [],
    _saveT: null,
    MAX_LINES: 5000, MAX_RAW: 20000, MAX_PTS: 5000, MAX_LINE: 4000,
    DEFAULT_EOL: { serial: 'lf', tcp: 'crlf', udp: '' },

    $(id) { return document.getElementById(id); },

    load() {
        return App.api('/api/tty/info').then(d => {
            const first = !this.info;
            this.info = d;
            if (first) {
                this.profiles = d.profiles.length ? d.profiles : [this._newProfile('Default')];
                this.cur = d.current || this.profiles[0].name;
                this.$('tt-baud').innerHTML = d.bauds.map(b => `<option>${b}</option>`).join('');
                this._wire();
                this.render();
            }
            this._ports();
            this.$('tt-blocked').textContent = d.blocked || '';
            return this.listSessions();
        });
    },

    _wire() {
        const inp = this.$('tt-input');
        inp.addEventListener('keydown', e => {
            if (e.key === 'Enter') { e.preventDefault(); this.sendInput(); }
            else if (e.key === 'ArrowUp' && this.hist.length) {
                e.preventDefault();
                this.histPos = Math.min(this.hist.length - 1, this.histPos + 1);
                inp.value = this.hist[this.histPos];
            } else if (e.key === 'ArrowDown') {
                e.preventDefault();
                this.histPos = Math.max(-1, this.histPos - 1);
                inp.value = this.histPos >= 0 ? this.hist[this.histPos] : '';
            }
        });
        this.$('tt-note').addEventListener('input', () => this._noteSave());
        this.$('tt-note').addEventListener('keydown', e => { if (e.key === 'Escape') { e.stopPropagation(); this.noteToggle(false); } });
        this.$('tt-out').addEventListener('click', e => {
            const b = e.target.closest('[data-json]');
            if (b) Devices.showText('JSON', Promise.resolve(JSON.stringify(this.lines[+b.dataset.json].json, null, 2)));
        });
        window.addEventListener('pagehide', () => {
            if (this.sid) navigator.sendBeacon('/api/tty/close', new Blob([JSON.stringify({ id: this.sid })], { type: 'application/json' }));
        });
    },

    _newProfile(name) {
        const port = this.info && this.info.ports.find(p => /USB|ACM/.test(p.device));
        return { name, eol: 'lf', wait: true, replyMs: 1000, conn: { transport: 'serial', port: port ? port.device : '/dev/ttyUSB0', baud: '115200', parity: 'N',
                 bytesize: '8', stopbits: '1', host: '', netport: '', listen: '' }, commands: [], view: { time: true, tx: true, json: true } };
    },

    prof() { return this.profiles.find(p => p.name === this.cur) || this.profiles[0]; },

    _ports() {
        const c = this.prof().conn, list = this.info.ports.slice();
        if (c.port && !list.some(p => p.device === c.port)) list.push({ device: c.port, description: 'not present' });
        this.$('tt-port').innerHTML = list.map(p => `<option value="${esc(p.device)}"${p.device === c.port ? ' selected' : ''}>` +
            `${esc(p.device)}${p.description ? ' · ' + esc(p.description) : ''}</option>`).join('') || '<option value="">no serial port</option>';
    },

    // ── Render ─────────────────────────────────────────────

    render() {
        if (!this.info) return;
        const p = this.prof(), c = p.conn, v = p.view || {};
        this.cur = p.name;
        this.$('tt-prof').innerHTML = this.profiles.map(x => `<option${x.name === p.name ? ' selected' : ''}>${esc(x.name)}</option>`).join('');
        this.$('tt-transport').value = c.transport || 'serial';
        this._ports();
        this.$('tt-baud').value = String(c.baud || 115200);
        this.$('tt-frame').value = `${c.bytesize || 8}${c.parity || 'N'}${c.stopbits || 1}`;
        this.$('tt-host').value = c.host || '';
        this.$('tt-netport').value = c.netport || '';
        this.$('tt-listen').value = c.listen || '';
        this.$('tt-eol').value = p.eol == null ? 'lf' : p.eol;
        this.$('tt-wait').checked = p.wait !== false;
        this.$('tt-reply-ms').value = p.replyMs || 1000;
        this.$('tt-time').checked = v.time !== false;
        this.$('tt-tx').checked = v.tx !== false;
        this.$('tt-json').checked = v.json !== false;
        this.$('tt-wrap').checked = !!v.wrap;
        this.$('tt-out').classList.toggle('wrap', !!v.wrap);
        this._mode(v.hex ? 'hex' : 'text');
        this._setNote(p.note);
        this._fields();
        this._connUi();
        this.renderCommands();
    },

    _fields() {
        const t = this.$('tt-transport').value;
        document.querySelectorAll('#devpane-tty .tt-f').forEach(el => {
            el.hidden = !(el.classList.contains('tt-' + t) || (el.classList.contains('tt-net') && t !== 'serial'));
        });
        this.$('tt-netport').placeholder = t === 'udp' ? 'send to port' : 'port';
        this.$('tt-host').placeholder = t === 'udp' ? 'send to host (optional)' : '192.168.1.50';
    },

    _connUi() {
        const on = !!this.sid && this.state && !this.state.closed, st = this.state, b = this.$('tt-connect');
        b.innerHTML = on ? '<i class="fa-solid fa-xmark"></i> Close' : '<i class="fa-solid fa-plug"></i> Connect';
        b.classList.toggle('btn-danger', on);
        b.classList.toggle('btn-primary', !on);
        ['tt-transport', 'tt-port', 'tt-baud', 'tt-frame', 'tt-host', 'tt-netport', 'tt-listen'].forEach(id => { this.$(id).disabled = on; });
        this.$('tt-state').innerHTML = on ? `<span class="badge badge-ok">open</span> <span class="hint mono">${esc(st.title)}${st.local ? ' · ' + esc(st.local) : ''}</span>`
            : st && st.error ? `<span class="badge badge-error">closed</span> <span class="hint text-error">${esc(st.error)}</span>` : '<span class="badge">closed</span>';
        const ser = on && st.conn.transport === 'serial' && st.lines;
        this.$('tt-lines').hidden = !ser;
        if (ser) document.querySelectorAll('#tt-lines [data-line]').forEach(x => x.classList.toggle('btn-warning', !!st.lines[x.dataset.line]));
        this.$('tt-stats').innerHTML = st ? `RX ${esc(App.fmtBytes(st.rx))} · TX ${esc(App.fmtBytes(st.tx))}` +
            (st.flood ? ' · <span class="badge badge-error" title="Too much data: it is counted, not shown">flood guard</span>' : '') +
            (st.dropped ? ` · <span class="text-warn" title="Not shown because of the flood guard">dropped ${esc(App.fmtBytes(st.dropped))}</span>` : '') : '';
        Devices.summary(on ? `Terminal: ${st.title}` : 'Terminal: not connected', this.id);
    },

    // ── Connection ─────────────────────────────────────────

    _conn() {
        const c = this.prof().conn;
        return { transport: c.transport, port: c.port, baud: c.baud, parity: c.parity, bytesize: c.bytesize, stopbits: c.stopbits,
                 host: c.host, netport: c.netport, listen: c.listen };
    },

    toggleConnect() { return this.sid && this.state && !this.state.closed ? this.disconnect() : this.connect(); },

    connect() {
        const b = this.$('tt-connect');
        b.disabled = true;
        return App.api('/api/tty/open', { json: { conn: this._conn() } }).then(st => {
            this.sid = st.id; this.state = st; this.next = 0;
            this.open = { rx: null, tx: null }; this.dec = {}; this.carryCR = { rx: false, tx: false };
            this._connUi();
            this._poll();
            this.$('tt-input').focus();
        }).catch(e => toast(e.message, true)).finally(() => { b.disabled = false; });
    },

    disconnect() {
        const sid = this.sid;
        return App.api('/api/tty/close', { json: { id: sid } }).then(st => { this.state = st; })
            .catch(() => {}).finally(() => { this._pollOnce(sid).finally(() => { clearTimeout(this.pollT); this.sid = null; this._connUi(); }); });
    },

    _pollOnce(sid) {
        if (!sid) return Promise.resolve();
        return App.api(`/api/tty/read?id=${sid}&since=${this.next}`).then(d => {
            if (sid !== this.sid) return d;
            d.chunks.forEach(c => this._chunk(c));
            this.next = d.next;
            this.state = d.state;
            if (d.chunks.length) this._flushRender();
            this._connUi();
            return d;
        });
    },

    _poll() {
        clearTimeout(this.pollT);
        const sid = this.sid;
        this._pollOnce(sid).then(d => {
            if (sid !== this.sid) return;
            if (d.state.closed) { this.sid = null; this._connUi(); return; }
            this.pollT = setTimeout(() => this._poll(), d.more ? 0 : 250);
        }).catch(e => {
            if (sid !== this.sid) return;
            if (/not found/i.test(e.message)) { this.sid = null; this.state = Object.assign({}, this.state || {}, { closed: true, error: 'connection lost' }); this._connUi(); return; }
            this.pollT = setTimeout(() => this._poll(), 1000);
        });
    },

    toggleLine(line) {
        if (!this.sid || !this.state.lines) return;
        const body = { id: this.sid };
        body[line] = !this.state.lines[line];
        App.api('/api/tty/lines', { json: body }).then(st => { this.state = st; this._connUi(); }).catch(e => toast(e.message, true));
    },

    // ── Incoming data → lines ──────────────────────────────

    _b64(s) {
        const bin = atob(s), out = new Uint8Array(bin.length);
        for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
        return out;
    },

    _chunk(c) {
        const bytes = this._b64(c.b64), t = c.t * 1000;
        this.raw.push({ t, dir: c.dir, bytes, src: c.src });
        if (this.raw.length > this.MAX_RAW) this.raw.splice(0, this.raw.length - this.MAX_RAW);
        this._text(c.dir, bytes, t, c.src);
    },

    /** Bytes of one direction -> display lines (a datagram / a sent message always starts a new line). */
    _text(dir, bytes, t, src) {
        if (dir === 'sys') { this._close(dir); return this._push({ t, dir, text: new TextDecoder().decode(bytes) }); }
        if (dir === 'tx' || (src && this.state && this.state.conn && this.state.conn.transport === 'udp')) this._close(dir);
        const dec = this.dec[dir] || (this.dec[dir] = new TextDecoder('utf-8', { fatal: false }));
        let s = dec.decode(bytes, { stream: true });
        if (this.carryCR[dir]) { s = '\r' + s; this.carryCR[dir] = false; }
        if (s.endsWith('\r')) { this.carryCR[dir] = true; s = s.slice(0, -1); }
        const parts = s.replace(/\r\n/g, '\n').replace(/\r/g, '\n').split('\n');
        parts.forEach((p, k) => {
            const cur = this.open[dir];
            if (cur) { cur.text += p; cur.dirty = true; }
            else if (p !== '' || k < parts.length - 1) this.open[dir] = this._push({ t, dir, text: p, src }, true);
            if (k < parts.length - 1) this._close(dir);
        });
        if (dir === 'tx') this._close(dir);
    },

    /** Finish the open line of a direction (parse JSON, show it final). */
    _close(dir) {
        const l = this.open[dir];
        this.carryCR[dir] = false;
        if (!l) return;
        this.open[dir] = null;
        l.open = false; l.dirty = true;
        if (dir === 'rx' && this.$('tt-json').checked) this._json(l);
    },

    _push(l, open) {
        l.open = !!open; l.dirty = true; l.n = (this._n = (this._n || 0) + 1);
        this.lines.push(l);
        if (this.lines.length > this.MAX_LINES) { this.lines.splice(0, this.lines.length - this.MAX_LINES); this._rebuild = true; }
        return l;
    },

    // ── JSON ───────────────────────────────────────────────

    /** Brace depth of a text outside strings (for JSON spread over several lines). */
    _depth(s) {
        let d = 0, str = false, esc_ = false;
        for (const ch of s) {
            if (str) { if (esc_) esc_ = false; else if (ch === '\\') esc_ = true; else if (ch === '"') str = false; continue; }
            if (ch === '"') str = true;
            else if (ch === '{' || ch === '[') d++;
            else if (ch === '}' || ch === ']') d--;
        }
        return d;
    },

    _json(l) {
        if (l.text.length > 200000) return;
        const text = l.text.trim();
        if (this.jsonBuf) {                                  // collecting a multi-line object
            const b = this.jsonBuf;
            b.text += '\n' + l.text; b.depth += this._depth(l.text); b.lines.push(l);
            if (b.depth <= 0 || b.lines.length > 300) {
                this.jsonBuf = null;
                try { this._gotJson(b.lines[b.lines.length - 1], JSON.parse(b.text.slice(b.text.search(/[{[]/)))); } catch (e) { /* not JSON */ }
            }
            return;
        }
        const i = text.search(/[{[]/);
        if (i < 0) return;
        const body = text.slice(i), j = Math.max(body.lastIndexOf('}'), body.lastIndexOf(']'));
        if (j >= 0) {
            try { return this._gotJson(l, JSON.parse(body.slice(0, j + 1))); } catch (e) { /* maybe incomplete */ }
        }
        const d = this._depth(body);
        if (d > 0 && i === 0) this.jsonBuf = { text: body, depth: d, lines: [l] };
    },

    _gotJson(l, obj) {
        if (obj === null || typeof obj !== 'object') return;
        l.json = obj; l.dirty = true;
        let n = 0;
        const walk = (v, path) => {
            if (n > 300) return;
            if (typeof v === 'number' && isFinite(v)) { n++; this._point(path, l.t, v); }
            else if (typeof v === 'boolean') { n++; this._point(path, l.t, v ? 1 : 0); }
            else if (Array.isArray(v)) v.slice(0, 64).forEach((x, k) => walk(x, `${path}[${k}]`));
            else if (v && typeof v === 'object') Object.keys(v).slice(0, 200).forEach(k => walk(v[k], path ? `${path}.${k}` : k));
        };
        walk(obj, '');
        if (this.$('tt-plot-overlay').classList.contains('open')) this._plotDirty = true;
        this.$('tt-plot-btn').innerHTML = `<i class="fa-solid fa-chart-line"></i> Plot <span class="faint">(${Object.keys(this.series).length})</span>`;
    },

    _point(path, t, v) {
        if (!path) path = '(value)';
        const s = this.series[path] || (Object.keys(this.series).length < 500 ? (this.series[path] = { pts: [] }) : null);
        if (!s) return;
        s.pts.push([t, v]); s.last = v;
        if (s.pts.length > this.MAX_PTS) s.pts.splice(0, s.pts.length - this.MAX_PTS);
    },

    // ── Output rendering ───────────────────────────────────

    _fmtTime(t) { return Devices.fmtMs(t / 1000); },

    _lineHtml(l, i) {
        const time = this.$('tt-time').checked ? `<span class="tt-t">${this._fmtTime(l.t)}</span>` : '';
        const mark = { rx: '', tx: '<span class="tt-dir">›</span>', sys: '<span class="tt-dir">●</span>' }[l.dir];
        const src = l.src ? `<span class="tt-src">${esc(l.src)}</span>` : '';
        const js = l.json ? `<button class="tt-jb" data-json="${i}" title="Show the parsed JSON">{}</button>` : '';
        let text = l.text, pre = '', post = '';
        const head = text.slice(0, 600), bad = (head.match(/[\x00-\x08\x0e-\x1f\x7f\ufffd]/g) || []).length;
        if (head.length > 40 && bad / head.length > 0.2) {                // binary data: don't flood the page with garbage
            pre = `<span class="tt-cut">[binary, ${text.length} chars — use Hex]</span> `;
            text = text.slice(0, 64);
        } else if (text.length > this.MAX_LINE) {                         // very long line: show the start only
            post = ` <span class="tt-cut">… +${text.length - this.MAX_LINE} chars</span>`;
            text = text.slice(0, this.MAX_LINE);
        }
        const vis = pre + esc(text).replace(/[\x00-\x08\x0b-\x1f\x7f]/g, ch => `<span class="tt-ctl">\\x${ch.charCodeAt(0).toString(16).padStart(2, '0')}</span>`) + post;
        return `<div class="tt-l ${l.dir}${l.open ? ' open' : ''}">${time}${mark}${src}${js}<span class="tt-x">${vis || '&#8203;'}</span></div>`;
    },

    _hexHtml(c) {
        const out = [];
        for (let o = 0; o < c.bytes.length || (o === 0 && !c.bytes.length); o += 16) {
            const row = Array.from(c.bytes.slice(o, o + 16));
            const hex = row.map(b => b.toString(16).padStart(2, '0').toUpperCase()).join(' ');
            const asc = row.map(b => b >= 32 && b < 127 ? String.fromCharCode(b) : '·').join('');
            out.push(`<div class="tt-l ${c.dir}">${this.$('tt-time').checked && !o ? `<span class="tt-t">${this._fmtTime(c.t)}</span>` : this.$('tt-time').checked ? '<span class="tt-t"></span>' : ''}` +
                `<span class="tt-dir">${c.dir === 'tx' ? '›' : c.dir === 'sys' ? '●' : ''}</span>${c.src && !o ? `<span class="tt-src">${esc(c.src)}</span>` : ''}` +
                `<span class="tt-hex">${esc(hex.padEnd(47))}</span> <span class="tt-asc">${esc(asc)}</span></div>`);
            if (!c.bytes.length) break;
        }
        return out.join('');
    },

    _visible(dir) { return dir !== 'tx' || this.$('tt-tx').checked; },

    /** Full re-render (mode / option change, trimming). */
    rerender() {
        const out = this.$('tt-out');
        if (this.prof().view && this.prof().view.hex) {
            out.innerHTML = this.raw.slice(-3000).filter(c => this._visible(c.dir)).map(c => this._hexHtml(c)).join('');
        } else {
            out.innerHTML = this.lines.map((l, i) => this._visible(l.dir) ? this._lineHtml(l, i) : '').join('');
            this.lines.forEach(l => { l.dirty = false; l.el = null; });
        }
        this._rendered = this.raw.length;
        this._rebuild = false;
        this._scroll();
    },

    /** Incremental render: update the open lines, append new ones. */
    _flushRender() {
        if (this.paused) return;
        if (this._rebuild || this.prof().view && this.prof().view.hex) {
            if (this.prof().view && this.prof().view.hex && !this._rebuild) {
                const out = this.$('tt-out');
                const html = this.raw.slice(this._rendered || 0).filter(c => this._visible(c.dir)).map(c => this._hexHtml(c)).join('');
                out.insertAdjacentHTML('beforeend', html);
                this._rendered = this.raw.length;
                while (out.childElementCount > 12000) out.firstElementChild.remove();
                return this._scroll();
            }
            return this.rerender();
        }
        const out = this.$('tt-out');
        const nodes = out.children;
        const start = this.lines.findIndex(l => l.dirty);
        if (start < 0) return;
        // the DOM holds one node per visible line in order; rebuild the tail from the first dirty line
        const visibleBefore = this.lines.slice(0, start).filter(l => this._visible(l.dir)).length;
        while (nodes.length > visibleBefore) nodes[nodes.length - 1].remove();
        out.insertAdjacentHTML('beforeend', this.lines.slice(start).map((l, k) => this._visible(l.dir) ? this._lineHtml(l, start + k) : '').join(''));
        for (let i = start; i < this.lines.length; i++) this.lines[i].dirty = false;
        this._scroll();
    },

    _scroll() {
        if (this.$('tt-scroll').checked) { const o = this.$('tt-out'); o.scrollTop = o.scrollHeight; }
    },

    setMode(m) { this.prof().view = Object.assign({}, this.prof().view, { hex: m === 'hex' }); this._mode(m); this.rerender(); this.save(); },
    _mode(m) { document.querySelectorAll('#tt-mode button').forEach(b => b.classList.toggle('active', b.dataset.mode === m)); },

    viewInput() {
        this.prof().view = Object.assign({}, this.prof().view, { time: this.$('tt-time').checked, tx: this.$('tt-tx').checked,
                                                                  json: this.$('tt-json').checked, wrap: this.$('tt-wrap').checked });
        this.$('tt-out').classList.toggle('wrap', this.$('tt-wrap').checked);
        this.rerender(); this.save();
    },

    togglePause() {
        this.paused = !this.paused;
        this.$('tt-pause').innerHTML = `<i class="fa-solid ${this.paused ? 'fa-play' : 'fa-pause'}"></i>`;
        this.$('tt-pause').classList.toggle('text-warn', this.paused);
        if (!this.paused) this.rerender();
    },

    clear() {
        this.lines = []; this.raw = []; this.open = { rx: null, tx: null }; this.jsonBuf = null;
        this.rerender();
    },

    saveLog() {
        const text = this.lines.map(l => `${this._fmtTime(l.t)} ${({ rx: '<', tx: '>', sys: '#' })[l.dir]}${l.src ? ' ' + l.src : ''} ${l.text}`).join('\n');
        const a = document.createElement('a');
        a.href = URL.createObjectURL(new Blob([text + '\n'], { type: 'text/plain' }));
        a.download = `terminal_${new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')}.txt`;
        document.body.append(a); a.click();
        setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
    },

    // ── Sending ────────────────────────────────────────────

    _eolText(eol, hex) {
        const m = { lf: ['\\n', ' 0A'], cr: ['\\r', ' 0D'], crlf: ['\\r\\n', ' 0D 0A'] }[eol];
        return m ? m[hex ? 1 : 0] : '';
    },

    /** Send through the open connection, or one-shot (open → send → reply → close) when not connected.
        Resolves to {oneshot, text (reply), ms, end} for the macro table. */
    send(text, hex, eol, wait) {
        const payload = text + this._eolText(eol, hex);
        if (this.sid && this.state && !this.state.closed) {
            return App.api('/api/tty/send', { json: { id: this.sid, text: payload, hex } })
                .then(st => { this.state = st; this._connUi(); return { oneshot: false }; })
                .catch(e => { toast(e.message, true); throw e; });
        }
        const p = this.prof(), w = wait === undefined ? p.wait !== false : wait;
        return App.api('/api/tty/oneshot', { json: { conn: this._conn(), text: payload, hex, wait: w, timeout: p.replyMs || 1000 } }).then(r => {
            this.open = { rx: null, tx: null }; this.dec = {}; this.carryCR = { rx: false, tx: false };
            // compact: command + reply + one summary line (the open / closed notes of the server are left out)
            const keep = r.chunks.filter(c => c.dir !== 'sys' || /error|failed/i.test(atob(c.b64)));
            keep.forEach(c => this._chunk(c));
            this._close('rx');
            const last = r.chunks.length ? r.chunks[r.chunks.length - 1].t * 1000 : Date.now();
            this._push({ t: last, dir: 'sys', text: `one-shot ${r.state.title} · ${r.end === 'closed' ? 'closed by the peer' : r.end === 'idle' ? 'reply complete' : r.end === 'timeout' ? 'no more data (timeout)' : 'sent, no reply awaited'} · ${r.ms} ms` });
            this._flushRender();
            const parts = r.chunks.filter(c => c.dir === 'rx').map(c => this._b64(c.b64));
            const all = new Uint8Array(parts.reduce((n, x) => n + x.length, 0));
            parts.reduce((off, x) => { all.set(x, off); return off + x.length; }, 0);
            const reply = new TextDecoder().decode(all);
            return { oneshot: true, text: reply, ms: r.ms, end: r.end };
        }).catch(e => { toast(e.message, true); throw e; });
    },

    sendInput() {
        const inp = this.$('tt-input'), text = inp.value;
        const eol = this.$('tt-eol').value;
        if (!text && !eol) return;
        this.send(text, this.$('tt-hexsend').checked, eol, this.$('tt-wait').checked).then(() => {
            if (text && this.hist[0] !== text) this.hist.unshift(text);
            this.hist.length = Math.min(this.hist.length, 100);
            this.histPos = -1;                           // the command stays in the field: edit, send again
        }).catch(() => {});
    },

    eolInput() { this.prof().eol = this.$('tt-eol').value; this.save(); },

    replyInput() {
        const p = this.prof();
        p.wait = this.$('tt-wait').checked;
        p.replyMs = Math.max(50, parseInt(this.$('tt-reply-ms').value, 10) || 1000);
        this.save();
    },

    httpTemplate() {
        const c = this.prof().conn, host = c.host + (c.netport && c.netport !== '80' ? ':' + c.netport : '');
        this.$('tt-input').value = `GET / HTTP/1.1\\r\\nHost: ${host}\\r\\nUser-Agent: ${navigator.userAgent}\\r\\n` +
            `Accept: text/html,application/json,*/*\\r\\nAccept-Language: ${navigator.languages ? navigator.languages.join(',') : navigator.language}\\r\\nConnection: close\\r\\n`;
        this.$('tt-eol').value = 'crlf'; this.prof().eol = 'crlf';
        this.$('tt-hexsend').checked = false;
        this.$('tt-input').focus();
    },

    // ── Notes with [[command]] tags ────────────────────────

    renderNote() {
        const text = this.$('tt-note').value, view = this.$('tt-note-view');
        const cmds = [];
        const html = esc(text).replace(/\[\[([\s\S]+?)\]\]/g, (m, c) => {
            const raw = c.replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&#39;/g, "'").trim();
            cmds.push(raw);
            return `<span class="tt-cmdtag" data-cmd="${cmds.length - 1}"><span>${esc(raw)}</span>` +
                `<button class="btn-icon" data-na="copy" title="To the send field"><i class="fa-solid fa-arrow-down"></i></button>` +
                `<button class="btn-icon text-ok" data-na="send" title="Send now with the send field settings (line ending, hex, reply)"><i class="fa-solid fa-play"></i></button></span>`;
        });
        view.innerHTML = html || '<span class="faint">No notes yet — Edit (or double-click) to write. Wrap commands in [[ ]] to send them from here.</span>';
        view.onclick = e => {
            const b = e.target.closest('[data-na]'), tag = e.target.closest('[data-cmd]');
            if (!tag) return;
            const cmd = cmds[+tag.dataset.cmd];
            this.$('tt-input').value = cmd;
            if (b && b.dataset.na === 'send') this.sendInput();
            else this.$('tt-input').focus();
        };
        view.ondblclick = e => { if (!e.target.closest('[data-cmd]')) this.noteToggle(true); };
    },

    noteToggle(edit) {
        const ta = this.$('tt-note'), view = this.$('tt-note-view');
        const editing = edit === undefined ? ta.hidden : edit;
        ta.hidden = !editing; view.hidden = editing;
        this.$('tt-note-edit').innerHTML = editing ? '<i class="fa-solid fa-check"></i> Done' : '<i class="fa-solid fa-pen"></i> Edit';
        if (editing) ta.focus(); else { this.renderNote(); this._noteSave(); }
    },

    noteInsert() {
        const cmd = this.$('tt-input').value.trim();
        if (!cmd) return toast('Type the command in the send field first', true);
        const ta = this.$('tt-note');
        ta.value = (ta.value && !ta.value.endsWith('\n') ? ta.value + '\n' : ta.value) + `[[${cmd}]]`;
        this.renderNote(); this._noteSave();
    },

    _noteSave() { this.prof().note = this.$('tt-note').value; this.save(); },

    _setNote(text) {
        this.$('tt-note').value = text || '';
        this.noteToggle(false);
    },

    // ── Commands with timers ───────────────────────────────

    renderCommands() {
        const cmds = this.prof().commands || (this.prof().commands = []);
        const eolOpt = v => [['', 'none'], ['lf', 'LF'], ['cr', 'CR'], ['crlf', 'CRLF']].map(([k, l]) => `<option value="${k}"${k === (v || '') ? ' selected' : ''}>${l}</option>`).join('');
        this.$('tt-cmds').innerHTML = cmds.map((c, i) => `<tr data-i="${i}">` +
            `<td><input type="checkbox" data-f="timer"${c.timer ? ' checked' : ''} title="Repeat at its period while the timers run"></td>` +
            `<td><input class="input input-sm tt-cmd-name" data-f="name" value="${esc(c.name)}" placeholder="name"></td>` +
            `<td><input class="input input-sm mono tt-cmd-data" data-f="data" value="${esc(c.data)}" placeholder="${c.hex ? '01 03 00 00' : 'MEAS:VOLT?'}"></td>` +
            `<td><input type="checkbox" data-f="hex"${c.hex ? ' checked' : ''} title="Hex bytes"></td>` +
            `<td><select class="input input-sm" data-f="eol">${eolOpt(c.eol)}</select></td>` +
            `<td><input type="checkbox" data-f="wait"${c.wait !== false ? ' checked' : ''} title="Wait for the reply (one-shot)"></td>` +
            `<td><input class="input input-sm mono tt-cmd-ms" data-f="period" type="number" min="50" step="50" value="${c.period || 1000}"></td>` +
            `<td class="mb-act"><button class="btn-icon text-ok" data-a="send" title="Send now"><i class="fa-solid fa-play"></i></button>` +
            `<button class="btn-icon" data-a="up" title="Up"><i class="fa-solid fa-arrow-up"></i></button>` +
            `<button class="btn-icon" data-a="down" title="Down"><i class="fa-solid fa-arrow-down"></i></button>` +
            `<button class="btn-icon" data-a="dup" title="Duplicate"><i class="fa-regular fa-clone"></i></button>` +
            `<button class="btn-icon" data-a="del" title="Delete"><i class="fa-solid fa-xmark"></i></button></td>` +
            `<td class="tt-res" id="tt-res-${i}">${this._macResHtml(this.macRes[i])}</td></tr>`).join('') ||
            '<tr><td colspan="9" class="tbl-empty">No macros — type a command in the send field and press “+ Macro”.</td></tr>';
        const el = this.$('tt-cmds');
        el.oninput = el.onchange = e => {
            const t = e.target, row = t.closest('tr[data-i]');
            if (!row || !t.dataset.f) return;
            const c = cmds[+row.dataset.i], f = t.dataset.f;
            c[f] = t.type === 'checkbox' ? t.checked : f === 'period' ? Math.max(50, parseInt(t.value, 10) || 1000) : t.value;
            if (f === 'period' || f === 'timer') this.due[+row.dataset.i] = 0;
            this.save();
        };
        el.onclick = e => {
            const b = e.target.closest('[data-a]'), row = e.target.closest('tr[data-i]');
            if (!b || !row) return;
            const i = +row.dataset.i, swap = (a, c) => { [cmds[a], cmds[c]] = [cmds[c], cmds[a]]; [this.macRes[a], this.macRes[c]] = [this.macRes[c], this.macRes[a]]; };
            switch (b.dataset.a) {
                case 'send': return this.runMacro(i).catch(() => {});
                case 'up': if (i > 0) swap(i, i - 1); break;
                case 'down': if (i < cmds.length - 1) swap(i, i + 1); break;
                case 'dup': cmds.splice(i + 1, 0, Object.assign({}, cmds[i], { name: cmds[i].name + ' copy' })); this.macRes.splice(i + 1, 0, null); break;
                case 'del': cmds.splice(i, 1); this.macRes.splice(i, 1); break;
            }
            this.due = {};
            this.renderCommands(); this.save();
        };
        this._timersUi();
    },

    _macResHtml(r) {
        if (!r) return '';
        const time = `<span class="mb-ms" title="${esc(new Date(r.at).toLocaleTimeString())}">${r.ms != null ? r.ms + ' ms' : esc(new Date(r.at).toLocaleTimeString())}</span>`;
        if (!r.ok) return `<span class="text-error">${esc(r.error)}</span> ${time}`;
        if (!r.oneshot) return `<span class="faint">sent (reply in the output)</span> ${time}`;
        const txt = r.text.replace(/\s+$/, '');
        return (txt ? `<span class="mono" title="${esc(txt)}">${esc(txt.length > 160 ? txt.slice(0, 160) + '…' : txt)}</span>`
                    : `<span class="faint">${r.end === 'sent' ? 'sent' : 'no reply'}</span>`) + ' ' + time;
    },

    runMacro(i) {
        const c = this.prof().commands[i];
        const done = r => { this.macRes[i] = Object.assign({ ok: true, at: Date.now() }, r); const td = this.$('tt-res-' + i); if (td) td.innerHTML = this._macResHtml(this.macRes[i]); };
        return this.send(c.data || '', !!c.hex, c.eol || '', c.wait !== false).then(done)
            .catch(e => { done({ ok: false, error: e.message }); throw e; });
    },

    addCommand() {
        const cmds = this.prof().commands, data = this.$('tt-input').value;
        cmds.push({ name: '', data, hex: this.$('tt-hexsend').checked, eol: this.$('tt-eol').value, period: 1000, timer: false, wait: this.$('tt-wait').checked });
        this.renderCommands(); this.save();
        const names = this.$('tt-cmds').querySelectorAll('.tt-cmd-name');
        names[names.length - 1].focus();
    },

    toggleTimers() { this.timersOn ? this.stopTimers() : this.startTimers(); },

    /** One scheduler: the macro that is due is sent, the next one only after it finished (reply or error). */
    startTimers() {
        const on = () => this.prof().commands.map((c, i) => c.timer ? i : -1).filter(i => i >= 0);
        if (!on().length) return toast('No macro has the timer switched on', true);
        this.timersOn = true; this.due = {};
        let errors = 0;
        const tick = () => {
            if (!this.timersOn) return;
            const now = performance.now(), cmds = this.prof().commands, list = on();
            if (!list.length) return this.stopTimers();
            const i = list.find(k => !(this.due[k] > now));
            if (i === undefined) { this.timerT = setTimeout(tick, Math.max(5, Math.min(200, Math.min(...list.map(k => this.due[k])) - now))); return; }
            this.due[i] = now + Math.max(50, +cmds[i].period || 1000);
            this.runMacro(i).then(() => { errors = 0; }).catch(() => { if (++errors >= 5) { this.stopTimers(); toast('Timers stopped after 5 errors in a row', true); } })
                .finally(() => { if (this.timersOn) this.timerT = setTimeout(tick, 5); });
        };
        tick();
        this._timersUi();
    },

    stopTimers() { this.timersOn = false; clearTimeout(this.timerT); this._timersUi(); },

    _timersUi() {
        const b = this.$('tt-timers');
        b.innerHTML = this.timersOn ? '<i class="fa-solid fa-stop"></i> Stop timers' : '<i class="fa-solid fa-repeat"></i> Start timers';
        b.classList.toggle('btn-warning', this.timersOn);
        b.classList.toggle('btn-ghost', !this.timersOn);
    },

    // ── Sessions (files on the controller) ─────────────────

    listSessions() {
        return App.api('/api/tty/sessions').then(d => { this.sessions = d.sessions; this._renderSessions(); });
    },

    _renderSessions() {
        const fmt = t => new Date(t * 1000).toLocaleString([], { dateStyle: 'short', timeStyle: 'short' });
        this.$('tt-sess').innerHTML = `<option value="">${this.sessions.length ? '— open a session —' : '— no saved sessions —'}</option>` +
            this.sessions.map(x => `<option value="${esc(x.name)}"${x.name === this.session ? ' selected' : ''}>${esc(x.name)} · ${x.rows} macro(s) · ${esc(fmt(x.saved))}</option>`).join('');
    },

    saveSession() {
        const name = (prompt('Session name:', this.session || `${this.prof().name} ${new Date().toISOString().slice(0, 10)}`) || '').trim();
        if (!name) return;
        const p = this.prof();
        const data = { profile: { conn: p.conn, eol: p.eol, wait: p.wait, replyMs: p.replyMs, view: p.view, commands: p.commands },
                       lines: this.lines.map(l => ({ t: l.t, dir: l.dir, text: l.text, src: l.src || '' })), note: this.$('tt-note').value };
        const go = overwrite => App.api('/api/tty/session/save', { json: { name, data, overwrite } }).then(r => {
            this.session = r.name; this.sessions = r.sessions; this._renderSessions();
            toast(`Session "${r.name}" saved`);
        });
        go(false).catch(e => {
            if (/already exists/.test(e.message) && confirm(`Session "${name}" exists. Overwrite it?`)) return go(true).catch(x => toast(x.message, true));
            toast(e.message, true);
        });
    },

    loadSession(name) {
        if (!name) return;
        if (this.sid && this.state && !this.state.closed) { toast('Close the connection first', true); return this._renderSessions(); }
        App.api('/api/tty/session?name=' + encodeURIComponent(name)).then(d => {
            this.stopTimers();
            const prof = Object.assign(this._newProfile(d.name), d.profile, { name: d.name });
            const i = this.profiles.findIndex(p => p.name === prof.name);
            if (i >= 0) this.profiles[i] = prof; else this.profiles.push(prof);
            this.cur = prof.name; this.session = d.name; this.macRes = [];
            // output: lines back, raw bytes rebuilt for the hex view, JSON parsed again (fills the plot)
            this.series = {}; this.plotSel.clear(); this.jsonBuf = null; this.open = { rx: null, tx: null };
            const enc = new TextEncoder();
            this.lines = []; this.raw = [];
            for (const l of d.lines || []) {
                const line = this._push({ t: l.t, dir: l.dir, text: l.text, src: l.src });
                line.open = false;
                this.raw.push({ t: l.t, dir: l.dir, bytes: enc.encode(l.text + (l.dir === 'sys' ? '' : '\n')), src: l.src });
                if (l.dir === 'rx' && (prof.view || {}).json !== false) this._json(line);
            }
            prof.note = d.note || prof.note || '';
            this.render(); this.rerender(); this._renderSessions();
            this.$('tt-plot-btn').innerHTML = `<i class="fa-solid fa-chart-line"></i> Plot <span class="faint">(${Object.keys(this.series).length})</span>`;
            this.save();
            toast(`Session "${d.name}" opened`);
        }).catch(e => { toast(e.message, true); this._renderSessions(); });
    },

    deleteSession() {
        const name = this.$('tt-sess').value;
        if (!name) return toast('Choose a session in the list first', true);
        if (!confirm(`Delete session "${name}"?`)) return;
        App.api('/api/tty/session/delete', { json: { name } }).then(r => {
            if (this.session === name) this.session = '';
            this.sessions = r.sessions; this._renderSessions();
            toast('Session deleted');
        }).catch(e => toast(e.message, true));
    },

    // ── Plot ───────────────────────────────────────────────

    openPlot() {
        this.$('tt-plot-overlay').classList.add('open');
        this.renderPlotList(); this.drawCharts();
        clearInterval(this._plotT);
        this._plotT = setInterval(() => {
            if (!this.$('tt-plot-overlay').classList.contains('open')) return clearInterval(this._plotT);
            if (this._plotDirty) { this._plotDirty = false; this.renderPlotList(true); this.drawCharts(); }
        }, 500);
        if (!this._esc) { this._esc = true; App.onEscape(() => { if (this.$('tt-plot-overlay').classList.contains('open')) this.closePlot(); }); }
    },

    closePlot() { this.$('tt-plot-overlay').classList.remove('open'); clearInterval(this._plotT); },

    clearSeries() { this.series = {}; this.plotSel.clear(); this.renderPlotList(); this.drawCharts(); this.$('tt-plot-btn').innerHTML = '<i class="fa-solid fa-chart-line"></i> Plot'; },

    _fmtV(v) { return Math.abs(v) >= 1e5 || (v && Math.abs(v) < 1e-3) ? v.toExponential(3) : String(+v.toPrecision(6)); },

    renderPlotList(valuesOnly) {
        const el = this.$('tt-plot-list'), q = this.$('tt-plot-q').value.trim().toLowerCase();
        const keys = Object.keys(this.series).filter(k => !q || k.toLowerCase().includes(q)).sort();
        if (valuesOnly && el.childElementCount === keys.length) {
            el.querySelectorAll('[data-path]').forEach(r => { const s = this.series[r.dataset.path]; if (s) r.querySelector('.tt-pv').textContent = this._fmtV(s.last); });
            return;
        }
        el.innerHTML = keys.map(k => `<label class="tt-pl" data-path="${esc(k)}"><input type="checkbox"${this.plotSel.has(k) ? ' checked' : ''}>` +
            `<span class="mono">${esc(k)}</span><span class="tt-pv mono">${esc(this._fmtV(this.series[k].last))}</span></label>`).join('') ||
            '<div class="tbl-empty small">No numeric JSON fields received yet (enable “JSON”).</div>';
        el.onchange = e => {
            const r = e.target.closest('[data-path]');
            if (!r) return;
            e.target.checked ? this.plotSel.add(r.dataset.path) : this.plotSel.delete(r.dataset.path);
            this.drawCharts();
        };
    },

    drawCharts() {
        const box = this.$('tt-charts'), sel = [...this.plotSel].filter(k => this.series[k]);
        const have = [...box.children].map(c => c.dataset.path);
        if (have.join('\n') !== sel.join('\n')) {
            box.innerHTML = sel.map(k => `<div class="tt-chart" data-path="${esc(k)}"><div class="tt-chart-head"><span class="mono">${esc(k)}</span>` +
                `<span class="tt-chart-v mono"></span></div><canvas></canvas></div>`).join('') ||
                '<div class="tbl-empty">Tick fields on the left.</div>';
        }
        const win = +this.$('tt-plot-win').value * 1000, now = Date.now();
        box.querySelectorAll('.tt-chart').forEach(div => {
            const s = this.series[div.dataset.path];
            div.querySelector('.tt-chart-v').textContent = this._fmtV(s.last);
            this._chart(div.querySelector('canvas'), win ? s.pts.filter(p => p[0] >= now - win) : s.pts, win ? now - win : null, now);
        });
    },

    /** Minimal line chart: auto y range (min..max), time axis in seconds ago. */
    _chart(cv, pts, t0, t1) {
        const w = cv.parentElement.clientWidth, h = 130, dpr = window.devicePixelRatio || 1;
        cv.width = w * dpr; cv.height = h * dpr; cv.style.width = w + 'px'; cv.style.height = h + 'px';
        const ctx = cv.getContext('2d'), css = getComputedStyle(document.documentElement), col = n => css.getPropertyValue(n).trim();
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        ctx.clearRect(0, 0, w, h);
        ctx.font = '10px ' + col('--mono');
        if (!pts.length) { ctx.fillStyle = col('--text-mute'); ctx.fillText('no values in the window', 10, h / 2); return; }
        if (t0 == null) t0 = pts[0][0];
        if (t1 - t0 < 1000) t0 = t1 - 1000;
        let lo = Math.min(...pts.map(p => p[1])), hi = Math.max(...pts.map(p => p[1]));
        if (lo === hi) { lo -= Math.abs(lo) * 0.1 || 1; hi += Math.abs(hi) * 0.1 || 1; }
        const pad = (hi - lo) * 0.08; lo -= pad; hi += pad;
        const padL = Math.max(...[lo, hi].map(v => ctx.measureText(this._fmtV(v)).width)) + 10, padR = 8, padT = 6, padB = 16;
        const x = t => padL + (t - t0) / (t1 - t0) * (w - padL - padR), y = v => padT + (hi - v) / (hi - lo) * (h - padT - padB);
        ctx.strokeStyle = col('--border-soft'); ctx.lineWidth = 1;
        ctx.fillStyle = col('--text-mute'); ctx.textAlign = 'right'; ctx.textBaseline = 'middle';
        for (let k = 0; k <= 2; k++) {
            const v = lo + (hi - lo) * k / 2, yy = Math.round(y(v)) + .5;
            ctx.beginPath(); ctx.moveTo(padL, yy); ctx.lineTo(w - padR, yy); ctx.stroke();
            ctx.fillText(this._fmtV(+v.toPrecision(4)), padL - 4, yy);
        }
        ctx.textAlign = 'center'; ctx.textBaseline = 'alphabetic'; ctx.fillStyle = col('--text-faint');
        const span = (t1 - t0) / 1000;
        ctx.fillText(`-${span >= 120 ? Math.round(span / 60) + 'm' : Math.round(span) + 's'}`, padL + 12, h - 3);
        ctx.fillText('now', w - padR - 10, h - 3);
        ctx.strokeStyle = col('--accent'); ctx.lineWidth = 1.5;
        ctx.beginPath();
        pts.forEach((p, k) => { const xx = x(p[0]), yy = y(p[1]); k ? ctx.lineTo(xx, yy) : ctx.moveTo(xx, yy); });
        ctx.stroke();
        if (pts.length < 60) { ctx.fillStyle = col('--accent'); pts.forEach(p => { ctx.beginPath(); ctx.arc(x(p[0]), y(p[1]), 2, 0, 7); ctx.fill(); }); }
    },

    // ── Profiles ───────────────────────────────────────────

    connInput(transportChanged) {
        const c = this.prof().conn, f = this.$('tt-frame').value;
        Object.assign(c, { transport: this.$('tt-transport').value, port: this.$('tt-port').value, baud: this.$('tt-baud').value,
                           bytesize: f[0], parity: f[1], stopbits: f[2], host: this.$('tt-host').value.trim(),
                           netport: this.$('tt-netport').value, listen: this.$('tt-listen').value });
        if (transportChanged) {                              // the usual line ending of the transport
            this.prof().eol = this.DEFAULT_EOL[c.transport];
            this.$('tt-eol').value = this.prof().eol;
        }
        this._fields();
        this.save();
    },

    pickProfile(name) {
        if (this.sid) return toast('Close the connection first', true) || (this.$('tt-prof').value = this.cur);
        this.stopTimers();
        this.cur = name; this.render(); this.save();
    },

    profileCmd(cmd) {
        const p = this.prof();
        if (cmd === 'new' || cmd === 'dup') {
            if (this.sid) return toast('Close the connection first', true);
            const name = (prompt('Profile name:', this._uniqueName(cmd === 'dup' ? p.name + ' copy' : 'Device')) || '').trim();
            if (!name) return;
            if (this.profiles.some(x => x.name === name)) return toast('Name already used', true);
            const np = cmd === 'dup' ? JSON.parse(JSON.stringify(p)) : this._newProfile(name);
            np.name = name;
            if (cmd === 'new') np.conn = Object.assign({}, p.conn);          // same port / host by default
            this.profiles.push(np);
            return this.pickProfile(name);
        }
        if (cmd === 'export') {
            const a = document.createElement('a');
            a.href = URL.createObjectURL(new Blob([JSON.stringify(p, null, 2)], { type: 'application/json' }));
            a.download = `terminal_${p.name.replace(/[^\w.-]+/g, '_')}.json`;
            document.body.append(a); a.click();
            setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
            return;
        }
        if (cmd === 'rename') {
            const name = (prompt('New name:', p.name) || '').trim();
            if (!name || name === p.name) return;
            if (this.profiles.some(x => x.name === name)) return toast('Name already used', true);
            p.name = name; this.cur = name; this.render(); return this.save();
        }
        if (cmd === 'delete') {
            if (this.profiles.length < 2) return toast('The last profile cannot be deleted', true);
            if (!confirm(`Delete profile "${p.name}"?`)) return;
            this.profiles = this.profiles.filter(x => x !== p);
            return this.pickProfile(this.profiles[0].name);
        }
    },

    _uniqueName(base) {
        let n = base, k = 2;
        while (this.profiles.some(p => p.name === n)) n = `${base} ${k++}`;
        return n;
    },

    importFile(input) {
        const f = input.files[0];
        input.value = '';
        if (!f) return;
        if (this.sid) return toast('Close the connection first', true);
        f.text().then(t => {
            const p = JSON.parse(t);
            if (!p || typeof p.conn !== 'object' || (p.commands && !Array.isArray(p.commands))) throw new Error('not a terminal profile');
            p.commands = p.commands || [];
            p.name = this._uniqueName(String(p.name || 'Imported'));
            this.profiles.push(p);
            this.pickProfile(p.name);
            toast(`Imported "${p.name}"`);
        }).catch(e => toast('Import failed: ' + e.message, true));
    },

    save() {
        clearTimeout(this._saveT);
        this._saveT = setTimeout(() => {
            App.api('/api/tty/profiles', { json: { profiles: this.profiles, current: this.cur } })
                .catch(e => toast('Terminal profiles not saved: ' + e.message, true));
        }, 1200);
    },
});
