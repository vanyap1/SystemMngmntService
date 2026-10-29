/* ==========================================================================
   Code editor page (templates/editor.html): Monaco tabs, file tree, outline,
   service log, terminal, command macros, sidebar system info.
   Uses shared core.js (App, esc, toast), services.js, sysinfo.js.
   ========================================================================== */

let editor = null;
let currentPath = null;
let activeRow = null;
// ── Tab state ────────────────────────────────────────────────
const tabs = new Map();   // path → { path, name, model, viewState, row, dirty }
let activeTabPath = null;

// ── Monaco init ─────────────────────────────────────────────────────────────
const VS = '/static/vendor/monaco/vs';   // vendored Monaco 0.44.0 (works offline)
const monacoLoader = document.createElement('script');
monacoLoader.src = VS + '/loader.js';
monacoLoader.onload = () => {
    require.config({ paths: { vs: VS } });
    require(['vs/editor/editor.main'], () => {
        editor = monaco.editor.create(document.getElementById('monaco-container'), {
            value: '// Select a file from the sidebar to open it',
            language: 'python',
            theme: 'vs-dark',
            automaticLayout: true,
            fontSize: 14,
            tabSize: 4,
            minimap: { enabled: true },
            scrollBeyondLastLine: false,
            renderLineHighlight: 'all',
            smoothScrolling: true,
            cursorBlinking: 'smooth',
        });
        editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, saveFile);
        editor.onDidChangeModelContent(() => { scheduleOutline(); });
        editor.onDidChangeCursorPosition(syncOutlineCursor);
    });
};
document.head.appendChild(monacoLoader);

// ── Language / icon helpers ─────────────────────────────────────────────────
const LANG_MAP = {
    py:'python', js:'javascript', ts:'typescript', tsx:'typescript', jsx:'javascript',
    html:'html', css:'css', scss:'css', json:'json', md:'markdown',
    sh:'shell', bash:'shell', yaml:'yaml', yml:'yaml',
    xml:'xml', ini:'ini', cfg:'ini', conf:'ini', txt:'plaintext', log:'plaintext'
};

function detectLang(name) {
    return LANG_MAP[name.split('.').pop().toLowerCase()] || 'plaintext';
}

function fileIcon(name) {
    if (!name) return '<i class="fa-regular fa-file" style="color:#888"></i>';
    const lower = name.toLowerCase();
    if (lower === 'dockerfile') return '<i class="fa-brands fa-docker" style="color:#2496ed"></i>';
    if (lower === '.dockerignore') return '<i class="fa-brands fa-docker" style="color:#7ab8d4"></i>';
    if (lower.startsWith('.git')) return '<i class="fa-brands fa-git-alt" style="color:#f34f29"></i>';
    if (lower === 'license' || lower === 'license.txt' || lower === 'license.md') {
        return '<i class="fa-solid fa-scale-balanced" style="color:#dcb67a"></i>';
    }
    if (lower === 'readme.md' || lower === 'readme.txt' || lower === 'readme') {
        return '<i class="fa-brands fa-markdown" style="color:#42a5f5"></i>';
    }

    const ext = lower.split('.').pop();
    switch (ext) {
        case 'py': case 'pyw': case 'pyc': case 'pyx': case 'pyd':
            return '<i class="fa-brands fa-python" style="color:#3776ab"></i>';
        case 'js': case 'mjs': case 'cjs':
            return '<i class="fa-brands fa-js" style="color:#f7df1e"></i>';
        case 'ts':
            return '<i class="fa-solid fa-code" style="color:#3178c6"></i>';
        case 'jsx': case 'tsx':
            return '<i class="fa-brands fa-react" style="color:#61dafb"></i>';
        case 'html': case 'htm':
            return '<i class="fa-brands fa-html5" style="color:#e34f26"></i>';
        case 'css':
            return '<i class="fa-brands fa-css3-alt" style="color:#2965f1"></i>';
        case 'scss': case 'sass': case 'less':
            return '<i class="fa-brands fa-sass" style="color:#cf649a"></i>';
        case 'json':
            return '<i class="fa-solid fa-code" style="color:#e5c07b"></i>';
        case 'yaml': case 'yml':
            return '<i class="fa-solid fa-sliders" style="color:#cb171e"></i>';
        case 'xml': case 'svg':
            return '<i class="fa-solid fa-code" style="color:#e8a838"></i>';
        case 'ini': case 'cfg': case 'conf': case 'env': case 'toml': case 'properties':
            return '<i class="fa-solid fa-gear" style="color:#9e9e9e"></i>';
        case 'sh': case 'bash': case 'zsh':
            return '<i class="fa-solid fa-terminal" style="color:#4ec9b0"></i>';
        case 'md': case 'markdown':
            return '<i class="fa-brands fa-markdown" style="color:#519aba"></i>';
        case 'txt': case 'text':
            return '<i class="fa-regular fa-file-lines" style="color:#aaaaaa"></i>';
        case 'log':
            return '<i class="fa-solid fa-list-ul" style="color:#ce9178"></i>';
        case 'sql': case 'sqlite': case 'sqlite3': case 'db':
            return '<i class="fa-solid fa-database" style="color:#b0bec5"></i>';
        case 'zip': case 'tar': case 'gz': case '7z': case 'bz2': case 'xz': case 'rar': case 'whl':
            return '<i class="fa-solid fa-box-archive" style="color:#e8a838"></i>';
        case 'png': case 'jpg': case 'jpeg': case 'gif': case 'webp': case 'ico': case 'bmp': case 'avif':
            return '<i class="fa-solid fa-image" style="color:#26a69a"></i>';
        case 'service': case 'socket': case 'target': case 'timer':
            return '<i class="fa-solid fa-microchip" style="color:#4ec9b0"></i>';
        case 'c': case 'h': case 'cpp': case 'hpp': case 'cc':
            return '<i class="fa-solid fa-c" style="color:#659ad2"></i>';
        case 'rs':
            return '<i class="fa-brands fa-rust" style="color:#dea584"></i>';
        case 'go':
            return '<i class="fa-brands fa-golang" style="color:#00add8"></i>';
        case 'java':
            return '<i class="fa-brands fa-java" style="color:#f89820"></i>';
        case 'php':
            return '<i class="fa-brands fa-php" style="color:#777bb4"></i>';
        case 'rb':
            return '<i class="fa-solid fa-gem" style="color:#cc342d"></i>';
        default:
            return '<i class="fa-regular fa-file-code" style="color:#858585"></i>';
    }
}
const IMG_EXTS = new Set(['png','jpg','jpeg','gif','webp','svg','bmp','ico','avif']);
function isImage(name) { return IMG_EXTS.has(name.split('.').pop().toLowerCase()); }

