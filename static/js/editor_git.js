/* ==========================================================================
   Git in the code editor (templates/editor.html): which repository a file belongs to (target_dir itself or
   projects cloned into it), change marks in the file tree, git status in the status bar, "Commit this file".
   The popup itself is the shared Git panel (static/js/git.js).
   ========================================================================== */

const EditorGit = {
    data: null,          // /api/git/tree_status: {root, repos: [{id, top, branch, ahead, behind, changes, remote}], files}
    _timer: 0,

    MARK: { modified: ['M', 'm'], added: ['A', 'a'], deleted: ['D', 'd'], renamed: ['R', 'r'], copied: ['C', 'a'],
            untracked: ['U', 'u'], conflict: ['!', 'c'] },

    refresh() {
        clearTimeout(this._timer);
        this._timer = setTimeout(() => {
            App.api('/api/git/tree_status').then(d => {
                this.data = d;
                this.decorate();
                this.showStatus();
                this._badge();
            }).catch(() => {});
        }, 150);
    },

    /** Repository of an absolute path (longest matching worktree), or null. */
    repoOf(path) {
        if (!this.data || !path) return null;
        let best = null;
        for (const r of this.data.repos) {
            if ((path === r.top || path.startsWith(r.top + '/')) && (!best || r.top.length > best.top.length)) best = r;
        }
        return best;
    },

    decorate() {
        const files = this.data ? this.data.files : {};
        const changed = Object.keys(files);
        const tops = new Map((this.data ? this.data.repos : []).map(r => [r.top, r]));
        document.querySelectorAll('#file-tree .tree-row[data-path]').forEach(row => {
            row.querySelectorAll('.git-mark, .git-root').forEach(x => x.remove());
            row.classList.remove('git-m', 'git-a', 'git-d', 'git-r', 'git-u', 'git-c', 'git-dirdot');
            const p = row.dataset.path, lbl = row.querySelector('.lbl');
            if (row.dataset.type === 'dir') {
                const repo = tops.get(p);
                if (repo) {
                    const tag = document.createElement('span');
                    tag.className = 'git-root';
                    tag.title = `git repository · ${repo.branch || 'detached'}` + (repo.remote ? ` · ${repo.remote.host}/${repo.remote.slug}` : ' · local only');
                    tag.innerHTML = `<i class="fa-brands fa-git-alt"></i>${esc(repo.branch || 'HEAD')}`;
                    lbl.after(tag);
                }
                if (changed.some(f => f.startsWith(p + '/'))) row.classList.add('git-dirdot');
                return;
            }
            const kind = files[p];
            if (!kind) return;
            const [letter, cls] = this.MARK[kind] || ['M', 'm'];
            row.classList.add('git-' + cls);
            const mark = document.createElement('span');
            mark.className = 'git-mark';
            mark.textContent = letter;
            mark.title = 'git: ' + kind;
            lbl.after(mark);
        });
    },

    showStatus() {
        const el = document.getElementById('eg-status');
        const btn = document.getElementById('eg-commit');
        const repo = this.repoOf(currentPath) || (this.data && this.data.repos.find(r => r.id === 'project'));
        const fileChanged = currentPath && this.data && this.data.files[currentPath];
        btn.hidden = !fileChanged;
        if (!repo) {
            const n = this.data ? this.data.repos.length : 0;
            const changes = n ? this.data.repos.reduce((s, r) => s + r.changes, 0) : 0;
            el.innerHTML = !this.data ? '' : n ? `<i class="fa-brands fa-git-alt"></i> ${n} repo(s) in target_dir${changes ? ` · ${changes}✎` : ''}`
                                                : '<i class="fa-brands fa-git-alt"></i> no git';
            el.title = n ? 'Projects cloned into target_dir — open a file to see its repository' : 'Not a git repository — click to clone a project or initialize one';
            return;
        }
        const name = repo.top.split('/').pop();
        el.innerHTML = `<i class="fa-brands fa-git-alt"></i> ${esc(name)} <i class="fa-solid fa-code-branch"></i> ${esc(repo.branch || 'detached')}` +
            (repo.changes ? ` · ${repo.changes}✎` : '') + (repo.ahead ? ` ↑${repo.ahead}` : '') + (repo.behind ? ` ↓${repo.behind}` : '') +
            (repo.remote && repo.remote.host ? ` · <i class="${/github/i.test(repo.remote.host) ? 'fa-brands fa-github' : 'fa-solid fa-cloud'}"></i> ${esc(repo.remote.slug)}` : '');
        el.title = `${repo.top}\nclick: Git (commit, push, pull…)`;
    },

    _badge() {
        const b = document.querySelector('#eg-btn .git-badge');
        const total = this.data ? this.data.repos.reduce((s, r) => s + r.changes, 0) : 0;
        b.hidden = !total;
        b.textContent = total;
        b.className = 'git-badge';
        document.getElementById('eg-btn').title = this.data && this.data.repos.length
            ? `Git · ${this.data.repos.length} repositor${this.data.repos.length > 1 ? 'ies' : 'y'} · ${total} change(s)`
            : 'Git — target_dir is not a git repository';
    },

    open() {
        const repo = this.repoOf(currentPath) || (this.data && (this.data.repos.find(r => r.id === 'project') || this.data.repos[0]));
        Git.openModal(repo ? repo.id : 'project');
    },

    commitCurrent() {
        const repo = this.repoOf(currentPath);
        if (!repo) return this.open();
        const tab = tabs.get(currentPath);
        if (tab && tab.dirty && !confirm('The file has unsaved changes — only the saved version is committed. Continue?')) return;
        Git.openModal(repo.id, { select: [currentPath.slice(repo.top.length + 1)] });
    },
};

document.addEventListener('git-changed', () => EditorGit.refresh());
EditorGit.refresh();
