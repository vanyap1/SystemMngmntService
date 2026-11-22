/* ==========================================================================
   Settings → Network (overview): interactive map of the board's networks from /api/netcfg/map (core/netap.py).

   Layout, left to right:  Internet · gateways · uplink interfaces · BOARD · other interfaces · their peers
   (AP clients, the local network of an interface without a default route). Uplinks = interfaces with a default
   route (lowest metric = the one in use, drawn thicker). Nodes are absolutely positioned HTML boxes, links are an
   SVG path layer under them in the same coordinate system. Click a node → details + actions below the map.
   Refreshed every LIVE_MS while the tab is visible and "live" is ticked.
   ========================================================================== */

const NetMap = {
    LIVE_MS: 5000,
    W: 160, GAP: 30, ROW: 74, PEER: 46, PAD: 12,
    data: null,
    nodes: {},
    _shown: false,
    _timer: null,
    _sel: '',

    $(id) { return document.getElementById(id); },

    visible(on) {
        this._shown = on;
        clearInterval(this._timer);
        if (!on) return;
        this.load();
        this.live(this.$('nm-live').checked);
    },

    live(on) {
        clearInterval(this._timer);
        if (on && this._shown) this._timer = setInterval(() => this.load(), this.LIVE_MS);
    },

    load() {
        return App.api('/api/netcfg/map').then(d => { this.data = d; this.render(); })
            .catch(e => { this.$('nm-canvas').innerHTML = `<div class="text-error">✗ ${esc(e.message)}</div>`; });
    },

    // ── Model → nodes / edges ──────────────────────────────────

    _icon(kind) {
        return { ethernet: 'fa-ethernet', wifi: 'fa-wifi', can: 'fa-car-battery', bridge: 'fa-diagram-project',
                 none: 'fa-plug', loopback: 'fa-rotate' }[kind] || 'fa-plug';
    },

    _netOf(cidr) {
        const [ip, p] = cidr.split('/');
        const n = NetAP._n(ip);
        if (n === null) return cidr;
        const mask = (0xffffffff << (32 - +p)) >>> 0;
        return NetAP._s((n & mask) >>> 0) + '/' + p;
    },

    build() {
        const d = this.data;
        const routeOf = {};
        d.routes.forEach((r, i) => { if (!(r.dev in routeOf)) routeOf[r.dev] = Object.assign({ primary: i === 0 }, r); });
        const ap = d.ap;
        const left = [], right = [];
        d.links.forEach(l => (routeOf[l.name] ? left : right).push(l));
        const rank = l => (l.up || l.connected ? 0 : 2) + (l.managed ? 0 : 1);
        right.sort((a, b) => rank(a) - rank(b) || a.name.localeCompare(b.name));
        left.sort((a, b) => (routeOf[a.name].metric || 0) - (routeOf[b.name].metric || 0));

        const nodes = [], edges = [];
        const live = l => l.connected || (l.up && l.ip4.length);
        // Left rows: internet ← gateway ← iface
        left.forEach(l => {
            const r = routeOf[l.name];
            const wifiNet = l.kind === 'wifi' && l.mode === 'client' ? l.connection : '';
            nodes.push({ id: 'gw:' + l.name, col: 'gw', side: 'L', row: l.name, kind: 'gw', title: wifiNet ? 'Wi-Fi ' + wifiNet : 'Gateway',
                         sub: r.gateway || 'direct', icon: wifiNet ? 'fa-wifi' : 'fa-route', data: { route: r, link: l } });
            edges.push({ a: 'gw:' + l.name, b: 'net', on: true, main: r.primary });
            edges.push({ a: 'if:' + l.name, b: 'gw:' + l.name, on: live(l), main: r.primary });
        });
        if (left.length) nodes.push({ id: 'net', col: 'net', kind: 'net', title: 'Internet / upstream', sub: d.routes.length + ' default route(s)', icon: 'fa-globe', data: {} });
        // Interfaces
        [...left.map(l => [l, 'L']), ...right.map(l => [l, 'R'])].forEach(([l, side]) => {
            const isAp = ap && ap.ifname === l.name && l.mode === 'ap';
            const you = d.client_device === l.name;
            nodes.push({ id: 'if:' + l.name, col: side === 'L' ? 'ifL' : 'ifR', side, row: l.name, kind: 'if', link: l,
                         title: l.name, icon: isAp ? 'fa-tower-broadcast' : this._icon(l.kind), on: live(l), you,
                         badge: isAp ? 'AP' : l.kind === 'wifi' && l.mode === 'client' ? 'client' : '',
                         sub: l.ip4[0] || (l.managed ? l.nm_state : l.state) || '—',
                         sub2: isAp ? 'SSID ' + ap.ssid : l.connection || (l.managed ? '' : l.kind + (l.managed ? '' : ' · not managed by NM')),
                         data: l });
            edges.push({ a: 'if:' + l.name, b: 'board', on: live(l), main: side === 'L' && routeOf[l.name].primary });
            // Peers on the right side
            if (side === 'R' && isAp) {
                (ap.clients || []).forEach(c => {
                    nodes.push({ id: 'cl:' + c.mac, col: 'peer', side, row: l.name, kind: 'client', title: c.name || c.hostname || c.mac,
                                 sub: c.ip || '—', meta: c.signal !== null && c.signal !== undefined ? c.signal + ' dBm' : c.online ? '' : 'offline',
                                 icon: 'fa-mobile-screen', on: c.online, pin: !!c.reserved, data: c });
                    edges.push({ a: 'cl:' + c.mac, b: 'if:' + l.name, on: c.online, dash: !c.online });
                });
                if (!(ap.clients || []).length) {
                    nodes.push({ id: 'pool:' + l.name, col: 'peer', side, row: l.name, kind: 'lan', title: 'No clients',
                                 sub: `pool ${ap.start} – ${ap.end.split('.').pop()}`, icon: 'fa-users', on: false, data: ap });
                    edges.push({ a: 'pool:' + l.name, b: 'if:' + l.name, on: false, dash: true });
                }
            } else if (side === 'R' && live(l) && l.ip4.length && l.kind !== 'can') {
                nodes.push({ id: 'lan:' + l.name, col: 'peer', side, row: l.name, kind: 'lan', title: 'Local network',
                             sub: this._netOf(l.ip4[0]), icon: 'fa-network-wired', on: true, data: l });
                edges.push({ a: 'lan:' + l.name, b: 'if:' + l.name, on: true });
            }
        });
        nodes.push({ id: 'board', col: 'board', kind: 'board', title: d.hostname, icon: 'fa-microchip',
                     sub: `${d.links.filter(live).length} of ${d.links.length} interfaces up`, data: {} });
        return { nodes, edges, left, right };
    },

    layout(m) {
        const cols = [];
        if (m.left.length) cols.push('net', 'gw', 'ifL');
        cols.push('board');
        if (m.right.length) cols.push('ifR');
        if (m.nodes.some(n => n.col === 'peer')) cols.push('peer');
        const x = {};
        cols.forEach((c, i) => { x[c] = this.PAD + i * (this.W + this.GAP); });
        const rowH = side => (side === 'L' ? m.left : m.right).map(l => {
            const peers = m.nodes.filter(n => n.col === 'peer' && n.row === l.name).length;
            return Math.max(this.ROW, peers * this.PEER + 10);
        });
        const hl = rowH('L'), hr = rowH('R');
        const sum = a => a.reduce((s, v) => s + v, 0);
        const total = Math.max(sum(hl), sum(hr), 150);
        const place = (list, hs) => {
            const out = {};
            let y = this.PAD + (total - sum(hs)) / 2;
            list.forEach((l, i) => { out[l.name] = { top: y, h: hs[i] }; y += hs[i]; });
            return out;
        };
        const rows = Object.assign(place(m.left, hl), place(m.right, hr));
        const peerIdx = {};
        m.nodes.forEach(n => {
            n.x = x[n.col];
            n.w = this.W;
            if (n.kind === 'board') { n.h = Math.max(total - 16, 110); n.y = this.PAD + (total - n.h) / 2; return; }
            if (n.kind === 'net') { n.h = 58; n.y = this.PAD + total / 2 - 29; return; }
            const r = rows[n.row];
            if (n.col === 'peer') {
                const cnt = m.nodes.filter(p => p.col === 'peer' && p.row === n.row).length;
                const i = peerIdx[n.row] = (peerIdx[n.row] || 0) + 1;
                n.h = 38;
                n.y = r.top + (r.h - cnt * this.PEER) / 2 + (i - 1) * this.PEER + (this.PEER - n.h) / 2;
            } else {
                n.h = 60;
                n.y = r.top + (r.h - n.h) / 2;
            }
        });
        return { width: this.PAD * 2 + cols.length * this.W + (cols.length - 1) * this.GAP, height: total + this.PAD * 2 };
    },

    // ── Render ─────────────────────────────────────────────────

    render() {
        const d = this.data;
        const m = this.build();
        const size = this.layout(m);
        const byId = Object.fromEntries(m.nodes.map(n => [n.id, n]));
        this.nodes = byId;
        const paths = m.edges.map(e => {
            const a = byId[e.a], b = byId[e.b];
            if (!a || !b) return '';
            const [l, r] = a.x < b.x ? [a, b] : [b, a];
            const x1 = l.x + l.w, x2 = r.x;
            const clamp = (v, n) => Math.max(n.y + 14, Math.min(n.y + n.h - 14, v));
            const yl = l.h > 70 ? clamp(r.y + r.h / 2, l) : l.y + l.h / 2;
            const yr = r.h > 70 ? clamp(l.y + l.h / 2, r) : r.y + r.h / 2;
            const mx = (x1 + x2) / 2;
            const cls = 'nm-edge' + (e.on ? ' on' : '') + (e.main ? ' main' : '') + (e.dash || !e.on ? ' dash' : '');
            return `<path class="${cls}" d="M${x1},${yl} C${mx},${yl} ${mx},${yr} ${x2},${yr}"/>`;
        }).join('');
        const html = m.nodes.map(n => {
            const cls = ['nm-node', 'nm-' + n.kind, n.on === false ? 'off' : n.on ? 'on' : '', n.you ? 'you' : '', this._sel === n.id ? 'sel' : ''].join(' ');
            return `<div class="${cls}" style="left:${n.x}px;top:${n.y}px;width:${n.w}px;height:${n.h}px" onclick="NetMap.select(${esc(JSON.stringify(n.id))})" title="${esc(n.title)}">
                <i class="fa-solid ${n.icon} nm-ico"></i>
                <div class="nm-txt"><b>${esc(n.title)}${n.badge ? ` <span class="nm-badge">${esc(n.badge)}</span>` : ''}${n.pin ? ' <i class="fa-solid fa-thumbtack nm-pin" title="Reserved address"></i>' : ''}${n.meta ? ` <span class="nm-meta">${esc(n.meta)}</span>` : ''}</b>
                    <span class="mono">${esc(n.sub || '')}</span>${n.sub2 ? `<span>${esc(n.sub2)}</span>` : ''}
                    ${n.kind === 'board' ? this._boardInfo() : ''}</div>
                ${n.you ? '<span class="nm-you" title="This page reaches the panel through this interface"><i class="fa-solid fa-location-dot"></i></span>' : ''}
            </div>`;
        }).join('');
        this.$('nm-canvas').innerHTML = (d.nm_error ? `<div class="text-warn small nm-err">NetworkManager: ${esc(d.nm_error)}</div>` : '') +
            `<div class="nm-stage" style="width:${size.width}px;height:${size.height}px">
                <svg class="nm-svg" width="${size.width}" height="${size.height}">${paths}</svg>${html}</div>`;
        if (this._sel && byId[this._sel]) this.detail(byId[this._sel]); else if (this._sel) { this._sel = ''; this.$('nm-detail').hidden = true; }
    },

    _boardInfo() {
        const d = this.data;
        const rows = d.routes.slice(0, 3).map(r => `<span class="small" title="default route">⇠ ${esc(r.gateway || 'direct')} · ${esc(r.dev)}</span>`).join('');
        return `<span class="nm-board-info">${rows || '<span class="muted small">no default route</span>'}
            ${d.ap && d.ap.active ? `<span class="small">AP <b>${esc(d.ap.ssid)}</b> · ${(d.ap.clients || []).filter(c => c.online).length} client(s)</span>` : ''}</span>`;
    },

    select(id) {
        this._sel = this._sel === id ? '' : id;
        this.$('nm-canvas').querySelectorAll('.nm-node').forEach(el => el.classList.remove('sel'));
        if (!this._sel) { this.$('nm-detail').hidden = true; return; }
        this.render();
    },

    detail(n) {
        const box = this.$('nm-detail'), d = this.data;
        const kv = rows => `<div class="nc-kv">${rows.filter(r => r[1] !== undefined && r[1] !== '').map(([k, v]) => `<span class="muted">${k}</span><span class="mono">${v}</span>`).join('')}</div>`;
        let body = '', acts = '';
        if (n.kind === 'if') {
            const l = n.data;
            const isAp = d.ap && d.ap.ifname === l.name;
            body = kv([['Type', esc(l.kind) + (l.managed ? '' : ' (not managed by NetworkManager)')],
                       ['State', esc(l.managed ? l.nm_state : l.state)], ['Connection', esc(l.connection || '')],
                       ['Mode', esc(l.mode || '')], ['IPv4', l.ip4.map(esc).join('<br>') || '—'], ['Gateway', esc(l.gateway || '')],
                       ['DNS', esc((l.dns || []).join(', '))], ['MAC', esc(l.mac)], ['MTU', esc(String(l.mtu || ''))],
                       ['Autoconnect', l.managed && l.uuid ? (l.autoconnect ? 'yes' : 'no') : '']]);
            if (l.managed && l.uuid && !(isAp && l.mode === 'ap')) acts += `<button class="btn btn-ghost btn-sm" type="button" onclick="NetMap.go('network-conn', () => NetCfg.edit(${esc(JSON.stringify(l.uuid))}))"><i class="fa-solid fa-pen"></i> Configure</button>`;
            if (l.kind === 'wifi') acts += `<a class="btn btn-ghost btn-sm" href="#network-ap"><i class="fa-solid fa-tower-broadcast"></i> Client / access point</a>`;
            if (l.managed) acts += `<a class="btn btn-ghost btn-sm" href="#network-conn"><i class="fa-solid fa-list"></i> Interfaces &amp; Wi-Fi</a>`;
        } else if (n.kind === 'client') {
            const c = n.data;
            body = kv([['Name', esc(c.name || c.hostname || '—')], ['IP', esc(c.ip || '—')], ['MAC', esc(c.mac)],
                       ['Reserved', esc(c.reserved || 'no')], ['Signal', c.signal !== null && c.signal !== undefined ? c.signal + ' dBm' : ''],
                       ['Bitrate', esc(c.bitrate || '')], ['Connected', c.online ? NetAP._dur(c.connected) : 'offline'],
                       ['Lease left', c.expires_in !== null ? NetAP._dur(c.expires_in) : ''],
                       ['Traffic', c.rx_bytes !== null && c.rx_bytes !== undefined ? `↓ ${App.fmtBytes(c.tx_bytes)} · ↑ ${App.fmtBytes(c.rx_bytes)}` : '']]);
            acts = `<button class="btn btn-ghost btn-sm" type="button" onclick="NetMap.go('network-ap', () => NetAP.${c.reserved ? `editRes(NetAP.data.reservations.findIndex(r => r.mac === ${esc(JSON.stringify(c.mac))}))` : `reserve(${esc(JSON.stringify(c.mac))})`})"><i class="fa-solid fa-thumbtack"></i> ${c.reserved ? 'Edit reservation' : 'Reserve IP'}</button>`;
        } else if (n.kind === 'gw') {
            const r = n.data.route;
            body = kv([['Interface', esc(r.dev)], ['Gateway', esc(r.gateway || 'direct')], ['Metric', esc(String(r.metric || 0))],
                       ['In use', r.primary ? 'yes — lowest metric' : 'backup']]);
        } else if (n.kind === 'lan') {
            body = n.data.ssid ? kv([['SSID', esc(n.data.ssid)], ['Address', esc(n.data.address + '/' + n.data.prefix)], ['Pool', esc(n.data.start + ' – ' + n.data.end)],
                                     ['Reservations', String(n.data.reservations)]])
                               : kv([['Network', esc(n.sub)], ['Interface', esc(n.data.name)], ['Board address', esc(n.data.ip4.join(', '))]]);
            if (n.data.ssid) acts = '<a class="btn btn-ghost btn-sm" href="#network-ap"><i class="fa-solid fa-sliders"></i> DHCP settings</a>';
        } else if (n.kind === 'board') {
            body = kv([['Host', esc(d.hostname)], ['Default routes', d.routes.map(r => esc(`${r.gateway || 'direct'} via ${r.dev} (metric ${r.metric || 0})`)).join('<br>') || 'none'],
                       ['You come through', esc(d.client_device || '?')]]);
        } else if (n.kind === 'net') {
            body = '<div class="muted small">Everything beyond the default gateways. Traffic leaves through the route with the lowest metric (thick line).</div>';
        }
        box.innerHTML = `<div class="card-head"><i class="fa-solid ${n.icon}"></i> ${esc(n.title)}<span class="spacer"></span>${acts}
            <button class="btn-icon" type="button" onclick="NetMap.select(${esc(JSON.stringify(n.id))})" title="Close"><i class="fa-solid fa-xmark"></i></button></div>
            <div class="card-body">${body}</div>`;
        box.hidden = false;
    },

    /** Switch to another network sub-tab and run fn once its data is there. */
    go(tab, fn) {
        location.hash = tab;
        const obj = tab === 'network-ap' ? NetAP : NetCfg;
        let n = 0;
        const t = setInterval(() => {
            if (obj.data || ++n > 40) { clearInterval(t); if (obj.data) fn(); }
        }, 100);
    },
};

document.addEventListener('netcfg-changed', () => { if (NetMap._shown) NetMap.load(); });