// ── File tree ───────────────────────────────────────────────────────────────
function buildTree(items, depth) {
    const ul = document.createElement('ul');
    ul.style.cssText = 'list-style:none;padding:0;margin:0';
    for (const item of items) {
        const li = document.createElement('li');
        li.className = 'tree-node';
        const row = document.createElement('div');
        row.className = 'tree-row';
        row.style.paddingLeft = (8 + depth * 16) + 'px';

        if (item.type === 'dir') {
            row.innerHTML = `<span class="arrow"><i class="fa-solid fa-chevron-right" style="font-size:9px"></i></span><span class="ico"><i class="fa-solid fa-folder" style="color:#dcb67a"></i></span><span class="lbl">${esc(item.name)}</span>`;
            const sub = buildTree(item.children || [], depth + 1);
            sub.className = 'tree-children';
            row.addEventListener('click', () => {
                const open = sub.classList.toggle('open');
                const arr = row.querySelector('.arrow');
                if (arr) arr.innerHTML = open ? '<i class="fa-solid fa-chevron-down" style="font-size:9px"></i>' : '<i class="fa-solid fa-chevron-right" style="font-size:9px"></i>';
                const ico = row.querySelector('.ico');
                if (ico) ico.innerHTML = open ? '<i class="fa-solid fa-folder-open" style="color:#e5c07b"></i>' : '<i class="fa-solid fa-folder" style="color:#dcb67a"></i>';
            });
            li.appendChild(row);
            li.appendChild(sub);
        } else {
            const sizeStr = item.size != null ? App.fmtBytes(item.size) : '';
            const ico = fileIcon(item.name);
            row.innerHTML =
                `<span class="arrow"></span>` +
                `<span class="ico">${ico}</span>` +
                `<span class="lbl">${esc(item.name)}</span>` +
                `<span class="fsize">${esc(sizeStr)}</span>` +
                `<span class="faction">` +
                  `<button class="faction-btn" title="Rename"><i class="fa-solid fa-pen-to-square"></i></button>` +
                  `<button class="faction-btn faction-del" title="Delete"><i class="fa-solid fa-trash"></i></button>` +
                `</span>`;
            row.querySelector('.faction-btn:not(.faction-del)').addEventListener('click', e => {
                e.stopPropagation();
                renameFile(item.path, item.name);
            });
            row.querySelector('.faction-del').addEventListener('click', e => {
                e.stopPropagation();
                deleteFile(item.path, item.name, li);
            });
            if (isImage(item.name)) {
                row.addEventListener('click', () => openImage(item.path, item.name, row));
            } else {
                row.addEventListener('click', () => openFile(item.path, item.name, row));
            }
            li.appendChild(row);
        }
        ul.appendChild(li);
    }
    return ul;
}

function reloadTree() {
    fetch('/api/tree')
        .then(r => r.json())
        .then(tree => {
            const el = document.getElementById('file-tree');
            el.innerHTML = '';
            el.appendChild(buildTree(tree, 0));
        })
        .catch(() => {
            document.getElementById('file-tree').innerHTML =
                '<div style="padding:12px;color:#f44">Failed to load tree</div>';
        });
}
reloadTree();

function newFile() {
    const name = prompt('New file name:');
    if (!name || !name.trim()) return;
    fetch('/api/file_create', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({name: name.trim()})
    }).then(r => r.json()).then(d => {
        if (d.success) { reloadTree(); toast(d.name + ' created'); }
        else toast('Error: ' + (d.error || 'unknown'), true);
    }).catch(() => toast('Request failed', true));
}

function renameFile(path, name) {
    const newName = prompt('Rename "' + name + '" to:', name);
    if (!newName || !newName.trim() || newName.trim() === name) return;
    fetch('/api/file_rename', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({path, new_name: newName.trim()})
    }).then(r => r.json()).then(d => {
        if (d.success) {
            if (tabs.has(path)) {
                const tab = tabs.get(path);
                const newPath = d.new_path;
                const newModel = monaco.editor.createModel(tab.model.getValue(), detectLang(d.new_name));
                newModel.onDidChangeContent(() => {
                    const t = tabs.get(newPath);
                    if (t) { t.dirty = true; renderTabs(); }
                });
                tab.model.dispose();
                tab.name = d.new_name; tab.path = newPath;
                tab.model = newModel; tab.dirty = false;
                tabs.delete(path); tabs.set(newPath, tab);
                if (activeTabPath === path) {
                    activeTabPath = newPath; currentPath = newPath;
                    editor.setModel(newModel);
                }
                renderTabs();
            }
            reloadTree();
            toast(name + ' → ' + d.new_name);
        } else toast('Error: ' + (d.error || 'unknown'), true);
    }).catch(() => toast('Request failed', true));
}

function deleteFile(path, name, li) {
    if (!confirm('Delete "' + name + '"?')) return;
    fetch('/api/file_delete', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({path})
    }).then(r => r.json()).then(d => {
        if (d.success) {
            if (tabs.has(path)) {
                const tab = tabs.get(path);
                if (tab.row) tab.row.classList.remove('selected');
                tab.model.dispose(); tabs.delete(path);
                if (activeTabPath === path) {
                    activeTabPath = null; currentPath = null;
                    const paths = [...tabs.keys()];
                    if (paths.length) { activateTab(paths[paths.length - 1]); }
                    else {
                        activeRow = null;
                        if (editor) editor.setModel(monaco.editor.createModel(
                            '// Select a file from the sidebar to open it', 'plaintext'));
                        updateOutline(); renderTabs();
                    }
                } else { renderTabs(); }
            }
            li.remove();
            toast(name + ' deleted');
        } else toast('Error: ' + (d.error || 'unknown'), true);
    }).catch(() => toast('Request failed', true));
}

function openImage(path, name, row) {
    if (activeRow) activeRow.classList.remove('selected');
    activeRow = row; row.classList.add('selected');
    document.getElementById('img-preview').src =
        '/api/file_raw?path=' + encodeURIComponent(path);
    document.getElementById('img-name-lbl').textContent = name;
    document.getElementById('img-overlay').classList.add('open');
}
function closeImage() {
    document.getElementById('img-overlay').classList.remove('open');
    document.getElementById('img-preview').src = '';
}
App.onEscape(() => { closeImage(); closeMacrosModal(); closeFaCatalog(); });

// ── Open file ───────────────────────────────────────────────────────────────
function openFile(path, name, row) {
    if (tabs.has(path)) {
        if (activeRow) activeRow.classList.remove('selected');
        activeRow = row;
        row.classList.add('selected');
        tabs.get(path).row = row;
        activateTab(path);
        return;
    }
    if (activeRow) activeRow.classList.remove('selected');
    activeRow = row;
    row.classList.add('selected');

    fetch('/api/file?path=' + encodeURIComponent(path))
        .then(r => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.text(); })
        .then(content => {
            if (!editor) return;
            const model = monaco.editor.createModel(content, detectLang(name));
            model.onDidChangeContent(() => {
                const t = tabs.get(path);
                if (t) { t.dirty = true; renderTabs(); }
            });
            tabs.set(path, { path, name, model, viewState: null, row, dirty: false });
            activateTab(path);
        })
        .catch(err => toast('Error opening file: ' + err.message, true));
}

