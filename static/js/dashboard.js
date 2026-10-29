/* ==========================================================================
   Main page (templates/index.html). Service status is public; archives and
   system info exist only for logged-in users (their DOM is absent otherwise).
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

    // ── Archives ──
    setArcStatus(msg, isErr) {
        const el = document.getElementById('arc-status');
        el.textContent = msg;
        el.className = 'meta ' + (isErr ? 'text-error' : 'text-ok');
        if (msg) setTimeout(() => { el.textContent = ''; }, 4000);
    },

    loadArchives() {
        App.api('/api/backups').then(files => {
            const card = document.getElementById('arc-card');
            if (!files.length) {
                card.innerHTML = '<div class="tbl-empty">No archives found</div>';
                return;
            }
            card.innerHTML = '<table class="tbl arc-tbl"><thead><tr>' +
                '<th>Name</th><th class="num">Size</th><th>Date</th><th></th></tr></thead><tbody>' +
                files.map(f => {
                    const n = esc(JSON.stringify(f.name));
                    return `<tr>
                        <td class="arc-name">${esc(f.name)}</td>
                        <td class="arc-size">${App.fmtBytes(f.size)}</td>
                        <td class="arc-date">${App.fmtDate(f.mtime)}</td>
                        <td class="arc-actions">
                            <button class="btn btn-sm btn-success" onclick="Dashboard.deploy(${n})"><i class="fa-solid fa-play"></i> Deploy</button>
                            <a class="btn btn-sm btn-info" href="/backups/download/${encodeURIComponent(f.name)}"><i class="fa-solid fa-download"></i> Download</a>
                            <button class="btn btn-sm btn-danger" onclick="Dashboard.deleteArchive(${n}, this)" title="Delete"><i class="fa-solid fa-xmark"></i></button>
                        </td></tr>`;
                }).join('') + '</tbody></table>';
        }).catch(e => Dashboard.setArcStatus('✗ ' + e.message, true));
    },

    deploy(name) {
        if (!confirm(`Deploy "${name}"?\n\nThe current project will be auto-backed up first, ` +
                     `then the service will be stopped and this archive extracted.`)) return;
        Dashboard.setArcStatus('Deploying…');
        App.api('/api/backups/deploy', { json: { filename: name } })
            .then(d => {
                Dashboard.setArcStatus(`✓ Deployed. Auto-backup: ${d.auto_backup}`);
                Dashboard.loadArchives();
                Dashboard.refreshStatus();
            })
            .catch(e => Dashboard.setArcStatus('✗ ' + e.message, true));
    },

    deleteArchive(name, btn) {
        if (!confirm(`Delete "${name}"?`)) return;
        btn.disabled = true;
        App.api('/api/backups/delete', { json: { filename: name } })
            .then(() => { Dashboard.setArcStatus('✓ Deleted'); Dashboard.loadArchives(); })
            .catch(e => { Dashboard.setArcStatus('✗ ' + e.message, true); btn.disabled = false; });
    },

    // ── System info ──
    renderSysinfo(d) {
        const m = d.mem || {};
        let h = '<div class="si-grid">';

        h += '<div class="si-block">';
        h += `<div class="si-head">CPU &mdash; ${esc(d.cpu_count || '?')} cores</div>`;
        h += `<div class="si-kv"><span class="k">Load avg</span><span class="v">${SysInfo.loadText(d)}</span></div>`;
        h += SysInfo.bar(SysInfo.loadPct(d));
        h += '<div class="si-head">Memory</div>';
        h += `<div class="si-kv"><span class="k">RAM</span><span class="v">${App.fmtKb(m.used_kb)} / ${App.fmtKb(m.total_kb)} (${m.pct}%)</span></div>`;
        h += SysInfo.bar(m.pct || 0);
        if (m.swap_total_kb > 0) {
            h += `<div class="si-kv"><span class="k">Swap</span><span class="v">${App.fmtKb(m.swap_used_kb)} / ${App.fmtKb(m.swap_total_kb)} (${m.swap_pct}%)</span></div>`;
            h += SysInfo.bar(m.swap_pct || 0);
        }
        h += `<div class="si-kv"><span class="k">Processes</span><span class="v text-ok">${esc(d.procs)}</span></div>`;
        h += '</div>';

        h += '<div class="si-block"><div class="si-head">Network</div>';
        (d.net || []).forEach(n => {
            const st = n.state === 'UP' ? '<span class="si-up">● UP</span>' : '<span class="si-down">○ DOWN</span>';
            h += `<div class="si-iface"><strong>${esc(n.iface)}</strong> ${st}<br>` +
                 `<small>${(n.addrs || []).map(esc).join('<br>') || '—'}</small></div>`;
        });
        if (!(d.net || []).length) h += '<small class="muted">No interfaces</small>';
        h += '</div>';

        h += `<div class="si-block"><div class="si-head">Storage</div>${SysInfo.lsblkTable(d.lsblk)}</div>`;
        h += '</div>';

        document.getElementById('si-card').innerHTML = h;
        document.getElementById('si-ts').textContent = App.fmtTime();
    },
};

Services.onChange(Dashboard.refreshStatus);
Dashboard.showStatus(document.getElementById('status-pre').textContent);
setInterval(Dashboard.refreshStatus, 10000);

if (App.config.loggedIn) {
    Dashboard.loadArchives();
    SysInfo.poll(Dashboard.renderSysinfo);
}
