/* ==========================================================================
   Run / debug Python in the code editor (templates/editor.html; server: core/pyrun.py + core/pydbg_agent.py).
   - Buttons in the tab bar: Run, Debug/Continue, Pause, Step over/into/out, Run previous line again, Stop
     (F5, Ctrl+F5, F6, F10, F11, Shift+F11, F7, Shift+F5); F9 or a click left of the line numbers toggles a
     breakpoint; context menu "Set next line here" while paused (pdb "jump" — values are not undone).
   - The program runs in a pty: its output goes to the Terminal tab, lines typed there go to its stdin.
   - While paused: current line highlighted, Variables / Call stack / Evaluate in the side panel ("Debug" tab),
     hovering a name in the editor shows its value.
   One session at a time; it lives while this page polls it (closing the page stops it).
   ========================================================================== */

const PyDebug = {
    BP_KEY: 'editor-breakpoints',
    ARGS_KEY: 'editor-run-args',
    sid: null,
    seq: 0,
    st: null,                // last poll snapshot
    frame: null,             // selected stack frame index
    timer: 0,
    breaks: {},              // path -> Set(lines)
    decos: {},               // path -> {bp: ids[], cur: ids[]}
    expanded: new Set(),     // variable exprs opened in the tree
    _lastPaused: '',

    init() {
        this.ready = new Promise(res => { this._readyRes = res; });
        try { const b = JSON.parse(localStorage.getItem(this.BP_KEY) || '{}'); for (const p in b) this.breaks[p] = new Set(b[p]); } catch (e) {}
        document.addEventListener('keydown', e => this._keys(e), true);
        window.addEventListener('pagehide', () => {
            if (this.sid && this.st && this.st.state !== 'exited')
                navigator.sendBeacon('/api/pyrun/stop', new Blob([JSON.stringify({ id: this.sid })], { type: 'application/json' }));
        });
        const wait = setInterval(() => {      // Monaco loads asynchronously
            if (typeof editor === 'undefined' || !editor || typeof monaco === 'undefined') return;
            clearInterval(wait);
            this._monaco();
            this._readyRes();
        }, 100);
        this.poll();                          // reattach to a running session (page reload)
        this.renderBreaks();
        this.updateButtons();
    },

    // ── Monaco integration ──
    _monaco() {
        editor.updateOptions({ glyphMargin: true });
        editor.onMouseDown(e => {
            const t = e.target.type;
            if (t === monaco.editor.MouseTargetType.GUTTER_GLYPH_MARGIN || t === monaco.editor.MouseTargetType.GUTTER_LINE_DECORATIONS) {
                this.toggleBreak(e.target.position.lineNumber);
            }
        });
        editor.onDidChangeModel(() => { this.updateButtons(); this._decorate(currentPath); });
        monaco.languages.registerHoverProvider('python', { provideHover: (model, pos) => this._hover(model, pos) });
        this._pausedKey = editor.createContextKey('dbgPaused', false);
        editor.addAction({
            id: 'dbg-set-next-line', label: 'Debug: Set next line here (run from this line)',
            contextMenuGroupId: 'navigation', contextMenuOrder: 0, precondition: 'dbgPaused',
            run: ed => {
                const p = this.st && this.st.paused, f = p && p.stack[p.stack.length - 1];
                if (!f || f.file !== currentPath) return toast('Only lines of the paused function can be chosen', true);
                this.back(ed.getPosition().lineNumber);
            },
        });
        for (const [path, tab] of tabs) this.modelOpened(path, tab.model);
    },

    modelOpened(path, model) {
        model.onDidChangeContent(() => this._syncBreakLines(path));
        this._decorate(path);
        this.updateButtons();
    },

    _model(path) { const t = tabs.get(path); return t ? t.model : null; },

    _decorate(path) {
        const model = path && this._model(path);
        if (!model) return;
        const d = this.decos[path] || (this.decos[path] = { bp: [], cur: [] });
        const lines = [...(this.breaks[path] || [])];
        d.bp = model.deltaDecorations(d.bp, lines.map(l => ({
            range: new monaco.Range(l, 1, l, 1),
            options: { glyphMarginClassName: 'dbg-glyph-bp', glyphMarginHoverMessage: { value: 'Breakpoint (click to remove)' }, stickiness: 1 },
        })));
        const p = this.st && this.st.state === 'paused' && this.st.paused;
        const f = p && p.stack[this.frame != null ? this.frame : p.frame];
        const cur = f && f.file === path ? [{
            range: new monaco.Range(f.line, 1, f.line, 1),
            options: { isWholeLine: true, className: this.frame === p.frame || this.frame == null ? 'dbg-line-cur' : 'dbg-line-frame',
                       glyphMarginClassName: 'dbg-glyph-cur' },
        }] : [];
        d.cur = model.deltaDecorations(d.cur, cur);
    },

    /** Breakpoint decorations move with edits — read their lines back. */
    _syncBreakLines(path) {
        const model = this._model(path), d = this.decos[path];
        if (!model || !d || !d.bp.length) return;
        const lines = new Set(d.bp.map(id => model.getDecorationRange(id)).filter(Boolean).map(r => r.startLineNumber));
        const old = [...(this.breaks[path] || [])].sort().join();
        if ([...lines].sort().join() !== old) { this.breaks[path] = lines; this._saveBreaks(false); }
    },

    toggleBreak(line) {
        const path = currentPath;
        if (!path || !/\.py$/i.test(path)) return;
        line = line || editor.getPosition().lineNumber;
        const set = this.breaks[path] || (this.breaks[path] = new Set());
        if (set.has(line)) set.delete(line); else set.add(line);
        if (!set.size) delete this.breaks[path];
        this._decorate(path);
        this._saveBreaks(true);
    },

    clearBreaks() {
        const paths = Object.keys(this.breaks);
        this.breaks = {};
        paths.forEach(p => this._decorate(p));
        this._saveBreaks(true);
    },

    _breaksJson() {
        const out = {};
        for (const p in this.breaks) out[p] = [...this.breaks[p]].sort((a, b) => a - b);
        return out;
    },

    _saveBreaks(push) {
        try { localStorage.setItem(this.BP_KEY, JSON.stringify(this._breaksJson())); } catch (e) {}
        this.renderBreaks();
        if (push && this.active() && this.st.debug) App.api('/api/pyrun/breaks', { json: { breaks: this._breaksJson() } }).catch(() => {});
    },

    renderBreaks() {
        const el = document.getElementById('dbg-breaks'), b = this._breaksJson();
        const rows = Object.keys(b).flatMap(p => b[p].map(l => ({ p, l })));
        el.innerHTML = rows.length ? rows.map(r => `<div class="dbg-row" onclick='PyDebug.goto(${esc(JSON.stringify(r.p))}, ${r.l})'>
                <i class="fa-solid fa-circle dbg-bp-ico"></i><span class="dbg-fn">${esc(r.p.split('/').pop())}</span><span class="dbg-ln">${r.l}</span></div>`).join('')
            : '<div class="dbg-empty">none</div>';
    },

    _hover(model, pos) {
        if (!this.st || this.st.state !== 'paused') return null;
        const text = model.getLineContent(pos.lineNumber);
        const re = /[A-Za-z_][\w]*(?:\.[A-Za-z_]\w*|\[(?:\d+|'[^']*'|"[^"]*")\])*/g;
        let m, expr = null;
        while ((m = re.exec(text))) {
            if (m.index < pos.column && pos.column <= m.index + m[0].length + 1) {
                // cut after the part under the cursor: a.b.c with the cursor on b -> a.b
                const rest = m[0].slice(pos.column - 1 - m.index);
                const cut = rest.search(/[.\[]/);
                expr = cut > 0 ? m[0].slice(0, pos.column - 1 - m.index + cut) : m[0];
                break;
            }
        }
        if (!expr || /^(def|class|import|from|return|if|else|elif|for|while|in|and|or|not|is|None|True|False|with|as|try|except|finally|lambda|pass|break|continue|yield|global|nonlocal|assert|del|raise)$/.test(expr)) return null;
        return App.api('/api/pyrun/eval', { json: { id: this.sid, expr, frame: this._frameIdx(), hover: true } })
            .then(r => r.error ? null : {
                range: new monaco.Range(pos.lineNumber, m.index + 1, pos.lineNumber, m.index + 1 + expr.length),
                contents: [{ value: '`' + expr + '`: *' + r.type + (r.len != null ? `[${r.len}]` : '') + '*' },
                           { value: '```python\n' + r.value + '\n```' }],
            }).catch(() => null);
    },

    // ── session ──
    active() { return !!(this.st && this.sid && (this.st.state === 'running' || this.st.state === 'paused' || this.st.state === 'starting')); },
    wantsInput() { return this.active(); },

    _file() {
        if (!currentPath || !/\.py$/i.test(currentPath)) { toast('Open a .py file to run it', true); return null; }
        return currentPath;
    },

    _args() {
        const raw = document.getElementById('dbg-args').value.trim();
        const out = [];
        raw.replace(/"([^"]*)"|'([^']*)'|(\S+)/g, (_, a, b, c) => out.push(a ?? b ?? c));
        return out;
    },

    _rememberArgs(path) {
        try {
            const all = JSON.parse(localStorage.getItem(this.ARGS_KEY) || '{}');
            all[path] = document.getElementById('dbg-args').value.trim();
            localStorage.setItem(this.ARGS_KEY, JSON.stringify(all));
        } catch (e) {}
    },

    _loadArgs(path) {
        try { document.getElementById('dbg-args').value = (JSON.parse(localStorage.getItem(this.ARGS_KEY) || '{}')[path]) || ''; } catch (e) {}
    },

    run(debug) {
        if (this.active()) return toast('A program is already running — stop it first', true);
        const path = this._file();
        if (!path) return;
        const tab = tabs.get(path);
        const go = () => {
            this._rememberArgs(path);
            const args = this._args();
            App.api('/api/pyrun/start', { json: { path, args, debug, breaks: this._breaksJson(), stop_on_entry: document.getElementById('dbg-entry').checked } })
                .then(s => {
                    this.sid = s.id; this.seq = 0; this.frame = null; this.expanded.clear(); this._lastPaused = '';
                    switchTab('term');
                    setTimeout(() => {
                        if (!term) initXterm();
                        term.write(`\r\n\x1b[38;5;75m▶ ${debug ? 'debug' : 'run'}: python3 ${path.split('/').pop()}${args.length ? ' ' + args.join(' ') : ''}\x1b[0m\r\n`);
                        this._setPrompt();
                    }, 80);
                    if (debug) this.side('debug');
                    this._apply(s);
                    this._schedule(150);
                }).catch(e => toast(e.message, true));
        };
        if (tab && tab.dirty) saveFile().then(ok => { if (ok) go(); }); else go();
    },

    debugOrContinue() {
        if (this.st && this.st.state === 'paused') return this.cmd('continue');
        if (!this.active()) this.run(true);
    },

    cmd(action) {
        if (!this.active() || !this.st.debug) return;
        if (action !== 'pause' && this.st.state !== 'paused') return;
        App.api('/api/pyrun/cmd', { json: { id: this.sid, action } }).then(() => {
            if (action !== 'pause') { this.st.state = 'running'; this.st.paused = null; this.frame = null; this._renderPaused(); }
            this._schedule(60);
        }).catch(e => toast(e.message, true));
    },

    /** Move the execution point to the previous line (or `line`) of the paused frame; nothing is undone. */
    back(line) {
        if (!this.active() || !this.st.debug || this.st.state !== 'paused') return;
        App.api('/api/pyrun/cmd', { json: { id: this.sid, action: 'jump', line: line || null } })
            .then(r => { toast(`Next line: ${r.line} — Step over runs it`); this._lastPaused = ''; this._schedule(60); })
            .catch(e => toast(e.message, true));
    },

    stop() {
        if (!this.active()) return;
        App.api('/api/pyrun/stop', { json: { id: this.sid } }).then(() => this._schedule(100)).catch(e => toast(e.message, true));
    },

    input(text) {
        App.api('/api/pyrun/input', { json: { id: this.sid, text } }).then(() => this._schedule(60)).catch(e => toast(e.message, true));
    },

    _schedule(ms) {
        clearTimeout(this.timer);
        this.timer = setTimeout(() => this.poll(), ms);
    },

    poll() {
        const q = this.sid ? `?id=${this.sid}&since=${this.seq}` : '?since=0';
        App.api('/api/pyrun/poll' + q).then(s => {
            if (s.state === 'none') { this.st = null; this.updateButtons(); return; }
            if (this.sid !== s.id) {                   // a session started before this page was loaded
                if (s.state === 'exited') { this.updateButtons(); return; }
                this.sid = s.id; this.seq = 0;
                return this._schedule(10);
            }
            this._apply(s);
            if (s.state !== 'exited') this._schedule(s.state === 'paused' ? 700 : 250);
        }).catch(() => { if (this.active()) this._schedule(1500); });
    },

    _apply(s) {
        const prev = this.st ? this.st.state : null;
        if (s.output) {
            if (!term) initXterm();
            if (s.lost) term.write('\r\n\x1b[38;5;244m[… older output dropped …]\x1b[0m\r\n');
            term.write(s.output);
        }
        this.seq = s.seq;
        this.st = s;
        if (s.state === 'exited' && prev !== 'exited') {
            const ok = s.exit_code === 0;
            if (term) term.write(`\r\n\x1b[38;5;${ok ? 78 : 203}m■ exited with code ${s.exit_code}\x1b[0m\r\n`);
            this._setPrompt();
        }
        const key = s.paused ? `${s.paused.file}:${s.paused.line}:${s.paused.stack.length}:${s.paused.frame}` : '';
        if (s.state === 'paused' && key !== this._lastPaused) {
            this._lastPaused = key;
            this.frame = s.paused.frame;
            this._onPause(s.paused);
        } else if (s.state !== 'paused' && this._lastPaused) {
            this._lastPaused = '';
            this._renderPaused();
        }
        this._renderState();
        this.updateButtons();
        this._setPrompt();
    },

    _frameIdx() { return this.frame != null ? this.frame : (this.st && this.st.paused ? this.st.paused.frame : 0); },

    _onPause(p) {
        this.side('debug');
        const f = p.stack[this._frameIdx()];
        this._show(f.file, f.line);
        this._renderPaused();
    },

    _show(file, line) {
        if (!editor) { this.ready.then(() => this._show(file, line)); return; }
        const reveal = () => { editor.revealLineInCenterIfOutsideViewport(line); editor.setPosition({ lineNumber: line, column: 1 }); this._decorate(file); };
        if (tabs.has(file)) { if (currentPath !== file) activateTab(file); reveal(); return; }
        openFile(file, file.split('/').pop(), null).then(reveal).catch(() => toast('Cannot open ' + file + ' (outside target_dir?)', true));
    },

    goto(file, line) { this._show(file, line); },

    selectFrame(i) {
        this.frame = i;
        const f = this.st.paused.stack[i];
        this._show(f.file, f.line);
        Object.keys(this.decos).forEach(p => this._decorate(p));
        this._loadVars();
    },

    _renderPaused() {
        Object.keys(this.decos).forEach(p => this._decorate(p));
        const p = this.st && this.st.state === 'paused' ? this.st.paused : null;
        const stack = document.getElementById('dbg-stack'), exc = document.getElementById('dbg-exc');
        exc.hidden = !(p && p.exception);
        if (p && p.exception) exc.innerHTML = `<i class="fa-solid fa-circle-exclamation"></i> Uncaught ${esc(p.exception)} — inspect, then Continue / Stop`;
        if (!p) {
            stack.innerHTML = '<div class="dbg-empty">—</div>';
            document.getElementById('dbg-vars').innerHTML = `<div class="dbg-empty">${this.active() ? 'Running…' : 'Shown while paused'}</div>`;
            return;
        }
        const cur = this._frameIdx();
        stack.innerHTML = p.stack.map((f, i) => ({ f, i })).reverse().map(({ f, i }) =>
            `<div class="dbg-row${i === cur ? ' sel' : ''}" onclick="PyDebug.selectFrame(${i})" title="${esc(f.file)}:${f.line}">
                <span class="dbg-func">${esc(f.func)}</span><span class="dbg-fn">${esc(f.file.split('/').pop())}</span><span class="dbg-ln">${f.line}</span></div>`).join('');
        if (cur === p.frame) this._renderVars(document.getElementById('dbg-vars'), p.vars, 0);
        else this._loadVars();
    },

    _loadVars() {
        App.api('/api/pyrun/vars', { json: { id: this.sid, frame: this._frameIdx() } })
            .then(d => this._renderVars(document.getElementById('dbg-vars'), d.vars, 0))
            .catch(e => { document.getElementById('dbg-vars').innerHTML = `<div class="dbg-empty text-error">${esc(e.message)}</div>`; });
    },

    _renderVars(el, vars, depth) {
        if (!vars.length) { el.innerHTML = `<div class="dbg-empty">${depth ? 'empty' : 'no variables'}</div>`; return; }
        el.innerHTML = '';
        vars.forEach(v => {
            const row = document.createElement('div');
            row.className = 'dbg-var';
            row.style.paddingLeft = (6 + depth * 12) + 'px';
            const open = v.expr && this.expanded.has(v.expr);
            row.innerHTML = `<span class="dbg-caret">${v.more && v.expr ? `<i class="fa-solid fa-caret-${open ? 'down' : 'right'}"></i>` : ''}</span>
                <span class="dbg-vname">${esc(v.name)}</span><span class="dbg-vtype">${esc(v.type)}${v.len != null ? `[${v.len}]` : ''}</span>
                <span class="dbg-vval" title="${esc(v.value)}">${esc(v.value)}</span>`;
            const kids = document.createElement('div');
            if (v.more && v.expr) {
                row.classList.add('more');
                row.onclick = () => {
                    if (this.expanded.has(v.expr)) { this.expanded.delete(v.expr); kids.innerHTML = ''; row.querySelector('.dbg-caret').innerHTML = '<i class="fa-solid fa-caret-right"></i>'; return; }
                    this.expanded.add(v.expr);
                    row.querySelector('.dbg-caret').innerHTML = '<i class="fa-solid fa-caret-down"></i>';
                    this._children(v.expr, kids, depth + 1);
                };
                if (open) this._children(v.expr, kids, depth + 1);
            }
            el.appendChild(row);
            el.appendChild(kids);
        });
    },

    _children(expr, el, depth) {
        el.innerHTML = '<div class="dbg-empty">…</div>';
        App.api('/api/pyrun/vars', { json: { id: this.sid, expr, frame: this._frameIdx() } })
            .then(d => this._renderVars(el, d.vars, depth))
            .catch(e => { el.innerHTML = `<div class="dbg-empty text-error">${esc(e.message)}</div>`; });
    },

    evaluate() {
        const inp = document.getElementById('dbg-eval'), out = document.getElementById('dbg-eval-out');
        const expr = inp.value.trim();
        if (!expr) return;
        if (!this.st || this.st.state !== 'paused') { out.innerHTML = '<div class="dbg-empty">Pause the program first</div>'; return; }
        App.api('/api/pyrun/eval', { json: { id: this.sid, expr, frame: this._frameIdx() } })
            .then(r => this._renderVars(out, [r], 0))
            .catch(e => { out.innerHTML = `<div class="dbg-empty text-error">${esc(e.message)}</div>`; });
    },

    // ── UI state ──
    _renderState() {
        const el = document.getElementById('dbg-state'), s = this.st, dot = document.getElementById('dbg-dot');
        const name = s && s.path ? esc(s.path.split('/').pop()) : '';
        const map = {
            running: `<i class="fa-solid fa-circle-play text-ok"></i> Running ${name}`,
            starting: `<i class="fa-solid fa-spinner fa-spin"></i> Starting ${name}`,
            paused: `<i class="fa-solid fa-circle-pause text-warn"></i> Paused · ${s && s.paused ? esc(s.paused.func) + ':' + s.paused.line : ''}`,
            exited: `<i class="fa-regular fa-circle"></i> ${name} exited (${s ? s.exit_code : ''})`,
        };
        el.innerHTML = s ? map[s.state] || esc(s.state) : '<i class="fa-regular fa-circle"></i> Not running';
        dot.hidden = !this.active();
        dot.className = 'dbg-dot ' + (s ? s.state : '');
    },

    updateButtons() {
        const py = !!(currentPath && /\.py$/i.test(currentPath));
        const act = this.active(), paused = act && this.st.state === 'paused', dbg = act && this.st.debug;
        const set = (id, on) => { const b = document.getElementById(id); if (b) b.disabled = !on; };
        set('dbg-run', py && !act);
        set('dbg-debug', (py && !act) || paused);
        set('dbg-pause', dbg && this.st.state === 'running');
        ['dbg-next', 'dbg-step', 'dbg-return', 'dbg-back'].forEach(id => set(id, paused));
        if (this._pausedKey) this._pausedKey.set(!!paused);
        set('dbg-stop', act);
        const d = document.getElementById('dbg-debug');
        if (d) {
            d.title = paused ? 'Continue (F5)' : 'Debug (F5)';
            d.innerHTML = paused ? '<i class="fa-solid fa-forward"></i>' : '<i class="fa-solid fa-bug"></i>';
        }
        document.getElementById('dbg-bar').classList.toggle('live', act);
        if (!act && currentPath) this._loadArgs(currentPath);
    },

    _setPrompt() {
        const p = document.getElementById('term-prompt'), inp = document.getElementById('term-input');
        if (!p.dataset.shell) p.dataset.shell = p.textContent;
        const on = this.active();
        p.textContent = on ? `${this.st.path.split('/').pop()} stdin › ` : p.dataset.shell;
        p.classList.toggle('dbg-prompt', on);
        inp.placeholder = on ? 'input for the program (Enter sends a line, Ctrl+C interrupts)' : 'enter command…';
    },

    side(which) {
        if (typeof outlineVisible !== 'undefined' && !outlineVisible) toggleOutline(true);
        document.querySelectorAll('.side-tab').forEach(t => t.classList.toggle('active', t.dataset.side === which));
        document.getElementById('outline-list').hidden = which !== 'outline';
        document.getElementById('debug-side').hidden = which !== 'debug';
    },

    _keys(e) {
        if (!document.getElementById('dbg-bar')) return;
        const k = e.key;
        let fn = null;
        if (k === 'F5' && e.shiftKey) fn = () => this.stop();
        else if (k === 'F5' && (e.ctrlKey || e.metaKey)) fn = () => this.run(false);
        else if (k === 'F5') fn = () => this.debugOrContinue();
        else if (k === 'F6') fn = () => this.cmd('pause');
        else if (k === 'F7') fn = () => this.back();
        else if (k === 'F9') fn = () => this.toggleBreak();
        else if (k === 'F10') fn = () => this.cmd('next');
        else if (k === 'F11' && e.shiftKey) fn = () => this.cmd('return');
        else if (k === 'F11') fn = () => this.cmd('step');
        if (fn) { e.preventDefault(); e.stopPropagation(); fn(); }
    },
};

PyDebug.init();