function activateTab(path) {
    if (!editor || !tabs.has(path)) return;
    if (activeTabPath && tabs.has(activeTabPath))
        tabs.get(activeTabPath).viewState = editor.saveViewState();
    activeTabPath = path;
    currentPath = path;
    const tab = tabs.get(path);
    editor.setModel(tab.model);
    if (tab.viewState) editor.restoreViewState(tab.viewState);
    editor.focus();
    if (activeRow) activeRow.classList.remove('selected');
    if (tab.row) { activeRow = tab.row; tab.row.classList.add('selected'); }
    document.getElementById('save-ok').style.display = 'none';
    renderTabs();
    updateOutline();
}

function closeTab(path, event) {
    if (event) event.stopPropagation();
    const tab = tabs.get(path);
    if (!tab) return;
    if (tab.dirty && !confirm('"' + tab.name + '" has unsaved changes. Close anyway?')) return;
    if (tab.row) tab.row.classList.remove('selected');
    tab.model.dispose();
    tabs.delete(path);
    if (activeTabPath === path) {
        activeTabPath = null;
        currentPath = null;
        const paths = [...tabs.keys()];
        if (paths.length) {
            activateTab(paths[paths.length - 1]);
        } else {
            activeRow = null;
            if (editor) editor.setModel(
                monaco.editor.createModel('// Select a file from the sidebar to open it', 'plaintext'));
            updateOutline();
            renderTabs();
        }
    } else {
        renderTabs();
    }
}

function renderTabs() {
    const scroll = document.getElementById('tab-scroll');
    scroll.innerHTML = '';
    for (const [path, tab] of tabs) {
        const el = document.createElement('div');
        el.className = 'tab' + (path === activeTabPath ? ' active' : '');
        el.title = path;
        el.innerHTML =
            '<span class="tab-ico">' + fileIcon(tab.name) + '</span>' +
            '<span class="tab-name">' + esc(tab.name) + '</span>' +
            (tab.dirty ? '<span class="tab-dirty">&#9679;</span>' : '') +
            '<span class="tab-close">&#215;</span>';
        el.querySelector('.tab-close').addEventListener('click', e => closeTab(path, e));
        el.addEventListener('click', () => activateTab(path));
        scroll.appendChild(el);
    }
    const active = scroll.querySelector('.tab.active');
    if (active) active.scrollIntoView({ inline: 'nearest', block: 'nearest' });
}

// ── Save ────────────────────────────────────────────────────────────────────
function saveFile() {
    if (!currentPath || !editor) return;
    fetch('/api/file', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: currentPath, content: editor.getValue() })
    })
    .then(r => r.json())
    .then(d => {
        if (d.success) {
            const tab = tabs.get(currentPath);
            if (tab) { tab.dirty = false; renderTabs(); }
            const ok = document.getElementById('save-ok');
            ok.style.display = 'inline';
            setTimeout(() => ok.style.display = 'none', 2500);
        } else {
            toast('Save error: ' + (d.error || 'unknown'), true);
        }
    })
    .catch(err => toast('Save failed: ' + err.message, true));
}

// ── Service log / status bar ───────────────────────────────────────────────
Services.onChange(refreshLog);
refreshLog();
setInterval(refreshLog, 10000);

// ── Sysinfo ──────────────────────────────────────────────────────────────────
function renderSysinfo(d) {
    let h = '';
    // CPU / load
    const la1 = parseFloat((d.load || {})['1'] || 0);
    const laPct = Math.min(100, Math.round(la1 / (d.cpu_count || 1) * 100));
    h += `<div class="si-section">CPU &mdash; ${d.cpu_count || '?'} cores</div>`;
    h += `<div class="si-row"><span class="si-key">Load avg</span><span class="si-val">${(d.load||{})['1']} &middot; ${(d.load||{})['5']} &middot; ${(d.load||{})['15']}</span></div>`;
    h += SysInfo.bar(laPct);
    // Memory
    const m = d.mem || {};
    h += `<div class="si-section">Memory</div>`;
    h += `<div class="si-row"><span class="si-key">RAM</span><span class="si-val">${App.fmtKb(m.used_kb)} / ${App.fmtKb(m.total_kb)} &nbsp;${m.pct}%</span></div>`;
    h += SysInfo.bar(m.pct || 0);
    if (m.swap_total_kb > 0) {
        h += `<div class="si-row"><span class="si-key">Swap</span><span class="si-val">${App.fmtKb(m.swap_used_kb)} / ${App.fmtKb(m.swap_total_kb)} &nbsp;${m.swap_pct}%</span></div>`;
        h += SysInfo.bar(m.swap_pct || 0);
    }
    // Network
    h += `<div class="si-section">Network</div>`;
    (d.net || []).forEach(n => {
        const cls = n.state === 'UP' ? 'si-up' : 'si-down';
        const addr = n.addrs[0] || '—';
        h += `<div class="si-row"><span class="si-key ${cls}">${esc(n.iface)}</span><span class="si-val">${esc(addr)}</span></div>`;
        for (let i = 1; i < n.addrs.length; i++)
            h += `<div class="si-row"><span class="si-key"></span><span class="si-val">${esc(n.addrs[i])}</span></div>`;
    });
    // Processes
    h += `<div class="si-section">Processes</div>`;
    h += `<div class="si-row"><span class="si-key">Running</span><span class="si-val">${esc(String(d.procs))}</span></div>`;
    // Storage
    h += `<div class="si-section">Storage</div>`;
    if (d.lsblk) h += SysInfo.lsblkTable(d.lsblk, true);
    document.getElementById('sysinfo-body').innerHTML = h;
    document.getElementById('sysinfo-ts').textContent =
        new Date().toLocaleTimeString([], {hour:'2-digit', minute:'2-digit', second:'2-digit'});
}
SysInfo.poll(renderSysinfo);

// ── Outline panel ─────────────────────────────────────────────────────────────
let outlineVisible = true;
let outlineDebounce = null;
let activeSymItem = null;

