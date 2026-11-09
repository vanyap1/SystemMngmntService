/* ==========================================================================
   Documentation viewer / editor (templates/help.html, routes/help.py).
   Markdown is rendered with marked + DOMPurify (+ highlight.js for code); the editor is Monaco,
   loaded on first use. Links to img/ and docs/ are relative to the page, as in any Markdown viewer.
   ========================================================================== */

const Help = {
    docs: [],
    current: null,          // {path, content, title, mtime}
    editing: false,
    dirty: false,
    mode: 'split',          // edit | split | preview
    editor: null,
    _monaco: null,
    _renderTimer: null,
    _searchTimer: null,
    _query: '',
    as: { kind: 'img', insert: false, items: [] },
    _docModal: null,        // {mode: 'new'|'rename', nameTouched}

    LANG_ALIAS: { service: 'ini', systemd: 'ini', conf: 'ini', cfg: 'ini', rules: 'plaintext', txt: 'plaintext',
                  text: 'plaintext', cmd: 'dos', bat: 'dos', ps: 'powershell', ps1: 'powershell', console: 'bash' },
    FILE_ICONS: [[/\.(zip|7z|gz|tgz|xz|bz2|rar|tar)$/i, 'fa-file-zipper'], [/\.pdf$/i, 'fa-file-pdf'],
                 [/\.(png|jpe?g|gif|webp|svg|bmp)$/i, 'fa-file-image'], [/\.(xlsx?|csv|ods)$/i, 'fa-file-excel'],
                 [/\.(docx?|odt|rtf)$/i, 'fa-file-word'], [/\.(py|sh|js|c|h|cpp|json|ya?ml|ini|service|rules|bat|ps1|sql)$/i, 'fa-file-code'],
                 [/\.(txt|log|md)$/i, 'fa-file-lines'], [/\.(exe|msi|deb|bin|hex|img)$/i, 'fa-gear']],

    // ── Start ──────────────────────────────────────────────────

    init() {
        marked.use({ gfm: true, breaks: false });
        this.mode = this._load('help.mode', 'split');
        this.closedFolders = new Set(JSON.parse(this._load('help.closed', '[]')));
        if (this._mobile()) document.getElementById('hp-app').classList.add('side-hidden');

        const q = document.getElementById('hp-q');
        q.addEventListener('input', () => {
            clearTimeout(this._searchTimer);
            this._searchTimer = setTimeout(() => this.search(q.value), 220);
        });
        q.addEventListener('keydown', e => {
            if (e.key === 'Escape') { this.clearSearch(); q.blur(); }
            if (e.key === 'Enter') { const first = document.querySelector('.hp-result'); if (first) first.click(); }
        });

        document.getElementById('hp-tree').addEventListener('click', e => this._treeClick(e));
        document.getElementById('hp-article').addEventListener('click', e => this._articleClick(e));
        document.getElementById('hp-view').addEventListener('scroll', () => this._onViewScroll(), { passive: true });
        document.getElementById('hp-toc').addEventListener('click', e => {
            const a = e.target.closest('a[data-id]');
            if (!a) return;
            e.preventDefault();
            this.scrollToId(a.dataset.id, true);
        });
        ['hp-f-title', 'hp-f-folder', 'hp-f-name'].forEach(id =>
            document.getElementById(id).addEventListener('input', e => this._docModalInput(e)));
        document.getElementById('hp-as-q').addEventListener('input', () => this.renderAssets());
        this._dropZone(document.getElementById('hp-as-body'), files => this.uploadFiles(files, this.as.kind === 'img' ? 'img' : 'docs', true));

        document.addEventListener('keydown', e => this._keys(e));
        window.addEventListener('beforeunload', e => { if (this.dirty) { e.preventDefault(); e.returnValue = ''; } });
        window.addEventListener('popstate', () => this._fromUrl(false));
        App.onEscape(() => {
            if (document.getElementById('hp-lightbox').classList.contains('open')) return this.closeLightbox();
            if (document.getElementById('hp-as-overlay').classList.contains('open')) return this.closeAssets();
            if (document.getElementById('hp-doc-overlay').classList.contains('open')) return this.closeDocModal();
        });

        this.loadTree().then(() => this._fromUrl(true));
    },

    _load(key, def) { try { return localStorage.getItem(key) ?? def; } catch (e) { return def; } },
    _store(key, val) { try { localStorage.setItem(key, val); } catch (e) { /* private mode */ } },
    _mobile() { return window.matchMedia('(max-width: 800px)').matches; },

    _keys(e) {
        const inField = e.target.closest('input, textarea, select, .monaco-editor');
        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's' && this.editing) { e.preventDefault(); this.save(); return; }
        if (inField || e.ctrlKey || e.metaKey || e.altKey || document.querySelector('.modal-overlay.open') || Diagrams.isOpen()) return;
        if (e.key === '/') { e.preventDefault(); document.getElementById('hp-q').focus(); }
        else if (e.key === 'e' && this.current && !this.editing) { e.preventDefault(); this.edit(); }
    },

    // ── Tree / search ──────────────────────────────────────────

    loadTree() {
        return App.api('/api/help/tree').then(d => {
            this.docs = d.docs;
            this.reserved = d.reserved;
            this.root = d.root;
            if (this._query) this.search(this._query); else this.renderTree();
        }).catch(e => toast(e.message, true));
    },

    _hasDoc(path) { return this.docs.some(d => d.path === path); },

    renderTree() {
        const el = document.getElementById('hp-tree');
        if (!this.docs.length) {
            el.innerHTML = '<div class="tbl-empty">No documents yet.</div>';
            return;
        }
        const root = { folders: {}, docs: [] };
        for (const d of this.docs) {
            const parts = d.path.split('/');
            let node = root, prefix = '';
            for (const p of parts.slice(0, -1)) {
                prefix += (prefix ? '/' : '') + p;
                node = node.folders[p] = node.folders[p] || { folders: {}, docs: [], path: prefix };
            }
            node.docs.push(d);
        }
        const count = n => n.docs.length + Object.values(n.folders).reduce((s, f) => s + count(f), 0);
        const first = d => /^(index|readme)\.md$/i.test(d.path.split('/').pop()) ? 0 : 1;
        const renderNode = node => {
            const docs = node.docs.slice().sort((a, b) => first(a) - first(b) || a.title.localeCompare(b.title));
            let html = docs.map(d =>
                `<div class="hp-doc${this.current && this.current.path === d.path ? ' active' : ''}" data-path="${esc(d.path)}" title="${esc(d.path)}">` +
                `<i class="fa-regular fa-file-lines"></i><span>${esc(d.title)}</span></div>`).join('');
            for (const name of Object.keys(node.folders).sort((a, b) => a.localeCompare(b))) {
                const f = node.folders[name];
                html += `<div class="hp-folder${this.closedFolders.has(f.path) ? ' closed' : ''}">` +
                        `<div class="hp-folder-head" data-folder="${esc(f.path)}"><i class="fa-solid fa-chevron-down"></i>` +
                        `<i class="fa-regular fa-folder"></i> ${esc(name)}<span class="hp-count">${count(f)}</span></div>` +
                        `<div class="hp-folder-items">${renderNode(f)}</div></div>`;
            }
            return html;
        };
        el.innerHTML = renderNode(root) + this._diagramGroup();
    },

    _diagramGroup() {
        const list = Diagrams.list || [], R = DiagramRender;
        const folder = (key, icon, label, inner, count, newTpl, title) =>
            `<div class="hp-folder${key === '__diagrams' ? ' hp-dg-group' : ''}${this.closedFolders.has(key) ? ' closed' : ''}">` +
            `<div class="hp-folder-head" data-folder="${esc(key)}"${title ? ` title="${esc(title)}"` : ''}><i class="fa-solid fa-chevron-down"></i>` +
            `<i class="fa-solid ${icon}"></i> ${esc(label)}<span class="hp-count">${count}</span>` +
            (newTpl ? `<button class="btn-icon hp-dg-new" data-new-diagram="${esc(newTpl)}" title="New in ${esc(label)}"><i class="fa-solid fa-plus"></i></button>` : '') +
            `</div><div class="hp-folder-items">${inner}</div></div>`;
        const item = d => {
            const cat = d.component ? R.category(d.component.category) : null;
            const icon = cat ? Diagrams._catIcon(d.component.category, 16)
                : `<i class="fa-solid ${R.CATALOGS[d.catalog] ? R.CATALOGS[d.catalog].icon : 'fa-diagram-project'}"></i>`;
            return `<div class="hp-doc${Diagrams.name === d.name ? ' active' : ''}" data-diagram="${esc(d.name)}" title="diagrams/${esc(d.name)}.json` +
                (cat ? ` · ${esc(cat.label)}, ${d.component.ports} port(s)` : '') + '">' + icon + `<span>${esc(d.title)}</span>` +
                `<button class="btn-icon hp-dg-clone" data-clone-diagram="${esc(d.name)}" title="Clone into this group under a new name"><i class="fa-regular fa-clone"></i></button></div>`;
        };
        const empty = (tpl, text) => `<div class="hp-doc hp-dg-empty" data-new-diagram="${esc(tpl)}"><i class="fa-solid fa-plus"></i><span>${esc(text)}</span></div>`;
        const NEW = { station: 'station', assembly: 'comp:jig', bus: 'bus:prog', component: 'comp:custom', uut: 'comp:dut', diagram: 'block' };
        const EMPTY = { station: 'New test station', assembly: 'New jig', bus: 'New bus-level module', component: 'New component',
                        uut: 'New UUT (DUT symbol)', diagram: 'New pinout / block diagram' };
        let inner = '';
        for (const [key, c] of Object.entries(R.CATALOGS)) {
            const items = list.filter(d => (R.CATALOGS[d.catalog] ? d.catalog : 'diagram') === key);
            let body = items.length ? items.map(item).join('') : empty(NEW[key], EMPTY[key]);
            if ((key === 'component' || key === 'bus') && items.length) {
                const tpl = key === 'bus' ? 'bus:' : 'comp:';
                body = Object.entries(R.COMPONENT_GROUPS).map(([g, gr]) => {
                    const l = items.filter(d => R.componentGroup(d.component ? d.component.category : 'custom') === g)
                        .sort((a, b) => gr.cats.indexOf(a.component.category) - gr.cats.indexOf(b.component.category) || a.title.localeCompare(b.title));
                    return l.length ? folder(`__dg_${key}_${g}`, gr.icon, gr.label, l.map(item).join(''), l.length, tpl + gr.cats[0],
                                             gr.cats.map(k => R.category(k).label).join(', ')) : '';
                }).join('');
            }
            inner += folder(`__dg_${key}`, c.icon, c.label, body, items.length, NEW[key], c.hint);
        }
        return folder('__diagrams', 'fa-diagram-project', 'Diagrams', inner, list.length, ' ');
    },

    _treeClick(e) {
        const cl = e.target.closest('[data-clone-diagram]');
        if (cl) { e.stopPropagation(); return Diagrams.duplicate(cl.dataset.cloneDiagram); }
        const nd = e.target.closest('[data-new-diagram]');
        if (nd) { e.stopPropagation(); return Diagrams.openNew(nd.dataset.newDiagram.trim() || undefined); }
        const dg = e.target.closest('[data-diagram]');
        if (dg) {
            this.openDiagram(dg.dataset.diagram);
            if (this._mobile()) document.getElementById('hp-app').classList.add('side-hidden');
            return;
        }
        const head = e.target.closest('[data-folder]');
        if (head) {
            const p = head.dataset.folder;
            head.parentElement.classList.toggle('closed');
            this.closedFolders.has(p) ? this.closedFolders.delete(p) : this.closedFolders.add(p);
            this._store('help.closed', JSON.stringify([...this.closedFolders]));
            return;
        }
        const item = e.target.closest('[data-path]');
        if (item) {
            this.open(item.dataset.path, '', item.dataset.q || '');
            if (this._mobile()) document.getElementById('hp-app').classList.add('side-hidden');
        }
    },

    search(q) {
        this._query = q.trim();
        document.getElementById('hp-q-clear').hidden = !this._query;
        if (!this._query) return this.renderTree();
        App.api('/api/help/search?q=' + encodeURIComponent(this._query)).then(d => {
            if (this._query !== q.trim()) return;
            const words = this._words(this._query);
            const el = document.getElementById('hp-tree');
            el.innerHTML = `<div class="hp-results-head">${d.results.length} document(s)</div>` +
                (d.results.map(r =>
                    `<div class="hp-result" data-path="${esc(r.path)}" data-q="${esc(this._query)}">` +
                    `<b>${this._mark(r.title, words)}</b><span class="hp-rpath">${esc(r.path)}</span>` +
                    r.hits.map(h => `<div class="hp-hit"><em>${h.line}</em>${this._mark(h.text, words)}</div>`).join('') +
                    '</div>').join('') || '<div class="tbl-empty">Nothing found.</div>');
        }).catch(e => toast(e.message, true));
    },

    clearSearch() {
        document.getElementById('hp-q').value = '';
        this.search('');
    },

    _words(q) { return q.toLowerCase().split(/\s+/).filter(Boolean); },
    _reEsc(s) { return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); },

    /** Escape text and wrap the search words in <mark>. */
    _mark(text, words) {
        if (!words.length) return esc(text);
        const re = new RegExp('(' + words.map(this._reEsc).join('|') + ')', 'gi');
        return String(text).split(re).map((part, i) => i % 2 ? `<mark>${esc(part)}</mark>` : esc(part)).join('');
    },

    toggleSide() { document.getElementById('hp-app').classList.toggle('side-hidden'); },

    // ── Open / view ────────────────────────────────────────────

    _fromUrl(initial) {
        const p = new URLSearchParams(location.search);
        if (p.get('diagram')) { Diagrams.open(p.get('diagram'), false); return; }
        if (Diagrams.isOpen() && !Diagrams.close(false)) return;
        let doc = p.get('doc');
        if (!doc && initial) {
            const start = this.docs.find(d => /^(index|readme)\.md$/i.test(d.path)) || this.docs[0];
            if (start) doc = start.path;
        }
        if (doc) this.open(doc, decodeURIComponent(location.hash.slice(1)), '', false);
        else this.showEmpty();
    },

    _confirmLeave() {
        return !this.dirty || confirm('Discard unsaved changes?');
    },

    /** Close the diagram editor / leave the Markdown editor; false if the user wants to stay. */
    _leaveEditors() {
        if (Diagrams.isOpen() && !Diagrams.close(false)) return false;
        if (this.editing && !this._confirmLeave()) return false;
        return true;
    },

    openDiagram(name) {
        if (this.editing && !this._confirmLeave()) return;
        this._closeEditor();
        if (this.current) this._bar();
        Diagrams.open(name);
    },

    open(path, hash = '', q = '', push = true) {
        if (!this._leaveEditors()) return;
        return App.api('/api/help/doc?path=' + encodeURIComponent(path)).then(doc => {
            this._closeEditor();
            this.current = doc;
            if (push) {
                const url = '/help?doc=' + encodeURIComponent(doc.path) + (hash ? '#' + encodeURIComponent(hash) : '');
                history.pushState(null, '', url);
            }
            this.showView();
            if (q) this._highlight(this._words(q));
            if (hash) this.scrollToId(hash, false);
            else document.getElementById('hp-view').scrollTop = 0;
            document.querySelectorAll('.hp-doc').forEach(el => el.classList.toggle('active', el.dataset.path === doc.path));
        }).catch(e => {
            toast(e.message, true);
            if (!this.current) this.showEmpty();
        });
    },

    showEmpty() {
        this.current = null;
        this._bar();
        document.getElementById('hp-toc').hidden = true;
        document.getElementById('hp-article').innerHTML =
            `<div class="hp-empty"><i class="fa-solid fa-book-open"></i>` +
            (this.docs.length ? 'Select a document on the left.' : 'There are no documents yet.') +
            `<br><button class="btn btn-success" style="margin-top:14px" onclick="Help.openNew()"><i class="fa-solid fa-plus"></i> New document</button></div>`;
    },

    showView() {
        this._bar();
        this.renderPreview(this.current.content);
        document.title = this.current.title + ' — ' + document.title.split(' — ').slice(-1)[0];
    },

    _bar() {
        const doc = this.current;
        const crumbs = document.getElementById('hp-crumbs');
        if (!doc) {
            crumbs.innerHTML = '<b>Documentation</b>';
            document.getElementById('hp-meta').textContent = '';
        } else {
            const parts = doc.path.split('/');
            crumbs.innerHTML = parts.slice(0, -1).map(p => `<span>${esc(p)}</span><i class="fa-solid fa-chevron-right"></i>`).join('') +
                `<b title="${esc(doc.path)}">${esc(doc.title)}</b>`;
            document.getElementById('hp-meta').textContent =
                'edited ' + App.fmtDate(doc.mtime) + ' · ' + App.fmtBytes(new Blob([doc.content]).size);
            document.getElementById('hp-download').href = this.fileUrl(doc.path) + '?dl=1';
        }
        document.getElementById('hp-view-actions').hidden = !doc || this.editing;
        document.getElementById('hp-edit-actions').hidden = !this.editing;
        document.getElementById('hp-toolbar').hidden = !this.editing;
        document.getElementById('hp-dirty').hidden = !this.dirty;
        const body = document.getElementById('hp-body');
        body.className = this.editing ? 'mode-' + this.mode : '';
        document.getElementById('hp-editor').hidden = !this.editing;
        document.querySelectorAll('#hp-modes button').forEach(b => b.classList.toggle('active', b.dataset.mode === this.mode));
    },

    fileUrl(rel) { return '/help/file/' + rel.split('/').map(encodeURIComponent).join('/'); },

    /** Resolve a relative link of the current page to a help_dir path; null for absolute/external links. */
    _resolve(href) {
        if (!href || /^([a-z][a-z0-9+.-]*:|\/\/|\/|#)/i.test(href)) return null;
        const path = this.current ? this.current.path : '';
        const dir = path.includes('/') ? path.slice(0, path.lastIndexOf('/') + 1) : '';
        try {
            const u = new URL(href, location.origin + '/' + dir);
            return { path: decodeURIComponent(u.pathname.slice(1)), hash: decodeURIComponent(u.hash.slice(1)) };
        } catch (e) { return null; }
    },

    _slug(text, used) {
        let s = text.toLowerCase().trim().replace(/[^\p{L}\p{N}\s_-]/gu, '').replace(/\s+/g, '-') || 'section';
        let id = s, n = 1;
        while (used.has(id)) id = `${s}-${++n}`;
        used.add(id);
        return id;
    },

    /** Markdown -> sanitized DOM inside #hp-article (+ TOC when viewing). */
    renderPreview(md) {
        const article = document.getElementById('hp-article');
        const tmp = document.createElement('div');
        tmp.innerHTML = DOMPurify.sanitize(marked.parse(md || ''), { ADD_ATTR: ['target'] });

        const used = new Set(), toc = [];
        tmp.querySelectorAll('h1, h2, h3, h4, h5, h6').forEach(h => {
            h.id = this._slug(h.textContent, used);
            const a = document.createElement('a');
            a.className = 'hp-anchor'; a.href = '#' + h.id; a.textContent = '#';
            h.prepend(a);
            if (/^H[234]$/.test(h.tagName)) toc.push({ id: h.id, level: +h.tagName[1], text: h.textContent.slice(1) });
        });

        tmp.querySelectorAll('img').forEach(img => {
            const r = this._resolve(img.getAttribute('src'));
            if (r) img.src = this.fileUrl(r.path);
            img.loading = 'lazy';
            const dm = r && r.path.match(/^diagrams\/(.+)\.svg$/);
            if (dm && !img.closest('a')) {
                if (this._bust[dm[1]]) img.src += '?v=' + this._bust[dm[1]];
                const wrap = document.createElement('span');
                wrap.className = 'hp-dgwrap';
                img.replaceWith(wrap);
                wrap.append(img);
                const b = document.createElement('button');
                b.type = 'button'; b.className = 'hp-dg-edit'; b.dataset.editDiagram = dm[1];
                b.innerHTML = '<i class="fa-solid fa-pen-ruler"></i> Edit diagram';
                wrap.append(b);
            }
        });

        tmp.querySelectorAll('a[href]').forEach(a => {
            const href = a.getAttribute('href');
            if (a.classList.contains('hp-anchor')) return;
            if (/^https?:/i.test(href)) { a.target = '_blank'; a.rel = 'noopener noreferrer'; return; }
            const r = this._resolve(href);
            if (!r) return;
            if (/\.md$/i.test(r.path)) {
                a.dataset.doc = r.path;
                a.dataset.hash = r.hash;
                a.href = '/help?doc=' + encodeURIComponent(r.path) + (r.hash ? '#' + encodeURIComponent(r.hash) : '');
                if (!this._hasDoc(r.path)) { a.classList.add('hp-missing'); a.title = 'Document not found: ' + r.path; }
                return;
            }
            a.href = this.fileUrl(r.path);
            a.target = '_blank';
            if (/^docs\//.test(r.path) && !a.querySelector('img')) {
                const name = r.path.split('/').pop();
                const icon = (this.FILE_ICONS.find(([re]) => re.test(name)) || [0, 'fa-file'])[1];
                a.classList.add('hp-file');
                a.title = 'Open / download ' + name;
                a.innerHTML = `<i class="fa-solid ${icon}"></i> ${esc(a.textContent)}` +
                              (a.textContent.trim() !== name ? ` <small>${esc(name)}</small>` : '');
            }
        });

        tmp.querySelectorAll('li > input[type=checkbox]').forEach(cb => cb.parentElement.classList.add('task'));

        tmp.querySelectorAll('blockquote').forEach(bq => {
            const p = bq.firstElementChild;
            const m = p && p.tagName === 'P' && p.innerHTML.match(/^\s*\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\s*(<br>)?/i);
            if (!m) return;
            const kind = m[1].toLowerCase();
            p.innerHTML = p.innerHTML.slice(m[0].length);
            if (!p.innerHTML.trim()) p.remove();
            bq.classList.add('hp-alert', kind === 'important' ? 'note' : kind);
            const t = document.createElement('div');
            t.className = 'hp-alert-title';
            t.textContent = m[1].toLowerCase();
            bq.prepend(t);
        });

        tmp.querySelectorAll('pre > code').forEach(code => {
            const pre = code.parentElement;
            let lang = ((code.className.match(/language-([\w+#-]+)/) || [])[1] || '').toLowerCase();
            const hl = this.LANG_ALIAS[lang] || lang;
            if (hl && hljs.getLanguage(hl)) {
                code.className = 'language-' + hl;
                try { hljs.highlightElement(code); } catch (e) { /* plain text */ }
            }
            const wrap = document.createElement('div');
            wrap.className = 'hp-pre';
            pre.replaceWith(wrap);
            wrap.append(pre);
            const tools = document.createElement('div');
            tools.className = 'hp-pre-tools';
            tools.innerHTML = (lang ? `<span>${esc(lang)}</span>` : '') +
                '<button class="hp-copy" type="button" title="Copy"><i class="fa-regular fa-copy"></i></button>';
            wrap.append(tools);
        });

        article.replaceChildren(...tmp.childNodes);
        this._renderToc(this.editing ? [] : toc);
    },

    _renderToc(items) {
        const el = document.getElementById('hp-toc');
        el.hidden = items.length < 2;
        el.innerHTML = '<div class="hp-toc-title">On this page</div>' + items.map(i =>
            `<a href="#${esc(i.id)}" data-id="${esc(i.id)}" class="l${i.level}" title="${esc(i.text)}">${esc(i.text)}</a>`).join('');
        this._onViewScroll();
    },

    _onViewScroll() {
        const view = document.getElementById('hp-view');
        const links = [...document.querySelectorAll('#hp-toc a')];
        if (!links.length) return;
        const top = view.getBoundingClientRect().top + 40;
        let active = links[0];
        for (const a of links) {
            const h = document.getElementById(a.dataset.id);
            if (h && h.getBoundingClientRect().top <= top) active = a;
        }
        links.forEach(a => a.classList.toggle('active', a === active));
    },

    scrollToId(id, smooth) {
        const el = id && document.getElementById(id);
        if (el) el.scrollIntoView({ behavior: smooth ? 'smooth' : 'auto', block: 'start' });
        if (smooth && this.current && !this.editing) {
            history.replaceState(null, '', '/help?doc=' + encodeURIComponent(this.current.path) + '#' + encodeURIComponent(id));
        }
    },

    _highlight(words) {
        if (!words.length) return;
        const src = words.map(this._reEsc).join('|');
        const re = new RegExp(src, 'gi'), probe = new RegExp(src, 'i');
        const article = document.getElementById('hp-article');
        const walker = document.createTreeWalker(article, NodeFilter.SHOW_TEXT);
        const nodes = [];
        while (walker.nextNode()) if (probe.test(walker.currentNode.nodeValue)) nodes.push(walker.currentNode);
        nodes.forEach(node => {
            const frag = document.createDocumentFragment();
            let last = 0;
            node.nodeValue.replace(re, (m, i) => {
                frag.append(node.nodeValue.slice(last, i));
                const mark = document.createElement('mark');
                mark.className = 'hp-find'; mark.textContent = m;
                frag.append(mark);
                last = i + m.length;
            });
            frag.append(node.nodeValue.slice(last));
            node.replaceWith(frag);
        });
        const first = article.querySelector('mark.hp-find');
        if (first) setTimeout(() => first.scrollIntoView({ block: 'center' }), 50);
    },

    _bust: {},

    /** A diagram was saved: reload its image in pages shown from now on. */
    bustDiagram(name) { this._bust[name] = Date.now(); },

    _articleClick(e) {
        const ed = e.target.closest('[data-edit-diagram]');
        if (ed) return this.openDiagram(ed.dataset.editDiagram);
        const copy = e.target.closest('.hp-copy');
        if (copy) {
            const code = copy.closest('.hp-pre').querySelector('code');
            this.copyText(code.textContent.replace(/\n$/, ''));
            copy.classList.add('ok');
            copy.innerHTML = '<i class="fa-solid fa-check"></i>';
            setTimeout(() => { copy.classList.remove('ok'); copy.innerHTML = '<i class="fa-regular fa-copy"></i>'; }, 1200);
            return;
        }
        const img = e.target.closest('img');
        if (img && !img.closest('a')) return this.openLightbox(img.src);
        const a = e.target.closest('a');
        if (!a) return;
        if (a.dataset.doc) {
            e.preventDefault();
            if (a.classList.contains('hp-missing') && this.editing) return toast('Document not found: ' + a.dataset.doc, true);
            this.open(a.dataset.doc, a.dataset.hash || '');
        } else if ((a.getAttribute('href') || '').startsWith('#')) {
            e.preventDefault();
            this.scrollToId(decodeURIComponent(a.getAttribute('href').slice(1)), true);
        }
    },

    copyText(text) {
        // navigator.clipboard needs a secure context (https); the panel is usually plain http on a LAN.
        if (navigator.clipboard && window.isSecureContext) {
            navigator.clipboard.writeText(text).catch(() => this._copyFallback(text));
        } else this._copyFallback(text);
    },

    _copyFallback(text) {
        const ta = document.createElement('textarea');
        ta.value = text;
        ta.style.cssText = 'position:fixed;top:-1000px;opacity:0';
        document.body.append(ta);
        ta.select();
        try { document.execCommand('copy'); } catch (e) { toast('Copy failed', true); }
        ta.remove();
    },

    openLightbox(src) {
        document.getElementById('hp-lightbox-img').src = src;
        document.getElementById('hp-lightbox').classList.add('open');
    },
    closeLightbox() { document.getElementById('hp-lightbox').classList.remove('open'); },

    // ── Editor ─────────────────────────────────────────────────

    _loadMonaco() {
        if (this._monaco) return this._monaco;
        this._monaco = new Promise((resolve, reject) => {
            const VS = '/static/vendor/monaco/vs';
            const s = document.createElement('script');
            s.src = VS + '/loader.js';
            s.onload = () => {
                require.config({ paths: { vs: VS } });
                require(['vs/editor/editor.main'], resolve, reject);
            };
            s.onerror = () => reject(new Error('Cannot load the editor'));
            document.head.append(s);
        });
        return this._monaco;
    },

    _createEditor() {
        const el = document.getElementById('hp-editor');
        el.hidden = false;
        this.editor = monaco.editor.create(el, {
            language: 'markdown', theme: 'vs-dark', automaticLayout: true, wordWrap: 'on',
            minimap: { enabled: false }, fontSize: 13, lineNumbers: 'on', scrollBeyondLastLine: false,
            renderWhitespace: 'selection', quickSuggestions: false, wordBasedSuggestions: false,
            unicodeHighlight: { ambiguousCharacters: false, invisibleCharacters: false },
            padding: { top: 10 }, tabSize: 4, insertSpaces: true,
        });
        const K = monaco.KeyMod.CtrlCmd, C = monaco.KeyCode;
        this.editor.addCommand(K | C.KeyS, () => this.save());
        this.editor.addCommand(K | C.KeyB, () => this.fmt('bold'));
        this.editor.addCommand(K | C.KeyI, () => this.fmt('italic'));
        this.editor.addCommand(K | C.KeyK, () => this.fmt('link'));
        this.editor.onDidChangeModelContent(() => {
            if (!this.dirty) { this.dirty = true; document.getElementById('hp-dirty').hidden = false; }
            clearTimeout(this._renderTimer);
            this._renderTimer = setTimeout(() => this.mode !== 'edit' && this.renderPreview(this.editor.getValue()), 200);
        });
        this.editor.onDidScrollChange(e => {
            if (this.mode !== 'split' || !e.scrollTopChanged) return;
            const max = e.scrollHeight - this.editor.getLayoutInfo().height;
            const view = document.getElementById('hp-view');
            view.scrollTop = max > 0 ? (e.scrollTop / max) * (view.scrollHeight - view.clientHeight) : 0;
        });
        // Pasted / dropped files are uploaded (images -> img/, the rest -> docs/) and linked at the cursor.
        el.addEventListener('paste', e => {
            const files = [...(e.clipboardData && e.clipboardData.files || [])];
            if (!files.length) return;
            e.preventDefault(); e.stopPropagation();
            this.uploadFiles(files, null);
        }, true);
        this._dropZone(el, (files, ev) => {
            const t = this.editor.getTargetAtClientPoint(ev.clientX, ev.clientY);
            if (t && t.position) this.editor.setPosition(t.position);
            this.uploadFiles(files, null);
        });
    },

    _dropZone(el, onFiles) {
        const has = e => [...(e.dataTransfer && e.dataTransfer.types || [])].includes('Files');
        el.addEventListener('dragover', e => { if (has(e)) { e.preventDefault(); e.stopPropagation(); el.classList.add('drop'); } }, true);
        el.addEventListener('dragleave', e => { if (!el.contains(e.relatedTarget)) el.classList.remove('drop'); }, true);
        el.addEventListener('drop', e => {
            el.classList.remove('drop');
            if (!has(e)) return;
            e.preventDefault(); e.stopPropagation();
            onFiles([...e.dataTransfer.files], e);
        }, true);
    },

    edit() {
        if (!this.current) return;
        this._loadMonaco().then(() => {
            if (!this.editor) this._createEditor();
            this.editor.setValue(this.current.content);
            this.editing = true;
            this.dirty = false;
            this._bar();
            this.renderPreview(this.current.content);
            this.editor.setScrollTop(0);
            this.editor.focus();
        }).catch(e => toast(e.message, true));
    },

    setMode(mode) {
        this.mode = mode;
        this._store('help.mode', mode);
        this._bar();
        if (mode !== 'edit') this.renderPreview(this.editor.getValue());
        if (mode !== 'preview') this.editor.focus();
    },

    cancel() {
        if (!this._confirmLeave()) return;
        this._closeEditor();
        this.showView();
    },

    _closeEditor() {
        this.editing = false;
        this.dirty = false;
    },

    save(force = false) {
        if (!this.editing || !this.current) return;
        const content = this.editor.getValue();
        App.api('/api/help/doc', { json: { path: this.current.path, content, mtime: this.current.mtime, force } })
            .then(r => {
                Object.assign(this.current, { content, mtime: r.mtime, title: r.title });
                this.dirty = false;
                this._bar();
                toast('Saved');
                this.loadTree();
            })
            .catch(e => {
                if (/changed by someone/i.test(e.message)) {
                    if (confirm('The document was changed on disk after you opened it.\nOverwrite it with your version?')) this.save(true);
                } else toast(e.message, true);
            });
    },

    // ── Formatting ─────────────────────────────────────────────

    _insert(text, selectFrom, selectLen) {
        const ed = this.editor, sel = ed.getSelection();
        ed.executeEdits('help', [{ range: sel, text, forceMoveMarkers: true }]);
        if (selectFrom != null) {
            const start = ed.getModel().getOffsetAt(sel.getStartPosition()) + selectFrom;
            const a = ed.getModel().getPositionAt(start), b = ed.getModel().getPositionAt(start + selectLen);
            ed.setSelection(new monaco.Selection(a.lineNumber, a.column, b.lineNumber, b.column));
        }
        ed.focus();
    },

    _wrap(left, right, placeholder) {
        const sel = this.editor.getSelection();
        const text = this.editor.getModel().getValueInRange(sel);
        if (text.startsWith(left) && text.endsWith(right) && text.length >= left.length + right.length) {
            return this._insert(text.slice(left.length, text.length - right.length));
        }
        const inner = text || placeholder;
        this._insert(left + inner + right, left.length, inner.length);
    },

    _linePrefix(prefix, strip) {
        const ed = this.editor, model = ed.getModel(), sel = ed.getSelection();
        const edits = [];
        let n = 1;
        for (let ln = sel.startLineNumber; ln <= sel.endLineNumber; ln++) {
            const line = model.getLineContent(ln);
            if (!line.trim() && sel.startLineNumber !== sel.endLineNumber) continue;
            const p = typeof prefix === 'function' ? prefix(n++) : prefix;
            const bare = line.replace(strip, '');
            const text = line.startsWith(p) ? line.slice(p.length) : p + bare;
            edits.push({ range: new monaco.Range(ln, 1, ln, line.length + 1), text });
        }
        ed.executeEdits('help', edits);
        ed.focus();
    },

    _block(text, selectFrom, selectLen) {
        const ed = this.editor, sel = ed.getSelection(), model = ed.getModel();
        const before = sel.startColumn > 1 ? '\n\n' : (sel.startLineNumber > 1 && model.getLineContent(sel.startLineNumber - 1).trim() ? '\n' : '');
        this._insert(before + text + '\n', selectFrom == null ? null : before.length + selectFrom, selectLen);
    },

    fmt(kind) {
        if (!this.editor || !this.editing) return;
        const sel = this.editor.getModel().getValueInRange(this.editor.getSelection());
        const heading = /^#{1,6}\s+/, list = /^(\s*)([-*+]\s+(\[[ x]\]\s+)?|\d+\.\s+)/;
        switch (kind) {
            case 'bold':   return this._wrap('**', '**', 'bold text');
            case 'italic': return this._wrap('*', '*', 'italic text');
            case 'strike': return this._wrap('~~', '~~', 'text');
            case 'code':   return this._wrap('`', '`', 'code');
            case 'h1': return this._linePrefix('# ', heading);
            case 'h2': return this._linePrefix('## ', heading);
            case 'h3': return this._linePrefix('### ', heading);
            case 'ul':   return this._linePrefix('- ', list);
            case 'ol':   return this._linePrefix(n => n + '. ', list);
            case 'task': return this._linePrefix('- [ ] ', list);
            case 'quote': return this._linePrefix('> ', /^>\s?/);
            case 'note': {
                const body = sel || 'Text of the note';
                return this._block('> [!NOTE]\n> ' + body.split('\n').join('\n> '), 12, body.length);
            }
            case 'codeblock': {
                const body = sel || 'command';
                return this._block('```bash\n' + body + '\n```', 3, 4);
            }
            case 'table':
                return this._block('| Column | Description |\n|---|---|\n| value | text |\n| value | text |', 2, 6);
            case 'hr': return this._block('---');
            case 'link': {
                const text = sel || 'link text';
                return this._insert(`[${text}](https://)`, text.length + 3, 8);
            }
            case 'doclink': return this.openAssets('pages', true);
        }
    },

    /** Relative link from the current page to a help_dir path, wrapped in <> when it has spaces. */
    relLink(to) {
        const from = this.current.path.split('/').slice(0, -1), parts = to.split('/');
        let i = 0;
        while (i < from.length && i < parts.length - 1 && from[i] === parts[i]) i++;
        const rel = '../'.repeat(from.length - i) + parts.slice(i).join('/');
        return /[\s()<>]/.test(rel) ? `<${rel}>` : rel;
    },

    _assetMd(kind, name) {
        const link = this.relLink(kind + '/' + name);
        const stem = name.replace(/\.[^.]+$/, '').replace(/[-_]+/g, ' ');
        return kind === 'img' ? `![${stem}](${link})` : `[${name}](${link})`;
    },

    // ── Uploads / assets ───────────────────────────────────────

    /** Upload files; kind null = by type (images -> img, others -> docs). Inserts links when editing. */
    async uploadFiles(files, kind, fromModal = false) {
        if (!files.length) return;
        const groups = {};
        for (const f of files) {
            const k = kind || (/^image\//.test(f.type) ? 'img' : 'docs');
            (groups[k] = groups[k] || []).push(f);
        }
        const inserted = [];
        for (const [k, list] of Object.entries(groups)) {
            const fd = new FormData();
            fd.append('kind', k);
            list.forEach((f, i) => {
                let name = f.name;
                if (!name || name === 'image.png') name = `pasted-${new Date().toISOString().replace(/\D/g, '').slice(0, 14)}${i || ''}.${(f.type.split('/')[1] || 'png').replace('jpeg', 'jpg')}`;
                fd.append('file', f, name);
            });
            try {
                const r = await fetch('/api/help/upload', { method: 'POST', body: fd });
                if (r.status === 401) return App.requireLogin();
                const d = await r.json().catch(() => ({ error: 'HTTP ' + r.status }));
                if (!r.ok) throw new Error(d.error || 'Upload failed');
                d.names.forEach(n => inserted.push([k, n]));
            } catch (e) { toast(e.message, true); }
        }
        if (!inserted.length) return;
        toast(`Uploaded: ${inserted.map(i => i[1]).join(', ')}`);
        const insertNow = this.editing && (!fromModal || this.as.insert);
        if (insertNow) {
            if (fromModal) this.closeAssets();
            this._insert(inserted.map(([k, n]) => this._assetMd(k, n)).join(inserted.some(i => i[0] === 'img') ? '\n\n' : '\n'));
        } else if (fromModal) this.loadAssets();
    },

    uploadPicked(input) {
        const files = [...input.files];
        input.value = '';
        this.uploadFiles(files, this.as.kind === 'img' ? 'img' : 'docs', true);
    },

    openAssets(kind, insert = false) {
        this.as.kind = kind;
        this.as.insert = insert && this.editing;
        document.querySelectorAll('#hp-as-kinds button').forEach(b => b.classList.toggle('active', b.dataset.kind === kind));
        const special = kind === 'pages' || kind === 'diagrams';
        document.getElementById('hp-as-dir').textContent = kind === 'pages' ? '' : (this.root || '') + '/' + kind;
        document.getElementById('hp-as-file').accept = kind === 'img' ? 'image/*' : '';
        document.getElementById('hp-as-file').closest('label').hidden = special;
        document.getElementById('hp-as-hint').textContent = kind === 'pages' ? 'Click a document to insert a link to it'
            : kind === 'diagrams' ? 'Insert embeds the exported SVG; it is updated every time the diagram is saved. New diagrams: “+” next to Diagrams in the sidebar.'
            : (this.as.insert ? 'Click “Insert” to add it at the cursor. ' : '') + 'Drop files here to upload. Deleted files go to .trash/';
        document.getElementById('hp-as-overlay').classList.add('open');
        this.loadAssets();
    },

    closeAssets() {
        document.getElementById('hp-as-overlay').classList.remove('open');
        if (this.editing) this.editor.focus();
    },

    loadAssets() {
        const body = document.getElementById('hp-as-body');
        if (this.as.kind === 'pages') { this.as.items = this.docs; return this.renderAssets(); }
        if (this.as.kind === 'diagrams') {
            return Diagrams.loadList().then(() => { this.as.items = Diagrams.list; this.renderAssets(); });
        }
        body.innerHTML = '<div class="tbl-empty">Loading…</div>';
        App.api('/api/help/assets?kind=' + this.as.kind)
            .then(d => { this.as.items = d.items; this.renderAssets(); })
            .catch(e => { body.innerHTML = `<div class="tbl-empty text-error">${esc(e.message)}</div>`; });
    },

    renderAssets() {
        const body = document.getElementById('hp-as-body');
        const f = document.getElementById('hp-as-q').value.trim().toLowerCase();
        const kind = this.as.kind;
        const items = this.as.items.filter(i => !f || (i.name || i.path + ' ' + i.title).toLowerCase().includes(f));
        if (!items.length) {
            body.innerHTML = `<div class="tbl-empty">${this.as.items.length ? 'Nothing matches the filter.' : 'Empty — upload files with the button above or drop them here.'}</div>`;
            return;
        }
        const used = i => i.used_by.length
            ? `<span title="${esc(i.used_by.join('\n'))}">used in ${i.used_by.length}</span>`
            : '<span class="hp-as-unused">not used</span>';
        const btns = i => {
            const n = esc(JSON.stringify(i.name));
            return (this.as.insert ? `<button class="btn btn-primary btn-sm" onclick="Help.insertAsset(${n})">Insert</button>` : '') +
                `<button class="btn btn-ghost btn-sm" onclick="Help.copyAsset(${n})" title="Copy Markdown"><i class="fa-regular fa-copy"></i></button>` +
                `<a class="btn btn-ghost btn-sm" href="${esc(this.fileUrl(kind + '/' + i.name))}" target="_blank" title="Open"><i class="fa-solid fa-up-right-from-square"></i></a>` +
                `<button class="btn btn-danger btn-sm" onclick="Help.deleteAsset(${n})" title="Delete"><i class="fa-regular fa-trash-can"></i></button>`;
        };
        if (kind === 'diagrams') {
            body.innerHTML = '<div class="hp-as-grid">' + items.map(d => {
                const n = esc(JSON.stringify(d.name));
                return `<div class="hp-as-card"><div class="hp-as-thumb" onclick="Help.openLightbox(this.querySelector('img').src)">` +
                    `<img src="${esc(this.fileUrl('diagrams/' + d.name + '.svg'))}?v=${d.mtime}" loading="lazy" alt=""></div>` +
                    `<div class="hp-as-info"><div class="hp-as-name" title="${esc(d.name)}">${esc(d.title)}</div>` +
                    `<div class="hp-as-sub mono">${esc(d.name)}</div></div><div class="hp-as-btns">` +
                    (this.as.insert ? `<button class="btn btn-primary btn-sm" onclick="Help.insertDiagram(${n})">Insert</button>` : '') +
                    `<button class="btn btn-ghost btn-sm" onclick="Help.closeAssets(); Help.openDiagram(${n})" title="Open in the diagram editor"><i class="fa-solid fa-pen-ruler"></i></button>` +
                    '</div></div>';
            }).join('') + '</div>';
            return;
        }
        if (kind === 'pages') {
            body.innerHTML = '<table class="tbl"><tbody>' + items.filter(d => d.path !== this.current.path).map(d =>
                `<tr class="clickable" style="cursor:pointer" onclick="Help.insertDocLink(${esc(JSON.stringify(d.path))})">` +
                `<td><i class="fa-regular fa-file-lines muted"></i> ${esc(d.title)}</td><td class="mono small faint">${esc(d.path)}</td></tr>`).join('') +
                '</tbody></table>';
        } else if (kind === 'img') {
            body.innerHTML = '<div class="hp-as-grid">' + items.map(i =>
                `<div class="hp-as-card"><div class="hp-as-thumb" onclick="Help.openLightbox(this.querySelector('img').src)">` +
                `<img src="${esc(this.fileUrl('img/' + i.name))}" loading="lazy" alt=""></div>` +
                `<div class="hp-as-info"><div class="hp-as-name" title="${esc(i.name)}">${esc(i.name)}</div>` +
                `<div class="hp-as-sub">${App.fmtBytes(i.size)} · ${used(i)}</div></div>` +
                `<div class="hp-as-btns">${btns(i)}</div></div>`).join('') + '</div>';
        } else {
            body.innerHTML = '<table class="tbl hp-as-tbl"><thead><tr><th>File</th><th class="num">Size</th><th>Uploaded</th><th>Used</th><th></th></tr></thead><tbody>' +
                items.map(i => {
                    const icon = (this.FILE_ICONS.find(([re]) => re.test(i.name)) || [0, 'fa-file'])[1];
                    return `<tr><td class="mono"><i class="fa-solid ${icon} muted"></i> ${esc(i.name)}</td><td class="num">${App.fmtBytes(i.size)}</td>` +
                           `<td class="small faint">${App.fmtDate(i.mtime)}</td><td class="hp-as-sub">${used(i)}</td><td>${btns(i)}</td></tr>`;
                }).join('') + '</tbody></table>';
        }
    },

    insertAsset(name) {
        const md = this._assetMd(this.as.kind, name);
        this.closeAssets();
        this._insert(md);
    },

    insertDiagram(name) {
        const d = Diagrams.list.find(x => x.name === name);
        this.closeAssets();
        this._insert(`![${d ? d.title : name}](${this.relLink('diagrams/' + name + '.svg')})`);
    },

    insertDocLink(path) {
        const d = this.docs.find(x => x.path === path);
        this.closeAssets();
        this._insert(`[${d ? d.title : path}](${this.relLink(path)})`);
    },

    copyAsset(name) {
        this.copyText(this.current ? this._assetMd(this.as.kind, name) : `${this.as.kind}/${name}`);
        toast('Markdown copied');
    },

    deleteAsset(name) {
        const item = this.as.items.find(i => i.name === name);
        const warn = item && item.used_by.length ? `\n\nIt is used in:\n${item.used_by.join('\n')}` : '';
        if (!confirm(`Delete ${this.as.kind}/${name}?${warn}`)) return;
        App.api('/api/help/asset_delete', { json: { kind: this.as.kind, name } })
            .then(() => { toast('Moved to .trash'); this.loadAssets(); })
            .catch(e => toast(e.message, true));
    },

    // ── New / rename / delete ──────────────────────────────────

    _folders() {
        const set = new Set();
        this.docs.forEach(d => {
            const parts = d.path.split('/').slice(0, -1);
            parts.forEach((_, i) => set.add(parts.slice(0, i + 1).join('/')));
        });
        return [...set].sort();
    },

    _slugName(title) {
        return title.trim().replace(/[^\p{L}\p{N}]+/gu, '-').replace(/^-+|-+$/g, '').toLowerCase().slice(0, 80);
    },

    _docModalPath() {
        const folder = document.getElementById('hp-f-folder').value.trim().replace(/^\/+|\/+$/g, '');
        let name = document.getElementById('hp-f-name').value.trim().replace(/\.md$/i, '');
        return name ? (folder ? folder + '/' : '') + name + '.md' : '';
    },

    _docModalInput(e) {
        if (e.target.id === 'hp-f-name') this._docModal.nameTouched = true;
        if (e.target.id === 'hp-f-title' && !this._docModal.nameTouched) {
            document.getElementById('hp-f-name').value = this._slugName(e.target.value);
        }
        const p = this._docModalPath();
        document.getElementById('hp-f-path').textContent = p ? (this.root || '') + '/' + p : '';
    },

    _showDocModal(mode, folder, name, title) {
        this._docModal = { mode, nameTouched: mode === 'rename' };
        document.getElementById('hp-doc-title').innerHTML = mode === 'new'
            ? '<i class="fa-solid fa-file-circle-plus text-ok"></i> New document'
            : '<i class="fa-solid fa-i-cursor text-ok"></i> Rename / move';
        document.getElementById('hp-f-title-row').hidden = mode !== 'new';
        document.getElementById('hp-f-submit').textContent = mode === 'new' ? 'Create' : 'Rename';
        document.getElementById('hp-folders').innerHTML = this._folders().map(f => `<option value="${esc(f)}">`).join('');
        document.getElementById('hp-f-title').value = title;
        document.getElementById('hp-f-folder').value = folder;
        document.getElementById('hp-f-name').value = name;
        this._docModalInput({ target: {} });
        document.getElementById('hp-doc-overlay').classList.add('open');
        document.getElementById(mode === 'new' ? 'hp-f-title' : 'hp-f-name').focus();
    },

    openNew() {
        if (!this._leaveEditors()) return;
        const folder = this.current && this.current.path.includes('/') ? this.current.path.slice(0, this.current.path.lastIndexOf('/')) : '';
        this._showDocModal('new', folder, '', '');
    },

    openRename() {
        if (!this.current) return;
        const p = this.current.path, i = p.lastIndexOf('/');
        this._showDocModal('rename', i < 0 ? '' : p.slice(0, i), p.slice(i + 1).replace(/\.md$/i, ''), '');
    },

    closeDocModal() { document.getElementById('hp-doc-overlay').classList.remove('open'); },

    submitDocModal() {
        const path = this._docModalPath();
        if (!path) return toast('Enter a file name', true);
        if (this._docModal.mode === 'new') {
            const title = document.getElementById('hp-f-title').value.trim();
            App.api('/api/help/create', { json: { path, title } }).then(r => {
                this.closeDocModal();
                this._closeEditor();
                return this.loadTree().then(() => this.open(r.path)).then(() => this.edit());
            }).catch(e => toast(e.message, true));
        } else {
            App.api('/api/help/rename', { json: { path: this.current.path, new_path: path } }).then(r => {
                this.closeDocModal();
                toast('Renamed');
                return this.loadTree().then(() => this.open(r.path));
            }).catch(e => toast(e.message, true));
        }
    },

    remove() {
        if (!this.current || !confirm(`Delete "${this.current.title}" (${this.current.path})?\nIt is moved to ${this.root}/.trash`)) return;
        App.api('/api/help/delete', { json: { path: this.current.path } }).then(() => {
            toast('Moved to .trash');
            this.current = null;
            history.pushState(null, '', '/help');
            return this.loadTree().then(() => this._fromUrl(true));
        }).catch(e => toast(e.message, true));
    },
};

Help.init();
