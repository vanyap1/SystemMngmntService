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
        this.loadServices();
        App.api('/api/git/summary?repo=project').then(s => {
            const b = document.querySelector('.st-nav-badge');
            if (s.errors || s.warnings) { b.hidden = false; b.textContent = '!'; b.className = 'git-badge st-nav-badge ' + (s.errors ? 'err' : 'warn'); }
        }).catch(() => {});
    },

    show(tab) {
        if (!document.querySelector(`[data-pane="${tab}"]`)) tab = 'general';
        document.querySelectorAll('.st-pane').forEach(p => { p.hidden = p.dataset.pane !== tab; });
        document.querySelectorAll('#st-nav a').forEach(a => a.classList.toggle('active', a.dataset.tab === tab));
        document.getElementById('st-savebar').hidden = ['git', 'display', 'video'].includes(tab) && !this.changed().length;
        if (tab === 'video' && typeof VideoSources !== 'undefined') VideoSources.load();
        if (typeof NetCfg !== 'undefined') NetCfg.visible(tab === 'network');
        if (tab !== 'video' && typeof VideoDevices !== 'undefined') VideoDevices.stop();
        if (typeof DisplaySettings !== 'undefined') DisplaySettings.visible(tab === 'display');
        if (tab === 'git' && !this._gitMounted) {
            this._gitMounted = true;
            Git.mount(document.getElementById('st-git'), 'project');
        }
        if (location.hash.slice(1) !== tab) history.replaceState(null, '', '#' + tab);
    },

    _val(el) { return el.type === 'checkbox' || el.type === 'radio' ? el.checked : el.value; },

    changed() {
        return [...document.querySelectorAll('[data-cfg]')].filter(el => this._val(el) !== this.initial[el.dataset.cfg]);
    },

    track() {
        const ch = this.changed();
        document.querySelectorAll('.st-changed').forEach(f => f.classList.remove('st-changed'));
        ch.forEach(el => (el.closest('.field, .st-switch, .check-row, .st-home-opt') || el).classList.add('st-changed'));
        const panes = new Set(ch.map(el => el.closest('.st-pane').dataset.pane));
        document.querySelectorAll('#st-nav a').forEach(a => a.classList.toggle('dirty', panes.has(a.dataset.tab)));
        const d = document.getElementById('st-dirty');
        d.textContent = ch.length ? `${ch.length} unsaved change(s)` : 'No unsaved changes';
        d.className = ch.length ? 'text-warn' : 'muted';
        document.getElementById('st-save').disabled = !ch.length;
        document.getElementById('st-revert').disabled = !ch.length;
        document.getElementById('st-savebar').hidden = !ch.length &&
            ['pane-git', 'pane-display', 'pane-video'].some(id => !document.getElementById(id).hidden);
    },

    revert() {
        document.querySelectorAll('[data-cfg]').forEach(el => {
            const v = this.initial[el.dataset.cfg];
            if (el.type === 'checkbox' || el.type === 'radio') el.checked = v; else el.value = v;
        });
        this.track();
    },

    // ── Target service list ────────────────────────────────────

    /** Fill the service <select>: "none" first, then every service of this host (the current value kept). */
    loadServices() {
        const sel = document.getElementById('service_name');
        App.api('/api/services').then(d => {
            const cur = sel.value;
            const names = d.services.map(s => s.name);
            if (cur !== 'none' && !names.includes(cur)) names.unshift(cur);   // configured but not loaded
            const desc = Object.fromEntries(d.services.map(s => [s.name, s]));
            sel.innerHTML = '<option value="none">none</option>' + names.map(n => {
                const s = desc[n];
                const note = s ? ` — ${s.active}${s.desc ? ' · ' + s.desc : ''}` : ' — not found';
                return `<option value="${esc(n)}">${esc(n + note)}</option>`;
            }).join('');
            sel.value = cur;
        }).catch(e => toast(e.message, true));
    },

    // ── Backup patterns ────────────────────────────────────────

    _lines(id) { return document.getElementById(id).value.split('\n').map(l => l.trim()).filter(Boolean); },

    previewPatterns() {
        const box = document.getElementById('st-pat-preview');
        box.innerHTML = '<span class="muted">Checking…</span>';
        App.api('/api/backups/preview', { json: { skip: this._lines('backup_skip'), keep: this._lines('deploy_keep') } })
            .then(r => {
                const list = (items, empty) => items.length
                    ? '<ul class="st-pat-list">' + items.map(i => `<li><span class="mono">${esc(i.path)}</span> <span class="muted">← ${esc(i.pattern)}</span></li>`).join('') + '</ul>'
                    : `<div class="muted">${empty}</div>`;
                const unused = (arr, what) => arr.length
                    ? `<div class="text-warn small">${what} that match nothing: ${arr.map(p => `<code>${esc(p)}</code>`).join(' ')}</div>` : '';
                box.innerHTML =
                    `<div class="small">Archived: <b>${r.files}</b> files, <b>${App.fmtBytes(r.bytes)}</b> (before compression).
                     Skipped: <b>${r.skipped_count}</b> entries.${r.truncated ? ' <span class="text-warn">Stopped early — the folder is very large.</span>' : ''}</div>
                     <div class="st-pat-cols">
                        <div><h4>Skipped when archiving</h4>${list(r.skipped, 'nothing')}${unused(r.unused_skip, 'Skip patterns')}</div>
                        <div><h4>Kept on deploy</h4>${list(r.kept, 'nothing — the whole project is replaced')}${unused(r.unused_keep, 'Keep patterns')}</div>
                     </div>`;
            })
            .catch(e => { box.innerHTML = `<span class="text-error">✗ ${esc(e.message)}</span>`; });
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
            service_name: val('service_name'), tests_dir: val('tests_dir'), test_logs_dir: val('test_logs_dir'),
            help_dir: val('help_dir'), host: val('host'), port: parseInt(val('port'), 10) || 80,
            update_check_minutes: Math.max(0, parseInt(val('update_check_minutes'), 10) || 0),
            show_demo_tests: document.getElementById('show_demo_tests').checked,
            backup_stop_service: document.getElementById('backup_stop_service').checked,
            backup_skip: Settings._lines('backup_skip'), deploy_keep: Settings._lines('deploy_keep'),
            auth: { enabled: document.getElementById('auth_enabled').checked, username: val('auth_username') },
            public_service_actions: [...document.querySelectorAll('.public-action:checked')].map(c => c.value),
            public: {
                home: (document.querySelector('input[name="public_home"]:checked') || {}).value || 'dashboard',
                backups: document.getElementById('public_backups').checked,
                docs: document.getElementById('public_docs').checked,
            },
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
