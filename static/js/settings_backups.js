/* ==========================================================================
   Settings → Backups → "Pick from the project…": a lazy tree of target_dir (one folder per request,
   POST /api/backups/tree) where each row adds / removes a line in the Skip or Keep list. Matching is done by
   the server (core/backups.Matcher) with the current, unsaved textarea contents.
   ========================================================================== */

const BackupTree = {
    folders: {},           // rel → items of a loaded folder
    open_: new Set(),      // expanded folders

    $(id) { return document.getElementById(id); },

    open() {
        this.folders = {};
        this.open_ = new Set();
        this.$('bt-overlay').classList.add('open');
        this.$('bt-tree').innerHTML = '<div class="muted">Loading…</div>';
        this._fetch('').then(() => this.render()).catch(e => { this.$('bt-tree').innerHTML = `<div class="text-error">✗ ${esc(e.message)}</div>`; });
    },

    close() { this.$('bt-overlay').classList.remove('open'); },

    _lines(id) { return this.$(id).value.split('\n').map(l => l.trim()).filter(Boolean); },

    _fetch(rel) {
        return App.api('/api/backups/tree', { json: { path: rel, skip: this._lines('backup_skip'), keep: this._lines('deploy_keep') } })
            .then(d => { this.folders[rel] = d.items; this.$('bt-root').textContent = d.target; });
    },

    /** Re-read every loaded folder (the patterns changed). */
    reload() {
        const rels = Object.keys(this.folders);
        return Promise.all(rels.map(r => this._fetch(r).catch(() => { delete this.folders[r]; this.open_.delete(r); })))
            .then(() => this.render());
    },

    toggleDir(rel) {
        if (this.open_.has(rel)) { this.open_.delete(rel); return this.render(); }
        this.open_.add(rel);
        (this.folders[rel] ? Promise.resolve() : this._fetch(rel)).then(() => this.render()).catch(e => toast(e.message, true));
    },

    patternFor(it) { return '/' + it.rel + (it.dir ? '/' : ''); },

    /** Add the pattern to the list, or remove it when it is there already. */
    toggle(list, pattern) {
        const ta = this.$(list === 'skip' ? 'backup_skip' : 'deploy_keep');
        const lines = ta.value.split('\n');
        const i = lines.findIndex(l => l.trim() === pattern);
        if (i >= 0) lines.splice(i, 1);
        else {
            while (lines.length && !lines[lines.length - 1].trim()) lines.pop();
            lines.push(pattern);
        }
        ta.value = lines.join('\n');
        Settings.track();
        this.reload();
    },

    render() {
        const row = (it, depth, inh) => {
            const own = this.patternFor(it);
            const ext = !it.dir && /\.[^./]+$/.test(it.name) ? '*' + it.name.slice(it.name.lastIndexOf('.')) : '';
            const btn = (list, pattern, label, matched) => {
                const on = matched === pattern, other = matched && !on;
                const title = on ? `Remove “${pattern}” from the ${list} list`
                    : other ? `Already matched by “${matched}” — edit that line in the list`
                    : `Add “${pattern}” to the ${list} list`;
                return `<button type="button" class="bt-tag ${list}${on ? ' on' : ''}${other ? ' other' : ''}" title="${esc(title)}"
                    ${other ? 'disabled' : `onclick="BackupTree.toggle('${list}', ${esc(JSON.stringify(pattern))})"`}>${esc(label)}</button>`;
            };
            const state = it.note ? `<span class="bt-note">${esc(it.note)}</span>`
                : inh.skip ? `<span class="bt-note">inside a skipped folder (${esc(inh.skip)})</span>`
                : [it.skip ? `<span class="bt-st skip">skip ← ${esc(it.skip)}</span>` : '',
                   it.keep || inh.keep ? `<span class="bt-st keep">keep ← ${esc(it.keep || inh.keep)}</span>` : ''].join('');
            const opened = it.dir && this.open_.has(it.rel);
            const n = esc(JSON.stringify(it.rel));
            let h = `<div class="bt-row${it.skip || inh.skip || it.note ? ' dim' : ''}" style="padding-left:${8 + depth * 18}px">
                <span class="bt-name"${it.dir && !it.note ? ` onclick="BackupTree.toggleDir(${n})"` : ''}>
                    ${it.dir ? `<i class="fa-solid fa-chevron-${opened ? 'down' : 'right'} bt-chev"></i><i class="fa-solid fa-folder bt-ico-dir"></i>`
                             : `<span class="bt-chev"></span><i class="fa-regular ${it.link ? 'fa-share-from-square' : 'fa-file'} bt-ico"></i>`}
                    <span class="mono">${esc(it.name)}${it.dir ? '/' : ''}</span>
                    ${it.size !== null ? `<span class="muted small">${App.fmtBytes(it.size)}</span>` : ''}
                    ${state}
                </span>
                <span class="bt-acts">${it.note || inh.skip ? '' : btn('skip', own, 'Skip', it.skip) + (ext ? btn('skip', ext, ext, it.skip) : '')}${it.note ? '' : btn('keep', own, 'Keep', it.keep)}</span>
            </div>`;
            if (opened) {
                const kids = this.folders[it.rel];
                const sub = { skip: inh.skip || (it.dir && it.skip) || '', keep: inh.keep || (it.dir && it.keep) || '' };
                h += kids ? (kids.map(k => row(k, depth + 1, sub)).join('') || `<div class="bt-row muted" style="padding-left:${26 + (depth + 1) * 18}px">empty</div>`)
                          : `<div class="bt-row muted" style="padding-left:${26 + (depth + 1) * 18}px">Loading…</div>`;
            }
            return h;
        };
        const root = this.folders[''] || [];
        this.$('bt-tree').innerHTML = root.map(it => row(it, 0, { skip: '', keep: '' })).join('') || '<div class="muted">The project folder is empty.</div>';
    },
};

App.onEscape(() => BackupTree.close());