// Symbol extractors per language
const SYMBOL_PATTERNS = [
    // Python class
    { re: /^(class)\s+(\w+)/,        kind: 'class',   ico: 'C' },
    // Python def / async def
    { re: /^(?:async\s+)?def\s+(\w+)/, kind: 'func',  ico: 'ƒ' },
    // JS/TS function declaration
    { re: /^(?:export\s+)?(?:async\s+)?function\s*(\w+)/, kind: 'func', ico: 'ƒ' },
    // JS/TS class
    { re: /^(?:export\s+)?(?:abstract\s+)?class\s+(\w+)/, kind: 'class', ico: 'C' },
    // JS/TS arrow / method assigned to const
    { re: /^(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?(?:\([^)]*\)|\w+)\s*=>/, kind: 'arrow', ico: '⇒' },
    // JS/TS object method shorthand / class method
    { re: /^\s{2,}(?:async\s+)?(\w+)\s*\([^)]*\)\s*\{/, kind: 'method', ico: 'm' },
    // Python @decorator (just show route)
    { re: /^@\w+\.route\(['"]([^'"]+)['"]/, kind: 'route', ico: '🔗' },
    // @app.route or @blueprint
    { re: /^@[\w.]+\s*$/, kind: 'deco', ico: '@' },
];

const KIND_COLOR = { class:'#4ec9b0', func:'#dcdcaa', arrow:'#9cdcfe',
                     method:'#c586c0', route:'#ce9178', deco:'#608b4e' };

function extractSymbols(code, lang) {
    const lines = code.split('\n');
    const symbols = [];
    let lastClass = null;

    for (let i = 0; i < lines.length; i++) {
        const line = lines[i];
        const trimmed = line.trimStart();
        const indent = line.length - trimmed.length;

        for (const pat of SYMBOL_PATTERNS) {
            const m = trimmed.match(pat.re);
            if (!m) continue;
            // name is group 1 or 2 depending on pattern
            const name = m[2] || m[1];
            if (!name || name.length < 1) break;

            // track class nesting for Python
            if (pat.kind === 'class') lastClass = { name, indent };

            // skip single-char or dunder helpers that are noise
            if (name.length === 1 && pat.kind === 'func') break;

            symbols.push({
                name,
                kind: pat.kind,
                ico: pat.ico,
                line: i + 1,   // 1-based
                indent,
                color: KIND_COLOR[pat.kind] || '#ccc',
                parent: (pat.kind === 'method' || pat.kind === 'func') && lastClass && indent > lastClass.indent
                    ? lastClass.name : null
            });
            break;
        }
    }
    return symbols;
}

function renderOutline(symbols) {
    const list = document.getElementById('outline-list');
    if (!symbols.length) {
        list.innerHTML = '<div id="outline-empty">No symbols found</div>';
        return;
    }
    list.innerHTML = '';
    activeSymItem = null;

    // group: classes on top, then functions/routes
    const classes  = symbols.filter(s => s.kind === 'class');
    const methods  = symbols.filter(s => s.kind === 'method' || (s.kind === 'func' && s.parent));
    const funcs    = symbols.filter(s => (s.kind === 'func' || s.kind === 'arrow') && !s.parent);
    const routes   = symbols.filter(s => s.kind === 'route');
    const other    = symbols.filter(s => !['class','func','arrow','method','route'].includes(s.kind));

    function addGroup(label, items) {
        if (!items.length) return;
        const g = document.createElement('div');
        g.className = 'sym-group';
        g.textContent = label;
        list.appendChild(g);
        items.forEach(sym => {
            const el = document.createElement('div');
            el.className = 'sym-item';
            el.dataset.line = sym.line;
            el.innerHTML =
                `<span class="sym-ico" style="color:${sym.color}">${sym.ico}</span>` +
                `<span class="sym-name" title="${esc(sym.name)}">${esc(sym.name)}</span>` +
                `<span class="sym-line">${sym.line}</span>`;
            el.addEventListener('click', () => jumpToLine(sym.line, el));
            list.appendChild(el);
        });
    }

    addGroup('Classes', classes);
    addGroup('Methods', methods);
    addGroup('Functions', funcs);
    addGroup('Routes', routes);
    addGroup('Other', other);
}

function jumpToLine(line, el) {
    if (!editor) return;
    if (activeSymItem) activeSymItem.classList.remove('active');
    activeSymItem = el;
    el.classList.add('active');
    editor.revealLineInCenter(line);
    editor.setPosition({ lineNumber: line, column: 1 });
    editor.focus();
}

function updateOutline() {
    if (!editor) return;
    const code = editor.getValue();
    const lang = editor.getModel()?.getLanguageId() || 'plaintext';
    const symbols = extractSymbols(code, lang);
    renderOutline(symbols);
}

function scheduleOutline() {
    clearTimeout(outlineDebounce);
    outlineDebounce = setTimeout(updateOutline, 500);
}

function toggleOutline(forceState) {
    if (typeof forceState === 'boolean') {
        outlineVisible = forceState;
    } else {
        outlineVisible = !outlineVisible;
    }
    const panel = document.getElementById('outline-panel');
    const strip = document.getElementById('outline-collapsed-strip');
    const tabBtn = document.getElementById('btn-outline-tab');

    if (panel) panel.classList.toggle('hidden', !outlineVisible);
    if (strip) strip.classList.toggle('hidden', outlineVisible);
    if (tabBtn) {
        tabBtn.classList.toggle('active', outlineVisible);
        tabBtn.title = outlineVisible ? 'Hide Outline' : 'Show Outline';
    }
    if (outlineVisible) {
        updateOutline();
    }
    if (editor) {
        setTimeout(() => editor.layout(), 30);
    }
}

// highlight current symbol on cursor move
function syncOutlineCursor() {
    if (!editor) return;
    const line = editor.getPosition()?.lineNumber;
    if (!line) return;
    const items = document.querySelectorAll('.sym-item');
    let best = null, bestLine = 0;
    items.forEach(el => {
        const l = parseInt(el.dataset.line);
        if (l <= line && l > bestLine) { bestLine = l; best = el; }
    });
    if (best !== activeSymItem) {
        if (activeSymItem) activeSymItem.classList.remove('active');
        if (best) best.classList.add('active');
        activeSymItem = best;
        if (best) best.scrollIntoView({ block: 'nearest' });
    }
}

// ── Console: tabs ────────────────────────────────────────────────────────────
let activeTab = 'log';
function switchTab(name) {
    activeTab = name;
    document.querySelectorAll('.ctab').forEach(t =>
        t.classList.toggle('active', t.dataset.tab === name));
    document.querySelectorAll('.cpane').forEach(p => p.classList.remove('active'));
    document.getElementById(name + '-pane').classList.add('active');
    if (name === 'log') refreshLog();
    if (name === 'term') {
        if (!term) setTimeout(initXterm, 50);
        else if (fitAddon) setTimeout(() => fitAddon.fit(), 10);
        setTimeout(() => document.getElementById('term-input').focus(), 120);
    }
}
function clearConsole() {
    if (activeTab === 'log') document.getElementById('log-pane').innerHTML = '';
    else if (term) term.clear();
}

// ── Service log ──────────────────────────────────────────────────────────────
function refreshLog() {
    const name = Services.current();
    fetch('/api/status?name=' + encodeURIComponent(name))
        .then(r => r.text())
        .then(text => {
            const pane = document.getElementById('log-pane');
            pane.innerHTML = Services.colorize(text);
            pane.scrollTop = pane.scrollHeight;
            // update status bar
            const dot = document.getElementById('svc-dot');
            dot.className = 'svc-dot ' + Services.stateOf(text);
            const aline = text.split('\n').find(l => /Active:/.test(l)) || '';
            document.getElementById('status-detail').textContent = aline.trim();
        })
        .catch(() => {
            document.getElementById('log-pane').textContent = 'Failed to fetch status.';
            document.getElementById('status-detail').textContent = 'Status unavailable';
        });
}

// ── Terminal ─────────────────────────────────────────────────────────────────
let cmdHistory = [], histIdx = -1;
let term = null, fitAddon = null;

function initXterm() {
    if (term || typeof Terminal === 'undefined') return;
    fitAddon = new FitAddon.FitAddon();
    term = new Terminal({
        theme: {
            background: '#1a1a1a', foreground: '#d4d4d4',
            cursor: '#4ec9b0', cursorAccent: '#1a1a1a',
            selectionBackground: 'rgba(78,201,176,.25)',
            black:   '#1e1e1e', red:     '#f44747', green:   '#6dbf85', yellow:  '#d4a95a',
            blue:    '#569cd6', magenta: '#c586c0', cyan:    '#4ec9b0', white:   '#d4d4d4',
            brightBlack:   '#808080', brightRed:     '#f44747', brightGreen:   '#6dbf85',
            brightYellow:  '#d4a95a', brightBlue:    '#569cd6', brightMagenta: '#c586c0',
            brightCyan:    '#4ec9b0', brightWhite:   '#ffffff',
        },
        fontSize: 12,
        fontFamily: "'Cascadia Code','Fira Mono',Consolas,monospace",
        lineHeight: 1.4,
        convertEol: true,
        scrollback: 3000,
        disableStdin: true,
        cursorBlink: false,
        allowProposedApi: true,
    });
    term.loadAddon(fitAddon);
    term.open(document.getElementById('xterm-container'));
    fitAddon.fit();
    term.write('\x1b[38;5;78m' + document.getElementById('term-prompt').textContent + '\x1b[0m');
}

function termKeyDown(e) {
    const inp = document.getElementById('term-input');
    const promptTxt = document.getElementById('term-prompt').textContent;
    if (e.key === 'Enter') {
        const cmd = inp.value.trim();
        inp.value = ''; histIdx = -1;
        if (!term) initXterm();
        term.write('\x1b[38;5;78m' + promptTxt + '\x1b[0m' + cmd + '\r\n');
        if (!cmd) {
            term.write('\x1b[38;5;78m' + promptTxt + '\x1b[0m');
            return;
        }
        cmdHistory.unshift(cmd);
        if (cmdHistory.length > 200) cmdHistory.pop();
        execCmd(cmd);
    } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        if (histIdx < cmdHistory.length - 1) inp.value = cmdHistory[++histIdx];
    } else if (e.key === 'ArrowDown') {
        e.preventDefault();
        if (histIdx > 0) { inp.value = cmdHistory[--histIdx]; }
        else { histIdx = -1; inp.value = ''; }
    }
}

