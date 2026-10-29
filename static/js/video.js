/* ==========================================================================
   Video stream: device selector in the top bar (partials/video_controls.html)
   and draggable/resizable popup (partials/video_modal.html). Logged-in only.
   ========================================================================== */

const Video = {
    streamId: null,
    device: null,
    res: '640x480',

    loadDevices() {
        const sel = document.getElementById('video-dev-select');
        const cur = sel.value;
        sel.innerHTML = '<option value="">Scanning devices…</option>';
        App.api('/api/video_devices').then(data => {
            const list = data.devices || [];
            if (!list.length) {
                sel.innerHTML = '<option value="">No video devices</option>';
                return;
            }
            sel.innerHTML = list.map(d =>
                `<option value="${esc(d.path)}"${d.path === cur ? ' selected' : ''}>${esc(d.label || d.path)}</option>`
            ).join('');
            if (!cur) sel.value = (list.find(d => d.path === '/dev/video1') || list[0]).path;
        }).catch(() => { sel.innerHTML = '<option value="">Failed to load devices</option>'; });
    },

    loadResolutions(device) {
        const resSel = document.getElementById('video-res-select');
        resSel.innerHTML = '<option value="">Detecting…</option>';
        return App.api('/api/video_resolutions?device=' + encodeURIComponent(device))
            .then(data => data.resolutions)
            .catch(() => ['640x480', '1280x720', '320x240'])
            .then(list => {
                resSel.innerHTML = list.map(r => `<option value="${esc(r)}">${esc(r)}</option>`).join('');
                const picked = [Video.res, '640x480', '1280x720'].find(r => list.includes(r)) || list[0];
                resSel.value = picked;
                Video.res = picked;
            });
    },

    open() {
        const sel = document.getElementById('video-dev-select');
        if (!sel.value) {
            toast('Please select a video device', true);
            return;
        }
        Video.device = sel.value;
        const opt = sel.options[sel.selectedIndex];
        document.getElementById('video-popup-dev-label').textContent = opt ? opt.textContent : Video.device;
        document.getElementById('video-overlay').classList.add('open');
        Video.loadResolutions(Video.device).then(Video.start);
    },

    start() {
        if (!Video.device) return;
        const img = document.getElementById('video-stream-img');
        const loading = document.getElementById('video-loading');
        const status = document.getElementById('video-stream-status');
        Video.res = document.getElementById('video-res-select').value || Video.res;
        document.getElementById('video-res-badge').textContent = Video.res;
        Video.streamId = 'stream_' + Date.now();
        loading.hidden = false;
        img.hidden = true;
        img.onload = () => { loading.hidden = true; img.hidden = false; };
        img.onerror = () => {
            loading.hidden = true;
            status.innerHTML = '<span class="text-error">✕ Video stream error</span>';
        };
        img.src = '/api/video_feed?device=' + encodeURIComponent(Video.device) +
                  '&size=' + encodeURIComponent(Video.res) + '&sid=' + Video.streamId;
        status.innerHTML = '<i class="fa-solid fa-circle-play"></i> Playback active';
    },

    _stopStream() {
        const img = document.getElementById('video-stream-img');
        img.src = '';
        img.hidden = true;
        if (Video.streamId) {
            App.api('/api/video_stop', { json: { stream_id: Video.streamId } }).catch(() => {});
            Video.streamId = null;
        }
    },

    restart() {
        Video._stopStream();
        setTimeout(Video.start, 100);
    },

    close() {
        const ov = document.getElementById('video-overlay');
        if (!ov || !ov.classList.contains('open')) return;
        ov.classList.remove('open');
        Video._stopStream();
        document.getElementById('video-stream-status').textContent = 'Stopped';
    },

    initDragResize() {
        const box = document.getElementById('video-popup-box');
        const header = document.getElementById('video-popup-header');
        const grip = document.getElementById('video-resize-grip');
        let mode = null, sx, sy, sl, st, sw, shh;

        const pin = () => {
            const r = box.getBoundingClientRect();
            box.style.transform = 'none';
            box.style.left = r.left + 'px';
            box.style.top = r.top + 'px';
            return r;
        };

        header.addEventListener('mousedown', e => {
            if (e.target.closest('button, select, input, a')) return;
            const r = pin();
            mode = 'drag'; sx = e.clientX; sy = e.clientY; sl = r.left; st = r.top;
            header.style.cursor = 'grabbing';
            document.body.style.userSelect = 'none';
            e.preventDefault();
        });

        grip.addEventListener('mousedown', e => {
            const r = pin();
            mode = 'resize'; sx = e.clientX; sy = e.clientY; sw = r.width; shh = r.height;
            document.body.style.cursor = 'nwse-resize';
            document.body.style.userSelect = 'none';
            e.preventDefault();
            e.stopPropagation();
        });

        document.addEventListener('mousemove', e => {
            if (mode === 'drag') {
                const maxL = Math.max(0, window.innerWidth - box.offsetWidth);
                const maxT = Math.max(0, window.innerHeight - box.offsetHeight);
                box.style.left = Math.max(0, Math.min(maxL, sl + e.clientX - sx)) + 'px';
                box.style.top = Math.max(0, Math.min(maxT, st + e.clientY - sy)) + 'px';
            } else if (mode === 'resize') {
                box.style.width = Math.max(340, Math.min(window.innerWidth - box.offsetLeft - 10, sw + e.clientX - sx)) + 'px';
                box.style.height = Math.max(240, Math.min(window.innerHeight - box.offsetTop - 10, shh + e.clientY - sy)) + 'px';
            }
        });

        document.addEventListener('mouseup', () => {
            if (!mode) return;
            mode = null;
            header.style.cursor = '';
            document.body.style.cursor = '';
            document.body.style.userSelect = '';
        });
    },
};

document.addEventListener('DOMContentLoaded', () => {
    Video.loadDevices();
    Video.initDragResize();
});
App.onEscape(() => Video.close());
