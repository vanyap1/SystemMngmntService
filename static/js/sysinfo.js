/* ==========================================================================
   System info helpers (logged-in pages). Each page renders /api/sysinfo
   in its own layout using these building blocks.
   ========================================================================== */

const SysInfo = {
    /** Poll /api/sysinfo and pass the data to `render` every `ms` milliseconds. */
    poll(render, ms = 3000) {
        const tick = () => App.api('/api/sysinfo').then(render).catch(() => {});
        tick();
        return setInterval(tick, ms);
    },

    loadPct(d) {
        const la1 = parseFloat((d.load || {})['1'] || 0);
        return Math.min(100, Math.round(la1 / (d.cpu_count || 1) * 100));
    },

    loadText(d) {
        const l = d.load || {};
        return `${esc(l['1'])} &middot; ${esc(l['5'])} &middot; ${esc(l['15'])}`;
    },

    bar(pct) {
        const c = pct >= 85 ? 'crit' : pct >= 65 ? 'warn' : 'ok';
        return `<div class="si-bar"><div class="si-fill ${c}" style="width:${pct}%"></div></div>`;
    },

    parseLsblk(text) {
        const rows = [], tree = /[└├─│]/;
        let last = null;
        for (const line of text.trim().split('\n')) {
            if (!line.trim() || /^NAME\s/i.test(line)) continue;
            const m = line.match(/^([\s└├─│]*\S+)\s+\d+:\d+\s+\d+\s+(\S+)\s+(\d+)\s+(\S+)\s*(.*)/);
            if (m) {
                last = { name: m[1].replace(/[\s└├─│]/g, ''),
                         isChild: tree.test(m[1]), size: m[2], ro: m[3] === '1', type: m[4],
                         mounts: m[5].trim() ? [m[5].trim()] : [] };
                rows.push(last);
            } else if (last) {
                const mp = line.trim();
                if (mp) last.mounts.push(mp);
            }
        }
        return rows;
    },

    lsblkTable(text, compact) {
        const rows = SysInfo.parseLsblk(text || '');
        if (!rows.length) return '<span class="muted">No devices</span>';
        const h = compact ? ['Dev', 'Size', 'Type', 'Mount'] : ['Device', 'Size', 'Type', 'Mountpoints'];
        let t = `<table class="si-tbl"><thead><tr><th>${h[0]}</th><th style="text-align:right">${h[1]}</th>` +
                `<th>${h[2]}</th><th>${h[3]}</th></tr></thead><tbody>`;
        for (const r of rows) {
            const pre = r.isChild ? '<span class="faint">&#x2514; </span>' : '';
            const mnt = r.mounts.map(esc).join('<br>') || '<span class="faint">—</span>';
            const ro  = r.ro ? '<span class="td-ro-badge">RO</span>' : '';
            t += `<tr><td class="td-name${r.isChild ? ' child' : ''}">${pre}${esc(r.name)}</td>` +
                 `<td class="td-size">${esc(r.size)}</td>` +
                 `<td class="td-type">${esc(r.type)}${ro}</td>` +
                 `<td class="td-mount">${mnt}</td></tr>`;
        }
        return t + '</tbody></table>';
    },
};
