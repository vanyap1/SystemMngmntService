/* ==========================================================================
   Settings → Video (routes/video.py /api/video/sources, core/video_sources.py): network cameras (RTSP / HTTP).
   The password is write-only: the server returns only password_set; an empty field keeps the stored one.
   ========================================================================== */

const VideoSources = {
    rows: [],
    dirty: false,
    loaded: false,

    $(id) { return document.getElementById(id); },

    load() {
        VideoDevices.load();
        if (this.loaded && this.dirty) return;
        App.api('/api/video/sources').then(d => {
            this.rows = d.sources.map(s => Object.assign({ password: '' }, s));
            this.loaded = true;
            this.setDirty(false);
            this.render();
        }).catch(e => toast(e.message, true));
    },

    render() {
        const tr = (s, i) => `<tr data-i="${i}">
            <td><input class="input input-sm mono" data-f="name" value="${esc(s.name)}" placeholder="gate"></td>
            <td><input class="input input-sm mono" data-f="url" value="${esc(s.url)}" placeholder="rtsp://192.168.1.108:554/cam/realmonitor?channel=1&subtype=1">
                <div class="vs-res" data-res="${i}">${s.result || ''}</div></td>
            <td><input class="input input-sm" data-f="username" value="${esc(s.username)}" autocomplete="off"></td>
            <td><input class="input input-sm" type="password" data-f="password" value="${esc(s.password)}" autocomplete="new-password"
                       placeholder="${s.password_set ? '(saved)' : ''}"></td>
            <td><select class="input input-sm" data-f="transport">${['tcp', 'udp'].map(t => `<option${t === s.transport ? ' selected' : ''}>${t}</option>`).join('')}</select></td>
            <td><button class="btn btn-ghost btn-sm" type="button" data-act="test" title="Open the stream and read its format (saves first)"><i class="fa-solid fa-plug"></i> Test</button>
                <button class="btn-icon git-danger" type="button" data-act="del" title="Remove"><i class="fa-regular fa-trash-can"></i></button></td></tr>`;
        const body = this.$('vs-rows');
        body.innerHTML = this.rows.map(tr).join('') || '<tr><td colspan="6" class="tbl-empty">No network cameras — Add camera.</td></tr>';
        body.oninput = e => {
            const r = e.target.closest('[data-i]'), f = e.target.dataset.f;
            if (!r || !f) return;
            this.rows[+r.dataset.i][f] = e.target.value;
            this.setDirty(true);
        };
        body.onclick = e => {
            const b = e.target.closest('[data-act]');
            if (!b) return;
            const i = +b.closest('[data-i]').dataset.i;
            if (b.dataset.act === 'del') { this.rows.splice(i, 1); this.setDirty(true); this.render(); }
            else this.test(i);
        };
    },

    add() {
        this.rows.push({ name: 'cam' + (this.rows.length + 1), url: '', username: '', password: '', transport: 'tcp', password_set: false });
        this.setDirty(true);
        this.render();
    },

    setDirty(on) {
        this.dirty = on;
        this.$('vs-save').disabled = !on;
        this.$('vs-dirty').textContent = on ? 'unsaved changes' : '';
        this.$('vs-dirty').className = on ? 'hint text-warn' : 'hint';
    },

    save() {
        const body = { sources: this.rows.map(s => ({ name: s.name.trim(), url: s.url.trim(), username: s.username,
                                                      password: s.password, transport: s.transport })) };
        return App.api('/api/video/sources', { json: body }).then(d => {
            const results = Object.fromEntries(this.rows.map(r => [r.name, r.result]));
            this.rows = d.sources.map(s => Object.assign({ password: '', result: results[s.name] }, s));
            this.setDirty(false);
            this.render();
            VideoDevices.load();
            toast('Cameras saved');
        }).catch(e => { toast(e.message, true); throw e; });
    },

    test(i) {
        const go = () => {
            const s = this.rows[i];
            s.result = '<span class="faint"><i class="fa-solid fa-spinner fa-spin"></i> connecting…</span>';
            this.render();
            App.api(`/api/video/sources/${encodeURIComponent(s.name)}/test`, { method: 'POST' }).then(r => {
                s.result = r.ok ? `<span class="text-ok"><i class="fa-solid fa-check"></i> ${esc(r.video)}</span>`
                                : `<span class="text-error"><i class="fa-solid fa-xmark"></i> ${esc(r.error)}</span>`;
                this.render();
            }).catch(e => { s.result = `<span class="text-error">${esc(e.message)}</span>`; this.render(); });
        };
        if (this.dirty) this.save().then(go).catch(() => {}); else go();
    },
};


/* Devices (local + network) with an inline preview. */
const VideoDevices = {
    list: [],
    sid: null,

    $(id) { return document.getElementById(id); },

    load() {
        App.api('/api/video_devices').then(d => {
            this.list = d.devices;
            const cur = this.$('vd-device').value;
            this.$('vd-rows').innerHTML = this.list.map(x => `<tr>
                <td class="mono">${esc(x.path)}</td>
                <td>${esc(x.name || '')}</td><td>${x.network ? 'network' : 'local'}</td>
                <td><button class="btn btn-ghost btn-sm" type="button" data-use="${esc(x.path)}"><i class="fa-solid fa-eye"></i> Preview</button></td></tr>`).join('') ||
                '<tr><td colspan="4" class="tbl-empty">No video devices</td></tr>';
            this.$('vd-rows').onclick = e => { const b = e.target.closest('[data-use]'); if (b) { this.pick(b.dataset.use).then(() => this.preview(true)); } };
            this.$('vd-device').innerHTML = this.list.map(x => `<option value="${esc(x.path)}">${esc(x.label)}</option>`).join('');
            if (this.list.some(x => x.path === cur)) this.$('vd-device').value = cur;
            if (this.$('vd-device').value) this.pick(this.$('vd-device').value);
        }).catch(e => toast(e.message, true));
    },

    pick(device, res) {
        this.stop();
        this.$('vd-device').value = device;
        return App.api('/api/video_resolutions?device=' + encodeURIComponent(device)).then(d => {
            const list = d.resolutions;
            this.$('vd-res').innerHTML = list.map(r => `<option>${esc(r)}</option>`).join('');
            this.$('vd-res').value = [res, 'source', '640x480'].find(r => r && list.includes(r)) || list[0];
        });
    },

    preview(force) {
        if (this.sid && !force) return this.stop();
        this.stop();
        const dev = this.$('vd-device').value;
        if (!dev) return;
        this.sid = 'settings_' + Date.now();
        this.$('vd-view').hidden = false;
        this.$('vd-img').src = `/api/video_feed?device=${encodeURIComponent(dev)}&size=${encodeURIComponent(this.$('vd-res').value)}&sid=${this.sid}`;
        this.$('vd-prev').innerHTML = '<i class="fa-solid fa-stop"></i> Stop';
    },

    stop() {
        if (!this.sid) return;
        this.$('vd-img').src = '';
        this.$('vd-view').hidden = true;
        App.api('/api/video_stop', { json: { stream_id: this.sid } }).catch(() => {});
        this.sid = null;
        this.$('vd-prev').innerHTML = '<i class="fa-solid fa-play"></i> Preview';
    },
};
window.addEventListener('pagehide', () => { if (VideoDevices.sid) navigator.sendBeacon('/api/video_stop', new Blob([JSON.stringify({ stream_id: VideoDevices.sid })], { type: 'application/json' })); });
