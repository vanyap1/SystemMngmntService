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

document.addEventListener('click', e => {
    if (!e.target.closest('.power-wrap')) closePowerMenu();
});
App.onEscape(closePowerMenu);
