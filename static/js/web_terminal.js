/* ==========================================================================
   Interactive terminal of the code editor ("Terminal" tab): a login shell in a pty on the panel
   (core/terminal.py) shown with xterm.js — full-screen programs (mc, htop, nano, vim, less) work.
   Output: Server-Sent Events /api/term/stream (byte offsets, so a reconnect resumes without gaps);
   keys: POST /api/term/input (batched, in order); size: POST /api/term/resize.
   The session id is kept in sessionStorage: a page reload reattaches to the same shell (within 60 s).
   Copy: select with the mouse (Ctrl+Shift+C or Ctrl+C while text is selected); paste: Ctrl+Shift+V / Ctrl+V.
   ========================================================================== */

const WebTerm = {
    KEY: 'editor-shell-id',
    term: null,
    fit: null,
    id: null,
    offset: 0,
    es: null,
    _out: '',
    _sending: null,
    _resizeT: 0,
    _exited: false,
    _opening: null,

    show() {
        if (!this.term) this._create();
        setTimeout(() => { this.fitNow(); this.term.focus(); }, 30);
        if (!this.id && !this._opening) this.open();
    },

    _create() {
        this.fit = new FitAddon.FitAddon();
        this.term = new Terminal({
            theme: {
                background: '#111111', foreground: '#d4d4d4', cursor: '#4ec9b0', cursorAccent: '#111111',
                selectionBackground: 'rgba(78,201,176,.30)',
                black: '#1e1e1e', red: '#f44747', green: '#6dbf85', yellow: '#d4a95a',
                blue: '#569cd6', magenta: '#c586c0', cyan: '#4ec9b0', white: '#d4d4d4',
                brightBlack: '#808080', brightRed: '#f44747', brightGreen: '#6dbf85', brightYellow: '#e5c07b',
                brightBlue: '#7ec8f5', brightMagenta: '#c586c0', brightCyan: '#4ec9b0', brightWhite: '#ffffff',
            },
            fontSize: 13,
            fontFamily: "'Cascadia Code','Fira Mono',Consolas,'DejaVu Sans Mono',monospace",
            lineHeight: 1.15,
            scrollback: 5000,
            cursorBlink: true,
            allowProposedApi: true,
            macOptionIsMeta: true,
        });
        this.term.loadAddon(this.fit);
        this.term.open(document.getElementById('shell-container'));
        this.term.onData(d => this.send(d));
        this.term.onBinary(d => this.send(d));
        this.term.onResize(({ cols, rows }) => this._resize(cols, rows));
        this.term.attachCustomKeyEventHandler(e => this._key(e));
        window.addEventListener('resize', () => this.fitNow());
        window.addEventListener('pagehide', () => {
            // a reload reattaches (sessionStorage); closing the tab lets the server drop the shell after 60 s
            if (this.es) this.es.close();
        });
    },

    /** Copy / paste shortcuts; everything else goes to the shell (F-keys, Ctrl+key, Alt+key). */
    _key(e) {
        if (e.type !== 'keydown') return true;
        const sel = this.term.hasSelection();
        if (e.ctrlKey && (e.key === 'C' || e.key === 'c') && (e.shiftKey || sel)) {
            if (sel) { this._copy(this.term.getSelection()); this.term.clearSelection(); }
            e.preventDefault();
            return false;
        }
        if (e.ctrlKey && e.shiftKey && (e.key === 'V' || e.key === 'v')) {
            if (navigator.clipboard && window.isSecureContext) {
                navigator.clipboard.readText().then(t => this.term.paste(t)).catch(() => {});
                e.preventDefault();
                return false;
            }
            return true;               // plain http: the browser's paste event (Ctrl+V) still works
        }
        if (e.ctrlKey && !e.shiftKey && (e.key === 'v' || e.key === 'V')) return true;   // native paste
        return true;
    },

    _copy(text) {
        if (navigator.clipboard && window.isSecureContext) { navigator.clipboard.writeText(text).catch(() => {}); return; }
        const ta = document.createElement('textarea');
        ta.value = text;
        ta.style.cssText = 'position:fixed;left:-9999px';
        document.body.appendChild(ta);
        ta.select();
        try { document.execCommand('copy'); } catch (e) { /* ignore */ }
        ta.remove();
        this.term.focus();
    },

    fitNow() {
        if (!this.term || !document.getElementById('term-pane').classList.contains('active')) return;
        try { this.fit.fit(); } catch (e) { /* hidden */ }
    },

    open(fresh) {
        if (!this.term) this._create();
        this.fitNow();
        let prev = null;
        try { prev = fresh ? null : sessionStorage.getItem(this.KEY); } catch (e) { /* no storage */ }
        this._exited = false;
        this._opening = App.api('/api/term/open', { json: { cols: this.term.cols, rows: this.term.rows, id: prev } }).then(s => {
            this.id = s.id;
            try { sessionStorage.setItem(this.KEY, s.id); } catch (e) { /* no storage */ }
            document.getElementById('term-user').textContent = s.user;
            document.getElementById('term-new').hidden = false;
            this.term.reset();
            this.offset = s.reattached ? s.start : 0;      // reattach: replay what the server still has
            this._stream();
        }).catch(e => {
            this.term.write(`\r\n\x1b[31mCannot open a shell: ${e.message}\x1b[0m\r\n`);
        }).finally(() => { this._opening = null; });
        return this._opening;
    },

    _stream() {
        if (this.es) this.es.close();
        const es = new EventSource(`/api/term/stream?id=${encodeURIComponent(this.id)}&from=${this.offset}`);
        this.es = es;
        es.addEventListener('out', e => {
            const m = JSON.parse(e.data);
            this.offset = m.o;
            this.term.write(m.d);
        });
        es.addEventListener('exit', e => {
            es.close();
            this.es = null;
            const code = JSON.parse(e.data).code;
            this._exited = true;
            this.id = null;
            try { sessionStorage.removeItem(this.KEY); } catch (err) { /* no storage */ }
            this.term.write(`\r\n\x1b[38;5;244m[shell exited${code ? ' with code ' + code : ''} — press Enter for a new one]\x1b[0m\r\n`);
        });
        es.onerror = () => {
            // EventSource would reconnect with the original ?from= — reconnect by hand from the current offset
            es.close();
            if (this.es !== es || this._exited) return;
            this.es = null;
            setTimeout(() => {
                if (this.id && !this.es) App.api('/api/term/open', { json: { cols: this.term.cols, rows: this.term.rows, id: this.id } })
                    .then(s => { if (s.id === this.id) this._stream(); else { this.id = s.id; this.offset = 0; this.term.reset(); this._stream(); } })
                    .catch(() => { this.term.write('\r\n\x1b[31m[connection lost — retrying]\x1b[0m'); this.es = null; setTimeout(() => es.onerror(), 3000); });
            }, 1000);
        };
    },

    /** Keys typed in the terminal (or a macro): batched into one POST, posts kept in order. */
    send(data) {
        if (this._exited) {
            if (data === '\r') this.restart();
            return;
        }
        if (!this.id) { if (!this._opening) this.open(); return; }
        this._out += data;
        if (this._sending) return;
        const flush = () => {
            if (!this._out || !this.id) { this._sending = null; return; }
            const chunk = this._out;
            this._out = '';
            this._sending = App.api('/api/term/input', { json: { id: this.id, data: chunk } })
                .catch(e => { if (/No such terminal/.test(e.message)) { this.id = null; this.term.write('\r\n\x1b[31m[session gone — press Enter]\x1b[0m'); this._exited = true; } })
                .then(flush);
        };
        this._sending = Promise.resolve().then(flush);
    },

    _resize(cols, rows) {
        clearTimeout(this._resizeT);
        this._resizeT = setTimeout(() => {
            if (this.id) App.api('/api/term/resize', { json: { id: this.id, cols, rows } }).catch(() => {});
        }, 120);
    },

    /** Run a command line in the shell (macros). */
    run(cmd) {
        switchTab('term');
        const go = () => this.send(cmd.replace(/\n/g, '\r') + '\r');
        if (this.id) go(); else (this._opening || this.open()).then(() => setTimeout(go, 300));
    },

    restart() {
        if (this.id) App.api('/api/term/close', { json: { id: this.id } }).catch(() => {});
        if (this.es) { this.es.close(); this.es = null; }
        this.id = null;
        try { sessionStorage.removeItem(this.KEY); } catch (e) { /* no storage */ }
        this.term.reset();
        this.open(true);
        this.term.focus();
    },

    clear() { if (this.term) this.term.clear(); },
};
