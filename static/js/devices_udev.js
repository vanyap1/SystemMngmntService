/* ==========================================================================
   Devices popup tab "udev": live events (udevadm monitor), rules editor
   (/etc/udev/rules.d), service status and udevadm tools.
   The monitor runs on the server only while the Events view is open and polled.
   ========================================================================== */

Devices.register({
    id: 'udev',
    autoMs: 0,
    EVENTS_MS: 1000,
    MAX_EVENTS: 500,
    view: 'events',
    events: [],
    since: 0,
    evTimer: null,
    evOpen: new Set(),      // event ids with expanded properties
    monitorState: null,
    files: [],
    dirsOpen: new Set(),    // rules directories are collapsed by default
    current: null,          // {dir, name, path, editable, isNew}
    original: '',
    dirty: false,

    onShow() {
        this.setView(this.view, true);
        this.loadStatus();
        if (!this._bound) {
            this._bound = true;
            document.getElementById('ur-text').addEventListener('keydown', e => {
                if ((e.ctrlKey || e.metaKey) && e.key === 's') {
                    e.preventDefault();
                    this.save();
                }
            });
            document.getElementById('ue-body').addEventListener('click', e => {
                const tr = e.target.closest('tr[data-id]');
                if (!tr) return;
                const id = +tr.dataset.id;
                if (this.evOpen.has(id)) this.evOpen.delete(id);
                else this.evOpen.add(id);
                this.renderEvents(true);
            });
        }
    },

    onHide() { this._stopEvents(); },

    canLeave() {
        return !this.dirty || confirm(`Discard unsaved changes in ${this.current ? this.current.name : 'the rule'}?`);
    },

    setView(view, force) {
        if (view === this.view && !force) return;
        this.view = view;
        document.querySelectorAll('.ud-views button').forEach(b => b.classList.toggle('active', b.dataset.view === view));
        document.querySelectorAll('#devpane-udev .ud-view').forEach(v => { v.hidden = v.dataset.view !== view; });
        document.querySelectorAll('#devpane-udev .ud-ctrl').forEach(c => { c.hidden = c.dataset.for !== view; });
        if (view === 'events') this._startEvents();
        else this._stopEvents();
        this.load();
    },

    load() {
        if (this.view === 'events') return this._pollEvents();
        if (this.view === 'rules') return this.loadRules();
        return this.loadStatus();
    },

    render() {
        if (this.view === 'events') this.renderEvents(true);
        else if (this.view === 'rules') this.renderRules();
    },

    // ── events ─────────────────────────────────────────────────────────────

    _startEvents() {
        if (this.evTimer) return;
        this.evTimer = setInterval(() => this._pollEvents(), this.EVENTS_MS);
    },

    _stopEvents() {
        clearInterval(this.evTimer);
        this.evTimer = null;
    },

    _pollEvents() {
        return App.api('/api/udev/events?since=' + this.since).then(data => {
            this.monitorState = data;
            if (data.next < this.since) this.since = 0;        // server restarted
            if (data.events.length) {
                this.events = data.events.reverse().concat(this.events).slice(0, this.MAX_EVENTS);
                this.since = data.next;
            }
            if (Devices.tab === 'udev' && this.view === 'events') this.renderEvents(false);
        });
    },

    clearEvents() {
        this.events = [];
        this.evOpen.clear();
        App.api('/api/udev/events/clear', { json: {} }).catch(() => {});
        this.renderEvents(true);
    },

    renderEvents(force) {
        const paused = document.getElementById('ue-pause').checked;
        const st = this.monitorState;
        const state = !st ? 'starting monitor…'
            : st.error ? 'monitor error: ' + st.error
            : st.running ? 'udevadm monitor running' : 'monitor stopped';
        Devices.summary(`${state} · ${this.events.length} events kept` + (paused ? ' · paused' : ''), this.id);
        if (paused && !force) return;

        const src = document.getElementById('ue-source').value;
        const q = document.getElementById('ue-filter').value.trim().toLowerCase();
        const list = this.events.filter(e => (!src || e.source === src) && (!q ||
            [e.action, e.subsystem, e.devpath, e.props.DEVNAME, e.props.ID_MODEL, e.props.ID_VENDOR_ID]
                .some(v => (v || '').toLowerCase().includes(q))));
        const body = document.getElementById('ue-body');
        if (!list.length) {
            body.innerHTML = `<div class="tbl-empty">${this.events.length ? 'No events match the filter'
                : 'Waiting for events… plug a USB device in or use “Trigger” in Service &amp; tools.'}</div>`;
            return;
        }
        const actionCls = { add: 'text-ok', bind: 'text-ok', remove: 'text-error', unbind: 'text-error', change: 'text-warn' };
        body.innerHTML = `<table class="tbl dev-tbl ue-tbl"><thead><tr>
            <th style="width:110px">Time</th><th style="width:70px">Source</th><th style="width:80px">Action</th>
            <th style="width:120px">Subsystem</th><th>Device</th></tr></thead><tbody>` +
            list.map(e => {
                const time = Devices.fmtMs(e.time);
                const model = [e.props.ID_VENDOR_ID && e.props.ID_MODEL_ID ? e.props.ID_VENDOR_ID + ':' + e.props.ID_MODEL_ID : '',
                               e.props.ID_MODEL].filter(Boolean).join(' ');
                const open = this.evOpen.has(e.id);
                const props = open ? `<tr class="ue-props"><td colspan="5"><pre>${esc(Object.entries(e.props)
                    .map(([k, v]) => k + '=' + v).join('\n'))}</pre></td></tr>` : '';
                return `<tr class="dev-row" data-id="${e.id}">
                    <td class="mono small">${time}</td>
                    <td><span class="badge ${e.source === 'udev' ? 'badge-info' : 'badge-muted'}">${esc(e.source)}</span></td>
                    <td class="mono ${actionCls[e.action] || ''}">${esc(e.action)}</td>
                    <td class="mono small">${esc(e.subsystem)}</td>
                    <td class="mono small"><i class="fa-solid fa-caret-${open ? 'down' : 'right'} dev-caret"></i>${
                        e.props.DEVNAME ? '<b>' + esc(e.props.DEVNAME) + '</b> ' : ''}<span class="faint">${esc(e.devpath)}</span>
                        ${model ? '<span class="muted"> · ' + esc(model) + '</span>' : ''}</td>
                </tr>${props}`;
            }).join('') + '</tbody></table>';
    },

    // ── rules ──────────────────────────────────────────────────────────────

    loadRules() {
        return App.api('/api/udev/rules').then(data => {
            this.files = data.files;
            this.dirs = data.dirs;
            const local = data.files.filter(f => f.dir === 'local').length;
            Devices.summary(`${data.files.length} rules files · ${local} local (editable)`, this.id);
            this.renderRules();
        });
    },

    toggleDir(key) {
        if (this.dirsOpen.has(key)) this.dirsOpen.delete(key);
        else this.dirsOpen.add(key);
        this.renderRules();
    },

    renderRules() {
        const box = document.getElementById('ur-files');
        if (!this.dirs) return;
        const q = document.getElementById('ur-filter').value.trim().toLowerCase();
        const cur = this.current;
        box.innerHTML = this.dirs.map(d => {
            const files = this.files.filter(f => f.dir === d.key && (!q || f.name.toLowerCase().includes(q)));
            const items = files.map(f => {
                const sel = cur && cur.dir === f.dir && cur.name === f.name;
                const overrides = f.dir !== 'system' && this.files.some(x => x.name === f.name && x.dir !== f.dir);
                return `<div class="ur-file${sel ? ' sel' : ''}${f.overridden_by ? ' overridden' : ''}"
                             onclick='Devices.tabs.udev.openRule(${esc(JSON.stringify(f.dir))}, ${esc(JSON.stringify(f.name))})'
                             title="${esc(f.path)}${f.overridden_by ? ' — overridden by ' + esc(f.overridden_by) : ''}">
                    <span class="mono">${esc(f.name)}</span>
                    ${overrides ? '<span class="badge badge-info">overrides</span>' : ''}
                    ${f.overridden_by ? '<span class="badge badge-muted">overridden</span>' : ''}
                </div>`;
            }).join('');
            const isNew = cur && cur.isNew && d.key === 'local'
                ? `<div class="ur-file sel"><span class="mono">${esc(cur.name)}</span><span class="badge badge-ok">new</span></div>` : '';
            const open = q || this.dirsOpen.has(d.key) || (cur && cur.dir === d.key);
            return `<div class="ur-dir">
                <div class="ur-dir-head" onclick='Devices.tabs.udev.toggleDir(${esc(JSON.stringify(d.key))})'>
                    <i class="fa-solid fa-caret-${open ? 'down' : 'right'} dev-caret"></i>
                    <i class="fa-solid ${d.editable ? 'fa-pen' : 'fa-lock'}"></i> ${esc(d.key)}
                    <span class="badge badge-muted">${files.length}</span>
                    <span class="faint mono">${esc(d.path)}</span></div>
                ${open ? isNew + (items || (isNew ? '' : '<div class="ur-empty faint small">no files</div>')) : ''}
            </div>`;
        }).join('');
    },

    _setEditor(rule, text, dirty) {
        this.current = rule;
        this.original = rule.isNew ? '' : text;
        const ta = document.getElementById('ur-text');
        ta.value = text;
        ta.disabled = false;
        ta.readOnly = !rule.editable;
        this.dirty = dirty;
        document.getElementById('ur-problems').hidden = true;
        this._renderHead();
        this.renderRules();
    },

    _renderHead() {
        const r = this.current;
        const head = document.getElementById('ur-head');
        if (!r) {
            head.innerHTML = '<span class="muted small">Select a rules file</span>';
            return;
        }
        const name = esc(JSON.stringify(r.name));
        head.innerHTML = `
            <i class="fa-solid fa-file-code text-ok"></i>
            <span class="mono">${esc(r.name)}</span>${this.dirty ? '<span class="text-warn" title="Unsaved changes">●</span>' : ''}
            <span class="faint small mono">${esc(r.path)}</span>
            ${r.editable ? '' : '<span class="badge badge-muted"><i class="fa-solid fa-lock"></i> read-only</span>'}
            <span class="spacer"></span>
            <button type="button" class="btn btn-ghost btn-sm" onclick="Devices.tabs.udev.check()"><i class="fa-solid fa-spell-check"></i> Check</button>
            ${r.editable ? `<button type="button" class="btn btn-success btn-sm" onclick="Devices.tabs.udev.save()" title="Ctrl+S"><i class="fa-solid fa-floppy-disk"></i> Save</button>` : ''}
            ${r.editable && this.dirty && !r.isNew ? `<button type="button" class="btn btn-ghost btn-sm" onclick="Devices.tabs.udev.revert()"><i class="fa-solid fa-rotate-left"></i> Revert</button>` : ''}
            ${!r.editable ? `<button type="button" class="btn btn-info btn-sm" onclick="Devices.tabs.udev.override()" title="Copy to /etc/udev/rules.d — the local copy replaces this file"><i class="fa-solid fa-code-branch"></i> Override in /etc</button>` : ''}
            ${r.editable && !r.isNew ? `<button type="button" class="btn btn-danger btn-sm" onclick='Devices.tabs.udev.remove(${name})'><i class="fa-solid fa-trash-can"></i></button>` : ''}`;
    },

    markDirty() {
        const was = this.dirty;
        this.dirty = this.current && (this.current.isNew || document.getElementById('ur-text').value !== this.original);
        if (was !== this.dirty) this._renderHead();
    },

    openRule(dir, name) {
        if (this.current && this.current.dir === dir && this.current.name === name) return Promise.resolve();
        if (!this.canLeave()) return Promise.resolve();
        return App.api(`/api/udev/rule?dir=${encodeURIComponent(dir)}&name=${encodeURIComponent(name)}`)
            .then(r => this._setEditor(r, r.text, false))
            .catch(e => toast(e.message, true));
    },

    /** Start a new local rules file; appends to an existing local file with the same name. */
    newRule(name, text = '') {
        if (Devices.tab !== 'udev') return;
        if (this.view !== 'rules') this.setView('rules');
        if (!this.canLeave()) return;
        this.dirty = false;
        if (!name) {
            name = prompt('New rules file in /etc/udev/rules.d:', '99-local.rules');
            if (!name) return;
            if (!name.endsWith('.rules')) name += '.rules';
        }
        const ready = this.files.length ? Promise.resolve() : this.loadRules();
        ready.then(() => {
            const existing = this.files.find(f => f.dir === 'local' && f.name === name);
            if (existing) {
                this.current = null;
                return this.openRule('local', name).then(() => {
                    const ta = document.getElementById('ur-text');
                    ta.value = ta.value.replace(/\n*$/, '\n\n') + text;
                    this.markDirty();
                    toast(`Appended to existing ${name} — review and save`);
                });
            }
            const dir = this.dirs.find(d => d.key === 'local');
            this._setEditor({ dir: 'local', name, path: dir.path + '/' + name, editable: true, isNew: true },
                text || '# ' + name + '\n', true);
        });
    },

    override() {
        const r = this.current;
        const text = `# Local copy of ${r.path} — this file replaces it.\n` + document.getElementById('ur-text').value;
        this.dirty = false;
        this.newRule(r.name, text);
    },

    revert() {
        if (!this.current || this.current.isNew) return;
        document.getElementById('ur-text').value = this.original;
        this.markDirty();
    },

    _showProblems(problems) {
        const box = document.getElementById('ur-problems');
        box.hidden = !problems.length;
        box.innerHTML = problems.map(p =>
            `<div class="ur-problem" onclick="Devices.tabs.udev.gotoLine(${p.line})"><i class="fa-solid fa-triangle-exclamation"></i>
                Line ${p.line}: ${esc(p.message)}</div>`).join('');
    },

    gotoLine(line) {
        const ta = document.getElementById('ur-text');
        const lines = ta.value.split('\n');
        const start = lines.slice(0, line - 1).reduce((s, l) => s + l.length + 1, 0);
        ta.focus();
        ta.setSelectionRange(start, start + (lines[line - 1] || '').length);
        ta.scrollTop = Math.max(0, (line - 5) * parseFloat(getComputedStyle(ta).lineHeight));
    },

    check() {
        const text = document.getElementById('ur-text').value;
        return App.api('/api/udev/rule/check', { json: { text } }).then(r => {
            this._showProblems(r.problems);
            if (!r.problems.length) toast('No syntax problems found');
            return r.problems;
        });
    },

    save() {
        const r = this.current;
        if (!r || !r.editable) return;
        const text = document.getElementById('ur-text').value;
        App.api('/api/udev/rule/check', { json: { text } }).then(c => {
            this._showProblems(c.problems);
            if (c.problems.length && !confirm(`${c.problems.length} syntax problem(s) found. Save anyway?`)) return;
            return App.api('/api/udev/rule', { json: { name: r.name, text, force: true } }).then(res => {
                r.isNew = false;
                r.path = res.path;
                this.original = text;
                this.dirty = false;
                this._renderHead();
                toast(`Saved ${res.path} — press “Reload rules” to apply`);
                return this.loadRules();
            });
        }).catch(e => toast(e.message, true));
    },

    remove(name) {
        if (!confirm(`Delete /etc/udev/rules.d/${name}?`)) return;
        App.api('/api/udev/rule/delete', { json: { name } }).then(() => {
            toast('Deleted ' + name);
            this.current = null;
            this.dirty = false;
            const ta = document.getElementById('ur-text');
            ta.value = '';
            ta.disabled = true;
            this._renderHead();
            return this.loadRules();
        }).catch(e => toast(e.message, true));
    },

    // ── service & tools ────────────────────────────────────────────────────

    loadStatus() {
        return App.api('/api/udev/status').then(s => {
            const ok = s.active === 'active';
            document.getElementById('ud-svc-state').innerHTML =
                `<span class="${ok ? 'text-ok' : 'text-error'}"><i class="fa-solid fa-circle"></i> udevd ${esc(s.active)}</span>`;
            document.getElementById('ut-status').innerHTML = `<table class="tbl dev-kv">
                <tr><td class="dev-k">State</td><td class="${ok ? 'text-ok' : 'text-error'}">${esc(s.active)} (${esc(s.sub)})</td></tr>
                <tr><td class="dev-k">PID</td><td class="mono">${esc(s.pid)}</td></tr>
                <tr><td class="dev-k">Since</td><td>${esc(s.since)}</td></tr>
                <tr><td class="dev-k">Version</td><td class="mono">${esc(s.version)}</td></tr>
                <tr><td class="dev-k">Rules</td><td>${s.rules.local} local · ${s.rules.runtime} runtime · ${s.rules.system} system</td></tr>
            </table>`;
            document.getElementById('ut-subsystems').innerHTML = s.subsystems.map(x => `<option value="${esc(x)}">`).join('');
            if (this.view === 'tools') Devices.summary(`systemd-udevd ${s.active} · udev ${s.version}`, this.id);
        });
    },

    _run(title, json) {
        const out = document.getElementById('ut-output');
        out.classList.remove('muted');
        out.textContent = `$ ${title}\nRunning…`;
        return Devices.udevAction(json)
            .then(r => { out.textContent = `$ ${title}\n${r.output || 'Done'}`; return r; })
            .catch(e => { out.textContent = `$ ${title}\n${e.message}`; throw e; });
    },

    reload() {
        Devices.udevAction({ action: 'reload' })
            .then(() => toast('udev rules reloaded'))
            .catch(e => toast(e.message.split('\n').slice(0, 3).join(' '), true));
    },

    restart() {
        if (!confirm('Restart systemd-udevd?')) return;
        this._run('systemctl restart systemd-udevd', { action: 'restart' })
            .then(() => toast('systemd-udevd restarted')).catch(() => toast('Restart failed', true))
            .finally(() => this.loadStatus());
    },

    trigger() {
        const kind = document.getElementById('ut-trig-kind').value;
        const subsystem = document.getElementById('ut-trig-sub').value.trim();
        const device = document.getElementById('ut-trig-dev').value.trim();
        const all = !subsystem && !device;
        if (all && !confirm(`Trigger "${kind}" for ALL devices?`)) return;
        this._run(`udevadm trigger --action=${kind}` + (subsystem ? ' --subsystem-match=' + subsystem : '') +
                  (device ? ' --name-match=' + device : ''),
            { action: 'trigger', kind, subsystem, device, all }).catch(() => {});
    },

    test() {
        const device = document.getElementById('ut-dev').value.trim();
        if (!device) return toast('Enter a device, e.g. /dev/ttyUSB0', true);
        const kind = document.getElementById('ut-test-kind').value;
        this._run(`udevadm test --action=${kind} ${device}`, { action: 'test', device, kind }).catch(() => {});
    },

    attrs() {
        const device = document.getElementById('ut-dev').value.trim();
        if (!device) return toast('Enter a device, e.g. /dev/ttyUSB0', true);
        this._run(`udevadm info --attribute-walk --name=${device}`, { action: 'attrs', device }).catch(() => {});
    },
});
