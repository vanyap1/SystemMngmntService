# Quectel M66 AT commands (SMS, TCP/HTTP)

Terminal settings: 115200 8N1 (or auto-baud), every command ends with `CR` (Enter).

## Initialization

| Command | Purpose | Answer |
|---|---|---|
| `AT` | link PC ⇄ modem | `OK` |
| `AT+CMEE=2` | text error messages instead of codes | `OK` |
| `AT+CPIN?` | SIM state (read, PIN) | `+CPIN: READY` |
| `AT+CSQ` | signal: first number 10…31 is usable, 31 is best | `+CSQ: 26,0` |
| `AT+CREG?` | network registration: `0,1` home, `0,5` roaming | `+CREG: 0,1` |

## 1. Send an SMS (text mode)

| Step | Command | Purpose | Answer |
|---|---|---|---|
| 1 | `AT+CMGF=1` | text mode (default is PDU) | `OK` |
| 2 | `AT+CMGS="+380XXXXXXXXX"` | recipient, international format | prompt `>` |
| 3 | `Message text` | Latin text, **no Enter** at the end | echoed after `>` |
| 4 | byte `0x1A` (Ctrl+Z) | send | `+CMGS: <id>` `OK` |

After delivery the modem may also print a status report `+CDS: …`.

## 2. HTTP GET over TCP

### A. GPRS context

| Command | Purpose | Answer |
|---|---|---|
| `AT+QIMODE=0` | normal (non-transparent) mode | `OK` |
| `AT+QIDNSIP=1` | connect by domain name | `OK` |
| `AT+QIDEACT` | close old sessions | `DEACT OK` |
| `AT+CGATT=1` | attach to GPRS | `OK` (`ERROR` = data blocked by the operator) |
| `AT+QIREGAPP="internet"` | APN (`internet` for Ukrainian operators) | `OK` |
| `AT+QIACT` | activate the context | `OK` |
| `AT+QILOCIP` | local IP (optional) | `10.123.45.67` |

### B. Connect and send

```text
AT+QIOPEN="TCP","httpbin.org",80     -> OK, then CONNECT OK
AT+QISEND                            -> >
GET /ip HTTP/1.1
Host: httpbin.org
                                     <- empty line, then Ctrl+Z (0x1A)
                                     -> SEND OK
```

### C. Read the answer

The modem reports incoming data with `+QIURC: "recv",0`.

```text
AT+QIRD=0,1024                       -> raw HTTP answer:
HTTP/1.1 200 OK
Content-Type: application/json

{ "origin": "176.105.x.x" }
```

## Session control

| Command | Purpose |
|---|---|
| `ATH` | hang up (after an accidental `ATD+380…;` voice call) |
| `AT+QICLOSE` | close the TCP connection, keep GPRS |
| `AT+QIDEACT` | drop the GPRS session |
