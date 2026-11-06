/* ==========================================================================
   Git panel (routes/git.py): status, problems + fixes, commit (current or new branch), branches,
   fetch / pull / push, discard, reset to remote. Mounted inline on Settings → Git and in the Git popup
   (templates/partials/git_modal.html) of the code editor and the docs.
   ========================================================================== */

const Git = {
    el: null,
    repo: 'project',
    data: null,
    repos: [],
    diffPath: null,
    busy: false,
    sel: null,              // Set of selected paths (null = all)
    _msg: '',

    STATUS: { modified: ['M', 'mod'], added: ['A', 'add'], deleted: ['D', 'del'], renamed: ['R', 'ren'], copied: ['C', 'add'],
              untracked: ['U', 'new'], conflict: ['!', 'cfl'] },

    // ── Mount / popup ──────────────────────────────────────────

    /** opts.select: paths (relative to the repository) to preselect for the commit. */
    mount(el, repo, opts = {}) {
        this.el = el;
        if (repo) this.repo = repo;
        this.sel = null;
        this._preselect = opts.select || null;
        this.diffPath = opts.select && opts.select.length === 1 ? opts.select[0] : null;
        el.innerHTML = '<div class="tbl-empty">Loading…</div>';
        return App.api('/api/git/repos').then(d => {
            this.repos = d.repos;
            const r = this.repos.find(x => x.aliases.includes(this.repo));
            if (r) this.repo = r.id;
            if (r && !r.top) { this.data = null; return this.renderNoRepo(r); }
            return this.load();
        }).catch(e => { el.innerHTML = `<div class="tbl-empty text-error">${esc(e.message)}</div>`; });
    },

    openModal(repo, opts) {
        document.getElementById('git-overlay').classList.add('open');
        this.mount(document.getElementById('git-modal-body'), repo, opts);
    },

    closeModal() {
        document.getElementById('git-overlay').classList.remove('open');
        this.el = null;
        this.badges();
    },

    load() {
        return App.api('/api/git/status?repo=' + encodeURIComponent(this.repo))
            .then(d => {
                this.data = d;
                if (this._preselect) {
                    const have = new Set(d.status.files.map(f => f.path));
                    this.sel = new Set(this._preselect.filter(p => have.has(p)));
                    if (this.diffPath && !have.has(this.diffPath)) this.diffPath = null;
                    this._preselect = null;
                }
                this.render();
            })
            .catch(e => { if (this.el) this.el.innerHTML = this._repoBar() + `<div class="git-alert err"><b>${esc(e.message)}</b></div>`; });
    },

    /** Update the small badges on the toolbar Git icons ([data-git-badge="<repo>"]). */
    badges() {
        document.querySelectorAll('[data-git-badge]').forEach(btn => {
            App.api('/api/git/summary?repo=' + encodeURIComponent(btn.dataset.gitBadge)).then(s => {
                const b = btn.querySelector('.git-badge');
                if (s.error) { btn.title = 'Git: ' + s.error; b.hidden = true; return; }
                const n = s.changes;
                b.hidden = !(n || s.errors || s.ahead || s.behind);
                b.textContent = s.errors ? '!' : (n || (s.ahead ? '↑' + s.ahead : '↓' + s.behind));
                b.className = 'git-badge' + (s.errors ? ' err' : s.warnings ? ' warn' : '');
                btn.title = `Git · ${s.branch || 'detached'} · ${n} change(s)` + (s.ahead ? ` · ${s.ahead} to push` : '') +
                            (s.behind ? ` · ${s.behind} to pull` : '') + (s.errors ? ` · ${s.errors} problem(s)` : '');
            }).catch(() => {});
        });
    },

    // ── Render ─────────────────────────────────────────────────

    _repoBar() {
        if (this.repos.length < 2) return '';
        return `<select class="select-mono git-repo" onchange="Git.switchRepo(this.value)">` +
            this.repos.map(r => `<option value="${esc(r.id)}"${r.id === this.repo ? ' selected' : ''}>${esc(r.label)}</option>`).join('') + '</select>';
    },

    switchRepo(id) {
        this.repo = id; this.sel = null; this.diffPath = null;
        const r = this.repos.find(x => x.id === id);
        if (r && !r.top) return this.renderNoRepo(r);
        this.load();
    },

    /** The folder is not in a git repository: clone a project into target_dir or initialize one. */
    renderNoRepo(r) {
        if (!this.el) return;
        const project = r.aliases.includes('project');
        this.el.innerHTML = `<div class="git-head">${this._repoBar()}<span class="git-top mono faint">${esc(r.path)}</span></div>` +
            `<div class="git-problems"><div class="git-alert warn"><i class="fa-solid fa-triangle-exclamation"></i><div class="git-alert-text">` +
            `<b>${esc(r.path)} is not a git repository</b><span>Clone a project (e.g. from GitHub) into a sub-folder or start a new repository here.</span></div></div></div>` +
            (project ? `<div class="git-norepo">` +
            `<div class="git-sec-head">Clone into ${esc(r.path)}/…</div>` +
            `<div class="git-clone"><input id="git-clone-url" class="input input-sm mono" placeholder="clone URL — https or git@github.com:owner/repo.git">` +
            `<input id="git-clone-name" class="input input-sm mono" placeholder="folder (default: repo name)">` +
            `<button class="btn btn-success btn-sm" onclick="Git.clone()"><i class="fa-solid fa-clone"></i> Clone</button></div>` +
            `<div class="hint">Private https repositories use the token from Settings → Git. ssh URLs use the keys of the folder owner.</div>` +
            `<div class="git-sec-head">Or</div><div><button class="btn btn-ghost btn-sm" onclick="Git.init()"><i class="fa-solid fa-seedling"></i> git init in ${esc(r.path)}</button></div></div>` : '') +
            `<pre class="git-out" id="git-out" ${this._out ? '' : 'hidden'}>${esc(this._out || '')}</pre>`;
    },

    _afterCreate(r) {
        this._out = r.message;
        toast(r.message);
        document.dispatchEvent(new CustomEvent('git-changed'));
        return App.api('/api/git/repos').then(d => { this.repos = d.repos; this.repo = r.repo; return this.load(); });
    },

    clone() {
        const url = document.getElementById('git-clone-url').value.trim();
        if (!url) return toast('Enter the repository URL', true);
        this.el.classList.add('git-busy');
        App.api('/api/git/clone', { json: { url, name: document.getElementById('git-clone-name').value.trim() } })
            .then(r => this._afterCreate(r))
            .catch(e => { this._out = e.message; toast(e.message, true); const r = this.repos.find(x => x.id === this.repo); if (r) this.renderNoRepo(r); })
            .finally(() => this.el && this.el.classList.remove('git-busy'));
    },

    init() {
        if (!confirm('Create a new git repository here?')) return;
        App.api('/api/git/init', { json: {} }).then(r => this._afterCreate(r)).catch(e => toast(e.message, true));
    },

    render() {
        if (!this.el || !this.data) return;
        const d = this.data, st = d.status;
        const files = st.files;
        if (this.sel) this.sel = new Set([...this.sel].filter(p => files.some(f => f.path === p)));
        const selected = this.sel ? files.filter(f => this.sel.has(f.path)) : files;
        const branchOpts = d.branches.map(b => `<option value="${esc(b.name)}"${b.current ? ' selected' : ''}>${esc(b.name)}</option>`).join('');
        const sync = st.upstream
            ? `<span class="git-sync" title="Upstream ${esc(st.upstream)}"><i class="fa-solid fa-arrow-up"></i> ${st.ahead} <i class="fa-solid fa-arrow-down"></i> ${st.behind} <span class="faint mono">${esc(st.upstream)}</span></span>`
            : `<span class="git-sync faint">no upstream</span>`;

        let h = `<div class="git-head">${this._repoBar()}` +
            `<span class="git-top mono faint" title="${esc(d.repo.top)}">${esc(d.repo.top)}</span>` + this._remoteLink(d.repo.remote) +
            `<span class="git-branch"><i class="fa-solid fa-code-branch"></i>` +
            (st.branch ? `<select class="select-mono" onchange="Git.checkout(this.value)" title="Switch branch">${branchOpts}</select>`
                       : '<b class="text-warn">detached HEAD</b>') + `</span>${sync}<span class="spacer"></span>` +
            `<button class="btn btn-ghost btn-sm" onclick="Git.act('fetch')" title="git fetch --prune"><i class="fa-solid fa-cloud-arrow-down"></i> Fetch</button>` +
            `<button class="btn btn-info btn-sm" onclick="Git.act('pull', {mode: 'ff'})" title="git pull --ff-only"><i class="fa-solid fa-download"></i> Pull${st.behind ? ' ' + st.behind : ''}</button>` +
            `<button class="btn btn-primary btn-sm" onclick="Git.act('push')" title="git push (sets the upstream on the first push)"><i class="fa-solid fa-upload"></i> Push${st.ahead ? ' ' + st.ahead : ''}</button>` +
            `<button class="btn-icon" onclick="Git.load()" title="Refresh"><i class="fa-solid fa-arrows-rotate"></i></button></div>`;

        if (d.problems.length) {
            h += '<div class="git-problems">' + d.problems.map(p =>
                `<div class="git-alert ${p.level === 'error' ? 'err' : p.level === 'warn' ? 'warn' : 'info'}">` +
                `<i class="fa-solid ${p.level === 'error' ? 'fa-circle-exclamation' : p.level === 'warn' ? 'fa-triangle-exclamation' : 'fa-circle-info'}"></i>` +
                `<div class="git-alert-text"><b>${esc(p.title)}</b>${p.detail ? `<span>${esc(p.detail)}</span>` : ''}</div>` +
                p.fixes.map(f => `<button class="btn btn-sm ${f.danger ? 'btn-danger' : 'btn-warning'}" onclick="Git.fix(${esc(JSON.stringify(f.id))}, ${esc(JSON.stringify(f.danger ? f.label : ''))})">${esc(f.label)}</button>`).join('') +
                (p.id === 'identity' ? `<button class="btn btn-sm btn-warning" onclick="document.getElementById('git-id-name').focus()">Set below</button>` : '') +
                '</div>').join('') + '</div>';
        } else {
            h += '<div class="git-ok"><i class="fa-solid fa-circle-check"></i> No problems found</div>';
        }

        // changes + commit
        h += '<div class="git-grid"><div class="git-col">';
        h += `<div class="git-sec-head"><label class="check-row small"><input type="checkbox" ${!this.sel || this.sel.size === files.length ? 'checked' : ''} ${files.length ? '' : 'disabled'} onchange="Git.selectAll(this.checked)"> Changes</label>` +
             `<span class="badge badge-muted">${files.length}</span><span class="spacer"></span>` +
             (files.length ? `<button class="btn-icon git-danger" onclick="Git.discard(null)" title="Discard the selected changes"><i class="fa-solid fa-rotate-left"></i></button>` : '') + '</div>';
        h += '<div class="git-files">' + (files.map(f => {
            const [letter, cls] = this.STATUS[f.kind] || ['?', 'mod'];
            const on = !this.sel || this.sel.has(f.path);
            const p = esc(JSON.stringify(f.path));
            return `<div class="git-file${this.diffPath === f.path ? ' active' : ''}">` +
                `<input type="checkbox" ${on ? 'checked' : ''} onchange="Git.toggle(${p}, this.checked)">` +
                `<span class="git-st ${cls}" title="${esc(f.kind)}${f.staged ? ', staged' : ''}">${letter}</span>` +
                `<span class="git-path" onclick="Git.diff(${p})" title="Show diff">${esc(f.path)}${f.orig ? ` <span class="faint">← ${esc(f.orig)}</span>` : ''}</span>` +
                `<button class="btn-icon git-danger" onclick="Git.discard([${p}])" title="Discard changes of this file"><i class="fa-solid fa-rotate-left"></i></button></div>`;
        }).join('') || '<div class="tbl-empty">Working tree clean.</div>') + '</div>';
        if (this.diffPath) h += `<div class="git-diff-head mono small"><span>${esc(this.diffPath)}</span><button class="btn-icon" onclick="Git.diff(null)"><i class="fa-solid fa-xmark"></i></button></div><pre class="git-diff" id="git-diff">Loading…</pre>`;

        const nb = document.getElementById('git-new-branch-on');
        const newBranchOn = nb ? nb.checked : false;
        h += `<div class="git-commit">` +
            `<textarea id="git-msg" class="input mono" rows="3" placeholder="Commit message (first line = summary)">${esc(this._msg)}</textarea>` +
            `<div class="git-commit-opts">` +
            `<label class="check-row small"><input type="radio" name="git-target" id="git-cur-branch" ${newBranchOn ? '' : 'checked'} onchange="Git._target()"> to <b class="mono">${esc(st.branch || 'detached HEAD')}</b></label>` +
            `<label class="check-row small"><input type="radio" name="git-target" id="git-new-branch-on" ${newBranchOn ? 'checked' : ''} onchange="Git._target()"> to a new branch</label>` +
            `<input id="git-new-branch" class="input input-sm mono" placeholder="feature/name" ${newBranchOn ? '' : 'disabled'}>` +
            `</div><div class="git-commit-opts">` +
            `<label class="check-row small"><input type="checkbox" id="git-push-after"> push after commit</label><span class="spacer"></span>` +
            `<button class="btn btn-success btn-sm" onclick="Git.commit()" ${selected.length ? '' : 'disabled'}><i class="fa-solid fa-check"></i> Commit ${selected.length} file(s)</button></div></div>`;
        h += '</div>';

        // branches, history, identity
        h += '<div class="git-col">';
        h += `<div class="git-sec-head">Branches <span class="badge badge-muted">${d.branches.length}</span></div><div class="git-branches">` +
            d.branches.map(b => {
                const n = esc(JSON.stringify(b.name));
                return `<div class="git-br${b.current ? ' cur' : ''}"><i class="fa-solid ${b.current ? 'fa-circle-dot text-ok' : 'fa-code-branch faint'}"></i>` +
                    `<span class="mono">${esc(b.name)}</span><span class="faint small">${esc(b.track || (b.upstream ? '' : 'local'))}</span><span class="spacer"></span>` +
                    `<span class="faint small">${esc(b.date)}</span>` +
                    (b.current ? '' : `<button class="btn-icon" onclick="Git.checkout(${n})" title="Switch to it"><i class="fa-solid fa-right-to-bracket"></i></button>` +
                                      `<button class="btn-icon git-danger" onclick="Git.deleteBranch(${n})" title="Delete"><i class="fa-regular fa-trash-can"></i></button>`) + '</div>';
            }).join('') + '</div>' +
            `<div class="row git-newbr"><input id="git-br-name" class="input input-sm mono" placeholder="new-branch-name" onkeydown="if(event.key==='Enter')Git.createBranch()">` +
            `<button class="btn btn-ghost btn-sm" onclick="Git.createBranch()"><i class="fa-solid fa-code-branch"></i> Create &amp; switch</button></div>`;
        h += `<div class="git-sec-head">Recent commits</div><div class="git-log">` + (d.log.map(c =>
            `<div class="git-commit-row" title="${esc(c.hash)}\n${esc(c.author)}"><span class="mono git-hash">${esc(c.short)}</span>` +
            `<span class="git-subj">${esc(c.subject)}${c.refs ? ` <span class="git-refs">${esc(c.refs)}</span>` : ''}</span><span class="faint small">${esc(c.when)}</span></div>`).join('') ||
            '<div class="tbl-empty">No commits yet.</div>') + '</div>';
        const id = d.identity;
        h += `<div class="git-sec-head">Identity <span class="faint small">${esc(id.name || '—')} &lt;${esc(id.email || '—')}&gt;</span></div>` +
            `<div class="git-identity"><input id="git-id-name" class="input input-sm" placeholder="Name" value="${esc(id.local_name || id.name)}">` +
            `<input id="git-id-email" class="input input-sm" placeholder="e-mail" value="${esc(id.local_email || id.email)}">` +
            `<select id="git-id-scope" class="input input-sm" title="local = this repository, global = the repository owner's ~/.gitconfig"><option value="local">this repo</option><option value="global">global</option></select>` +
            `<button class="btn btn-ghost btn-sm" onclick="Git.saveIdentity()">Save</button></div>`;
        const cr = d.credentials;
        h += `<div class="git-cred faint small"><i class="fa-solid fa-key"></i> HTTPS token: ${cr.token_set ? `<span class="text-ok">set (${esc(cr.token_hint)})</span>` : 'not set'}` +
             (cr.username ? ` · user <span class="mono">${esc(cr.username)}</span>` : '') +
             (document.getElementById('st-git-cred') ? '' : ` · <a href="/settings#git">Settings → Git</a>`) + '</div>';
        h += `<div class="git-danger-zone"><button class="btn btn-ghost btn-sm" onclick="Git.discard('all')" ${files.length ? '' : 'disabled'}><i class="fa-solid fa-broom"></i> Discard all changes</button>` +
             `<button class="btn btn-danger btn-sm" onclick="Git.resetHard()" ${st.upstream ? '' : 'disabled'} title="Backup branch + stash first, then git reset --hard upstream"><i class="fa-solid fa-triangle-exclamation"></i> Reset to remote</button></div>`;
        h += '</div></div>';
        h += `<pre class="git-out" id="git-out" ${this._out ? '' : 'hidden'}>${esc(this._out || '')}</pre>`;
        this.el.innerHTML = h;
        if (this.busy) this.el.classList.add('git-busy');
        const msg = document.getElementById('git-msg');
        msg.addEventListener('input', () => { this._msg = msg.value; });
        msg.addEventListener('keydown', e => { if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') this.commit(); });
        if (this.diffPath) this._loadDiff();
    },

    _target() {
        const on = document.getElementById('git-new-branch-on').checked;
        const inp = document.getElementById('git-new-branch');
        inp.disabled = !on;
        if (on) inp.focus();
    },

    _remoteLink(rm) {
        if (!rm) return '<span class="git-remote faint" title="No remote — Push needs one">local only</span>';
        const icon = /github/i.test(rm.host) ? 'fa-brands fa-github' : /gitlab/i.test(rm.host) ? 'fa-brands fa-gitlab' : 'fa-solid fa-cloud';
        const label = `<i class="${icon}"></i> ${esc(rm.host ? rm.host + '/' : '')}${esc(rm.slug)}`;
        return rm.web ? `<a class="git-remote" href="${esc(rm.web)}" target="_blank" rel="noopener noreferrer" title="Open on ${esc(rm.host)}">${label}</a>`
                      : `<span class="git-remote">${label}</span>`;
    },

    toggle(path, on) {
        const all = this.data.status.files.map(f => f.path);
        if (!this.sel) this.sel = new Set(all);
        on ? this.sel.add(path) : this.sel.delete(path);
        if (this.sel.size === all.length) this.sel = null;
        this.render();
    },

    selectAll(on) { this.sel = on ? null : new Set(); this.render(); },

    diff(path) { this.diffPath = path; this.render(); },

    _loadDiff() {
        App.api(`/api/git/diff?repo=${encodeURIComponent(this.repo)}&path=${encodeURIComponent(this.diffPath)}`).then(d => {
            const el = document.getElementById('git-diff');
            if (!el) return;
            el.innerHTML = d.diff.split('\n').map(l => {
                const c = /^(\+\+\+|---)/.test(l) ? 'h' : l[0] === '+' ? 'a' : l[0] === '-' ? 'd' : l.startsWith('@@') ? 'u' : '';
                return `<span class="${c}">${esc(l)}</span>`;
            }).join('\n');
        }).catch(e => { const el = document.getElementById('git-diff'); if (el) el.textContent = e.message; });
    },

    // ── Actions ────────────────────────────────────────────────

    act(action, body = {}, confirmText) {
        if (this.busy || (confirmText && !confirm(confirmText))) return Promise.resolve();
        this.busy = true;
        if (this.el) this.el.classList.add('git-busy');
        return App.api('/api/git/' + action, { json: Object.assign({ repo: this.repo }, body) })
            .then(r => {
                this._out = r.message || '';
                this.data = r.overview;
                toast((r.message || 'Done').split('\n')[0]);
                return r;
            })
            .catch(e => {
                this._out = e.message;
                toast(e.message, true);
                return this.load().then(() => null);
            })
            .finally(() => {
                this.busy = false;
                if (this.el) this.el.classList.remove('git-busy');
                this.render();
                this.badges();
                document.dispatchEvent(new CustomEvent('git-changed'));
            });
    },

    commit() {
        const msg = (document.getElementById('git-msg').value || '').trim();
        if (!msg) { toast('Enter a commit message', true); return document.getElementById('git-msg').focus(); }
        const newOn = document.getElementById('git-new-branch-on').checked;
        const nb = newOn ? document.getElementById('git-new-branch').value.trim() : '';
        if (newOn && !nb) { toast('Enter the new branch name', true); return document.getElementById('git-new-branch').focus(); }
        const paths = this.sel ? [...this.sel] : null;
        this.act('commit', { message: msg, paths, new_branch: nb, push: document.getElementById('git-push-after').checked })
            .then(r => { if (r) { this._msg = ''; this.sel = null; this.render(); } });
    },

    checkout(branch) {
        if (this.data.status.files.length && !confirm(`Switch to "${branch}"?\nUncommitted changes are carried over; git refuses if they conflict.`)) return this.render();
        this.act('checkout', { branch });
    },

    createBranch() {
        const name = document.getElementById('git-br-name').value.trim();
        if (!name) return toast('Enter a branch name', true);
        this.act('branch', { name });
    },

    deleteBranch(branch) {
        if (!confirm(`Delete branch "${branch}"?`)) return;
        this.act('branch_delete', { branch }).then(r => {
            if (r === null && confirm(`"${branch}" is not merged. Delete it anyway? Its commits will be lost.`)) {
                this.act('branch_delete', { branch, force: true });
            }
        });
    },

    discard(paths) {
        const files = this.data.status.files.map(f => f.path);
        if (paths === 'all') paths = files;
        else if (paths === null) paths = this.sel ? [...this.sel] : files;
        if (!paths.length) return;
        this.act('discard', { paths }, `Discard changes in ${paths.length} file(s)?\n${paths.slice(0, 8).join('\n')}${paths.length > 8 ? '\n…' : ''}\n\nThis cannot be undone (new files are deleted).`);
    },

    resetHard() {
        const st = this.data.status;
        this.act('reset', {}, `Reset "${st.branch}" to ${st.upstream}?\n\nA backup branch (backup/<date>) keeps the current commits and uncommitted changes are stashed (git stash list).`);
    },

    fix(id, dangerLabel) {
        this.act('fix', { id }, dangerLabel ? dangerLabel + '?' : null);
    },

    saveIdentity() {
        this.act('identity', { name: document.getElementById('git-id-name').value, email: document.getElementById('git-id-email').value,
                               scope: document.getElementById('git-id-scope').value });
    },
};

App.onEscape(() => {
    const o = document.getElementById('git-overlay');
    if (o && o.classList.contains('open')) Git.closeModal();
});
document.addEventListener('DOMContentLoaded', () => Git.badges());
