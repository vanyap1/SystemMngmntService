/* ==========================================================================
   Test log viewer (templates/logs.html): filters, statistics, run list,
   parsed log view and per-step analysis. Filters live in location.hash
   (#script=…&verdict=FAIL,ERROR&q=…&from=…&to=…&step=…&open=<log>) so a view can be linked.
   ========================================================================== */

const Logs = {
    PAGE: 100,
    filters: {},
    offset: 0,
    items: [],              // rows of the current page
    total: 0,
    current: null,          // parsed log in the viewer
    mode: 'steps',
    stepName: '',

    // ── filters / URL state ──
    readHash() {
        const p = new URLSearchParams(location.hash.slice(1));
        this.filters = {};
        ['script', 'verdict', 'q', 'from', 'to', 'step'].forEach(k => { if (p.get(k)) this.filters[k] = p.get(k); });
        document.getElementById('lg-script').value = this.filters.script || '';
        document.getElementById('lg-q').value = this.filters.q || '';
        document.getElementById('lg-from').value = this.filters.from || '';
        document.getElementById('lg-to').value = this.filters.to || '';
        const vs = (this.filters.verdict || '').split(',');
        document.querySelectorAll('#lg-verdicts button').forEach(b => b.classList.toggle('active', vs.includes(b.dataset.v)));
        const sf = document.getElementById('lg-step-filter');
        sf.hidden = !this.filters.step;
        sf.innerHTML = this.filters.step ? `failed: ${esc(this.filters.step)} <i class="fa-solid fa-xmark" onclick="Logs.set({step: ''})"></i>` : '';
        return p.get('open');
    },

    query(extra = {}) {
        const p = new URLSearchParams({ ...this.filters, ...extra });
        return p.toString();
    },

    writeHash(open) {
        const p = new URLSearchParams(this.filters);
        if (open) p.set('open', open);
        const h = p.toString();
        history.replaceState(null, '', h ? '#' + h : location.pathname);
    },

    set(patch) {
        Object.entries(patch).forEach(([k, v]) => { if (v) this.filters[k] = v; else delete this.filters[k]; });
        this.offset = 0;
        this.writeHash();
        this.readHash();
        this.load();
    },

    reset() { this.filters = {}; this.offset = 0; this.writeHash(); this.readHash(); this.load(); },

    // ── list ──
    load() {
        document.getElementById('lg-csv').href = '/api/logs/export.csv?' + this.query();
        return App.api(`/api/logs?${this.query({ offset: this.offset, limit: this.PAGE })}`).then(d => {
            this.items = d.items;
            this.total = d.total;
            const sel = document.getElementById('lg-script');
            const cur = this.filters.script || '';
            sel.innerHTML = '<option value="">All scripts</option>' +
                d.scripts.map(s => `<option value="${esc(s)}">${esc(s)}</option>`).join('');
            sel.value = cur;
            this.renderSummary(d.summary);
            this.renderList();
        }).catch(e => {
            document.getElementById('lg-list').innerHTML = `<div class="tbl-empty text-error">${esc(e.message)}</div>`;
        });
    },

    renderSummary(s) {
        const v = s.verdicts;
        const tile = (cls, label, value, title, verdict) =>
            `<div class="lg-tile ${cls}${verdict ? ' clickable' : ''}" title="${title}"${verdict ? ` onclick="Logs.set({verdict: '${verdict}'})"` : ''}>
                <b>${value}</b><span>${label}</span></div>`;
        const pct = x => x == null ? '—' : x + '%';
        document.getElementById('lg-tiles').innerHTML =
            tile('', 'Runs', s.runs, 'Runs matching the filter') +
            tile('st-pass', 'Pass', v.PASS, 'Show PASS runs', 'PASS') +
            tile('st-fail', 'Fail', v.FAIL, 'Show FAIL runs', 'FAIL') +
            tile('st-error', 'Error', v.ERROR, 'Show ERROR runs', 'ERROR') +
            tile('st-stopped', 'Stopped', v.STOPPED, 'Show stopped runs', 'STOPPED') +
            tile('st-yield', 'Yield', pct(s.yield), 'PASS / (PASS + FAIL + ERROR), stopped runs excluded') +
            tile('', 'Boards', s.boards, 'Distinct serial numbers (runs with a serial)') +
            tile('st-yield', 'First-pass', pct(s.fpy), 'Boards whose first finished run passed');
        const top = s.top_failures;
        const max = Math.max(1, ...top.map(t => t.count));
        document.getElementById('lg-top').innerHTML = top.length ? top.map(t => `
            <div class="lg-fail-row" onclick='Logs.openStep(${esc(JSON.stringify(t.name))})'>
                <span class="lg-fail-name" title="${esc(t.name)}">${esc(t.name)}</span>
                <span class="lg-fail-bar"><i style="width:${t.count * 100 / max}%"></i></span>
                <b>${t.count}</b>
                <button class="btn-icon" title="Runs where this step failed" onclick='event.stopPropagation(); Logs.set({step: ${esc(JSON.stringify(t.name))}})'><i class="fa-solid fa-filter"></i></button>
            </div>`).join('') : '<div class="tbl-empty">No failures 🎉</div>';
    },

    verdictBadge(v) {
        return `<span class="lg-verdict v-${esc(v)}">${esc(v)}</span>`;
    },

    renderList() {
        const n = this.total, from = n ? this.offset + 1 : 0, to = Math.min(n, this.offset + this.PAGE);
        document.getElementById('lg-count').textContent = n ? `${from}–${to} of ${n}` : '';
        const pages = Math.ceil(n / this.PAGE), page = Math.floor(this.offset / this.PAGE);
        document.getElementById('lg-pager').innerHTML = pages > 1 ? `
            <button class="btn-icon" ${page ? '' : 'disabled'} onclick="Logs.page(-1)" title="Newer"><i class="fa-solid fa-chevron-left"></i></button>
            <span class="small muted">page ${page + 1} / ${pages}</span>
            <button class="btn-icon" ${page < pages - 1 ? '' : 'disabled'} onclick="Logs.page(1)" title="Older"><i class="fa-solid fa-chevron-right"></i></button>` : '';
        if (!this.items.length) {
            document.getElementById('lg-list').innerHTML = '<div class="tbl-empty">No logs match the filter</div>';
            return;
        }
        document.getElementById('lg-list').innerHTML = `<table class="tbl lg-tbl"><thead><tr>
            <th>Started</th><th>Script</th><th>Serial</th><th>Verdict</th><th class="num">Steps ✓ / ✗ / !</th>
            <th class="num">Time</th><th>First failure</th><th></th></tr></thead><tbody>` +
            this.items.map((l, i) => {
                const ff = l.first_fail;
                const n = esc(JSON.stringify(l.name));
                return `<tr class="clickable" onclick="Logs.openIndex(${i})">
                    <td class="nowrap mono small">${esc(App.fmtDate(l.started))}</td>
                    <td class="mono small">${esc(l.script)}</td>
                    <td class="mono">${l.serial ? `<a href="#" onclick='event.preventDefault(); event.stopPropagation(); Logs.set({q: ${esc(JSON.stringify(l.serial))}})' title="All runs of this board">${esc(l.serial)}</a>` : '<span class="faint">—</span>'}</td>
                    <td>${this.verdictBadge(l.verdict)}</td>
                    <td class="num mono small"><span class="text-ok">${l.counts.PASS}</span> / <span class="${l.counts.FAIL ? 'text-error' : 'faint'}">${l.counts.FAIL}</span> / <span class="${l.counts.ERROR ? 'text-warn' : 'faint'}">${l.counts.ERROR}</span></td>
                    <td class="num small nowrap">${l.duration != null ? l.duration + ' s' : ''}</td>
                    <td class="small lg-ff">${ff ? `<b>${esc(ff.name)}</b> <span class="mono faint">${esc(ff.condition)}</span>` : ''}</td>
                    <td class="nowrap" onclick="event.stopPropagation()">
                        <a class="btn-icon" href="/api/tests/logs/${encodeURIComponent(l.name)}?download=1" title="Download"><i class="fa-solid fa-download"></i></a>
                        <button class="btn-icon" onclick="Logs.remove(${n})" title="Delete"><i class="fa-solid fa-trash-can"></i></button>
                    </td></tr>`;
            }).join('') + '</tbody></table>';
    },

    page(dir) {
        this.offset = Math.max(0, this.offset + dir * this.PAGE);
        this.load();
    },

    remove(name) {
        if (!confirm(`Delete log "${name}"?`)) return;
        App.api('/api/tests/logs/delete', { json: { name } })
            .then(() => { toast('Deleted'); this.load(); })
            .catch(e => toast(e.message, true));
    },

    // ── viewer ──
    openIndex(i) { this.open(this.items[i].name); },

    open(name) {
        return App.api('/api/logs/view/' + encodeURIComponent(name)).then(log => {
            this.current = log;
            this.writeHash(name);
            const h = log.header, f = log.footer;
            document.getElementById('lv-title').innerHTML =
                `${this.verdictBadge(log.verdict)} <span class="mono">${esc(log.script)}</span>` +
                (log.serial ? ` <span class="mono text-ok">${esc(log.serial)}</span>` : '');
            document.getElementById('lv-meta').innerHTML = [
                ['Started', h.started], ['Finished', f.finished], ['Duration', f.duration != null ? f.duration + ' s' : ''],
                ['Exit code', f.exit_code], ['Stop on fail', h.stop_on_fail], ['Host', h.host],
                ['Steps', `${log.counts.PASS} pass · ${log.counts.FAIL} fail · ${log.counts.ERROR} error`], ['File', log.name],
            ].filter(r => r[1]).map(([k, v]) => `<span><i>${k}</i> ${esc(v)}</span>`).join('');
            document.getElementById('lv-download').href = '/api/tests/logs/' + encodeURIComponent(name) + '?download=1';
            document.getElementById('lv-overlay').classList.add('open');
            this.renderLog();
            document.getElementById('lv-body').scrollTop = 0;
        }).catch(e => toast(e.message, true));
    },

    closeLog() {
        document.getElementById('lv-overlay').classList.remove('open');
        this.current = null;
        this.writeHash();
    },

    isOpen() { return document.getElementById('lv-overlay').classList.contains('open'); },

    /** Open the newer (-1) / older (+1) run of the list, crossing pages. */
    step(dir) {
        if (!this.current) return;
        const i = this.items.findIndex(l => l.name === this.current.name);
        const j = i + dir;
        if (i >= 0 && j >= 0 && j < this.items.length) return this.open(this.items[j].name);
        const off = this.offset + dir * this.PAGE;
        if (i < 0 || off < 0 || off >= this.total) return;
        this.offset = off;
        this.load().then(() => this.open(this.items[dir > 0 ? 0 : this.items.length - 1].name));
    },

    setMode(mode) {
        this.mode = mode;
        document.querySelectorAll('.lv-modes button').forEach(b => b.classList.toggle('active', b.dataset.mode === mode));
        this.renderLog();
    },

    /** Position of a measured value between its limits (limits at 20 % / 80 % of the bar). */
    measureBar(cond, status) {
        const m = (cond || '').match(/^\s*(-?[\d.eE+]+)\s*<\s*(-?[\d.eE+]+)\s*<\s*(-?[\d.eE+]+)\s*$/);
        if (!m) return '';
        const [lo, v, hi] = m.slice(1).map(Number);
        if (!(hi > lo)) return '';
        const pos = Math.min(100, Math.max(0, 20 + (v - lo) / (hi - lo) * 60));
        return `<span class="lv-mbar" title="${lo} … ${hi}"><i class="lim" style="left:20%"></i><i class="lim" style="left:80%"></i>` +
               `<i class="val s-${esc(status)}" style="left:${pos}%"></i></span>`;
    },

    renderLog() {
        const log = this.current;
        if (!log) return;
        const q = document.getElementById('lv-search').value.trim().toLowerCase();
        const body = document.getElementById('lv-body');
        const hl = text => {
            const s = esc(text);
            if (!q) return s;
            const re = new RegExp(q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'), 'gi');
            return s.replace(re, x => `<mark>${x}</mark>`);
        };
        if (this.mode === 'raw') {
            App.api('/api/tests/logs/' + encodeURIComponent(log.name)).then(text => {
                if (this.current !== log || this.mode !== 'raw') return;
                const lines = text.split('\n').filter(l => !q || l.toLowerCase().includes(q));
                body.innerHTML = `<pre class="lv-raw">${lines.map(hl).join('\n')}</pre>`;
            });
            return;
        }
        const showOut = document.getElementById('lv-output').checked;
        let idx = 0, rows = '';
        for (const it of log.items) {
            const text = [it.name, it.condition, it.units, it.text].filter(Boolean).join(' ').toLowerCase();
            if (it.type === 'step') idx++;
            if (q && !text.includes(q)) continue;
            if (it.type === 'step') {
                rows += `<tr class="lv-step s-${esc(it.status)}">
                    <td class="num faint">${idx}</td>
                    <td class="num mono small faint">${it.t.toFixed(2)}s</td>
                    <td><a href="#" onclick='event.preventDefault(); Logs.openStep(${esc(JSON.stringify(it.name))})' title="Analyse this step across runs">${hl(it.name)}</a></td>
                    <td class="mono lv-cond">${hl(it.condition)}${this.measureBar(it.condition, it.status)}</td>
                    <td class="small muted">${hl(it.units)}</td>
                    <td><span class="lg-verdict v-${esc(it.status)}">${esc(it.status)}</span></td></tr>`;
            } else if (it.type === 'section') {
                const stop = /^stop on fail/i.test(it.name);
                rows += `<tr class="lv-section${stop ? ' stop' : ''}"><td colspan="6"><i class="fa-solid fa-${stop ? 'forward' : 'flag-checkered'}"></i> ${hl(it.name)}</td></tr>`;
            } else if (it.type === 'prompt' || it.type === 'answer') {
                rows += `<tr class="lv-qa"><td></td><td colspan="5"><i class="fa-solid fa-${it.type === 'prompt' ? 'circle-question' : 'reply'}"></i> ${hl(it.text)}</td></tr>`;
            } else if (showOut) {
                rows += `<tr class="lv-out"><td></td><td colspan="5" class="mono">${hl(it.text)}</td></tr>`;
            }
        }
        body.innerHTML = rows
            ? `<table class="tbl lv-tbl"><thead><tr><th class="num">#</th><th class="num">Time</th><th>Step</th><th>Condition / value</th><th>Units</th><th>Status</th></tr></thead><tbody>${rows}</tbody></table>`
            : '<div class="tbl-empty">Nothing matches</div>';
    },

    // ── step analysis ──
    openStep(name) {
        this.stepName = name;
        document.getElementById('sa-title').textContent = name;
        document.getElementById('sa-body').innerHTML = '<div class="tbl-empty">Loading…</div>';
        document.getElementById('sa-overlay').classList.add('open');
        const f = { ...this.filters };
        delete f.step;
        App.api('/api/logs/step?' + new URLSearchParams({ ...f, name })).then(d => this.renderStep(d))
            .catch(e => { document.getElementById('sa-body').innerHTML = `<div class="tbl-empty text-error">${esc(e.message)}</div>`; });
    },

    closeStep() { document.getElementById('sa-overlay').classList.remove('open'); },

    filterStep() { this.closeStep(); this.closeLog(); this.set({ step: this.stepName }); },

    renderStep(d) {
        const s = d.stats, u = s.units ? ' ' + esc(s.units) : '';
        const kv = (k, v, cls = '') => `<div class="lg-tile ${cls}"><b>${v}</b><span>${k}</span></div>`;
        let h = '<div class="lg-tiles">' + kv('Occurrences', s.n) +
            kv('Pass', s.status.PASS || 0, 'st-pass') + kv('Fail', s.status.FAIL || 0, 'st-fail') +
            (s.status.ERROR ? kv('Error', s.status.ERROR, 'st-error') : '');
        if (s.mean != null) {
            const cpkCls = s.cpk == null ? '' : s.cpk >= 1.33 ? 'st-pass' : s.cpk >= 1 ? 'st-error' : 'st-fail';
            h += kv('Limits', `${s.lo} … ${s.hi}${u}`) + kv('Min', s.min + u) + kv('Mean', s.mean + u) +
                 kv('Max', s.max + u) + kv('σ', s.stdev) +
                 kv('Cpk', s.cpk ?? '—', cpkCls);
        }
        h += '</div>';
        const pts = d.rows.filter(r => r.value != null).slice().reverse();     // oldest → newest
        if (pts.length > 1) h += this.scatter(pts, s);
        h += `<table class="tbl lv-tbl"><thead><tr><th>Started</th><th>Serial</th><th>Condition / value</th><th>Units</th><th>Status</th></tr></thead><tbody>` +
            d.rows.map(r => `<tr class="clickable" onclick='Logs.closeStep(); Logs.open(${esc(JSON.stringify(r.log))})'>
                <td class="nowrap mono small">${esc(App.fmtDate(r.started))}</td>
                <td class="mono">${esc(r.serial) || '<span class="faint">—</span>'}</td>
                <td class="mono lv-cond">${esc(r.condition)}${this.measureBar(r.condition, r.status)}</td>
                <td class="small muted">${esc(r.units)}</td>
                <td><span class="lg-verdict v-${esc(r.status)}">${esc(r.status)}</span></td></tr>`).join('') +
            '</tbody></table>';
        document.getElementById('sa-body').innerHTML = h;
    },

    /** SVG run chart: measured values in run order with the limit lines (one y-axis). */
    scatter(pts, s) {
        const W = 760, H = 180, pl = 54, pr = 10, pt = 10, pb = 18;
        const vals = pts.map(p => p.value).concat([s.lo, s.hi]);
        let lo = Math.min(...vals), hi = Math.max(...vals);
        const pad = (hi - lo) * 0.1 || 1;
        lo -= pad; hi += pad;
        const x = i => pl + (pts.length === 1 ? 0 : i / (pts.length - 1)) * (W - pl - pr);
        const y = v => pt + (hi - v) / (hi - lo) * (H - pt - pb);
        const fmt = v => Math.abs(v) >= 1000 ? v.toFixed(0) : +v.toPrecision(4);
        let g = '';
        [s.lo, s.hi].forEach(v => {
            g += `<line x1="${pl}" x2="${W - pr}" y1="${y(v)}" y2="${y(v)}" class="sa-lim"/>` +
                 `<text x="${pl - 6}" y="${y(v) + 3}" class="sa-lbl" text-anchor="end">${fmt(v)}</text>`;
        });
        g += `<line x1="${pl}" x2="${W - pr}" y1="${y(s.mean)}" y2="${y(s.mean)}" class="sa-mean"/>` +
             `<text x="${W - pr}" y="${y(s.mean) - 4}" class="sa-lbl" text-anchor="end">x̄ ${fmt(s.mean)}</text>`;
        g += `<polyline class="sa-line" points="${pts.map((p, i) => `${x(i)},${y(p.value)}`).join(' ')}"/>`;
        g += pts.map((p, i) => `<circle cx="${x(i)}" cy="${y(p.value)}" r="4" class="sa-pt s-${esc(p.status)}"><title>${esc(App.fmtDate(p.started))} ${esc(p.serial)}: ${p.value}${esc(p.units ? ' ' + p.units : '')} (${esc(p.status)})</title></circle>`).join('');
        g += `<text x="${pl}" y="${H - 4}" class="sa-lbl">oldest</text><text x="${W - pr}" y="${H - 4}" class="sa-lbl" text-anchor="end">newest · ${pts.length} values</text>`;
        return `<div class="sa-chart"><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Values of the step in run order">${g}</svg></div>`;
    },

    init() {
        const open = this.readHash();
        document.getElementById('lg-script').addEventListener('change', e => this.set({ script: e.target.value }));
        document.getElementById('lg-from').addEventListener('change', e => this.set({ from: e.target.value }));
        document.getElementById('lg-to').addEventListener('change', e => this.set({ to: e.target.value }));
        let t;
        document.getElementById('lg-q').addEventListener('input', e => {
            clearTimeout(t);
            t = setTimeout(() => this.set({ q: e.target.value.trim() }), 300);
        });
        document.querySelectorAll('#lg-verdicts button').forEach(b => b.addEventListener('click', () => {
            b.classList.toggle('active');
            const vs = [...document.querySelectorAll('#lg-verdicts button.active')].map(x => x.dataset.v);
            this.set({ verdict: vs.join(',') });
        }));
        document.getElementById('lv-search').addEventListener('input', () => this.renderLog());
        document.getElementById('lv-output').addEventListener('change', () => this.renderLog());
        document.addEventListener('keydown', e => {
            if (!this.isOpen() || document.getElementById('sa-overlay').classList.contains('open')) return;
            if (e.target.matches('input, textarea, select')) return;
            if (e.key === 'ArrowLeft') this.step(-1);
            if (e.key === 'ArrowRight') this.step(1);
        });
        App.onEscape(() => {
            if (document.getElementById('sa-overlay').classList.contains('open')) this.closeStep();
            else if (this.isOpen()) this.closeLog();
        });
        this.load().then(() => { if (open) this.open(open); });
    },
};

Logs.init();
