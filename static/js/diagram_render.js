/* ==========================================================================
   Diagram model -> SVG (used by the editor in static/js/diagrams.js and for the exported .svg).

   Model (help_dir/diagrams/<name>.json):
     { version: 1, title, width, height, background, grid, kinds: {key: Kind}, items: [Item] }
   Kind  (pin style):  { label, fill, stroke, text, dash, badge, sample, color }   ("free" = unused pin)
   Items (z-order = array order), every item has a unique id:
     text   { x, y, text, size, weight, color, font: sans|mono, anchor: start|middle|end, rotate: 0|-90, italic }
     block  { x, y, w, h, title, lines[] ("`" prefix = monospace), style: light|dark|accent|note|plain,
              fill, stroke, titleColor, textColor, dashed, titleSize, lineSize, radius, align: left|center }
     chip   { x, y, w, h, body: module|outline, holes, ic: {show, title, subtitle}, caption, caption2,
              pinStyle: tags|simple, corner (left/right margin), corner2 (top/bottom), portW, fnW, numbers,
              pins: { left|right|top|bottom: [{ n, port, fn, kind, badge, note }] } }
     wire   { from, to: {id, side, t} | {x, y},  via: [[x, y]], route: ortho|straight, label, labelDx, labelDy,
              arrow: end|start|both|none, dashed, color, width, labelSize,
              line: bus (thick double line, default width 5), busWidth ("8", "SWD": slash mark + text near the start),
              signals: "TXD, RXD" (bus: carried signals, plus the wires tapped into it), hideSignals }
            A wire end may also sit on a bus line: {wire: "<bus id>", t: 0..1 (fraction of its length)} — only signal
            wires tap buses (bus ends never do, so anchors cannot recurse). Colour of a wire without `color` = colour of
            the type of the port it starts from (else the port it ends on); ports on the far end adopt the wire colour.
   Optional doc.catalog: station|assembly|bus|component|uut|diagram (sidebar group; derived from the content when absent).
     legend { x, y, source: kinds|ports, kinds: [keys] | null (= used ones), style: tags|swatch, size }
     unit   { x, y, w, h, category (CATEGORIES key), title, subtitle, des (designator, e.g. MUX1),
              ports: [{ name, type (PORT_TYPES key), side: left|right|top|bottom, note }],
              ref: "<diagram name>"   – an instance of a library component: category/title/ports are a copy of
                                        that diagram's symbol (refreshed by the editor), des/subtitle/size are own;
              master: true, prefix    – the symbol of this diagram = it is a library component (one per diagram),
              detail: pins|bus        – master only: pin level (every signal) or bus level (one port per interface) }
   Wire ends attach to a block/chip side {id, side, t} or to a unit port {id, port: "<name>"}.
   Ports of a side are placed in list order (left/right: top → bottom, top/bottom: left → right), PORT_PITCH apart.
   ========================================================================== */

