// HW Utils → Modbus against tests/fake_devices.py (Modbus TCP :5502)
Devices.open(); Devices.setTab('modbus');
setTimeout(async () => {
    const m = Devices.tabs.modbus, p = m.prof();
    Object.assign(p.conn, { transport: 'tcp', host: '127.0.0.1', netport: '5502', timeout: '300' });
    p.macros = [
        { name: 'status', unit: '1', fn: '3', addr: '0', count: '4', fmt: 'u16' },
        { name: 'firmware', unit: '1', fn: '3', addr: '4', count: '3', fmt: 'ascii' },
        { name: 'model', unit: '1', fn: '3', addr: '7', count: '5', fmt: 'ascii' },
        { name: 'block', unit: '1', fn: '3', addr: '0', count: '12', fmt: 'hex' },
        { name: 'input regs', unit: '1', fn: '4', addr: '0', count: '2', fmt: 'u16' },
        { name: 'counter', unit: '1', fn: '3', addr: '2', count: '2', fmt: 'u16', auto: true, cycle: true, period: 500 },
        { name: 'energy', unit: '1', fn: '3', addr: '20', count: '2', fmt: 's32sw', auto: true, cycle: true, period: 1000 },
        { name: 'voltage', unit: '1', fn: '3', addr: '30', count: '2', fmt: 'f32', auto: true, cycle: true, period: 1000 },
    ];
    p.note = 'Charger J1772 (unit 1, Modbus TCP). Only function 03 is supported.\n' +
             'Firmware [[03 4 3 ascii]]   model [[03 7 5 ascii]]   state block [[03 0 4]]\n' +
             'Energy [[03 20 2 s32sw]]   mains voltage [[03 30 2 f32]]   start charging [[06 100 =1]]';
    m.render();
    await m.runRows([0, 1, 2, 3, 4]);
    m.fillQuick(m.parseTag('03 30 2 f32')); await m.runQuick();
    m.startCycle();
    setTimeout(() => m.stopCycle(), 2500);
}, 1500);
