/* ==========================================================================
   Core helpers shared by every page. Loaded first (see templates/base.html).
   Exposes the global `App` namespace plus the `esc` and `toast` shorthands.
   ========================================================================== */

const App = {
    // Injected by base.html: serviceName, loggedIn, publicServiceActions, loginUrl.
    config: window.APP_CONFIG || {},
    _escapeHandlers: [],

    /** Send the user to the login page and come back afterwards. */
    requireLogin() {
        location.href = App.config.loginUrl + '?next=' +
            encodeURIComponent(location.pathname + location.search);
    },

    /**
     * fetch() wrapper. `opts.json` is sent as a JSON body (method defaults to POST).
     * Resolves with parsed JSON or text; rejects with Error(message) on HTTP errors.
     * A 401 response redirects to the login page.
     */
    api(url, opts = {}) {
        const init = { method: opts.method || (opts.json !== undefined ? 'POST' : 'GET'), headers: {} };
        if (opts.json !== undefined) {
            init.headers['Content-Type'] = 'application/json';
            init.body = JSON.stringify(opts.json);
        }
        return fetch(url, init).then(r => {
            if (r.status === 401) {
                App.requireLogin();
                throw new Error('Login required');
            }
            const isJson = (r.headers.get('Content-Type') || '').includes('application/json');
            return (isJson ? r.json() : r.text()).then(data => {
                if (!r.ok) throw new Error((data && data.error) || data || ('HTTP ' + r.status));
                return data;
            });
        });
    },

    /** Register a callback for the Escape key (close modals, menus...). */
    onEscape(fn) { App._escapeHandlers.push(fn); },

    fmtBytes(b) {
        if (b >= 1073741824) return (b / 1073741824).toFixed(1) + ' GB';
        if (b >= 1048576)    return (b / 1048576).toFixed(1) + ' MB';
        if (b >= 1024)       return (b / 1024).toFixed(0) + ' KB';
        return b + ' B';
    },

    fmtKb(kb) { return App.fmtBytes(kb * 1024); },

    fmtDate(ts) {
        return new Date(ts * 1000).toLocaleString([], {
            year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
    },

    fmtTime(d = new Date()) {
        return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    },
};

/** Escape a value for safe insertion into HTML (text and attribute values). */
function esc(s) {
    if (s == null) return '';
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
                    .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

/** Show a short notification in the bottom-right corner. */
function toast(msg, isError) {
    const el = document.createElement('div');
    el.className = 'toast ' + (isError ? 'error' : 'ok');
    el.textContent = msg;
    document.body.appendChild(el);
    setTimeout(() => { el.style.opacity = '0'; setTimeout(() => el.remove(), 300); }, 2500);
}

document.addEventListener('keydown', e => {
    if (e.key === 'Escape') App._escapeHandlers.forEach(fn => fn(e));
});

// Dismissible flash messages
document.addEventListener('click', e => {
    const btn = e.target.closest('.alert-close');
    if (btn) btn.closest('.alert').remove();
});
