/* ==========================================================================
   Settings → Display (routes/display.py, core/display_ui.py): which Kivy script from UI/ runs on the device
   screen and how (output, size, rotation, scale, input). Enable / script apply at once; the other fields with
   Apply. The process status and its log are polled while the tab is visible.
   ========================================================================== */

const DisplaySettings = {
    timer: null,
    dirty: false,
    scripts: [],
    bgs: [],
    bg: '',
    FIELDS: { mode: 'dsp-mode', x_display: 'dsp-xdisplay', width: 'dsp-width', height: 'dsp-height', rotation: 'dsp-rotation',
              scale: 'dsp-scale', fps: 'dsp-fps', cursor: 'dsp-cursor', bg_dim: 'dsp-bgdim' },
    CHECKS: { enabled: 'dsp-enabled', fullscreen: 'dsp-fullscreen', touch: 'dsp-touch', mouse: 'dsp-mouse' },

    $(id) { return document.getElementById(id); },

    visible(on) {
        clearInterval(this.timer);
        this.timer = null;
        if (!on) return;
        this.load();
        this.timer = setInterval(() => this.poll(), 2000);
    },

    load() {
        return Promise.all([App.api('/api/display/scripts'), App.api('/api/display/backgrounds')]).then(([d, b]) => {
            this.scripts = d.scripts;
            this.bgs = b.backgrounds;
            return this.poll(true);
        }).catch(e => toast(e.message, true));
    },

    poll(fill) {
        return App.api('/api/display/status').then(st => {
            if (fill || !this.dirty) this._fill(st.settings);
            this._status(st);
        }).catch(() => {});
    },

    _fill(s) {
        const sel = this.$('dsp-script');
        const names = this.scripts.map(x => x.name);
        if (s.script && !names.includes(s.script)) names.push(s.script);
        sel.innerHTML = names.map(n => `<option value="${esc(n)}">${esc(n)}</option>`).join('') || '<option value="">no scripts in UI/</option>';
        Object.entries(this.FIELDS).forEach(([k, id]) => { this.$(id).value = s[k]; });
        Object.entries(this.CHECKS).forEach(([k, id]) => { this.$(id).checked = !!s[k]; });
        sel.value = s.script;
        this.bg = s.background || '';
        this._bgs();
        this.dimInput(true);
        this._desc();
        this.dirty = false;
        this._dirtyUi();
    },

    _desc() {
        const sc = this.scripts.find(x => x.name === this.$('dsp-script').value);
        this.$('dsp-script-desc').textContent = sc ? sc.description : 'Not found in UI/';
    },

    _collect() {
        const out = { script: this.$('dsp-script').value, background: this.bg };
        Object.entries(this.FIELDS).forEach(([k, id]) => { out[k] = this.$(id).value; });
        Object.entries(this.CHECKS).forEach(([k, id]) => { out[k] = this.$(id).checked; });
        return out;
    },

    changed() { this.dirty = true; this._dirtyUi(); },

    /** Preview tiles of UI/backgrounds/ (+ "none"); a click applies the picture at once. */
    _bgs() {
        const tile = (name, inner) => `<button type="button" class="dsp-bg${name === this.bg ? ' on' : ''}" data-bg="${esc(name)}" title="${esc(name || 'no background')}">${inner}</button>`;
        this.$('dsp-bgs').innerHTML = tile('', '<span class="dsp-bg-none"><i class="fa-solid fa-ban"></i> none</span>') +
            this.bgs.map(b => tile(b.name, `<img loading="lazy" src="/api/display/background/${encodeURIComponent(b.name)}" alt="">` +
                                            `<span class="dsp-bg-cap">${esc(b.name)}</span>`)).join('') +
            (this.bg && !this.bgs.some(b => b.name === this.bg) ? tile(this.bg, `<span class="dsp-bg-none text-error">${esc(this.bg)} — missing</span>`) : '');
        this.$('dsp-bg-name').textContent = this.bg ? '— ' + this.bg : '— none';
        this.$('dsp-bgs').onclick = e => {
            const t = e.target.closest('[data-bg]');
            if (!t || t.dataset.bg === this.bg) return;
            this.bg = t.dataset.bg;
            this._bgs();
            this.apply();
        };
    },

    dimInput(quiet) {
        this.$('dsp-bgdim-val').textContent = `— ${this.$('dsp-bgdim').value} %`;
        if (!quiet) this.changed();
    },

    _dirtyUi() {
        this.$('dsp-apply').disabled = !this.dirty;
        this.$('dsp-dirty').textContent = this.dirty ? 'Changed — Apply restarts the script with the new settings' : '';
        this.$('dsp-dirty').className = this.dirty ? 'hint text-warn' : 'hint';
    },

    apply() {
        this._desc();
        const btn = this.$('dsp-apply');
        btn.disabled = true;
        return App.api('/api/display/settings', { json: this._collect() }).then(r => {
            this.dirty = false;
            this._fill(r.settings);
            this._status(r.status);
            toast(r.settings.enabled ? `Display: ${r.settings.script}` : 'Display UI off');
        }).catch(e => { toast(e.message, true); this._dirtyUi(); });
    },

    restart() {
        App.api('/api/display/restart', { method: 'POST' }).then(r => { this._status(r.status); toast('Restarting the script'); })
            .catch(e => toast(e.message, true));
    },

    /** GPU acceleration and connected screens; a warning when Kivy would draw on the CPU. */
    _gpu(g, s) {
        const outs = (g.outputs || []).filter(o => o.status === 'connected');
        const screen = outs.length ? outs.map(o => `${esc(o.name)} ${esc(o.mode || '')}`).join(', ')
                                   : '<span class="text-warn">no connected screen found</span>';
        const nodes = (g.nodes || []).map(n => `${esc(n.node)} (${esc(n.driver || '?')})`).join(', ');
        let cls = 'ok', icon = 'fa-microchip', text;
        if (g.software) {
            cls = 'err'; icon = 'fa-triangle-exclamation';
            text = `<b>No GPU acceleration</b> — OpenGL renderer <code>${esc(g.renderer)}</code> draws on the CPU: the screen will be slow ` +
                   `and load the processor. Lower <i>Max frames / s</i> to 10–15, avoid big charts / pictures, or install the board's Mesa GPU driver.`;
        } else if (!g.hw) {
            cls = 'warn'; icon = 'fa-triangle-exclamation';
            text = `<b>No GPU found</b> (no <code>/dev/dri/renderD*</code> with a GPU driver) — Kivy will draw on the CPU (llvmpipe) and the ` +
                   `screen will be slow. Lower <i>Max frames / s</i> to 10–15; check the kernel GPU driver (lima / panfrost / v3d) and Mesa.`;
        } else {
            text = `<b>GPU acceleration</b>: ${g.renderer ? `<code>${esc(g.renderer)}</code>` : nodes} ` +
                   (g.renderer ? '' : '<span class="faint">(the renderer shows after the first start of a script)</span>');
        }
        this.$('dsp-gpu').className = 'dsp-gpu ' + cls;
        this.$('dsp-gpu').innerHTML = `<i class="fa-solid ${icon}"></i><div>${text}<br><span class="faint">screen: ${screen}` +
            (nodes ? ` · render nodes: ${nodes}` : '') + '</span></div>';
    },

    _status(st) {
        const badge = this.$('dsp-state');
        const cls = { running: 'badge-ok', off: 'badge-muted', waiting: 'badge-info', error: 'badge-error' }[st.state] || 'badge-info';
        badge.className = 'badge ' + cls;
        badge.textContent = st.state;
        const up = st.uptime != null ? ` · up ${Math.floor(st.uptime / 60)}:${String(Math.floor(st.uptime % 60)).padStart(2, '0')}` : '';
        this.$('dsp-proc').textContent = st.pid
            ? `${st.script} · pid ${st.pid} · ${st.mode} · as ${st.user}${up} · restarts ${st.restarts}`
            : (st.next_start_in != null ? `next start in ${st.next_start_in} s` : '');
        const notes = [];
        notes.push(st.kivy ? `Kivy ${esc(st.kivy)}` : '<span class="text-error">Kivy is not installed</span> — <code>sudo ./install.sh display</code>');
        notes.push(st.x_running ? `X server on ${esc(st.settings.x_display)}: running` : 'no X server — output straight to the screen (DRM/KMS)');
        if (!st.supervisor) notes.push('<span class="text-warn">the display supervisor runs only in the panel service</span>');
        if (st.error) notes.push(`<span class="text-error">${esc(st.error)}</span>`);
        if (st.last_exit && !st.pid) notes.push(`last exit: ${esc(st.last_exit.script || '')} code ${esc(String(st.last_exit.code))} after ${esc(String(st.last_exit.ran))} s`);
        this.$('dsp-env').innerHTML = '<i class="fa-solid fa-circle-info"></i><span>' + notes.join(' · ') + '</span>';
        this._gpu(st.gpu || {}, st.settings);
        const log = this.$('dsp-log');
        const stick = log.scrollTop + log.clientHeight >= log.scrollHeight - 20;
        log.textContent = (st.log || []).join('\n') || '(no output yet)';
        if (stick) log.scrollTop = log.scrollHeight;
    },
};

document.getElementById('dsp-script').addEventListener('change', () => DisplaySettings._desc());
DisplaySettings.visible(!document.getElementById('pane-display').hidden);
