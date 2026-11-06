/* ==========================================================================
   Panel update notice in the top bar (partials/update_button.html). Logged-in only.
   The server fetches the panel repository's upstream in the background (core/updates.py); when HEAD is behind,
   a yellow button appears after the power menu, its popup lists the new commits and offers to update
   (git pull --ff-only) and then to restart the panel.
   ========================================================================== */

const Updates = {
    st: null,
    _timer: 0,
    _done: null,             // result of the last apply: {message, restart}
    POLL_MS: 15 * 60 * 1000, // the server decides when to fetch; this only picks the result up
    CHECKING_MS: 8000,

    init() {
        if (!document.getElementById('upd-wrap')) return;
        this.poll();
        document.addEventListener('click', e => { if (!e.target.closest('.upd-wrap')) this.close(); });
        App.onEscape(() => this.close());
    },

    poll(force) {
        clearTimeout(this._timer);
        App.api('/api/update/status' + (force ? '?force=1' : '')).then(st => {
            this.st = st;
            this.render();
            this._timer = setTimeout(() => this.poll(), st.checking ? this.CHECKING_MS : this.POLL_MS);
        }).catch(() => { this._timer = setTimeout(() => this.poll(), this.POLL_MS); });
    },

    render() {
        const st = this.st, wrap = document.getElementById('upd-wrap');
        const show = !!st && (st.available || !!this._done);
        wrap.hidden = !show;
        if (!show) return this.close();
        document.getElementById('upd-count').textContent = st.behind || '';
        document.getElementById('upd-btn').title = this._done ? 'Panel updated — restart to apply'
            : `Panel update available: ${st.behind} new commit(s) on ${st.upstream}`;
        if (document.getElementById('upd-pop').classList.contains('open')) this._fill();
    },

    _fill() {
        const st = this.st, pop = document.getElementById('upd-pop');
        if (!st) return;
        if (this._done) {
            pop.innerHTML = `<div class="upd-head"><i class="fa-solid fa-circle-check text-ok"></i> Panel updated</div>
                <pre class="upd-out">${esc(this._done.message)}</pre>
                ${this._done.restart ? `<p class="upd-note">Restart the panel to run the new version.</p>` : ''}
                <div class="upd-foot">
                    ${this._done.restart && st.can_restart ? `<button class="btn btn-warning btn-sm" onclick="Updates.restart()"><i class="fa-solid fa-rotate-right"></i> Restart panel</button>` : ''}
                    ${this._done.restart && !st.can_restart ? `<span class="muted">Not running as a service — restart it by hand.</span>` : ''}
                    <span class="spacer"></span>
                    <button class="btn btn-ghost btn-sm" onclick="Updates.close()">Close</button>
                </div>`;
            return;
        }
        const diverged = st.ahead > 0;
        const commits = st.commits.map(c => `<li><code>${esc(c.short)}</code> <span class="upd-subj">${esc(c.subject)}</span>
            <span class="upd-when">${esc(c.author)} · ${esc(c.when)}</span></li>`).join('');
        pop.innerHTML = `<div class="upd-head"><i class="fa-solid fa-triangle-exclamation text-warn"></i> Update available</div>
            <p class="upd-note"><b>${st.behind}</b> new commit(s) on <code>${esc(st.upstream)}</code>
               (local branch <code>${esc(st.branch || 'detached')}</code>).</p>
            <ul class="upd-commits">${commits}</ul>
            ${st.behind > st.commits.length ? `<p class="upd-note muted">…and ${st.behind - st.commits.length} more</p>` : ''}
            ${st.dirty ? `<p class="upd-note text-warn"><i class="fa-solid fa-pen"></i> ${st.dirty} local change(s) — they are kept; the update stops if they touch the same files.</p>` : ''}
            ${diverged ? `<p class="upd-note text-error"><i class="fa-solid fa-code-fork"></i> The branch also has ${st.ahead} local commit(s) — it has diverged, resolve it in Settings → Git.</p>` : ''}
            <div class="upd-foot">
                ${diverged ? `<a class="btn btn-info btn-sm" href="/settings#git"><i class="fa-brands fa-git-alt"></i> Open Git</a>`
                           : `<button class="btn btn-success btn-sm" id="upd-apply" onclick="Updates.apply()"><i class="fa-solid fa-download"></i> Update now</button>`}
                <button class="btn btn-ghost btn-sm" onclick="Updates.poll(true)" title="Fetch again"><i class="fa-solid fa-arrows-rotate"></i></button>
                <span class="spacer"></span>
                <button class="btn btn-ghost btn-sm" onclick="Updates.close()">Later</button>
            </div>`;
    },

    toggle(e) {
        if (e) e.stopPropagation();
        const pop = document.getElementById('upd-pop');
        if (pop.classList.toggle('open')) this._fill();
    },

    close() {
        const pop = document.getElementById('upd-pop');
        if (pop) pop.classList.remove('open');
    },

    apply() {
        const btn = document.getElementById('upd-apply');
        if (btn) { btn.disabled = true; btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Updating…'; }
        App.api('/api/update/apply', { method: 'POST' }).then(d => {
            this._done = { message: d.message, restart: d.restart };
            this.st = d.status;
            this.render();
            this._fill();
            document.dispatchEvent(new CustomEvent('git-changed'));
        }).catch(e => {
            toast(e.message, true);
            if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fa-solid fa-download"></i> Update now'; }
        });
    },

    restart() {
        if (!confirm('Restart the panel now? It is unavailable for a few seconds.')) return;
        App.api('/api/update/restart', { method: 'POST' }).then(d => {
            toast(d.message);
            document.getElementById('upd-pop').innerHTML =
                '<div class="upd-head"><i class="fa-solid fa-spinner fa-spin"></i> Restarting the panel…</div>';
            this._waitBack(Date.now());
        }).catch(e => toast(e.message, true));
    },

    _waitBack(started) {   // reload once the restarted panel (another boot id) answers
        const boot = this.st && this.st.boot;
        setTimeout(() => {
            fetch('/api/update/status', { cache: 'no-store' })
                .then(r => r.status === 401 ? { boot: -1 } : r.json())
                .then(d => { if (d.boot !== boot) location.reload(); else throw 0; })
                .catch(() => { if (Date.now() - started < 90000) this._waitBack(started); else location.reload(); });
        }, 1500);
    },
};

Updates.init();