const DiagramRender = {
    SANS: "'Segoe UI', Arial, sans-serif",
    MONO: "Consolas, 'DejaVu Sans Mono', monospace",
    INK: '#1f2937', MUTED: '#6b7280', FAINT: '#9ca3af',
    SIDES: ['left', 'top', 'right', 'bottom'],

    DEFAULT_KINDS: {
        out:  { label: 'output',             fill: '#1f2937', stroke: '#1f2937', text: '#ffffff', dash: '',    badge: 'OUT', sample: 'OUT',  color: '#1f2937' },
        in:   { label: 'input',              fill: '#ffffff', stroke: '#1f2937', text: '#1f2937', dash: '',    badge: 'IN',  sample: 'IN',   color: '#374151' },
        bus:  { label: 'bus / peripheral',   fill: '#e7e5e4', stroke: '#a8a29e', text: '#292524', dash: '',    badge: '',    sample: 'BUS',  color: '#0e9488' },
        pwr:  { label: 'power',              fill: '#f6eeee', stroke: '#b08a8a', text: '#7a2e2e', dash: '',    badge: '',    sample: '5V',   color: '#dc2626' },
        pwm:  { label: 'PWM',                fill: '#fbf6ee', stroke: '#a16a2a', text: '#7c4a12', dash: '5 3', badge: 'PWM', sample: 'PWM',  color: '#d6157a' },
        nc:   { label: 'wired, not in code', fill: '#6b7280', stroke: '#6b7280', text: '#ffffff', dash: '',    badge: '—',   sample: 'NC',   color: '#6b7280' },
        free: { label: 'free',               fill: '#ffffff', stroke: '#d1d5db', text: '#9ca3af', dash: '',    badge: '',    sample: 'FREE', color: '#9ca3af' },
    },

    /** Library element categories (unit items): symbol colour, designator prefix, pictogram (32×32 stroke paths). */
    CATEGORIES: {
        dut:     { label: 'DUT / UUT',          prefix: 'DUT',  color: '#be185d', icon: '<rect x="9" y="9" width="14" height="14" rx="1.5"/><path d="M9 12.5H4M9 16H4M9 19.5H4M23 12.5h5M23 16h5M23 19.5h5M12.5 9V4M19.5 9V4M12.5 23v5M19.5 23v5"/>' },
        scope:   { label: 'Oscilloscope', prefix: 'OSC',  color: '#0e7490', icon: '<rect x="3" y="5" width="26" height="19" rx="2"/><path d="M6 17c2.5-9 5-9 7 0s4.5 7 7 0 3.5-5 6-3M11 28h10"/>' },
        gen:     { label: 'Generator',    prefix: 'GEN',  color: '#7c3aed', icon: '<circle cx="16" cy="16" r="12"/><path d="M8.5 16c2-8 5.5-8 7.5 0s5.5 8 7.5 0"/>' },
        psu:     { label: 'Power supply', prefix: 'PSU',  color: '#dc2626', icon: '<rect x="3" y="7" width="26" height="18" rx="2"/><path d="M8 16h7M11.5 12.5v7M18 16h7"/>' },
        dmm:     { label: 'Multimeter',   prefix: 'DMM',  color: '#0d9488', icon: '<rect x="7" y="3" width="18" height="26" rx="3"/><rect x="10" y="6.5" width="12" height="6" rx="1"/><circle cx="16" cy="21" r="4"/><path d="M16 21l2.5-2.5"/>' },
        io:      { label: 'IO block',     prefix: 'IO',   color: '#2563eb', icon: '<rect x="3" y="8" width="26" height="16" rx="2"/><circle cx="8.5" cy="13" r="1.8"/><circle cx="14" cy="13" r="1.8"/><circle cx="19.5" cy="13" r="1.8"/><circle cx="25" cy="13" r="1.2"/><path d="M7 19.5h18"/>' },
        pc:      { label: 'Computer',     prefix: 'PC',   color: '#374151', icon: '<rect x="3" y="4" width="26" height="17" rx="2"/><path d="M16 21v5M10 27h12"/>' },
        mux:     { label: 'Multiplexer',  prefix: 'MUX',  color: '#a16207', icon: '<path d="M9 4l14 6v12L9 28z"/><path d="M3 9h6M3 16h6M3 23h6M23 16h6M16 25v4"/>' },
        relay:   { label: 'Relay',        prefix: 'K',    color: '#ea580c', icon: '<rect x="3" y="10" width="9" height="12" rx="1"/><path d="M12 16h4" stroke-dasharray="2 2"/><circle cx="19" cy="22" r="1.6"/><path d="M19 22l8-9M26 9h4M3 6h9"/>' },
        ctrl:    { label: 'Controller',   prefix: 'CTRL', color: '#4f46e5', icon: '<rect x="3" y="6" width="26" height="20" rx="2"/><rect x="11" y="11" width="10" height="10" rx="1"/><path d="M14 11V8M18 11V8M14 24v-3M18 24v-3M8 11h1M8 16h1M8 21h1"/>' },
        prog:    { label: 'Programmer',   prefix: 'PRG',  color: '#15803d', icon: '<rect x="3" y="8" width="14" height="16" rx="2"/><path d="M7 13h6M7 17h4M17 13h5M17 16h5M17 19h5"/><rect x="22" y="10" width="7" height="12" rx="1"/>' },
        adapter: { label: 'Interface adapter', prefix: 'ADP', color: '#0369a1', icon: '<rect x="3" y="12" width="7" height="8" rx="1"/><path d="M5.5 15h2M5.5 17h2M10 16h5"/><rect x="15" y="9" width="14" height="14" rx="2"/><path d="M19 13h6M19 16h6M19 19h6"/>' },
        hub:     { label: 'Hub / switch', prefix: 'HUB',  color: '#4d7c0f', icon: '<rect x="10" y="11" width="10" height="10" rx="1.5"/><path d="M3 16h7M20 16h4M24 7v18M24 7h5M24 16h5M24 25h5"/>' },
        iso:     { label: 'Isolator',     prefix: 'ISO',  color: '#c026d3', icon: '<rect x="3" y="7" width="26" height="18" rx="2"/><path d="M16 4v24" stroke-dasharray="3 2.5"/><path d="M6 16h6M9.5 13l3 3-3 3M20 16h6M23.5 13l3 3-3 3"/>' },
        jig:     { label: 'Test jig',     prefix: 'JIG',  color: '#57534e', icon: '<rect x="4" y="4" width="24" height="5" rx="1"/><path d="M9 9v10M16 9v12M23 9v10"/><rect x="3" y="22" width="26" height="6" rx="1"/>' },
        station: { label: 'Test station', prefix: 'ST',   color: '#1f2937', icon: '<rect x="6" y="3" width="20" height="26" rx="1.5"/><path d="M6 11h20M6 19h20"/><circle cx="10" cy="7" r="1"/><circle cx="10" cy="15" r="1"/><circle cx="10" cy="23" r="1"/>' },
        custom:  { label: 'Other',        prefix: 'U',    color: '#6b7280', icon: '<path d="M16 4l11 6v12l-11 6-11-6V10z"/><path d="M5 10l11 6 11-6M16 16v12"/>' },
    },

    /** Unit port types: colour + marker on the pin stub. */
    PORT_TYPES: {
        in:     { label: 'input',          color: '#2563eb', mark: 'in' },
        out:    { label: 'output',         color: '#ea580c', mark: 'out' },
        io:     { label: 'bidirectional',  color: '#7c3aed', mark: 'io' },
        analog: { label: 'analog',         color: '#0d9488', mark: 'dot' },
        tp:     { label: 'test point',     color: '#be185d', mark: 'tp' },
        pwr:    { label: 'power',          color: '#dc2626', mark: 'sq' },
        gnd:    { label: 'ground',         color: '#374151', mark: 'gnd' },
        bus:    { label: 'bus / interface', color: '#a16207', mark: 'bus' },
        nc:     { label: 'not connected',  color: '#9ca3af', mark: 'nc' },
    },
    PORT_PITCH: 20, PORT_STUB: 16,

    /** Catalogs = sidebar groups of diagrams (doc.catalog, or derived by catalogOf; same rule in core/diagrams.py). */
    CATALOGS: {
        station:   { label: 'Test stations',      icon: 'fa-industry',        hint: 'whole stations: instruments + jig + UUT' },
        assembly:  { label: 'Jigs & assemblies',  icon: 'fa-cubes',           hint: 'jigs and boards built of components' },
        bus:       { label: 'Bus-level modules',  icon: 'fa-grip-lines',      hint: 'one port per interface (SWD, UART, I²C…), no power — for station overviews' },
        component: { label: 'Components (pin level)', icon: 'fa-cube',        hint: 'every signal: instruments, programmers, controllers, mux, relays…' },
        uut:       { label: 'UUT (products)',     icon: 'fa-box-open',        hint: 'products under test (DUT symbols)' },
        diagram:   { label: 'Pinouts & diagrams', icon: 'fa-diagram-project', hint: 'pinouts and block diagrams' },
    },

    /** Sub-groups of the Components catalog (sidebar, library popover) by symbol category. */
    COMPONENT_GROUPS: {
        instruments: { label: 'Instruments',  icon: 'fa-wave-square', cats: ['scope', 'gen', 'psu', 'dmm'] },
        programming: { label: 'Programmers',  icon: 'fa-bug',         cats: ['prog'] },
        interfaces:  { label: 'Interfaces, hubs & isolation', icon: 'fa-plug', cats: ['adapter', 'hub', 'iso'] },
        control:     { label: 'Control & IO', icon: 'fa-microchip',   cats: ['pc', 'ctrl', 'io'] },
        switching:   { label: 'Switching',    icon: 'fa-shuffle',     cats: ['mux', 'relay'] },
        other:       { label: 'Other',        icon: 'fa-shapes',      cats: ['custom', 'dut', 'jig', 'station'] },
    },

    componentGroup(cat) {
        return Object.keys(this.COMPONENT_GROUPS).find(g => this.COMPONENT_GROUPS[g].cats.includes(cat)) || 'other';
    },

    catalogOf(doc) {
        if (doc.catalog && this.CATALOGS[doc.catalog]) return doc.catalog;
        const items = doc.items || [], m = items.find(i => i.type === 'unit' && i.master);
        const units = items.some(i => i.type === 'unit' && !i.master);
        if (m) {
            if (m.category === 'station') return 'station';
            if (m.category === 'dut') return 'uut';
            if (units || m.category === 'jig') return 'assembly';
            return m.detail === 'bus' ? 'bus' : 'component';
        }
        return units ? 'station' : 'diagram';
    },

    BLOCK_STYLES: {
        light:  { fill: '#ffffff', stroke: '#57534e', title: '#1f2937', text: '#6b7280' },
        dark:   { fill: '#2b3440', stroke: '#2b3440', title: '#f9fafb', text: '#cbd5e1' },
        accent: { fill: '#ffffff', stroke: '#a16a2a', title: '#1f2937', text: '#6b7280' },
        note:   { fill: '#fbf6ee', stroke: '#e7d8bf', title: '#7c4a12', text: '#78716c' },
        plain:  { fill: 'none',    stroke: 'none',    title: '#1f2937', text: '#6b7280' },
    },

    esc(s) {
        return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    },
    num(v) { return Math.round(v * 100) / 100; },

    newDoc(title) {
        return { version: 1, title: title || 'Diagram', width: 1600, height: 1000, background: '#fafaf9', grid: 10,
                 kinds: JSON.parse(JSON.stringify(this.DEFAULT_KINDS)), items: [] };
    },

    kind(doc, key) {
        const k = (doc.kinds || {})[key] || this.DEFAULT_KINDS[key];
        return k || this.DEFAULT_KINDS.out;
    },

    byId(doc, id) { return doc.items.find(i => i.id === id); },

    // ── Geometry ───────────────────────────────────────────────

    /** Point on a block/chip side for a wire end {id, side, t}; free ends {x, y} pass through. */
    anchor(doc, end) {
        if (!end) return { x: 0, y: 0, side: null };
        if (end.wire) {
            const bus = this.byId(doc, end.wire);
            if (bus && bus.type === 'wire' && !bus.from.wire && !bus.to.wire) {
                const pts = this.wirePoints(doc, bus), len = this._length(pts);
                const q = this._along(pts, (end.t == null ? 0.5 : end.t) * len);
                return { x: q.x, y: q.y, side: null, tx: q.tx, ty: q.ty };
            }
            return { x: end.x || 0, y: end.y || 0, side: null };
        }
        if (end.id) {
            const it = this.byId(doc, end.id);
            if (it && it.type === 'unit' && end.port != null) {
                const pp = this.portPositions(it).find(q => q.port.name === end.port);
                if (pp) return { x: pp.tx, y: pp.ty, side: pp.side };
                return { x: it.x, y: it.y + it.h / 2, side: 'left' };     // port gone: left middle
            }
            if (it && it.w != null) {
                const t = end.t == null ? 0.5 : end.t;
                switch (end.side) {
                    case 'left':   return { x: it.x, y: it.y + it.h * t, side: 'left' };
                    case 'right':  return { x: it.x + it.w, y: it.y + it.h * t, side: 'right' };
                    case 'top':    return { x: it.x + it.w * t, y: it.y, side: 'top' };
                    default:       return { x: it.x + it.w * t, y: it.y + it.h, side: 'bottom' };
                }
            }
        }
        return { x: end.x || 0, y: end.y || 0, side: null };
    },

    /** Nearest side + position (0..1) on a box for point p. */
    nearestSide(it, p) {
        const c = v => Math.max(0, Math.min(1, v));
        const d = { left: Math.abs(p.x - it.x), right: Math.abs(p.x - it.x - it.w),
                    top: Math.abs(p.y - it.y), bottom: Math.abs(p.y - it.y - it.h) };
        const side = Object.keys(d).reduce((a, b) => d[a] <= d[b] ? a : b);
        const t = side === 'left' || side === 'right' ? c((p.y - it.y) / it.h) : c((p.x - it.x) / it.w);
        return { side, t: Math.round(t * 1000) / 1000 };
    },

    wirePoints(doc, w) {
        const a = this.anchor(doc, w.from), b = this.anchor(doc, w.to);
        const via = (w.via || []).map(([x, y]) => ({ x, y }));
        if (via.length || w.route === 'straight') return [a, ...via, b];
        const tapSide = (p, q) => {               // a signal leaves a bus perpendicular to it, towards the other end
            if (p.tx == null) return;
            p.side = Math.abs(p.tx) >= Math.abs(p.ty) ? (q.y < p.y ? 'top' : 'bottom') : (q.x < p.x ? 'left' : 'right');
        };
        tapSide(a, b); tapSide(b, a);
        if ((w.from && (w.from.port != null || w.from.wire)) || (w.to && (w.to.port != null || w.to.wire))) {
            return this._portRoute(a, b, w.from && w.from.port != null, w.to && w.to.port != null);
        }
        const horiz = (p, q) => p.side ? (p.side === 'left' || p.side === 'right') : Math.abs(q.x - p.x) >= Math.abs(q.y - p.y);
        const h1 = horiz(a, b), h2 = horiz(b, a);
        if (h1 && h2) {
            if (Math.abs(a.y - b.y) < 0.5) return [a, b];
            const mx = (a.x + b.x) / 2;
            return [a, { x: mx, y: a.y }, { x: mx, y: b.y }, b];
        }
        if (!h1 && !h2) {
            if (Math.abs(a.x - b.x) < 0.5) return [a, b];
            const my = (a.y + b.y) / 2;
            return [a, { x: a.x, y: my }, { x: b.x, y: my }, b];
        }
        return h1 ? [a, { x: b.x, y: a.y }, b] : [a, { x: a.x, y: b.y }, b];
    },

    /** Orthogonal route that first leaves a port outwards (LEAD), then turns; goes around when the ports face away. */
    _portRoute(a, b, leadA, leadB) {
        const LEAD = 14, V = { left: [-1, 0], right: [1, 0], top: [0, -1], bottom: [0, 1] };
        const dirOf = (p, q) => p.side ? V[p.side]
            : Math.abs(q.x - p.x) >= Math.abs(q.y - p.y) ? [Math.sign(q.x - p.x) || 1, 0] : [0, Math.sign(q.y - p.y) || 1];
        const da = dirOf(a, b), db = dirOf(b, a);
        const a1 = { x: a.x + da[0] * (leadA ? LEAD : 0), y: a.y + da[1] * (leadA ? LEAD : 0) };
        const b1 = { x: b.x + db[0] * (leadB ? LEAD : 0), y: b.y + db[1] * (leadB ? LEAD : 0) };
        const ha = da[0] !== 0, hb = db[0] !== 0, mid = [];
        if (ha && hb) {
            if (da[0] * (b1.x - a1.x) >= 0 && db[0] * (a1.x - b1.x) >= 0) {
                const mx = (a1.x + b1.x) / 2; mid.push({ x: mx, y: a1.y }, { x: mx, y: b1.y });
            } else if (da[0] === db[0]) {
                const x = da[0] > 0 ? Math.max(a1.x, b1.x) : Math.min(a1.x, b1.x); mid.push({ x, y: a1.y }, { x, y: b1.y });
            } else {
                const my = (a1.y + b1.y) / 2; mid.push({ x: a1.x, y: my }, { x: b1.x, y: my });
            }
        } else if (!ha && !hb) {
            if (da[1] * (b1.y - a1.y) >= 0 && db[1] * (a1.y - b1.y) >= 0) {
                const my = (a1.y + b1.y) / 2; mid.push({ x: a1.x, y: my }, { x: b1.x, y: my });
            } else if (da[1] === db[1]) {
                const y = da[1] > 0 ? Math.max(a1.y, b1.y) : Math.min(a1.y, b1.y); mid.push({ x: a1.x, y }, { x: b1.x, y });
            } else {
                const mx = (a1.x + b1.x) / 2; mid.push({ x: mx, y: a1.y }, { x: mx, y: b1.y });
            }
        } else if (ha) {          // a leaves horizontally, b vertically
            const ok = da[0] * (b1.x - a1.x) >= 0 && db[1] * (a1.y - b1.y) >= 0;
            mid.push(ok ? { x: b1.x, y: a1.y } : { x: a1.x, y: b1.y });
        } else {
            const ok = da[1] * (b1.y - a1.y) >= 0 && db[0] * (a1.x - b1.x) >= 0;
            mid.push(ok ? { x: a1.x, y: b1.y } : { x: b1.x, y: a1.y });
        }
        return this._simplify([a, a1, ...mid, b1, b]);
    },

    /** Drop repeated points and middle points of straight runs (keeps the ends). */
    _simplify(pts) {
        const out = [];
        for (const p of pts) {
            const q = out[out.length - 1];
            if (q && Math.abs(q.x - p.x) < 0.5 && Math.abs(q.y - p.y) < 0.5) continue;
            out.push(p);
        }
        for (let i = out.length - 2; i > 0; i--) {
            const p = out[i - 1], q = out[i], r = out[i + 1];
            if ((Math.abs(p.x - q.x) < 0.5 && Math.abs(q.x - r.x) < 0.5) || (Math.abs(p.y - q.y) < 0.5 && Math.abs(q.y - r.y) < 0.5)) out.splice(i, 1);
        }
        return out;
    },

    /** Default label position: middle of the longest segment (above a horizontal one, right of a vertical one). */
    wireLabelPos(pts, w) {
        let best = 0, len = -1;
        for (let i = 0; i < pts.length - 1; i++) {
            const l = Math.hypot(pts[i + 1].x - pts[i].x, pts[i + 1].y - pts[i].y);
            if (l > len) { len = l; best = i; }
        }
        const p = pts[best], q = pts[best + 1] || p;
        const vertical = Math.abs(q.x - p.x) < Math.abs(q.y - p.y);
        const lines = String(w.label || '').split('\n').length;
        const x = (p.x + q.x) / 2 + (w.labelDx || 0), y = (p.y + q.y) / 2 + (w.labelDy || 0);
        return vertical ? { x: x + 10, y: y + 4 - (lines - 1) * 8, anchor: 'start' }
                        : { x, y: y - 8 - (lines - 1) * 16, anchor: 'middle' };
    },

    /** Pin positions of a chip: [{side, i, pin, x, y, rot, d}] (d = +1/-1 outward along the rotated x axis). */
    pinPositions(chip) {
        const out = [], pins = chip.pins || {};
        const c1 = chip.corner == null ? 100 : chip.corner, c2 = chip.corner2 == null || chip.corner2 === '' ? c1 : chip.corner2;
        const place = (n, len, corner) => n === 1 ? [len / 2] :
            Array.from({ length: n }, (_, i) => corner + i * (len - 2 * corner) / (n - 1));
        const L = pins.left || [], R = pins.right || [], T = pins.top || [], B = pins.bottom || [];
        place(L.length, chip.h, c1).forEach((o, i) => out.push({ side: 'left', i, pin: L[i], x: chip.x, y: chip.y + o, rot: 0, d: -1 }));
        place(R.length, chip.h, c1).forEach((o, i) => out.push({ side: 'right', i, pin: R[i], x: chip.x + chip.w, y: chip.y + o, rot: 0, d: 1 }));
        place(T.length, chip.w, c2).forEach((o, i) => out.push({ side: 'top', i, pin: T[i], x: chip.x + o, y: chip.y, rot: -90, d: 1 }));
        place(B.length, chip.w, c2).forEach((o, i) => out.push({ side: 'bottom', i, pin: B[i], x: chip.x + o, y: chip.y + chip.h, rot: -90, d: -1 }));
        return out;
    },

    category(key) { return this.CATEGORIES[key] || this.CATEGORIES.custom; },
    portType(key) { return this.PORT_TYPES[key] || this.PORT_TYPES.io; },

    /** Port positions of a unit: [{side, port, x, y (body edge), tx, ty (stub tip = wire anchor), rot, d}]. */
    portPositions(u) {
        const out = [], P = this.PORT_PITCH, S = this.PORT_STUB;
        const by = { left: [], right: [], top: [], bottom: [] };
        (u.ports || []).forEach(p => (by[p.side] || by.left).push(p));
        const place = (n, len) => {
            if (!n) return [];
            let pitch = P, start = Math.round((len - (n - 1) * P) / 20) * 10;
            if ((n - 1) * P > len - 20) { pitch = (len - 20) / Math.max(1, n - 1); start = n === 1 ? len / 2 : 10; }
            return Array.from({ length: n }, (_, i) => start + i * pitch);
        };
        place(by.left.length, u.h).forEach((o, i) => out.push({ side: 'left', port: by.left[i], x: u.x, y: u.y + o, tx: u.x - S, ty: u.y + o, rot: 0, d: -1 }));
        place(by.right.length, u.h).forEach((o, i) => out.push({ side: 'right', port: by.right[i], x: u.x + u.w, y: u.y + o, tx: u.x + u.w + S, ty: u.y + o, rot: 0, d: 1 }));
        // isolator: top/bottom ports split in halves — side A left of the barrier, side B right of it
        const across = n => {
            if (u.category !== 'iso' || n < 2) return place(n, u.w);
            const h = Math.ceil(n / 2);
            return [...place(h, u.w / 2), ...place(n - h, u.w / 2).map(o => o + u.w / 2)];
        };
        across(by.top.length).forEach((o, i) => out.push({ side: 'top', port: by.top[i], x: u.x + o, y: u.y, tx: u.x + o, ty: u.y - S, rot: -90, d: 1 }));
        across(by.bottom.length).forEach((o, i) => out.push({ side: 'bottom', port: by.bottom[i], x: u.x + o, y: u.y + u.h, tx: u.x + o, ty: u.y + u.h + S, rot: -90, d: -1 }));
        return out;
    },

    /** Category pictogram at (x, y), `size` px square. */
    icon(cat, x, y, size, color) {
        const c = this.category(cat);
        return `<g transform="translate(${this.num(x)},${this.num(y)}) scale(${this.num(size / 32)})" fill="none" stroke="${this.esc(color || c.color)}"` +
               ` stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${c.icon}</g>`;
    },

    // ── Render ─────────────────────────────────────────────────

    /** Full standalone SVG document (export). */
    toSvg(doc) {
        const W = doc.width, H = doc.height;
        return `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">\n` +
               `<rect width="${W}" height="${H}" fill="${this.esc(doc.background || '#ffffff')}"/>\n` +
               this.renderItems(doc, {}) + '\n</svg>\n';
    },

    /** Markup of all items; opts.editor adds data-id groups and wide invisible hit paths for wires. */
    renderItems(doc, opts = {}) {
        const out = [];
        const wires = doc.items.filter(i => i.type === 'wire');
        const colors = new Set(wires.filter(w => w.line !== 'bus').map(w => this.wireColor(doc, w)));
        const busColors = new Set(wires.filter(w => w.line === 'bus').map(w => this.wireColor(doc, w)));
        opts = Object.assign({}, opts, { portColors: this.portColors(doc) });
        if (colors.size || busColors.size) {
            out.push('<defs>' + [...colors].map(c =>
                `<marker id="${this.markerId(c)}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">` +
                `<path d="M0,0 L10,5 L0,10 z" fill="${this.esc(c)}"/></marker>`).join('') +
                [...busColors].map(c =>          // bus arrows: fixed size, not scaled by the thick stroke
                `<marker id="${this.markerId(c, true)}" viewBox="0 0 10 10" refX="8" refY="5" markerUnits="userSpaceOnUse" markerWidth="18" markerHeight="18" orient="auto-start-reverse">` +
                `<path d="M0,0 L10,5 L0,10 z" fill="${this.esc(c)}"/></marker>`).join('') + '</defs>');
        }
        for (const it of doc.items) {
            const fn = this['_' + it.type];
            if (!fn) continue;
            const body = fn.call(this, doc, it, opts);
            out.push(opts.editor ? `<g data-id="${this.esc(it.id)}" class="dg-item dg-${it.type}">${body}</g>` : body);
        }
        return out.join('\n');
    },

    markerId(color, bus) { return (bus ? 'arb-' : 'ar-') + String(color).replace(/[^\w]/g, ''); },

    /** Polyline shortened by `a` at the start and `b` at the end (bus core line stops before arrowheads). */
    _trim(pts, a, b) {
        const cut = (p, q, L) => { const d = Math.hypot(q.x - p.x, q.y - p.y) || 1; return { x: p.x + (q.x - p.x) * Math.min(1, L / d), y: p.y + (q.y - p.y) * Math.min(1, L / d) }; };
        const r = pts.slice();
        if (a && r.length > 1) r[0] = cut(r[0], r[1], a);
        if (b && r.length > 1) r[r.length - 1] = cut(r[r.length - 1], r[r.length - 2], b);
        return r;
    },

    _length(pts) { let L = 0; for (let i = 0; i < pts.length - 1; i++) L += Math.hypot(pts[i + 1].x - pts[i].x, pts[i + 1].y - pts[i].y); return L; },

    DEFAULT_WIRE: '#57534e',

    /** Port {name, type} a wire end is attached to, or null. */
    endPort(doc, end) {
        if (!end || end.port == null || !end.id) return null;
        const u = this.byId(doc, end.id);
        return u && u.type === 'unit' ? (u.ports || []).find(q => q.name === end.port) || null : null;
    },

    /** Effective wire colour: own colour, else the type colour of its start port / end port, else of the bus it taps. */
    wireColor(doc, w, depth = 0) {
        if (w.color) return w.color;
        const p = this.endPort(doc, w.from) || this.endPort(doc, w.to);
        if (p) return this.portType(p.type).color;
        const tap = [w.from, w.to].find(e => e && e.wire);
        const bus = tap && depth < 2 && this.byId(doc, tap.wire);
        return bus && bus.type === 'wire' ? this.wireColor(doc, bus, depth + 1) : this.DEFAULT_WIRE;
    },

    /** "unitId\u0000port" -> colour of the wire connected there (the net colour); first wire wins. */
    portColors(doc) {
        const m = new Map();
        for (const w of doc.items) {
            if (w.type !== 'wire') continue;
            for (const e of [w.from, w.to]) {
                if (e && e.id && e.port != null) {
                    const k = e.id + '\u0000' + e.port;
                    if (!m.has(k)) m.set(k, this.wireColor(doc, w));
                }
            }
        }
        return m;
    },

    /** Signals carried by a bus: its own list + labels / port names of the wires tapped into it. */
    busSignals(doc, bus) {
        const out = String(bus.signals || '').split(/[,;]/).map(s => s.trim()).filter(Boolean);
        for (const w of doc.items) {
            if (w.type !== 'wire' || w === bus) continue;
            const tapFrom = w.from && w.from.wire === bus.id, tapTo = w.to && w.to.wire === bus.id;
            if (!tapFrom && !tapTo) continue;
            const p = this.endPort(doc, tapFrom ? w.to : w.from);
            const name = String(w.label || '').split('\n')[0].trim() || (p ? p.name : '');
            if (name && !out.includes(name)) out.push(name);
        }
        return out;
    },

    /** Point and unit direction at distance `L` along a polyline. */
    _along(pts, L) {
        for (let i = 0; i < pts.length - 1; i++) {
            const p = pts[i], q = pts[i + 1], d = Math.hypot(q.x - p.x, q.y - p.y);
            if (d && (L <= d || i === pts.length - 2)) {
                const k = Math.min(L, d) / d;
                return { x: p.x + (q.x - p.x) * k, y: p.y + (q.y - p.y) * k, tx: (q.x - p.x) / d, ty: (q.y - p.y) / d };
            }
            L -= d;
        }
        return { x: pts[0].x, y: pts[0].y, tx: 1, ty: 0 };
    },

    _font(f) { return f === 'mono' ? this.MONO : this.SANS; },

    _text(doc, t) {
        const size = t.size || 14, lines = String(t.text || '').split('\n');
        const attrs = `font-size="${size}" font-family="${this.esc(this._font(t.font))}" fill="${this.esc(t.color || this.INK)}"` +
            ` text-anchor="${t.anchor || 'start'}"` + (t.weight && t.weight !== 'normal' ? ` font-weight="${t.weight}"` : '') +
            (t.italic ? ' font-style="italic"' : '');
        const tr = t.rotate ? ` transform="rotate(${t.rotate} ${t.x} ${t.y})"` : '';
        if (lines.length === 1) return `<text x="${t.x}" y="${t.y}" ${attrs}${tr}>${this.esc(lines[0])}</text>`;
        return `<text x="${t.x}" y="${t.y}" ${attrs}${tr}>` + lines.map((l, k) =>
            `<tspan x="${t.x}" dy="${k ? this.num(size * 1.3) : 0}">${this.esc(l) || ' '}</tspan>`).join('') + '</text>';
    },

    _block(doc, b) {
        const st = this.BLOCK_STYLES[b.style] || this.BLOCK_STYLES.light;
        const fill = b.fill || st.fill, stroke = b.stroke || st.stroke;
        const tc = b.titleColor || st.title, sc = b.textColor || st.text;
        const ts = b.titleSize || 16, ls = b.lineSize || 13, r = b.radius == null ? 10 : b.radius;
        const center = b.align === 'center';
        const tx = center ? b.x + b.w / 2 : b.x + 16, anchor = center ? ' text-anchor="middle"' : '';
        let s = `<rect x="${b.x}" y="${b.y}" width="${b.w}" height="${b.h}" rx="${r}" fill="${this.esc(fill)}" stroke="${this.esc(stroke)}" stroke-width="1.5"` +
                (b.dashed ? ' stroke-dasharray="6 4"' : '') + '/>';
        if (b.title) {
            s += `<text x="${tx}" y="${b.y + ts + 12}" font-size="${ts}" font-weight="700" fill="${this.esc(tc)}" font-family="${this.esc(this.SANS)}"${anchor}>${this.esc(b.title)}</text>`;
        }
        const top = b.title ? b.y + ts + 36 : b.y + ls + 14;
        (b.lines || []).forEach((ln, k) => {
            const mono = ln.startsWith('`');
            s += `<text x="${tx}" y="${this.num(top + k * (ls + 7))}" font-size="${ls}" fill="${this.esc(sc)}" font-family="${this.esc(mono ? this.MONO : this.SANS)}"${anchor} xml:space="preserve">${this.esc(mono ? ln.replace(/^`|`$/g, '') : ln)}</text>`;
        });
        return s;
    },

    _wire(doc, w, opts) {
        const pts = this.wirePoints(doc, w);
        const bus = w.line === 'bus';
        const color = this.wireColor(doc, w), mid = `url(#${this.markerId(color, bus)})`;
        const path = list => 'M' + list.map(p => `${this.num(p.x)},${this.num(p.y)}`).join(' L');
        const d = path(pts);
        const arrow = w.arrow || 'end';
        const aEnd = arrow === 'end' || arrow === 'both', aStart = arrow === 'start' || arrow === 'both';
        const W = w.width || (bus ? 5 : 1.6);
        let s = `<path d="${d}" fill="none" stroke="${this.esc(color)}" stroke-width="${W}"` + (bus ? ' stroke-linejoin="round"' : '') +
                (arrow === 'end' || arrow === 'both' ? ` marker-end="${mid}"` : '') +
                (arrow === 'start' || arrow === 'both' ? ` marker-start="${mid}"` : '') +
                (w.dashed ? ' stroke-dasharray="6 4"' : '') + '/>';
        if (bus) {
            s += `<path d="${path(this._trim(pts, aStart ? 14 : 0, aEnd ? 14 : 0))}" fill="none" stroke="#ffffff" stroke-opacity=".85"` +
                 ` stroke-width="${this.num(W * 0.36)}" stroke-linejoin="round"${w.dashed ? ' stroke-dasharray="6 4"' : ''}/>`;
            if (w.busWidth) {                    // slash mark with the width / name near the start
                const q = this._along(pts, 30), nx = q.ty, ny = -q.tx;            // normal: up for → , right for ↓
                const vertical = Math.abs(q.ty) > Math.abs(q.tx);
                s += `<path d="M${this.num(q.x - nx * 8 - q.tx * 5)},${this.num(q.y - ny * 8 - q.ty * 5)} L${this.num(q.x + nx * 8 + q.tx * 5)},${this.num(q.y + ny * 8 + q.ty * 5)}"` +
                     ` stroke="${this.esc(color)}" stroke-width="1.6"/>` +
                     `<text x="${this.num(q.x + (vertical ? 12 : nx * 13 + 8))}" y="${this.num(q.y + (vertical ? 4 : ny * 13 + 4))}" font-size="11"` +
                     ` text-anchor="start" fill="${this.esc(color)}" font-family="${this.esc(this.MONO)}">${this.esc(w.busWidth)}</text>`;
            }
        }
        for (const e of [w.from, w.to]) {           // junction dot where a signal joins a bus
            if (e && e.wire) {
                const b = this.byId(doc, e.wire), a = this.anchor(doc, e);
                if (b) s += `<circle cx="${this.num(a.x)}" cy="${this.num(a.y)}" r="4" fill="${this.esc(this.wireColor(doc, b))}" stroke="#ffffff" stroke-width="1"/>`;
            }
        }
        if (bus && !w.hideSignals) {
            const sig = this.busSignals(doc, w);
            if (sig.length) {
                const p = this.wireLabelPos(pts, Object.assign({}, w, { label: ' ' }));
                const lines = w.label ? String(w.label).split('\n').length : 0;
                // horizontal run: below the line (the label is above it); vertical run: under the label lines
                const y = p.anchor === 'middle' ? p.y + 8 + 3 + W / 2 + 12 : p.y + lines * 16;
                s += `<text x="${this.num(p.x)}" y="${this.num(y)}" font-size="11" text-anchor="${p.anchor}" fill="${this.esc(color)}"` +
                     ` font-family="${this.esc(this.MONO)}" class="dg-wire-label">{${this.esc(sig.join(', '))}}</text>`;
            }
        }
        if (opts.editor) s = `<path d="${d}" fill="none" stroke="transparent" stroke-width="${Math.max(12, W + 8)}" class="dg-hit"/>` + s;
        if (w.label) {
            const p = this.wireLabelPos(pts, w);
            const size = w.labelSize || 12.5;
            s += `<g class="dg-wire-label">` + String(w.label).split('\n').map((ln, k) =>
                `<text x="${this.num(p.x)}" y="${this.num(p.y + k * 16)}" font-size="${size}" text-anchor="${p.anchor}" fill="#374151" font-family="${this.esc(this.MONO)}" xml:space="preserve">${this.esc(ln)}</text>`).join('') + '</g>';
        }
        return s;
    },

    _legend(doc, lg) {
        if (lg.source === 'ports') return this._legendPorts(doc, lg);
        const used = new Set();
        doc.items.filter(i => i.type === 'chip').forEach(c =>
            this.SIDES.forEach(sd => (c.pins && c.pins[sd] || []).forEach(p => used.add(p.kind || 'free'))));
        const keys = (lg.kinds && lg.kinds.length ? lg.kinds : Object.keys(doc.kinds || {}).filter(k => used.has(k)))
            .filter(k => (doc.kinds || {})[k]);
        const size = lg.size || 13;
        let x = lg.x, s = '';
        for (const k of keys) {
            const kd = this.kind(doc, k), label = kd.label || k;
            if (lg.style === 'swatch') {
                s += `<rect x="${x}" y="${lg.y - 13}" width="16" height="16" rx="3" fill="${this.esc(kd.color || kd.fill)}"/>` +
                     `<text x="${x + 22}" y="${lg.y}" font-size="${size + 2}" fill="#111827" font-family="${this.esc(this.SANS)}">${this.esc(label)}</text>`;
                x += 44 + label.length * (size * 0.6) + 20;
            } else {
                s += `<g transform="translate(${this.num(x)},${lg.y})">` + this._tag(0, 70, kd.sample || k.toUpperCase(), kd, 11.5) +
                     `<text x="80" y="4.5" font-size="${size}" fill="#374151" font-family="${this.esc(this.SANS)}">${this.esc(label)}</text></g>`;
                x += 80 + label.length * (size * 0.57) + 34;
            }
        }
        return s || `<text x="${lg.x}" y="${lg.y}" font-size="12" fill="${this.FAINT}" font-family="${this.esc(this.SANS)}">legend (no pin kinds used)</text>`;
    },

    _legendPorts(doc, lg) {
        const used = new Set();
        doc.items.filter(i => i.type === 'unit').forEach(u => (u.ports || []).forEach(p => used.add(p.type || 'io')));
        const keys = Object.keys(this.PORT_TYPES).filter(k => used.has(k));
        const size = lg.size || 13;
        let x = lg.x, s = '';
        for (const k of keys) {
            const pt = this.PORT_TYPES[k];
            s += `<g transform="translate(${this.num(x)},${lg.y - 4})">` + this._portMark(pt, 1, true) +
                 `<text x="${this.PORT_STUB + 10}" y="4.5" font-size="${size}" fill="#374151" font-family="${this.esc(this.SANS)}">${this.esc(pt.label)}</text></g>`;
            x += this.PORT_STUB + 10 + pt.label.length * (size * 0.57) + 30;
        }
        return s || `<text x="${lg.x}" y="${lg.y}" font-size="12" fill="${this.FAINT}" font-family="${this.esc(this.SANS)}">legend (no unit ports used)</text>`;
    },

    /** Stub + type marker in local coordinates (body edge at 0, outward = +d along x). */
    _portMark(pt, d, legend) {
        const S = this.PORT_STUB, c = this.esc(pt.color), f = v => this.num(v * d);
        let s = `<line x1="0" y1="0" x2="${f(S)}" y2="0" stroke="${c}" stroke-width="${pt.mark === 'bus' ? 3.5 : 1.6}"${pt.mark === 'nc' ? ' stroke-dasharray="3 2"' : ''}/>`;
        switch (pt.mark) {
            case 'in':  s += `<path d="M${f(3)},0 L${f(11)},-4.5 L${f(11)},4.5 z" fill="${c}"/>`; break;
            case 'out': s += `<path d="M${f(12)},0 L${f(4)},-4.5 L${f(4)},4.5 z" fill="${c}"/>`; break;
            case 'io':  s += `<path d="M${f(2)},0 L${f(7)},-4.5 L${f(12)},0 L${f(7)},4.5 z" fill="${c}"/>`; break;
            case 'dot': s += `<circle cx="${f(7)}" cy="0" r="3.2" fill="${c}"/>`; break;
            case 'tp':  s += `<circle cx="${f(S)}" cy="0" r="4" fill="#ffffff" stroke="${c}" stroke-width="1.8"/>`; break;
            case 'sq':  s += `<rect x="${this.num(7 * d - 3.5)}" y="-3.5" width="7" height="7" fill="${c}"/>`; break;
            case 'gnd': s += `<path d="M${f(8)},-5 V5 M${f(10.5)},-3.3 V3.3 M${f(13)},-1.6 V1.6" stroke="${c}" stroke-width="1.6"/>`; break;
            case 'nc':  s += `<path d="M${f(S - 4)},-4 L${f(S + 4)},4 M${f(S - 4)},4 L${f(S + 4)},-4" stroke="${c}" stroke-width="1.6"/>`; break;
        }
        return s;
    },

    _unit(doc, u, opts) {
        const cat = this.category(u.category), col = this.esc(cat.color);
        let s = `<rect x="${u.x}" y="${u.y}" width="${u.w}" height="${u.h}" rx="6" fill="#ffffff" stroke="${col}" stroke-width="1.8"/>` +
                `<path d="M${u.x + 6},${u.y + 1} H${u.x + u.w - 6}" stroke="${col}" stroke-width="4" stroke-linecap="round" opacity=".55"/>`;
        // centre: pictogram, designator, title, subtitle
        const rows = [];
        if (u.des) rows.push({ h: 17, text: u.des, size: 13, fill: cat.color, font: this.MONO, weight: 700 });
        if (u.title) rows.push({ h: 19, text: u.title, size: 15, fill: this.INK, font: this.SANS, weight: 700 });
        if (u.subtitle) rows.push({ h: 16, text: u.subtitle, size: 12, fill: this.MUTED, font: this.SANS, weight: 400 });
        const IC = 30, total = IC + 6 + rows.reduce((a, r) => a + r.h, 0);
        const labW = sd => { const l = (u.ports || []).filter(p => p.side === sd); return l.length ? l.reduce((m, p) => Math.max(m, String(p.name || '').length), 0) * 7.3 + 10 : 0; };
        const x0 = u.x + labW('left'), x1 = u.x + u.w - labW('right'), y0 = u.y + labW('top'), y1 = u.y + u.h - labW('bottom');
        const cx = x1 - x0 > 60 ? (x0 + x1) / 2 : u.x + u.w / 2;
        let y = (y1 - y0 > total ? (y0 + y1) / 2 : u.y + u.h / 2) - total / 2;
        if (u.category === 'iso') {                 // isolation barrier between side A (left) and side B (right)
            const bx = this.num(u.x + u.w / 2), dash = ` stroke="${col}" stroke-width="1.6" stroke-dasharray="6 4"`;
            const top = u.y + 8, bot = u.y + u.h - 8;
            if (y - 6 > top) s += `<path d="M${bx},${this.num(top)} V${this.num(y - 6)}"${dash}/>`;
            if (y + total + 4 < bot) s += `<path d="M${bx},${this.num(y + total + 4)} V${this.num(bot)}"${dash}/>`;
        }
        s += this.icon(u.category, cx - IC / 2, y, IC);
        y += IC + 6;
        for (const r of rows) {
            y += r.h;
            s += `<text x="${this.num(cx)}" y="${this.num(y - 4)}" font-size="${r.size}" text-anchor="middle" fill="${this.esc(r.fill)}" font-family="${this.esc(r.font)}"` +
                 (r.weight !== 400 ? ` font-weight="${r.weight}"` : '') + `>${this.esc(r.text)}</text>`;
        }
        for (const pos of this.portPositions(u)) {
            const p = pos.port || {}, d = pos.d, t0 = this.portType(p.type);
            const net = opts && opts.portColors && opts.portColors.get(u.id + '\u0000' + p.name);
            const pt = net ? Object.assign({}, t0, { color: net }) : t0;
            s += `<g transform="translate(${this.num(pos.x)},${this.num(pos.y)})${pos.rot ? ` rotate(${pos.rot})` : ''}" data-port="${this.esc(p.name)}">` +
                 (opts && opts.editor && p.note ? `<title>${this.esc(p.name + ' — ' + p.note)}</title>` : '') + this._portMark(pt, d) +
                 `<text x="${-6 * d}" y="4" font-size="12" text-anchor="${d > 0 ? 'end' : 'start'}" fill="${p.type === 'nc' ? this.FAINT : this.INK}" font-family="${this.esc(this.MONO)}">${this.esc(p.name)}</text></g>`;
        }
        return s;
    },

    _tag(x0, w, text, kd, fs = 12.5) {
        return `<rect x="${this.num(x0)}" y="-10" width="${w}" height="20" rx="4" fill="${this.esc(kd.fill)}" stroke="${this.esc(kd.stroke)}" stroke-width="1.2"` +
               (kd.dash ? ` stroke-dasharray="${this.esc(kd.dash)}"` : '') + '/>' +
               `<text x="${this.num(x0 + w / 2)}" y="4.5" font-size="${fs}" text-anchor="middle" fill="${this.esc(kd.text)}" font-family="${this.esc(this.MONO)}">${this.esc(text)}</text>`;
    },

    _chip(doc, c) {
        const outline = c.body === 'outline';
        let s = '';
        if (outline) {
            s += `<rect x="${c.x}" y="${c.y}" width="${c.w}" height="${c.h}" fill="#f9fafb" stroke="#111827" stroke-width="3"/>`;
        } else {
            s += `<rect x="${c.x}" y="${c.y}" width="${c.w}" height="${c.h}" rx="18" fill="#2b3440"/>` +
                 `<rect x="${c.x + 8}" y="${c.y + 8}" width="${c.w - 16}" height="${c.h - 16}" rx="12" fill="none" stroke="#3d4855" stroke-width="1.5"/>`;
            if (c.holes !== false) {
                for (const [hx, hy] of [[c.x + 34, c.y + 34], [c.x + c.w - 34, c.y + 34], [c.x + 34, c.y + c.h - 34], [c.x + c.w - 34, c.y + c.h - 34]]) {
                    s += `<circle cx="${hx}" cy="${hy}" r="11" fill="${this.esc(doc.background || '#fafaf9')}" stroke="#c9a96e" stroke-width="3"/>`;
                }
            }
        }
        const cx = c.x + c.w / 2, cy = c.y + c.h / 2;
        const ic = c.ic || {};
        const light = outline ? { t: '#111827', s: '#4b5563' } : { t: '#e5e7eb', s: '#9ca3af' };
        if (ic.show !== false && (ic.title || ic.subtitle)) {
            const z = Math.min(240, Math.min(c.w, c.h) * 0.45);
            if (!outline) {
                s += `<rect x="${this.num(cx - z / 2)}" y="${this.num(cy - z * 0.625)}" width="${this.num(z)}" height="${this.num(z)}" rx="10" fill="#1b2129" stroke="#4b5563"/>` +
                     `<circle cx="${this.num(cx - z / 2 + 22)}" cy="${this.num(cy - z * 0.625 + 22)}" r="5" fill="#4b5563"/>`;
            }
            s += `<text x="${cx}" y="${this.num(cy - z / 6)}" font-size="${this.num(z / 6)}" font-weight="700" text-anchor="middle" fill="${light.t}" font-family="${this.esc(this.SANS)}">${this.esc(ic.title || '')}</text>` +
                 `<text x="${cx}" y="${this.num(cy - z / 24)}" font-size="14" text-anchor="middle" fill="${light.s}" font-family="${this.esc(this.SANS)}">${this.esc(ic.subtitle || '')}</text>`;
        }
        const capY = ic.show !== false && (ic.title || ic.subtitle) ? cy + Math.min(240, Math.min(c.w, c.h) * 0.45) * 0.58 : cy;
        if (c.caption) s += `<text x="${cx}" y="${this.num(capY)}" font-size="22" font-weight="600" text-anchor="middle" fill="${light.t}" font-family="${this.esc(this.SANS)}">${this.esc(c.caption)}</text>`;
        if (c.caption2) s += `<text x="${cx}" y="${this.num(capY + 28)}" font-size="13" text-anchor="middle" fill="${light.s}" font-family="${this.esc(this.SANS)}">${this.esc(c.caption2)}</text>`;
        for (const p of this.pinPositions(c)) {
            s += c.pinStyle === 'simple' ? this._pinSimple(doc, c, p) : this._pinTags(doc, c, p);
        }
        return s;
    },

    _pinTags(doc, c, pos) {
        const p = pos.pin || {}, d = pos.d;
        const free = !p.kind || p.kind === 'free';
        const kd = this.kind(doc, free ? 'free' : p.kind), fk = this.kind(doc, 'free');
        const portW = c.portW || 66, fnW = c.fnW || 128;
        const place = (cc, w) => d > 0 ? cc : -cc - w;
        let s = `<g transform="translate(${this.num(pos.x)},${this.num(pos.y)})${pos.rot ? ` rotate(${pos.rot})` : ''}" data-pin="${pos.side}:${pos.i}">` +
                `<circle cx="${-12 * d}" cy="0" r="4.5" fill="#c9a96e"/>`;
        if (c.numbers !== false && p.n !== '' && p.n != null) {
            s += `<text x="${-22 * d}" y="3.5" font-size="10" text-anchor="${d > 0 ? 'end' : 'start'}" fill="${c.body === 'outline' ? '#64748b' : '#cbd5e1'}" font-family="${this.esc(this.MONO)}">${this.esc(p.n)}</text>`;
        }
        s += `<line x1="${-12 * d}" y1="0" x2="${14 * d}" y2="0" stroke="${free ? this.FAINT : '#57534e'}" stroke-width="1.4"/>`;
        let cc = 16;
        s += `<rect x="${place(cc, portW)}" y="-10" width="${portW}" height="20" rx="4" fill="${free ? '#ffffff' : '#f3f4f6'}" stroke="#d1d5db"/>` +
             `<text x="${place(cc, portW) + portW / 2}" y="4.5" font-size="12.5" text-anchor="middle" fill="${free ? this.esc(fk.text) : '#374151'}" font-family="${this.esc(this.MONO)}">${this.esc(p.port)}</text>`;
        cc += portW + 4;
        if (!free) {
            s += this._tag(place(cc, fnW), fnW, p.fn || '', kd);
            cc += fnW + 4;
            const b = p.badge || kd.badge || '';
            if (b) s += `<text x="${cc * d + (d > 0 ? 21 : -21)}" y="4" font-size="10" text-anchor="middle" fill="${this.MUTED}" font-family="${this.esc(this.SANS)}" font-weight="600" letter-spacing="0.5">${this.esc(b)}</text>`;
            cc += 46;
        }
        if (p.note) {
            s += `<text x="${cc * d}" y="4" font-size="11.5" text-anchor="${d > 0 ? 'start' : 'end'}" fill="${free ? this.FAINT : this.MUTED}" font-family="${this.esc(this.SANS)}"${free ? ' font-style="italic"' : ''}>${this.esc(p.note)}</text>`;
        }
        return s + '</g>';
    },

    _pinSimple(doc, c, pos) {
        const p = pos.pin || {}, d = pos.d, STUB = 34;
        const free = !p.kind || p.kind === 'free';
        const kd = this.kind(doc, free ? 'free' : p.kind);
        const col = this.esc(kd.color || kd.stroke);
        const outA = d > 0 ? 'start' : 'end', inA = d > 0 ? 'end' : 'start';
        let s = `<g transform="translate(${this.num(pos.x)},${this.num(pos.y)})${pos.rot ? ` rotate(${pos.rot})` : ''}" data-pin="${pos.side}:${pos.i}">` +
                `<line x1="0" y1="0" x2="${STUB * d}" y2="0" stroke="${col}" stroke-width="2.5"/>`;
        if (c.numbers !== false && p.n !== '' && p.n != null) {
            s += `<text x="${STUB / 2 * d}" y="-4" font-size="11" text-anchor="middle" fill="#6b7280" font-family="${this.esc(this.MONO)}">${this.esc(p.n)}</text>`;
        }
        s += `<text x="${-8 * d}" y="5" font-size="15" text-anchor="${inA}" fill="#111827" font-family="${this.esc(this.MONO)}">${this.esc(p.port)}</text>`;
        const label = free ? (p.note ? '· ' + p.note : 'nc') : (p.fn || '');
        s += `<text x="${(STUB + 8) * d}" y="5" font-size="16" text-anchor="${outA}" fill="${col}" font-family="${this.esc(this.MONO)}"${free ? '' : ' font-weight="bold"'}>${this.esc(label)}` +
             (!free && p.note ? `<tspan font-size="12" font-weight="normal" fill="${this.MUTED}">  ${this.esc(p.note)}</tspan>` : '') + '</text>';
        if (!free && kd.dash) {
            const outer = STUB + 150, inner = 80;   // highlight box of gen_pinout.py
            s += `<rect x="${d > 0 ? -inner : -outer}" y="-12" width="${outer + inner}" height="24" rx="5" fill="none" stroke="${col}" stroke-width="2" stroke-dasharray="${this.esc(kd.dash)}"/>`;
        }
        return s + '</g>';
    },
};
