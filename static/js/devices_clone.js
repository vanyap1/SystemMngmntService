/* ==========================================================================
   HW Utils tab "Clone / Image" (core/sysclone.py, core/smb.py, tools/clone-system.sh):
   copy the running system to another disk, build a bootable .img on an SMB share (mounted and browsed here), or
   write an image from the share / a mounted local disk / a home folder onto a disk.
   The partition size = used data + reserve + extra MiB (or the whole disk). The job runs on the server and
   survives closing the popup; this tab polls its log while visible.
   ========================================================================== */

Devices.register({
    id: 'clone',
    autoMs: 0,
    data: null,              // /api/sysclone/info
    path: null,              // current folder in the share ('' = root), null = not browsed yet
    listing: null,
    filled: false,           // share form filled from the saved settings once
    logNext: 0,
    poll: null,
    wr: { root: null, path: '', listing: null, found: null, sel: null },   // Write image: location, folder, chosen image

    $(id) { return document.getElementById(id); },
    mib(n) { return Math.round(n).toLocaleString('en-US').replace(/,/g, ' ') + ' MiB'; },

    load() {
        return App.api('/api/sysclone/info').then(d => {
            this.data = d;
            const s = d.smb.settings || {};
            if (!this.filled) {
                this.filled = true;
                this.$('smb-share').value = s.share || '';
                this.$('smb-user').value = s.username || '';
                this.$('smb-vers').innerHTML = d.smb.versions.map(v => `<option value="${esc(v)}">${v ? esc(v) : 'auto'}</option>`).join('');
                this.$('smb-vers').value = s.vers || '';
                this.$('smb-remember').checked = !!s.password_set;
            }
            this.$('smb-pass').placeholder = s.password_set ? '(saved)' : '';
            if (d.smb.mounted && this.path === null) this.browse(this._sub());
            this._roots();
            if (!d.smb.mounted) { this.path = null; this.listing = null; }
            this.render();
            if (d.job) this._job(d.job, true);
        });
    },

    /** Folder part of the share field (//host/share/sub -> sub). */
    _sub() {
        const parts = this.$('smb-share').value.replace(/\\/g, '/').replace(/^smb:/i, '').split('/').filter(Boolean);
        return parts.slice(2).join('/');
    },

    onShow() { if (this.data && this.data.job && this.data.job.state === 'running') this._startPoll(); },
    onHide() { this._stopPoll(); },

    render() {
        const d = this.data;
        if (!d) return;
        this.$('cl-sys').innerHTML = `System: <b class="mono">${esc(d.root_part || '?')}</b> · used ${esc(App.fmtBytes(d.used))}` +
            ` · minimal partition <b>${this.mib(d.min_mb)}</b> (data + ${d.reserve_mb} MiB reserve)` +
            ` · partition from ${this.mib(d.part_start / 2048)} · u-boot: ${esc(d.uboot || 'not found')}`;
        const warn = [];
        if (!d.root) warn.push('The panel runs without root here — mounting, cloning and imaging are not possible (view only).');
        if (d.missing.length) warn.push('Missing tools: ' + d.missing.join(', ') + ' (apt install rsync fdisk e2fsprogs mount).');
        if (!d.uboot) warn.push('No u-boot found (/usr/lib/u-boot/platform_install.sh) — the copy would not boot by itself.');
        this.$('cl-warn').hidden = !warn.length;
        this.$('cl-warn').innerHTML = warn.map(w => `<div><i class="fa-solid fa-triangle-exclamation"></i> ${esc(w)}</div>`).join('');
        this._renderDisks();
        this._renderShare();
        this._wrRender();
        this.sizes();
        Devices.summary(`${d.disks.length} disk(s) · share ${d.smb.mounted ? 'mounted' : 'not mounted'}`, this.id);
    },

    // ── Disks ──────────────────────────────────────────────

    /** Radio list of disks; ``group`` = 'cl' (clone target) or 'wr' (write target); ``minMb`` = smallest usable size. */
    _disksHtml(group, minMb) {
        const d = this.data, cur = this._disk(group);
        const free = d.disks.filter(x => !x.system && !x.mounted.length);
        return d.disks.map(x => {
            const parts = x.parts.map(p => `${esc(p.name)} ${esc(App.fmtBytes(p.size))}${p.fstype ? ' ' + esc(p.fstype) : ''}${p.label ? ' «' + esc(p.label) + '»' : ''}` +
                (p.mountpoints.length ? ` → ${esc(p.mountpoints.join(', '))}` : '')).join('<br>') || '<i>no partitions</i>';
            const small = !x.system && minMb && (x.size / 1048576) < minMb;
            const note = x.system ? 'the system runs from it — excluded' : small ? 'too small' :
                x.mounted.length ? `mounted (${x.mounted.join(', ')}) — unmount it first` : '';
            const off = x.system || small || x.mounted.length, on = cur && cur.name === x.name;
            return `<label class="cl-disk${off ? ' sys' : ''}${on ? ' on' : ''}">` +
                `<input type="radio" name="${group}-disk" value="${esc(x.name)}"${off ? ' disabled' : ''}${on ? ' checked' : ''}` +
                ` onchange="Devices.tabs.clone.pickDisk('${group}')">` +
                `<span class="cl-dname mono">${esc(x.name)}</span><span class="cl-dsize">${esc(App.fmtBytes(x.size))}</span>` +
                `<span class="cl-dinfo">${esc([x.tran, x.model, x.removable ? 'removable' : ''].filter(Boolean).join(' · '))}` +
                (note ? ` <span class="cl-dnote${x.system ? '' : ' text-error'}">${esc(note)}</span>` : '') +
                `<br><span class="faint small">${parts}</span></span></label>`;
        }).join('') + (free.length ? '' : '<div class="hint">No free disk: insert an SD card / USB disk (disks with mounted partitions are not offered).</div>');
    },

    _renderDisks() {
        this.$('cl-disks').innerHTML = this._disksHtml('cl', this.data.min_mb + 64);
        const img = this.wr.sel, raw = img && /\.img$/i.test(img.name);
        this.$('wr-disks').innerHTML = this._disksHtml('wr', raw ? img.size / 1048576 : 0);
    },

    _disk(group = 'cl') {
        const r = document.querySelector(`input[name="${group}-disk"]:checked`);
        return r && this.data ? this.data.disks.find(x => x.name === r.value) : null;
    },

    pickDisk(group = 'cl') { this.$(group + '-confirm').value = ''; this._renderDisks(); this.sizes(); },

    // ── Sizes / buttons ────────────────────────────────────

    sizes() {
        const d = this.data;
        if (!d) return;
        const busy = !!(d.job && (d.job.state === 'running' || d.job.state === 'stopping'));
        const ex = Math.max(0, parseInt(this.$('img-extra').value, 10) || 0);
        const part = d.min_mb + ex, img = d.part_start / 2048 + part + 1;
        this.$('img-size').innerHTML = `partition = ${this.mib(d.min_mb)} (data + reserve) + ${this.mib(ex)} = <b>${this.mib(part)}</b>, ` +
            `image ≈ ${esc(App.fmtBytes(img * 1048576))}` + (this.$('img-compress').value ? ' before compression' : '') +
            (d.smb.free != null ? ` · free on the share ${esc(App.fmtBytes(d.smb.free))}` : '');
        const tag = this.$('img-tag').value.trim(), stamp = new Date().toISOString().slice(0, 19).replace(/[-:]/g, '').replace('T', '_');
        const file = `${d.hostname}${tag ? '_' + tag : ''}_${stamp}.img${this.$('img-compress').value ? '.gz' : ''}`;
        this.$('img-target').innerHTML = d.smb.mounted && this.path !== null
            ? `Image goes to <b class="mono">${esc(d.smb.source.replace(/\\/g, '/'))}${this.path ? '/' + esc(this.path) : ''}</b> · file <span class="mono">${esc(file)}</span>`
            : 'Connect the share and open the folder for the image.';
        this.$('img-start').disabled = busy || !d.root || !d.smb.mounted || this.path === null;

        const disk = this._disk(), whole = this.$('cl-whole').checked;
        this.$('cl-extra').disabled = whole;
        this.$('cl-grow').disabled = whole;
        let txt = 'Choose a disk.';
        if (disk) {
            const max = Math.floor((disk.size - d.part_start * 512) / 1048576) - 1;
            const cx = Math.max(0, parseInt(this.$('cl-extra').value, 10) || 0);
            const size = whole ? max : d.min_mb + cx;
            txt = `${esc(disk.path)}: partition <b>${this.mib(size)}</b>` + (whole ? ' (whole disk)' : ` = ${this.mib(d.min_mb)} + ${this.mib(cx)}`) +
                ` of ${this.mib(max)} possible` + (size > max ? ' — <span class="text-error">does not fit, lower the extra size</span>' : '');
        }
        this.$('cl-size').innerHTML = txt;
        const ok = disk && this.$('cl-confirm').value.trim() === disk.name;
        this.$('cl-confirm').placeholder = disk ? disk.name : 'e.g. mmcblk1';
        this.$('cl-start').disabled = busy || !d.root || !ok;

        const wd = this._disk('wr'), wimg = this.wr.sel;
        this.$('wr-confirm').placeholder = wd ? wd.name : 'e.g. sda';
        let wt = !wimg ? 'Choose an image on the left.' : !wd ? 'Choose a target disk.' : '';
        if (wimg && wd) {
            const raw = /\.img$/i.test(wimg.name);
            wt = `${esc(wimg.name)} (${esc(App.fmtBytes(wimg.size))}${raw ? '' : ', compressed'}) → <b>${esc(wd.path)}</b> (${esc(App.fmtBytes(wd.size))})` +
                (raw && wimg.size > wd.size ? ' — <span class="text-error">the image is larger than the disk</span>' : '');
        }
        this.$('wr-size').innerHTML = wt;
        this.$('wr-start').disabled = busy || !d.root || !wimg || !wd || this.$('wr-confirm').value.trim() !== wd.name;
    },

    // ── Share ──────────────────────────────────────────────

    _renderShare() {
        const s = this.data.smb;
        this.$('smb-state').innerHTML = s.mounted ? `<span class="text-ok">connected</span> <span class="mono">${esc(s.source)}</span>` : 'not connected';
        this.$('smb-connect').hidden = s.mounted;
        this.$('smb-disconnect').hidden = !s.mounted;
        this.$('smb-forget').hidden = !(s.settings && s.settings.password_set);
        ['smb-share', 'smb-user', 'smb-pass', 'smb-vers'].forEach(id => { this.$(id).disabled = s.mounted; });
        this.$('smb-browser').hidden = !s.mounted;
        this.$('smb-free').textContent = s.free != null ? `${App.fmtBytes(s.free)} free of ${App.fmtBytes(s.total)}` : '';
        this._renderList();
    },

    connect() {
        const btn = this.$('smb-connect');
        btn.disabled = true;
        App.api('/api/smb/mount', { json: { share: this.$('smb-share').value, username: this.$('smb-user').value,
            password: this.$('smb-pass').value, vers: this.$('smb-vers').value, remember: this.$('smb-remember').checked } })
            .then(() => {
                this.$('smb-pass').value = '';
                this.path = null;
                toast('Share mounted');
                return Devices.refresh();
            })
            .catch(e => toast(e.message, true))
            .finally(() => { btn.disabled = false; });
    },

    disconnect() {
        App.api('/api/smb/umount', { json: {} }).then(() => { this.path = null; this.listing = null; toast('Share unmounted'); Devices.refresh(); })
            .catch(e => toast(e.message, true));
    },

    forget() {
        if (!confirm('Forget the saved share password?')) return;
        App.api('/api/smb/forget', { json: {} }).then(() => { this.$('smb-remember').checked = false; Devices.refresh(); })
            .catch(e => toast(e.message, true));
    },

    browse(path) {
        if (path === undefined) path = this.path || '';
        return App.api('/api/smb/list?path=' + encodeURIComponent(path)).then(d => {
            this.path = d.path; this.listing = d;
            this._renderList(); this.sizes();
        }).catch(e => {
            if (path) return this.browse('');            // a remembered sub folder is gone: show the root
            toast(e.message, true);
        });
    },

    mkdir() {
        const name = (prompt('New folder name:') || '').trim();
        if (!name) return;
        App.api('/api/smb/mkdir', { json: { path: this.path || '', name } }).then(() => this.browse((this.path ? this.path + '/' : '') + name))
            .catch(e => toast(e.message, true));
    },

    _renderList() {
        const el = this.$('smb-list'), crumbs = this.$('smb-crumbs');
        if (!this.listing) { el.innerHTML = ''; crumbs.innerHTML = ''; return; }
        const parts = this.listing.path ? this.listing.path.split('/') : [];
        crumbs.innerHTML = `<a data-go=""><i class="fa-solid fa-server"></i> ${esc((this.data.smb.source || 'share').replace(/\\/g, '/'))}</a>` +
            parts.map((p, i) => `<i class="fa-solid fa-chevron-right"></i><a data-go="${esc(parts.slice(0, i + 1).join('/'))}">${esc(p)}</a>`).join('');
        crumbs.onclick = e => { const a = e.target.closest('[data-go]'); if (a) this.browse(a.dataset.go); };
        const up = parts.length ? `<div class="cl-item dir" data-go="${esc(parts.slice(0, -1).join('/'))}"><i class="fa-solid fa-turn-up"></i><span>..</span><span></span><span></span><span></span></div>` : '';
        el.innerHTML = up + this.listing.items.map(it => {
            const p = (this.listing.path ? this.listing.path + '/' : '') + it.name;
            const icon = it.type === 'dir' ? 'fa-folder' : it.type === 'link' ? 'fa-link' : /\.img(\.gz|\.xz)?$/i.test(it.name) ? 'fa-compact-disc' : 'fa-file';
            const name = esc(it.name) + (it.type === 'link' ? ` <span class="faint">→ ${esc(it.target)}</span>` : '');
            return `<div class="cl-item ${it.type}"${it.type === 'dir' ? ` data-go="${esc(p)}"` : ''}><i class="fa-solid ${icon}"></i><span>${name}</span>` +
                `<span class="mono">${it.size != null ? esc(App.fmtBytes(it.size)) : ''}</span><span>${esc(App.fmtDate(it.mtime))}</span><span class="mono faint">${esc(it.mode)}</span></div>`;
        }).join('') + (this.listing.items.length ? '' : '<div class="hint cl-empty">empty folder</div>') +
            (this.listing.truncated ? '<div class="hint cl-empty">… more entries not shown</div>' : '');
        el.onclick = e => { const r = e.target.closest('[data-go]'); if (r) this.browse(r.dataset.go); };
    },

    // ── Write image → disk ─────────────────────────────────

    _roots() {
        const roots = this.data.roots || [], sel = this.$('wr-root');
        if (!roots.some(r => r.path === this.wr.root)) {                  // first time / location gone: share > disk > home
            const pick = roots.find(r => r.kind === 'share') || roots.find(r => r.kind === 'disk') || roots[0];
            this.wr = { root: pick ? pick.path : null, path: '', listing: null, found: null, sel: null };
            if (pick) this.wrBrowse('');
        }
        const kind = { share: 'Share', disk: 'Disk', home: 'Home' };
        sel.innerHTML = roots.map(r => `<option value="${esc(r.path)}"${r.path === this.wr.root ? ' selected' : ''}>${kind[r.kind] || ''}: ${esc(r.label)}</option>`).join('') ||
            '<option value="">no location</option>';
    },

    wrRoot(root) {
        this.wr = { root, path: '', listing: null, found: null, sel: null };
        this.wrBrowse('');
    },

    wrBrowse(path) {
        if (!this.wr.root) return Promise.resolve();
        if (path === undefined) path = this.wr.path;
        const q = `root=${encodeURIComponent(this.wr.root)}&path=${encodeURIComponent(path)}`;
        return App.api('/api/sysclone/browse?' + q).then(d => {
            this.wr.path = d.path; this.wr.listing = d; this.wr.found = null;
            this._wrRender();
        }).catch(e => { if (path) return this.wrBrowse(''); toast(e.message, true); });
    },

    wrFind() {
        if (!this.wr.root) return;
        const list = this.$('wr-list');
        list.innerHTML = '<div class="hint cl-empty"><i class="fa-solid fa-spinner fa-spin"></i> searching…</div>';
        App.api(`/api/sysclone/find?root=${encodeURIComponent(this.wr.root)}&path=${encodeURIComponent(this.wr.path)}`).then(d => {
            this.wr.found = d;
            this._wrRender();
        }).catch(e => { toast(e.message, true); this._wrRender(); });
    },

    _imgRow(it, sub) {
        const on = this.wr.sel && this.wr.sel.path === it.path;
        return `<div class="cl-item img${on ? ' on' : ''}" data-img="${esc(it.path)}"><i class="fa-solid fa-compact-disc"></i>` +
            `<span>${esc(it.name)}${sub ? ` <span class="cl-sub">${esc(sub)}</span>` : ''}</span>` +
            `<span class="mono">${esc(App.fmtBytes(it.size))}</span><span>${esc(App.fmtDate(it.mtime))}</span><span></span></div>`;
    },

    _wrRender() {
        const el = this.$('wr-list'), crumbs = this.$('wr-crumbs'), w = this.wr;
        const root = (this.data.roots || []).find(r => r.path === w.root);
        if (!root) { el.innerHTML = '<div class="hint cl-empty">No location (mount the share or a disk).</div>'; crumbs.innerHTML = ''; return this._wrSel(); }
        const parts = w.path ? w.path.split('/') : [];
        crumbs.innerHTML = `<a data-go=""><i class="fa-solid fa-folder-open"></i> ${esc(root.path)}</a>` +
            parts.map((p, i) => `<i class="fa-solid fa-chevron-right"></i><a data-go="${esc(parts.slice(0, i + 1).join('/'))}">${esc(p)}</a>`).join('');
        crumbs.onclick = e => { const a = e.target.closest('[data-go]'); if (a) this.wrBrowse(a.dataset.go); };
        let html = '';
        if (w.found) {
            html = `<div class="hint cl-empty">${w.found.images.length} image(s) below this folder${w.found.truncated ? ' (search stopped early)' : ''} · ` +
                `<a data-back>back to the folder</a></div>` +
                w.found.images.map(it => this._imgRow(it, it.path.includes('/') ? it.path.slice(0, it.path.lastIndexOf('/')) : '')).join('');
        } else if (w.listing) {
            const up = parts.length ? `<div class="cl-item dir" data-go="${esc(parts.slice(0, -1).join('/'))}"><i class="fa-solid fa-turn-up"></i><span>..</span><span></span><span></span><span></span></div>` : '';
            html = up + w.listing.dirs.map(dd => `<div class="cl-item dir" data-go="${esc((w.path ? w.path + '/' : '') + dd.name)}"><i class="fa-solid fa-folder"></i>` +
                    `<span>${esc(dd.name)}</span><span></span><span></span><span></span></div>`).join('') +
                w.listing.images.map(it => this._imgRow(it)).join('') +
                (w.listing.images.length ? '' : '<div class="hint cl-empty">No images in this folder — open a folder or use “Find images”.</div>');
        }
        el.innerHTML = html;
        el.onclick = e => {
            if (e.target.closest('[data-back]')) { w.found = null; return this._wrRender(); }
            const g = e.target.closest('[data-go]');
            if (g) return this.wrBrowse(g.dataset.go);
            const r = e.target.closest('[data-img]');
            if (r) {
                const list = w.found ? w.found.images : w.listing.images;
                w.sel = Object.assign({ root: w.root }, list.find(i => i.path === r.dataset.img));
                this._wrRender(); this._renderDisks(); this.sizes();
            }
        };
        this._wrSel();
    },

    _wrSel() {
        const s = this.wr.sel;
        this.$('wr-sel').innerHTML = s ? `<i class="fa-solid fa-compact-disc"></i> <b>${esc(s.name)}</b> · ${esc(App.fmtBytes(s.size))} · ${esc(App.fmtDate(s.mtime))}` +
            `<br><span class="mono faint small">${esc(s.root + '/' + s.path)}</span>` : '<span class="hint">No image chosen.</span>';
    },

    startWrite() {
        const disk = this._disk('wr'), img = this.wr.sel;
        if (!disk || !img) return;
        if (!confirm(`ALL DATA ON ${disk.path} (${App.fmtBytes(disk.size)}) WILL BE DESTROYED.\nWrite ${img.name} onto it?`)) return;
        App.api('/api/sysclone/write', { json: { root: img.root, path: img.path, disk: disk.name, confirm: this.$('wr-confirm').value.trim() } })
            .then(r => { this.$('wr-confirm').value = ''; this._started(r.job); })
            .catch(e => toast(e.message, true));
    },

    // ── Jobs ───────────────────────────────────────────────

    startImage() {
        const body = { folder: this.path || '', extra_mb: parseInt(this.$('img-extra').value, 10) || 0, tag: this.$('img-tag').value.trim(),
                       compress: this.$('img-compress').value, grow: this.$('img-grow').checked };
        if (!confirm('Build a bootable image of the running system on the share?\nIt takes several minutes; the system keeps running.')) return;
        App.api('/api/sysclone/image', { json: body }).then(r => this._started(r.job)).catch(e => toast(e.message, true));
    },

    startClone() {
        const disk = this._disk();
        if (!disk) return;
        if (!confirm(`ALL DATA ON ${disk.path} (${App.fmtBytes(disk.size)}) WILL BE DESTROYED.\nCopy the running system onto it?`)) return;
        const body = { disk: disk.name, confirm: this.$('cl-confirm').value.trim(), extra_mb: parseInt(this.$('cl-extra').value, 10) || 0,
                       whole: this.$('cl-whole').checked, grow: this.$('cl-grow').checked };
        App.api('/api/sysclone/clone', { json: body }).then(r => { this.$('cl-confirm').value = ''; this._started(r.job); })
            .catch(e => toast(e.message, true));
    },

    stop() {
        if (!confirm('Stop the job? An unfinished image is deleted; an unfinished disk will not boot.')) return;
        App.api('/api/sysclone/stop', { json: {} }).then(r => this._job(r.job, false)).catch(e => toast(e.message, true));
    },

    _started(job) {
        this.logNext = 0;
        this.$('cl-log').textContent = '';
        this._job(job, true);
        this._startPoll();
    },

    /** Show a job status; ``full`` = the status carries the log from line 0. */
    _job(job, full) {
        if (!job) return;
        if (this.data) this.data.job = job;
        const box = this.$('cl-job'), log = this.$('cl-log');
        box.hidden = false;
        if (full) { log.textContent = ''; this.logNext = 0; }
        if (job.lines && job.lines.length) {
            const stick = log.scrollTop + log.clientHeight >= log.scrollHeight - 20;
            log.textContent += job.lines.join('\n') + '\n';
            if (stick) log.scrollTop = log.scrollHeight;
        }
        this.logNext = job.next;
        this.$('cl-job-title').textContent = job.title;
        const st = this.$('cl-job-state');
        st.textContent = job.state;
        st.className = 'badge ' + ({ ok: 'badge-ok', error: 'badge-error', stopped: 'badge-error' }[job.state] || 'badge-info');
        const m = Math.floor(job.elapsed / 60), s = Math.floor(job.elapsed % 60);
        this.$('cl-job-time').textContent = `${m}:${String(s).padStart(2, '0')}` + (job.result ? ` · ${job.result}` : '');
        this.$('cl-stop').hidden = job.state !== 'running';
        const p = job.progress, running = job.state === 'running';
        const pct = job.state === 'ok' ? 100 : p ? p.percent : 0;
        this.$('cl-bar').style.width = pct + '%';
        this.$('cl-bar').classList.toggle('err', job.state === 'error' || job.state === 'stopped');
        this.$('cl-prog-text').textContent = p ? `${p.percent}% · ${p.done} · ${p.speed} · ${running ? 'ETA ' + p.eta : ''}` : (running ? 'preparing…' : '');
        if (!running) { this._stopPoll(); this.sizes(); }
    },

    _startPoll() {
        this._stopPoll();
        this.poll = setInterval(() => {
            App.api('/api/sysclone/job?since=' + this.logNext).then(r => {
                const wasRunning = this.data && this.data.job && this.data.job.state === 'running';
                this._job(r.job, false);
                if (wasRunning && r.job && r.job.state !== 'running') {
                    toast(r.job.state === 'ok' ? 'Done: ' + r.job.title : r.job.title + ': ' + r.job.state, r.job.state !== 'ok');
                    Devices.refresh();
                }
            }).catch(() => {});
        }, 1000);
    },

    _stopPoll() { clearInterval(this.poll); this.poll = null; },
});
