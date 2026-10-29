/* ==========================================================================
   Test platform page (templates/tests.html). Polls /api/tests/status
   incrementally: only new results/output lines are transferred each tick.
   ========================================================================== */

const Tests = {
    runId: null,
    runScript: null,
    prompt: null,
    resultsCount: 0,
    outputCount: 0,
    state: 'IDLE',
    scripts: [],
    _timer: null,

    // ── Scripts ──
    loadScripts() {
        const sel = document.getElementById('test-script');
        const saved = Tests._saved();
        App.api('/api/tests/scripts').then(d => {
            Tests.scripts = d.scripts;
            if (!d.scripts.length) {
                sel.innerHTML = '<option value="">No *_test.py scripts found</option>';
                return;
            }
            const cur = sel.value || Tests.runScript || saved;
            sel.innerHTML = d.scripts.map(s =>
                `<option value="${esc(s.name)}"${s.name === cur ? ' selected' : ''}>${esc(s.name)}</option>`).join('');
            Tests.showDescription();
        }).catch(e => toast(e.message, true));
    },

    // ── Board statistics (per selected script, from run logs) ──
    loadStats() {
        const script = document.getElementById('test-script').value;
        if (!script) return;
        App.api('/api/tests/stats?script=' + encodeURIComponent(script)).then(st => {
            document.getElementById('brd-total').textContent = st.total;
            document.getElementById('brd-pass').textContent = st.PASS;
            document.getElementById('brd-fail').textContent = st.FAIL;
            document.getElementById('brd-error').textContent = st.ERROR;
            document.getElementById('brd-yield').textContent =
                st.total ? (st.PASS * 100 / st.total).toFixed(1) + '%' : '—';
        }).catch(() => {});
    },

    showDescription() {
        Tests.loadStats();
        const name = document.getElementById('test-script').value;
        const s = Tests.scripts.find(x => x.name === name);
        document.getElementById('script-desc').textContent = s ? s.description : '';
        try { localStorage.setItem('tests.script', name); } catch (e) { /* storage unavailable */ }
    },

    _saved() {
        try { return localStorage.getItem('tests.script') || ''; } catch (e) { return ''; }
    },

    // ── Run control ──
    start() {
        const script = document.getElementById('test-script').value;
        if (!script) return toast('Select a test script', true);
        const serial = document.getElementById('test-serial').value.trim();
        const stop_on_fail = document.getElementById('stop-on-fail').checked;
        document.getElementById('btn-start').disabled = true;
        App.api('/api/tests/start', { json: { script, serial, stop_on_fail } })
            .then(() => Tests.poll())
            .catch(e => { toast(e.message, true); Tests.poll(); });
    },

    stop() {
        document.getElementById('btn-stop').disabled = true;
        App.api('/api/tests/stop', { method: 'POST' })
            .then(() => toast('Stopping test…'))
            .catch(e => toast(e.message, true))
            .finally(() => Tests.poll());
    },

    // ── Status polling ──
    poll() {
        clearTimeout(Tests._timer);
        const q = `run_id=${Tests.runId ?? ''}&results_from=${Tests.resultsCount}&output_from=${Tests.outputCount}`;
        App.api('/api/tests/status?' + q)
            .then(d => Tests.apply(d.run))
            .catch(() => {})
            .finally(() => {
                Tests._timer = setTimeout(Tests.poll, Tests.state === 'RUNNING' ? 600 : 3000);
            });
    },

    apply(run) {
        if (!run) return Tests.setState('IDLE');
        if (run.id !== Tests.runId) Tests.reset(run);
        if (run.results_from === Tests.resultsCount) run.results.forEach(Tests.addResult);
        if (run.output_from === Tests.outputCount) Tests.addOutput(run.output);

        const c = run.counts;
        document.getElementById('cnt-pass').textContent = c.PASS;
        document.getElementById('cnt-fail').textContent = c.FAIL;
        document.getElementById('cnt-error').textContent = c.ERROR;
        document.getElementById('run-time').textContent = run.elapsed.toFixed(1) + ' s';

        const wasRunning = Tests.state === 'RUNNING';
        Tests.setState(run.state);
        Tests.showPrompt(run.state === 'RUNNING' ? run.prompt : null);
        if (run.state !== 'RUNNING') {
            Tests.showVerdict(run);
            if (wasRunning) {
                Tests.loadLogs();
                Tests.loadStats();
                Tests.focusSerial();   // ready to scan the next unit
            }
        }
    },

    reset(run) {
        Tests.runId = run.id;
        Tests.runScript = run.script;
        Tests.resultsCount = 0;
        Tests.outputCount = 0;
        document.getElementById('results-body').innerHTML = '';
        document.getElementById('output').textContent = '';
        document.getElementById('verdict').hidden = true;
        const sel = document.getElementById('test-script');
        if ([...sel.options].some(o => o.value === run.script)) { sel.value = run.script; Tests.showDescription(); }
        document.getElementById('run-title').textContent = `#${run.id} ${run.script}` +
            (run.serial ? ` · SN ${run.serial}` : '') + (run.stop_on_fail ? ' · stop on fail' : '') + ` — ${new Date(run.started * 1000).toLocaleString()}`;
    },

    setState(state) {
        Tests.state = state;
        const el = document.getElementById('run-state');
        el.textContent = state;
        el.className = 'run-state state-' + state;
        const running = state === 'RUNNING';
        document.getElementById('btn-start').disabled = running;
        document.getElementById('btn-stop').disabled = !running;
        document.getElementById('test-script').disabled = running;
        document.getElementById('test-serial').disabled = running;
        document.getElementById('stop-on-fail').disabled = running;
    },

    focusSerial() {
        const el = document.getElementById('test-serial');
        el.focus();
        el.select();
    },

    addResult(r) {
        const tr = document.createElement('tr');
        if (r.status === 'SECTION') {
            tr.className = 'r-section' + (r.name.startsWith('Stop on fail') ? ' r-section-stop' : '');
            tr.innerHTML = `<td colspan="6"><i class="fa-solid ${r.name.startsWith('Stop on fail') ? 'fa-forward' : 'fa-flag-checkered'}"></i> ${esc(r.name)}</td>`;
            document.getElementById('results-body').appendChild(tr);
            Tests.resultsCount++;
            Tests.scrollResults();
            return;
        }
        tr.className = 'r-' + r.status;
        tr.innerHTML =
            `<td class="num r-idx">${r.index}</td>` +
            `<td class="r-name">${esc(r.name)}</td>` +
            `<td class="r-cond">${esc(r.condition)}</td>` +
            `<td class="r-unit">${esc(r.units)}</td>` +
            `<td class="num r-time">${r.t.toFixed(2)}s</td>` +
            `<td><span class="status-tag status-${esc(r.status)}">${esc(r.status)}</span></td>`;
        document.getElementById('results-body').appendChild(tr);
        Tests.resultsCount++;
        Tests.scrollResults();
    },

    scrollResults() {
        const wrap = document.querySelector('.results-wrap');
        requestAnimationFrame(() => { wrap.scrollTop = wrap.scrollHeight; });
    },

    addOutput(lines) {
        if (!lines.length) return;
        const pre = document.getElementById('output');
        pre.appendChild(document.createTextNode(lines.join('\n') + '\n'));
        Tests.outputCount += lines.length;
        if (document.getElementById('output-follow').checked) pre.scrollTop = pre.scrollHeight;
    },

    showVerdict(run) {
        const el = document.getElementById('verdict');
        const c = run.counts;
        el.className = 'verdict state-' + run.state;
        el.innerHTML = `${esc(run.state)}<small>${run.serial ? `SN ${esc(run.serial)} · ` : ''}${esc(run.script)} · ${run.elapsed.toFixed(1)} s · ` +
            `${c.PASS} pass / ${c.FAIL} fail / ${c.ERROR} error` +
            (run.log ? ` · log: ${esc(run.log)}` : '') + '</small>';
        el.hidden = false;
        Tests.scrollResults();   // the banner shrinks the results pane
    },

    // ── Operator prompt ──
    showPrompt(p) {
        const overlay = document.getElementById('prompt-overlay');
        const stateEl = document.getElementById('run-state');
        if (p) { stateEl.textContent = 'INPUT'; stateEl.className = 'run-state state-INPUT'; }
        if (!p) {
            Tests.prompt = null;
            overlay.classList.remove('open');
            return;
        }
        if (Tests.prompt && Tests.prompt.id === p.id) return;   // already shown
        Tests.prompt = p;
        document.getElementById('prompt-name').textContent = p.name;
        document.getElementById('prompt-message').textContent = p.message;
        document.getElementById('prompt-error').textContent = '';
        document.getElementById('prompt-field').innerHTML = Tests._promptField(p);
        document.getElementById('prompt-submit').hidden = p.type === 'buttons';
        overlay.classList.add('open');
        const focus = overlay.querySelector('#prompt-input, .prompt-buttons .btn');
        if (focus) setTimeout(() => { focus.focus(); if (focus.select) focus.select(); }, 50);
    },

    _promptField(p) {
        const def = p.default != null ? esc(p.default) : '';
        if (p.type === 'number') {
            const range = [p.min != null ? `min ${p.min}` : '', p.max != null ? `max ${p.max}` : ''].filter(Boolean).join(', ');
            return `<div class="row prompt-number">
                <input id="prompt-input" class="input" type="number" step="any" value="${def}"
                       ${p.min != null ? `min="${p.min}"` : ''} ${p.max != null ? `max="${p.max}"` : ''}>
                <span class="prompt-units">${esc(p.units)}</span></div>` +
                (range ? `<span class="hint">${esc(range)}</span>` : '');
        }
        if (p.type === 'choice') {
            return `<select id="prompt-input" class="input">` + p.options.map(o =>
                `<option value="${esc(o)}"${o === p.default ? ' selected' : ''}>${esc(o)}</option>`).join('') + '</select>';
        }
        if (p.type === 'buttons') {
            const style = o => /^(no|fail|cancel|abort)$/i.test(o) ? 'btn-danger'
                             : /^(yes|pass|ok|continue)$/i.test(o) ? 'btn-success' : 'btn-primary';
            return '<div class="prompt-buttons">' + p.options.map(o =>
                `<button type="button" class="btn btn-lg ${style(o)}" onclick="Tests.submitPrompt(${esc(JSON.stringify(o))})">${esc(o)}</button>`
            ).join('') + '</div>';
        }
        return `<input id="prompt-input" class="input" type="text" value="${def}" autocomplete="off">`;
    },

    submitPrompt(value) {
        const p = Tests.prompt;
        if (!p) return;
        if (value === undefined) value = document.getElementById('prompt-input').value;
        App.api('/api/tests/answer', { json: { run_id: Tests.runId, prompt_id: p.id, value } })
            .then(() => {
                Tests.prompt = null;
                document.getElementById('prompt-overlay').classList.remove('open');
                Tests.poll();
            })
            .catch(e => { document.getElementById('prompt-error').textContent = e.message; });
    },

    // ── History / logs ──
    loadLogs() {
        App.api('/api/tests/logs').then(d => {
            const box = document.getElementById('history');
            if (!d.logs.length) {
                box.innerHTML = '<div class="tbl-empty">No test runs yet</div>';
                return;
            }
            box.innerHTML = '<table class="tbl"><thead><tr><th>Date</th><th>Script</th><th>Serial</th><th>Verdict</th><th></th></tr></thead><tbody>' +
                d.logs.map(l => {
                    const n = esc(JSON.stringify(l.name));
                    return `<tr>
                        <td class="h-date">${App.fmtDate(l.started)}</td>
                        <td class="h-script">${esc(l.script)}</td>
                        <td class="h-serial">${esc(l.serial) || '<span class="faint">—</span>'}</td>
                        <td><span class="status-tag state-${esc(l.verdict)}">${esc(l.verdict)}</span></td>
                        <td><div class="h-acts">
                            <button class="btn btn-sm btn-ghost" onclick="Tests.openLog(${n})" title="View"><i class="fa-solid fa-eye"></i></button>
                            <a class="btn btn-sm btn-info" href="/api/tests/logs/${encodeURIComponent(l.name)}?download=1" title="Download"><i class="fa-solid fa-download"></i></a>
                            <button class="btn btn-sm btn-danger" onclick="Tests.deleteLog(${n})" title="Delete"><i class="fa-solid fa-xmark"></i></button>
                        </div></td></tr>`;
                }).join('') + '</tbody></table>';
        }).catch(e => toast(e.message, true));
    },

    openLog(name) {
        App.api('/api/tests/logs/' + encodeURIComponent(name)).then(text => {
            document.getElementById('log-title').textContent = name;
            document.getElementById('log-text').textContent = text;
            document.getElementById('log-download').href = '/api/tests/logs/' + encodeURIComponent(name) + '?download=1';
            document.getElementById('log-overlay').classList.add('open');
        }).catch(e => toast(e.message, true));
    },

    deleteLog(name) {
        if (!confirm(`Delete log "${name}"?`)) return;
        App.api('/api/tests/logs/delete', { json: { name } })
            .then(() => { Tests.loadLogs(); Tests.loadStats(); })
            .catch(e => toast(e.message, true));
    },

    clearLogs() {
        if (!confirm('Delete ALL test logs? This cannot be undone.')) return;
        App.api('/api/tests/logs/delete', { json: { all: true } })
            .then(d => { toast(`Deleted ${d.deleted} log(s)`); Tests.loadLogs(); Tests.loadStats(); })
            .catch(e => toast(e.message, true));
    },

    closeLog() { document.getElementById('log-overlay').classList.remove('open'); },

    openHistory() {
        Tests.loadLogs();
        document.getElementById('history-overlay').classList.add('open');
    },

    closeHistory() { document.getElementById('history-overlay').classList.remove('open'); },
};

document.getElementById('test-script').addEventListener('change', Tests.showDescription);
// Keep the results pinned to the last step when the pane is resized (verdict banner, window)
(() => {
    const wrap = document.querySelector('.results-wrap');
    let atBottom = true;
    wrap.addEventListener('scroll', () => {
        atBottom = wrap.scrollTop + wrap.clientHeight >= wrap.scrollHeight - 4;
    });
    new ResizeObserver(() => { if (atBottom) wrap.scrollTop = wrap.scrollHeight; }).observe(wrap);
})();
// Enter in the serial field starts the test (barcode scanners send Enter after the code)
document.getElementById('test-serial').addEventListener('keydown', e => {
    if (e.key === 'Enter' && Tests.state !== 'RUNNING') { e.preventDefault(); Tests.start(); }
});
App.onEscape(() => {
    const log = document.getElementById('log-overlay');
    if (log.classList.contains('open')) Tests.closeLog();
    else Tests.closeHistory();
});
Tests.loadScripts();
Tests.poll();
