/* ==========================================================================
   HW Utils → CAN: visual editor of one TX list row (a popover next to the row's ⚙ button).
   Bit grid (click = toggle), bytes (hex, ↑ ↓ / wheel ±1), DLC; fields kept in the row
   (`fields`: bit, u8 / s8 / u16 / s16 / u32 / s32 LSB or MSB first, × scale + offset,
   min / max / step) with a switch or input + slider, and a sweep (min → max → min).
   Every change goes through Devices.tabs.can.rowChanged(): saved with the list and
   sent on the fly to the row's running transmission. Sweeps stop when the editor closes.
   ========================================================================== */

const CanTxEdit = {
    row: null,
    bytes: [],
    sweeps: {},             // field index -> {timer, dir}
    COLORS: ['--info', '--warn', '--git', '--accent', '--danger', '--code'],
    RANGES: { u8: [0, 255], s8: [-128, 127], u16: [0, 65535], s16: [-32768, 32767],
              u32: [0, 4294967295], s32: [-2147483648, 2147483647], bit: [0, 1] },
    SIZE: { bit: 0, u8: 1, s8: 1, u16: 2, s16: 2, u32: 4, s32: 4 },

    $(id) { return document.getElementById(id); },
    can() { return Devices.tabs.can; },

    open(row, anchor) {
        if (this.row === row) return this.close();         // the ⚙ button toggles
        this.close();
        this.row = row;
        this.anchor = anchor || null;
        this._scrolled = false;
        row.fields = row.fields || [];
        this.bytes = this._parse(row.data) || [];
        this.$('can-te').hidden = false;
        this.$('can-te-form').hidden = true;
        this._bind();
        this.render();
    },

    toggleForm() {
        const f = this.$('can-te-form');
        f.hidden = !f.hidden;
        this.place();
        if (!f.hidden) this.$('can-te-name').focus();
    },

    /** Above the row's button when there is room (else below), arrow pointing at the button. */
    place() {
        const el = this.$('can-te'), arrow = this.$('can-te-arrow');
        const box = el.offsetParent ? el.offsetParent.getBoundingClientRect() : null;
        if (!box) return;
        const w = Math.min(1000, box.width - 16);
        el.style.width = w + 'px';
        if (this.anchor && this.anchor.isConnected && !this._scrolled) {
            this._scrolled = true;
            this.anchor.scrollIntoView({ block: 'nearest' });             // a row scrolled out of the TX list
        }
        const a = this.anchor && this.anchor.isConnected ? this.anchor.getBoundingClientRect() : null;
        if (!a || !a.height) {
            el.style.maxHeight = (box.height - 16) + 'px';
            el.style.left = (box.width - w) / 2 + 'px';
            el.style.top = '8px';
            arrow.hidden = true;
            return;
        }
        // the side with more room; the popover never leaves the CAN tab (it scrolls inside instead)
        const roomAbove = a.top - box.top - 14, roomBelow = box.bottom - a.bottom - 14;
        const up = roomAbove >= roomBelow;
        el.style.maxHeight = Math.max(160, up ? roomAbove : roomBelow) + 'px';
        const h = el.offsetHeight;
        const ax = a.left + a.width / 2 - box.left;
        const left = Math.max(8, Math.min(box.width - w - 8, ax - w * 0.6));
        el.style.left = left + 'px';
        el.style.top = (up ? Math.max(4, a.top - box.top - 12 - h) : a.bottom - box.top + 12) + 'px';
        arrow.hidden = false;
        arrow.className = 'can-te-arrow ' + (up ? 'down' : 'up');
        arrow.style.left = Math.max(12, Math.min(w - 24, ax - left - 8)) + 'px';
    },

    close() {
        Object.keys(this.sweeps).forEach(i => this.stopSweep(+i));
        this.row = null;
        const el = this.$('can-te');
        if (el) el.hidden = true;
    },

    /** The row changed elsewhere (table input): take its bytes unless the change came from here. */
    rowChanged(r) {
        if (r !== this.row || this._self) return;
        const b = this._parse(r.data);
        if (b) { this.bytes = b; this.renderValues(); }
        this._renderHead();
    },

    _parse(data) {
        const hex = String(data || '').replace(/0x/gi, '').replace(/[\s,:]/g, '');
        if (!/^([0-9a-f]{2})*$/i.test(hex) || hex.length > 16) return null;
        const out = [];
        for (let i = 0; i < hex.length; i += 2) out.push(parseInt(hex.substr(i, 2), 16));
        return out;
    },

    _hex(v) { return v.toString(16).toUpperCase().padStart(2, '0'); },

    /** Same as core/net.checksum: over data[0 .. dlc-2]; toyota adds the ID bytes and the DLC. */
    checksum(kind, bytes) {
        const n = bytes.length, body = bytes.slice(0, Math.max(0, n - 1));
        if (kind === 'xor8') return body.reduce((a, b) => a ^ b, 0);
        let v = body.reduce((a, b) => a + b, 0);
        if (kind === 'toyota') {
            const id = parseInt(String(this.row.id || '0').replace(/^0x/i, ''), 16) || 0;
            v += (id & 0xFF) + ((id >> 8) & 0xFF) + ((id >> 16) & 0xFF) + ((id >>> 24) & 0xFF) + n;
        }
        return v & 0xFF;
    },

    /** CS / counter selects -> row.cs / row.cnt (applied by the server to every transmission). */
    setMods() {
        const cs = this.$('can-te-cs').value, b = this.$('can-te-cnt').value;
        if (cs) this.row.cs = cs; else delete this.row.cs;
        if (b !== '') this.row.cnt = { byte: +b, bits: this.$('can-te-cntbits').value }; else delete this.row.cnt;
        this.$('can-te-cntbits').hidden = b === '';
        this._commit();
        if (!this.row.quick) {                      // CS / N badges in the table; keep pointing at the new row button
            this.can().renderTx();
            this.anchor = document.querySelector(`#can-tx-rows tr[data-uid="${CSS.escape(this.row.uid)}"] [data-a="edit"]`);
        }
        this.renderValues();
        this.place();
    },

    /** Write the bytes into the row (live update of a running transmission) and refresh the view. */
    _commit() {
        if (!this.row) return;
        if (this.row.cs && this.bytes.length && !this.row.rtr) {
            this.bytes[this.bytes.length - 1] = this.checksum(this.row.cs, this.bytes);   // shown / sent once as is
        }
        this.row.data = this.bytes.map(v => this._hex(v)).join(' ');
        this._self = true;
        try { this.can().rowChanged(this.row, 'data'); } finally { this._self = false; }
        this.renderValues();
    },

    // ── encode / decode ────────────────────────────────────────────────────

    _raw(f) {
        if (f.type === 'bit') {
            const v = this.bytes[f.byte];
            return v == null ? null : (v >> f.bit) & 1;
        }
        const n = this.SIZE[f.type];
        if (f.byte + n > this.bytes.length) return null;
        let v = 0;
        for (let i = 0; i < n; i++) v = v * 256 + this.bytes[f.byte + (f.order === 'be' ? i : n - 1 - i)];
        if (f.type[0] === 's' && v >= 2 ** (8 * n - 1)) v -= 2 ** (8 * n);
        return v;
    },

    value(f) {
        const raw = this._raw(f);
        return raw == null ? null : f.type === 'bit' ? raw : raw * (f.scale || 1) + (f.offset || 0);
    },

    /** Physical limits of a field: its min / max, else the range of its type through scale / offset. */
    limits(f) {
        if (f.type === 'bit') return [0, 1];
        const [lo, hi] = this.RANGES[f.type].map(r => r * (f.scale || 1) + (f.offset || 0));
        return [f.min ?? Math.min(lo, hi), f.max ?? Math.max(lo, hi)];
    },

    setValue(i, v) {
        const f = this.row.fields[i];
        if (v == null || isNaN(v)) return;
        if (f.type === 'bit') {
            const b = this.bytes[f.byte];
            if (b == null) return;
            this.bytes[f.byte] = v ? b | (1 << f.bit) : b & ~(1 << f.bit);
            return this._commit();
        }
        const n = this.SIZE[f.type];
        while (this.bytes.length < f.byte + n) this.bytes.push(0);         // a field past the DLC extends the frame
        const [lo, hi] = this.limits(f);
        v = Math.min(hi, Math.max(lo, v));
        const [rlo, rhi] = this.RANGES[f.type];
        let raw = Math.round((v - (f.offset || 0)) / (f.scale || 1));
        raw = Math.min(rhi, Math.max(rlo, raw));
        if (raw < 0) raw += 2 ** (8 * n);
        for (let k = 0; k < n; k++) {
            const byte = Math.floor(raw / 2 ** (8 * k)) % 256;                 // k = 0: least significant
            this.bytes[f.byte + (f.order === 'be' ? n - 1 - k : k)] = byte;
        }
        this._commit();
    },

    stepValue(i, dir) {
        const f = this.row.fields[i];
        const v = this.value(f);
        this.setValue(i, (v ?? 0) + dir * (f.step || f.scale || 1));
    },

    // ── bits / bytes ───────────────────────────────────────────────────────

    toggleBit(i, k) {
        if (this.bytes[i] == null) return;
        this.bytes[i] ^= 1 << k;
        this._commit();
    },

    setByte(i, v) {
        if (i >= this.bytes.length) return;
        this.bytes[i] = ((v % 256) + 256) % 256;
        this._commit();
    },

    setDlc(n) {
        n = Math.max(0, Math.min(8, n));
        this.bytes = this.bytes.slice(0, n);
        while (this.bytes.length < n) this.bytes.push(0);
        this._commit();
        this.render();
    },

    // ── fields ─────────────────────────────────────────────────────────────

    _fieldName(f) {
        if (f.name) return f.name;
        return f.type === 'bit' ? `B${f.byte}.${f.bit}` : `${f.type}${this.SIZE[f.type] > 1 ? (f.order === 'be' ? ' MSB' : ' LSB') : ''} @${f.byte}`;
    },

    addField(f) {
        const n = this.SIZE[f.type];
        if (n && f.byte + n > 8) return toast(`${f.type} at byte ${f.byte} does not fit into 8 bytes`, true);
        this.row.fields.push(Object.assign({ name: '', byte: 0, bit: 0, order: 'le', scale: 1, offset: 0, step: 1 }, f));
        this.$('can-te-form').hidden = true;
        this.can().save();
        this.render();
    },

    addFromForm() {
        const num = (id, d) => { const v = this.$(id).value.trim(); return v === '' ? d : parseFloat(v); };
        const f = { type: this.$('can-te-type').value, byte: +this.$('can-te-byte').value, bit: +this.$('can-te-bit').value,
                    order: this.$('can-te-order').value, scale: num('can-te-scale', 1) || 1, offset: num('can-te-offset', 0),
                    step: num('can-te-step', 1) || 1, name: this.$('can-te-name').value.trim() };
        const mn = num('can-te-min', null), mx = num('can-te-max', null);
        if (mn != null) f.min = mn;
        if (mx != null) f.max = mx;
        this.$('can-te-name').value = '';
        this.addField(f);
    },

    /** Fields from the analyser's signals of this ID (they share the decoding). */
    fromAnalyser() {
        const fr = this.can()._rowFrame(this.row);
        if (fr.error) return toast(fr.error, true);
        const key = `${fr.ext ? 'x' : 's'}:${parseInt(fr.id, 16).toString(16)}`;
        let sigs = [];
        try { sigs = JSON.parse(localStorage.getItem('can.sig.' + key) || '[]') || []; } catch (e) { /* none */ }
        sigs = sigs.filter(s => this.SIZE[s.type] !== undefined);
        if (!sigs.length) return toast(`No analyser signals for ID ${fr.id.toUpperCase()}`, true);
        sigs.forEach(s => this.row.fields.push({ name: s.name || '', type: s.type, byte: s.byte, bit: s.bit || 0, order: s.order || 'le',
                                                 scale: s.scale || 1, offset: s.offset || 0, step: 1 }));
        this.can().save();
        this.render();
        toast(`${sigs.length} field(s) from the analyser`);
    },

    /** Move a field to another byte / bit, change its byte order or sweep mode — also while the row is being sent:
        from now on the value is written there (the old bytes keep what they had). */
    setFieldOpt(i, opt, value) {
        const f = this.row.fields[i];
        if (!f) return;
        const keep = f.type === 'bit' ? null : this.value(f);
        if (opt === 'pos') f.byte = +value;
        else if (opt === 'bitpos') f.bit = +value;
        else if (opt === 'order') f.order = value;
        else if (opt === 'swmode') f.sweep = value;
        this.can().save();
        if ((opt === 'pos' || opt === 'order') && keep != null) this.setValue(i, keep);   // write the current value at the new place
        this._renderFields();
        this.renderValues();
    },

    removeField(i) {
        this.stopSweep(i);
        this.row.fields.splice(i, 1);
        this.sweeps = {};
        this.can().save();
        this.render();
    },

    moveField(i, d) {
        const a = this.row.fields, j = i + d;
        if (j < 0 || j >= a.length) return;
        Object.keys(this.sweeps).forEach(k => this.stopSweep(+k));
        [a[i], a[j]] = [a[j], a[i]];
        this.can().save();
        this.render();
    },

    toggleSweep(i) {
        if (this.sweeps[i]) return this.stopSweep(i);
        const f = this.row.fields[i];
        const ms = Math.max(20, parseInt(this.$(`can-te-sw-${i}`).value, 10) || 100);
        const st = this.sweeps[i] = { dir: 1 };
        st.timer = setInterval(() => {
            if (!this.row || !this.row.fields.includes(f)) return this.stopSweep(i);
            const [lo, hi] = this.limits(f);
            const step = f.type === 'bit' ? 1 : (f.step || f.scale || 1);
            let v = this.value(f) ?? lo;
            const mode = f.sweep || 'both';
            if (f.type === 'bit') v = v ? 0 : 1;
            else if (mode === 'up') v = v + step > hi + 1e-9 ? lo : v + step;          // lo → hi, again from lo
            else if (mode === 'down') v = v - step < lo - 1e-9 ? hi : v - step;      // hi → lo, again from hi
            else {                                                                   // lo → hi → lo
                v += st.dir * step;
                if (v >= hi) { v = hi; st.dir = -1; }
                if (v <= lo) { v = lo; st.dir = 1; }
            }
            this.setValue(i, v);
        }, ms);
        this._renderSweep(i);
    },

    stopSweep(i) {
        const st = this.sweeps[i];
        if (!st) return;
        clearInterval(st.timer);
        delete this.sweeps[i];
        this._renderSweep(i);
    },

    // ── rendering ──────────────────────────────────────────────────────────

    _bind() {
        if (this._bound) return;
        this._bound = true;
        const root = this.$('can-te');
        root.addEventListener('click', e => {
            const t = e.target.closest('[data-te]');
            if (!t) return;
            const i = +t.dataset.i;
            switch (t.dataset.te) {
                case 'bit': return this.toggleBit(+t.dataset.byte, +t.dataset.k);
                case 'bswitch': return this.setValue(i, this.value(this.row.fields[i]) ? 0 : 1);
                case 'minus': return this.stepValue(i, -1);
                case 'plus': return this.stepValue(i, 1);
                case 'sweep': return this.toggleSweep(i);
                case 'del': return this.removeField(i);
                case 'up': return this.moveField(i, -1);
                case 'down': return this.moveField(i, 1);
                case 'byteadd': return this.addField({ type: 'u8', byte: +t.dataset.byte });
            }
        });
        root.addEventListener('input', e => {
            const t = e.target;
            if (t.dataset.tv === 'num' || t.dataset.tv === 'range') {
                const v = parseFloat(t.value);
                if (!isNaN(v)) this.setValue(+t.dataset.i, v);
            } else if (t.dataset.tv === 'byte') {
                if (/^[0-9a-f]{1,2}$/i.test(t.value)) this.setByte(+t.dataset.byte, parseInt(t.value, 16));
            } else if (['pos', 'bitpos', 'order', 'swmode'].includes(t.dataset.tv)) {
                this.setFieldOpt(+t.dataset.i, t.dataset.tv, t.value);
            }
        });
        root.addEventListener('keydown', e => {
            const t = e.target;
            if (t.dataset.tv === 'byte' && (e.key === 'ArrowUp' || e.key === 'ArrowDown')) {
                e.preventDefault();
                this.setByte(+t.dataset.byte, this.bytes[+t.dataset.byte] + (e.key === 'ArrowUp' ? 1 : -1) * (e.shiftKey ? 16 : 1));
            }
        });
        root.addEventListener('wheel', e => {
            const t = e.target;
            if (t.dataset && (t.dataset.tv === 'byte' || t.dataset.tv === 'num') && t === document.activeElement) {
                e.preventDefault();
                const up = e.deltaY < 0;
                if (t.dataset.tv === 'byte') this.setByte(+t.dataset.byte, this.bytes[+t.dataset.byte] + (up ? 1 : -1));
                else this.stepValue(+t.dataset.i, up ? 1 : -1);
            }
        }, { passive: false });
        this.$('can-te-type').addEventListener('change', () => this._formUi());
        this._formUi();
        document.addEventListener('keydown', e => {
            if (e.key === 'Escape' && this.row && !e.target.closest('input, select')) {
                e.stopImmediatePropagation();
                e.preventDefault();
                this.close();
            }
        }, true);
    },

    _formUi() {
        const t = this.$('can-te-type').value;
        this.$('can-te-bitwrap').hidden = t !== 'bit';
        this.$('can-te-order').hidden = !(this.SIZE[t] > 1);
        this.$('can-te-numwrap').hidden = t === 'bit';
    },

    _color(i) { return `var(${this.COLORS[i % this.COLORS.length]})`; },

    render() {
        if (!this.row) return;
        this._renderHead();
        this._renderFields();
        this.renderValues();
        this.renderState();
        this.place();
    },

    _renderHead() {
        const r = this.row, fr = this.can()._rowFrame(r);
        this.$('can-te-title').innerHTML = `<i class="fa-solid fa-sliders"></i><b>${esc(r.quick ? 'Quick send' : r.name || 'TX frame')}</b>` +
            `<span class="mono">ID ${esc(String(r.id || '?').toUpperCase())}${r.ext ? ' EXT' : ''}${r.rtr ? ' RTR' : ''}</span>` +
            (fr.error ? `<span class="text-error small">${esc(fr.error)}</span>` : '');
        const dlc = this.$('can-te-dlc');
        if (document.activeElement !== dlc) dlc.value = String(this.bytes.length);
        this.$('can-te-cs').value = r.cs || '';
        this.$('can-te-cnt').value = r.cnt ? String(r.cnt.byte) : '';
        this.$('can-te-cntbits').value = r.cnt ? r.cnt.bits || '0-7' : '0-7';
        this.$('can-te-cntbits').hidden = !r.cnt;
        const p = this.$('can-te-period');
        if (document.activeElement !== p) p.value = r.period;
    },

    setPeriod(v) {
        this.row.period = Math.max(0, parseInt(v, 10) || 0);
        this.can().rowChanged(this.row, 'period');
    },

    renderState() {
        if (!this.row) return;
        const j = this.can()._job(this.row.uid);
        const b = this.$('can-te-cyc');
        b.innerHTML = j ? '<i class="fa-solid fa-stop"></i> Stop' : '<i class="fa-solid fa-repeat"></i> Start';
        b.classList.toggle('btn-danger', !!j);
        b.classList.toggle('btn-warning', !j);
        this.$('can-te-state').innerHTML = j
            ? `<span class="text-warn"><i class="fa-solid fa-repeat fa-spin can-spin"></i> every ${j.period_ms} ms · ${j.sent} sent</span>` +
              (j.errors ? ` · <span class="text-error" title="${esc(j.last_error)}">${j.errors} errors</span>` : '')
            : '<span class="muted">stopped — ▶ sends once</span>';
    },

    sendOnce() { this.can()._sendRow(this.row); },

    /** Start / stop the cyclic send of the row (a TX list row or the quick send, tag = its uid). */
    toggleCyc() {
        const can = this.can(), j = can._job(this.row.uid);
        if (!can.canIface) return;
        const done = () => can._pollFrames();
        if (j) can._post('/api/net/can/send', { action: 'stop', job: j.job }).then(done).catch(e => toast(e.message, true));
        else can._startRow(this.row).then(done).catch(e => toast(e.message, true));
    },

    /** Bits, bytes and field values from this.bytes (inputs being typed into are left alone). */
    renderValues() {
        if (!this.row) return;
        const owner = {};
        this.row.fields.forEach((f, i) => {
            if (f.type === 'bit') owner[f.byte * 8 + f.bit] = i;
            else for (let b = f.byte; b < f.byte + this.SIZE[f.type]; b++) for (let k = 0; k < 8; k++) owner[b * 8 + k] = owner[b * 8 + k] ?? i;
        });
        let html = '<table class="can-an-bits can-te-bits"><thead><tr><th></th>' + [7, 6, 5, 4, 3, 2, 1, 0].map(k => `<th>${k}</th>`).join('') +
                   '<th>hex</th><th>dec</th><th></th></tr></thead><tbody>';
        for (let i = 0; i < 8; i++) {
            const v = this.bytes[i];
            const isCs = this.row.cs && i === this.bytes.length - 1;
            html += `<tr><th>${v == null ? `B${i}` : `<span class="can-te-blbl" data-te="byteadd" data-byte="${i}" title="Add a u8 field for byte ${i}">B${i}</span>`}</th>`;
            const cnt = this.row.cnt && this.row.cnt.byte === i ? { '0-7': [0, 8], '0-3': [0, 4], '4-7': [4, 4], '0-1': [0, 2] }[this.row.cnt.bits || '0-7'] : null;
            for (let k = 7; k >= 0; k--) {
                const bit = v == null ? null : (v >> k) & 1, o = owner[i * 8 + k];
                const special = isCs ? ' can-te-cs' : cnt && k >= cnt[0] && k < cnt[0] + cnt[1] ? ' can-te-cnt' : '';
                html += `<td class="can-an-bit${bit ? ' on' : ''}${bit == null ? ' none' : ''}${special}" ${bit == null || isCs ? '' : `data-te="bit" data-byte="${i}" data-k="${k}"`}` +
                        `${o != null ? ` style="--fc:${this._color(o)}" data-own` : ''} title="B${i}.${k}${o != null ? ' — ' + esc(this._fieldName(this.row.fields[o])) : ''} — click to toggle">${bit == null ? '·' : bit}</td>`;
            }
            const cur = this.$(`can-te-b${i}`);
            const typing = cur && cur === document.activeElement;
            html += v == null ? '<td></td><td></td><td></td>'
                : `<td><input class="input input-sm mono can-te-byte" id="can-te-b${i}" data-tv="byte" data-byte="${i}" maxlength="2" value="${typing ? esc(cur.value) : this._hex(v)}" title="hex — ↑ ↓ / wheel ±1"></td>` +
                  `<td class="mono faint">${isCs ? '<span class="can-te-tag" title="checksum — computed">CS</span>' : cnt ? '<span class="can-te-tag" title="rolling counter: +1 per frame">N</span>' : v}</td>` +
                  `<td><button type="button" class="btn-icon can-te-badd" data-te="byteadd" data-byte="${i}" title="Add a u8 field for byte ${i}"><i class="fa-solid fa-plus"></i></button></td>`;
            html += '</tr>';
        }
        const focusId = document.activeElement && document.activeElement.id;
        const pos = focusId && focusId.startsWith('can-te-b') ? document.activeElement.selectionStart : null;
        this.$('can-te-grid').innerHTML = html + '</tbody></table>';
        if (pos != null && this.$(focusId)) { this.$(focusId).focus(); this.$(focusId).setSelectionRange(pos, pos); }
        this.$('can-te-data').textContent = this.bytes.map(v => this._hex(v)).join(' ') || '(no data)';
        this.row.fields.forEach((f, i) => {
            const v = this.value(f);
            const raw = this._raw(f);
            const val = this.$(`can-te-v-${i}`);
            if (!val) return;
            if (f.type === 'bit') {
                val.classList.toggle('on', !!v);
                val.textContent = v ? 'ON' : 'OFF';
            } else {
                const num = this.$(`can-te-n-${i}`), rng = this.$(`can-te-r-${i}`);
                const shown = v == null ? '' : String(+v.toFixed(6));
                if (num !== document.activeElement) num.value = shown;
                if (rng !== document.activeElement && v != null) rng.value = v;
                val.textContent = raw == null ? 'outside the frame' : `0x${(raw < 0 ? raw + 2 ** (8 * this.SIZE[f.type]) : raw).toString(16).toUpperCase()}`;
                val.title = raw == null ? '' : `raw ${raw}`;
            }
        });
        this._renderHead();
    },

    _renderFields() {
        const box = this.$('can-te-fields');
        const fields = this.row.fields;
        if (!fields.length) {
            box.innerHTML = '<div class="muted small can-an-hint">No fields yet: + Field, a click on a byte label (B0…B7) = u8, ' +
                'or From analyser. Bits are toggled in the grid.</div>';
            return;
        }
        const per = Math.max(20, this.row.period || 100);
        box.innerHTML = fields.map((f, i) => {
            const [lo, hi] = this.limits(f);
            const sub = f.type === 'bit' ? `B${f.byte}.${f.bit}` : `${f.type}${this.SIZE[f.type] > 1 ? (f.order === 'be' ? ' MSB' : ' LSB') : ''} @${f.byte}` +
                ((f.scale || 1) !== 1 || f.offset ? ` ×${f.scale} ${f.offset >= 0 ? '+' : ''}${f.offset}` : '');
            const ctl = f.type === 'bit'
                ? `<button type="button" class="can-te-switch" id="can-te-v-${i}" data-te="bswitch" data-i="${i}">OFF</button><span class="spacer"></span>`
                : `<button type="button" class="btn-icon" data-te="minus" data-i="${i}" title="− step"><i class="fa-solid fa-minus"></i></button>` +
                  `<input class="input input-sm mono can-te-num" id="can-te-n-${i}" data-tv="num" data-i="${i}" type="number" step="${f.step || f.scale || 1}" title="value (wheel ± step)">` +
                  `<button type="button" class="btn-icon" data-te="plus" data-i="${i}" title="+ step"><i class="fa-solid fa-plus"></i></button>` +
                  `<input class="can-te-range" id="can-te-r-${i}" data-tv="range" data-i="${i}" type="range" min="${lo}" max="${hi}" step="${f.step || f.scale || 1}" title="${+lo.toFixed(6)} … ${+hi.toFixed(6)}">` +
                  `<span class="faint small mono can-te-raw" id="can-te-v-${i}"></span>`;
            const size = this.SIZE[f.type];
            const opts = (n, cur, lbl) => Array.from({ length: n }, (_, k) => `<option value="${k}"${k === cur ? ' selected' : ''}>${lbl(k)}</option>`).join('');
            const where = `<select class="input input-sm can-te-pos" data-tv="pos" data-i="${i}" title="Byte the value is written to — can be changed while it runs">${opts(8 - Math.max(size, 1) + 1, f.byte, k => size > 1 ? `B${k}–${k + size - 1}` : `B${k}`)}</select>` +
                (f.type === 'bit' ? `<select class="input input-sm can-te-pos" data-tv="bitpos" data-i="${i}" title="Bit">${opts(8, f.bit, k => `.${k}`)}</select>` : '') +
                (size > 1 ? `<select class="input input-sm can-te-pos" data-tv="order" data-i="${i}" title="Byte order"><option value="le"${f.order !== 'be' ? ' selected' : ''}>LSB</option><option value="be"${f.order === 'be' ? ' selected' : ''}>MSB</option></select>` : '');
            const swmode = f.type === 'bit' ? '' : `<select class="input input-sm can-te-swmode" data-tv="swmode" data-i="${i}" title="Sweep mode: ↗ min → max, then again from min · ↘ max → min, then again from max · ↗↘ min → max → min">` +
                [['up', '↗'], ['down', '↘'], ['both', '↗↘']].map(([v, l]) =>
                    `<option value="${v}"${(f.sweep || 'both') === v ? ' selected' : ''}>${l}</option>`).join('') + '</select>';
            return `<div class="can-te-field" style="--fc:${this._color(i)}">
                <span class="can-te-fname" title="${esc(sub)}"><b>${esc(f.name || f.type)}</b><span class="faint small">${esc(f.name ? f.type + (f.scale !== 1 || f.offset ? ' ×' + f.scale : '') : (f.scale !== 1 || f.offset ? '×' + f.scale + ' ' + (f.offset >= 0 ? '+' : '') + f.offset : ''))}</span></span>
                ${where}
                ${ctl}
                ${swmode}
                <input class="input input-sm mono can-te-swms" id="can-te-sw-${i}" type="number" min="20" step="10" value="${per}" title="sweep: ms per step">
                <button type="button" class="btn btn-ghost btn-sm can-te-swb" id="can-te-swb-${i}" data-te="sweep" data-i="${i}" title="${f.type === 'bit' ? 'Toggle the bit periodically' : 'Run min → max → min with the step'}"><i class="fa-solid fa-right-left"></i></button>
                <span class="can-more">
                    <button type="button" class="btn-icon" data-te="up" data-i="${i}" title="Up"${i ? '' : ' disabled'}><i class="fa-solid fa-arrow-up"></i></button>
                    <button type="button" class="btn-icon" data-te="down" data-i="${i}" title="Down"${i < fields.length - 1 ? '' : ' disabled'}><i class="fa-solid fa-arrow-down"></i></button>
                    <button type="button" class="btn-icon" data-te="del" data-i="${i}" title="Remove the field (the bytes stay)"><i class="fa-solid fa-xmark"></i></button>
                </span></div>`;
        }).join('');
        Object.keys(this.sweeps).forEach(i => this._renderSweep(+i));
    },

    _renderSweep(i) {
        const b = this.$(`can-te-swb-${i}`);
        if (!b) return;
        const on = !!this.sweeps[i];
        b.innerHTML = on ? '<i class="fa-solid fa-stop"></i>' : '<i class="fa-solid fa-right-left"></i>';
        b.title = on ? 'Stop the sweep' : 'Sweep';
        b.classList.toggle('btn-warning', on);
        b.classList.toggle('btn-ghost', !on);
    },
};