function execCmd(cmd) {
    const promptTxt = document.getElementById('term-prompt').textContent;
    fetch('/api/exec', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ cmd })
    })
    .then(r => r.json())
    .then(d => {
        if (!term) return;
        if (d.stdout) term.write(d.stdout);
        if (d.stderr) term.write('\x1b[38;5;203m' + d.stderr + '\x1b[0m');
        if (!d.stdout && !d.stderr && d.returncode !== 0)
            term.write('\x1b[38;5;203mExit code: ' + d.returncode + '\x1b[0m\r\n');
        term.write('\x1b[38;5;78m' + promptTxt + '\x1b[0m');
    })
    .catch(err => {
        if (term) {
            term.write('\x1b[38;5;203mRequest failed: ' + err.message + '\x1b[0m\r\n');
            term.write('\x1b[38;5;78m' + promptTxt + '\x1b[0m');
        }
    });
}

// ── Resize grip ──────────────────────────────────────────────────────────────
(function () {
    const grip  = document.getElementById('resize-grip');
    const panel = document.getElementById('console-panel');
    let dragging = false, startY = 0, startH = 0;
    grip.addEventListener('mousedown', e => {
        dragging = true; startY = e.clientY; startH = panel.offsetHeight;
        grip.classList.add('dragging');
        document.body.style.cssText += ';cursor:ns-resize;user-select:none';
    });
    document.addEventListener('mousemove', e => {
        if (!dragging) return;
        const h = Math.max(60, Math.min(startH + startY - e.clientY, window.innerHeight * 0.75));
        panel.style.height = h + 'px';
    });
    document.addEventListener('mouseup', () => {
        if (!dragging) return;
        dragging = false;
        grip.classList.remove('dragging');
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
        if (fitAddon) setTimeout(() => fitAddon.fit(), 20);
    });
})();
window.addEventListener('resize', () => { if (fitAddon) fitAddon.fit(); });

// ── Command Macros ────────────────────────────────────────────────────────────
let _macrosList = [];
let _modalMacros = [];
let _activeIconPickerIdx = null;
let _currentFaCategory = 'all';

const PRESET_COLORS = [
    { color: '#162638', name: 'Blue' },
    { color: '#1b4d2e', name: 'Green' },
    { color: '#4d1b1b', name: 'Red' },
    { color: '#4d3b1a', name: 'Amber' },
    { color: '#381c4e', name: 'Purple' },
    { color: '#113d48', name: 'Teal' },
    { color: '#252526', name: 'Dark Gray' },
    { color: '#1e2a5a', name: 'Indigo' },
    { color: '#4a2c11', name: 'Brown' }
];

const QUICK_ICONS = [
    { cls: 'fa-solid fa-terminal', name: 'Terminal' },
    { cls: 'fa-brands fa-git-alt', name: 'Git' },
    { cls: 'fa-solid fa-hard-drive', name: 'Disk' },
    { cls: 'fa-solid fa-microchip', name: 'CPU' },
    { cls: 'fa-solid fa-clock', name: 'Uptime' },
    { cls: 'fa-solid fa-server', name: 'Server' },
    { cls: 'fa-solid fa-play', name: 'Play' },
    { cls: 'fa-solid fa-arrows-rotate', name: 'Refresh' },
    { cls: 'fa-solid fa-database', name: 'Database' },
    { cls: 'fa-solid fa-box-archive', name: 'Archive' },
    { cls: 'fa-solid fa-code', name: 'Code' },
    { cls: 'fa-solid fa-gear', name: 'Settings' }
];

