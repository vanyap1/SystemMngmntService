/* ==========================================================================
   Power menu in the top bar (partials/power_menu.html). Logged-in only.
   ========================================================================== */

function togglePowerMenu(e) {
    if (e) e.stopPropagation();
    document.getElementById('power-dropdown').classList.toggle('open');
}

function closePowerMenu() {
    const d = document.getElementById('power-dropdown');
    if (d) d.classList.remove('open');
}

function confirmPower(action) {
    const isReboot = action === 'reboot';
    if (!confirm(isReboot ? 'Are you sure you want to reboot the system?'
                          : 'Are you sure you want to shut down the system?')) return;
    closePowerMenu();
    toast(isReboot ? 'Rebooting system...' : 'Shutting down system...');
    App.api('/api/power/' + action, { method: 'POST' })
        .then(d => toast(d.message || 'Command sent'))
        .catch(e => toast(e.message, true));
}

/** Restart the panel's own systemd unit (/api/update/restart) and reload the page once the new instance answers. */
function restartPanel() {
    if (!confirm('Restart the panel service?\nThe web interface is unavailable for a few seconds; a running test, terminal or\ndevice display script is stopped.')) return;
    closePowerMenu();
    let boot = null;
    App.api('/api/update/status').then(st => { boot = st.boot; }).catch(() => {})
        .then(() => App.api('/api/update/restart', { method: 'POST' }))
        .then(d => {
            toast(d.message || 'Restarting…');
            const started = Date.now();
            const wait = () => setTimeout(() => {
                fetch('/api/update/status', { cache: 'no-store' })
                    .then(r => r.status === 401 ? { boot: -1 } : r.json())
                    .then(s => { if (s.boot !== boot) location.reload(); else throw 0; })
                    .catch(() => { if (Date.now() - started < 90000) wait(); else location.reload(); });
            }, 1500);
            wait();
        })
        .catch(e => toast(e.message, true));
}

document.addEventListener('click', e => {
    if (!e.target.closest('.power-wrap')) closePowerMenu();
});
App.onEscape(closePowerMenu);
