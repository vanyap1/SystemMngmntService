/* ==========================================================================
   Devices popup tabs: "Devices" (udev database grouped by kind) and "/dev" (node tree).
   ========================================================================== */

Devices.register({
    id: 'list',
    autoMs: 3000,
    data: null,
    expanded: new Set(),    // groups are collapsed by default

    load() {
        return App.api('/api/devices/list').then(data => {
            this.data = data;
            Devices.trackChanges(this, data.devices.map(d => d.node));
            const real = data.devices.filter(d => d.group !== 'virtual').length;
            Devices.summary(`${data.devices.length} devices · ${real} physical · ` +
                `${data.devices.filter(d => d.group === 'serial').length} serial · ` +
                `${data.devices.filter(d => d.group === 'usb').length} USB`, this.id);
            this.render();
        });
    },

    toggle(key) {
        if (this.expanded.has(key)) this.expanded.delete(key);
        else this.expanded.add(key);
        this.render();
    },

    expandAll(open) {
        this.expanded = open && this.data ? new Set(this.data.groups.map(g => g.key)) : new Set();
        this.render();
    },

    render() {
        const body = document.getElementById('dl-body');
        if (!this.data) return;
        const q = document.getElementById('dl-filter').value.trim().toLowerCase();
        const virtual = document.getElementById('dl-virtual').checked;
        const match = d => !q || [d.node, d.title, d.driver, d.id, d.subsystem, ...d.symlinks]
            .some(v => (v || '').toLowerCase().includes(q));

        const html = this.data.groups.map(g => {
            if (g.key === 'virtual' && !virtual && !q) return '';
            const items = this.data.devices.filter(d => d.group === g.key && match(d));
            if (!items.length) return '';
            const collapsed = !this.expanded.has(g.key) && !q;
            const head = `<div class="dl-group-head" onclick='Devices.tabs.list.toggle(${esc(JSON.stringify(g.key))})'>
                <i class="fa-solid fa-caret-${collapsed ? 'right' : 'down'} dev-caret"></i>
                <i class="${esc(g.icon)} text-ok"></i>
                <b>${esc(g.label)}</b>
                <span class="badge badge-muted">${items.length}</span>
            </div>`;
            if (collapsed) return `<div class="dl-group">${head}</div>`;
            const rows = items.map(d => {
                const key = d.node.startsWith('/dev/') ? d.node : d.devpath;
                const cls = [Devices.isFresh(this, d.node) ? 'dev-new' : '', Devices.selected === key ? 'sel' : ''].join(' ');
                const links = d.symlinks.length
                    ? `<span class="faint small" title="${esc(d.symlinks.join('\n'))}"><i class="fa-solid fa-link"></i> ${d.symlinks.length}</span>` : '';
                return `<tr class="dev-row ${cls}" data-node="${esc(d.node)}" data-devpath="${esc(d.devpath)}" data-title="${esc(d.title)}">
                    <td class="dev-name"><i class="${Devices.icon(d.node)} dev-ico"></i>${esc(d.node)}</td>
                    <td class="dl-title">${d.title ? esc(d.title) : '<span class="faint">—</span>'}</td>
                    <td class="mono small">${esc(d.id)}</td>
                    <td class="small muted">${esc(d.driver)}</td>
                    <td class="small faint">${esc(d.subsystem)}</td>
                    <td>${links}</td>
                </tr>`;
            }).join('');
            return `<div class="dl-group">${head}<table class="tbl dev-tbl dl-tbl"><tbody>${rows}</tbody></table></div>`;
        }).join('');
        body.innerHTML = html || '<div class="tbl-empty">Nothing matches the filter</div>';
    },

    onShow() {
        if (this._bound) return;
        this._bound = true;
        document.getElementById('dl-body').addEventListener('click', e => {
            const tr = e.target.closest('tr[data-node]');
            if (!tr) return;
            const node = tr.dataset.node;
            if (node.startsWith('/dev/')) Devices.showInfo({ path: node, title: tr.dataset.title });
            else Devices.showInfo({ devpath: tr.dataset.devpath, title: tr.dataset.title });
        });
    },
});


