"""Simulated network devices for manual checks and README screenshots (``tests/devserver.py --fake-devices``).

  127.0.0.1:5502  Modbus TCP slave, unit 1: holding registers 0..299 — 0..3 status, 4..6 "3.47" (firmware),
                  7..11 " J1772_0" (model), 20..21 energy (s32, word swap), 30..31 voltage (float32),
                  a counter in 2 and a slowly moving value in 3; function 04 answers "illegal function".
  127.0.0.1:5555  TCP JSON telemetry: one object per line every 200 ms (temperatures, voltage, current, state).
  127.0.0.1:5588  SCPI-like bench PSU: one TCP connection per command, "MEAS:VOLT?" style queries answer a number.

Never used by the unit tests; nothing here touches real hardware.
"""
import json
import math
import random
import socketserver
import struct
import threading
import time

MODBUS_PORT, JSON_PORT, SCPI_PORT = 5502, 5555, 5588


class _Regs:
    def __init__(self):
        self.r = [0] * 300
        self.r[0:2] = [0, 1]
        self.r[4:7] = [0x332E, 0x3437, 0x0000]                         # "3.47"
        self.r[7:12] = [0x204A, 0x3137, 0x3732, 0x5F30, 0x0000]         # " J1772_0"
        self.t0 = time.time()

    def tick(self):
        k = int((time.time() - self.t0) * 2)
        self.r[2] = k & 0xFFFF
        self.r[3] = int(500 + 120 * math.sin(k / 20)) & 0xFFFF
        energy = 1234567 + k * 13
        self.r[20], self.r[21] = energy & 0xFFFF, (energy >> 16) & 0xFFFF       # s32, word order CDAB
        hi, lo = struct.unpack('>HH', struct.pack('>f', 230.0 + 2 * math.sin(k / 15)))
        self.r[30], self.r[31] = hi, lo

    def pdu(self, pdu):
        fn = pdu[0]
        self.tick()
        if fn == 3:
            a, n = struct.unpack('>HH', pdu[1:5])
            if a + n > len(self.r) or not 1 <= n <= 125:
                return bytes([fn | 0x80, 2])
            return bytes([fn, n * 2]) + b''.join(struct.pack('>H', x) for x in self.r[a:a + n])
        if fn == 6:
            a, v = struct.unpack('>HH', pdu[1:5])
            if a >= len(self.r):
                return bytes([fn | 0x80, 2])
            self.r[a] = v
            return pdu[:5]
        if fn == 16:
            a, n = struct.unpack('>HH', pdu[1:5])
            if a + n > len(self.r):
                return bytes([fn | 0x80, 2])
            self.r[a:a + n] = list(struct.unpack(f'>{n}H', pdu[6:6 + 2 * n]))
            return pdu[:5]
        return bytes([fn | 0x80, 1])


def _modbus(regs):
    class H(socketserver.BaseRequestHandler):
        def handle(self):
            while True:
                head = self.request.recv(7)
                if len(head) < 7:
                    return
                tid, _, ln, unit = struct.unpack('>HHHB', head)
                pdu = self.request.recv(ln - 1)
                if unit != 1:
                    continue
                ans = regs.pdu(pdu)
                self.request.sendall(struct.pack('>HHHB', tid, 0, len(ans) + 1, unit) + ans)
    return H


class _Json(socketserver.BaseRequestHandler):
    def handle(self):
        k = 0
        try:
            while True:
                k += 1
                msg = {'devType': 'CAN', 'devId': 18, 'socVoltage': 5300 + int(20 * math.sin(k / 9)),
                       'socCurrent': 229 + random.randint(-3, 3), 'temp': {'board': round(41 + 2 * math.sin(k / 25), 2),
                       'cell': round(28 + math.cos(k / 30), 2)}, 'charging': k % 40 < 30}
                self.request.sendall((json.dumps(msg) + '\r\n').encode())
                if k % 15 == 0:
                    self.request.sendall(b'heartbeat ok\r\n')
                time.sleep(0.2)
        except OSError:
            pass


class _Scpi(socketserver.BaseRequestHandler):
    def handle(self):
        cmd = self.request.recv(200).strip().upper()
        if cmd.endswith(b'?') or b'?' in cmd:
            val = 12 + random.random() * 0.05 if b'VOLT' in cmd else 0.4 + random.random() * 0.02
            self.request.sendall(f'{val:.4f}\n'.encode())


def start():
    """Start the three servers in daemon threads (idempotent per process)."""
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    servers = []
    for port, handler in [(MODBUS_PORT, _modbus(_Regs())), (JSON_PORT, _Json), (SCPI_PORT, _Scpi)]:
        try:
            srv = socketserver.ThreadingTCPServer(('127.0.0.1', port), handler)
        except OSError as e:
            print(f'fake device on :{port} not started: {e}')
            continue
        srv.daemon_threads = True
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        servers.append(srv)
    return servers


if __name__ == '__main__':
    start()
    print(f'Modbus TCP :{MODBUS_PORT} · JSON telemetry :{JSON_PORT} · SCPI PSU :{SCPI_PORT}  (Ctrl+C to stop)')
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
