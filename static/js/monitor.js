/* ==========================================================================
   System monitor (main page: public; floating window: logged in): CPU, RAM, temperature, active network
   interface and block devices from /api/monitor, with time charts.
   One shared poller (MonitorData) feeds every view; a view is created with
   Monitor.create(container) — the dashboard card on the main page and the
   floating window (MonitorFloat) on the other pages.
   ========================================================================== */

/** Shared poller: polls only while at least one view is subscribed and the page is visible. */
const MonitorData = {
    POLL_MS: 2000,
    history: [],            // [t, cpu %, mem %, rx B/s, tx B/s, temp °C]
    last: null,
    _subs: new Set(),
    _timer: null,
    _busy: false,

    subscribe(fn) {
        this._subs.add(fn);
        if (this.last) fn(this.last);
        this._start();
        return () => { this._subs.delete(fn); if (!this._subs.size) this._stop(); };
    },

    _start() {
        if (this._timer || !this._subs.size || document.hidden) return;
        this._tick();
        this._timer = setInterval(() => this._tick(), this.POLL_MS);
    },

    _stop() { clearInterval(this._timer); this._timer = null; },

    _tick() {
        if (this._busy) return;
        this._busy = true;
        const since = this.history.length ? this.history[this.history.length - 1][0] : 0;
        App.api('/api/monitor?since=' + since).then(d => {
            this.history.push(...d.history);
            const keep = d.now - 900;
            while (this.history.length && this.history[0][0] < keep) this.history.shift();
            this.last = d;
            this._subs.forEach(fn => fn(d));
        }).catch(() => {}).finally(() => { this._busy = false; });
    },
};

document.addEventListener('visibilitychange', () => {
    if (document.hidden) MonitorData._stop();
    else MonitorData._start();
});


/** Line chart of MonitorData.history columns over the last `window` seconds (canvas, one y-axis). */
class TimeChart {
    /**
     * @param el      container element
     * @param series  [{col, label, color: CSS variable name, dash, fill}]
     * @param opts    {max: fixed y max (else auto), fmt: value formatter}
     */
    constructor(el, series, opts) {
        this.el = el;
        this.series = series;
        this.opts = opts;
        this.window = 300;
        this.canvas = document.createElement('canvas');
        this.tip = document.createElement('div');
        this.tip.className = 'mon-tip';
        this.tip.hidden = true;
        el.append(this.canvas, this.tip);
        this.hover = null;
        this.canvas.addEventListener('mousemove', e => {
            this.hover = e.clientX - this.canvas.getBoundingClientRect().left;
            this.draw();
        });
        this.canvas.addEventListener('mouseleave', () => { this.hover = null; this.draw(); });
        new ResizeObserver(() => this.draw()).observe(el);
    }

    /** Round the axis maximum up to 1/2/2.5/5 × 10ⁿ (in the value's 1024-based unit for rates). */
    _niceMax(v) {
        if (v <= 0) return 1024;
        let k = 1;
        while (v / k >= 1000) k *= 1024;
        const x = v / k, p = Math.pow(10, Math.floor(Math.log10(x)));
        return ([1, 2, 2.5, 5, 10].map(m => m * p).find(m => m >= x * 1.1) || 10 * p) * k;
    }

