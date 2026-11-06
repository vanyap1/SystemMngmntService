/* ==========================================================================
   Floating documentation window of the code editor (templates/editor.html, button "?").
   Left: sections (folders) → documents → headings, with a search over titles, headings and paragraphs.
   Right: the document, compact (marked + DOMPurify + highlight.js, the same Markdown as the Docs page).
   Code examples: every line and every block can be inserted into the editor at the cursor or copied.
   Data: /api/help/tree, /api/help/doc (login only); window position / size / last document in localStorage.
   ========================================================================== */

const HelpFloat = {
    KEY: 'help.float',
    DEFAULT_DOC: 'testing/test-platform.md',
    docs: [],               // [{path, title}]
    texts: {},              // path -> markdown
    heads: {},              // path -> [{id, level, text}]
    open: {},               // nav: expanded folders / documents
    cur: null,              // current document path
    _loaded: null,

    el() { return document.getElementById('help-float'); },

    _state() { try { return JSON.parse(localStorage.getItem(this.KEY)) || {}; } catch (e) { return {}; } },
    _save(patch) { try { localStorage.setItem(this.KEY, JSON.stringify({ ...this._state(), ...patch })); } catch (e) { /* no storage */ } },

    toggle() { this.el().hidden ? this.show() : this.close(); },

    show(path, hash) {
        const win = this.el(), st = this._state();
        if (win.hidden) {
            const w = st.w || 860, h = st.h || Math.min(620, window.innerHeight - 120);
            win.style.width = w + 'px';
            win.style.height = h + 'px';
            win.style.left = (st.x != null ? st.x : Math.max(10, window.innerWidth - w - 330)) + 'px';
            win.style.top = (st.y != null ? st.y : 70) + 'px';
            win.hidden = false;
            this._clamp();
            this._save({ open: true });
        }
        this.load().then(() => {
            const want = path || this.cur || st.doc;
            const doc = this.docs.find(d => d.path === want) || this.docs.find(d => d.path === this.DEFAULT_DOC) || this.docs[0];
            if (doc) this.openDoc(doc.path, hash);
        });
        setTimeout(() => document.getElementById('hf-search').focus(), 50);
    },

    close() {
        this.el().hidden = true;
        this._save({ open: false });
    },

    /** Document list + all texts (the docs are small; this makes headings and search work everywhere). */
    load() {
        if (!this._loaded) {
            this._loaded = App.api('/api/help/tree').then(d => {
                this.docs = d.docs.map(x => ({ path: x.path, title: x.title || x.path }));
                return Promise.all(this.docs.map(doc => App.api('/api/help/doc?path=' + encodeURIComponent(doc.path))
                    .then(r => { this.texts[doc.path] = r.content || ''; this.heads[doc.path] = this._headings(r.content || ''); })
                    .catch(() => { this.texts[doc.path] = ''; this.heads[doc.path] = []; })));
            }).then(() => this.renderNav()).catch(e => {
                this._loaded = null;
                document.getElementById('hf-content').innerHTML = `<div class="hf-empty text-error">${esc(e.message)}</div>`;
            });
        }
        return this._loaded;
    },

    reload() {
        this._loaded = null;
        this.texts = {};
        this.load().then(() => this.cur && this.openDoc(this.cur));
    },

    _slug(text, used) {
        let s = text.toLowerCase().trim().replace(/[^\p{L}\p{N}\s_-]/gu, '').replace(/\s+/g, '-') || 'section';
        let id = s, n = 1;
        while (used.has(id)) id = `${s}-${++n}`;
        used.add(id);
        return id;
    },

    /** Headings of a Markdown text (outside code fences), with the same ids the renderer gives them. */
    _headings(md) {
        const out = [], used = new Set();
        let fence = false;
        for (const line of md.split('\n')) {
            if (/^\s*(```|~~~)/.test(line)) { fence = !fence; continue; }
            const m = !fence && line.match(/^(#{1,4})\s+(.+?)\s*#*\s*$/);
            if (m) {
                const text = m[2].replace(/[*_`]/g, '').replace(/\[([^\]]*)\]\([^)]*\)/g, '$1');
                out.push({ level: m[1].length, text, id: this._slug(text, used) });
            }
        }
        return out;
    },

    // ── navigation (left) ──
    renderNav() {
        const q = document.getElementById('hf-search').value.trim().toLowerCase();
        const nav = document.getElementById('hf-nav');
        if (q) return this._renderSearch(nav, q);
        const groups = {};
        this.docs.forEach(d => {
            const folder = d.path.includes('/') ? d.path.slice(0, d.path.lastIndexOf('/')) : '';
            (groups[folder] = groups[folder] || []).push(d);
        });
        const folders = Object.keys(groups).sort((a, b) => (a === '') - (b === '') || a.localeCompare(b));
        nav.innerHTML = folders.map(f => {
            const openF = f === '' || this._isOpen('f:' + f);
            const head = f ? `<div class="hf-folder" onclick='HelpFloat.toggleNav(${esc(JSON.stringify('f:' + f))})'>
                    <i class="fa-solid fa-caret-${openF ? 'down' : 'right'}"></i><i class="fa-solid fa-folder"></i> ${esc(f.replace(/[-_]/g, ' '))}</div>` : '';
            const docs = openF ? groups[f].sort((a, b) => a.title.localeCompare(b.title)).map(d => this._navDoc(d, f ? 1 : 0)).join('') : '';
            return head + docs;
        }).join('');
        const sel = nav.querySelector('.hf-doc.sel');
        if (sel && !this._navScrolled) { sel.scrollIntoView({ block: 'nearest' }); this._navScrolled = true; }
    },

    _navDoc(d, depth) {
        const isCur = d.path === this.cur;
        const openD = this._isOpen('d:' + d.path);
        const heads = (this.heads[d.path] || []).filter(h => h.level >= 2 && h.level <= 3);
        let html = `<div class="hf-doc${isCur ? ' sel' : ''}" style="padding-left:${8 + depth * 12}px" title="${esc(d.path)}">
            <span class="hf-caret" onclick='event.stopPropagation(); HelpFloat.toggleNav(${esc(JSON.stringify('d:' + d.path))})'>${heads.length ? `<i class="fa-solid fa-caret-${openD ? 'down' : 'right'}"></i>` : ''}</span>
            <span class="hf-doc-t" onclick='HelpFloat.openDoc(${esc(JSON.stringify(d.path))})'>${esc(d.title)}</span></div>`;
        if (openD) {
            html += heads.map(h => `<div class="hf-head l${h.level}" style="padding-left:${22 + depth * 12 + (h.level - 2) * 12}px" data-id="${esc(h.id)}"
                onclick='HelpFloat.openDoc(${esc(JSON.stringify(d.path))}, ${esc(JSON.stringify(h.id))})'>${esc(h.text)}</div>`).join('');
        }
        return html;
    },

    /** Expanded state: set by the user, otherwise open for the current document and its folder. */
    _isOpen(key) {
        if (this.open[key] !== undefined) return this.open[key];
        const p = key.slice(2);
        return key[0] === 'd' ? p === this.cur : !!(this.cur && this.cur.startsWith(p + '/'));
    },

    toggleNav(key) {
        this.open[key] = !this._isOpen(key);
        this.renderNav();
    },

    /** Search: documents, headings and paragraphs that contain the text. */
    _renderSearch(nav, q) {
        const hits = [];
        for (const d of this.docs) {
            const md = this.texts[d.path] || '';
            const heads = this.heads[d.path] || [];
            if (d.title.toLowerCase().includes(q)) hits.push({ d, kind: 'doc', text: d.title });
            heads.forEach(h => { if (h.text.toLowerCase().includes(q)) hits.push({ d, kind: 'head', text: h.text, id: h.id }); });
            let headIdx = -1, fence = false, n = 0;
            for (const line of md.split('\n')) {
                if (/^\s*(```|~~~)/.test(line)) fence = !fence;
                if (!fence && /^#{1,4}\s/.test(line)) { headIdx++; continue; }
                if (/^\s*!\[/.test(line)) continue;                          // image lines
                const plain = line.replace(/\[([^\]]*)\]\([^)]*\)/g, '$1').replace(/[`*]/g, '').replace(/^[\s>\-|#]+/, '').trim();
                if (plain.toLowerCase().includes(q) && n < 6) {
                    n++;
                    const h = heads[headIdx];
                    hits.push({ d, kind: 'text', text: plain, id: h ? h.id : null, find: q });
                }
            }
            if (hits.length > 200) break;
        }
        const mark = t => esc(t).replace(new RegExp(q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'ig'), m => `<mark>${m}</mark>`);
        nav.innerHTML = hits.length ? hits.map(h => `<div class="hf-hit ${h.kind}" onclick='HelpFloat.openDoc(${esc(JSON.stringify(h.d.path))}, ${esc(JSON.stringify(h.id || ''))}, ${esc(JSON.stringify(h.find || ''))})'>
                <i class="fa-solid ${h.kind === 'doc' ? 'fa-file-lines' : h.kind === 'head' ? 'fa-hashtag' : 'fa-align-left'}"></i>
                <span><span class="hf-hit-t">${mark(h.text.slice(0, 140))}</span>${h.kind !== 'doc' ? `<small>${esc(h.d.title)}</small>` : ''}</span></div>`).join('')
            : '<div class="hf-empty">Nothing found</div>';
    },

    // ── content (right) ──
    openDoc(path, hash, find) {
        const content = document.getElementById('hf-content');
        if (path !== this.cur) {
            this.cur = path;
            this._save({ doc: path });
            const doc = this.docs.find(d => d.path === path);
            document.getElementById('hf-title').textContent = doc ? doc.title : path;
            document.getElementById('hf-open-docs').href = '/help?doc=' + encodeURIComponent(path);
            this._render(this.texts[path] || '');
            content.scrollTop = 0;
            if (!document.getElementById('hf-search').value) this.renderNav();
        }
        if (hash) {
            const target = content.querySelector('#' + CSS.escape('hf-' + hash));
            if (target) {
                let el = target;
                if (find) {   // the paragraph with the found text after this heading
                    for (let n = target.nextElementSibling; n && !/^H[1-4]$/.test(n.tagName); n = n.nextElementSibling) {
                        if (n.textContent.toLowerCase().includes(find)) { el = n; break; }
                    }
                }
                content.scrollTop = el.offsetTop - 6;
                el.classList.add('hf-flash');
                setTimeout(() => el.classList.remove('hf-flash'), 1200);
            }
        } else if (find) {
            const el = [...content.querySelectorAll('p, li, td, pre, h1, h2, h3, h4')].find(n => n.textContent.toLowerCase().includes(find));
            if (el) { content.scrollTop = el.offsetTop - 6; el.classList.add('hf-flash'); setTimeout(() => el.classList.remove('hf-flash'), 1200); }
        }
    },

    _resolve(href) {
        if (!href || /^([a-z][a-z0-9+.-]*:|\/\/|\/|#)/i.test(href)) return null;
        const dir = this.cur && this.cur.includes('/') ? this.cur.slice(0, this.cur.lastIndexOf('/') + 1) : '';
        try {
            const u = new URL(href, location.origin + '/' + dir);
            return { path: decodeURIComponent(u.pathname.slice(1)), hash: decodeURIComponent(u.hash.slice(1)) };
        } catch (e) { return null; }
    },

    _fileUrl(rel) { return '/help/file/' + rel.split('/').map(encodeURIComponent).join('/'); },

    LANG_ALIAS: { service: 'ini', systemd: 'ini', conf: 'ini', cfg: 'ini', console: 'bash', sh: 'bash', py: 'python' },

    _render(md) {
        const tmp = document.createElement('div');
        tmp.innerHTML = DOMPurify.sanitize(marked.parse(md || ''));
        const used = new Set();
        tmp.querySelectorAll('h1, h2, h3, h4, h5, h6').forEach(h => { h.id = 'hf-' + this._slug(h.textContent, used); });
        tmp.querySelectorAll('img').forEach(img => {
            const r = this._resolve(img.getAttribute('src'));
            if (r) img.src = this._fileUrl(r.path);
            img.loading = 'lazy';
            img.title = 'Click to open full size';
            img.onclick = () => window.open(img.src, '_blank');
        });
        tmp.querySelectorAll('a[href]').forEach(a => {
            const href = a.getAttribute('href');
            if (/^https?:/i.test(href)) { a.target = '_blank'; a.rel = 'noopener noreferrer'; return; }
            if (href.startsWith('#')) { a.onclick = e => { e.preventDefault(); this.openDoc(this.cur, href.slice(1)); }; return; }
            const r = this._resolve(href);
            if (!r) return;
            if (/\.md$/i.test(r.path)) {
                a.href = '/help?doc=' + encodeURIComponent(r.path);
                a.onclick = e => { e.preventDefault(); this.openDoc(r.path, r.hash); };
            } else { a.href = this._fileUrl(r.path); a.target = '_blank'; }
        });
        tmp.querySelectorAll('blockquote').forEach(bq => {
            const p = bq.firstElementChild;
            const m = p && p.tagName === 'P' && p.innerHTML.match(/^\s*\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\s*(<br>)?/i);
            if (!m) return;
            p.innerHTML = p.innerHTML.slice(m[0].length);
            const kind = m[1].toLowerCase() === 'important' ? 'note' : m[1].toLowerCase();
            bq.classList.add('hf-alert', kind);
            bq.insertAdjacentHTML('afterbegin', `<div class="hf-alert-t">${esc(m[1].toLowerCase())}</div>`);
        });
        tmp.querySelectorAll('li > input[type=checkbox]').forEach(cb => cb.parentElement.classList.add('task'));
        tmp.querySelectorAll('pre > code').forEach(code => this._codeBlock(code));
        tmp.querySelectorAll(':not(pre) > code').forEach(c => { c.classList.add('hf-inline'); c.title = 'Click: copy'; });
        const content = document.getElementById('hf-content');
        content.replaceChildren(...tmp.childNodes);
    },

    /** A code block with per-line and per-block Insert / Copy buttons. */
    _codeBlock(code) {
        const pre = code.parentElement;
        const lang = ((code.className.match(/language-([\w+#-]+)/) || [])[1] || '').toLowerCase();
        const hl = this.LANG_ALIAS[lang] || lang;
        const text = code.textContent.replace(/\n$/, '');
        const ok = hl && typeof hljs !== 'undefined' && hljs.getLanguage(hl);
        const lines = text.split('\n');
        const wrap = document.createElement('div');
        wrap.className = 'hf-pre';
        wrap.dataset.code = text;
        wrap.innerHTML = `<div class="hf-pre-head"><span>${esc(lang || 'text')}</span><span class="spacer"></span>
                <button type="button" class="hf-act" data-act="insert-all" title="Insert the whole example into the editor at the cursor"><i class="fa-solid fa-arrow-right-to-bracket"></i> Insert</button>
                <button type="button" class="hf-act" data-act="copy-all" title="Copy the whole example"><i class="fa-regular fa-copy"></i> Copy</button></div>
            <pre class="hf-code hljs">${lines.map((l, i) => {
                let html = esc(l);
                if (ok) { try { html = hljs.highlight(l, { language: hl, ignoreIllegals: true }).value; } catch (e) { /* plain */ } }
                return `<div class="hf-line" data-i="${i}"><span class="hf-lt">${html || ' '}</span>${l.trim() ? `<span class="hf-line-acts">
                    <button type="button" class="hf-act" data-act="insert" title="Insert this line into the editor"><i class="fa-solid fa-arrow-right-to-bracket"></i></button>
                    <button type="button" class="hf-act" data-act="copy" title="Copy this line"><i class="fa-regular fa-copy"></i></button></span>` : ''}</div>`;
            }).join('')}</pre>`;
        pre.replaceWith(wrap);
    },

    _onClick(e) {
        const act = e.target.closest('.hf-act');
        if (act) {
            const block = act.closest('.hf-pre'), all = block.dataset.code;
            const line = act.closest('.hf-line');
            let text = line ? all.split('\n')[+line.dataset.i] : all;
            if (line && act.dataset.act === 'insert') text = this._withImports(text, all);
            if (act.dataset.act.startsWith('insert')) this.insert(text); else this.copy(text, act);
            return;
        }
        const inline = e.target.closest('code.hf-inline');
        if (inline) this.copy(inline.textContent, inline);
    },

    /** One line of an example + the example's import lines for the modules that line uses (re.fullmatch -> import re). */
    _withImports(line, block) {
        const need = block.split('\n').filter(l => {
            const m = l.match(/^import\s+([\w.]+)(?:\s+as\s+(\w+))?\s*$/) || l.match(/^from\s+[\w.]+\s+import\s+(\w+)(?:\s+as\s+(\w+))?\s*$/);
            if (!m || l === line) return false;
            const name = m[2] || m[1].split('.')[0];
            return new RegExp('\\b' + name + '\\b').test(line);
        });
        return need.length ? need.join('\n') + '\n' + line : line;
    },

    copy(text, el) {
        const done = () => {
            if (!el) return;
            el.classList.add('ok');
            setTimeout(() => el.classList.remove('ok'), 900);
        };
        if (navigator.clipboard && window.isSecureContext) {
            navigator.clipboard.writeText(text).then(done).catch(() => { this._copyFallback(text); done(); });
        } else { this._copyFallback(text); done(); }
        toast('Copied');
    },

    _copyFallback(text) {
        // navigator.clipboard needs https; the panel usually runs on plain http in a LAN
        const ta = document.createElement('textarea');
        ta.value = text;
        ta.style.cssText = 'position:fixed;left:-9999px;top:0';
        document.body.appendChild(ta);
        ta.select();
        try { document.execCommand('copy'); } catch (e) { toast('Copy failed', true); }
        ta.remove();
    },

    /**
     * Insert text at the editor cursor. On an empty line it goes there (indented like the line); inside a
     * non-empty line the snippet is put on a new line below with the same indentation.
     */
    insert(text) {
        if (typeof editor === 'undefined' || !editor || !currentPath) return toast('Open a file in the editor first', true);
        const model = editor.getModel();
        const isPy = /\.py$/i.test(currentPath);
        const IMPORT = /^(import\s+[\w.]+(\s+as\s+\w+)?(\s*,\s*[\w.]+(\s+as\s+\w+)?)*|from\s+[\w.]+\s+import\s+.+)\s*$/;
        let lines = text.split('\n');
        // Python: top-level "import x" lines of an example belong to the imports of the file, not to the cursor
        const imports = isPy ? lines.filter(l => IMPORT.test(l)) : [];
        if (imports.length) lines = lines.filter(l => !IMPORT.test(l));
        while (lines.length && !lines[0].trim()) lines.shift();
        const added = this._addImports(model, imports);
        const msg = [];
        if (added.length) msg.push('added ' + added.join(', '));
        if (lines.some(l => l.trim())) {
            this._insertAtCursor(model, lines);
            msg.unshift(lines.length > 1 ? `Inserted ${lines.length} lines` : 'Inserted');
        } else if (!added.length && imports.length) {
            msg.push('already imported');
        }
        editor.pushUndoStop();
        editor.focus();
        toast(msg.join(' · ') || 'Nothing to insert');
    },

    /** Add import lines the file does not have yet after its last top-level import (or the docstring). */
    _addImports(model, imports) {
        const have = new Set(model.getLinesContent().map(l => l.trim()));
        const todo = [...new Set(imports.map(l => l.trim()))].filter(l => !have.has(l));
        if (!todo.length) return [];
        const src = model.getLinesContent();
        let after = 0, inDoc = false;
        for (let i = 0; i < src.length; i++) {
            const l = src[i];
            if (i === 0 && /^\s*("""|\'\'\'|#!)/.test(l)) {
                inDoc = /^\s*("""|\'\'\')/.test(l) && !/^\s*(""".*"""|\'\'\'.*\'\'\')\s*$/.test(l);
                after = i + 1;
                continue;
            }
            if (inDoc) { if (/("""|\'\'\')/.test(l)) { inDoc = false; after = i + 1; } continue; }
            if (/^(import|from)\s+\S/.test(l)) after = i + 1;
            else if (l.trim() && !l.startsWith('#') && after && i > after + 1) break;
        }
        const line = after + 1;
        const range = new monaco.Range(line, 1, line, 1);
        editor.executeEdits('help', [{ range, text: todo.join('\n') + '\n', forceMoveMarkers: true }]);
        return todo.map(l => l.replace(/^import\s+|^from\s+(\S+).*$/, (m, mod) => mod || ''));
    },

    /**
     * Insert lines at the editor cursor. On an empty line they go there (indented like the line); inside a
     * non-empty line they are put on a new line below with the same indentation.
     */
    _insertAtCursor(model, lines) {
        const pos = editor.getPosition(), sel = editor.getSelection();
        const lineText = model.getLineContent(pos.lineNumber);
        const indent = (lineText.match(/^\s*/) || [''])[0];
        const common = Math.min(...lines.filter(l => l.trim()).map(l => l.match(/^\s*/)[0].length));
        const body = lines.map(l => l.slice(Math.min(common, l.match(/^\s*/)[0].length)));
        let range, out;
        if (!sel.isEmpty()) {
            range = sel;
            out = body.map((l, i) => (i ? indent : '') + l).join('\n');
        } else if (!lineText.trim()) {
            range = new monaco.Range(pos.lineNumber, 1, pos.lineNumber, lineText.length + 1);
            out = body.map(l => (l ? indent + l : l)).join('\n');
        } else {
            const end = lineText.length + 1;
            range = new monaco.Range(pos.lineNumber, end, pos.lineNumber, end);
            out = '\n' + body.map(l => (l ? indent + l : l)).join('\n');
        }
        editor.executeEdits('help', [{ range, text: out, forceMoveMarkers: true }]);
    },

    // ── window ──
    _clamp() {
        const win = this.el(), r = win.getBoundingClientRect();
        win.style.left = Math.min(Math.max(0, r.left), Math.max(0, window.innerWidth - 120)) + 'px';
        win.style.top = Math.min(Math.max(0, r.top), Math.max(0, window.innerHeight - 40)) + 'px';
    },

    init() {
        const win = this.el();
        if (!win) return;
        const head = win.querySelector('.mon-float-head');
        head.addEventListener('pointerdown', e => {
            if (e.button !== 0 || e.target.closest('button, input, select, a')) return;
            const r = win.getBoundingClientRect(), dx = e.clientX - r.left, dy = e.clientY - r.top;
            head.setPointerCapture(e.pointerId);
            win.classList.add('dragging');
            const move = ev => {
                win.style.left = Math.min(Math.max(0, ev.clientX - dx), window.innerWidth - 120) + 'px';
                win.style.top = Math.min(Math.max(0, ev.clientY - dy), window.innerHeight - 40) + 'px';
            };
            const up = () => {
                head.removeEventListener('pointermove', move);
                win.classList.remove('dragging');
                this._save({ x: parseInt(win.style.left), y: parseInt(win.style.top) });
            };
            head.addEventListener('pointermove', move);
            head.addEventListener('pointerup', up, { once: true });
            head.addEventListener('pointercancel', up, { once: true });
        });
        new ResizeObserver(() => { if (!win.hidden) this._save({ w: win.offsetWidth, h: win.offsetHeight }); }).observe(win);
        window.addEventListener('resize', () => { if (!win.hidden) this._clamp(); });
        document.getElementById('hf-content').addEventListener('click', e => this._onClick(e));
        const search = document.getElementById('hf-search');
        search.addEventListener('input', () => this.renderNav());
        search.addEventListener('keydown', e => { if (e.key === 'Escape') { search.value = ''; this.renderNav(); e.stopPropagation(); } });
        if (typeof marked !== 'undefined') marked.use({ gfm: true, breaks: false });
        if (this._state().open) this.show();
    },
};

HelpFloat.init();
