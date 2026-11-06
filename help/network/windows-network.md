# Windows network tools

## Network drives (net use)

| Command | What it does |
|---|---|
| `net use` | list connections |
| `net use * /delete /y` | remove **all** connections |
| `net use \\192.168.1.141\share /delete` | remove one connection |
| `net use * \\192.168.1.141\share /user:pi` | connect as a user |
| `net use Z: \\192.168.1.141\share /persistent:yes` | map drive Z: and reconnect at logon |
| `net use Z: /delete` | unmap Z: |
| `net config workstation` | current user name and domain |
| `net help use` | help |

Saved credentials (Windows reuses them silently — delete them when a share asks for "wrong" user):

| Command | What it does |
|---|---|
| `cmdkey /list` | list |
| `cmdkey /delete:192.168.1.141` | delete for a host |
| `cmdkey /delete:TERMSRV/192.168.1.141` | delete RDP credentials |
| `cmdkey /add:192.168.1.141 /user:vanya /pass:<password>` | add manually |

## Wi-Fi profiles (netsh)

```bat
netsh interface show interface
netsh wlan show interfaces
netsh wlan show profiles
netsh wlan show profile name="Internet" key=clear

rem all saved Wi-Fi passwords (cmd, not PowerShell)
for /f "skip=9 tokens=1,2 delims=:" %i in ('netsh wlan show profiles') do @echo %j | findstr -i -v echo | netsh wlan show profiles %j key=clear

netsh wlan export profile key=clear folder=C:\tmp\wifi
netsh wlan add profile filename="C:\tmp\wifi\Wi-Fi-Internet.xml" user=all
netsh wlan delete profile name="profilename"
```

## COM port over TCP (com2tcp)

`com2tcp` (part of the com0com project) connects a Windows COM port to a TCP server — e.g. a MOXA NPort or
a board with `ser2net`.

[com2tcp.exe](../docs/com2tcp.exe)
[com0com-3.0.0.0-i386-and-x64-signed.zip](../docs/com0com-3.0.0.0-i386-and-x64-signed.zip)

Serve COM4 as a telnet server on port 12345 ([com2tcp-run.bat](../docs/com2tcp-run.bat)):

```bat
@echo off
com2tcp --baud 9600 --ignore-dsr --telnet \\.\COM4 12345
```

Connect COM4 to a MOXA server 192.168.1.253:4004 ([com2tcp-moxa.bat](../docs/com2tcp-moxa.bat)):

```bat
com2tcp --baud 9600 --ignore-dsr \\.\COM4 192.168.1.253 4004
```

With com0com create a virtual pair (e.g. `COM2` ⇄ `CNCB0`), run com2tcp on `\\.\CNCB0` and the old application on `COM2`.

> [!TIP]
> Autostart: put the `.bat` into `shell:startup` (Win+R). When connecting from another PC, allow the port in the firewall.

## Syncthing autostart without a console window

Download from syncthing.net, unpack to `C:\Syncthing`, create `syncthing_start.vbs`:

```vb
Set WshShell = CreateObject("WScript.Shell")
WshShell.Run """C:\Syncthing\syncthing.exe"" --no-browser", 0, False
```

Put the `.vbs` into `shell:startup` (Win+R → `shell:startup`).
