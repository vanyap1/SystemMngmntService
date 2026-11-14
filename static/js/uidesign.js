/* ==========================================================================
   UI designer (routes/uidesign.py, core/ui_screens.py): screens for the device display, stored in UI/screens/.
   The stage shows the screen in design pixels (scaled with a CSS transform); widgets are dragged, resized and edited
   in the properties panel. Live data from the panel's API previews values, bars and charts. Save writes the JSON —
   the device (UI/screen_runner.py) reloads a shown screen by itself; "On device" makes it the display script.
   ========================================================================== */

const UIDesign = {
    meta: null, screens: [], images: [], display: null, tests: null,
    name: '', doc: null, sel: null, dirty: false, undoStack: [],
    k: 1, live: {}, hist: {}, liveTimer: null, lastT: 0,
    ICONS: { panel: 'fa-square', label: 'fa-font', value: 'fa-hashtag', bar: 'fa-bars-progress', chart: 'fa-chart-line',
             image: 'fa-image', button: 'fa-hand-pointer', clock: 'fa-clock', camera: 'fa-video' },
    SIZES: { panel: [400, 240], label: [400, 80], value: [300, 100], bar: [400, 40], chart: [600, 300], image: [240, 240],
             button: [260, 100], clock: [300, 90], camera: [640, 360] },
    cams: null, camRes: {}, preview: {},       // video devices, resolutions per device, previewed widget ids

    $(id) { return document.getElementById(id); },

    init() {
        this.$('ud-palette').innerHTML = Object.keys(this.ICONS).map(t =>
            `<button type="button" onclick="UIDesign.add('${t}')"><i class="fa-solid ${this.ICONS[t]}"></i>${t}</button>`).join('');
        this._wireStage();
        document.addEventListener('keydown', e => this._key(e));
        window.addEventListener('resize', () => this.fit());
        window.addEventListener('beforeunload', e => { if (this.dirty) { e.preventDefault(); e.returnValue = ''; } });
        window.addEventListener('pagehide', () => this.stopPreviews());
        App.api('/api/uiscreens').then(d => {
            this.meta = d.meta; this.screens = d.screens; this.images = d.images; this.display = d.display;
            this._bgOptions();
            let want = new URLSearchParams(location.search).get('screen');
            try { want = want || localStorage.getItem('uidesign.screen'); } catch (e) { /* storage unavailable */ }
            const first = this.screens.find(s => s.name === want) || this.screens[0];
            if (first) this.open(first.name);
            else this.newScreen('main');
            this.liveToggle();
        }).catch(e => toast(e.message, true));
    },

    // ── Screens ────────────────────────────────────────────

    _screenList() {
        this.$('ud-screen').innerHTML = this.screens.map(s => `<option value="${esc(s.name)}">${esc(s.name)}${s.title ? ' — ' + esc(s.title) : ''}</option>`).join('') +
            (this.name && !this.screens.some(s => s.name === this.name) ? `<option value="${esc(this.name)}">${esc(this.name)} (new)</option>` : '');
        this.$('ud-screen').value = this.name;
    },

    open(name) {
        if (this.dirty && name !== this.name && !confirm(`Discard the unsaved changes of "${this.name}"?`)) return this._screenList();
        App.api('/api/uiscreens/' + encodeURIComponent(name)).then(d => {
            this._load(name, d.screen);
        }).catch(e => toast(e.message, true));
    },

    _load(name, doc, dirty = false) {
        this.stopPreviews();
        this.name = name; this.doc = doc; this.sel = null; this.undoStack = []; this.hist = {};
        try { localStorage.setItem('uidesign.screen', name); } catch (e) { /* storage unavailable */ }
        this._docForm();
        this._screenList();
        this.setDirty(dirty);
        this.render();
        this.fit();
        if (this.$('ud-live').checked) this._poll();
    },

    _defaultSize() {
        const m = /^(\d+)x(\d+)/.exec((this.display && this.display.screen && this.display.screen.mode) || '');
        const s = this.display ? this.display.settings : {};
        if (s.width && s.height) return [s.width, s.height];
        return m ? [+m[1], +m[2]] : [1280, 720];
    },

    newScreen(suggest) {
        const name = suggest || (prompt('New screen name (letters, digits, _ -):') || '').trim();
        if (!name) return;
        if (this.dirty && !confirm(`Discard the unsaved changes of "${this.name}"?`)) return;
        const [w, h] = this._defaultSize();
        this._load(name, { title: name, width: w, height: h, bg: '', interval: 2, widgets: [
            { id: 'w1', type: 'label', x: 40, y: 30, w: Math.round(w * 0.6), h: 90, text: name, size: 56, color: 'accent', align: 'left', bold: true },
            { id: 'w2', type: 'clock', x: w - 360, y: 30, w: 320, h: 90, format: '%H:%M:%S', size: 56, color: 'text', align: 'right' },
        ] }, true);
    },

    saveAs() {
        const name = (prompt('Copy this screen as (new name):', this.name + '_copy') || '').trim();
        if (!name) return;
        this.name = name;
        this.save();
    },

    remove() {
        if (!this.screens.some(s => s.name === this.name)) { this.setDirty(false); return this.screens.length ? this.open(this.screens[0].name) : this.newScreen('main'); }
        if (!confirm(`Delete the screen "${this.name}"? (moved to UI/screens/.trash)`)) return;
        App.api(`/api/uiscreens/${encodeURIComponent(this.name)}/delete`, { method: 'POST' }).then(d => {
            this.screens = d.screens; this.setDirty(false);
            if (this.screens.length) this.open(this.screens[0].name); else this.newScreen('main');
            toast('Screen deleted');
        }).catch(e => toast(e.message, true));
    },

    save() {
        return App.api('/api/uiscreens/' + encodeURIComponent(this.name), { json: this.doc }).then(d => {
            this.screens = d.screens;
            const keepSel = this.sel;
            this.doc = d.screen;
            this.sel = this.doc.widgets.some(w => w.id === keepSel) ? keepSel : null;
            this.setDirty(false);
            this._screenList();
            this.render();
            toast(`Saved ${this.name}` + (this.display && this.display.script === `screens/${this.name}.json` ? ' — the device reloads it' : ''));
        }).catch(e => toast(e.message, true));
    },

    show() {
        this.stopPreviews();                    // free the camera for the device
        this.render();
        const go = () => App.api(`/api/uiscreens/${encodeURIComponent(this.name)}/show`, { method: 'POST' }).then(d => {
            this.display.settings = d.settings; this.display.script = d.settings.script;
            toast(`On the device: ${this.name}`);
        }).catch(e => toast(e.message, true));
        if (this.dirty || !this.screens.some(s => s.name === this.name)) this.save().then(go); else go();
    },

    setDirty(on) {
        this.dirty = on;
        this.$('ud-dirty').textContent = on ? 'unsaved' : '';
    },

    _snapshot() {
        this.undoStack.push(JSON.stringify(this.doc));
        if (this.undoStack.length > 60) this.undoStack.shift();
        this.setDirty(true);
    },

    undo() {
        const prev = this.undoStack.pop();
        if (!prev) return;
        this.doc = JSON.parse(prev);
        if (!this.doc.widgets.some(w => w.id === this.sel)) this.sel = null;
        this._docForm();
        this.setDirty(true);
        this.render();
        this.fit();
    },

    // ── Screen properties ──────────────────────────────────

    _bgOptions() {
        const s = this.display ? this.display.settings : {};
        const bgName = s.background ? `picture of Settings → Display (${s.background})` : 'Settings → Display (no picture)';
        this.$('ud-bg').innerHTML = `<option value="">${esc(bgName)}</option>` +
            this.meta.theme.map(t => `<option value="${t}">colour: ${t}</option>`).join('') + '<option value="#">colour: custom</option>';
    },

    _docForm() {
        const d = this.doc;
        this.$('ud-title').value = d.title || '';
        this.$('ud-w').value = d.width; this.$('ud-h').value = d.height;
        this.$('ud-int').value = d.interval;
        const custom = d.bg && d.bg.startsWith('#');
        this.$('ud-bg').value = custom ? '#' : (d.bg || '');
        this.$('ud-bgc').hidden = !custom;
        if (custom) this.$('ud-bgc').value = d.bg;
    },

    docInput() {
        this._snapshot();
        const d = this.doc, bg = this.$('ud-bg').value;
        d.title = this.$('ud-title').value;
        d.width = Math.max(160, parseInt(this.$('ud-w').value, 10) || d.width);
        d.height = Math.max(120, parseInt(this.$('ud-h').value, 10) || d.height);
        d.interval = Math.max(0.5, parseFloat(this.$('ud-int').value) || 2);
        this.$('ud-bgc').hidden = bg !== '#';
        d.bg = bg === '#' ? this.$('ud-bgc').value : bg;
        this.render();
        this.fit();
    },

    fitScreen() {
        const [w, h] = this._defaultSize();
        this.$('ud-w').value = w; this.$('ud-h').value = h;
        this.docInput();
    },

    // ── Widgets ────────────────────────────────────────────

    add(type) {
        if (!this.doc) return;
        this._snapshot();
        const props = this.meta.types[type], [w, h] = this.SIZES[type];
        const item = { id: this._newId(), type, x: Math.round((this.doc.width - w) / 2 / 10) * 10, y: Math.round((this.doc.height - h) / 2 / 10) * 10, w, h };
        props.forEach(([k, p]) => { item[k] = p[1]; });
        if (type === 'image' && this.images.length) item.file = this.images[0];
        this.doc.widgets.push(item);
        this.select(item.id);
    },

    _newId() {
        let n = this.doc.widgets.length + 1;
        while (this.doc.widgets.some(w => w.id === 'w' + n)) n++;
        return 'w' + n;
    },

    cur() { return this.doc && this.doc.widgets.find(w => w.id === this.sel); },

    select(id) { this.sel = id; this.render(); },

    duplicate() {
        const w = this.cur();
        if (!w) return;
        this._snapshot();
        const c = Object.assign({}, w, { id: this._newId(), x: w.x + 20, y: w.y + 20 });
        this.doc.widgets.push(c);
        this.select(c.id);
    },

    del() {
        if (!this.cur()) return;
        this._snapshot();
        this.doc.widgets = this.doc.widgets.filter(w => w.id !== this.sel);
        this.sel = null;
        this.render();
    },

    layer(dir) {
        const i = this.doc.widgets.findIndex(w => w.id === this.sel);
        if (i < 0) return;
        this._snapshot();
        const [w] = this.doc.widgets.splice(i, 1);
        if (dir === 'front') this.doc.widgets.push(w); else this.doc.widgets.unshift(w);
        this.render();
    },

    // ── Rendering ──────────────────────────────────────────

    color(v) {
        if (!v) return 'transparent';
        return v.startsWith('#') ? v : (this.meta.theme_hex[v] || '#dddddd');
    },

    fit() {
        if (!this.doc) return;
        const vp = this.$('ud-viewport'), st = this.$('ud-stage');
        const k = Math.min((vp.clientWidth - 30) / this.doc.width, (vp.clientHeight - 30) / this.doc.height);
        this.k = Math.max(0.05, k);
        st.style.width = this.doc.width + 'px';
        st.style.height = this.doc.height + 'px';
        st.style.transform = `translate(${(vp.clientWidth - this.doc.width * this.k) / 2}px, ${(vp.clientHeight - this.doc.height * this.k) / 2}px) scale(${this.k})`;
        this.$('ud-zoom').textContent = `${this.doc.width}×${this.doc.height} · ${Math.round(this.k * 100)} %`;
    },

    _stageBg() {
        const st = this.$('ud-stage'), d = this.doc, s = this.display ? this.display.settings : {};
        if (d.bg) {
            st.style.backgroundImage = '';
            st.style.backgroundColor = this.color(d.bg);
        } else if (s.background) {
            const dim = (s.bg_dim || 0) / 100;
            st.style.backgroundColor = this.meta.theme_hex.bg;
            st.style.backgroundImage = `linear-gradient(rgba(0,0,0,${dim}), rgba(0,0,0,${dim})), url("/api/display/background/${encodeURIComponent(s.background)}")`;
        } else {
            st.style.backgroundImage = '';
            st.style.backgroundColor = this.meta.theme_hex.bg;
        }
    },

    render() {
        if (!this.doc) return;
        this._stageBg();
        const panelAlpha = !this.doc.bg && this.display && this.display.settings.background;   // translucent like smms_ui
        const st = this.$('ud-stage'), keep = {};
        // a camera may be opened once: keep the running preview <img> (its stream) across re-renders
        st.querySelectorAll('img.ud-cam').forEach(img => { keep[img.closest('.ud-w').dataset.id] = img; });
        st.innerHTML = this.doc.widgets.map(w => this._widgetHtml(w, panelAlpha)).join('');
        Object.entries(keep).forEach(([id, img]) => {
            const ph = st.querySelector(`.ud-w[data-id="${CSS.escape(id)}"] img.ud-cam`);
            if (ph && ph.getAttribute('src') === img.getAttribute('src')) { img.style.cssText = ph.style.cssText; ph.replaceWith(img); }
        });
        this.$('ud-count').textContent = this.doc.widgets.length;
        this.$('ud-outline').innerHTML = this.doc.widgets.slice().reverse().map(w =>
            `<div class="${w.id === this.sel ? 'on' : ''}" data-id="${esc(w.id)}"><i class="fa-solid ${this.ICONS[w.type]}"></i> ${esc(w.id)} ` +
            `<span class="faint">${esc(this._caption(w))}</span></div>`).join('') || '<span class="hint">empty screen</span>';
        this.$('ud-outline').onclick = e => { const r = e.target.closest('[data-id]'); if (r) this.select(r.dataset.id); };
        this._props();
    },

    _caption(w) {
        return { label: w.text, value: `${w.source}.${w.path}`, bar: w.path, chart: w.path, image: w.file, button: w.text,
                 clock: w.format, camera: `${w.device} ${w.resolution}`, panel: '' }[w.type] || '';
    },

    _value(w) {
        const d = this.live[w.source];
        return d ? this.getPath(d, w.path) : undefined;
    },

    _widgetHtml(w, translucent) {
        const box = `left:${w.x}px;top:${w.y}px;width:${w.w}px;height:${w.h}px;`;
        const just = { left: 'flex-start', center: 'center', right: 'flex-end' }[w.align || 'left'];
        const txt = (s, extra = '') => `<div class="ud-txt" style="font-size:${w.size}px;color:${this.color(w.color)};justify-content:${just};` +
            `text-align:${w.align || 'left'};font-weight:${w.bold ? 700 : 400};${extra}">${esc(s)}</div>`;
        let inner = '', style = box;
        if (w.type === 'panel') {
            style += `background:${this.color(w.color)};border-radius:${w.radius}px;` + (translucent && ['panel', 'panel2'].includes(w.color) ? 'opacity:.8;' : '');
        } else if (w.type === 'label') {
            inner = txt(w.text);
        } else if (w.type === 'value') {
            const v = this._value(w);
            const n = parseFloat(v), warn = parseFloat(w.warn), crit = parseFloat(w.crit);
            const col = !isNaN(n) && !isNaN(crit) && n >= crit ? this.meta.theme_hex.danger : !isNaN(n) && !isNaN(warn) && n >= warn ? this.meta.theme_hex.warn : null;
            const sample = !this.$('ud-live').checked || !this.live[w.source];   // no data yet: a sample number
            inner = txt(`${w.prefix}${sample ? '123' : this.fmtValue(v, w.fmt)}${w.suffix}`, col ? `color:${col};` : '');
        } else if (w.type === 'clock') {
            inner = txt(this.strftime(w.format || '%H:%M:%S'));
        } else if (w.type === 'bar') {
            const v = parseFloat(this._value(w));
            const pct = isNaN(v) ? 60 : Math.max(0, Math.min(100, v * 100 / (w.max || 100)));
            inner = `<div class="ud-track"><div class="ud-fill" style="width:${pct}%;background:${this.color(w.color)}"></div></div>`;
        } else if (w.type === 'chart') {
            style += `background:${this.meta.theme_hex.panel2};`;
            inner = this._chartSvg(w);
        } else if (w.type === 'image') {
            inner = w.file ? `<img src="/api/uiscreens/image/${encodeURIComponent(w.file)}" style="object-fit:${{ contain: 'contain', cover: 'cover', stretch: 'fill' }[w.fit]}" alt="">`
                           : txt('no picture', 'justify-content:center;font-size:20px;');
        } else if (w.type === 'camera') {
            const bw = w.border_w, fit = { contain: 'contain', cover: 'cover', stretch: 'fill' }[w.fit];
            const tf = `${w.mirror ? 'scaleX(-1)' : ''} ${w.flip ? 'scaleY(-1)' : ''}`;
            style += `background:${this.meta.theme_hex.bg};border:${bw}px solid ${this.color(w.border)};border-radius:${w.radius}px;`;
            inner = this.preview[w.id]
                ? `<img class="ud-cam" src="${esc(this.preview[w.id])}" style="object-fit:${fit};transform:${tf}" alt="">`
                : `<div class="ud-txt" style="justify-content:center;flex-direction:column;font-size:${Math.max(14, w.h / 12)}px;color:${this.meta.theme_hex.dim}">` +
                  `<i class="fa-solid fa-video" style="font-size:2em"></i><span>${esc(w.device)} · ${esc(w.resolution)} · ${w.fps} fps</span></div>`;
            if (w.caption) inner += `<div class="ud-cap" style="font-size:${w.caption_size}px">${esc(w.caption)}</div>`;
        } else if (w.type === 'button') {
            style += `background:${this.color(w.bg)};`;
            inner = txt(w.text, 'justify-content:center;text-align:center;');
        }
        return `<div class="ud-w${w.id === this.sel ? ' sel' : ''}" data-id="${esc(w.id)}" style="${style}">${inner}<div class="ud-handle" data-h="1"></div></div>`;
    },

    _chartSvg(w) {
        const pts = this.hist[w.id] || [];
        const W = w.w, H = w.h;
        const top = w.ymax || Math.max(1, ...pts.map(p => p[1])) * 1.1;
        let line;
        if (pts.length > 1) {
            const now = pts[pts.length - 1][0];
            line = pts.filter(p => p[0] >= now - w.window).map(p => `${(W * (1 - (now - p[0]) / w.window)).toFixed(1)},${(H - H * Math.min(1, Math.max(0, p[1] / top))).toFixed(1)}`).join(' ');
        } else {
            line = Array.from({ length: 40 }, (_, i) => `${(W * i / 39).toFixed(1)},${(H * (0.5 - 0.3 * Math.sin(i / 5))).toFixed(1)}`).join(' ');
        }
        const grid = [1, 2, 3].map(i => `<line x1="0" x2="${W}" y1="${H * i / 4}" y2="${H * i / 4}" stroke="${this.meta.theme_hex.border}" stroke-width="2"/>`).join('');
        return `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">${grid}<polyline points="${line}" fill="none" stroke="${this.color(w.color)}" stroke-width="3" vector-effect="non-scaling-stroke"/></svg>`;
    },

    // ── Drag / resize ──────────────────────────────────────

    _wireStage() {
        const st = this.$('ud-stage');
        st.addEventListener('pointerdown', e => {
            const el = e.target.closest('.ud-w');
            if (!el) { if (e.target === st) { this.sel = null; this.render(); } return; }
            e.preventDefault();
            const id = el.dataset.id;
            if (this.sel !== id) { this.select(id); }
            const w = this.cur(), resize = !!e.target.closest('[data-h]');
            const sx = e.clientX, sy = e.clientY, o = { x: w.x, y: w.y, w: w.w, h: w.h };
            let moved = false;
            const snap = v => this.$('ud-snap').checked ? Math.round(v / 10) * 10 : Math.round(v);
            const move = ev => {
                const dx = (ev.clientX - sx) / this.k, dy = (ev.clientY - sy) / this.k;
                if (!moved && Math.abs(dx) + Math.abs(dy) < 2) return;
                if (!moved) { this._snapshot(); moved = true; }
                if (resize) { w.w = Math.max(10, snap(o.w + dx)); w.h = Math.max(10, snap(o.h + dy)); }
                else { w.x = snap(o.x + dx); w.y = snap(o.y + dy); }
                const node = st.querySelector(`.ud-w[data-id="${CSS.escape(id)}"]`);
                if (node) Object.assign(node.style, { left: w.x + 'px', top: w.y + 'px', width: w.w + 'px', height: w.h + 'px' });
            };
            const up = () => {
                window.removeEventListener('pointermove', move);
                window.removeEventListener('pointerup', up);
                if (moved) this.render();
            };
            window.addEventListener('pointermove', move);
            window.addEventListener('pointerup', up);
        });
    },

    _key(e) {
        const tag = (e.target.tagName || '').toLowerCase();
        const typing = ['input', 'textarea', 'select'].includes(tag);
        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') { e.preventDefault(); return this.save(); }
        if (typing) return;
        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') { e.preventDefault(); return this.undo(); }
        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'd') { e.preventDefault(); return this.duplicate(); }
        const w = this.cur();
        if (!w) return;
        if (e.key === 'Delete' || e.key === 'Backspace') { e.preventDefault(); return this.del(); }
        const step = e.shiftKey ? 10 : 1, mv = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] }[e.key];
        if (mv) { e.preventDefault(); this._snapshot(); w.x += mv[0]; w.y += mv[1]; this.render(); }
    },

    // ── Properties ─────────────────────────────────────────

    _props() {
        const w = this.cur(), box = this.$('ud-props');
        this.$('ud-props-title').textContent = w ? `${w.type} · ${w.id}` : 'Properties';
        if (!w) { box.innerHTML = '<div class="hint">Select a widget, or add one on the left.</div>'; return; }
        const props = this.meta.types[w.type];
        let h = `<div class="ud-xy">${['x', 'y', 'w', 'h'].map(k => `<div class="field"><label>${k}</label><input class="input input-sm" type="number" data-k="${k}" value="${w[k]}"></div>`).join('')}</div>`;
        props.forEach(([k, p]) => { h += this._field(w, k, p); });
        if (w.type === 'camera') {
            h += `<div class="row"><button class="btn btn-ghost btn-sm" onclick="UIDesign.camPreview()" title="Live picture in the editor (through the panel's video stream). A camera can be read by one program at a time — stop the preview before showing the screen on the device.">` +
                 `<i class="fa-solid ${this.preview[w.id] ? 'fa-stop' : 'fa-play'}"></i> ${this.preview[w.id] ? 'stop preview' : 'preview'}</button></div>`;
        }
        h += `<div class="row"><button class="btn btn-ghost btn-sm" onclick="UIDesign.layer('front')" title="Bring to front"><i class="fa-solid fa-arrow-up"></i> front</button>` +
             `<button class="btn btn-ghost btn-sm" onclick="UIDesign.layer('back')" title="Send to back"><i class="fa-solid fa-arrow-down"></i> back</button>` +
             `<button class="btn btn-ghost btn-sm" onclick="UIDesign.duplicate()"><i class="fa-regular fa-copy"></i> copy</button>` +
             `<button class="btn btn-danger btn-sm" onclick="UIDesign.del()"><i class="fa-regular fa-trash-can"></i></button></div>`;
        box.innerHTML = h;
        box.oninput = e => this._propInput(e);
        box.onchange = e => this._propInput(e, true);
    },

    _field(w, k, p) {
        const kind = p[0], v = w[k];
        const lab = { border_w: 'border width, px', caption_size: 'caption size', fps: 'frames / s', mirror: 'mirror (left ↔ right)',
                      flip: 'upside down', device: 'video device', fmt: 'format', ymax: 'y max (0 = auto)', window: 'window, s', warn: 'warn from', crit: 'critical from',
                      body: 'JSON body (optional)', target: { screen: 'screen', post: 'API path (POST)', test_start: 'test script' }[w.action] || 'target' }[k] || k;
        if (k === 'target' && !['screen', 'post', 'test_start'].includes(w.action)) return '';
        if (k === 'body' && !['post', 'test_start'].includes(w.action)) return '';
        let input;
        if (kind === 'enum') {
            input = `<select class="input input-sm" data-k="${k}">${p[2].map(o => `<option${o === v ? ' selected' : ''}>${esc(o)}</option>`).join('')}</select>`;
        } else if (kind === 'bool') {
            return `<label class="check-row small"><input type="checkbox" data-k="${k}"${v ? ' checked' : ''}> ${esc(lab)}</label>`;
        } else if (kind === 'color') {
            const custom = v && v.startsWith('#');
            input = `<div class="ud-colrow"><select class="input input-sm" data-k="${k}" data-color="1">` +
                this.meta.theme.map(t => `<option value="${t}"${t === v ? ' selected' : ''}>${t}</option>`).join('') +
                `<option value="#"${custom ? ' selected' : ''}>custom…</option></select>` +
                `<input type="color" class="ud-color" data-k="${k}" data-pick="1" value="${custom ? v : this.color(v)}"></div>`;
        } else if (kind === 'path') {
            const src = (this.meta.sources[w.source] || { paths: [] }).paths;
            input = `<input class="input input-sm mono" data-k="${k}" list="ud-paths-${esc(w.id)}" value="${esc(v)}">` +
                `<datalist id="ud-paths-${esc(w.id)}">${src.map(o => `<option value="${esc(o)}">`).join('')}</datalist>`;
        } else if (kind === 'device') {
            if (!this.cams) { this.cams = []; App.api('/api/video_devices').then(d => { this.cams = d.devices; this._props(); }).catch(() => {}); }
            const list = this.cams.some(c => c.path === v) ? this.cams : [{ path: v, label: v + ' (not found)' }].concat(this.cams);
            input = `<select class="input input-sm" data-k="${k}">${list.map(c => `<option value="${esc(c.path)}"${c.path === v ? ' selected' : ''}>${esc(c.label)}</option>`).join('')}</select>`;
        } else if (kind === 'size') {
            const dev = w.device;
            if (!this.camRes[dev]) { this.camRes[dev] = []; App.api('/api/video_resolutions?device=' + encodeURIComponent(dev)).then(d => { this.camRes[dev] = d.resolutions; this._props(); }).catch(() => {}); }
            input = `<input class="input input-sm mono" data-k="${k}" list="ud-res-${esc(w.id)}" value="${esc(v)}" placeholder="640x480">` +
                `<datalist id="ud-res-${esc(w.id)}">${this.camRes[dev].map(r => `<option value="${esc(r)}">`).join('')}</datalist>`;
        } else if (kind === 'image') {
            input = `<select class="input input-sm" data-k="${k}"><option value="">— none —</option>${this.images.map(o => `<option${o === v ? ' selected' : ''}>${esc(o)}</option>`).join('')}</select>` +
                    '<span class="hint">pictures of UI/images/</span>';
        } else if (k === 'target' && w.action === 'screen') {
            input = `<select class="input input-sm" data-k="${k}"><option value=""></option>${this.screens.map(s => `<option${s.name === v ? ' selected' : ''}>${esc(s.name)}</option>`).join('')}</select>`;
        } else if (k === 'target' && w.action === 'test_start') {
            if (!this.tests) { this.tests = []; App.api('/api/tests/scripts').then(d => { this.tests = d.scripts.map(s => s.name); this._props(); }).catch(() => {}); }
            input = `<select class="input input-sm" data-k="${k}"><option value=""></option>${this.tests.map(s => `<option${s === v ? ' selected' : ''}>${esc(s)}</option>`).join('')}</select>`;
        } else if (k === 'body' || (k === 'text' && w.type === 'label')) {
            input = `<textarea class="input input-sm mono" data-k="${k}">${esc(v)}</textarea>`;
        } else {
            const num = kind === 'int' || kind === 'float';
            input = `<input class="input input-sm" ${num ? 'type="number" step="any"' : ''} data-k="${k}" value="${esc(v)}">`;
        }
        return `<div class="field"><label>${esc(lab)}</label>${input}</div>`;
    },

    _propInput(e, committed) {
        const el = e.target, k = el.dataset.k, w = this.cur();
        if (!k || !w) return;
        if (!this._editing) { this._snapshot(); this._editing = true; }
        let v;
        if (el.type === 'checkbox') v = el.checked;
        else if (el.dataset.pick) v = el.value;
        else if (el.dataset.color) v = el.value === '#' ? (el.parentNode.querySelector('[data-pick]').value) : el.value;
        else if (el.type === 'number') v = parseFloat(el.value);
        else v = el.value;
        if (el.type === 'number' && isNaN(v)) return;
        w[k] = ['x', 'y', 'w', 'h'].includes(k) ? Math.round(v) : v;
        if (w.type === 'camera') {                  // re-render keeps the preview stream; a new device / size restarts it
            if ((k === 'device' || k === 'resolution') && this.preview[w.id] && committed) { this.camPreview(); this.camPreview(); }
            if (committed || el.tagName === 'SELECT' || el.type === 'checkbox') this._editing = false;
            return this.render();
        }
        const node = this.$('ud-stage').querySelector(`.ud-w[data-id="${CSS.escape(w.id)}"]`);
        if (node) node.outerHTML = this._widgetHtml(w, !this.doc.bg && this.display && this.display.settings.background);
        if (committed || el.tagName === 'SELECT' || el.type === 'checkbox') { this._editing = false; this.render(); }
    },

    /** Toggle the live picture of the selected camera widget (MJPEG of /api/video_feed, stopped explicitly). */
    camPreview() {
        const w = this.cur();
        if (!w || w.type !== 'camera') return;
        const sid = 'uid-' + w.id;
        if (this.preview[w.id]) {
            delete this.preview[w.id];
            App.api('/api/video_stop', { json: { stream_id: sid } }).catch(() => {});
        } else {
            this.preview[w.id] = `/api/video_feed?device=${encodeURIComponent(w.device)}&size=${encodeURIComponent(w.resolution)}&sid=${sid}&t=${Date.now()}`;
        }
        this.render();
    },

    stopPreviews() {
        Object.keys(this.preview).forEach(id => navigator.sendBeacon('/api/video_stop', new Blob([JSON.stringify({ stream_id: 'uid-' + id })], { type: 'application/json' })));
        this.preview = {};
    },

    // ── Live data ──────────────────────────────────────────

    liveToggle() {
        clearInterval(this.liveTimer);
        this.liveTimer = null;
        if (!this.$('ud-live').checked) { this.live = {}; this.render(); return; }
        this._poll();
        this.liveTimer = setInterval(() => this._poll(), 2000);
    },

    _poll() {
        if (!this.doc) return;
        const used = new Set(this.doc.widgets.filter(w => ['value', 'bar', 'chart'].includes(w.type)).map(w => w.source));
        const urls = { monitor: () => '/api/monitor?since=' + this.lastT, tests: () => '/api/tests/status?results_from=999999&output_from=999999999' };
        [...used].filter(s => urls[s]).forEach(src => App.api(urls[src]()).then(d => {
            if (src === 'monitor') { if (d.history && d.history.length) this.lastT = d.history[d.history.length - 1][0]; }
            this.live[src] = d;
            const now = Date.now() / 1000;
            this.doc.widgets.filter(w => w.type === 'chart' && w.source === src).forEach(w => {
                const v = parseFloat(this.getPath(d, w.path));
                if (isNaN(v)) return;
                const h = this.hist[w.id] || (this.hist[w.id] = []);
                h.push([now, v]);
                if (h.length > 2000) h.splice(0, h.length - 2000);
            });
            if (!this._dragging) this._refreshLive();
        }).catch(() => {}));
    },

    _refreshLive() {
        const st = this.$('ud-stage'), tr = !this.doc.bg && this.display && this.display.settings.background;
        this.doc.widgets.filter(w => ['value', 'bar', 'chart', 'clock'].includes(w.type)).forEach(w => {
            const node = st.querySelector(`.ud-w[data-id="${CSS.escape(w.id)}"]`);
            if (node) node.outerHTML = this._widgetHtml(w, tr);
        });
    },

    // ── Formatting (same as UI/screen_runner.py fmt) ───────

    getPath(d, path) {
        let cur = d;
        for (const part of (path || '').split('.')) {
            if (part === '') continue;
            if (cur === null || cur === undefined) return undefined;
            cur = Array.isArray(cur) ? cur[parseInt(part, 10)] : cur[part];
        }
        return cur === null ? undefined : cur;
    },

    fmtBytes(n) {
        const units = ['B', 'KB', 'MB', 'GB', 'TB'];
        let i = 0;
        while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
        return i ? `${n.toFixed(1)} ${units[i]}` : `${n.toFixed(0)} B`;
    },

    fmtValue(v, kind) {
        if (v === undefined || v === null) return '—';
        if (typeof v === 'object') return JSON.stringify(v).slice(0, 60);
        const n = parseFloat(v);
        if (isNaN(n)) return String(v);
        switch (kind) {
            case 'int': return n.toFixed(0);
            case '1dp': return n.toFixed(1);
            case '2dp': return n.toFixed(2);
            case 'percent': return `${n.toFixed(0)} %`;
            case 'bytes': return this.fmtBytes(n);
            case 'rate': return this.fmtBytes(n) + '/s';
            case 'uptime': {
                const s = Math.floor(n), d = Math.floor(s / 86400), h = Math.floor(s / 3600) % 24, m = Math.floor(s / 60) % 60;
                return d ? `${d}d ${h}h ${m}m` : `${h}h ${m}m`;
            }
            default: return String(v);
        }
    },

    strftime(f) {
        const d = new Date(), p = n => String(n).padStart(2, '0');
        return f.replace(/%([HMSdmYy%])/g, (_, c) => ({ H: p(d.getHours()), M: p(d.getMinutes()), S: p(d.getSeconds()), d: p(d.getDate()),
            m: p(d.getMonth() + 1), Y: d.getFullYear(), y: p(d.getFullYear() % 100), '%': '%' })[c]);
    },
};

UIDesign.init();
setInterval(() => { if (UIDesign.doc && UIDesign.doc.widgets.some(w => w.type === 'clock')) UIDesign._refreshLive(); }, 1000);