const FA_CATALOG = [
    // System / Hardware
    { cls: 'fa-solid fa-server', name: 'Server', cat: 'sys' },
    { cls: 'fa-solid fa-hard-drive', name: 'Disk', cat: 'sys' },
    { cls: 'fa-solid fa-microchip', name: 'CPU', cat: 'sys' },
    { cls: 'fa-solid fa-memory', name: 'Memory', cat: 'sys' },
    { cls: 'fa-solid fa-clock', name: 'Uptime', cat: 'sys' },
    { cls: 'fa-solid fa-gauge-high', name: 'Load', cat: 'sys' },
    { cls: 'fa-solid fa-network-wired', name: 'Network', cat: 'sys' },
    { cls: 'fa-solid fa-wifi', name: 'Wi-Fi', cat: 'sys' },
    { cls: 'fa-solid fa-bolt', name: 'Power', cat: 'sys' },
    { cls: 'fa-solid fa-power-off', name: 'Shutdown', cat: 'sys' },
    { cls: 'fa-solid fa-rotate-right', name: 'Reboot', cat: 'sys' },
    { cls: 'fa-solid fa-shield-halved', name: 'Security', cat: 'sys' },
    { cls: 'fa-solid fa-fan', name: 'Cooler', cat: 'sys' },
    { cls: 'fa-solid fa-temperature-half', name: 'Temperature', cat: 'sys' },
    { cls: 'fa-solid fa-tower-broadcast', name: 'Antenna', cat: 'sys' },
    { cls: 'fa-solid fa-ethernet', name: 'Ethernet', cat: 'sys' },

    // Dev / CLI / Git
    { cls: 'fa-solid fa-terminal', name: 'Terminal', cat: 'dev' },
    { cls: 'fa-brands fa-git-alt', name: 'Git', cat: 'dev' },
    { cls: 'fa-brands fa-github', name: 'GitHub', cat: 'dev' },
    { cls: 'fa-brands fa-docker', name: 'Docker', cat: 'dev' },
    { cls: 'fa-brands fa-python', name: 'Python', cat: 'dev' },
    { cls: 'fa-brands fa-node-js', name: 'Node.js', cat: 'dev' },
    { cls: 'fa-brands fa-rust', name: 'Rust', cat: 'dev' },
    { cls: 'fa-brands fa-linux', name: 'Linux', cat: 'dev' },
    { cls: 'fa-brands fa-ubuntu', name: 'Ubuntu', cat: 'dev' },
    { cls: 'fa-solid fa-code', name: 'Code', cat: 'dev' },
    { cls: 'fa-solid fa-code-branch', name: 'Branch', cat: 'dev' },
    { cls: 'fa-solid fa-code-commit', name: 'Commit', cat: 'dev' },
    { cls: 'fa-solid fa-code-merge', name: 'Merge', cat: 'dev' },
    { cls: 'fa-solid fa-bug', name: 'Bug', cat: 'dev' },
    { cls: 'fa-solid fa-cubes', name: 'Packages', cat: 'dev' },
    { cls: 'fa-solid fa-plug', name: 'Plugin', cat: 'dev' },
    { cls: 'fa-solid fa-key', name: 'Key', cat: 'dev' },
    { cls: 'fa-solid fa-lock', name: 'Lock', cat: 'dev' },
    { cls: 'fa-solid fa-unlock', name: 'Unlock', cat: 'dev' },

    // Files / Data
    { cls: 'fa-solid fa-folder', name: 'Folder', cat: 'files' },
    { cls: 'fa-solid fa-folder-open', name: 'Open Folder', cat: 'files' },
    { cls: 'fa-solid fa-file-code', name: 'Code File', cat: 'files' },
    { cls: 'fa-solid fa-file-lines', name: 'Log / Text', cat: 'files' },
    { cls: 'fa-solid fa-database', name: 'Database', cat: 'files' },
    { cls: 'fa-solid fa-box-archive', name: 'Archive', cat: 'files' },
    { cls: 'fa-solid fa-download', name: 'Download', cat: 'files' },
    { cls: 'fa-solid fa-upload', name: 'Upload', cat: 'files' },
    { cls: 'fa-solid fa-copy', name: 'Copy', cat: 'files' },
    { cls: 'fa-solid fa-trash-can', name: 'Trash', cat: 'files' },
    { cls: 'fa-solid fa-floppy-disk', name: 'Save', cat: 'files' },
    { cls: 'fa-solid fa-share-nodes', name: 'Share', cat: 'files' },

    // Actions / Status
    { cls: 'fa-solid fa-play', name: 'Play', cat: 'actions' },
    { cls: 'fa-solid fa-stop', name: 'Stop', cat: 'actions' },
    { cls: 'fa-solid fa-pause', name: 'Pause', cat: 'actions' },
    { cls: 'fa-solid fa-arrows-rotate', name: 'Refresh', cat: 'actions' },
    { cls: 'fa-solid fa-circle-check', name: 'Success', cat: 'actions' },
    { cls: 'fa-solid fa-triangle-exclamation', name: 'Warning', cat: 'actions' },
    { cls: 'fa-solid fa-circle-exclamation', name: 'Error', cat: 'actions' },
    { cls: 'fa-solid fa-circle-info', name: 'Info', cat: 'actions' },
    { cls: 'fa-solid fa-magnifying-glass', name: 'Search', cat: 'actions' },
    { cls: 'fa-solid fa-filter', name: 'Filter', cat: 'actions' },
    { cls: 'fa-solid fa-wrench', name: 'Tools', cat: 'actions' },
    { cls: 'fa-solid fa-gear', name: 'Settings', cat: 'actions' },
    { cls: 'fa-solid fa-sliders', name: 'Sliders', cat: 'actions' },
    { cls: 'fa-solid fa-chart-line', name: 'Chart', cat: 'actions' },
    { cls: 'fa-solid fa-chart-simple', name: 'Stats', cat: 'actions' },
    { cls: 'fa-solid fa-bell', name: 'Bell', cat: 'actions' },
    { cls: 'fa-solid fa-bullseye', name: 'Target / Ping', cat: 'actions' },
    { cls: 'fa-solid fa-eye', name: 'Monitor', cat: 'actions' },
    { cls: 'fa-solid fa-cloud', name: 'Cloud', cat: 'actions' },
    { cls: 'fa-solid fa-globe', name: 'Web', cat: 'actions' },
    { cls: 'fa-solid fa-layer-group', name: 'Groups', cat: 'actions' },
    { cls: 'fa-solid fa-list-check', name: 'Tasks', cat: 'actions' }
];

function formatFaClass(cls) {
    if (!cls) return '';
    cls = cls.trim();
    if (/^fa-[a-z0-9-]+$/i.test(cls)) {
        return 'fa-solid ' + cls;
    }
    return cls;
}

function getContrastTextColor(hex) {
    if (!hex || !hex.startsWith('#')) return '#8ec8f6';
    let c = hex.replace('#', '');
    if (c.length === 3) c = c.split('').map(x => x + x).join('');
    if (c.length !== 6) return '#ffffff';
    const r = parseInt(c.substring(0, 2), 16) || 0;
    const g = parseInt(c.substring(2, 4), 16) || 0;
    const b = parseInt(c.substring(4, 6), 16) || 0;
    const yiq = ((r * 299) + (g * 587) + (b * 114)) / 1000;
    return yiq >= 150 ? '#111111' : '#ffffff';
}

