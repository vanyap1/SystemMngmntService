/* ==========================================================================
   Settings page (templates/settings.html): section tabs, change tracking, directory picker,
   save / revert, git credentials and the Git panel (static/js/git.js).
   ========================================================================== */

const Settings = {
    initial: {},
    _gitMounted: false,

    init() {
        document.querySelectorAll('[data-cfg]').forEach(el => { this.initial[el.dataset.cfg] = this._val(el); });
        document.querySelector('.st-main').addEventListener('input', e => { if (e.target.dataset.cfg) this.track(); });
        document.querySelector('.st-main').addEventListener('change', e => { if (e.target.dataset.cfg) this.track(); });
        window.addEventListener('hashchange', () => this.show(location.hash.slice(1)));
        window.addEventListener('beforeunload', e => { if (this.changed().length) { e.preventDefault(); e.returnValue = ''; } });
        this.show(location.hash.slice(1) || 'general');
        this.loadGitCred();
        App.api('/api/git/summary?repo=project').then(s => {
            const b = document.querySelector('.st-nav-badge');
            if (s.errors || s.warnings) { b.hidden = false; b.textContent = '!'; b.className = 'git-badge st-nav-badge ' + (s.errors ? 'err' : 'warn'); }
        }).catch(() => {});
    },

    show(tab) {
        if (!document.querySelector(`[data-pane="${tab}"]`)) tab = 'general';
        document.querySelectorAll('.st-pane').forEach(p => { p.hidden = p.dataset.pane !== tab; });
        document.querySelectorAll('#st-nav a').forEach(a => a.classList.toggle('active', a.dataset.tab === tab));
        document.getElementById('st-savebar').hidden = tab === 'git' && !this.changed().length;
        if (tab === 'git' && !this._gitMounted) {
            this._gitMounted = true;
            Git.mount(document.getElementById('st-git'), 'project');
        }
        if (location.hash.slice(1) !== tab) history.replaceState(null, '', '#' + tab);
    },

    _val(el) { return el.type === 'checkbox' ? el.checked : el.value; },

    changed() {
        return [...document.querySelectorAll('[data-cfg]')].filter(el => this._val(el) !== this.initial[el.dataset.cfg]);
    },

    track() {
        const ch = this.changed();
        document.querySelectorAll('.st-changed').forEach(f => f.classList.remove('st-changed'));
        ch.forEach(el => (el.closest('.field, .st-switch, .check-row') || el).classList.add('st-changed'));
        const panes = new Set(ch.map(el => el.closest('.st-pane').dataset.pane));
        document.querySelectorAll('#st-nav a').forEach(a => a.classList.toggle('dirty', panes.has(a.dataset.tab)));
        const d = document.getElementById('st-dirty');
        d.textContent = ch.length ? `${ch.length} unsaved change(s)` : 'No unsaved changes';
        d.className = ch.length ? 'text-warn' : 'muted';
        document.getElementById('st-save').disabled = !ch.length;
        document.getElementById('st-revert').disabled = !ch.length;
        document.getElementById('st-savebar').hidden = !ch.length && !document.getElementById('pane-git').hidden;
    },

    revert() {
        document.querySelectorAll('[data-cfg]').forEach(el => {
            const v = this.initial[el.dataset.cfg];
            if (el.type === 'checkbox') el.checked = v; else el.value = v;
        });
        this.track();
    },

    // ── Directory picker ───────────────────────────────────────

    openBrowser(fieldId) {
        const dd = document.getElementById('browser-' + fieldId);
        document.querySelectorAll('.dir-dropdown').forEach(d => { if (d !== dd) d.classList.remove('open'); });
        if (dd.classList.contains('open')) return dd.classList.remove('open');
        this.loadDir(fieldId, document.getElementById(fieldId).value || '/');
    },

    loadDir(fieldId, path) {
        App.api('/api/browse?path=' + encodeURIComponent(path))
            .then(d => this.renderDir(fieldId, d))
            .catch(e => toast(e.message, true));
    },

    renderDir(fieldId, d) {
        const dd = document.getElementById('browser-' + fieldId);
        const call = (fn, path) => `Settings.${fn}('${fieldId}', ${esc(JSON.stringify(path))})`;
        let h = '<div class="dir-header">';
        if (d.parent !== null) h += `<button class="btn btn-ghost btn-sm" type="button" onclick="${call('loadDir', d.parent)}">↑ Up</button>`;
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
        this.track();
    },

    // ── Save ───────────────────────────────────────────────────

    resetHost() {
        if (!confirm('Delete the settings of this host and use the defaults?')) return;
        App.api('/api/settings/reset', { method: 'POST' })
            .then(() => { this.initial = {}; location.reload(); })
            .catch(e => toast(e.message, true));
    },

    save() {
        const val = id => document.getElementById(id).value.trim();
        const payload = {
            app_title: val('app_title'), page_title: val('page_title'), device_name: val('device_name'),
            target_dir: val('target_dir'), backup_dir: val('backup_dir'),
            archive_name: val('archive_name'), upload_tmp_name: val('upload_tmp_name'),
            service_name: val('service_name'), tests_dir: val('tests_dir'), test_logs_dir: val('test_logs_dir'),
            help_dir: val('help_dir'), host: val('host'), port: parseInt(val('port'), 10) || 80,
            auth: { enabled: document.getElementById('auth_enabled').checked, username: val('auth_username') },
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
                this.initial = {};
                document.querySelectorAll('[data-cfg]').forEach(el => { this.initial[el.dataset.cfg] = this._val(el); });
                document.getElementById('auth_password').value = '';
                this.initial['auth.password'] = '';
                this.track();
                status.textContent = '';
                setTimeout(() => location.reload(), 600);
            })
            .catch(e => {
                status.className = 'text-error';
                status.textContent = '✗ ' + e.message;
            });
    },

    // ── Git credentials (write-only token) ─────────────────────

    loadGitCred() {
        return App.api('/api/git/credentials').then(c => this._showCred(c)).catch(e => toast(e.message, true));
    },

    _showCred(c) {
        document.getElementById('git_user').value = c.username;
        document.getElementById('git_token').value = '';
        document.getElementById('git_token').placeholder = c.token_set ? `stored (${c.token_hint}) — type to replace` : 'not set';
        document.getElementById('git_token_hint').innerHTML = c.token_set
            ? '<span class="text-ok"><i class="fa-solid fa-check"></i> Token stored</span>' : 'Needed only for https:// remotes';
        document.getElementById('git_token_clear').disabled = !c.token_set;
        document.getElementById('git_cred_path').textContent = c.path;
    },

    toggleToken() {
        const t = document.getElementById('git_token');
        t.type = t.type === 'password' ? 'text' : 'password';
    },

    saveGitCred() {
        const token = document.getElementById('git_token').value.trim();
        App.api('/api/git/credentials', { json: { username: document.getElementById('git_user').value, token: token || null } })
            .then(c => { this._showCred(c); toast('Git credentials saved'); if (this._gitMounted) Git.load(); })
            .catch(e => toast(e.message, true));
    },

    clearGitToken() {
        if (!confirm('Remove the stored git token from this host?')) return;
        App.api('/api/git/credentials', { json: { clear_token: true } })
            .then(c => { this._showCred(c); toast('Token removed'); if (this._gitMounted) Git.load(); })
            .catch(e => toast(e.message, true));
    },
};

document.addEventListener('click', e => {
    if (!e.target.closest('.path-wrap')) document.querySelectorAll('.dir-dropdown').forEach(d => d.classList.remove('open'));
});
document.addEventListener('keydown', e => {
    if ((e.ctrlKey || e.metaKey) && e.key === 's' && !e.target.closest('.git-commit')) { e.preventDefault(); if (Settings.changed().length) Settings.save(); }
});

Settings.init();