Devices.register({
    id: 'dev',
    autoMs: 2000,
    // Node groups for the selector, matched against the full path.
    GROUPS: {
        serial: n => /^\/dev\/(tty(S|USB|ACM|AMA|FIQ|GS)\d+|serial\/.+)$/.test(n.path),
        usb:    n => /^\/dev\/(bus\/usb\/.+|ttyUSB\d+|ttyACM\d+|serial\/.+)$/.test(n.path),
        video:  n => /^\/dev\/(video\d+|media\d+|v4l\/.+|dri\/.+)$/.test(n.path),
        i2c:    n => /^\/dev\/i2c-\d+$/.test(n.path),
        spi:    n => /^\/dev\/spidev/.test(n.path),
        gpio:   n => /^\/dev\/gpiochip\d+$/.test(n.path),
        block:  n => n.type === 'block' || n.path.startsWith('/dev/disk/'),
        input:  n => /^\/dev\/(input\/.+|hidraw\d+)$/.test(n.path),
        sound:  n => n.path.startsWith('/dev/snd/'),
    },
    tree: [],
    nodes: {},              // path -> node
    expanded: new Set(),

    load() {
        return App.api('/api/devices/dev').then(data => {
            this.tree = data.tree || [];
            this.nodes = {};
            const walk = list => list.forEach(n => {
                this.nodes[n.path] = n;
                if (n.children) walk(n.children);
            });
            walk(this.tree);
            Devices.trackChanges(this, Object.keys(this.nodes));

            const counts = { char: 0, block: 0, link: 0, dir: 0 };
            Object.values(this.nodes).forEach(n => { if (n.type in counts) counts[n.type]++; });
            Devices.summary(`${data.count} entries · ${counts.char} char · ${counts.block} block · ` +
                `${counts.link} links · ${counts.dir} dirs` + (data.truncated ? ' · list truncated' : ''), this.id);
            this.render();
        });
    },

    _match(n, q, group) {
        if (group && !this.GROUPS[group](n)) return false;
        if (!q) return true;
        return n.path.toLowerCase().includes(q) || (n.target || '').toLowerCase().includes(q) ||
               (n.dev || '') === q;
    },

    /** Flatten the tree into [node, depth, open] rows honouring filter and expanded dirs. */
    _rows(nodes, depth, q, group, out) {
        const filtering = q || group;
        for (const n of nodes) {
            const isDir = n.type === 'dir';
            if (!filtering) {
                const open = isDir && this.expanded.has(n.path);
                out.push([n, depth, open]);
                if (open) this._rows(n.children, depth + 1, q, group, out);
                continue;
            }
            const self = this._match(n, q, group);
            // A matching directory shows its whole subtree; otherwise only matching descendants.
            const sub = isDir ? this._rows(n.children, depth + 1, self ? '' : q, self ? '' : group, []) : [];
            if (self || sub.length) {
                out.push([n, depth, isDir]);
                out.push(...sub);
            }
        }
        return out;
    },

    render() {
        const tbody = document.getElementById('dev-tbody');
        if (!this.known) return;
        const q = document.getElementById('dt-filter').value.trim().toLowerCase();
        const group = document.getElementById('dt-group').value;
        const rows = this._rows(this.tree, 0, q, group, []);
        if (!rows.length) {
            tbody.innerHTML = '<tr><td colspan="5" class="tbl-empty">Nothing matches the filter</td></tr>';
            return;
        }
        tbody.innerHTML = rows.map(([n, depth, open]) => {
            const isDir = n.type === 'dir';
            const cls = ['dev-row', 'dev-' + n.type, Devices.isFresh(this, n.path) ? 'dev-new' : '',
                         n.path === Devices.selected ? 'sel' : ''].join(' ');
            const caret = isDir
                ? `<i class="fa-solid fa-caret-${open ? 'down' : 'right'} dev-caret"></i>`
                : '<span class="dev-caret"></span>';
            const icon = isDir && open ? 'fa-solid fa-folder-open' : Devices.icon(n.path, n.type);
            const target = n.type === 'link'
                ? ` <span class="dev-target${n.broken ? ' text-error' : ''}">→ ${esc(n.target)}</span>` : '';
            const count = isDir ? ` <span class="faint small">(${n.children.length})</span>` : '';
            return `<tr class="${cls}" data-path="${esc(n.path)}">
                <td class="dev-name" style="padding-left:${10 + depth * 18}px">${caret}<i class="${icon} dev-ico"></i>${esc(n.name)}${count}${target}</td>
                <td><span class="dev-type">${esc(n.type)}</span></td>
                <td class="mono">${esc(n.dev || '')}</td>
                <td class="mono faint">${esc(n.mode)}</td>
                <td class="small muted">${esc(n.owner)}:${esc(n.group)}</td>
            </tr>`;
        }).join('');
    },

    onShow() {
        if (this._bound) return;
        this._bound = true;
        document.getElementById('dev-tbody').addEventListener('click', e => {
            const tr = e.target.closest('tr[data-path]');
            const n = tr && this.nodes[tr.dataset.path];
            if (!n) return;
            if (n.type === 'dir') {
                if (document.getElementById('dt-filter').value || document.getElementById('dt-group').value) return;
                if (this.expanded.has(n.path)) this.expanded.delete(n.path);
                else this.expanded.add(n.path);
                this.render();
                return;
            }
            Devices.showInfo({ path: n.path });
        });
    },
});