    draw() {
        const w = this.el.clientWidth, h = this.el.clientHeight;
        if (!w || !h) return;
        const dpr = window.devicePixelRatio || 1;
        if (this.canvas.width !== Math.round(w * dpr) || this.canvas.height !== Math.round(h * dpr)) {
            this.canvas.width = Math.round(w * dpr);
            this.canvas.height = Math.round(h * dpr);
            this.canvas.style.width = w + 'px';
            this.canvas.style.height = h + 'px';
        }
        const ctx = this.canvas.getContext('2d');
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        ctx.clearRect(0, 0, w, h);

        const css = getComputedStyle(document.documentElement);
        const color = name => css.getPropertyValue(name).trim();
        const fmt = this.opts.fmt;
        const hist = MonitorData.history;
        const now = MonitorData.last ? MonitorData.last.now : Date.now() / 1000;
        const t0 = now - this.window;
        const pts = hist.filter(r => r[0] >= t0 - 2);

        let max = this.opts.max;
        if (!max) max = this._niceMax(Math.max(0, ...pts.flatMap(r => this.series.map(s => r[s.col] || 0))));

        ctx.font = '10px ' + color('--mono');
        const padL = Math.ceil(Math.max(...[0, max / 2, max].map(v => ctx.measureText(fmt(v, true)).width))) + 9;
        const padR = 8, padT = 6, padB = 16;
        const pw = w - padL - padR, ph = h - padT - padB;
        const x = t => padL + (t - t0) / this.window * pw;
        const y = v => padT + ph - Math.min(v, max) / max * ph;

        // grid + y labels (recessive)
        ctx.textBaseline = 'middle';
        ctx.textAlign = 'right';
        for (let i = 0; i <= 4; i++) {
            const v = max * i / 4, yy = Math.round(y(v)) + .5;
            ctx.strokeStyle = i ? color('--border-soft') : color('--border-strong');
            ctx.lineWidth = 1;
            ctx.beginPath(); ctx.moveTo(padL, yy); ctx.lineTo(w - padR, yy); ctx.stroke();
            if (i % 2 === 0) { ctx.fillStyle = color('--text-mute'); ctx.fillText(fmt(v, true), padL - 5, yy); }
        }
        // x labels: minutes ago
        ctx.textAlign = 'center';
        ctx.textBaseline = 'alphabetic';
        const step = this.window <= 60 ? 15 : this.window <= 300 ? 60 : 300;
        for (let s = step; s < this.window; s += step) {
            ctx.fillStyle = color('--text-faint');
            ctx.fillText(s >= 60 ? `-${s / 60}m` : `-${s}s`, x(now - s), h - 3);
        }

        if (!pts.length) {
            ctx.fillStyle = color('--text-mute');
            ctx.fillText('waiting for data…', padL + pw / 2, padT + ph / 2);
            this.tip.hidden = true;
            return;
        }

        ctx.save();
        ctx.beginPath(); ctx.rect(padL, padT - 2, pw, ph + 4); ctx.clip();
        const gap = Math.max(3, (MonitorData.last ? MonitorData.last.interval : 1) * 3.5);
        for (const s of this.series) {
            const c = color(s.color);
            const segs = [[]];                          // break the line where samples are missing
            pts.forEach((r, i) => {
                if (r[s.col] == null || (i && r[0] - pts[i - 1][0] > gap)) segs.push([]);
                if (r[s.col] != null) segs[segs.length - 1].push([x(r[0]), y(r[s.col])]);
            });
            for (const seg of segs.filter(g => g.length)) {
                if (s.fill) {
                    ctx.beginPath();
                    ctx.moveTo(seg[0][0], y(0));
                    seg.forEach(([px, py]) => ctx.lineTo(px, py));
                    ctx.lineTo(seg[seg.length - 1][0], y(0));
                    ctx.closePath();
                    ctx.globalAlpha = .14; ctx.fillStyle = c; ctx.fill(); ctx.globalAlpha = 1;
                }
                ctx.beginPath();
                seg.forEach(([px, py], i) => i ? ctx.lineTo(px, py) : ctx.moveTo(px, py));
                ctx.strokeStyle = c; ctx.lineWidth = 2; ctx.lineJoin = 'round';
                ctx.setLineDash(s.dash ? [5, 3] : []);
                ctx.stroke();
            }
        }
        ctx.restore();
        ctx.setLineDash([]);

        // hover: crosshair + markers + tooltip
        if (this.hover == null || this.hover < padL) { this.tip.hidden = true; return; }
        const th = t0 + (this.hover - padL) / pw * this.window;
        const r = pts.reduce((a, b) => Math.abs(b[0] - th) < Math.abs(a[0] - th) ? b : a);
        const hx = Math.round(x(r[0])) + .5;
        ctx.strokeStyle = color('--text-mute'); ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(hx, padT); ctx.lineTo(hx, padT + ph); ctx.stroke();
        for (const s of this.series) {
            if (r[s.col] == null) continue;
            ctx.beginPath(); ctx.arc(hx, y(r[s.col]), 4, 0, Math.PI * 2);
            ctx.fillStyle = color(s.color); ctx.fill();
            ctx.lineWidth = 2; ctx.strokeStyle = color('--bg-panel'); ctx.stroke();
        }
        this.tip.innerHTML = `<div class="faint">${Monitor.fmtClock(r[0])}</div>` + this.series.map(s =>
            `<div><span class="mon-key${s.dash ? ' dash' : ''}" style="--c:var(${s.color})"></span>${esc(s.label)} <b>${esc(r[s.col] == null ? '—' : fmt(r[s.col]))}</b></div>`).join('');
        this.tip.hidden = false;
        const tw = this.tip.offsetWidth;
        this.tip.style.left = (hx + 10 + tw > w ? hx - 10 - tw : hx + 10) + 'px';
    }
}

