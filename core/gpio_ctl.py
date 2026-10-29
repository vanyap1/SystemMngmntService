"""Manual GPIO control from the Devices popup.

Lines are requested only on explicit "claim" from a browser client and are held under a lease:
the client keeps it alive while the GPIO tab is open (polling ``snapshot``). Leaving the tab,
closing the popup or the page releases them; a client that disappears silently loses its lines
after LEASE_SECONDS. Claimed lines are requested "as is", so claiming never changes a pin.
Works with libgpiod Python bindings v1 and v2.
"""
import os
import re
import threading
import time

CONSUMER = 'sysmngmnt-web'
LEASE_SECONDS = 6
CHIP_PATTERN = re.compile(r'^/dev/gpiochip\d+$')
CLIENT_PATTERN = re.compile(r'^[\w-]{8,64}$')


class GpioError(Exception):
    pass


def _gpiod():
    try:
        import gpiod
    except ImportError:
        raise GpioError('Python module gpiod is not installed')
    return gpiod


class _LineV1:
    def __init__(self, gpiod, path, offset):
        self.gpiod = gpiod
        self.chip = gpiod.Chip(path)
        try:
            self.line = self.chip.get_line(offset)
            self.direction = ('output' if self.line.direction() == gpiod.Line.DIRECTION_OUTPUT
                              else 'input')
            self.line.request(consumer=CONSUMER, type=gpiod.LINE_REQ_DIR_AS_IS)
        except Exception:
            self.chip.close()
            raise

    def get(self):
        return int(self.line.get_value())

    def set(self, value):
        self.line.set_value(value)

    def to_input(self):
        self.line.set_direction_input()

    def to_output(self, value):
        self.line.set_direction_output(value)

    def release(self):
        try:
            self.line.release()
        finally:
            self.chip.close()


class _LineV2:
    def __init__(self, gpiod, path, offset):
        from gpiod.line import Direction, Value
        self.gpiod, self.Direction, self.Value, self.offset = gpiod, Direction, Value, offset
        with gpiod.Chip(path) as chip:
            info = chip.get_line_info(offset)
        self.direction = 'output' if info.direction == Direction.OUTPUT else 'input'
        self.req = gpiod.request_lines(path, consumer=CONSUMER, config={
            offset: gpiod.LineSettings(direction=Direction.AS_IS)})

    def get(self):
        return 1 if self.req.get_value(self.offset) == self.Value.ACTIVE else 0

    def set(self, value):
        self.req.set_value(self.offset, self.Value.ACTIVE if value else self.Value.INACTIVE)

    def to_input(self):
        self.req.reconfigure_lines({self.offset: self.gpiod.LineSettings(direction=self.Direction.INPUT)})

    def to_output(self, value):
        self.req.reconfigure_lines({self.offset: self.gpiod.LineSettings(
            direction=self.Direction.OUTPUT,
            output_value=self.Value.ACTIVE if value else self.Value.INACTIVE)})

    def release(self):
        self.req.release()


