/* ==========================================================================
   Panel update notice in the top bar (partials/update_button.html). Logged-in only.
   The server fetches the panel repository's upstream in the background (core/updates.py); when HEAD is behind,
   a yellow button appears after the power menu, its popup lists the new commits and offers to update.
   The update itself runs in the progress window (partials/update_modal.html, Updates.openFlow — also used by
   Git → Update panel): plan (fetch, what is in the way) → confirm → background job with its steps
   (/api/update/job) → offer to restart the panel (never automatic) → reload when the new instance answers.
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
            ${diverged ? `<p class="upd-note text-error"><i class="fa-solid fa-code-fork"></i> The branch also has ${st.ahead} local commit(s) — it has diverged; the update keeps them on a backup branch.</p>` : ''}
            <div class="upd-foot">
                <button class="btn btn-success btn-sm" onclick="Updates.openFlow()"><i class="fa-solid fa-download"></i> Update…</button>
                ${diverged ? `<a class="btn btn-info btn-sm" href="/settings#git"><i class="fa-brands fa-git-alt"></i> Open Git</a>` : ''}
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

    // ── Progress window ───────────────────────────────────────

    flow: null,              // {phase: plan|confirm|job|done|restart|error, plan, job, error}
    JOB_MS: 700,

    _el(id) { return document.getElementById(id); },

    /** Open the update window: show a running job, else fetch and show what the update brings. */
    openFlow() {
        this.close();
        this._el('upd-overlay').classList.add('open');
        this.flow = { phase: 'plan' };
        this._draw();
        App.api('/api/update/job').then(j => {
            if (j.running) { this.flow = { phase: 'job', job: j }; this._draw(); return this._pollJob(); }
            return this._plan();
        }).catch(e => this._fail(e.message));
    },

    closeFlow() {
        if (this.flow && ['job', 'restart'].includes(this.flow.phase)) return toast('The update is still running', true);
        this._el('upd-overlay').classList.remove('open');
        clearTimeout(this._jobTimer);
        this.flow = null;
    },

    _plan() {
        this.flow = { phase: 'plan' };
        this._draw();
        return App.api('/api/update/plan', { method: 'POST' })
            .then(p => { this.flow = { phase: 'confirm', plan: p }; this._draw(); })
            .catch(e => this._fail(e.message));
    },

    _fail(msg) { this.flow = Object.assign({}, this.flow, { phase: 'error', error: msg }); this._draw(); },

    start() {
        const p = this.flow && this.flow.plan;
        App.api('/api/update/job', { json: { confirm: !!(p && p.issues.length) } }).then(j => {
            this.flow = { phase: 'job', plan: p, job: j };
            this._draw();
            this._pollJob();
        }).catch(e => this._fail(e.message));
    },

    _pollJob() {
        clearTimeout(this._jobTimer);
        this._jobTimer = setTimeout(() => App.api('/api/update/job').then(j => {
            if (!this.flow) return;
            this.flow.job = j;
            if (j.running) { this._draw(); return this._pollJob(); }
            if (j.plan) { this.flow = { phase: 'confirm', plan: j.plan }; return this._draw(); }   // changed meanwhile
            this.flow.phase = j.error ? 'error' : 'done';
            this.flow.error = j.error;
            this._draw();
            document.dispatchEvent(new CustomEvent('git-changed'));
            if (typeof Git !== 'undefined' && Git.el && Git.load) Git.load();
            this.poll();
        }).catch(() => this._pollJob()), this.JOB_MS);
    },

    _steps(j) {
        if (!j || !j.steps.length) return '';
        const icon = { run: 'fa-solid fa-spinner fa-spin', ok: 'fa-solid fa-check', err: 'fa-solid fa-xmark' };
        return '<ul class="upd-steps">' + j.steps.map(s => `<li class="${s.state}"><i class="${icon[s.state] || icon.ok}"></i>` +
            `<span>${esc(s.text)}</span><span class="upd-t">${s.t.toFixed(1)} s</span>` +
            s.details.map(d => `<div class="upd-det">${esc(d)}</div>`).join('') + '</li>').join('') + '</ul>';
    },

    _alert(kind, icon, html) {
        return `<div class="git-alert ${kind}"><i class="fa-solid ${icon}"></i><div class="git-alert-text">${html}</div></div>`;
    },

    _commits(p) {
        if (!p.commits.length) return '';
        return '<ul class="upd-commits">' + p.commits.map(c => `<li><code>${esc(c.short)}</code> <span class="upd-subj">${esc(c.subject)}</span>
            <span class="upd-when">${esc(c.author)} · ${esc(c.when)}</span></li>`).join('') + '</ul>' +
            (p.behind > p.commits.length ? `<p class="upd-note muted">…and ${p.behind - p.commits.length} more</p>` : '');
    },

    _draw() {
        const f = this.flow, body = this._el('upd-flow-body'), foot = this._el('upd-flow-foot');
        if (!f || !body) return;
        const btn = (cls, onclick, icon, label) => `<button class="btn ${cls} btn-sm" onclick="${onclick}"><i class="fa-solid ${icon}"></i> ${label}</button>`;
        const close = btn('btn-ghost', 'Updates.closeFlow()', 'fa-xmark', 'Close');
        const p = f.plan, j = f.job;
        let h = '', ft = '';
        if (p) h += `<div class="upd-route"><code>${esc(p.branch)}</code> ← <code>${esc(p.upstream)}</code></div>`;
        if (f.phase === 'plan') {
            h += `<div class="upd-head"><i class="fa-solid fa-spinner fa-spin"></i> Fetching the upstream and checking local changes…</div>`;
            ft = '<span class="spacer"></span>' + close;
        } else if (f.phase === 'confirm') {
            const files = (title, a) => a.length ? `<div>${esc(title)}:<ul>${a.slice(0, 12).map(x => `<li>${esc(x)}</li>`).join('')}` +
                (a.length > 12 ? `<li>… +${a.length - 12}</li>` : '') + '</ul></div>' : '';
            if (!p.behind && !p.issues.length) {
                h += this._alert('info', 'fa-circle-check', `<b>Up to date</b><span>No new commits on ${esc(p.upstream)}.</span>`);
                ft = btn('btn-ghost', 'Updates._plan()', 'fa-arrows-rotate', 'Check again') + '<span class="spacer"></span>' + close;
            } else {
                h += `<div class="upd-head"><span>${p.behind ? `<b>${p.behind}</b> new commit(s)` : 'No new commits'}</span></div>` + this._commits(p);
                if (p.issues.length) {
                    h += this._alert('warn', 'fa-triangle-exclamation', '<b>Local changes are in the way</b>' +
                        p.issues.map(i => `<span>• ${esc(i)}</span>`).join('') + files('Modified files', p.changed) +
                        files('Untracked files that get overwritten', p.in_way) +
                        '<span>They are saved first (backup branch / git stash / copies in .git).</span>');
                }
                if (p.kept.length) h += `<p class="upd-note"><i class="fa-solid fa-lock"></i> Kept as they are: ${p.kept.map(esc).join(', ')} (settings of this host).</p>`;
                h += `<p class="upd-note muted">The panel keeps running during the update; you are asked to restart it at the end.</p>`;
                ft = btn(p.issues.length ? 'btn-warning' : 'btn-success', 'Updates.start()', 'fa-download',
                         p.issues.length ? 'Update anyway' : 'Update now') + '<span class="spacer"></span>' +
                     btn('btn-ghost', 'Updates.closeFlow()', 'fa-xmark', 'Cancel');
            }
        } else if (f.phase === 'job') {
            h += `<div class="upd-head"><i class="fa-solid fa-spinner fa-spin"></i> Updating…</div>` + this._steps(j);
            ft = '<span class="spacer"></span><span class="muted small">Please wait</span>';
        } else if (f.phase === 'done') {
            const r = j.result;
            h += this._steps(j);
            h += this._alert('info', 'fa-circle-check', `<b>${esc(r.message.split(' · ')[0])}</b>` +
                 (r.notes || []).map(n => `<span>${esc(n)}</span>`).join(''));
            if (r.syntax_errors && r.syntax_errors.length) {
                h += this._alert('err', 'fa-bug', '<b>The new code has errors — the panel may not start after a restart</b><ul>' +
                     r.syntax_errors.map(e => `<li>${esc(e)}</li>`).join('') + '</ul>');
            }
            if (!r.changed) {
                h += `<p class="upd-note">The code did not change — no restart is needed.</p>`;
                ft = '<span class="spacer"></span>' + close;
            } else if (r.can_restart) {
                h += `<p class="upd-note">Restart <code>${esc(r.unit || 'the panel service')}</code> to run the new version (the panel is unavailable for a few seconds).</p>`;
                ft = btn(r.syntax_errors && r.syntax_errors.length ? 'btn-danger' : 'btn-warning', 'Updates.restart()', 'fa-rotate-right',
                         r.syntax_errors && r.syntax_errors.length ? 'Restart anyway' : 'Restart now') +
                     '<span class="spacer"></span>' + btn('btn-ghost', 'Updates.closeFlow()', 'fa-clock', 'Later');
            } else {
                h += `<p class="upd-note text-warn">The panel does not run as a systemd service — restart it by hand to run the new version.</p>`;
                ft = '<span class="spacer"></span>' + close;
            }
        } else if (f.phase === 'restart') {
            h += this._steps(j) + `<div class="upd-head"><i class="fa-solid fa-spinner fa-spin"></i> ${esc(f.note || 'Restarting the panel…')}</div>` +
                 `<p class="upd-note muted">The page reloads when the new instance answers.</p>`;
        } else if (f.phase === 'error') {
            h += this._steps(j) + this._alert('err', 'fa-circle-xmark', `<b>Update failed</b><span>${esc(f.error || '')}</span>`) +
                 (j ? '<p class="upd-note">The panel keeps running the code it had; local changes saved so far are listed above.</p>' : '');
            ft = btn('btn-ghost', 'Updates._plan()', 'fa-arrows-rotate', 'Try again') + '<span class="spacer"></span>' + close;
        }
        body.innerHTML = h;
        foot.innerHTML = ft;
        foot.hidden = !ft;
    },

    apply() { this.openFlow(); },

    restart() {
        const inFlow = !!(this.flow && this.flow.phase === 'done');
        if (!inFlow && !confirm('Restart the panel now? It is unavailable for a few seconds.')) return;
        App.api('/api/update/restart', { method: 'POST' }).then(d => {
            toast(d.message);
            if (inFlow) { this.flow.phase = 'restart'; this.flow.note = d.message; this._draw(); }
            const pop = document.getElementById('upd-pop');
            if (pop) pop.innerHTML = '<div class="upd-head"><i class="fa-solid fa-spinner fa-spin"></i> Restarting the panel…</div>';
            this._waitBack(Date.now(), this.flow && this.flow.job ? this.flow.job.boot : null);
        }).catch(e => toast(e.message, true));
    },

    _waitBack(started, boot) {   // reload once the restarted panel (another boot id) answers
        if (boot == null) boot = this.st && this.st.boot;
        const sec = Math.round((Date.now() - started) / 1000);
        if (this.flow && this.flow.phase === 'restart' && sec >= 3) {
            this.flow.note = `Waiting for the panel to come back… ${sec} s`;
            this._draw();
        }
        setTimeout(() => {
            fetch('/api/update/status', { cache: 'no-store' })
                .then(r => r.status === 401 ? { boot: -1 } : r.json())
                .then(d => { if (d.boot !== boot) location.reload(); else throw 0; })
                .catch(() => { if (Date.now() - started < 90000) this._waitBack(started, boot); else location.reload(); });
        }, 1500);
    },
};

Updates.init();
