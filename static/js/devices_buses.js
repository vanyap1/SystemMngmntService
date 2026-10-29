/* ==========================================================================
   Devices popup tab "Buses": USB topology (like lsusb -t), PCI (lspci -k), I2C adapters.
   ========================================================================== */

Devices.register({
    id: 'buses',
    autoMs: 3000,
    data: null,
    expanded: new Set(),    // sections (usb/pci/i2c), USB devpaths and I2C buses; all collapsed by default

    load() {
        return App.api('/api/devices/buses').then(data => {
            this.data = data;
            Devices.trackChanges(this, data.usb.map(d => d.devpath), dp => {
                const d = data.usb.find(x => x.devpath === dp) || (this._prev || []).find(x => x.devpath === dp);
                return d ? `USB ${d.vid}:${d.pid} ${d.product || ''}`.trim() : dp;
            });
            this._prev = data.usb;
            const ext = data.usb.filter(d => d.parent).length;
            Devices.summary(`USB: ${data.usb.length - ext} root hubs, ${ext} devices · PCI: ${data.pci.length} · ` +
                `I²C: ${data.i2c.length} buses, ${data.i2c.reduce((s, b) => s + b.clients.length, 0)} clients`, this.id);
            this.render();
        });
    },

    toggle(key) {
        if (this.expanded.has(key)) this.expanded.delete(key);
        else this.expanded.add(key);
        this.render();
    },

    expandAll(open) {
        this.expanded = new Set();
        if (open && this.data) {
            ['usb', 'pci', 'i2c'].forEach(k => this.expanded.add(k));
            this.data.usb.forEach(d => this.expanded.add(d.devpath));
            this.data.i2c.forEach(b => this.expanded.add('i2c-' + b.bus));
        }
        this.render();
    },

    rawLsusb() {
        Devices.showText('lsusb; lsusb -t', App.api('/api/devices/usb/verbose').then(r => r.text));
    },

    verbose(bus, dev) {
        Devices.showText(`lsusb -v -s ${bus}:${dev}`,
            App.api(`/api/devices/usb/verbose?bus=${bus}&dev=${dev}`).then(r => r.text));
    },

    _speed(mbps) {
        const n = parseFloat(mbps);
        if (!n) return '';
        return n >= 1000 ? (n / 1000) + ' Gb/s' : n + ' Mb/s';
    },

    _usbRows(q) {
        const usb = this.data.usb;
        const match = d => !q || [d.vid + ':' + d.pid, d.vendor, d.product, d.manufacturer, d.product_str,
            d.serial, d.class, ...d.interfaces.map(i => i.driver + ' ' + i.class), ...d.nodes]
            .some(v => (v || '').toLowerCase().includes(q));
        // With a filter: keep matching devices and their ancestors.
        const keep = new Set();
        usb.filter(match).forEach(d => {
            for (let x = d; x; x = usb.find(p => p.devpath === x.parent)) keep.add(x.devpath);
        });
        const rows = [];
        const walk = (parent, depth) => usb.filter(d => d.parent === parent && keep.has(d.devpath))
            .sort((a, b) => a.kernel.localeCompare(b.kernel, undefined, { numeric: true }))
            .forEach(d => {
                const kids = usb.filter(x => x.parent === d.devpath && keep.has(x.devpath)).length;
                const open = kids > 0 && (q || this.expanded.has(d.devpath));
                rows.push([d, depth, kids, open]);
                if (open) walk(d.devpath, depth + 1);
            });
        walk(null, 0);
        return rows;
    },

    render() {
        const body = document.getElementById('db-body');
        if (!this.data) return;
        const q = document.getElementById('db-filter').value.trim().toLowerCase();

        const usbRows = this._usbRows(q).map(([d, depth, kids, open]) => {
            const root = !d.parent;
            const ifaces = d.interfaces.map(i =>
                `<span class="db-iface" title="${esc(i.name)}">${esc(i.class)}${i.driver ? ' → <b>' + esc(i.driver) + '</b>' : ' <span class="text-warn">(no driver)</span>'}</span>`).join('');
            const nodes = d.nodes.map(n =>
                `<button type="button" class="db-node" onclick='Devices.showInfo({path: ${esc(JSON.stringify(n))}})'>${esc(n)}</button>`).join('');
            const name = [d.vendor, d.product].filter(Boolean).join(' ') || d.product_str || '—';
            return `<tr class="${Devices.isFresh(this, d.devpath) ? 'dev-new' : ''}${root ? ' db-root' : ''}">
                <td class="mono small nowrap" style="padding-left:${10 + depth * 22}px">
                    ${depth ? '<span class="db-branch">└</span>' : ''}${kids
                        ? `<i class="fa-solid fa-caret-${open ? 'down' : 'right'} dev-caret db-toggle" onclick='Devices.tabs.buses.toggle(${esc(JSON.stringify(d.devpath))})' title="${kids} device(s)"></i>`
                        : '<span class="dev-caret"></span>'}<i class="fa-brands fa-usb ${root ? 'faint' : 'text-ok'}"></i>
                    ${String(d.bus).padStart(3, '0')}:${String(d.dev).padStart(3, '0')}
                    <span class="faint">${esc(d.kernel)}</span></td>
                <td class="mono">${esc(d.vid)}:${esc(d.pid)}</td>
                <td><div>${esc(name)}</div>
                    ${d.serial && !root ? `<div class="faint small mono">S/N ${esc(d.serial)}</div>` : ''}</td>
                <td class="small nowrap">${esc(this._speed(d.speed))}<div class="faint">USB ${esc(d.version)}</div></td>
                <td class="small">${ifaces}${nodes ? `<div class="db-nodes">${nodes}</div>` : ''}</td>
                <td class="nowrap"><button type="button" class="btn-icon" title="lsusb -v" onclick="Devices.tabs.buses.verbose(${d.bus}, ${d.dev})"><i class="fa-solid fa-magnifying-glass"></i></button>
                    <button type="button" class="btn-icon" title="udev details" onclick='Devices.showInfo({devpath: ${esc(JSON.stringify(d.devpath))}, title: ${esc(JSON.stringify(name))}})'><i class="fa-solid fa-circle-info"></i></button></td>
            </tr>`;
        }).join('');

        const pci = this.data.pci.filter(p => !q || Object.values(p).some(v => String(v).toLowerCase().includes(q)))
            .map(p => `<tr>
                <td class="mono">${esc(p.slot)}</td>
                <td class="small muted">${esc(p.class)}</td>
                <td>${esc(p.vendor)}<div class="small">${esc(p.device)}</div></td>
                <td class="small">${p.driver ? '<b>' + esc(p.driver) + '</b>' : '<span class="text-warn">no driver</span>'}</td>
            </tr>`).join('');

        const i2c = this.data.i2c.map(b => {
            const clients = b.clients.filter(c => !q || [c.addr, c.name, c.driver, b.name, 'i2c-' + b.bus]
                .some(v => (v || '').toLowerCase().includes(q)));
            if (q && !clients.length && !(b.name.toLowerCase().includes(q) || ('i2c-' + b.bus).includes(q))) return '';
            const open = q || this.expanded.has('i2c-' + b.bus);
            const rows = !open ? '' : clients.map(c => `<tr>
                <td></td>
                <td class="mono">${esc(c.addr)}</td>
                <td class="mono">${esc(c.name)}</td>
                <td class="small">${c.driver ? '<b>' + esc(c.driver) + '</b>' : '<span class="text-warn">no driver</span>'}</td>
            </tr>`).join('');
            return `<tr class="db-root">
                <td class="mono nowrap">${b.clients.length
                    ? `<i class="fa-solid fa-caret-${open ? 'down' : 'right'} dev-caret db-toggle" onclick='Devices.tabs.buses.toggle(${esc(JSON.stringify('i2c-' + b.bus))})'></i>`
                    : '<span class="dev-caret"></span>'}<i class="fa-solid fa-microchip text-ok"></i> i2c-${b.bus}</td>
                <td colspan="2">${esc(b.name)} ${b.node ? `<button type="button" class="db-node" onclick='Devices.showInfo({path: ${esc(JSON.stringify(b.node))}})'>${esc(b.node)}</button>` : ''}</td>
                <td class="small faint">${b.clients.length} client${b.clients.length === 1 ? '' : 's'}</td>
            </tr>${rows}`;
        }).join('');

        const section = (key, icon, title, count, note, table) => {
            const open = q || this.expanded.has(key);
            return `<div class="db-section">
                <div class="dl-group-head" onclick='Devices.tabs.buses.toggle(${esc(JSON.stringify(key))})'>
                    <i class="fa-solid fa-caret-${open ? 'down' : 'right'} dev-caret"></i>
                    <i class="${icon} text-ok"></i><b>${title}</b><span class="badge badge-muted">${count}</span>
                    <span class="faint small">${note}</span></div>
                ${open ? table : ''}</div>`;
        };
        const usbCount = this.data.usb.length;
        const i2cCount = this.data.i2c.length;
        body.innerHTML =
            section('usb', 'fa-brands fa-usb', 'USB', usbCount, 'topology like lsusb -t · 🔍 = lsusb -v',
                usbRows ? `<table class="tbl dev-tbl"><thead><tr><th style="width:190px">Bus:Dev</th><th style="width:90px">ID</th><th>Device</th><th style="width:90px">Speed</th><th>Interfaces → driver / nodes</th><th style="width:60px"></th></tr></thead><tbody>${usbRows}</tbody></table>`
                        : '<div class="tbl-empty">No USB devices match</div>') +
            section('pci', 'fa-solid fa-memory', 'PCI', this.data.pci.length, 'lspci -k',
                pci ? `<table class="tbl dev-tbl"><thead><tr><th style="width:90px">Slot</th><th style="width:240px">Class</th><th>Device</th><th style="width:130px">Driver</th></tr></thead><tbody>${pci}</tbody></table>`
                    : '<div class="tbl-empty">No PCI devices</div>') +
            section('i2c', 'fa-solid fa-microchip', 'I²C', i2cCount, 'devices declared in the device tree / bound by drivers — the bus is not scanned',
                i2c ? `<table class="tbl dev-tbl"><thead><tr><th style="width:190px">Bus</th><th style="width:90px">Address</th><th>Name</th><th style="width:180px">Driver</th></tr></thead><tbody>${i2c}</tbody></table>`
                    : '<div class="tbl-empty">No I²C buses</div>');
    },
});
