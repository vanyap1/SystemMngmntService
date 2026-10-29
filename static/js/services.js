/* ==========================================================================
   Services widget: service selector (#svc-select), start/stop/restart,
   "All Services" modal (partials/services_modal.html), status log colouring.
   Available to anonymous users; actions are limited by App.config.publicServiceActions.

   Page hooks:
     Services.onChange(fn)  - called with the service name when selection changes
                              and shortly after an action on the selected service.
   ========================================================================== */

const Services = {
    all: [],
    sortMode: 'state-running',
    _listeners: [],

    current() {
        const sel = document.getElementById('svc-select');
        return (sel && sel.value) || App.config.serviceName;
    },

    canAct(action) {
        return App.config.loggedIn || (App.config.publicServiceActions || []).includes(action);
    },

    onChange(fn) { Services._listeners.push(fn); },

    _notify() { Services._listeners.forEach(fn => fn(Services.current())); },

    action(action, name) {
        name = name || Services.current();
        return App.api('/api/service/' + action + '?name=' + encodeURIComponent(name), { method: 'POST' })
            .then(d => {
                if (d.success === false) toast(name + ': ' + action + ' failed', true);
                else toast(name + ': ' + action);
                setTimeout(() => {
                    if (name === Services.current()) Services._notify();
                    if (document.getElementById('svc-overlay').classList.contains('open')) Services.load();
                }, 1500);
            })
            .catch(e => toast(e.message || 'Command failed', true));
    },

    select(name) {
        const sel = document.getElementById('svc-select');
        if (sel) {
            if (![...sel.options].some(o => o.value === name)) sel.add(new Option(name, name));
            sel.value = name;
        }
        Services._notify();
    },

    /** Load the service list into the selector and the modal. */
    load() {
        const tbody = document.getElementById('svc-mbody');
        if (tbody && !Services.all.length) tbody.innerHTML = '<tr><td colspan="4" class="tbl-empty">Loading…</td></tr>';
        return App.api('/api/services').then(data => {
            Services.all = data.services || [];
            const sel = document.getElementById('svc-select');
            if (sel) {
                const cur = sel.value || data.default;
                sel.innerHTML = Services.all.map(s =>
                    `<option value="${esc(s.name)}"${s.name === cur ? ' selected' : ''}>${esc(s.name)}</option>`
                ).join('');
                if (cur && sel.value !== cur) {
                    sel.add(new Option(cur, cur), 0);
                    sel.value = cur;
                }
            }
            Services.render();
        }).catch(() => {
            if (tbody) tbody.innerHTML = '<tr><td colspan="4" class="tbl-empty text-error">Failed to load services</td></tr>';
        });
    },

    // ── Modal ──
    openModal() {
        document.getElementById('svc-overlay').classList.add('open');
        const f = document.getElementById('svc-mfilter');
        f.value = '';
        Services.load();
        setTimeout(() => f.focus(), 100);
    },

    closeModal() { document.getElementById('svc-overlay').classList.remove('open'); },

    setSort(mode) {
        Services.sortMode = mode;
        document.getElementById('svc-sort-select').value = mode;
        Services.render();
    },

    toggleSort(col) {
        const m = Services.sortMode;
        const next = {
            state: m === 'state-running' ? 'state-failed' : m === 'state-failed' ? 'state-az' : 'state-running',
            name:  m === 'name-asc' ? 'name-desc' : 'name-asc',
            desc:  m === 'desc-asc' ? 'desc-desc' : 'desc-asc',
        };
        Services.setSort(next[col]);
    },

    _weight(sub) {
        const w = { running: 1, active: 2, reloading: 3, failed: 4, exited: 5, dead: 6, inactive: 7 };
        return sub ? (w[sub.toLowerCase()] ?? 50) : 99;
    },

    _compare(a, b) {
        const byName = a.name.localeCompare(b.name);
        switch (Services.sortMode) {
            case 'state-running': return (Services._weight(a.sub) - Services._weight(b.sub)) || byName;
            case 'state-failed':
                return ((a.sub === 'failed' ? 0 : 1) - (b.sub === 'failed' ? 0 : 1)) ||
                       (Services._weight(b.sub) - Services._weight(a.sub)) || byName;
            case 'state-az':  return (a.sub || '').localeCompare(b.sub || '') || byName;
            case 'name-asc':  return byName;
            case 'name-desc': return -byName;
            case 'desc-asc':  return (a.desc || '').localeCompare(b.desc || '');
            case 'desc-desc': return (b.desc || '').localeCompare(a.desc || '');
        }
        return 0;
    },

    _sortIcons() {
        const m = Services.sortMode;
        const off = '<i class="fa-solid fa-sort" style="opacity:.3"></i>';
        const az = '<i class="fa-solid fa-arrow-down-a-z text-ok"></i>';
        const za = '<i class="fa-solid fa-arrow-up-z-a text-ok"></i>';
        document.getElementById('sort-ico-name').innerHTML = m === 'name-asc' ? az : m === 'name-desc' ? za : off;
        document.getElementById('sort-ico-desc').innerHTML = m === 'desc-asc' ? az : m === 'desc-desc' ? za : off;
        document.getElementById('sort-ico-state').innerHTML =
            m === 'state-running' ? '<i class="fa-solid fa-arrow-down-short-wide text-ok" title="Running first"></i>' :
            m === 'state-failed'  ? '<i class="fa-solid fa-arrow-down-wide-short text-error" title="Failed first"></i>' :
            m === 'state-az'      ? az : off;
    },

    _badge(sub) {
        const cls = sub === 'running' ? 'badge-ok' : sub === 'failed' ? 'badge-error'
                  : sub === 'dead' ? 'badge-muted' : 'badge-info';
        return `<span class="badge ${cls}">${esc(sub)}</span>`;
    },

    _actionButtons(name) {
        const n = esc(JSON.stringify(name));
        const btn = (action, cls, icon, title) => Services.canAct(action)
            ? `<button class="btn ${cls}" title="${title}" onclick="Services.action('${action}', ${n})"><i class="fa-solid ${icon}"></i></button>`
            : '';
        return btn('start', 'btn-start', 'fa-play', 'Start') +
               btn('stop', 'btn-stop', 'fa-stop', 'Stop') +
               btn('restart', 'btn-restart', 'fa-rotate-right', 'Restart');
    },

    render() {
        const tbody = document.getElementById('svc-mbody');
        if (!tbody) return;
        const q = document.getElementById('svc-mfilter').value.toLowerCase().trim();
        const list = Services.all.filter(s => !q ||
            s.name.toLowerCase().includes(q) ||
            (s.desc || '').toLowerCase().includes(q) ||
            (s.sub || '').toLowerCase().includes(q)
        ).sort(Services._compare);

        document.getElementById('svc-count').textContent = list.length;
        Services._sortIcons();
        if (!list.length) {
            tbody.innerHTML = '<tr><td colspan="4" class="tbl-empty">No services found</td></tr>';
            return;
        }
        const cur = Services.current();
        tbody.innerHTML = list.map(s => `
            <tr class="${s.name === cur ? 'svc-cur' : ''}">
                <td><span class="svc-name" onclick="Services.select(${esc(JSON.stringify(s.name))}); Services.closeModal()">${esc(s.name)}</span></td>
                <td>${Services._badge(s.sub)}</td>
                <td><span class="svc-desc" title="${esc(s.desc)}">${esc(s.desc)}</span></td>
                <td><div class="svc-acts">${Services._actionButtons(s.name)}</div></td>
            </tr>`).join('');
    },

    // ── Status helpers ──
    /** 'running' | 'stopped' | '' from `systemctl status` output. */
    stateOf(text) {
        return /active \(running\)/.test(text) ? 'running'
             : /inactive|failed|dead/.test(text) ? 'stopped' : '';
    },

    activeLine(text) {
        return (text.split('\n').find(l => /Active:/.test(l)) || '').trim();
    },

    fetchStatus(name) {
        return App.api('/api/status?name=' + encodeURIComponent(name || Services.current()));
    },

    /** Colourise `systemctl status` output into HTML. */
    colorize(text) {
        const isRunning = /active \(running\)/.test(text);
        return text.split('\n').map(line => {
            if (/^●/.test(line)) {
                const cls = isRunning ? 'lg-run' : /failed|dead/.test(text) ? 'lg-stop' : 'lg-warn';
                return `<span class="${cls}">${esc(line)}</span>`;
            }
            const kv = line.match(/^(\s*)([\w ]+):\s(.*)$/);
            if (kv) {
                let vc = 'lg-val';
                if (kv[2].trim() === 'Active')
                    vc = /active \(running\)/.test(kv[3]) ? 'lg-arun' : /inactive|failed|dead/.test(kv[3]) ? 'lg-fail' : 'lg-val';
                return `${esc(kv[1])}<span class="lg-key">${esc(kv[2])}:</span> <span class="${vc}">${esc(kv[3])}</span>`;
            }
            const jr = line.match(/^([A-Z][a-z]{2}\s+\d+\s+[\d:]+)\s+(\S+)\s+(.*)/);
            if (jr) {
                return `<span class="lg-ts">${esc(jr[1])}</span> <span class="lg-host">${esc(jr[2])}</span> ` +
                       `<span class="lg-val">${esc(jr[3])}</span>`;
            }
            if (/└─|├─|CGroup/.test(line)) return `<span class="lg-dim">${esc(line)}</span>`;
            return esc(line);
        }).join('\n');
    },
};

/** Shorthand for inline handlers: svcAction('restart') acts on the selected service. */
function svcAction(action) { Services.action(action); }

document.addEventListener('DOMContentLoaded', () => {
    const sel = document.getElementById('svc-select');
    if (sel) sel.addEventListener('change', () => Services._notify());
    Services.load();
});
App.onEscape(() => Services.closeModal());
