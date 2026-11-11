"""SSH to the unit under test (or any Linux box): run a command, get its output — with the system OpenSSH client.

    from instruments.ssh_term import SshTerm

    uut = SshTerm("192.168.1.80", "root", "secret")          # or key="/path/id_ed25519", port=22
    print(uut.cmd("uname -r"))                                 # stdout (stripped); SshError if the exit code ≠ 0
    r = uut.run("ls /missing")                                 # Result: r.out, r.err, r.code — never raises
    ok = uut.cmdOk("systemctl is-active myapp")                # True / False
    uut.put("fw.bin", "/tmp/fw.bin"); uut.get("/var/log/app.log", "app.log")
    uut.waitOnline(60)                                         # after a reboot
    uut.close()

No extra Python packages: ``ssh`` / ``scp`` of OpenSSH ≥ 8.4. A password goes to ssh through SSH_ASKPASS (a private
helper script reading it from the environment) — never on a command line. One SSH connection is kept open and
shared by the commands (ControlMaster), so a command takes milliseconds, not a new handshake.
Host keys are NOT checked by default (``strict=False``): units under test get a new key with every flash. Use
``strict=True`` for machines that must be verified.
"""
import os
import shlex
import shutil
import subprocess
import tempfile
import time
from typing import List, Optional


class SshError(Exception):
    """SSH cannot connect / authenticate, or a command failed (cmd())."""


class Result:
    def __init__(self, out: str, err: str, code: int) -> None:
        self.out, self.err, self.code = out, err, code

    @property
    def ok(self) -> bool:
        return self.code == 0

    def __repr__(self) -> str:
        return f"Result(code={self.code}, out={self.out[:60]!r}, err={self.err[:60]!r})"


