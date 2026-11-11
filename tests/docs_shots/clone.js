// HW Utils → Clone / Image (the dev server is not root: show the tab as the root service sees it)
Devices.open(); Devices.setTab('clone');
setTimeout(() => { const c = Devices.tabs.clone; c.data.root = true; c.render(); }, 2000);
