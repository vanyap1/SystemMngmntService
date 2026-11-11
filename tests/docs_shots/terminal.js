// HW Utils → Terminal: TCP client on the JSON telemetry of tests/fake_devices.py (:5555)
Devices.open(); Devices.setTab('tty');
setTimeout(async () => {
    const t = Devices.tabs.tty, p = t.prof();
    Object.assign(p.conn, { transport: 'tcp', host: '127.0.0.1', netport: '5555' });
    p.eol = 'crlf';
    p.commands = [
        { name: 'PSU voltage', data: 'MEAS:VOLT?', eol: 'crlf', wait: true, period: 1000, timer: false },
        { name: 'PSU current', data: 'MEAS:CURR?', eol: 'crlf', wait: true, period: 1000, timer: false },
        { name: 'status', data: 'STATUS', eol: 'crlf', wait: false, period: 2000, timer: false },
    ];
    p.note = 'Charger telemetry on TCP :5555 (one JSON object per line).\n' +
             'Bench PSU (SCPI, one connection per command): [[MEAS:VOLT?]]  [[MEAS:CURR?]]  [[OUTP ON]]';
    t.render();
    await t.connect();
    t.macRes = [{ ok: true, oneshot: true, text: '12.0153\n', ms: 6, end: 'closed', at: Date.now() },
                { ok: true, oneshot: true, text: '0.4087\n', ms: 5, end: 'closed', at: Date.now() }];
    t.renderCommands();
    if (typeof SHOT_PLOT !== 'undefined') setTimeout(() => {                 // terminal-plot.png
        ['socVoltage', 'socCurrent', 'temp.board'].forEach(k => t.plotSel.add(k));
        t.openPlot();
    }, 5000);
}, 1500);
