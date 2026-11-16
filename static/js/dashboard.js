/* ==========================================================================
   Main page (templates/index.html). Service status and the system monitor are
   public; archives exist only for logged-in users (their DOM is absent otherwise).
   ========================================================================== */

const Dashboard = {
    showStatus(text) {
        document.getElementById('status-pre').innerHTML = Services.colorize(text);
        document.getElementById('svc-dot').className = 'svc-dot ' + Services.stateOf(text);
    },

    refreshStatus() {
        Services.fetchStatus()
            .then(Dashboard.showStatus)
            .catch(() => { document.getElementById('status-pre').textContent = 'Status unavailable'; });
    },

    // ── Archives + backup job (core/backups.py) ──
    info: {},
    job: null,
    _timer: null,
    _hidden: false,

    setArcStatus(msg, isErr) {
        const el = document.getElementById('arc-status');
        el.textContent = msg;
        el.className = 'meta ' + (isErr ? 'text-error' : 'text-ok');
        if (msg) setTimeout(() => { el.textContent = ''; }, 4000);
    },

    loadArchives() {
        return App.api('/api/backups').then(d => {
            Dashboard.info = d;
            Dashboard.renderArchives(d.archives);
            Dashboard.showJob(d.job);
        }).catch(e => Dashboard.setArcStatus('✗ ' + e.message, true));
    },

    renderArchives(files) {
        const card = document.getElementById('arc-card');
        if (!files.length) {
            card.innerHTML = '<div class="tbl-empty">No archives found</div>';
            return;
        }
        const busy = Dashboard.running();
        card.innerHTML = '<table class="tbl arc-tbl"><thead><tr>' +
            '<th>Name</th><th class="num">Size</th><th>Date</th><th></th></tr></thead><tbody>' +
            files.map(f => {
                const n = esc(JSON.stringify(f.name));
                const dis = f.busy ? ' disabled title="In use by the running job"' : '';
                return `<tr${f.busy ? ' class="arc-busy"' : ''}>
                    <td class="arc-name">${esc(f.name)}${f.busy ? ' <span class="badge badge-info">in use</span>' : ''}</td>
                    <td class="arc-size">${App.fmtBytes(f.size)}</td>
                    <td class="arc-date">${App.fmtDate(f.mtime)}</td>
                    <td class="arc-actions">
                        ${App.config.loggedIn ? `<button class="btn btn-sm btn-success" onclick="Dashboard.openDeploy(${n})"${busy ? ' disabled title="A backup job is running"' : ''}><i class="fa-solid fa-play"></i> Deploy</button>` : ''}
                        ${f.busy ? `<button class="btn btn-sm btn-info" disabled><i class="fa-solid fa-download"></i> Download</button>`
                                 : `<a class="btn btn-sm btn-info" href="/backups/download/${encodeURIComponent(f.name)}"><i class="fa-solid fa-download"></i> Download</a>`}
                        ${App.config.loggedIn ? `<button class="btn btn-sm btn-danger" onclick="Dashboard.deleteArchive(${n}, this)" title="Delete"${dis}><i class="fa-solid fa-xmark"></i></button>` : ''}
                    </td></tr>`;
            }).join('') + '</tbody></table>';
    },

    running() { return !!(Dashboard.job && Dashboard.job.state === 'running'); },

    /** Render the job box; poll while it runs, reload the list when it ends. */
    showJob(job) {
        const wasRunning = Dashboard.running();
        Dashboard.job = job;
        const box = document.getElementById('bk-job');
        if (!box) return;                                     // anonymous: archive list only
        document.getElementById('bk-create').disabled = Dashboard.running();
        if (!job) { box.hidden = true; return; }
        if (job.state === 'running') Dashboard._hidden = false;
        box.hidden = Dashboard._hidden;
        const pct = job.total ? Math.min(100, Math.round(job.done * 100 / job.total)) : null;
        const bar = document.getElementById('bk-bar');
        const ended = job.state !== 'running';
        bar.style.width = (ended ? 100 : (pct ?? 0)) + '%';
        bar.classList.toggle('err', job.state === 'error');
        let phase = job.phase;
        if (!ended && pct !== null) phase += ` — ${pct}% (${App.fmtBytes(job.done)} / ${App.fmtBytes(job.total)})`;
        if (job.state === 'error') phase = 'Failed: ' + job.error;
        if (job.state === 'done') phase = 'Done' + (job.result.archive ? ': ' + job.result.archive : '')
            + (job.result.auto_backup ? ' · backup ' + job.result.auto_backup : '');
        document.getElementById('bk-phase').textContent = phase;
        document.getElementById('bk-job-title').textContent = job.title;
        document.getElementById('bk-job-ico').className = {
            running: 'fa-solid fa-spinner fa-spin', done: 'fa-solid fa-circle-check text-ok',
            error: 'fa-solid fa-circle-xmark text-error', cancelled: 'fa-solid fa-ban text-warn'}[job.state];
        document.getElementById('bk-cancel').hidden = !job.cancellable;
        document.getElementById('bk-close').hidden = !ended;
        const log = document.getElementById('bk-log');
        const atEnd = log.scrollTop + log.clientHeight >= log.scrollHeight - 4;
        log.textContent = job.log.join('\n');
        if (atEnd) log.scrollTop = log.scrollHeight;

        clearTimeout(Dashboard._timer);
        if (!ended) Dashboard._timer = setTimeout(Dashboard.pollJob, 700);
        if (wasRunning && ended) {
            Dashboard.loadArchives();
            Dashboard.refreshStatus();
            toast(job.state === 'done' ? job.title + ' — done' : job.title + ' — ' + job.state, job.state === 'error');
        } else if (!wasRunning && !ended) {
            Dashboard.renderArchives(Dashboard.info.archives || []);
        }
    },

    pollJob() {
        App.api('/api/backups/job').then(d => Dashboard.showJob(d.job))
            .catch(() => { Dashboard._timer = setTimeout(Dashboard.pollJob, 2000); });
    },

    hideJob() { Dashboard._hidden = true; document.getElementById('bk-job').hidden = true; },

    createArchive() {
        App.api('/api/backups/create', { json: {} })
            .then(d => Dashboard.loadArchives())
            .catch(e => toast(e.message, true));
    },

    cancelJob() {
        App.api('/api/backups/cancel', { json: {} }).then(d => Dashboard.showJob(d.job)).catch(e => toast(e.message, true));
    },

    openDeploy(name) {
        const i = Dashboard.info;
        Dashboard._deployName = name;
        document.getElementById('dep-name').textContent = name;
        document.getElementById('dep-target').textContent = i.target || '';
        document.getElementById('dep-keep').textContent = (i.keep || []).length ? i.keep.join('   ') : 'none';
        document.getElementById('dep-service').textContent = /\.service$/.test(i.service || '')
            ? `${i.service} — stopped while the folder is replaced, started again if it was running`
            : 'none — nothing is stopped';
        const block = document.getElementById('dep-block');
        block.hidden = !i.deploy_block;
        block.textContent = i.deploy_block ? '✗ ' + i.deploy_block : '';
        document.getElementById('dep-go').disabled = !!i.deploy_block;
        document.getElementById('dep-overlay').classList.add('open');
    },

    closeDeploy() { document.getElementById('dep-overlay').classList.remove('open'); },

    runDeploy() {
        const backup = document.getElementById('dep-backup').checked;
        Dashboard.closeDeploy();
        Dashboard._hidden = false;
        App.api('/api/backups/deploy', { json: { filename: Dashboard._deployName, backup } })
            .then(() => Dashboard.loadArchives())
            .catch(e => toast(e.message, true));
    },

    deleteArchive(name, btn) {
        if (!confirm(`Delete "${name}"?`)) return;
        btn.disabled = true;
        App.api('/api/backups/delete', { json: { filename: name } })
            .then(() => { Dashboard.setArcStatus('✓ Deleted'); Dashboard.loadArchives(); })
            .catch(e => { Dashboard.setArcStatus('✗ ' + e.message, true); btn.disabled = false; });
    },
};

Services.onChange(Dashboard.refreshStatus);
Dashboard.showStatus(document.getElementById('status-pre').textContent);
setInterval(Dashboard.refreshStatus, 10000);

Monitor.create(document.getElementById('mon-card'));
MonitorData.subscribe(() => { document.getElementById('mon-ts').textContent = App.fmtTime(); });

if (document.getElementById('arc-card')) Dashboard.loadArchives();
if (App.config.loggedIn) App.onEscape(() => Dashboard.closeDeploy());