function getBorderColor(hex) {
    if (!hex || !hex.startsWith('#')) return '#244161';
    let c = hex.replace('#', '');
    if (c.length === 3) c = c.split('').map(x => x + x).join('');
    if (c.length !== 6) return 'rgba(255,255,255,0.2)';
    let r = parseInt(c.substring(0, 2), 16) || 0;
    let g = parseInt(c.substring(2, 4), 16) || 0;
    let b = parseInt(c.substring(4, 6), 16) || 0;
    r = Math.min(255, Math.floor(r * 1.35 + 20));
    g = Math.min(255, Math.floor(g * 1.35 + 20));
    b = Math.min(255, Math.floor(b * 1.35 + 20));
    return `rgb(${r}, ${g}, ${b})`;
}

function renderMacroButtons() {
    const bar = document.getElementById('macro-bar');
    if (!bar) return;
    bar.innerHTML = '';
    _macrosList.forEach((m, idx) => {
        const btn = document.createElement('button');
        btn.className = 'btn btn-macro';
        btn.title = m.tooltip || m.name || m.command || '';
        const faCls = formatFaClass(m.icon);
        let inner = '';
        if (faCls) inner += `<i class="${esc(faCls)}"></i>`;
        if (m.name) inner += `<span>${esc(m.name)}</span>`;
        if (!inner) inner = `<span>#${idx + 1}</span>`;
        btn.innerHTML = inner;
        const col = (m.color || '').trim();
        if (col) {
            btn.style.backgroundColor = col;
            btn.style.borderColor = getBorderColor(col);
            btn.style.color = getContrastTextColor(col);
        }
        btn.onclick = () => runMacro(idx);
        bar.appendChild(btn);
    });
}

function runMacro(idx) {
    const m = _macrosList[idx];
    if (!m || !m.command) {
        toast('Command is not configured', true);
        return;
    }
    switchTab('term');
    if (!term) initXterm();
    const cmd = m.command.trim();
    const promptEl = document.getElementById('term-prompt');
    const promptTxt = promptEl ? promptEl.textContent : '$ ';
    term.write('\x1b[38;5;78m' + promptTxt + '\x1b[0m' + cmd + '\r\n');
    cmdHistory.unshift(cmd);
    if (cmdHistory.length > 200) cmdHistory.pop();
    toast('▶ ' + (m.name || cmd));
    execCmd(cmd);
}

function openMacrosModal() {
    _modalMacros = JSON.parse(JSON.stringify(_macrosList));
    document.getElementById('macros-status').textContent = '';
    renderMacrosEditor();
    document.getElementById('macros-overlay').classList.add('open');
}

function closeMacrosModal() {
    document.getElementById('macros-overlay').classList.remove('open');
}

function syncModalMacrosFromDOM() {
    const cards = document.querySelectorAll('#macros-editor-list .macro-card');
    const updated = [];
    cards.forEach(card => {
        updated.push({
            name: card.querySelector('.macro-input-name').value,
            tooltip: card.querySelector('.macro-input-tooltip').value,
            command: card.querySelector('.macro-input-cmd').value,
            icon: card.querySelector('.macro-input-icon').value,
            color: card.querySelector('.macro-input-color') ? card.querySelector('.macro-input-color').value : '#162638'
        });
    });
    _modalMacros = updated;
}

function renderMacrosEditor() {
    const list = document.getElementById('macros-editor-list');
    if (!list) return;
    if (!_modalMacros.length) {
        list.innerHTML = `<div class="macros-empty-msg">
            <div style="font-size:24px;margin-bottom:8px;opacity:.5"><i class="fa-solid fa-terminal"></i></div>
            <div>No command macros.</div>
            <div style="font-size:11.5px;color:#777;margin-top:4px">Click "Add Button" below to create your first macro.</div>
        </div>`;
        return;
    }
    list.innerHTML = _modalMacros.map((m, i) => {
        const faCls = formatFaClass(m.icon);
        const cardColor = m.color || '#162638';
        return `
        <div class="macro-card" data-idx="${i}">
            <div class="macro-card-head">
                <div class="macro-card-title">
                    <span class="macro-card-badge">#${i + 1}</span>
                    <div class="macro-preview-chip" id="chip-prev-${i}" style="background-color:${esc(cardColor)};border-color:${esc(getBorderColor(cardColor))};color:${esc(getContrastTextColor(cardColor))}">
                        <i class="${esc(faCls || 'fa-solid fa-play')}"></i>
                        <span class="chip-text">${esc(m.name || 'Button')}</span>
                    </div>
                </div>
                <div class="macro-card-ctrls">
                    <button type="button" class="macro-btn-ctrl" onclick="moveMacroItem(${i}, -1)" title="Up" ${i === 0 ? 'disabled' : ''}><i class="fa-solid fa-arrow-up"></i></button>
                    <button type="button" class="macro-btn-ctrl" onclick="moveMacroItem(${i}, 1)" title="Down" ${i === _modalMacros.length - 1 ? 'disabled' : ''}><i class="fa-solid fa-arrow-down"></i></button>
                    <button type="button" class="macro-btn-ctrl macro-btn-del" onclick="deleteMacroCard(${i})" title="Delete"><i class="fa-solid fa-trash-can"></i></button>
                </div>
            </div>
            <div class="macro-card-body">
                <div class="macro-field-row">
                    <div class="macro-field">
                        <label>Button Label</label>
                        <input type="text" class="macro-input-name" value="${esc(m.name || '')}" placeholder="e.g. Git Status" oninput="updateMacroCardPreview(${i})">
                        <span class="hint">Button name shown on topbar</span>
                    </div>
                    <div class="macro-field">
                        <label>Tooltip (on hover)</label>
                        <input type="text" class="macro-input-tooltip" value="${esc(m.tooltip || '')}" placeholder="e.g. Check Git repository status">
                        <span class="hint">Hover tooltip text</span>
                    </div>
                </div>
                <div class="macro-field-row">
                    <div class="macro-field">
                        <label>Command to execute (Bash)</label>
                        <input type="text" class="macro-input-cmd" value="${esc(m.command || '')}" placeholder="e.g. git status" style="font-family:'Cascadia Code','Fira Mono',Consolas,monospace">
                        <span class="hint">Executed in the interactive terminal</span>
                    </div>
                    <div class="macro-field">
                        <label>Button Color (Color Picker & Palette)</label>
                        <div class="macro-color-row">
                            <input type="color" class="macro-input-color" value="${esc(cardColor)}" oninput="updateMacroCardPreview(${i})">
                            <span class="macro-color-hex">${esc(cardColor)}</span>
                            <div class="macro-swatches">
                                ${PRESET_COLORS.map(p => `
                                    <button type="button" class="macro-swatch" style="background:${p.color}" onclick="setMacroCardColor(${i}, '${p.color}')" title="${p.name}"></button>
                                `).join('')}
                            </div>
                        </div>
                        <span class="hint">Button background color</span>
                    </div>
                </div>
                <div class="macro-field">
                    <div style="display:flex;justify-content:space-between;align-items:center">
                        <label>FontAwesome Icon</label>
                        <button type="button" class="btn-fa-catalog" onclick="openFaCatalog(${i})">
                            <i class="fa-solid fa-icons"></i> FA Icons Catalog
                        </button>
                    </div>
                    <div style="display:flex;gap:6px;align-items:center;margin-top:2px">
                        <input type="text" class="macro-input-icon" value="${esc(m.icon || '')}" placeholder="fa-solid fa-terminal" oninput="updateMacroCardPreview(${i})">
                        <div class="macro-icon-preview" id="icon-prev-${i}"><i class="${esc(faCls || 'fa-solid fa-play')}"></i></div>
                    </div>
                    <div class="macro-quick-icons">
                        <span style="font-size:10px;color:#777;margin-right:2px">Quick select:</span>
                        ${QUICK_ICONS.map(q => `
                            <button type="button" class="macro-quick-ico-btn" onclick="setMacroCardIcon(${i}, '${q.cls}')" title="${q.name} (${q.cls})">
                                <i class="${q.cls}"></i>
                            </button>
                        `).join('')}
                    </div>
                </div>
            </div>
        </div>`;
    }).join('');
}

