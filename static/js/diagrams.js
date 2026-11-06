/* ==========================================================================
   Diagram editor inside the Docs page (templates/help.html, #dg-pane): pinouts and block diagrams.
   Model and SVG output: static/js/diagram_render.js. Files: help_dir/diagrams/<name>.json + <name>.svg
   (the .svg is exported on every save and embedded into pages as ../diagrams/<name>.svg).
   ========================================================================== */

const Diagrams = {
    list: [],
    name: null, doc: null, mtime: null, usedBy: [],
    dirty: false,
    sel: [],                      // selected item ids
    tool: 'select',
    view: { x: 0, y: 0, k: 1 },   // viewBox origin (diagram units) and zoom (px per unit)
    showGrid: true,
    undoStack: [], redoStack: [],
    clip: null,
    drag: null,
    _raf: 0,
    _space: false,
    pinSide: 'left',
    PIN_FIELDS: ['n', 'port', 'fn', 'kind', 'badge', 'note'],

    $(id) { return document.getElementById(id); },
    R: DiagramRender,

    init() {
        const svg = this.$('dg-svg');
        svg.addEventListener('mousedown', e => this._down(e));
        window.addEventListener('mousemove', e => this._move(e));
        window.addEventListener('mouseup', e => this._up(e));
        svg.addEventListener('dblclick', e => this._dbl(e));
        svg.addEventListener('wheel', e => this._wheel(e), { passive: false });
        svg.addEventListener('contextmenu', e => e.preventDefault());
        new ResizeObserver(() => this._viewBox()).observe(this.$('dg-canvas'));
        document.addEventListener('keydown', e => this._keys(e));
        document.addEventListener('keyup', e => { if (e.code === 'Space') { this._space = false; this._cursor(); } });
        const props = this.$('dg-props');
        props.addEventListener('focusin', () => { this._propUndo = false; });
        props.addEventListener('input', e => this._propInput(e));
        props.addEventListener('change', e => this._propInput(e, true));
        props.addEventListener('click', e => this._propClick(e));
        const pins = this.$('dg-pins-body');
        pins.addEventListener('focusin', () => { this._propUndo = false; });
        pins.addEventListener('input', e => this._pinInput(e));
        pins.addEventListener('change', e => this._pinInput(e));
        pins.addEventListener('click', e => this._pinClick(e));
        pins.addEventListener('paste', e => this._pinPaste(e));
        App.onEscape(() => {
            if (this.$('dg-pins-overlay').classList.contains('open')) return this.closePins();
            if (this.$('dg-new-overlay').classList.contains('open')) return this.closeNew();
        });
        this.loadList();
    },

    isOpen() { return !!this.doc; },

    loadList() {
        return App.api('/api/help/diagrams').then(d => {
            this.list = d.items;
            if (!Help._query) Help.renderTree();
        }).catch(e => toast(e.message, true));
    },

    confirmLeave() { return !this.dirty || confirm('Discard unsaved diagram changes?'); },

    // ── Open / close ───────────────────────────────────────────

    open(name, push = true) {
        if (this.doc && name !== this.name && !this.confirmLeave()) return Promise.resolve(false);
        return App.api('/api/help/diagram?name=' + encodeURIComponent(name)).then(d => {
            this.name = d.name; this.mtime = d.mtime; this.usedBy = d.used_by || [];
            this.doc = this._normalize(d.data);
            this.dirty = false; this.sel = []; this.undoStack = []; this.redoStack = []; this.tool = 'select';
            if (push) history.pushState(null, '', '/help?diagram=' + encodeURIComponent(d.name));
            this._show(true);
            requestAnimationFrame(() => { this.fit(); this.render(); this.renderProps(); });
            document.querySelectorAll('.hp-doc').forEach(el => el.classList.toggle('active', el.dataset.diagram === d.name));
            return true;
        }).catch(e => { toast(e.message, true); return false; });
    },

    _normalize(data) {
        const doc = Object.assign(DiagramRender.newDoc(), data || {});
        doc.kinds = Object.assign({}, doc.kinds || {});
        if (!doc.kinds.free) doc.kinds.free = Object.assign({}, DiagramRender.DEFAULT_KINDS.free);
        doc.items = (doc.items || []).map(i => Object.assign({ id: this._id(i.type || 'x') }, i));
        return doc;
    },

    _show(on) {
        this.$('dg-pane').hidden = !on;
        ['hp-bar', 'hp-toolbar', 'hp-body'].forEach(id => this.$(id).classList.toggle('dg-hidden', on));
        if (on) this._bar();
    },

    /** Leave the diagram editor (asks about unsaved changes). Returns false when the user stays. */
    close(goBack = true) {
        if (!this.doc) return true;
        if (!this.confirmLeave()) return false;
        this.doc = null; this.name = null; this.dirty = false; this.sel = [];
        this._show(false);
        if (goBack) {
            if (Help.current) {
                history.pushState(null, '', '/help?doc=' + encodeURIComponent(Help.current.path));
                Help.showView();
            } else {
                history.pushState(null, '', '/help');
                Help._fromUrl(true);
            }
        }
        document.querySelectorAll('.hp-doc[data-diagram]').forEach(el => el.classList.remove('active'));
        return true;
    },

    _bar() {
        this.$('dg-title').textContent = this.doc ? (this.doc.title || this.name) : '';
        this.$('dg-name').textContent = this.name ? `diagrams/${this.name}.json` : '';
        this.$('dg-dirty').hidden = !this.dirty;
        document.querySelectorAll('#dg-tools button').forEach(b => b.classList.toggle('active', b.dataset.tool === this.tool));
        this.$('dg-zoom').textContent = Math.round(this.view.k * 100) + '%';
        this.$('dg-grid-btn').classList.toggle('active', this.showGrid);
        this.$('dg-undo').disabled = !this.undoStack.length;
        this.$('dg-redo').disabled = !this.redoStack.length;
        this.$('dg-used').textContent = this.usedBy.length ? `used in ${this.usedBy.length} doc(s)` : 'not used in docs';
        this.$('dg-used').title = this.usedBy.join('\n');
    },

    markDirty() {
        if (!this.dirty) { this.dirty = true; }
        this._bar();
    },

    // ── Undo ───────────────────────────────────────────────────

    snapshot() {
        this.undoStack.push(JSON.stringify(this.doc));
        if (this.undoStack.length > 150) this.undoStack.shift();
        this.redoStack = [];
    },

    undo() {
        if (!this.undoStack.length) return;
        this.redoStack.push(JSON.stringify(this.doc));
        this.doc = JSON.parse(this.undoStack.pop());
        this._afterHistory();
    },

    redo() {
        if (!this.redoStack.length) return;
        this.undoStack.push(JSON.stringify(this.doc));
        this.doc = JSON.parse(this.redoStack.pop());
        this._afterHistory();
    },

    _afterHistory() {
        this.sel = this.sel.filter(id => this.R.byId(this.doc, id));
        this.markDirty();
        this.render(); this.renderProps(); this._refreshPins();
    },

    // ── View ───────────────────────────────────────────────────

    _viewBox() {
        if (!this.doc) return;
        const c = this.$('dg-canvas'), k = this.view.k;
        this.$('dg-svg').setAttribute('viewBox', `${this.view.x} ${this.view.y} ${c.clientWidth / k} ${c.clientHeight / k}`);
        const g = this.doc.grid || 10, step = g * k >= 8 ? g : g * 5;
        const pat = this.$('dg-grid');
        pat.setAttribute('width', step); pat.setAttribute('height', step);
        pat.firstElementChild.setAttribute('d', `M ${step} 0 L 0 0 0 ${step}`);
        this.$('dg-zoom').textContent = Math.round(k * 100) + '%';
        if (this.sel.length) this.renderOverlay();
    },

    fit() {
        const c = this.$('dg-canvas');
        if (!this.doc || !c.clientWidth) return;
        const W = this.doc.width, H = this.doc.height;
        const k = Math.max(0.05, Math.min(4, Math.min((c.clientWidth - 40) / W, (c.clientHeight - 40) / H)));
        this.view = { k, x: -(c.clientWidth / k - W) / 2, y: -(c.clientHeight / k - H) / 2 };
        this._viewBox();
    },

    zoom(f, cx, cy) {
        const c = this.$('dg-canvas');
        if (cx == null) { cx = c.clientWidth / 2; cy = c.clientHeight / 2; }
        const k0 = this.view.k, k = Math.max(0.05, Math.min(6, k0 * f));
        const px = this.view.x + cx / k0, py = this.view.y + cy / k0;
        this.view = { k, x: px - cx / k, y: py - cy / k };
        this._viewBox();
    },

    zoom100() { this.zoom(1 / this.view.k); },

    toggleGrid() { this.showGrid = !this.showGrid; this.render(); this._bar(); },

    _pt(e) {
        const r = this.$('dg-canvas').getBoundingClientRect();
        return { x: this.view.x + (e.clientX - r.left) / this.view.k, y: this.view.y + (e.clientY - r.top) / this.view.k };
    },

    _snap(v, e) {
        const g = this.doc.grid || 10;
        return e && e.altKey ? Math.round(v) : Math.round(v / g) * g;
    },

    _wheel(e) {
        if (!this.doc) return;
        e.preventDefault();
        const r = this.$('dg-canvas').getBoundingClientRect();
        if (e.ctrlKey || !e.shiftKey) this.zoom(e.deltaY < 0 ? 1.15 : 1 / 1.15, e.clientX - r.left, e.clientY - r.top);
        else { this.view.x += e.deltaY / this.view.k; this._viewBox(); }
    },

    // ── Render ─────────────────────────────────────────────────

    render() {
        if (!this.doc) return;
        const d = this.doc;
        const page = this.$('dg-page');
        page.setAttribute('width', d.width); page.setAttribute('height', d.height);
        page.setAttribute('fill', d.background || '#ffffff');
        const grid = this.$('dg-page-grid');
        grid.setAttribute('width', d.width); grid.setAttribute('height', d.height);
        grid.style.display = this.showGrid ? '' : 'none';
        this.$('dg-content').innerHTML = this.R.renderItems(d, { editor: true });
        this._viewBox();
        this.renderOverlay();
    },

    _schedule() {
        if (this._raf) return;
        this._raf = requestAnimationFrame(() => { this._raf = 0; this.render(); });
    },

    _box(it) {
        if (it.w != null) return { x: it.x, y: it.y, w: it.w, h: it.h };
        const g = this.$('dg-content').querySelector(`[data-id="${CSS.escape(it.id)}"]`);
        if (!g) return null;
        const b = g.getBBox();
        return { x: b.x, y: b.y, w: b.width, h: b.height };
    },

    renderOverlay() {
        const ov = this.$('dg-overlay');
        if (!this.doc) { ov.innerHTML = ''; return; }
        const k = this.view.k, hs = 9 / k, out = [];
        const single = this.sel.length === 1;
        for (const id of this.sel) {
            const it = this.R.byId(this.doc, id);
            if (!it) continue;
            if (it.type === 'wire') {
                const pts = this.R.wirePoints(this.doc, it);
                out.push(`<path d="M${pts.map(p => `${p.x},${p.y}`).join(' L')}" class="dg-sel-wire"/>`);
                if (single) {
                    const a = pts[0], b = pts[pts.length - 1];
                    out.push(`<circle cx="${a.x}" cy="${a.y}" r="${hs * 0.6}" class="dg-h dg-h-end${it.from.id ? ' on' : ''}" data-h="from"/>`);
                    out.push(`<circle cx="${b.x}" cy="${b.y}" r="${hs * 0.6}" class="dg-h dg-h-end${it.to.id ? ' on' : ''}" data-h="to"/>`);
                    (it.via || []).forEach(([x, y], i) =>
                        out.push(`<rect x="${x - hs / 2}" y="${y - hs / 2}" width="${hs}" height="${hs}" class="dg-h dg-h-via" data-h="via:${i}"/>`));
                }
                continue;
            }
            const b = this._box(it);
            if (!b) continue;
            out.push(`<rect x="${b.x}" y="${b.y}" width="${b.w}" height="${b.h}" class="dg-sel"/>`);
            if (single && it.w != null) {
                const hx = { w: b.x, c: b.x + b.w / 2, e: b.x + b.w }, hy = { n: b.y, m: b.y + b.h / 2, s: b.y + b.h };
                for (const [name, x, y] of [['nw', hx.w, hy.n], ['n', hx.c, hy.n], ['ne', hx.e, hy.n], ['e', hx.e, hy.m],
                                            ['se', hx.e, hy.s], ['s', hx.c, hy.s], ['sw', hx.w, hy.s], ['w', hx.w, hy.m]]) {
                    out.push(`<rect x="${x - hs / 2}" y="${y - hs / 2}" width="${hs}" height="${hs}" class="dg-h dg-h-${name}" data-h="resize:${name}"/>`);
                }
            }
        }
        const dr = this.drag;
        if (dr && dr.type === 'marquee') {
            const x = Math.min(dr.x0, dr.x1), y = Math.min(dr.y0, dr.y1);
            out.push(`<rect x="${x}" y="${y}" width="${Math.abs(dr.x1 - dr.x0)}" height="${Math.abs(dr.y1 - dr.y0)}" class="dg-marquee"/>`);
        }
        if (dr && dr.type === 'create') {
            const r = this._rectOf(dr);
            out.push(`<rect x="${r.x}" y="${r.y}" width="${r.w}" height="${r.h}" class="dg-marquee"/>`);
        }
        if (dr && dr.hover) {
            const b = dr.hover;
            out.push(`<rect x="${b.x}" y="${b.y}" width="${b.w}" height="${b.h}" class="dg-hover"/>`);
            if (dr.hoverPt) out.push(`<circle cx="${dr.hoverPt.x}" cy="${dr.hoverPt.y}" r="${hs * 0.7}" class="dg-anchor"/>`);
        }
        ov.innerHTML = out.join('');
    },

    _cursor() {
        const svg = this.$('dg-svg');
        svg.style.cursor = this._space || (this.drag && this.drag.type === 'pan') ? 'grab'
            : this.tool === 'select' ? 'default' : 'crosshair';
    },

    // ── Tools / creation ───────────────────────────────────────

    setTool(t) {
        this.tool = t;
        this._bar();
        this._cursor();
    },

    _id(type) {
        let id;
        do { id = (type || 'x')[0] + Math.random().toString(36).slice(2, 8); } while (this.doc && this.R.byId(this.doc, id));
        return id;
    },

    _add(item, select = true) {
        item.id = item.id || this._id(item.type);
        this.doc.items.push(item);
        if (select) this.sel = [item.id];
        return item;
    },

    _newItem(type, p) {
        const s = v => this._snap(v);
        switch (type) {
            case 'block': return { type, x: s(p.x), y: s(p.y), w: 260, h: 90, title: 'Block', lines: ['description'], style: 'light' };
            case 'text': return { type, x: s(p.x), y: s(p.y), text: 'Text', size: 16, color: '#1f2937' };
            case 'legend': return { type, x: s(p.x), y: s(p.y), kinds: null, style: 'tags' };
            case 'chip': {
                const pins = {};
                const mk = (side, n0, count) => Array.from({ length: count }, (_, i) =>
                    ({ n: n0 + i, port: `P${side[0].toUpperCase()}${i}`, fn: '', kind: 'free', badge: '', note: '' }));
                pins.left = mk('left', 1, 8); pins.bottom = mk('bottom', 9, 8);
                pins.right = mk('right', 17, 8).reverse(); pins.top = mk('top', 25, 8).reverse();
                return { type, x: s(p.x), y: s(p.y), w: 600, h: 560, body: 'module', holes: true,
                         ic: { show: true, title: 'MCU', subtitle: 'part number' }, caption: 'Module · U1', caption2: '',
                         pinStyle: 'tags', corner: 90, portW: 66, fnW: 128, numbers: true, pins };
            }
        }
    },

    _rectOf(dr) {
        return { x: Math.min(dr.x0, dr.x1), y: Math.min(dr.y0, dr.y1), w: Math.abs(dr.x1 - dr.x0), h: Math.abs(dr.y1 - dr.y0) };
    },

    /** Block or chip under a point (topmost), ignoring ids in `skip`. */
    _boxAt(p, skip = []) {
        const m = 6 / this.view.k;
        for (let i = this.doc.items.length - 1; i >= 0; i--) {
            const it = this.doc.items[i];
            if (it.w == null || skip.includes(it.id)) continue;
            if (p.x >= it.x - m && p.x <= it.x + it.w + m && p.y >= it.y - m && p.y <= it.y + it.h + m) return it;
        }
        return null;
    },

    _endAt(p, e, skip) {
        const box = this._boxAt(p, skip);
        if (box && !(e && e.altKey)) {
            const ns = this.R.nearestSide(box, p);
            // snap the position along the side to the grid
            const g = this.doc.grid || 10, len = ns.side === 'left' || ns.side === 'right' ? box.h : box.w;
            const off = ns.side === 'left' || ns.side === 'right' ? box.y : box.x;
            ns.t = Math.max(0, Math.min(1, (Math.round((off + ns.t * len) / g) * g - off) / len));
            ns.t = Math.round(ns.t * 1000) / 1000;
            return { end: { id: box.id, side: ns.side, t: ns.t }, box };
        }
        return { end: { x: this._snap(p.x, e), y: this._snap(p.y, e) }, box: null };
    },

    // ── Mouse ──────────────────────────────────────────────────

    _down(e) {
        if (!this.doc) return;
        const p = this._pt(e);
        if (e.button === 1 || e.button === 2 || this._space) {
            e.preventDefault();
            this.drag = { type: 'pan', sx: e.clientX, sy: e.clientY, vx: this.view.x, vy: this.view.y };
            this._cursor();
            return;
        }
        if (e.button !== 0) return;
        if (document.activeElement && document.activeElement.blur) document.activeElement.blur();
        const h = e.target.closest('[data-h]');
        const hitEl = e.target.closest('#dg-content [data-id]');
        const hit = hitEl ? this.R.byId(this.doc, hitEl.dataset.id) : null;

        if (h && this.tool === 'select') {
            const it = this.R.byId(this.doc, this.sel[0]);
            const [kind, arg] = h.dataset.h.split(':');
            this.snapshot();
            if (kind === 'resize') this.drag = { type: 'resize', id: it.id, dir: arg, orig: { x: it.x, y: it.y, w: it.w, h: it.h }, p0: p };
            else if (kind === 'via') this.drag = { type: 'via', id: it.id, i: +arg };
            else this.drag = { type: 'end', id: it.id, which: kind };
            return;
        }

        if (this.tool === 'wire') {
            this.snapshot();
            this.sel = [];
            const { end } = this._endAt(p, e, []);
            const w = this._add({ type: 'wire', from: end, to: { x: end.x != null ? end.x : p.x, y: end.y != null ? end.y : p.y },
                                  route: 'ortho', arrow: 'end', label: '' });
            this.drag = { type: 'end', id: w.id, which: 'to', creating: true, p0: p };
            this.render();
            return;
        }
        if (this.tool === 'block') {
            this.drag = { type: 'create', x0: this._snap(p.x, e), y0: this._snap(p.y, e), x1: this._snap(p.x, e), y1: this._snap(p.y, e) };
            return;
        }
        if (['chip', 'text', 'legend'].includes(this.tool)) {
            this.snapshot();
            this._add(this._newItem(this.tool, p));
            this.setTool('select');
            this.markDirty(); this.render(); this.renderProps();
            return;
        }

        // select tool
        if (hit) {
            if (e.shiftKey) {
                this.sel = this.sel.includes(hit.id) ? this.sel.filter(i => i !== hit.id) : [...this.sel, hit.id];
            } else if (!this.sel.includes(hit.id)) {
                this.sel = [hit.id];
            }
            this.renderOverlay(); this.renderProps();
            if (!this.sel.includes(hit.id)) return;
            if (hit.type === 'wire' && e.target.closest('.dg-wire-label') && this.sel.length === 1) {
                this.drag = { type: 'label', id: hit.id, p0: p, dx: hit.labelDx || 0, dy: hit.labelDy || 0, moved: false };
                return;
            }
            this.drag = { type: 'move', p0: p, moved: false, orig: this._origOf(this.sel) };
            return;
        }
        if (!e.shiftKey) { this.sel = []; this.renderProps(); }
        this.drag = { type: 'marquee', x0: p.x, y0: p.y, x1: p.x, y1: p.y, add: e.shiftKey ? [...this.sel] : [] };
        this.renderOverlay();
    },

    _origOf(ids) {
        const o = {};
        for (const id of ids) {
            const it = this.R.byId(this.doc, id);
            if (!it) continue;
            o[id] = it.type === 'wire'
                ? { from: Object.assign({}, it.from), to: Object.assign({}, it.to), via: (it.via || []).map(v => v.slice()) }
                : { x: it.x, y: it.y };
        }
        return o;
    },

    _move(e) {
        const dr = this.drag;
        if (!dr || !this.doc) return;
        if (dr.type === 'pan') {
            this.view.x = dr.vx - (e.clientX - dr.sx) / this.view.k;
            this.view.y = dr.vy - (e.clientY - dr.sy) / this.view.k;
            this._viewBox();
            return;
        }
        const p = this._pt(e);
        if (dr.type === 'marquee') {
            dr.x1 = p.x; dr.y1 = p.y;
            const r = this._rectOf(dr);
            const inside = this.doc.items.filter(it => {
                const b = it.type === 'wire' ? this._wireBox(it) : this._box(it);
                return b && b.x >= r.x && b.y >= r.y && b.x + b.w <= r.x + r.w && b.y + b.h <= r.y + r.h;
            }).map(i => i.id);
            this.sel = [...new Set([...dr.add, ...inside])];
            this.renderOverlay();
            return;
        }
        if (dr.type === 'create') {
            dr.x1 = this._snap(p.x, e); dr.y1 = this._snap(p.y, e);
            this.renderOverlay();
            return;
        }
        if (dr.type === 'move') {
            const g = this.doc.grid || 10;
            let dx = p.x - dr.p0.x, dy = p.y - dr.p0.y;
            if (!e.altKey) { dx = Math.round(dx / g) * g; dy = Math.round(dy / g) * g; }
            if (!dr.moved) {
                if (Math.hypot(p.x - dr.p0.x, p.y - dr.p0.y) * this.view.k < 3) return;
                this.snapshot(); dr.moved = true;
            }
            for (const [id, o] of Object.entries(dr.orig)) {
                const it = this.R.byId(this.doc, id);
                if (it.type === 'wire') {
                    if (!it.from.id) it.from = { x: o.from.x + dx, y: o.from.y + dy };
                    if (!it.to.id) it.to = { x: o.to.x + dx, y: o.to.y + dy };
                    if (o.via.length) it.via = o.via.map(([x, y]) => [x + dx, y + dy]);
                } else { it.x = o.x + dx; it.y = o.y + dy; }
            }
            this._schedule();
            return;
        }
        if (dr.type === 'resize') {
            const it = this.R.byId(this.doc, dr.id), o = dr.orig, s = v => this._snap(v, e);
            let x0 = o.x, y0 = o.y, x1 = o.x + o.w, y1 = o.y + o.h;
            if (dr.dir.includes('w')) x0 = Math.min(s(p.x), x1 - 40);
            if (dr.dir.includes('e')) x1 = Math.max(s(p.x), x0 + 40);
            if (dr.dir.includes('n')) y0 = Math.min(s(p.y), y1 - 30);
            if (dr.dir.includes('s')) y1 = Math.max(s(p.y), y0 + 30);
            Object.assign(it, { x: x0, y: y0, w: x1 - x0, h: y1 - y0 });
            this._schedule();
            return;
        }
        if (dr.type === 'end') {
            const w = this.R.byId(this.doc, dr.id);
            const other = dr.which === 'from' ? w.to : w.from;
            const { end, box } = this._endAt(p, e, []);
            w[dr.which] = end;
            dr.hover = box ? { x: box.x, y: box.y, w: box.w, h: box.h } : null;
            dr.hoverPt = box ? this.R.anchor(this.doc, end) : null;
            if (other && other.id && box && box.id === other.id && dr.creating) { /* same box: allowed */ }
            this._schedule();
            return;
        }
        if (dr.type === 'via') {
            const w = this.R.byId(this.doc, dr.id);
            w.via[dr.i] = [this._snap(p.x, e), this._snap(p.y, e)];
            this._schedule();
            return;
        }
        if (dr.type === 'label') {
            const w = this.R.byId(this.doc, dr.id);
            if (!dr.moved) { this.snapshot(); dr.moved = true; }
            w.labelDx = Math.round(dr.dx + p.x - dr.p0.x);
            w.labelDy = Math.round(dr.dy + p.y - dr.p0.y);
            this._schedule();
        }
    },

    _up(e) {
        const dr = this.drag;
        if (!dr) return;
        this.drag = null;
        if (dr.type === 'pan') { this._cursor(); return; }
        if (dr.type === 'create') {
            this.snapshot();
            const r = this._rectOf(dr);
            const b = this._newItem('block', { x: r.x, y: r.y });
            if (r.w >= 40 && r.h >= 30) Object.assign(b, { w: r.w, h: r.h });
            this._add(b);
            this.setTool('select');
            this.markDirty(); this.render(); this.renderProps();
            return;
        }
        if (dr.type === 'end' && dr.creating) {
            const w = this.R.byId(this.doc, dr.id);
            const a = this.R.anchor(this.doc, w.from), b = this.R.anchor(this.doc, w.to);
            if (Math.hypot(a.x - b.x, a.y - b.y) < 10) {   // just a click: no wire
                this.doc.items = this.doc.items.filter(i => i.id !== w.id);
                this.undoStack.pop();
                this.sel = [];
                this.render(); this.renderProps();
                return;
            }
        }
        if (dr.type === 'marquee') { this.renderOverlay(); this.renderProps(); return; }
        if ((dr.type === 'move' || dr.type === 'label') && !dr.moved) return;
        this.markDirty();
        this.render();
        this.renderProps();
    },

    _wireBox(w) {
        const pts = this.R.wirePoints(this.doc, w);
        const xs = pts.map(p => p.x), ys = pts.map(p => p.y);
        return { x: Math.min(...xs), y: Math.min(...ys), w: Math.max(...xs) - Math.min(...xs), h: Math.max(...ys) - Math.min(...ys) };
    },

    _dbl(e) {
        if (!this.doc) return;
        const p = this._pt(e);
        const h = e.target.closest('[data-h^="via"]');
        const it = this.R.byId(this.doc, this.sel[0]);
        if (h && it) {                              // remove a bend point
            this.snapshot();
            it.via.splice(+h.dataset.h.split(':')[1], 1);
            this.markDirty(); this.render();
            return;
        }
        const hitEl = e.target.closest('#dg-content [data-id]');
        const hit = hitEl && this.R.byId(this.doc, hitEl.dataset.id);
        if (!hit) return;
        if (hit.type === 'wire') {                  // add a bend point (keeps the current route)
            this.snapshot();
            const pts = this.R.wirePoints(this.doc, hit);
            let best = 0, bd = Infinity;
            for (let i = 0; i < pts.length - 1; i++) {
                const d = this._segDist(p, pts[i], pts[i + 1]);
                if (d < bd) { bd = d; best = i; }
            }
            const via = pts.slice(1, -1).map(q => [Math.round(q.x), Math.round(q.y)]);
            via.splice(best, 0, [this._snap(p.x, e), this._snap(p.y, e)]);
            hit.via = via;
            this.sel = [hit.id];
            this.markDirty(); this.render(); this.renderProps();
            return;
        }
        if (hit.type === 'chip') return this.openPins();
        const field = this.$('dg-props').querySelector('[data-p="title"], [data-p="text"]');
        if (field) { field.focus(); field.select && field.select(); }
    },

    _segDist(p, a, b) {
        const dx = b.x - a.x, dy = b.y - a.y, l = dx * dx + dy * dy;
        const t = l ? Math.max(0, Math.min(1, ((p.x - a.x) * dx + (p.y - a.y) * dy) / l)) : 0;
        return Math.hypot(p.x - a.x - t * dx, p.y - a.y - t * dy);
    },

    // ── Keyboard ───────────────────────────────────────────────

    _keys(e) {
        if (!this.doc || document.querySelector('.modal-overlay.open')) return;
        const inField = e.target.closest('input, textarea, select, [contenteditable]');
        const ctrl = e.ctrlKey || e.metaKey, key = e.key.toLowerCase();
        if (ctrl && key === 's') { e.preventDefault(); return this.save(); }
        if (inField) return;
        if (e.code === 'Space') { this._space = true; this._cursor(); e.preventDefault(); return; }
        if (ctrl && key === 'z') { e.preventDefault(); return e.shiftKey ? this.redo() : this.undo(); }
        if (ctrl && key === 'y') { e.preventDefault(); return this.redo(); }
        if (ctrl && key === 'a') { e.preventDefault(); this.sel = this.doc.items.map(i => i.id); this.renderOverlay(); return this.renderProps(); }
        if (ctrl && key === 'c') { e.preventDefault(); return this.copy(); }
        if (ctrl && key === 'v') { e.preventDefault(); return this.paste(); }
        if (ctrl && key === 'd') { e.preventDefault(); this.copy(); return this.paste(); }
        if (ctrl) return;
        if (key === 'delete' || key === 'backspace') { e.preventDefault(); return this.deleteSel(); }
        if (key === 'escape') { this.sel = []; this.setTool('select'); this.renderOverlay(); return this.renderProps(); }
        if (key.startsWith('arrow') && this.sel.length) {
            e.preventDefault();
            const st = e.shiftKey ? (this.doc.grid || 10) : 1;
            const d = { arrowleft: [-st, 0], arrowright: [st, 0], arrowup: [0, -st], arrowdown: [0, st] }[key];
            return this.nudge(d[0], d[1]);
        }
        const tools = { v: 'select', b: 'block', c: 'chip', t: 'text', w: 'wire', l: 'legend' };
        if (tools[key]) return this.setTool(tools[key]);
        if (key === 'f') return this.fit();
        if (key === '+' || key === '=') return this.zoom(1.25);
        if (key === '-') return this.zoom(0.8);
        if (key === '0') return this.zoom100();
    },

    nudge(dx, dy) {
        this.snapshot();
        const o = this._origOf(this.sel);
        for (const [id, v] of Object.entries(o)) {
            const it = this.R.byId(this.doc, id);
            if (it.type === 'wire') {
                if (!it.from.id) it.from = { x: v.from.x + dx, y: v.from.y + dy };
                if (!it.to.id) it.to = { x: v.to.x + dx, y: v.to.y + dy };
                if (v.via.length) it.via = v.via.map(([x, y]) => [x + dx, y + dy]);
            } else { it.x += dx; it.y += dy; }
        }
        this.markDirty(); this.render(); this.renderProps();
    },

    // ── Edit commands ──────────────────────────────────────────

    deleteSel() {
        if (!this.sel.length) return;
        this.snapshot();
        const gone = new Set(this.sel);
        for (const w of this.doc.items.filter(i => i.type === 'wire' && !gone.has(i.id))) {
            for (const end of ['from', 'to']) {               // keep wires: detach their ends at the same place
                if (w[end].id && gone.has(w[end].id)) {
                    const a = this.R.anchor(this.doc, w[end]);
                    w[end] = { x: Math.round(a.x), y: Math.round(a.y) };
                }
            }
        }
        this.doc.items = this.doc.items.filter(i => !gone.has(i.id));
        this.sel = [];
        this.markDirty(); this.render(); this.renderProps();
    },

    copy() {
        if (!this.sel.length) return;
        this.clip = JSON.stringify(this.doc.items.filter(i => this.sel.includes(i.id)));
    },

    paste() {
        if (!this.clip) return;
        this.snapshot();
        const items = JSON.parse(this.clip), map = {}, off = (this.doc.grid || 10) * 2;
        items.forEach(it => { map[it.id] = this._id(it.type); });
        for (const it of items) {
            it.id = map[it.id];
            if (it.type === 'wire') {
                for (const end of ['from', 'to']) {
                    if (it[end].id && map[it[end].id]) it[end].id = map[it[end].id];
                    else if (!it[end].id) it[end] = { x: it[end].x + off, y: it[end].y + off };
                }
                if (it.via) it.via = it.via.map(([x, y]) => [x + off, y + off]);
            } else { it.x += off; it.y += off; }
            this.doc.items.push(it);
        }
        this.sel = items.map(i => i.id);
        this.clip = JSON.stringify(items);                // the next paste goes further
        this.markDirty(); this.render(); this.renderProps();
    },

    order(where) {
        if (!this.sel.length) return;
        this.snapshot();
        const s = this.doc.items.filter(i => this.sel.includes(i.id)), rest = this.doc.items.filter(i => !this.sel.includes(i.id));
        this.doc.items = where === 'front' ? [...rest, ...s] : [...s, ...rest];
        this.markDirty(); this.render();
    },

    align(how) {
        const items = this.sel.map(id => this.R.byId(this.doc, id)).filter(i => i && i.type !== 'wire');
        if (items.length < 2) return;
        this.snapshot();
        const boxes = items.map(i => this._box(i));
        const minX = Math.min(...boxes.map(b => b.x)), maxX = Math.max(...boxes.map(b => b.x + b.w));
        const minY = Math.min(...boxes.map(b => b.y)), maxY = Math.max(...boxes.map(b => b.y + b.h));
        items.forEach((it, k) => {
            const b = boxes[k];
            if (how === 'left') it.x += minX - b.x;
            if (how === 'right') it.x += maxX - (b.x + b.w);
            if (how === 'center') it.x += (minX + maxX) / 2 - (b.x + b.w / 2);
            if (how === 'top') it.y += minY - b.y;
            if (how === 'bottom') it.y += maxY - (b.y + b.h);
            if (how === 'middle') it.y += (minY + maxY) / 2 - (b.y + b.h / 2);
            it.x = Math.round(it.x); it.y = Math.round(it.y);
        });
        this.markDirty(); this.render();
    },

    /** Page size = content + margin; content at negative coordinates is shifted into the page. */
    fitPage() {
        const b = this.$('dg-content').getBBox();
        if (!b.width) return;
        this.snapshot();
        const m = 60, dx = b.x < m ? Math.ceil(m - b.x) : 0, dy = b.y < m ? Math.ceil(m - b.y) : 0;
        if (dx || dy) {
            for (const it of this.doc.items) {
                if (it.type === 'wire') {
                    if (!it.from.id) { it.from.x += dx; it.from.y += dy; }
                    if (!it.to.id) { it.to.x += dx; it.to.y += dy; }
                    if (it.via) it.via = it.via.map(([x, y]) => [x + dx, y + dy]);
                } else { it.x += dx; it.y += dy; }
            }
        }
        this.doc.width = Math.ceil(b.x + dx + b.width + m);
        this.doc.height = Math.ceil(b.y + dy + b.height + m);
        this.markDirty(); this.render(); this.renderProps(); this.fit();
    },

    // ── Properties panel ───────────────────────────────────────

    _fields(it) {
        const colorRow = (label, p) => ({ label, p, t: 'color' });
        const sel = (label, p, opts) => ({ label, p, t: 'select', opts });
        const num = (label, p) => ({ label, p, t: 'num' });
        const pos = [num('X', 'x'), num('Y', 'y')];
        const size = [num('W', 'w'), num('H', 'h')];
        switch (it.type) {
            case 'text': return [{ label: 'Text', p: 'text', t: 'area' }, num('Size', 'size'), colorRow('Colour', 'color'),
                sel('Font', 'font', [['sans', 'Sans'], ['mono', 'Mono']]), sel('Weight', 'weight', [['normal', 'Normal'], ['600', 'Semi-bold'], ['700', 'Bold']]),
                sel('Align', 'anchor', [['start', 'Left'], ['middle', 'Centre'], ['end', 'Right']]),
                sel('Rotate', 'rotate', [['0', '0°'], ['-90', '-90° (up)'], ['90', '90° (down)']]),
                { label: 'Italic', p: 'italic', t: 'check' }, ...pos];
            case 'block': return [{ label: 'Title', p: 'title', t: 'text' },
                { label: 'Lines', p: 'lines', t: 'area', hint: 'One per line; start with ` for monospace' },
                sel('Style', 'style', Object.keys(this.R.BLOCK_STYLES).map(k => [k, k])),
                colorRow('Fill', 'fill'), colorRow('Border', 'stroke'), colorRow('Title colour', 'titleColor'), colorRow('Text colour', 'textColor'),
                { label: 'Dashed border', p: 'dashed', t: 'check' }, sel('Text align', 'align', [['left', 'Left'], ['center', 'Centre']]),
                num('Title size', 'titleSize'), num('Line size', 'lineSize'), num('Corner radius', 'radius'), ...pos, ...size,
                { t: 'button', label: 'Fit height to text', act: 'fitBlock' }];
            case 'wire': return [{ label: 'Label', p: 'label', t: 'area', hint: 'Drag the label to move it' },
                sel('Arrows', 'arrow', [['end', '→ end'], ['start', '← start'], ['both', '↔ both'], ['none', 'none']]),
                sel('Route', 'route', [['ortho', 'Orthogonal'], ['straight', 'Straight']]),
                { label: 'Dashed', p: 'dashed', t: 'check' }, colorRow('Colour', 'color'), num('Width', 'width'), num('Label size', 'labelSize'),
                { t: 'button', label: 'Reset route & label', act: 'resetWire' }, { t: 'button', label: 'Reverse direction', act: 'reverseWire' },
                { t: 'info', text: 'Double-click the wire to add a bend point, double-click a bend point to remove it. Drag an end onto a block to attach it (Alt = free).' }];
            case 'chip': return [{ t: 'button', label: 'Edit pins…', act: 'openPins', cls: 'btn-primary' },
                { t: 'info', text: this.R.SIDES.map(s => `${s}: ${(it.pins[s] || []).length}`).join(' · ') },
                sel('Pin style', 'pinStyle', [['tags', 'Tags (port · function · dir · note)'], ['simple', 'Simple (coloured text)']]),
                sel('Body', 'body', [['module', 'Dark module'], ['outline', 'Light outline']]),
                { label: 'Mounting holes', p: 'holes', t: 'check' }, { label: 'Pin numbers', p: 'numbers', t: 'check' },
                { label: 'Centre chip', p: 'ic.show', t: 'check' }, { label: 'Chip title', p: 'ic.title', t: 'text' },
                { label: 'Chip subtitle', p: 'ic.subtitle', t: 'text' }, { label: 'Caption', p: 'caption', t: 'text' },
                { label: 'Caption 2', p: 'caption2', t: 'text' }, num('Pin margin L/R', 'corner'), num('Pin margin T/B', 'corner2'),
                num('Port tag width', 'portW'), num('Function tag width', 'fnW'), ...pos, ...size];
            case 'legend': return [sel('Style', 'style', [['tags', 'Tags'], ['swatch', 'Colour squares']]), num('Font size', 'size'),
                { t: 'kinds' }, ...pos];
        }
        return [];
    },

    _get(obj, path) { return path.split('.').reduce((o, k) => o == null ? undefined : o[k], obj); },
    _set(obj, path, v) {
        const ks = path.split('.'), last = ks.pop();
        const tgt = ks.reduce((o, k) => (o[k] = o[k] && typeof o[k] === 'object' ? o[k] : {}), obj);
        if (v === undefined) delete tgt[last]; else tgt[last] = v;
    },

    _defaultOf(it, p) {
        if (it.type === 'block') {
            const st = this.R.BLOCK_STYLES[it.style] || this.R.BLOCK_STYLES.light;
            return { fill: st.fill, stroke: st.stroke, titleColor: st.title, textColor: st.text }[p];
        }
        if (it.type === 'wire' && p === 'color') return '#57534e';
        if (it.type === 'text' && p === 'color') return '#1f2937';
        return '';
    },

    _fieldHtml(it, f) {
        if (f.t === 'button') return `<button class="btn btn-sm ${f.cls || 'btn-ghost'} dg-pbtn" data-act="${f.act}">${esc(f.label)}</button>`;
        if (f.t === 'info') return `<div class="hint dg-pinfo">${esc(f.text)}</div>`;
        if (f.t === 'kinds') {
            const on = new Set(it.kinds || []);
            return `<div class="field"><label>Kinds (none = used ones)</label><div class="dg-kind-checks">` +
                Object.entries(this.doc.kinds).map(([k, kd]) =>
                    `<label class="check-row small"><input type="checkbox" data-legend-kind="${esc(k)}"${on.has(k) ? ' checked' : ''}> ${esc(kd.label || k)}</label>`).join('') +
                '</div></div>';
        }
        let v = this._get(it, f.p);
        if (f.p === 'lines' && Array.isArray(v)) v = v.join('\n');
        const p = esc(f.p);
        let input;
        switch (f.t) {
            case 'area': input = `<textarea class="input input-sm mono" rows="${f.p === 'lines' ? 6 : 3}" data-p="${p}">${esc(v || '')}</textarea>`; break;
            case 'num': input = `<input class="input input-sm" type="number" step="any" data-p="${p}" value="${v == null ? '' : esc(v)}">`; break;
            case 'check': {
                const checked = f.p === 'holes' || f.p === 'numbers' || f.p === 'ic.show' ? v !== false : !!v;
                return `<label class="check-row small dg-check"><input type="checkbox" data-p="${p}"${checked ? ' checked' : ''}> ${esc(f.label)}</label>`;
            }
            case 'select': {
                const cur = v == null ? f.opts[0][0] : String(v);
                input = `<select class="input input-sm" data-p="${p}">` + f.opts.map(([val, lab]) =>
                    `<option value="${esc(val)}"${val === cur ? ' selected' : ''}>${esc(lab)}</option>`).join('') + '</select>';
                break;
            }
            case 'color': {
                const def = this._defaultOf(it, f.p), shown = v || (def && def !== 'none' ? def : '#ffffff');
                input = `<div class="dg-color"><input type="color" data-p="${p}" value="${esc(shown)}">` +
                        `<span class="mono small ${v ? '' : 'faint'}">${esc(v || 'default')}</span>` +
                        (v ? `<button class="btn-icon" data-clear="${p}" title="Use the default"><i class="fa-solid fa-xmark"></i></button>` : '') + '</div>';
                break;
            }
            default: input = `<input class="input input-sm" data-p="${p}" value="${esc(v == null ? '' : v)}">`;
        }
        return `<div class="field${f.t === 'num' ? ' dg-num' : ''}"><label>${esc(f.label)}</label>${input}${f.hint ? `<span class="hint">${esc(f.hint)}</span>` : ''}</div>`;
    },

    renderProps() {
        const el = this.$('dg-props');
        if (!this.doc) { el.innerHTML = ''; return; }
        const items = this.sel.map(id => this.R.byId(this.doc, id)).filter(Boolean);
        if (items.length > 1) {
            el.innerHTML = `<div class="dg-ptitle">${items.length} items selected</div>` +
                '<div class="field"><label>Align</label><div class="dg-btnrow">' +
                [['left', 'fa-align-left'], ['center', 'fa-align-center'], ['right', 'fa-align-right']].map(([a, i]) =>
                    `<button class="btn btn-ghost btn-sm" data-act="align:${a}" title="Align ${a}"><i class="fa-solid ${i}"></i></button>`).join('') +
                [['top', 'Top'], ['middle', 'Middle'], ['bottom', 'Bottom']].map(([a, l]) =>
                    `<button class="btn btn-ghost btn-sm" data-act="align:${a}">${l}</button>`).join('') + '</div></div>' +
                this._commonButtons();
            return;
        }
        if (items.length === 1) {
            const it = items[0];
            const names = { text: 'Text', block: 'Block', wire: 'Wire / arrow', chip: 'Chip / module', legend: 'Legend' };
            const fields = this._fields(it);
            let html = `<div class="dg-ptitle"><i class="fa-solid ${this.ICONS[it.type]}"></i> ${names[it.type]}</div><div class="dg-pgrid">`;
            for (const f of fields) html += this._fieldHtml(it, f);
            el.innerHTML = html + '</div>' + this._commonButtons();
            return;
        }
        // nothing selected: the diagram itself + pin kinds
        const d = this.doc;
        el.innerHTML = `<div class="dg-ptitle"><i class="fa-solid fa-diagram-project"></i> Diagram</div><div class="dg-pgrid">` +
            this._docField('Title', 'title', 'text') +
            this._docField('Page width', 'width', 'num') + this._docField('Page height', 'height', 'num') +
            this._docField('Background', 'background', 'color') + this._docField('Grid', 'grid', 'num') +
            `<button class="btn btn-ghost btn-sm dg-pbtn" data-act="fitPage"><i class="fa-solid fa-expand"></i> Fit page to content</button></div>` +
            `<div class="dg-ptitle dg-sub">Pin kinds <button class="btn-icon" data-act="addKind" title="Add kind"><i class="fa-solid fa-plus"></i></button></div>` +
            '<div class="dg-kinds">' + Object.entries(d.kinds).map(([k, kd]) => this._kindHtml(k, kd)).join('') + '</div>' +
            '<div class="hint dg-pinfo">Tools: V select · B block · C chip · T text · W wire · L legend. Space/right-drag = pan, wheel = zoom, ' +
            'F = fit, Alt = no snapping, Ctrl+D duplicate, Delete, Ctrl+Z / Ctrl+Y.</div>';
    },

    ICONS: { text: 'fa-font', block: 'fa-square', wire: 'fa-arrow-right-long', chip: 'fa-microchip', legend: 'fa-list' },

    _commonButtons() {
        return '<div class="dg-btnrow dg-pfoot">' +
            '<button class="btn btn-ghost btn-sm" data-act="front" title="Bring to front"><i class="fa-solid fa-arrow-up"></i> Front</button>' +
            '<button class="btn btn-ghost btn-sm" data-act="back" title="Send to back"><i class="fa-solid fa-arrow-down"></i> Back</button>' +
            '<button class="btn btn-ghost btn-sm" data-act="dup" title="Duplicate (Ctrl+D)"><i class="fa-regular fa-clone"></i></button>' +
            '<button class="btn btn-danger btn-sm" data-act="del" title="Delete (Del)"><i class="fa-regular fa-trash-can"></i></button></div>';
    },

    _docField(label, p, t) {
        const v = this.doc[p];
        if (t === 'color') return `<div class="field"><label>${label}</label><div class="dg-color"><input type="color" data-dp="${p}" value="${esc(v || '#ffffff')}"><span class="mono small">${esc(v)}</span></div></div>`;
        return `<div class="field${t === 'num' ? ' dg-num' : ''}"><label>${label}</label><input class="input input-sm" ${t === 'num' ? 'type="number"' : ''} data-dp="${p}" value="${esc(v == null ? '' : v)}"></div>`;
    },

    _kindHtml(k, kd) {
        const fk = this.R.esc;
        const sw = (f, title) => `<input type="color" data-kind="${esc(k)}" data-kf="${f}" value="${esc(kd[f] || '#ffffff')}" title="${title}">`;
        return `<div class="dg-kind"><div class="dg-kind-head">` +
            `<svg width="64" height="22" viewBox="-2 -12 68 24">${this.R._tag(0, 64, kd.sample || k, kd, 11)}</svg>` +
            `<input class="input input-sm mono dg-kkey" value="${fk(k)}" disabled title="Kind key (used in the pin table)">` +
            (k === 'free' ? '' : `<button class="btn-icon" data-act="delKind:${esc(k)}" title="Delete kind"><i class="fa-regular fa-trash-can"></i></button>`) +
            `</div><div class="dg-kind-row">` +
            `<input class="input input-sm" data-kind="${esc(k)}" data-kf="label" value="${esc(kd.label || '')}" placeholder="legend label">` +
            `<input class="input input-sm mono" data-kind="${esc(k)}" data-kf="sample" value="${esc(kd.sample || '')}" placeholder="sample" title="Legend sample text">` +
            `<input class="input input-sm mono" data-kind="${esc(k)}" data-kf="badge" value="${esc(kd.badge || '')}" placeholder="dir" title="Direction text next to the tag (OUT, IN…)">` +
            `</div><div class="dg-kind-row">${sw('fill', 'Tag fill')}${sw('stroke', 'Tag border')}${sw('text', 'Tag text')}${sw('color', 'Colour in simple style / swatch')}` +
            `<label class="check-row small" title="Dashed tag border"><input type="checkbox" data-kind="${esc(k)}" data-kf="dash"${kd.dash ? ' checked' : ''}> dashed</label></div></div>`;
    },

    _propInput(e, isChange) {
        const t = e.target;
        if (t.dataset.p == null && t.dataset.dp == null && t.dataset.kind == null && t.dataset.legendKind == null) return;
        if (!this._propUndo) { this.snapshot(); this._propUndo = true; }
        if (t.dataset.dp != null) {
            const p = t.dataset.dp;
            let v = t.value;
            if (['width', 'height', 'grid'].includes(p)) { v = parseFloat(v); if (!(v > 0)) return; }
            this.doc[p] = v;
            if (p === 'title') this._bar();
        } else if (t.dataset.kind != null) {
            const kd = this.doc.kinds[t.dataset.kind], f = t.dataset.kf;
            kd[f] = t.type === 'checkbox' ? (t.checked ? '5 3' : '') : t.value;
            if (isChange) this.renderProps();
        } else if (t.dataset.legendKind != null) {
            const it = this.R.byId(this.doc, this.sel[0]);
            const on = new Set(it.kinds || []);
            t.checked ? on.add(t.dataset.legendKind) : on.delete(t.dataset.legendKind);
            it.kinds = Object.keys(this.doc.kinds).filter(k => on.has(k));
            if (!it.kinds.length) it.kinds = null;
        } else {
            const it = this.R.byId(this.doc, this.sel[0]);
            if (!it) return;
            const p = t.dataset.p;
            let v;
            if (t.type === 'checkbox') v = t.checked;
            else if (t.type === 'number') { v = t.value === '' ? undefined : parseFloat(t.value); if (v != null && isNaN(v)) return; }
            else v = t.value;
            if (p === 'lines') v = t.value.split('\n');
            if (p === 'rotate') v = parseInt(v, 10) || 0;
            if (['x', 'y', 'w', 'h'].includes(p) && v == null) return;
            this._set(it, p, v);
            if (t.type === 'color' && isChange) this.renderProps();
        }
        this.markDirty();
        this._schedule();
    },

    _propClick(e) {
        const clr = e.target.closest('[data-clear]');
        if (clr) {
            this.snapshot();
            this._set(this.R.byId(this.doc, this.sel[0]), clr.dataset.clear, undefined);
            this.markDirty(); this.render(); this.renderProps();
            return;
        }
        const b = e.target.closest('[data-act]');
        if (!b) return;
        const [act, arg] = b.dataset.act.split(':');
        const it = this.R.byId(this.doc, this.sel[0]);
        switch (act) {
            case 'openPins': return this.openPins();
            case 'fitPage': return this.fitPage();
            case 'align': return this.align(arg);
            case 'front': case 'back': return this.order(act);
            case 'dup': this.copy(); return this.paste();
            case 'del': return this.deleteSel();
            case 'fitBlock': {
                this.snapshot();
                const ls = it.lines || [], tsz = it.titleSize || 16, lsz = it.lineSize || 13;
                it.h = Math.ceil(((it.title ? tsz + 36 : lsz + 14) + Math.max(0, ls.length - 1) * (lsz + 7) + 18) / 10) * 10;
                break;
            }
            case 'resetWire': this.snapshot(); delete it.via; delete it.labelDx; delete it.labelDy; break;
            case 'reverseWire': this.snapshot(); [it.from, it.to] = [it.to, it.from]; if (it.via) it.via.reverse(); break;
            case 'addKind': {
                const key = (prompt('Kind key (letters/digits, e.g. "i2c"):') || '').trim();
                if (!key) return;
                if (!/^[\w-]+$/.test(key) || this.doc.kinds[key]) return toast('Invalid or existing key', true);
                this.snapshot();
                this.doc.kinds[key] = { label: key, fill: '#e0f2fe', stroke: '#0284c7', text: '#075985', dash: '', badge: '', sample: key.toUpperCase(), color: '#0284c7' };
                break;
            }
            case 'delKind': {
                const used = this.doc.items.some(c => c.type === 'chip' && this.R.SIDES.some(s => (c.pins[s] || []).some(p => p.kind === arg)));
                if (!confirm(`Delete kind "${arg}"?` + (used ? '\nPins of this kind become "free".' : ''))) return;
                this.snapshot();
                delete this.doc.kinds[arg];
                this.doc.items.filter(c => c.type === 'chip').forEach(c => this.R.SIDES.forEach(s =>
                    (c.pins[s] || []).forEach(p => { if (p.kind === arg) p.kind = 'free'; })));
                break;
            }
            default: return;
        }
        this.markDirty(); this.render(); this.renderProps();
    },

    // ── Pin table ──────────────────────────────────────────────

    _chip() { const it = this.R.byId(this.doc, this.sel[0]); return it && it.type === 'chip' ? it : null; },

    openPins() {
        const c = this._chip();
        if (!c) return;
        this.$('dg-pins-title').textContent = 'Pins — ' + (c.caption || (c.ic && c.ic.title) || 'chip');
        this.$('dg-pins-overlay').classList.add('open');
        this._propUndo = false;
        this.renderPins();
    },

    closePins() {
        this.$('dg-pins-overlay').classList.remove('open');
        this.renderProps();
    },

    setPinSide(s) { this.pinSide = s; this.renderPins(); },

    _refreshPins() { if (this.$('dg-pins-overlay').classList.contains('open')) { if (this._chip()) this.renderPins(); else this.closePins(); } },

    renderPins() {
        const c = this._chip();
        if (!c) return;
        c.pins = c.pins || {};
        document.querySelectorAll('#dg-pin-sides button').forEach(b => {
            b.classList.toggle('active', b.dataset.side === this.pinSide);
            b.querySelector('span').textContent = (c.pins[b.dataset.side] || []).length;
        });
        const pins = c.pins[this.pinSide] || [];
        const kinds = Object.keys(this.doc.kinds);
        const kindSel = (v, i) => `<select class="input input-sm" data-i="${i}" data-f="kind">` +
            [...new Set([...kinds, v || 'free'])].map(k => `<option value="${esc(k)}"${k === (v || 'free') ? ' selected' : ''}>${esc(k)}</option>`).join('') + '</select>';
        const order = { left: 'top → bottom', right: 'top → bottom', top: 'left → right', bottom: 'left → right' }[this.pinSide];
        this.$('dg-pins-order').textContent = `Row order on the drawing: ${order}`;
        this.$('dg-pins-body').innerHTML = !pins.length ? '<div class="tbl-empty">No pins on this side. Add rows or paste them from a spreadsheet.</div>' :
            '<table class="tbl dg-pins"><thead><tr><th>#</th><th>Pin</th><th>Port</th><th>Function / net</th><th>Kind</th><th>Dir</th><th>Note</th><th></th></tr></thead><tbody>' +
            pins.map((p, i) => `<tr data-i="${i}"><td class="faint small">${i + 1}</td>` +
                `<td><input class="input input-sm mono dg-pn" data-i="${i}" data-f="n" value="${esc(p.n == null ? '' : p.n)}"></td>` +
                `<td><input class="input input-sm mono" data-i="${i}" data-f="port" value="${esc(p.port || '')}"></td>` +
                `<td><input class="input input-sm mono" data-i="${i}" data-f="fn" value="${esc(p.fn || '')}"></td>` +
                `<td>${kindSel(p.kind, i)}</td>` +
                `<td><input class="input input-sm mono dg-pb" data-i="${i}" data-f="badge" value="${esc(p.badge || '')}" placeholder="auto"></td>` +
                `<td><input class="input input-sm" data-i="${i}" data-f="note" value="${esc(p.note || '')}"></td>` +
                `<td class="dg-row-act"><button class="btn-icon" data-pa="up:${i}" title="Move up"><i class="fa-solid fa-arrow-up"></i></button>` +
                `<button class="btn-icon" data-pa="down:${i}" title="Move down"><i class="fa-solid fa-arrow-down"></i></button>` +
                `<button class="btn-icon" data-pa="ins:${i}" title="Insert below"><i class="fa-solid fa-plus"></i></button>` +
                `<button class="btn-icon" data-pa="del:${i}" title="Delete"><i class="fa-solid fa-xmark"></i></button></td></tr>`).join('') +
            '</tbody></table>';
    },

    _pins() { const c = this._chip(); return c ? (c.pins[this.pinSide] = c.pins[this.pinSide] || []) : []; },

    _pinChanged(rerender) {
        this.markDirty();
        this._schedule();
        if (rerender) this.renderPins();
    },

    _pinInput(e) {
        const t = e.target;
        if (t.dataset.f == null) return;
        if (!this._propUndo) { this.snapshot(); this._propUndo = true; }
        const p = this._pins()[+t.dataset.i];
        if (!p) return;
        const f = t.dataset.f;
        p[f] = f === 'n' && /^\d+$/.test(t.value) ? +t.value : t.value;
        this._pinChanged(false);
    },

    _pinClick(e) {
        const b = e.target.closest('[data-pa]');
        if (!b) return;
        const [act, s] = b.dataset.pa.split(':'), i = +s, pins = this._pins();
        this.snapshot();
        if (act === 'up' && i > 0) [pins[i - 1], pins[i]] = [pins[i], pins[i - 1]];
        if (act === 'down' && i < pins.length - 1) [pins[i + 1], pins[i]] = [pins[i], pins[i + 1]];
        if (act === 'del') pins.splice(i, 1);
        if (act === 'ins') pins.splice(i + 1, 0, this._nextPin(pins, i));
        this._pinChanged(true);
    },

    _nextPin(pins, i) {
        const prev = pins[i];
        const n = prev && typeof prev.n === 'number' ? prev.n + 1 : '';
        return { n, port: '', fn: '', kind: 'free', badge: '', note: '' };
    },

    pinCmd(cmd) {
        const pins = this._pins();
        if (cmd === 'add') {
            const count = Math.max(1, Math.min(200, parseInt(prompt('How many pins to add?', '1'), 10) || 0));
            if (!count) return;
            this.snapshot();
            for (let k = 0; k < count; k++) pins.push(this._nextPin(pins, pins.length - 1));
        } else if (cmd === 'number') {
            const ans = prompt('Number pins of this side: start, step (e.g. "1, 1" or "50, -1")', '1, 1');
            if (!ans) return;
            const [start, step] = ans.split(',').map(v => parseFloat(v));
            if (isNaN(start)) return;
            this.snapshot();
            pins.forEach((p, k) => { p.n = start + k * (isNaN(step) ? 1 : step); });
        } else if (cmd === 'reverse') {
            this.snapshot(); pins.reverse();
        } else if (cmd === 'clear') {
            if (!pins.length || !confirm(`Delete all ${pins.length} pins of the ${this.pinSide} side?`)) return;
            this.snapshot(); pins.length = 0;
        } else if (cmd === 'copy') {
            Help.copyText(pins.map(p => this.PIN_FIELDS.map(f => p[f] == null ? '' : p[f]).join('\t')).join('\n'));
            return toast('Copied as TSV (paste into Excel)');
        }
        this._pinChanged(true);
    },

    /** Paste spreadsheet rows (TSV, or ; / , separated) starting at the focused cell; adds rows as needed. */
    _pinPaste(e) {
        const text = (e.clipboardData || window.clipboardData).getData('text');
        if (!text || (!text.includes('\t') && !text.includes('\n'))) return;   // a single value: normal paste
        e.preventDefault();
        const t = e.target.closest('[data-f]');
        const pins = this._pins();
        const row0 = t ? +t.dataset.i : pins.length, col0 = t ? this.PIN_FIELDS.indexOf(t.dataset.f) : 0;
        const lines = text.replace(/\r/g, '').split('\n').filter((l, k, a) => l.trim() || k < a.length - 1);
        const sep = text.includes('\t') ? '\t' : (text.includes(';') ? ';' : ',');
        const kinds = this.doc.kinds;
        const toKind = v => {
            const s = String(v).trim().toLowerCase();
            if (!s) return 'free';
            return Object.keys(kinds).find(k => k.toLowerCase() === s || (kinds[k].label || '').toLowerCase() === s) || s;
        };
        this.snapshot();
        lines.forEach((line, k) => {
            const cells = line.split(sep);
            const p = pins[row0 + k] || (pins[row0 + k] = { n: '', port: '', fn: '', kind: 'free', badge: '', note: '' });
            cells.forEach((v, c) => {
                const f = this.PIN_FIELDS[col0 + c];
                if (!f) return;
                v = v.trim();
                p[f] = f === 'kind' ? toKind(v) : (f === 'n' && /^\d+$/.test(v) ? +v : v);
            });
            if (col0 <= 2 && !cells[2 - col0] && p.kind !== 'free' && !p.fn) p.kind = 'free';
        });
        this._pinChanged(true);
        toast(`${lines.length} row(s) pasted`);
    },

    // ── Save / export / manage ─────────────────────────────────

    save(force = false) {
        if (!this.doc) return;
        const svg = this.R.toSvg(this.doc);
        App.api('/api/help/diagram/save', { json: { name: this.name, data: this.doc, svg, mtime: this.mtime, force } })
            .then(r => {
                this.mtime = r.mtime; this.dirty = false; this._bar();
                toast('Saved');
                this.loadList();
                Help.bustDiagram(this.name);
            })
            .catch(e => {
                if (/changed by someone/i.test(e.message)) {
                    if (confirm('The diagram was changed on disk after you opened it.\nOverwrite it with your version?')) this.save(true);
                } else toast(e.message, true);
            });
    },

    _download(blob, name) {
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = name;
        document.body.append(a);
        a.click();
        setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
    },

    exportSvg() { this._download(new Blob([this.R.toSvg(this.doc)], { type: 'image/svg+xml' }), this.name + '.svg'); },

    exportPng(scale = 2) {
        const svg = this.R.toSvg(this.doc);
        const img = new Image();
        img.onload = () => {
            const cv = document.createElement('canvas');
            cv.width = this.doc.width * scale; cv.height = this.doc.height * scale;
            const ctx = cv.getContext('2d');
            ctx.scale(scale, scale);
            ctx.drawImage(img, 0, 0);
            cv.toBlob(b => this._download(b, this.name + '.png'), 'image/png');
        };
        img.onerror = () => toast('PNG export failed', true);
        img.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg);
    },

    copyEmbed() {
        Help.copyText(`![${this.doc.title || this.name}](diagrams/${this.name}.svg)`);
        toast('Markdown copied (relative to help/; use the Docs editor button for the right path)');
    },

    rename() {
        const n = prompt('New diagram name (letters, digits, . _ -):', this.name);
        if (!n || n === this.name) return;
        const go = () => App.api('/api/help/diagram/rename', { json: { name: this.name, new_name: n } }).then(r => {
            this.dirty = false;
            toast('Renamed' + (r.docs.length ? `, links fixed in ${r.docs.length} doc(s)` : ''));
            this.doc = null;
            Help.loadTree();
            return this.loadList().then(() => this.open(r.name, false)).then(() =>
                history.replaceState(null, '', '/help?diagram=' + encodeURIComponent(r.name)));
        }).catch(e => toast(e.message, true));
        if (this.dirty) {
            if (!confirm('Save the changes first?')) return;
            const svg = this.R.toSvg(this.doc);
            App.api('/api/help/diagram/save', { json: { name: this.name, data: this.doc, svg, mtime: this.mtime } })
                .then(go).catch(e => toast(e.message, true));
        } else go();
    },

    remove() {
        const warn = this.usedBy.length ? `\n\nIt is used in:\n${this.usedBy.join('\n')}` : '';
        if (!confirm(`Delete diagram "${this.name}"? It is moved to .trash.${warn}`)) return;
        App.api('/api/help/diagram/delete', { json: { name: this.name } }).then(() => {
            toast('Moved to .trash');
            this.dirty = false;
            this.close();
            this.loadList();
        }).catch(e => toast(e.message, true));
    },

    // ── New diagram ────────────────────────────────────────────

    openNew() {
        if (!Help._leaveEditors()) return;
        this.$('dg-new-title').value = '';
        this.$('dg-new-name').value = '';
        this._newNameTouched = false;
        this.$('dg-new-overlay').classList.add('open');
        this.$('dg-new-title').focus();
    },

    closeNew() { this.$('dg-new-overlay').classList.remove('open'); },

    newInput(e) {
        if (e.target.id === 'dg-new-name') this._newNameTouched = true;
        else if (!this._newNameTouched) {
            this.$('dg-new-name').value = e.target.value.trim().replace(/[^\p{L}\p{N}._-]+/gu, '_').replace(/^[_.]+|_+$/g, '').slice(0, 80);
        }
    },

    submitNew() {
        const name = this.$('dg-new-name').value.trim(), title = this.$('dg-new-title').value.trim() || name;
        if (!name) return toast('Enter a name', true);
        const data = this.template(this.$('dg-new-tpl').value, title);
        App.api('/api/help/diagram/create', { json: { name, data, svg: this.R.toSvg(data) } }).then(r => {
            this.closeNew();
            return this.loadList().then(() => this.open(r.name));
        }).catch(e => toast(e.message, true));
    },

    template(kind, title) {
        const doc = this.R.newDoc(title), prev = this.doc;
        this.doc = doc;                                  // _id() checks uniqueness against this.doc
        const add = it => { it.id = this._id(it.type); doc.items.push(it); return it; };
        add({ type: 'text', x: 60, y: 68, text: title, size: 32, weight: '700' });
        if (kind === 'pinout') {
            Object.assign(doc, { width: 1700, height: 1350 });
            add({ type: 'text', x: 60, y: 98, text: 'Pinout: port → function · grey = free / alternative functions', size: 16, color: '#6b7280' });
            add({ type: 'legend', x: 60, y: 140, kinds: null, style: 'tags' });
            const chip = add(this._newItem('chip', { x: 550, y: 380 }));
            Object.assign(chip, { w: 600, h: 600 });
            chip.pins.left[0] = { n: 1, port: 'PA0', fn: 'LED_RUN', kind: 'out', badge: '', note: 'status LED' };
            chip.pins.left[1] = { n: 2, port: 'PA1', fn: 'BTN_START', kind: 'in', badge: '', note: 'pull-up' };
            chip.pins.left[2] = { n: 3, port: 'PA2', fn: 'UART_TX', kind: 'bus', badge: 'UART1', note: 'debug' };
            chip.pins.left[3] = { n: 4, port: 'PA3', fn: 'UART_RX', kind: 'bus', badge: 'UART1', note: 'debug' };
            chip.pins.left[7] = { n: 8, port: 'GND', fn: 'GND', kind: 'pwr', badge: '', note: '' };
            chip.pins.bottom[0] = { n: 9, port: 'VCC', fn: '3V3', kind: 'pwr', badge: '', note: '' };
        } else if (kind === 'block') {
            Object.assign(doc, { width: 1400, height: 700 });
            const a = add({ type: 'block', x: 80, y: 200, w: 300, h: 100, title: 'Sensor', lines: ['I²C · 0x48'], style: 'light' });
            const b = add({ type: 'block', x: 540, y: 160, w: 340, h: 180, title: 'Controller', lines: ['service (Python)', '`HTTP :8080', '`UDP  :8088'], style: 'dark' });
            const c = add({ type: 'block', x: 1040, y: 200, w: 280, h: 100, title: 'PC', lines: ['dashboard'], style: 'light' });
            const p = add({ type: 'block', x: 540, y: 470, w: 340, h: 90, title: 'Power 5 V → 3V3', lines: ['buck + LDO'], style: 'accent' });
            add({ type: 'wire', from: { id: a.id, side: 'right', t: 0.5 }, to: { id: b.id, side: 'left', t: 0.5 }, label: 'SDA · SCL', arrow: 'both', route: 'ortho' });
            add({ type: 'wire', from: { id: b.id, side: 'right', t: 0.5 }, to: { id: c.id, side: 'left', t: 0.5 }, label: 'Ethernet', arrow: 'both', route: 'ortho' });
            add({ type: 'wire', from: { id: p.id, side: 'top', t: 0.5 }, to: { id: b.id, side: 'bottom', t: 0.5 }, label: '3V3', arrow: 'end', route: 'ortho', dashed: true });
        }
        this.doc = prev;
        return doc;
    },
};
Diagrams.init();
