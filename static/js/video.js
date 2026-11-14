/* ==========================================================================
   Video window: the top bar button (partials/video_controls.html) opens the camera chosen in Settings → Video
   (/api/video/default; local /dev/video* or a network source net:<name>) in a draggable / resizable popup
   (partials/video_modal.html). Devices are managed on the settings tab (settings_video.js). Logged-in only.
   ========================================================================== */

const Video = {
    streamId: null,
    device: null,
    res: '640x480',

    toggle() {
        const ov = document.getElementById('video-overlay');
        if (ov.classList.contains('open')) return Video.close();
        App.api('/api/video/default').then(d => {
            if (!d.device) {
                toast('Choose the camera in Settings → Video', true);
                if (location.pathname === '/settings') location.hash = 'video'; else location.href = '/settings#video';
                return;
            }
            Video.open(d.device, d.resolution, d.device);
        }).catch(e => toast(e.message, true));
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

    /** Open the popup on ``device`` (/dev/videoN or net:<name>) at ``res`` (kept when the device offers it). */
    open(device, res, label) {
        Video.device = device;
        if (res) Video.res = res;
        document.getElementById('video-popup-dev-label').textContent = label || device;
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

document.addEventListener('DOMContentLoaded', () => Video.initDragResize());   // devices are listed when the menu opens
App.onEscape(() => Video.close());