const Monitor = {
    fmtRate(v, short) {
        if (v == null) return '—';
        const u = ['B/s', 'KB/s', 'MB/s', 'GB/s'];
        let i = 0;
        while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
        return (v >= 100 || i === 0 || short ? Math.round(v) : v.toFixed(1)) + ' ' + u[i];
    },

    fmtPct(v) { return Math.round(v) + '%'; },

    fmtClock(t) {
        return new Date(t * 1000).toLocaleTimeString([], { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
    },

    fmtUptime(s) {
        if (s == null) return '—';
        const d = Math.floor(s / 86400), h = Math.floor(s % 86400 / 3600), m = Math.floor(s % 3600 / 60);
        return (d ? d + 'd ' : '') + (d || h ? h + 'h ' : '') + m + 'm';
    },

    /** Status class for a percentage / temperature: '', 'warn' or 'crit'. */
    level(v, warn, crit) { return v == null ? '' : v >= crit ? 'crit' : v >= warn ? 'warn' : ''; },

    bar(pct, warn = 70, crit = 90) {
        return `<div class="si-bar"><div class="si-fill ${Monitor.level(pct, warn, crit) || 'ok'}" style="width:${Math.min(100, pct || 0)}%"></div></div>`;
    },

    /** Build a monitor view inside `root`; returns {destroy()}. */
    create(root) {
        root.classList.add('mon');
        root.innerHTML = `
            <div class="mon-tiles"></div>
            <div class="mon-charts">
                <div class="mon-chart-box"><div class="mon-chart-head"><b>CPU</b><span class="mon-legend" data-k="cpu"></span>
                    <span class="spacer"></span>
                    <select class="input mon-window" title="Time window"><option value="60">1 min</option><option value="300" selected>5 min</option><option value="900">15 min</option></select></div>
                    <div class="mon-chart" data-chart="cpu"></div></div>
                <div class="mon-chart-box"><div class="mon-chart-head"><b>Memory</b><span class="mon-legend" data-k="mem"></span></div>
                    <div class="mon-chart" data-chart="mem"></div></div>
                <div class="mon-chart-box"><div class="mon-chart-head"><b>Network</b><span class="mon-legend" data-k="net"></span></div>
                    <div class="mon-chart" data-chart="net"></div></div>
            </div>
            <div class="mon-bottom">
                <div class="mon-panel"><div class="mon-panel-head">Block devices</div><div class="mon-blocks"></div></div>
                <div class="mon-panel"><div class="mon-panel-head">Active network interface</div><div class="mon-iface"></div></div>
            </div>`;
        const q = s => root.querySelector(s);
        const charts = [
            new TimeChart(q('[data-chart=cpu]'), [{ col: 1, label: 'CPU', color: '--accent', fill: true }], { max: 100, fmt: Monitor.fmtPct }),
            new TimeChart(q('[data-chart=mem]'), [{ col: 2, label: 'RAM used', color: '--info', fill: true }], { max: 100, fmt: Monitor.fmtPct }),
            new TimeChart(q('[data-chart=net]'), [
                { col: 3, label: 'RX', color: '--info' },
                { col: 4, label: 'TX', color: '--warn', dash: true },
            ], { fmt: Monitor.fmtRate }),
        ];
        const sel = q('.mon-window');
        try { sel.value = localStorage.getItem('monitor.window') || '300'; } catch (e) { /* storage unavailable */ }
        const applyWindow = () => { charts.forEach(c => { c.window = +sel.value; c.draw(); }); };
        sel.addEventListener('change', () => {
            try { localStorage.setItem('monitor.window', sel.value); } catch (e) { /* storage unavailable */ }
            applyWindow();
        });
        applyWindow();

        const unsubscribe = MonitorData.subscribe(d => {
            Monitor._render(root, d);
            charts.forEach(c => c.draw());
        });
        return { destroy() { unsubscribe(); root.innerHTML = ''; } };
    },

    _render(root, d) {
        const c = d.current || {};
        const cpu = c.cpu, mem = c.mem, net = c.net || {};
        const q = s => root.querySelector(s);
        if (!cpu) { q('.mon-tiles').innerHTML = '<div class="muted">Collecting samples…</div>'; return; }

        const tile = (icon, label, value, sub, lvl, extra = '') =>
            `<div class="mon-tile ${lvl}"><div class="mon-tile-label"><i class="${icon}"></i> ${label}</div>
                <div class="mon-tile-value">${value}</div><div class="mon-tile-sub">${sub}</div>${extra}</div>`;
        const cores = cpu.cores.map(p => `<i style="height:${Math.max(2, p)}%" class="${Monitor.level(p, 70, 90)}" title="${p}%"></i>`).join('');
        const tempLvl = Monitor.level(c.temp, 70, 85);
        q('.mon-tiles').innerHTML =
            tile('fa-solid fa-microchip', 'CPU', Monitor.fmtPct(cpu.pct),
                `${cpu.count} cores${cpu.freq_mhz ? ' · ' + cpu.freq_mhz + ' MHz' : ''} · load ${cpu.load.map(esc).join(' ')}`,
                Monitor.level(cpu.pct, 70, 90), `<div class="mon-cores" title="Per-core load">${cores}</div>`) +
            tile('fa-solid fa-memory', 'RAM', Monitor.fmtPct(mem.pct),
                `${App.fmtBytes(mem.used)} / ${App.fmtBytes(mem.total)}`, Monitor.level(mem.pct, 80, 92), Monitor.bar(mem.pct, 80, 92)) +
            (mem.swap_total ? tile('fa-solid fa-right-left', 'Swap', Monitor.fmtPct(mem.swap_pct),
                `${App.fmtBytes(mem.swap_used)} / ${App.fmtBytes(mem.swap_total)}`, '', Monitor.bar(mem.swap_pct, 80, 95)) : '') +
            (c.temp != null ? tile(`fa-solid fa-temperature-${tempLvl === 'crit' ? 'full' : tempLvl === 'warn' ? 'three-quarters' : 'half'}`,
                'Temperature', c.temp.toFixed(1) + ' °C',
                c.sensors.map(s => `${esc(s.name)} ${s.temp}°`).join(' · '), tempLvl) : '') +
            tile('fa-solid fa-network-wired', esc(net.iface || 'Network'),
                `<span class="mon-rx">↓ ${Monitor.fmtRate(net.rx_rate)}</span>`,
                `<span class="mon-tx">↑ ${Monitor.fmtRate(net.tx_rate)}</span>`,
                net.iface && net.operstate === 'up' ? '' : 'warn') +
            tile('fa-solid fa-clock', 'Uptime', Monitor.fmtUptime(d.uptime), `${esc(c.procs)} processes · ${esc(d.hostname)}`, '');

        q('[data-k=cpu]').textContent = Monitor.fmtPct(cpu.pct);
        q('[data-k=mem]').textContent = `${Monitor.fmtPct(mem.pct)} · ${App.fmtBytes(mem.used)}`;
        q('[data-k=net]').innerHTML =
            `<span class="mon-key" style="--c:var(--info)"></span>RX ${Monitor.fmtRate(net.rx_rate)}` +
            `<span class="mon-key dash" style="--c:var(--warn)"></span>TX ${Monitor.fmtRate(net.tx_rate)}`;

        q('.mon-blocks').innerHTML = Monitor._blocks(d.blocks || [], c.disk || {});
        q('.mon-iface').innerHTML = Monitor._iface(net);
    },

    _blocks(blocks, io) {
        if (!blocks.length) return '<div class="tbl-empty">No block devices</div>';
        const row = (b, child) => {
            const s = io[b.name] || {};
            const usage = b.fssize
                ? `${Monitor.bar(b.fsused * 100 / b.fssize, 80, 92)}<span class="small">${App.fmtBytes(b.fsused)} / ${App.fmtBytes(b.fssize)} · ${Math.round(b.fsused * 100 / b.fssize)}%</span>`
                : '<span class="faint">—</span>';
            const flags = [b.ro ? '<span class="badge badge-muted">RO</span>' : '',
                           b.rm ? '<span class="badge badge-info">removable</span>' : ''].join(' ');
            const what = child ? [b.fstype].filter(Boolean)
                : [b.tran.toUpperCase(), b.model].filter(Boolean);
            const temp = b.temp != null
                ? ` <span class="${Monitor.level(b.temp, 60, 70) ? 'text-' + (Monitor.level(b.temp, 60, 70) === 'crit' ? 'error' : 'warn') : 'faint'}">${b.temp} °C</span>` : '';
            const ioText = s.read_rate || s.write_rate
                ? `<span class="mon-rx">R ${Monitor.fmtRate(s.read_rate)}</span> <span class="mon-tx">W ${Monitor.fmtRate(s.write_rate)}</span>`
                : '<span class="faint">idle</span>';
            return `<tr>
                <td class="mono nowrap${child ? ' mon-child' : ''}">${child ? '<span class="faint">└ </span>' : '<i class="fa-solid fa-hard-drive faint"></i> '}${esc(b.name)}${temp}
                    <div class="small faint">${esc(what.join(' · '))} ${flags}</div></td>
                <td class="num nowrap small">${App.fmtBytes(b.size)}</td>
                <td class="mon-usage">${usage}</td>
                <td class="small mono">${b.mounts.map(esc).join('<br>') || '<span class="faint">—</span>'}</td>
                <td class="small nowrap">${ioText}${s.busy ? `<div class="faint">busy ${s.busy}%</div>` : ''}</td>
            </tr>`;
        };
        const rows = blocks.map(b => row(b, false) + b.children.map(ch => row(ch, true)).join('')).join('');
        return `<div class="mon-scroll"><table class="tbl mon-tbl"><thead><tr><th>Device</th><th class="num">Size</th>
            <th>Usage</th><th>Mounted</th><th>I/O</th></tr></thead><tbody>${rows}</tbody></table></div>`;
    },

    _iface(n) {
        if (!n.iface) return '<div class="tbl-empty">No active interface (no default route)</div>';
        const up = n.operstate === 'up';
        const kv = (k, v) => `<div class="si-kv"><span class="k">${k}</span><span class="v">${v}</span></div>`;
        return `<div class="mon-iface-name"><i class="fa-solid fa-${n.wireless ? 'wifi' : 'ethernet'}"></i>
                <b class="mono">${esc(n.iface)}</b>
                <span class="badge ${up ? 'badge-ok' : 'badge-error'}">${up ? '● UP' : '○ ' + esc((n.operstate || 'down').toUpperCase())}</span>
                ${n.carrier ? '' : '<span class="badge badge-error">no carrier</span>'}</div>` +
            kv('Speed', n.speed ? (n.speed >= 1000 ? n.speed / 1000 + ' Gb/s' : n.speed + ' Mb/s') : '—') +
            kv('Addresses', (n.addrs || []).map(a => `<span class="mono">${esc(a)}</span>`).join('<br>') || '—') +
            kv('Gateway', `<span class="mono">${esc(n.gateway || '—')}</span>`) +
            kv('MAC / MTU', `<span class="mono">${esc(n.mac)}</span> · ${esc(n.mtu)}`) +
            kv('Rate', `<span class="mon-rx">↓ ${Monitor.fmtRate(n.rx_rate)}</span> &nbsp;<span class="mon-tx">↑ ${Monitor.fmtRate(n.tx_rate)}</span>`) +
            kv('Total', `↓ ${App.fmtBytes(n.rx_bytes)} (${n.rx_packets} pkt) · ↑ ${App.fmtBytes(n.tx_bytes)} (${n.tx_packets} pkt)`) +
            kv('Errors / drops', `<span class="${n.rx_errors + n.tx_errors ? 'text-error' : ''}">${n.rx_errors + n.tx_errors}</span> / ${n.rx_dropped + n.tx_dropped}`);
    },
};


/** Floating monitor window on pages other than the main one: drag, resize, opacity, close. */
const MonitorFloat = {
    KEY: 'monitor.float',
    view: null,

    el() { return document.getElementById('mon-float'); },

    _state() {
        try { return JSON.parse(localStorage.getItem(this.KEY)) || {}; } catch (e) { return {}; }
    },

    _save(patch) {
        try { localStorage.setItem(this.KEY, JSON.stringify({ ...this._state(), ...patch })); } catch (e) { /* storage unavailable */ }
    },

    toggle() { this.view ? this.close() : this.open(); },

    open() {
        const win = this.el();
        if (!win || this.view) return;
        const st = this._state();
        win.style.width = (st.w || 720) + 'px';
        win.style.height = (st.h || 560) + 'px';
        win.style.left = (st.x != null ? st.x : window.innerWidth - (st.w || 720) - 20) + 'px';
        win.style.top = (st.y != null ? st.y : 60) + 'px';
        const op = st.opacity || 100;
        document.getElementById('mon-opacity').value = op;
        this._opacity(op);
        win.hidden = false;
        this._clamp();
        this.view = Monitor.create(document.getElementById('mon-float-body'));
        this._save({ open: true });
    },

    close() {
        if (!this.view) return;
        this.view.destroy();
        this.view = null;
        this.el().hidden = true;
        this._save({ open: false });
    },

    _opacity(v) {
        this.el().style.opacity = v / 100;
        document.getElementById('mon-opacity-val').textContent = v + '%';
    },

    _clamp() {
        const win = this.el(), r = win.getBoundingClientRect();
        const x = Math.min(Math.max(0, r.left), Math.max(0, window.innerWidth - 80));
        const y = Math.min(Math.max(0, r.top), Math.max(0, window.innerHeight - 40));
        win.style.left = x + 'px';
        win.style.top = y + 'px';
    },

    init() {
        const win = this.el();
        if (!win) return;
        const head = win.querySelector('.mon-float-head');
        head.addEventListener('pointerdown', e => {
            if (e.button !== 0 || e.target.closest('button, input, select')) return;
            const r = win.getBoundingClientRect(), dx = e.clientX - r.left, dy = e.clientY - r.top;
            head.setPointerCapture(e.pointerId);
            win.classList.add('dragging');
            const move = ev => {
                win.style.left = Math.min(Math.max(0, ev.clientX - dx), window.innerWidth - 80) + 'px';
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
        // native CSS resize handle: remember the size
        new ResizeObserver(() => {
            if (!win.hidden) this._save({ w: win.offsetWidth, h: win.offsetHeight });
        }).observe(win);
        const range = document.getElementById('mon-opacity');
        range.addEventListener('input', () => { this._opacity(+range.value); this._save({ opacity: +range.value }); });
        window.addEventListener('resize', () => { if (!win.hidden) this._clamp(); });
        if (this._state().open) this.open();        // stays open while navigating between pages
    },
};

MonitorFloat.init();
