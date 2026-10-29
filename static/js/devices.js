/* ==========================================================================
   Devices popup (partials/devices_modal.html) — shell shared by the tabs.
   Each tab lives in its own file (devices_<tab>.js) and registers itself:

     Devices.register({
         id: 'name',          // matches data-tab / #devpane-<id>
         autoMs: 2000,        // periodic refresh while "Auto" is on (0 = never)
         load() {},           // fetch data -> Promise (called by refresh)
         render() {},         // redraw from loaded data (filters changed)
         onShow() {}, onHide() {},   // optional: tab became visible / hidden
     });

   Logged-in only.
   ========================================================================== */

const Devices = {
    HIGHLIGHT_MS: 10000,
    // Paths that come and go on their own (terminals, shared memory): highlighted, no toast.
    QUIET: /^\/dev\/(pts|shm|mqueue)\//,

    tabs: {},
    tab: 'list',
    timer: null,
    changes: [],            // recent {sign, path}
    selected: null,         // key of the device shown in the info panel

    register(tab) { Devices.tabs[tab.id] = tab; },

    current() { return Devices.tabs[Devices.tab]; },

    isOpen() {
        return document.getElementById('devices-overlay').classList.contains('open');
    },

    open() {
        document.getElementById('devices-overlay').classList.add('open');
        Devices._show(Devices.tab);
    },

    close() {
        if (!Devices.isOpen()) return;
        const tab = Devices.current();
        if (tab.canLeave && !tab.canLeave()) return;
        document.getElementById('devices-overlay').classList.remove('open');
        clearInterval(Devices.timer);
        Devices.timer = null;
        if (tab.onHide) tab.onHide();
    },

    setTab(id) {
        if (id === Devices.tab) return;
        const old = Devices.current();
        if (old.canLeave && !old.canLeave()) return;
        if (old.onHide) old.onHide();
        Devices.tab = id;
        Devices._show(id);
    },

    _show(id) {
        const tab = Devices.tabs[id];
        document.querySelectorAll('.dev-tab').forEach(b => b.classList.toggle('active', b.dataset.tab === id));
        document.querySelectorAll('.dev-pane').forEach(p => { p.hidden = p.id !== 'devpane-' + id; });
        document.getElementById('dev-auto-wrap').hidden = !tab.autoMs;
        document.getElementById('dev-summary').textContent = '';
        Devices.hideInfo();
        if (tab.onShow) tab.onShow();
        Devices.render();
        Devices.refresh();
        Devices.setAuto();
    },

    setAuto() {
        clearInterval(Devices.timer);
        Devices.timer = null;
        const tab = Devices.current();
        if (tab.autoMs && document.getElementById('dev-auto').checked && Devices.isOpen()) {
            Devices.timer = setInterval(Devices.refresh, tab.autoMs);
        }
    },

    refresh() {
        const tab = Devices.current();
        if (tab._busy || !tab.load) return;
        tab._busy = true;
        const ico = document.getElementById('dev-refresh-ico');
        ico.classList.add('fa-spin');
        tab.load().then(() => {
            document.getElementById('dev-updated').textContent = 'Updated ' + App.fmtTime();
        }).catch(e => {
            document.getElementById('dev-updated').innerHTML = `<span class="text-error">${esc(e.message)}</span>`;
        }).finally(() => {
            tab._busy = false;
            ico.classList.remove('fa-spin');
        });
    },

    render() {
        const tab = Devices.current();
        if (tab.render) tab.render();
    },

    /** Footer summary; ignored when ``tabId`` is given and that tab is no longer visible. */
    /** Unix time (s) -> "HH:MM:SS.mmm" (24 h) for event and frame tables. */
    fmtMs(t) {
        const d = new Date(t * 1000);
        const p = (n, w = 2) => String(n).padStart(w, '0');
        return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}.${p(d.getMilliseconds(), 3)}`;
    },

    summary(text, tabId) {
        if (tabId && tabId !== Devices.tab) return;
        document.getElementById('dev-summary').textContent = text;
    },

    /**
     * Compare the keys of a fresh list with the previous one (per tab).
     * Returns {key: firstSeenTimestamp} for row highlighting; logs and toasts real changes.
     */
    trackChanges(state, keys, label = k => k) {
        const now = Date.now();
        const current = new Set(keys);
        state.addedAt = state.addedAt || {};
        if (state.known) {
            const added = [...current].filter(k => !state.known.has(k));
            const removed = [...state.known].filter(k => !current.has(k));
            added.forEach(k => { state.addedAt[k] = now; });
            Devices._logChanges(added.map(label), removed.map(label));
        }
        state.known = current;
        return state.addedAt;
    },

    isFresh(state, key) {
        return Date.now() - ((state.addedAt || {})[key] || 0) < Devices.HIGHLIGHT_MS;
    },

    _logChanges(added, removed) {
        const items = added.map(p => ({ sign: '+', path: p })).concat(removed.map(p => ({ sign: '−', path: p })));
        if (!items.length) return;
        Devices.changes = items.concat(Devices.changes).slice(0, 4);
        document.getElementById('dev-changes').innerHTML = Devices.changes.map(c =>
            `<span class="${c.sign === '+' ? 'text-ok' : 'text-error'}">${c.sign}${esc(c.path)}</span>`).join(' ');

        const loud = items.filter(c => !Devices.QUIET.test(c.path));
        if (loud.length === 1) {
            toast((loud[0].sign === '+' ? 'Device added: ' : 'Device removed: ') + loud[0].path, loud[0].sign !== '+');
        } else if (loud.length > 1) {
            toast(`Devices changed: +${added.length} / −${removed.length}`);
        }
    },

    /** Icon class for a device node path (+ optional dir/link type from the /dev tree). */
    icon(path, type) {
        if (type === 'dir') return 'fa-solid fa-folder';
        if (type === 'link') return 'fa-solid fa-link';
        if (type === 'block' || /^\/dev\/(sd|mmcblk|nvme|loop|zram|mtdblock)/.test(path)) return 'fa-solid fa-hard-drive';
        if (type === 'socket') return 'fa-solid fa-network-wired';
        if (type === 'fifo') return 'fa-solid fa-right-left';
        const name = path.split('/').pop();
        if (/^tty/.test(name)) return 'fa-solid fa-terminal';
        if (/^(video|media)/.test(name)) return 'fa-solid fa-video';
        if (/^gpiochip/.test(name)) return 'fa-solid fa-plug';
        if (/^(i2c|spidev)/.test(name)) return 'fa-solid fa-microchip';
        if (/^(hidraw|event|mouse|mice|js)/.test(name)) return 'fa-solid fa-keyboard';
        if (path.startsWith('/dev/snd/')) return 'fa-solid fa-volume-high';
        if (path.startsWith('/dev/bus/usb/')) return 'fa-brands fa-usb';
        if (!path.startsWith('/dev/')) return 'fa-solid fa-network-wired';
        return type && type !== 'char' ? 'fa-solid fa-file' : 'fa-solid fa-cube';
    },

    // ── info panel (device details + udev actions) ─────────────────────────

    /** Show udev details of a node in /dev (``path``) or of a sysfs device (``devpath``). */
    showInfo({ path = '', devpath = '', title = '' }) {
        const box = document.getElementById('dev-info');
        const key = path || devpath;
        Devices.selected = key;
        box.hidden = false;
        const head = `<div class="dev-info-head">
            <i class="${Devices.icon(path || '/sys')} text-ok"></i>
            <span class="mono dev-info-name">${esc(path || devpath.split('/').pop())}</span>
            <span class="spacer"></span>
            <button type="button" class="modal-close" onclick="Devices.hideInfo()" title="Close details">&#215;</button>
        </div>`;
        box.innerHTML = head + '<div class="tbl-empty">Loading…</div>';
        const q = path ? 'path=' + encodeURIComponent(path) : 'devpath=' + encodeURIComponent(devpath);
        App.api('/api/devices/dev/info?' + q).then(info => {
            if (Devices.selected !== key) return;
            Devices._info = info;
            const kv = (k, v) => `<tr><td class="dev-k">${esc(k)}</td><td class="mono">${v}</td></tr>`;
            let rows = title ? kv('Device', esc(title)) : '';
            if (path && info.real !== path) rows += kv('Resolves to', esc(info.real));
            if (info.devpath) rows += kv('Sysfs', esc('/sys' + info.devpath));
            if (info.symlinks.length) rows += kv('Symlinks', info.symlinks.map(esc).join('<br>'));
            const dev = path ? esc(JSON.stringify(info.real)) : 'null';
            const actions = `<div class="dev-info-actions">
                <button type="button" class="btn btn-ghost btn-sm" onclick='Devices.attrs(${dev}, ${esc(JSON.stringify(info.devpath))})'><i class="fa-solid fa-list"></i> Attributes</button>
                ${path ? `<button type="button" class="btn btn-ghost btn-sm" onclick='Devices.testRules(${dev})'><i class="fa-solid fa-flask"></i> Test rules</button>
                <button type="button" class="btn btn-ghost btn-sm" onclick='Devices.triggerDevice(${dev})'><i class="fa-solid fa-bolt"></i> Trigger change</button>
                <button type="button" class="btn btn-success btn-sm" onclick="Devices.ruleFromInfo()"><i class="fa-solid fa-file-circle-plus"></i> New rule…</button>` : ''}
            </div>`;
            const props = Object.entries(info.props).map(([k, v]) => kv(k, esc(v))).join('');
            box.innerHTML = head + actions +
                `<table class="tbl dev-kv">${rows}</table>` +
                (props ? `<div class="dev-info-sub">udev properties</div><table class="tbl dev-kv">${props}</table>`
                       : `<div class="tbl-empty">${esc(info.error || 'No udev properties')}</div>`);
        }).catch(e => {
            box.innerHTML = head + `<div class="tbl-empty text-error">${esc(e.message)}</div>`;
        });
        Devices.render();
    },

    hideInfo() {
        if (!Devices.selected && document.getElementById('dev-info').hidden) return;
        Devices.selected = null;
        Devices._info = null;
        document.getElementById('dev-info').hidden = true;
        Devices.render();
    },

    udevAction(json) {
        return App.api('/api/udev/action', { json });
    },

    attrs(device, devpath) {
        Devices.showText('udevadm info --attribute-walk ' + (device || devpath),
            Devices.udevAction({ action: 'attrs', device, devpath }).then(r => r.output));
    },

    testRules(device) {
        Devices.showText('udevadm test ' + device,
            Devices.udevAction({ action: 'test', device, kind: 'add' }).then(r => r.output));
    },

    triggerDevice(device) {
        if (!confirm(`Trigger a "change" event for ${device}?\nudev re-applies its rules to this device.`)) return;
        Devices.udevAction({ action: 'trigger', kind: 'change', device })
            .then(r => toast(r.output || 'Triggered'))
            .catch(e => toast(e.message, true));
    },

    /** Draft a rule that matches the device in the info panel and open it in the rules editor. */
    ruleFromInfo() {
        const info = Devices._info;
        if (!info) return;
        const p = info.props;
        const name = (p.DEVNAME || info.path).split('/').pop();
        const link = 'my_' + name.replace(/\d+$/, '').replace(/[^\w]/g, '').toLowerCase();
        const match = [`SUBSYSTEM=="${p.SUBSYSTEM || ''}"`];
        if (p.ID_VENDOR_ID && p.ID_MODEL_ID) {
            match.push(`ATTRS{idVendor}=="${p.ID_VENDOR_ID}"`, `ATTRS{idProduct}=="${p.ID_MODEL_ID}"`);
            if (p.ID_SERIAL_SHORT) match.push(`ATTRS{serial}=="${p.ID_SERIAL_SHORT}"`);
            if (p.ID_USB_INTERFACE_NUM) match.push(`ENV{ID_USB_INTERFACE_NUM}=="${p.ID_USB_INTERFACE_NUM}"`);
        } else {
            match.push(`KERNEL=="${name}"`);
        }
        const desc = [p.ID_VENDOR_FROM_DATABASE || p.ID_VENDOR, p.ID_MODEL_FROM_DATABASE || p.ID_MODEL]
            .filter(Boolean).join(' ');
        const text = `# ${info.path}${desc ? ' — ' + desc : ''}\n` +
            `# Stable name /dev/${link} and access for everybody. Check matches with "Attributes".\n` +
            match.join(', ') + `, SYMLINK+="${link}", MODE="0666"\n`;
        Devices.setTab('udev');
        Devices.tabs.udev.newRule(`99-${link.replace(/_/g, '-')}.rules`, text);
    },

    // ── text popup (command output) ────────────────────────────────────────

    showText(title, promise) {
        document.getElementById('dev-text-title').textContent = title;
        const body = document.getElementById('dev-text-body');
        body.textContent = 'Running…';
        document.getElementById('dev-text-overlay').classList.add('open');
        Promise.resolve(promise).then(text => { body.textContent = text || '(no output)'; })
            .catch(e => { body.textContent = e.message; });
    },

    closeText() {
        const ov = document.getElementById('dev-text-overlay');
        if (!ov.classList.contains('open')) return false;
        ov.classList.remove('open');
        return true;
    },
};

App.onEscape(() => { if (!Devices.closeText()) Devices.close(); });
