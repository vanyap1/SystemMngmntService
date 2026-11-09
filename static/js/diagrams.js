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
    PORT_FIELDS: ['name', 'type', 'side', 'note'],
    usedIn: [],                   // diagrams that place this one as a unit (when it is a library component)
    lib: {},                      // component name -> {mtime, master} fetched for placing / checking units
    stale: new Set(), missing: new Set(),   // unit ids whose component changed / is gone
    unitPick: null,               // {ref, master} chosen in the library for the Unit tool

    /** Bus-level (simplified) symbols: one port per interface, no power. Other categories: UNIT_TEMPLATES without power. */
    BUS_TEMPLATES: {
        prog:    'L:USB/bus;R:SWD/bus',
        adapter: 'L:USB/bus;R:UART/bus',
        iso:     'L:BUS_A/bus;R:BUS_B/bus',
        hub:     'L:UP/bus;R:P1/bus,P2/bus,P3/bus,P4/bus',
        dut:     'L:IN/bus;R:OUT/bus,DEBUG/bus;B:TP/tp',
        mux:     'L:CH/bus;R:COM/analog;T:ADDR/bus',
        ctrl:    'L:USB/bus;R:RELAYS/bus,MUX_ADDR/bus',
        io:      'L:DI/bus,AI/bus;R:DO/bus,AO/bus;T:ETH/bus',
    },

    _busPorts(cat) {
        if (this.BUS_TEMPLATES[cat]) return this._parsePorts(this.BUS_TEMPLATES[cat]);
        return this._parsePorts(this.UNIT_TEMPLATES[cat] || '').filter(p => p.type !== 'pwr' && p.type !== 'gnd');
    },

    /** Typical ports of a new library component by category ("L:" left, "R:" right, "T:" top, "B:" bottom). */
    UNIT_TEMPLATES: {
        dut:     'L:VIN/pwr,GND/gnd,IN1/in,IN2/in;R:OUT1/out,OUT2/out,UART/bus;B:TP1/tp,TP2/tp,TP3/tp,TP4/tp',
        scope:   'L:CH1/analog,CH2/analog,CH3/analog,CH4/analog,EXT_TRIG/in;R:USB/bus,LAN/bus',
        gen:     'L:USB/bus,LAN/bus;R:OUT1/analog,OUT2/analog,SYNC/out',
        psu:     'L:LAN/bus;R:OUT1+/pwr,OUT1-/gnd,OUT2+/pwr,OUT2-/gnd',
        dmm:     'L:HI/analog,LO/analog,I/analog;R:USB/bus',
        io:      'L:DI1/in,DI2/in,DI3/in,DI4/in,AI1/analog,AI2/analog;R:DO1/out,DO2/out,DO3/out,DO4/out,AO1/analog;T:ETH/bus;B:24V/pwr,GND/gnd',
        pc:      'R:USB1/bus,USB2/bus,ETH/bus,COM1/bus,GPIO/io',
        mux:     'L:CH1/analog,CH2/analog,CH3/analog,CH4/analog,CH5/analog,CH6/analog,CH7/analog,CH8/analog;R:COM/analog;T:A0/in,A1/in,A2/in,EN/in;B:VCC/pwr,GND/gnd',
        relay:   'L:COIL+/in,COIL-/gnd;R:COM/io,NO/io,NC/io',
        ctrl:    'L:USB/bus,I2C/bus,UART/bus;R:K1/out,K2/out,K3/out,K4/out,K5/out,K6/out,K7/out,K8/out;B:12V/pwr,GND/gnd',
        prog:    'L:USB/bus;R:VTG/analog,SWDIO/io,SWCLK/out,SWO/in,nRESET/out,GND/gnd',
        adapter: 'L:USB/bus;R:TXD/out,RXD/in,VCCIO/pwr,GND/gnd',
        iso:     'L:IN_A/in,OUT_A/out;R:OUT_B/out,IN_B/in;T:VDD_A/pwr,VDD_B/pwr;B:GND_A/gnd,GND_B/gnd',
        hub:     'L:UP/bus;R:P1/bus,P2/bus,P3/bus,P4/bus;B:PWR/pwr,GND/gnd',
        jig:     'L:PWR/pwr,GND/gnd,CTRL/bus;R:J1/io,J2/io,J3/io,J4/io;B:TP_BUS/analog',
        station: 'L:MAINS/pwr,LAN/bus',
        custom:  'L:IN1/in;R:OUT1/out',
    },

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
        const ports = this.$('dg-ports-body');
        ports.addEventListener('focusin', () => { this._propUndo = false; });
        ports.addEventListener('input', e => this._portInput(e));
        ports.addEventListener('change', e => this._portInput(e));
        ports.addEventListener('click', e => this._portClick(e));
        ports.addEventListener('paste', e => this._portPaste(e));
        this.$('dg-lib-list').addEventListener('click', e => this.libClick(e));
        this.$('dg-lib-q').addEventListener('input', () => this.renderLib());
        App.onEscape(() => {
            if (!this.$('dg-lib').hidden) return this.closeLib();
            if (this.$('dg-ports-overlay').classList.contains('open')) return this.closePorts();
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
            this.name = d.name; this.mtime = d.mtime; this.usedBy = d.used_by || []; this.usedIn = d.used_in || [];
            this.doc = this._normalize(d.data);
            this.stale = new Set(); this.missing = new Set(); this.unitPick = null;
            this.closeLib();
            this.dirty = false; this.sel = []; this.undoStack = []; this.redoStack = []; this.tool = 'select';
            if (push) history.pushState(null, '', '/help?diagram=' + encodeURIComponent(d.name));
            this._show(true);
            requestAnimationFrame(() => { this.fit(); this.render(); this.renderProps(); });
            this.checkUnits();
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
        const alive = set => [...set].filter(id => this.doc && this.R.byId(this.doc, id)).length;
        const ns = alive(this.stale), n = ns + alive(this.missing), st = this.$('dg-stale');
        st.hidden = !n;
        st.innerHTML = `<i class="fa-solid fa-triangle-exclamation"></i> ${n} unit(s) ` + (ns ? 'outdated · Update' : 'missing');
        st.title = ns ? 'Library components changed since these units were placed: copy their ports / title again'
                                   : 'The library component of these units no longer exists';
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
        if (this.$('dg-ports-overlay').classList.contains('open')) { if (this._unitSel()) this.renderPorts(); else this.closePorts(); }
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
                    out.push(`<circle cx="${a.x}" cy="${a.y}" r="${hs * 0.6}" class="dg-h dg-h-end${this._attached(it.from) ? ' on' : ''}" data-h="from"/>`);
                    out.push(`<circle cx="${b.x}" cy="${b.y}" r="${hs * 0.6}" class="dg-h dg-h-end${this._attached(it.to) ? ' on' : ''}" data-h="to"/>`);
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
        for (const id of [...this.stale, ...this.missing]) {
            const it = this.R.byId(this.doc, id);
            if (it) out.push(`<rect x="${it.x - 4}" y="${it.y - 4}" width="${it.w + 8}" height="${it.h + 8}" rx="8" class="dg-stale-box${this.missing.has(id) ? ' missing' : ''}"/>`);
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
        if (t === 'unit' && !this.unitPick) return this.openLib();
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
            const mm = it.type === 'unit' ? m + this.R.PORT_STUB + 4 : m;     // port stubs stick out of a unit
            if (p.x >= it.x - mm && p.x <= it.x + it.w + mm && p.y >= it.y - mm && p.y <= it.y + it.h + mm) return it;
        }
        return null;
    },

    /** Wire end attached to something (block / chip / unit port, or a bus line) — moves with it. */
    _attached(end) { return !!(end && (end.id || end.wire)); },

    /** Bus line under point p (for tapping a signal wire into it): {bus, t}. */
    _busAt(p, self) {
        if (self && self.line === 'bus') return null;
        let best = null, bd = 8 / this.view.k + 4;
        for (const b of this.doc.items) {
            if (b.type !== 'wire' || b.line !== 'bus' || b === self || b.from.wire || b.to.wire) continue;
            const pts = this.R.wirePoints(this.doc, b), len = this.R._length(pts) || 1;
            let acc = 0;
            for (let i = 0; i < pts.length - 1; i++) {
                const a = pts[i], c = pts[i + 1], sl = Math.hypot(c.x - a.x, c.y - a.y);
                const dx = c.x - a.x, dy = c.y - a.y, l2 = dx * dx + dy * dy;
                const k = l2 ? Math.max(0, Math.min(1, ((p.x - a.x) * dx + (p.y - a.y) * dy) / l2)) : 0;
                const dd = Math.hypot(p.x - a.x - k * dx, p.y - a.y - k * dy);
                if (dd < bd) { bd = dd; best = { bus: b, t: Math.round((acc + k * sl) / len * 1000) / 1000 }; }
                acc += sl;
            }
        }
        return best;
    },

    _endAt(p, e, skip, self) {
        const tap = !(e && e.altKey) && this.tool !== 'bus' ? this._busAt(p, self) : null;
        const box = this._boxAt(p, skip);
        if (tap && !(box && box.type === 'unit')) return { end: { wire: tap.bus.id, t: tap.t }, box: null, bus: tap.bus };
        if (box && box.type === 'unit' && (box.ports || []).length && !(e && e.altKey)) {
            let best = null, bd = Infinity;
            for (const q of this.R.portPositions(box)) {
                const dd = Math.hypot(q.tx - p.x, q.ty - p.y);
                if (dd < bd) { bd = dd; best = q; }
            }
            return { end: { id: box.id, port: best.port.name }, box };
        }
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

        if (this.tool === 'wire' || this.tool === 'bus') {
            this.snapshot();
            this.sel = [];
            const { end } = this._endAt(p, e, []);
            const w = this._add({ type: 'wire', from: end, to: { x: end.x != null ? end.x : p.x, y: end.y != null ? end.y : p.y },
                                  route: 'ortho', arrow: this.tool === 'bus' ? 'none' : 'end', label: '' });
            if (this.tool === 'bus') w.line = 'bus';
            this.drag = { type: 'end', id: w.id, which: 'to', creating: true, p0: p };
            this.render();
            return;
        }
        if (this.tool === 'block') {
            this.drag = { type: 'create', x0: this._snap(p.x, e), y0: this._snap(p.y, e), x1: this._snap(p.x, e), y1: this._snap(p.y, e) };
            return;
        }
        if (this.tool === 'unit') {
            if (!this.unitPick) { this.setTool('select'); return this.openLib(); }
            this.snapshot();
            const u = this._unitFrom(this.unitPick.master, this.unitPick.ref);
            u.x = this._snap(p.x - u.w / 2); u.y = this._snap(p.y - u.h / 2);
            this._add(u);
            this.lib[this.unitPick.ref] = this.unitPick;
            if (!e.shiftKey) { this.setTool('select'); this.unitPick = null; }   // Shift = place more
            this.markDirty(); this.render(); this.renderProps();
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
                    if (!this._attached(it.from)) it.from = { x: o.from.x + dx, y: o.from.y + dy };
                    if (!this._attached(it.to)) it.to = { x: o.to.x + dx, y: o.to.y + dy };
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
            const { end, box } = this._endAt(p, e, [], w);
            w[dr.which] = end;
            dr.hover = box ? { x: box.x, y: box.y, w: box.w, h: box.h } : null;
            dr.hoverPt = box || end.wire ? this.R.anchor(this.doc, end) : null;
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
            if (w.line !== 'bus' && [w.from, w.to].some(en => this._portType(en) === 'bus')) {   // drawn from a bus port
                w.line = 'bus'; w.arrow = 'none';
            }
        }
        if (dr.type === 'marquee') { this.renderOverlay(); this.renderProps(); return; }
        if ((dr.type === 'move' || dr.type === 'label') && !dr.moved) return;
        this.markDirty();
        this.render();
        this.renderProps();
    },

    _portType(end) {
        const u = end && end.port != null && this.R.byId(this.doc, end.id);
        const p = u && (u.ports || []).find(q => q.name === end.port);
        return p ? p.type || 'io' : null;
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
        if (hit.type === 'unit') return hit.ref ? this.openRef(hit) : this.openPorts();
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
        const ctrl = e.ctrlKey || e.metaKey;
        // letters by physical key: shortcuts work with any keyboard layout (Ukrainian "с" = C)
        const key = /^Key[A-Z]$/.test(e.code) ? e.code.slice(3).toLowerCase() : e.key.toLowerCase();
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
        if (key === 'escape') { this.closeLib(); this.unitPick = null; this.sel = []; this.setTool('select'); this.renderOverlay(); return this.renderProps(); }
        if (key.startsWith('arrow') && this.sel.length) {
            e.preventDefault();
            const st = e.shiftKey ? (this.doc.grid || 10) : 1;
            const d = { arrowleft: [-st, 0], arrowright: [st, 0], arrowup: [0, -st], arrowdown: [0, st] }[key];
            return this.nudge(d[0], d[1]);
        }
        const tools = { v: 'select', b: 'block', c: 'chip', t: 'text', w: 'wire', s: 'bus', l: 'legend' };
        if (tools[key]) return this.setTool(tools[key]);
        if (key === 'u') return this.toggleLib();
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
                if (!this._attached(it.from)) it.from = { x: v.from.x + dx, y: v.from.y + dy };
                if (!this._attached(it.to)) it.to = { x: v.to.x + dx, y: v.to.y + dy };
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
                if ((w[end].id && gone.has(w[end].id)) || (w[end].wire && gone.has(w[end].wire))) {
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
        const ids = new Set(this.sel);
        const items = JSON.parse(JSON.stringify(this.doc.items.filter(i => ids.has(i.id))));
        for (const w of items.filter(i => i.type === 'wire')) {
            for (const end of ['from', 'to']) {      // attached to something not copied: keep the place as a free end
                if ((w[end].id && !ids.has(w[end].id)) || (w[end].wire && !ids.has(w[end].wire))) {
                    const a = this.R.anchor(this.doc, w[end]);
                    w[end] = { x: Math.round(a.x), y: Math.round(a.y) };
                }
            }
        }
        this.clip = JSON.stringify(items);
        try { localStorage.setItem('dg.clip', this.clip); } catch (e) { /* private mode */ }
        toast(`${items.length} item(s) copied`);
    },

    paste() {
        if (!this.clip) { try { this.clip = localStorage.getItem('dg.clip'); } catch (e) { /* private mode */ } }
        if (!this.clip) return;
        this.snapshot();
        const items = JSON.parse(this.clip), map = {}, off = (this.doc.grid || 10) * 2;
        items.forEach(it => { map[it.id] = this._id(it.type); });
        for (const it of items) {
            it.id = map[it.id];
            if (it.type === 'wire') {
                for (const end of ['from', 'to']) {
                    if (it[end].id && map[it[end].id]) it[end].id = map[it[end].id];
                    else if (it[end].wire && map[it[end].wire]) it[end].wire = map[it[end].wire];
                    else if (!this._attached(it[end])) it[end] = { x: it[end].x + off, y: it[end].y + off };
                }
                if (it.via) it.via = it.via.map(([x, y]) => [x + off, y + off]);
            } else { it.x += off; it.y += off; }
            if (it.type === 'unit' && it.master && this.doc.items.some(i => i.type === 'unit' && i.master)) delete it.master;
            if (it.type === 'unit' && it.des && this.doc.items.some(i => i.type === 'unit' && i.des === it.des)) {
                const m = String(it.des).match(/^(.*?)\d*$/);
                it.des = this._nextDes(m[1] || it.des);
            }
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
                    if (!this._attached(it.from)) { it.from.x += dx; it.from.y += dy; }
                    if (!this._attached(it.to)) { it.to.x += dx; it.to.y += dy; }
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
                sel('Line', 'line', [['signal', 'Signal (thin)'], ['bus', 'Bus (thick double line)']]),
                ...(it.line === 'bus' ? [{ label: 'Bus width / name', p: 'busWidth', t: 'text', hint: 'e.g. 8 or SWD — slash mark near the start' },
                    { label: 'Signals', p: 'signals', t: 'text', hint: 'Comma separated, e.g. TXD, RXD. Wires dropped onto the bus are added automatically.' },
                    { t: 'info', text: 'Carried: ' + (this.R.busSignals(this.doc, it).join(', ') || '—') },
                    { label: 'Hide the signal list', p: 'hideSignals', t: 'check' }] : []),
                sel('Arrows', 'arrow', [['end', '→ end'], ['start', '← start'], ['both', '↔ both'], ['none', 'none']]),
                sel('Route', 'route', [['ortho', 'Orthogonal'], ['straight', 'Straight']]),
                { label: 'Dashed', p: 'dashed', t: 'check' }, colorRow('Colour', 'color'), num('Width', 'width'), num('Label size', 'labelSize'),
                { t: 'button', label: 'Reset route & label', act: 'resetWire' }, { t: 'button', label: 'Reverse direction', act: 'reverseWire' },
                { t: 'info', text: 'Double-click the wire to add a bend point, double-click a bend point to remove it. Drag an end onto a block / port to attach it, ' +
                  'onto a bus line to add the signal to the bus (Alt = free). Without an own colour the wire takes the colour of its port type.' }];
            case 'chip': return [{ t: 'button', label: 'Edit pins…', act: 'openPins', cls: 'btn-primary' },
                { t: 'info', text: this.R.SIDES.map(s => `${s}: ${(it.pins[s] || []).length}`).join(' · ') },
                sel('Pin style', 'pinStyle', [['tags', 'Tags (port · function · dir · note)'], ['simple', 'Simple (coloured text)']]),
                sel('Body', 'body', [['module', 'Dark module'], ['outline', 'Light outline']]),
                { label: 'Mounting holes', p: 'holes', t: 'check' }, { label: 'Pin numbers', p: 'numbers', t: 'check' },
                { label: 'Centre chip', p: 'ic.show', t: 'check' }, { label: 'Chip title', p: 'ic.title', t: 'text' },
                { label: 'Chip subtitle', p: 'ic.subtitle', t: 'text' }, { label: 'Caption', p: 'caption', t: 'text' },
                { label: 'Caption 2', p: 'caption2', t: 'text' }, num('Pin margin L/R', 'corner'), num('Pin margin T/B', 'corner2'),
                num('Port tag width', 'portW'), num('Function tag width', 'fnW'), ...pos, ...size];
            case 'legend': return [sel('Shows', 'source', [['kinds', 'Pin kinds (chips)'], ['ports', 'Port types (units)']]),
                ...(it.source === 'ports' ? [] : [sel('Style', 'style', [['tags', 'Tags'], ['swatch', 'Colour squares']])]), num('Font size', 'size'),
                ...(it.source === 'ports' ? [] : [{ t: 'kinds' }]), ...pos];
            case 'unit': {
                const counts = { t: 'info', text: this.R.SIDES.map(sd => `${sd}: ${(it.ports || []).filter(q => q.side === sd).length}`).join(' · ') };
                const tail = [...pos, ...size, { t: 'button', label: 'Auto size', act: 'autoSize' }];
                if (it.ref) return [{ t: 'unitref' }, { label: 'Designator', p: 'des', t: 'text' }, { label: 'Subtitle', p: 'subtitle', t: 'text' },
                    counts, ...tail,
                    { t: 'info', text: 'Category, title and ports come from the library component — edit them there (double-click the unit).' }];
                return [{ t: 'button', label: 'Edit ports…', act: 'openPorts', cls: 'btn-primary' }, counts,
                    sel('Category', 'category', Object.entries(this.R.CATEGORIES).map(([k, c]) => [k, c.label])),
                    { label: 'Title', p: 'title', t: 'text' }, { label: 'Subtitle', p: 'subtitle', t: 'text' },
                    { label: 'Designator', p: 'des', t: 'text' },
                    ...(it.master ? [{ label: 'Designator prefix', p: 'prefix', t: 'text', hint: 'Instances get PREFIX1, PREFIX2…' },
                        sel('Detail', 'detail', [['pins', 'Pin level — every signal'], ['bus', 'Bus level — one port per interface']])] : []),
                    { label: 'Library symbol of this diagram', p: 'master', t: 'check' },
                    { t: 'button', label: 'Load typical ports of the category', act: 'tplPorts' }, ...tail];
            }
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
        if (it.type === 'wire' && p === 'color') return this.R.wireColor(this.doc, Object.assign({}, it, { color: undefined }));
        if (it.type === 'text' && p === 'color') return '#1f2937';
        return '';
    },

    _fieldHtml(it, f) {
        if (f.t === 'button') return `<button class="btn btn-sm ${f.cls || 'btn-ghost'} dg-pbtn" data-act="${f.act}">${esc(f.label)}</button>`;
        if (f.t === 'info') return `<div class="hint dg-pinfo">${esc(f.text)}</div>`;
        if (f.t === 'unitref') {
            const st = this.missing.has(it.id) ? '<span class="text-error"><i class="fa-solid fa-triangle-exclamation"></i> component not found</span>'
                : this.stale.has(it.id) ? '<span class="dg-warn"><i class="fa-solid fa-triangle-exclamation"></i> component changed</span>' +
                  ' <button class="btn btn-warning btn-sm" data-act="updateUnit">Update</button>' : '';
            return `<div class="field dg-unitref"><label>Library component</label>` +
                `<div class="dg-unitref-row">${this._catIcon(it.category)}<span><b>${esc(it.title || it.ref)}</b><br><span class="mono small faint">diagrams/${esc(it.ref)}</span></span></div>` +
                (st ? `<div class="small">${st}</div>` : '') +
                `<button class="btn btn-ghost btn-sm" data-act="openRef"><i class="fa-solid fa-arrow-up-right-from-square"></i> Open component</button></div>`;
        }
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
            const names = { text: 'Text', block: 'Block', wire: 'Wire / arrow', chip: 'Chip / module', legend: 'Legend',
                            unit: it.ref ? 'Unit · ' + this.R.category(it.category).label : it.master ? 'Library symbol' : 'Unit (local)' };
            const fields = this._fields(it);
            let html = `<div class="dg-ptitle"><i class="fa-solid ${this.ICONS[it.type]}"></i> ${names[it.type]}</div><div class="dg-pgrid">`;
            for (const f of fields) html += this._fieldHtml(it, f);
            el.innerHTML = html + '</div>' + this._commonButtons();
            return;
        }
        // nothing selected: the diagram itself + pin kinds
        const d = this.doc, master = this._master();
        const comp = master
            ? `<div class="dg-ptitle dg-sub"><i class="fa-solid fa-cube"></i> Library component</div><div class="dg-pgrid">` +
              `<div class="hint dg-pinfo">${this._catIcon(master.category)} ${esc(this.R.category(master.category).label)} · ${(master.ports || []).length} port(s). ` +
              (this.usedIn.length ? `Placed in: ${this.usedIn.map(esc).join(', ')}.` : 'Not placed in other diagrams yet.') + ' Save, then use the Unit tool (U) elsewhere.</div>' +
              `<button class="btn btn-ghost btn-sm dg-pbtn" data-act="selMaster"><i class="fa-solid fa-arrow-pointer"></i> Select the symbol</button></div>`
            : `<div class="dg-ptitle dg-sub"><i class="fa-solid fa-cube"></i> Library component</div><div class="dg-pgrid">` +
              `<div class="hint dg-pinfo">A diagram with a symbol (category, ports) can be placed on other diagrams as a unit.</div>` +
              `<button class="btn btn-ghost btn-sm dg-pbtn" data-act="makeComponent"><i class="fa-solid fa-plus"></i> Make this diagram a component</button></div>`;
        const auto = this.R.catalogOf(Object.assign({}, d, { catalog: undefined }));
        const catSel = `<div class="field"><label>Catalog (sidebar group)</label><select class="input input-sm" data-dp="catalog">` +
            `<option value="">Auto — ${esc(this.R.CATALOGS[auto].label)}</option>` +
            Object.entries(this.R.CATALOGS).map(([k, c]) => `<option value="${k}"${d.catalog === k ? ' selected' : ''}>${esc(c.label)} — ${esc(c.hint)}</option>`).join('') +
            '</select></div>';
        el.innerHTML = `<div class="dg-ptitle"><i class="fa-solid fa-diagram-project"></i> Diagram</div><div class="dg-pgrid">` +
            this._docField('Title', 'title', 'text') + catSel +
            this._docField('Page width', 'width', 'num') + this._docField('Page height', 'height', 'num') +
            this._docField('Background', 'background', 'color') + this._docField('Grid', 'grid', 'num') +
            `<button class="btn btn-ghost btn-sm dg-pbtn" data-act="fitPage"><i class="fa-solid fa-expand"></i> Fit page to content</button></div>` +
            comp +
            `<div class="dg-ptitle dg-sub">Pin kinds <button class="btn-icon" data-act="addKind" title="Add kind"><i class="fa-solid fa-plus"></i></button></div>` +
            '<div class="dg-kinds">' + Object.entries(d.kinds).map(([k, kd]) => this._kindHtml(k, kd)).join('') + '</div>' +
            '<div class="hint dg-pinfo">Tools: V select · B block · C chip · U unit (library) · T text · W wire · S bus line · L legend. Space/right-drag = pan, wheel = zoom, ' +
            'F = fit, Alt = no snapping, Ctrl+C / Ctrl+V copy (also into another diagram), Ctrl+D duplicate, Delete, Ctrl+Z / Ctrl+Y. ' +
            'Shortcuts work in any keyboard layout.</div>';
    },

    ICONS: { text: 'fa-font', block: 'fa-square', wire: 'fa-arrow-right-long', chip: 'fa-microchip', legend: 'fa-list', unit: 'fa-cube' },

    _catIcon(cat, size = 22) {
        return `<svg class="dg-caticon" width="${size}" height="${size}" viewBox="0 0 32 32">${this.R.icon(cat, 0, 0, 32)}</svg>`;
    },

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
            if (p === 'catalog' && !v) delete this.doc.catalog; else this.doc[p] = v;
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
            if (p === 'master') {
                if (v) this.doc.items.forEach(i => { if (i !== it) delete i.master; });
                else v = undefined;
                if (v && !it.prefix) it.prefix = this.R.category(it.category).prefix;
                if (isChange) setTimeout(() => this.renderProps());
            }
            if (p === 'source' && isChange) setTimeout(() => this.renderProps());
            if (p === 'detail' && v === 'pins') v = undefined;
            if (p === 'line') {
                if (v === 'signal') {
                    v = undefined;
                    for (const w of this.doc.items.filter(i => i.type === 'wire')) {      // signal lines carry no taps
                        for (const end of ['from', 'to']) {
                            if (w[end].wire === it.id) { const a = this.R.anchor(this.doc, w[end]); w[end] = { x: Math.round(a.x), y: Math.round(a.y) }; }
                        }
                    }
                }
                if (isChange) setTimeout(() => this.renderProps());
            }
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
            case 'openPorts': return this.openPorts();
            case 'openRef': return this.openRef(it);
            case 'updateUnit': return this.updateUnits([it.id]);
            case 'selMaster': this.sel = [this._master().id]; this.renderOverlay(); return this.renderProps();
            case 'makeComponent': return this.makeComponent();
            case 'autoSize': this.snapshot(); this._autoSize(it, true); break;
            case 'tplPorts': {
                if ((it.ports || []).length && !confirm('Replace all ports with the typical set of this category?')) return;
                this.snapshot();
                const ports = it.detail === 'bus' ? this._busPorts(it.category) : this._parsePorts(this.UNIT_TEMPLATES[it.category] || '');
                this._detachMissing(it, ports);
                it.ports = ports;
                this._autoSize(it);
                break;
            }
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

    // ── Units / library components ─────────────────────────────

    _master(doc = this.doc) { return doc && doc.items.find(i => i.type === 'unit' && i.master); },

    _parsePorts(spec) {
        const sides = { L: 'left', R: 'right', T: 'top', B: 'bottom' }, out = [];
        for (const part of spec.split(';').filter(Boolean)) {
            const [sd, list] = part.split(':');
            for (const e of (list || '').split(',').filter(Boolean)) {
                const [name, type] = e.split('/');
                out.push({ name, type: type || 'io', side: sides[sd] || 'left', note: '' });
            }
        }
        return out;
    },

    /** Size that fits the ports (pitch, label lengths) and the centre text; `grow` keeps a bigger current size. */
    _autoSize(u, exact) {
        const by = sd => (u.ports || []).filter(p => p.side === sd);
        const L = by('left'), R = by('right'), T = by('top'), B = by('bottom');
        const lab = list => list.reduce((m, p) => Math.max(m, String(p.name || '').length), 0) * 7.3 + 14;
        const P = this.R.PORT_PITCH, g = this.doc.grid || 10, up = v => Math.ceil(v / g) * g;
        const text = Math.max(String(u.title || '').length * 8.6, String(u.subtitle || '').length * 6.6, String(u.des || '').length * 8, 60) + 30;
        const side = (L.length ? lab(L) : 0) + (R.length ? lab(R) : 0);     // top/bottom ports sit between the side label columns
        const w = up(Math.max(160, side + text, side + (Math.max(T.length, B.length) + 1) * P + 10));
        const rows = 36 + (u.des ? 17 : 0) + (u.title ? 19 : 0) + (u.subtitle ? 16 : 0);
        const h = up(Math.max(110, (Math.max(L.length, R.length) + 1) * P, (T.length ? lab(T) : 0) + (B.length ? lab(B) : 0) + rows + 20));
        if (exact) { u.w = w; u.h = h; } else { u.w = Math.max(u.w || 0, w); u.h = Math.max(u.h || 0, h); }
    },

    _newUnit(cat, title) {
        const u = { type: 'unit', x: 0, y: 0, w: 0, h: 0, category: cat, title: title || this.R.category(cat).label, subtitle: '',
                    des: '', ports: this._parsePorts(this.UNIT_TEMPLATES[cat] || '') };
        this._autoSize(u, true);
        return u;
    },

    _nextDes(prefix) {
        const re = new RegExp('^' + prefix.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '(\\d+)$');
        const used = this.doc.items.filter(i => i.type === 'unit').map(i => (String(i.des || '').match(re) || [])[1]).filter(Boolean).map(Number);
        return prefix + (used.length ? Math.max(...used) + 1 : 1);
    },

    /** A new instance of library component `ref` (copy of its master symbol). */
    _unitFrom(master, ref) {
        const prefix = master.prefix || this.R.category(master.category).prefix;
        const u = { type: 'unit', ref, x: 0, y: 0, w: master.w, h: master.h, category: master.category, title: master.title || ref,
                    subtitle: master.subtitle || '', des: this._nextDes(prefix), ports: JSON.parse(JSON.stringify(master.ports || [])) };
        this._autoSize(u);
        return u;
    },

    _libFields(u, ref) { return JSON.stringify({ c: u.category || 'custom', t: u.title || ref, p: (u.ports || []).map(q => [q.name, q.type, q.side, q.note || '']) }); },

    _fetchLib(name) {
        return App.api('/api/help/diagram?name=' + encodeURIComponent(name)).then(d => {
            const master = this._master({ items: (d.data && d.data.items) || [] });
            const e = { ref: name, mtime: d.mtime, master: master || null };
            this.lib[name] = e;
            return e;
        }).catch(() => { delete this.lib[name]; return null; });
    },

    /** Compare every unit with its library component (fetched fresh). */
    checkUnits() {
        const doc = this.doc;
        const refs = [...new Set(doc.items.filter(i => i.type === 'unit' && i.ref).map(i => i.ref))];
        if (!refs.length) return Promise.resolve();
        return Promise.all(refs.map(r => this._fetchLib(r))).then(() => {
            if (this.doc !== doc) return;
            this.stale = new Set(); this.missing = new Set();
            for (const u of doc.items.filter(i => i.type === 'unit' && i.ref)) {
                const e = this.lib[u.ref];
                if (!e || !e.master) this.missing.add(u.id);
                else if (this._libFields(u, u.ref) !== this._libFields(e.master, u.ref)) this.stale.add(u.id);
            }
            this._bar(); this.renderOverlay(); this.renderProps();
        });
    },

    /** Copy category / title / ports from the library again (all outdated units when ids is omitted). */
    updateUnits(ids) {
        ids = ids || [...this.stale].filter(id => this.R.byId(this.doc, id));
        if (!ids.length) return;
        this.snapshot();
        for (const id of ids) {
            const u = this.R.byId(this.doc, id), e = u && this.lib[u.ref];
            if (!e || !e.master) continue;
            const ports = JSON.parse(JSON.stringify(e.master.ports || []));
            this._detachMissing(u, ports);
            Object.assign(u, { category: e.master.category, title: e.master.title || u.ref, ports });
            this._autoSize(u);
            this.stale.delete(id);
        }
        this.markDirty(); this.render(); this.renderProps();
        toast(`${ids.length} unit(s) updated`);
    },

    /** Wires attached to ports of `u` that are not in `ports` keep their current position as free ends. */
    _detachMissing(u, ports) {
        const names = new Set(ports.map(p => p.name));
        for (const w of this.doc.items.filter(i => i.type === 'wire')) {
            for (const end of ['from', 'to']) {
                if (w[end].id === u.id && w[end].port != null && !names.has(w[end].port)) {
                    const a = this.R.anchor(this.doc, w[end]);
                    w[end] = { x: Math.round(a.x), y: Math.round(a.y) };
                }
            }
        }
    },

    openRef(u) {
        if (!u || !u.ref) return;
        if (u.ref === this.name) return;
        Help.openDiagram(u.ref);
    },

    makeComponent() {
        if (this._master()) return;
        this.snapshot();
        const u = this._newUnit('custom', this.doc.title || this.name);
        u.master = true; u.prefix = this.R.category('custom').prefix;
        u.x = this._snap((this.doc.width - u.w) / 2); u.y = this._snap((this.doc.height - u.h) / 2);
        this._add(u);
        this.markDirty(); this.render(); this.renderProps();
        toast('Symbol added: pick a category, edit ports, save');
    },

    // Library popover (Unit tool)

    openLib() {
        const el = this.$('dg-lib');
        el.hidden = false;
        this.$('dg-lib-q').value = '';
        this.renderLib();
        this.loadList().then(() => this.renderLib());
        setTimeout(() => this.$('dg-lib-q').focus());
        if (!this._libClose) {
            this._libClose = e => { if (!e.target.closest('#dg-lib, [data-tool="unit"]')) this.closeLib(); };
            document.addEventListener('mousedown', this._libClose);
        }
    },

    closeLib() {
        const el = this.$('dg-lib');
        if (el) el.hidden = true;
        if (this._libClose) { document.removeEventListener('mousedown', this._libClose); this._libClose = null; }
    },

    toggleLib() { if (this.$('dg-lib').hidden) this.openLib(); else this.closeLib(); },

    renderLib() {
        const q = this.$('dg-lib-q').value.trim().toLowerCase();
        const comps = this.list.filter(d => d.component && d.name !== this.name &&
            (!q || (d.title + ' ' + d.name + ' ' + this.R.category(d.component.category).label).toLowerCase().includes(q)));
        const groups = [];
        for (const cl of ['assembly', 'bus', 'component', 'uut', 'station']) {
            const inCl = comps.filter(d => (d.catalog || 'component') === cl);
            if (cl !== 'component' && cl !== 'bus') { if (inCl.length) groups.push([this.R.CATALOGS[cl].label, inCl]); continue; }
            Object.entries(this.R.COMPONENT_GROUPS).forEach(([g, gr]) => {
                const l = inCl.filter(d => this.R.componentGroup(d.component.category) === g)
                    .sort((a, b) => gr.cats.indexOf(a.component.category) - gr.cats.indexOf(b.component.category) || a.title.localeCompare(b.title));
                if (l.length) groups.push([(cl === 'bus' ? 'Bus level · ' : '') + gr.label, l]);
            });
        }
        this.$('dg-lib-list').innerHTML = groups.map(([label, l]) =>
            `<div class="dg-lib-cat">${esc(label)}</div>` + l.map(d =>
                `<button type="button" class="dg-lib-item" data-ref="${esc(d.name)}" title="diagrams/${esc(d.name)} · ${d.component.ports} port(s)">` +
                `${this._catIcon(d.component.category)}<span>${esc(d.title)}<small class="mono faint">${esc(d.name)}</small></span>` +
                `<span class="faint small">${d.component.ports}</span></button>`).join('')).join('') ||
            `<div class="tbl-empty small">${q ? 'Nothing found.' : 'No library components yet. Create one: a new diagram from a “Library component” template, or “Make this diagram a component”.'}</div>`;
    },

    libClick(e) {
        const b = e.target.closest('[data-ref]');
        if (!b) return;
        this._fetchLib(b.dataset.ref).then(en => {
            if (!en || !en.master) return toast('This component has no symbol', true);
            this.unitPick = en;
            this.closeLib();
            this.tool = 'unit'; this._bar(); this._cursor();
            toast(`Click on the page to place “${en.master.title || en.ref}” (Shift+click = several)`);
        });
    },

    newComponent() { this.closeLib(); this.openNew('comp:custom'); },

    // ── Port table (unit symbol) ───────────────────────────────

    _unitSel() { const it = this.R.byId(this.doc, this.sel[0]); return it && it.type === 'unit' && !it.ref ? it : null; },

    openPorts() {
        const u = this._unitSel();
        if (!u) return;
        this.$('dg-ports-title').textContent = 'Ports — ' + (u.title || u.des || 'unit');
        this.$('dg-ports-overlay').classList.add('open');
        this._propUndo = false;
        this.renderPorts();
    },

    closePorts() {
        this.$('dg-ports-overlay').classList.remove('open');
        this.renderProps();
    },

    renderPorts() {
        const u = this._unitSel();
        if (!u) return;
        const ports = u.ports = u.ports || [];
        const count = {};
        ports.forEach(p => { count[p.name] = (count[p.name] || 0) + 1; });
        const opt = (list, v) => list.map(([k, l]) => `<option value="${esc(k)}"${k === v ? ' selected' : ''}>${esc(l)}</option>`).join('');
        const types = Object.entries(this.R.PORT_TYPES).map(([k, t]) => [k, t.label === k ? k : `${k} — ${t.label}`]);
        const sides = this.R.SIDES.map(sd => [sd, sd]);
        this.$('dg-ports-body').innerHTML = !ports.length ? '<div class="tbl-empty">No ports. Add rows or paste them from a spreadsheet (name, type, side, note).</div>' :
            '<table class="tbl dg-pins dg-ports"><thead><tr><th>#</th><th>Name</th><th>Type</th><th>Side</th><th>Note</th><th></th></tr></thead><tbody>' +
            ports.map((p, i) => `<tr data-i="${i}"><td class="faint small">${i + 1}</td>` +
                `<td><input class="input input-sm mono dg-port-name${count[p.name] > 1 || !p.name ? ' dg-dup' : ''}" data-i="${i}" data-f="name" value="${esc(p.name || '')}"` +
                `${count[p.name] > 1 ? ' title="Duplicate name: wires attach to the first one"' : ''}></td>` +
                `<td><span class="dg-port-sw" style="background:${esc(this.R.portType(p.type).color)}"></span><select class="input input-sm" data-i="${i}" data-f="type">${opt(types, p.type || 'io')}</select></td>` +
                `<td><select class="input input-sm" data-i="${i}" data-f="side">${opt(sides, p.side || 'left')}</select></td>` +
                `<td><input class="input input-sm" data-i="${i}" data-f="note" value="${esc(p.note || '')}"></td>` +
                `<td class="dg-row-act"><button class="btn-icon" data-pa="up:${i}" title="Move up"><i class="fa-solid fa-arrow-up"></i></button>` +
                `<button class="btn-icon" data-pa="down:${i}" title="Move down"><i class="fa-solid fa-arrow-down"></i></button>` +
                `<button class="btn-icon" data-pa="ins:${i}" title="Insert below"><i class="fa-solid fa-plus"></i></button>` +
                `<button class="btn-icon" data-pa="del:${i}" title="Delete"><i class="fa-solid fa-xmark"></i></button></td></tr>`).join('') +
            '</tbody></table>';
    },

    _portsChanged(rerender) {
        const u = this._unitSel();
        if (u) this._autoSize(u);
        this.markDirty();
        this._schedule();
        if (rerender) this.renderPorts();
    },

    _portInput(e) {
        const t = e.target, u = this._unitSel();
        if (t.dataset.f == null || !u) return;
        if (!this._propUndo) { this.snapshot(); this._propUndo = true; }
        const p = u.ports[+t.dataset.i];
        if (!p) return;
        const f = t.dataset.f;
        if (f === 'name') {                            // keep attached wires on the renamed port
            const old = p.name;
            if (!u.ports.some((q, k) => q.name === old && k !== +t.dataset.i)) {
                this.doc.items.filter(i => i.type === 'wire').forEach(w => ['from', 'to'].forEach(end => {
                    if (w[end].id === u.id && w[end].port === old) w[end].port = t.value;
                }));
            }
        }
        p[f] = t.value;
        this._portsChanged(e.type === 'change' && f !== 'note');
    },

    _portRemove(u, i) {
        const rest = u.ports.filter((_, k) => k !== i);
        this._detachMissing(u, rest);
        u.ports.splice(i, 1);
    },

    _portClick(e) {
        const b = e.target.closest('[data-pa]'), u = this._unitSel();
        if (!b || !u) return;
        const [act, s] = b.dataset.pa.split(':'), i = +s, ports = u.ports;
        this.snapshot();
        if (act === 'up' && i > 0) [ports[i - 1], ports[i]] = [ports[i], ports[i - 1]];
        if (act === 'down' && i < ports.length - 1) [ports[i + 1], ports[i]] = [ports[i], ports[i + 1]];
        if (act === 'del') this._portRemove(u, i);
        if (act === 'ins') ports.splice(i + 1, 0, this._nextPort(ports, ports[i]));
        this._portsChanged(true);
    },

    /** Next port after `prev`: same type/side, name with the trailing number + 1 (CH3 → CH4). */
    _nextPort(ports, prev) {
        const names = new Set(ports.map(p => p.name));
        let name = '';
        const m = prev && String(prev.name || '').match(/^(.*?)(\d+)(\D*)$/);
        if (m) { let n = +m[2]; do { name = m[1] + (++n) + m[3]; } while (names.has(name)); }
        return { name, type: prev ? prev.type : 'io', side: prev ? prev.side : 'left', note: '' };
    },

    portCmd(cmd) {
        const u = this._unitSel();
        if (!u) return;
        const ports = u.ports;
        if (cmd === 'add') {
            const ans = prompt('Add ports: name pattern with {n}, first number, count, type, side\ne.g. "CH{n}, 1, 8, analog, left"', 'CH{n}, 1, 8, analog, left');
            if (!ans) return;
            const [pat, first, count, type, side] = ans.split(',').map(v => v.trim());
            const n0 = parseInt(first, 10), cnt = Math.max(1, Math.min(256, parseInt(count, 10) || 1));
            if (!pat) return;
            const tp = this.R.PORT_TYPES[type] ? type : 'io', sd = this.R.SIDES.includes(side) ? side : 'left';
            this.snapshot();
            for (let k = 0; k < cnt; k++) {
                ports.push({ name: pat.includes('{n}') ? pat.replace('{n}', (isNaN(n0) ? 1 : n0) + k) : (cnt > 1 ? pat + ((isNaN(n0) ? 1 : n0) + k) : pat),
                             type: tp, side: sd, note: '' });
            }
        } else if (cmd === 'sort') {
            this.snapshot();
            const order = this.R.SIDES;
            const idx = new Map(ports.map((p, i) => [p, i]));
            ports.sort((a, b) => order.indexOf(a.side) - order.indexOf(b.side) || idx.get(a) - idx.get(b));
        } else if (cmd === 'clear') {
            if (!ports.length || !confirm(`Delete all ${ports.length} ports?`)) return;
            this.snapshot();
            this._detachMissing(u, []);
            ports.length = 0;
        } else if (cmd === 'copy') {
            Help.copyText(ports.map(p => this.PORT_FIELDS.map(f => p[f] == null ? '' : p[f]).join('\t')).join('\n'));
            return toast('Copied as TSV (paste into Excel)');
        }
        this._portsChanged(true);
    },

    /** Paste rows (name, type, side, note — TSV or ; / , separated) starting at the focused cell. */
    _portPaste(e) {
        const text = (e.clipboardData || window.clipboardData).getData('text');
        if (!text || (!text.includes('\t') && !text.includes('\n'))) return;
        e.preventDefault();
        const u = this._unitSel();
        if (!u) return;
        const t = e.target.closest('[data-f]'), ports = u.ports;
        const row0 = t ? +t.dataset.i : ports.length, col0 = t ? this.PORT_FIELDS.indexOf(t.dataset.f) : 0;
        const lines = text.replace(/\r/g, '').split('\n').filter((l, k, a) => l.trim() || k < a.length - 1);
        const sep = text.includes('\t') ? '\t' : (text.includes(';') ? ';' : ',');
        const types = this.R.PORT_TYPES;
        const toType = v => {
            const s = v.toLowerCase();
            return types[s] ? s : (Object.keys(types).find(k => types[k].label === s) || 'io');
        };
        this.snapshot();
        lines.forEach((line, k) => {
            const p = ports[row0 + k] || (ports[row0 + k] = { name: '', type: 'io', side: 'left', note: '' });
            line.split(sep).forEach((v, c) => {
                const f = this.PORT_FIELDS[col0 + c];
                if (!f) return;
                v = v.trim();
                p[f] = f === 'type' ? toType(v) : f === 'side' ? (this.R.SIDES.includes(v.toLowerCase()) ? v.toLowerCase() : 'left') : v;
            });
        });
        this._portsChanged(true);
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
            toast('Renamed' + (r.docs.length ? `, links fixed in ${r.docs.length} doc(s)` : '') +
                  (r.diagrams && r.diagrams.length ? `, units relinked in ${r.diagrams.length} diagram(s)` : ''));
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
        const warn = (this.usedBy.length ? `\n\nIt is used in:\n${this.usedBy.join('\n')}` : '') +
            (this.usedIn.length ? `\n\nIt is placed as a unit in diagrams:\n${this.usedIn.join('\n')}\n(their units keep the copy but are marked as missing)` : '');
        if (!confirm(`Delete diagram "${this.name}"? It is moved to .trash.${warn}`)) return;
        App.api('/api/help/diagram/delete', { json: { name: this.name } }).then(() => {
            toast('Moved to .trash');
            this.dirty = false;
            this.close();
            this.loadList();
        }).catch(e => toast(e.message, true));
    },

    // ── New diagram ────────────────────────────────────────────

    openNew(tpl) {
        if (!Help._leaveEditors()) return;
        this._copyMode = false;
        this._newMode();
        if (tpl) this.$('dg-new-tpl').value = tpl;
        this.$('dg-new-title').value = '';
        this.$('dg-new-name').value = '';
        this._newNameTouched = false;
        this.$('dg-new-overlay').classList.add('open');
        this.$('dg-new-title').focus();
    },

    closeNew() { this.$('dg-new-overlay').classList.remove('open'); this._copyMode = false; this._copySrc = null; },

    _newMode() {
        const src = this._copySrc, copy = this._copyMode && src, m = copy && this._master(src.doc);
        this.$('dg-new-head').textContent = copy ? 'Duplicate diagram' : 'New diagram';
        const show = (id, on) => { this.$(id).style.display = on ? '' : 'none'; };
        show('dg-new-tpl-field', !copy); show('dg-new-copy', copy); show('dg-new-cat-field', !!m);
        if (!copy) return;
        this.$('dg-new-catalog').innerHTML = `<option value="">Auto</option>` + Object.entries(this.R.CATALOGS).map(([k, c]) =>
            `<option value="${k}"${src.doc.catalog === k ? ' selected' : ''}>${esc(c.label)}</option>`).join('');
        this.$('dg-new-cat').innerHTML = Object.entries(this.R.CATEGORIES).map(([k, c]) =>
            `<option value="${k}"${m && m.category === k ? ' selected' : ''}>${esc(c.label)}</option>`).join('');
    },

    /** Copy a diagram under a new name (the open one with its unsaved changes, or `name` from the sidebar):
        e.g. a variant of a relay / a new instrument version, in the same catalog and category by default. */
    duplicate(name) {
        const own = !name || (this.doc && name === this.name);
        if (own && !this.doc) return;
        if (!own && !Help._leaveEditors()) return;
        const src = own ? Promise.resolve({ name: this.name, doc: this.doc, own: true })
            : App.api('/api/help/diagram?name=' + encodeURIComponent(name)).then(d => ({ name: d.name, doc: this._normalize(d.data) }));
        src.then(sd => {
            this._copySrc = sd; this._copyMode = true;
            this._newMode();
            const names = new Set(this.list.map(d => d.name));
            let n = sd.name + '_copy', k = 2;
            while (names.has(n)) n = `${sd.name}_copy${k++}`;
            this.$('dg-new-title').value = (sd.doc.title || sd.name) + ' (copy)';
            this.$('dg-new-name').value = n;
            this._newNameTouched = false;              // typing a new title renames the file too
            this.$('dg-new-overlay').classList.add('open');
            this.$('dg-new-title').select();
        }).catch(e => toast(e.message, true));
    },

    _copyData(title) {
        const src = this._copySrc, data = JSON.parse(JSON.stringify(src.doc)), old = data.title || src.name;
        data.title = title;
        data.items.forEach(i => { if (i.type === 'text' && i.text === old) i.text = title; });
        const m = this._master(data);
        if (m) {
            if (!m.title || m.title === old) m.title = title;
            m.category = this.$('dg-new-cat').value || m.category;
        }
        const cl = this.$('dg-new-catalog').value;
        if (cl) data.catalog = cl; else delete data.catalog;
        return data;
    },

    newInput(e) {
        if (e.target.id === 'dg-new-name') this._newNameTouched = true;
        else if (!this._newNameTouched) {
            this.$('dg-new-name').value = e.target.value.trim().replace(/[^\p{L}\p{N}._-]+/gu, '_').replace(/^[_.]+|_+$/g, '').slice(0, 80);
        }
    },

    submitNew() {
        const name = this.$('dg-new-name').value.trim(), title = this.$('dg-new-title').value.trim() || name;
        if (!name) return toast('Enter a name', true);
        const data = this._copyMode ? this._copyData(title) : this.template(this.$('dg-new-tpl').value, title);
        const ownCopy = this._copyMode && this._copySrc && this._copySrc.own;
        App.api('/api/help/diagram/create', { json: { name, data, svg: this.R.toSvg(data) } }).then(r => {
            this.closeNew();
            if (ownCopy) this.dirty = false;           // the copy carries the changes; the original stays as saved
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
        } else if (kind === 'station') {
            Object.assign(doc, { width: 1800, height: 1100, catalog: 'station' });
            add({ type: 'text', x: 60, y: 98, text: 'Test station: place instruments, jigs and the DUT with the Unit tool (U), connect their ports with wires.', size: 16, color: '#6b7280' });
            add({ type: 'block', x: 40, y: 130, w: 1720, h: 900, title: 'ST1 · Test station', lines: [], style: 'plain', stroke: '#9ca3af', dashed: true, radius: 14 });
            add({ type: 'legend', x: 70, y: 1070, source: 'ports' });
        } else if (kind.startsWith('comp:') || kind.startsWith('bus:')) {
            const bus = kind.startsWith('bus:'), key = kind.slice(kind.indexOf(':') + 1);
            const cat = this.R.CATEGORIES[key] ? key : 'custom';
            add({ type: 'text', x: 60, y: 98, text: `Library component · ${this.R.category(cat).label}. Edit the ports of the symbol (double-click it), save, ` +
                  'then place it on other diagrams with the Unit tool.', size: 14, color: '#6b7280' });
            const u = add(this._newUnit(cat, title));
            u.master = true; u.prefix = this.R.category(cat).prefix;
            if (bus) { u.detail = 'bus'; u.ports = this._busPorts(cat); this._autoSize(u, true); }
            Object.assign(doc, { width: Math.max(1000, u.w + 300), height: Math.max(560, u.h + 260) });
            u.x = Math.round((doc.width - u.w) / 20) * 10; u.y = 160;
            add({ type: 'legend', x: 60, y: doc.height - 40, source: 'ports' });
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
