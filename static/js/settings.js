/* ==========================================================================
   Settings page (templates/settings.html): directory picker and save.
   ========================================================================== */

const Settings = {
    openBrowser(fieldId) {
        const dd = document.getElementById('browser-' + fieldId);
        document.querySelectorAll('.dir-dropdown').forEach(d => { if (d !== dd) d.classList.remove('open'); });
        if (dd.classList.contains('open')) {
            dd.classList.remove('open');
            return;
        }
        Settings.loadDir(fieldId, document.getElementById(fieldId).value || '/');
    },

    loadDir(fieldId, path) {
        App.api('/api/browse?path=' + encodeURIComponent(path))
            .then(d => Settings.renderDir(fieldId, d))
            .catch(e => toast(e.message, true));
    },

    renderDir(fieldId, d) {
        const dd = document.getElementById('browser-' + fieldId);
        const call = (fn, path) => `Settings.${fn}('${fieldId}', ${esc(JSON.stringify(path))})`;
        let h = '<div class="dir-header">';
        if (d.parent !== null)
            h += `<button class="btn btn-ghost btn-sm" onclick="${call('loadDir', d.parent)}">↑ Up</button>`;
        h += `<span class="cur-path">${esc(d.path)}</span></div>`;
        if (!d.dirs.length) h += '<div class="dir-item muted">No subdirectories</div>';
        d.dirs.forEach(name => {
            const full = (d.path === '/' ? '' : d.path) + '/' + name;
            h += `<div class="dir-item" onclick="${call('loadDir', full)}"><i class="fa-solid fa-folder"></i>${esc(name)}</div>`;
        });
        h += `<div class="dir-select" onclick="${call('selectDir', d.path)}">✔ Select: <strong>${esc(d.path)}</strong></div>`;
        dd.innerHTML = h;
        dd.classList.add('open');
    },

    selectDir(fieldId, path) {
        document.getElementById(fieldId).value = path;
        document.getElementById('browser-' + fieldId).classList.remove('open');
    },

    resetHost() {
        if (!confirm('Delete the settings of this host and use the defaults?')) return;
        App.api('/api/settings/reset', { method: 'POST' })
            .then(() => location.reload())
            .catch(e => toast(e.message, true));
    },

    save() {
        const val = id => document.getElementById(id).value.trim();
        const payload = {
            app_title:       val('app_title'),
            page_title:      val('page_title'),
            device_name:     val('device_name'),
            target_dir:      val('target_dir'),
            backup_dir:      val('backup_dir'),
            archive_name:    val('archive_name'),
            upload_tmp_name: val('upload_tmp_name'),
            service_name:    val('service_name'),
            tests_dir:       val('tests_dir'),
            test_logs_dir:   val('test_logs_dir'),
            host:            val('host'),
            port:            parseInt(val('port')) || 80,
            auth: {
                enabled:  document.getElementById('auth_enabled').checked,
                username: val('auth_username'),
            },
            public_service_actions: [...document.querySelectorAll('.public-action:checked')].map(c => c.value),
        };
        const pw = document.getElementById('auth_password').value;
        if (pw) payload.auth.password = pw;

        const status = document.getElementById('save-status');
        status.className = 'muted';
        status.textContent = 'Saving…';
        App.api('/api/settings', { json: payload })
            .then(() => {
                toast('Settings saved for this host');
                setTimeout(() => location.reload(), 700);
            })
            .catch(e => {
                status.className = 'text-error';
                status.textContent = '✗ ' + e.message;
            })
            .finally(() => setTimeout(() => { status.textContent = ''; }, 4000));
    },
};

document.addEventListener('click', e => {
    if (!e.target.closest('.path-wrap'))
        document.querySelectorAll('.dir-dropdown').forEach(d => d.classList.remove('open'));
});

document.addEventListener('keydown', e => {
    if ((e.ctrlKey || e.metaKey) && e.key === 's') { e.preventDefault(); Settings.save(); }
});
