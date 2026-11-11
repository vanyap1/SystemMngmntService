# SSH terminal — commands on the UUT over the network

Driver `testPlatform/instruments/ssh_term.py`: run commands on a Linux UUT (or any machine) over SSH and get
their output — with the system OpenSSH client, no extra Python packages. A password is passed through
SSH_ASKPASS, never on a command line; one SSH connection is kept open and shared, so each command takes
milliseconds after the first. See [Instruments](instruments.md).

Host keys are not checked by default (`strict=False`) — a unit under test gets a new key with every flash.

## Connect

```python
from instruments.ssh_term import SshTerm, SshError

uut = SshTerm("192.168.1.80", "root", "secret")             # host, user, password, port=22, timeout=15
uut = SshTerm("192.168.1.80", "root", key="/home/vanya/.ssh/id_ed25519")
uut = SshTerm("10.0.0.2", "admin", "pw", port=2222, strict=True)   # verify the host key
uut.ping()                                      # True if a session can be opened
uut.waitOnline(60)                              # after a reboot / flash: True when SSH answers
uut.close()                                     # in finalize()
```

## Commands

```python
uut.cmd("uname -r")                             # stdout without outer whitespace; SshError if exit code ≠ 0
uut.cmd("cat /etc/fw_version")
uut.cmdOk("systemctl is-active myapp")          # True / False (also False when SSH cannot connect)
r = uut.run("ls /missing")                      # never raises for the command itself:
r.out, r.err, r.code                            # output, errors, exit code
r.ok                                            # True if code == 0
uut.run("cat > /tmp/cfg", stdin="key=1\n")      # with input
```

`run` raises `SshError` only when SSH itself fails (host unreachable, wrong password).

```python
uut.waitOnline(90)
ts.stringMatchTest("Kernel", uut.cmd("uname -r"), "6.1.0-orangepi")
ts.booleanTest("App running", uut.cmdOk("systemctl is-active myapp"), True)
ts.numericLimitTest("Free RAM", int(uut.cmd("free -m | awk '/Mem/ {print $7}'")), 200, 4000, "MB")
```

## Files

```python
uut.put("fw.bin", "/tmp/fw.bin")                # copy to the UUT (scp)
uut.get("/var/log/app.log", "app.log")          # copy from the UUT
uut.readFile("/etc/hostname")                   # text of a remote file
uut.writeFile("/etc/myapp.conf", "mode=test\n") # write a remote text file
```
