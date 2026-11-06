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
              arrow: end|start|both|none, dashed, color, width, labelSize }
     legend { x, y, kinds: [keys] | null (= used ones), style: tags|swatch, size }
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
        if (end.id) {
            const it = this.byId(doc, end.id);
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
        const colors = new Set(doc.items.filter(i => i.type === 'wire').map(w => w.color || '#57534e'));
        if (colors.size) {
            out.push('<defs>' + [...colors].map(c =>
                `<marker id="${this.markerId(c)}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">` +
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

    markerId(color) { return 'ar-' + String(color).replace(/[^\w]/g, ''); },

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
        const color = w.color || '#57534e', mid = `url(#${this.markerId(color)})`;
        const d = 'M' + pts.map(p => `${this.num(p.x)},${this.num(p.y)}`).join(' L');
        const arrow = w.arrow || 'end';
        let s = `<path d="${d}" fill="none" stroke="${this.esc(color)}" stroke-width="${w.width || 1.6}"` +
                (arrow === 'end' || arrow === 'both' ? ` marker-end="${mid}"` : '') +
                (arrow === 'start' || arrow === 'both' ? ` marker-start="${mid}"` : '') +
                (w.dashed ? ' stroke-dasharray="6 4"' : '') + '/>';
        if (opts.editor) s = `<path d="${d}" fill="none" stroke="transparent" stroke-width="12" class="dg-hit"/>` + s;
        if (w.label) {
            const p = this.wireLabelPos(pts, w);
            const size = w.labelSize || 12.5;
            s += `<g class="dg-wire-label">` + String(w.label).split('\n').map((ln, k) =>
                `<text x="${this.num(p.x)}" y="${this.num(p.y + k * 16)}" font-size="${size}" text-anchor="${p.anchor}" fill="#374151" font-family="${this.esc(this.MONO)}" xml:space="preserve">${this.esc(ln)}</text>`).join('') + '</g>';
        }
        return s;
    },

    _legend(doc, lg) {
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