class GpioControl:
    def __init__(self):
        self._lock = threading.Lock()
        self._lines = {}        # (chip path, offset) -> {'owner': client, 'handle': _LineV1|_LineV2}
        self._seen = {}         # client -> last heartbeat (monotonic)
        self._watchdog = None
        self.blocked = None     # callable -> reason string when claiming is not allowed

    @staticmethod
    def _check(client, path=None, offset=None):
        if not CLIENT_PATTERN.match(str(client or '')):
            raise GpioError('Invalid client id')
        if path is None:
            return None
        if not CHIP_PATTERN.match(str(path)) or not os.path.exists(path):
            raise GpioError('Unknown GPIO chip')
        try:
            offset = int(offset)
        except (TypeError, ValueError):
            raise GpioError('Invalid line offset')
        if offset < 0:
            raise GpioError('Invalid line offset')
        return (path, offset)

    def _own(self, client, key):
        entry = self._lines.get(key)
        if not entry or entry['owner'] != client:
            raise GpioError('Line is not claimed by this client')
        return entry['handle']

    def _start_watchdog(self):
        if self._watchdog and self._watchdog.is_alive():
            return
        self._watchdog = threading.Thread(target=self._watch, daemon=True, name='gpio-lease')
        self._watchdog.start()

    def _watch(self):
        while True:
            time.sleep(1)
            now = time.monotonic()
            with self._lock:
                expired = {c for c, t in self._seen.items() if now - t > LEASE_SECONDS}
                for client in expired:
                    self._release_client(client)
                if not self._lines:
                    self._watchdog = None
                    return

    def _release_client(self, client):
        for key in [k for k, e in self._lines.items() if e['owner'] == client]:
            self._release_key(key)
        self._seen.pop(client, None)

    def _release_key(self, key):
        entry = self._lines.pop(key, None)
        if entry:
            try:
                entry['handle'].release()
            except Exception:
                pass

    def _state(self, client):
        lines = []
        for (path, offset), entry in sorted(self._lines.items()):
            if entry['owner'] != client:
                continue
            handle = entry['handle']
            try:
                value, error = handle.get(), None
            except Exception as e:
                value, error = None, str(e)
            lines.append({'chip': path, 'offset': offset, 'direction': handle.direction,
                          'value': value, 'error': error})
        return {'held': lines, 'lease': LEASE_SECONDS}

    # ── public API (all calls refresh the client's lease) ──

    def snapshot(self, client):
        self._check(client)
        with self._lock:
            if any(e['owner'] == client for e in self._lines.values()):
                self._seen[client] = time.monotonic()
            return self._state(client)

    def claim(self, client, path, offset):
        key = self._check(client, path, offset)
        reason = self.blocked() if self.blocked else None
        if reason:
            raise GpioError(reason)
        gpiod = _gpiod()
        line_cls = _LineV2 if hasattr(gpiod, 'request_lines') else _LineV1
        with self._lock:
            if key in self._lines:
                raise GpioError('Line is already claimed from the web panel')
            try:
                handle = line_cls(gpiod, path, key[1])
            except Exception as e:
                raise GpioError(f'Cannot request line {key[1]}: {e}')
            self._lines[key] = {'owner': client, 'handle': handle}
            self._seen[client] = time.monotonic()
            self._start_watchdog()
            return self._state(client)

    def configure(self, client, path, offset, direction, value=None):
        key = self._check(client, path, offset)
        with self._lock:
            handle = self._own(client, key)
            self._seen[client] = time.monotonic()
            try:
                if direction == 'input':
                    handle.to_input()
                elif direction == 'output':
                    # Keep the current level when switching to output unless a value is given.
                    level = handle.get() if value is None else int(bool(value))
                    handle.to_output(level)
                else:
                    raise GpioError('Direction must be input or output')
                handle.direction = direction
            except GpioError:
                raise
            except Exception as e:
                raise GpioError(f'Cannot set direction: {e}')
            return self._state(client)

    def set_value(self, client, path, offset, value):
        key = self._check(client, path, offset)
        with self._lock:
            handle = self._own(client, key)
            self._seen[client] = time.monotonic()
            if handle.direction != 'output':
                raise GpioError('Line is not an output')
            try:
                handle.set(int(bool(value)))
            except Exception as e:
                raise GpioError(f'Cannot set value: {e}')
            return self._state(client)

    def release(self, client, path, offset):
        key = self._check(client, path, offset)
        with self._lock:
            self._own(client, key)
            self._release_key(key)
            return self._state(client)

    def release_client(self, client):
        self._check(client)
        with self._lock:
            self._release_client(client)
            return self._state(client)

    def release_all(self):
        """Free every line held from the web (e.g. before a test script starts)."""
        with self._lock:
            for key in list(self._lines):
                self._release_key(key)
            self._seen.clear()


gpio_ctl = GpioControl()
