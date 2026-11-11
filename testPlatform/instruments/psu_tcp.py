"""Transport of the custom Ethernet PSU controllers (PSU_CUSTOM6020, PSU_CUSTOM305): raw SCPI on TCP :8080,
one connection per command. Not used by test scripts directly — import the model driver."""
import socket
import threading
import time
from typing import Optional


class PsuError(Exception):
    """Controller answered "ERROR: ..." or cannot be reached."""


class OneShotTcpPsu:
    """Transport shared by the custom Ethernet PSU controllers: raw SCPI on TCP :8080, one connection per
    command — connect, send "<cmd>\\r\\n", read until the controller closes; an "ERROR…" answer raises PsuError."""
    DEFAULT_PORT = 8080
    DEFAULT_HOST = ""

    def __init__(self, host: Optional[str] = None, port: int = DEFAULT_PORT, timeout: float = 3.0,
                 retries: int = 5) -> None:
        host = host or self.DEFAULT_HOST
        self.host = host
        self.port = port
        self.timeout = timeout
        self.retries = retries
        self._lock = threading.Lock()   # one command at a time (also from a TestWatch check)

    # ------------------------------------------------------------------ #
    #  Raw access
    # ------------------------------------------------------------------ #
    def query(self, cmd: str) -> str:
        """Send one command, return the answer text (without the trailing CR LF)."""
        if "\r" in cmd or "\n" in cmd:
            raise ValueError("one command per call")
        last = None
        with self._lock:
            for attempt in range(self.retries):
                try:
                    with socket.create_connection((self.host, self.port), timeout=self.timeout) as s:
                        s.sendall(cmd.encode("ascii") + b"\r\n")
                        data = b""
                        while True:
                            chunk = s.recv(4096)
                            if not chunk:
                                break
                            data += chunk
                    answer = data.decode("utf-8", errors="replace").rstrip("\r\n")
                    if answer.upper().startswith("ERROR"):
                        raise PsuError(f"{cmd}: {answer}")
                    return answer
                except (ConnectionRefusedError, ConnectionResetError) as e:   # all sockets busy: retry
                    last = e
                    time.sleep(0.05 * (attempt + 1))
                except socket.timeout as e:
                    last = e
                    break
                except OSError as e:
                    last = e
                    break
        raise PsuError(f"{cmd}: no answer from {self.host}:{self.port} ({last})")

    def command(self, cmd: str) -> str:
        """Send a setting command; the answer must not be an error (raises PsuError)."""
        return self.query(cmd)

    def _float(self, cmd: str) -> float:
        answer = self.query(cmd)
        try:
            return float(answer.split(",")[0])
        except ValueError:
            raise PsuError(f"{cmd}: unexpected answer {answer!r}")

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.host!r})"

    def close(self) -> None:
        """Nothing to close (one connection per command); kept for symmetry with the other drivers."""