function setMacroCardColor(idx, color) {
    const card = document.querySelector(`.macro-card[data-idx="${idx}"]`);
    if (!card) return;
    const inp = card.querySelector('.macro-input-color');
    if (inp) inp.value = color;
    updateMacroCardPreview(idx);
}

function setMacroCardIcon(idx, cls) {
    const card = document.querySelector(`.macro-card[data-idx="${idx}"]`);
    if (!card) return;
    const inp = card.querySelector('.macro-input-icon');
    if (inp) inp.value = cls;
    updateMacroCardPreview(idx);
}

function updateMacroCardPreview(idx) {
    const card = document.querySelector(`.macro-card[data-idx="${idx}"]`);
    if (!card) return;
    const nameVal = card.querySelector('.macro-input-name').value.trim();
    const iconVal = card.querySelector('.macro-input-icon').value.trim();
    const colorVal = card.querySelector('.macro-input-color') ? card.querySelector('.macro-input-color').value : '#162638';
    const colorHexSpan = card.querySelector('.macro-color-hex');
    if (colorHexSpan) colorHexSpan.textContent = colorVal;
    const faCls = formatFaClass(iconVal);

    const chip = document.getElementById(`chip-prev-${idx}`);
    if (chip) {
        chip.innerHTML = `<i class="${esc(faCls || 'fa-solid fa-play')}"></i> <span class="chip-text">${esc(nameVal || 'Button')}</span>`;
        chip.style.backgroundColor = colorVal;
        chip.style.borderColor = getBorderColor(colorVal);
        chip.style.color = getContrastTextColor(colorVal);
    }
    const icoBox = document.getElementById(`icon-prev-${idx}`);
    if (icoBox) {
        icoBox.innerHTML = `<i class="${esc(faCls || 'fa-solid fa-play')}"></i>`;
    }
}

function addMacroCard() {
    syncModalMacrosFromDOM();
    _modalMacros.push({
        name: '',
        tooltip: '',
        command: '',
        icon: 'fa-solid fa-terminal',
        color: '#162638'
    });
    renderMacrosEditor();
    const list = document.getElementById('macros-editor-list');
    if (list) list.scrollTop = list.scrollHeight;
}

function deleteMacroCard(idx) {
    syncModalMacrosFromDOM();
    _modalMacros.splice(idx, 1);
    renderMacrosEditor();
}

function moveMacroItem(idx, delta) {
    syncModalMacrosFromDOM();
    const target = idx + delta;
    if (target < 0 || target >= _modalMacros.length) return;
    const tmp = _modalMacros[idx];
    _modalMacros[idx] = _modalMacros[target];
    _modalMacros[target] = tmp;
    renderMacrosEditor();
}

function saveMacrosModal() {
    syncModalMacrosFromDOM();
    const clean = _modalMacros.map(m => ({
        name: (m.name || '').trim(),
        tooltip: (m.tooltip || '').trim(),
        command: (m.command || '').trim(),
        icon: (m.icon || '').trim(),
        color: (m.color || '').trim() || '#162638'
    }));

    const statusEl = document.getElementById('macros-status');
    statusEl.style.color = '#888';
    statusEl.textContent = 'Saving…';

    fetch('/api/macros', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(clean)
    })
    .then(r => r.json())
    .then(data => {
        if (data.success) {
            _macrosList = data.macros;
            renderMacroButtons();
            statusEl.style.color = '#4ec9b0';
            statusEl.textContent = '✓ Saved';
            toast('Macros saved successfully');
            setTimeout(() => {
                closeMacrosModal();
            }, 600);
        } else {
            statusEl.style.color = '#f44747';
            statusEl.textContent = 'Error: ' + (data.error || 'failed to save');
        }
    })
    .catch(err => {
        statusEl.style.color = '#f44747';
        statusEl.textContent = 'Error: ' + err.message;
    });
}

// ── FontAwesome Catalog Modal Logic ──────────────────────────────────────────
function setFaCategory(cat) {
    _currentFaCategory = cat;
    document.querySelectorAll('.fa-pill').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.cat === cat);
    });
    filterFaIcons();
}

function filterFaIcons() {
    const q = (document.getElementById('fa-search-input').value || '').toLowerCase().trim();
    const grid = document.getElementById('fa-icon-grid');
    if (!grid) return;
    const filtered = FA_CATALOG.filter(item => {
        const matchesCat = _currentFaCategory === 'all' || item.cat === _currentFaCategory;
        const matchesSearch = !q || item.cls.toLowerCase().includes(q) || item.name.toLowerCase().includes(q);
        return matchesCat && matchesSearch;
    });

    if (!filtered.length) {
        grid.innerHTML = '<div style="grid-column:1/-1;text-align:center;padding:30px;color:#666">No icons found</div>';
        return;
    }

    grid.innerHTML = filtered.map(item => `
        <button type="button" class="fa-grid-item" onclick="selectFaIcon('${item.cls}')" title="${item.cls}">
            <i class="${item.cls}"></i>
            <span class="fa-item-lbl">${esc(item.name)}</span>
        </button>
    `).join('');
}

function openFaCatalog(idx) {
    _activeIconPickerIdx = idx;
    _currentFaCategory = 'all';
    document.querySelectorAll('.fa-pill').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.cat === 'all');
    });
    const inp = document.getElementById('fa-search-input');
    if (inp) inp.value = '';
    filterFaIcons();
    const ov = document.getElementById('fa-catalog-overlay');
    if (ov) ov.classList.add('open');
    setTimeout(() => { if (inp) inp.focus(); }, 100);
}

function closeFaCatalog() {
    const ov = document.getElementById('fa-catalog-overlay');
    if (ov) ov.classList.remove('open');
    _activeIconPickerIdx = null;
}

function selectFaIcon(cls) {
    if (_activeIconPickerIdx !== null) {
        setMacroCardIcon(_activeIconPickerIdx, cls);
    }
    closeFaCatalog();
}


// Init: render macro buttons
App.api('/api/macros').then(list => { _macrosList = list; renderMacroButtons(); }).catch(() => {});