class SshTerm:
    def __init__(self, host: str, user: str = "root", password: Optional[str] = None, port: int = 22,
                 key: Optional[str] = None, timeout: float = 15.0, strict: bool = False,
                 ssh_bin: str = "ssh", scp_bin: str = "scp") -> None:
        self.host, self.user, self.port, self.key, self.timeout = host, user, int(port), key, timeout
        self.strict, self.ssh_bin, self.scp_bin = strict, ssh_bin, scp_bin
        self._password = password
        self._dir = None
        self._env = dict(os.environ)
        self._prepare()

    def _prepare(self) -> None:
        """Private 0700 folder for the control socket and the askpass helper (made again after close())."""
        if self._dir and os.path.isdir(self._dir):
            return
        self._dir = tempfile.mkdtemp(prefix="sshterm-")
        if self._password is not None:
            helper = os.path.join(self._dir, "askpass")
            with open(helper, "w") as f:
                f.write('#!/bin/sh\nprintf "%s\\n" "$SSHTERM_PASSWORD"\n')
            os.chmod(helper, 0o700)
            self._env.update(SSH_ASKPASS=helper, SSH_ASKPASS_REQUIRE="force", DISPLAY=":0",
                             SSHTERM_PASSWORD=self._password)

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"SshTerm({self.user}@{self.host}:{self.port})"

    def _opts(self, mux: bool = True) -> List[str]:
        self._prepare()
        o = ["-o", f"ConnectTimeout={int(max(1, self.timeout))}", "-o", "ServerAliveInterval=5", "-o", "LogLevel=ERROR"]
        o += (["-o", "ControlMaster=auto", "-o", f"ControlPath={self._dir}/cm", "-o", "ControlPersist=60"] if mux
              else ["-o", "ControlMaster=no", "-o", "ControlPath=none"])
        if self.strict:
            o += ["-o", "StrictHostKeyChecking=yes"]
        else:
            o += ["-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null"]
        if self._password is None:
            o += ["-o", "BatchMode=yes"]                          # never hang on a password prompt
        else:
            o += ["-o", "NumberOfPasswordPrompts=1", "-o", "PubkeyAuthentication=no"]
        if self.key:
            o += ["-i", self.key, "-o", "IdentitiesOnly=yes"]
        return o

    def _call(self, argv: List[str], timeout: Optional[float], stdin: Optional[str] = None) -> Result:
        try:
            p = subprocess.run(argv, input=stdin, capture_output=True, text=True, env=self._env,
                               timeout=timeout or self.timeout, stdin=None if stdin is not None else subprocess.DEVNULL)
        except FileNotFoundError:
            raise SshError(f"{argv[0]} not found (apt install openssh-client)")
        except subprocess.TimeoutExpired:
            raise SshError(f"{self!r}: no answer within {timeout or self.timeout} s")
        return Result(p.stdout, p.stderr, p.returncode)

    # ── Commands ────────────────────────────────────────────

    def run(self, command: str, timeout: Optional[float] = None, stdin: Optional[str] = None) -> Result:
        """Run a shell command on the host; returns Result(out, err, code). Raises SshError only when SSH itself
        fails (cannot connect, wrong password: code 255)."""
        argv = lambda mux: [self.ssh_bin, "-p", str(self.port), *self._opts(mux), f"{self.user}@{self.host}", "--", command]  # noqa: E731
        r = self._call(argv(True), timeout, stdin)
        if r.code == 255:                       # SSH itself failed: once more without the shared connection —
            self.close(keep_dir=True)           # it works then, or ssh tells the real reason (not a mux error)
            r = self._call(argv(False), timeout, stdin)
            if r.code == 255:
                raise SshError(f"{self!r}: {r.err.strip() or 'connection failed'}")
        return r

    def cmd(self, command: str, timeout: Optional[float] = None) -> str:
        """Run a command, return its stdout without the outer whitespace; SshError if it exits with ≠ 0."""
        r = self.run(command, timeout)
        if r.code != 0:
            raise SshError(f"{command!r} exited with {r.code}: {(r.err or r.out).strip()[:300]}")
        return r.out.strip()

    def cmdOk(self, command: str, timeout: Optional[float] = None) -> bool:
        """True if the command exits with 0 (also False when SSH cannot connect)."""
        try:
            return self.run(command, timeout).code == 0
        except SshError:
            return False

    def ping(self) -> bool:
        """True if an SSH session can be opened."""
        return self.cmdOk("true")

    def waitOnline(self, timeout: float = 60.0, interval: float = 2.0) -> bool:
        """Wait until SSH answers (after a reboot / flash); False on timeout."""
        end = time.time() + timeout
        while time.time() < end:
            if self.ping():
                return True
            self.close(keep_dir=True)                             # a stale master socket would hang
            time.sleep(interval)
        return False

    # ── Files ───────────────────────────────────────────────

    def _scp(self, src: str, dst: str, timeout: Optional[float]) -> None:
        r = self._call([self.scp_bin, "-q", "-P", str(self.port), *self._opts(), src, dst], timeout or self.timeout * 4)
        if r.code != 0:
            raise SshError(f"scp {src} → {dst}: {r.err.strip() or r.code}")

    def put(self, local: str, remote: str, timeout: Optional[float] = None) -> None:
        """Copy a local file to the host."""
        self._scp(local, f"{self.user}@{self.host}:{shlex.quote(remote)}", timeout)

    def get(self, remote: str, local: str, timeout: Optional[float] = None) -> None:
        """Copy a file from the host."""
        self._scp(f"{self.user}@{self.host}:{shlex.quote(remote)}", local, timeout)

    def readFile(self, remote: str) -> str:
        """Text of a file on the host."""
        return self.cmd(f"cat {shlex.quote(remote)}")

    def writeFile(self, remote: str, text: str) -> None:
        """Write a text file on the host (replaces it)."""
        r = self.run(f"cat > {shlex.quote(remote)}", stdin=text)
        if r.code != 0:
            raise SshError(f"write {remote}: {r.err.strip()}")

    # ── End ─────────────────────────────────────────────────

    def close(self, keep_dir: bool = False) -> None:
        """Close the shared SSH connection (and remove the helper files)."""
        if not self._dir:
            return
        if os.path.exists(os.path.join(self._dir, "cm")):
            try:
                subprocess.run([self.ssh_bin, "-o", f"ControlPath={self._dir}/cm", "-O", "exit",
                                f"{self.user}@{self.host}"], capture_output=True, timeout=5, env=self._env)
            except (OSError, subprocess.SubprocessError):
                pass
        if not keep_dir:
            shutil.rmtree(self._dir, ignore_errors=True)
            self._dir = None

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass


SSH_TERM = SshTerm
