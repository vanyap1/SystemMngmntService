# Linux network from the command line

Cheat sheet for the boards (Debian / Armbian / Raspberry Pi OS). They use **NetworkManager**: settings are saved
in *connection profiles* and managed with `nmcli`. The `ip` tool shows and changes the **current** state only — what
you set with `ip` is lost after a reboot or reconnect.

> Interface names on these boards: `end0` / `eth0` (wired), `wlan0` (Wi-Fi), `enx<mac>` (USB Ethernet),
> `can0` (CAN). Replace them and the connection names (`"Wired connection 1"`) in the examples with yours —
> `nmcli connection show` lists them.

The same can be done in the panel: **Settings → Network** (with an automatic rollback if the panel becomes
unreachable). See also [Linux network and SMB](linux-network.md).

## Look around

### Interfaces and addresses

| Command | Shows |
|---|---|
| `ip -br link` | every interface, one line: name, state (UP / DOWN), MAC |
| `ip -br addr` | every interface with its IPv4 / IPv6 addresses |
| `ip addr show end0` | one interface in detail (MTU, MAC, addresses, lifetimes) |
| `ip -s link show end0` | packet / byte / error / drop counters |
| `ip -j -p addr` | the same as JSON (for scripts) |
| `ls /sys/class/net` | interface names |
| `cat /sys/class/net/end0/speed` | link speed in Mbit/s (cable connected) |
| `cat /sys/class/net/end0/carrier` | `1` = cable / link present |
| `ethtool end0` | speed, duplex, autonegotiation, link detected (`apt install ethtool`) |
| `ethtool -i end0` | driver and firmware of the interface |

### Routes, gateway, DNS

| Command | Shows |
|---|---|
| `ip route` | routing table; `default via 192.168.1.1 dev end0` = the gateway |
| `ip route get 8.8.8.8` | which interface / gateway a packet to that address takes |
| `ip neigh` | ARP table: IP ↔ MAC of the neighbours on the LAN |
| `cat /etc/resolv.conf` | DNS servers in use |
| `resolvectl status` | DNS per interface (only with systemd-resolved) |
| `nmcli device show end0 \| grep -E 'IP4|DNS'` | addresses, gateway, DNS the interface got |

### NetworkManager state

| Command | Shows |
|---|---|
| `nmcli` | short overview of all devices |
| `nmcli device status` | devices: type, state, connection in use |
| `nmcli connection show` | saved profiles (NAME, UUID, TYPE, DEVICE); active ones have a device |
| `nmcli connection show --active` | only the active profiles |
| `nmcli connection show "Wired connection 1"` | every setting of a profile (`ipv4.method`, addresses, DNS, …) |
| `nmcli -g ipv4.method,ipv4.addresses connection show "Wired connection 1"` | chosen fields only |
| `nmcli -f GENERAL,IP4 device show end0` | device: state, MAC, addresses, gateway, DNS |
| `ls /etc/NetworkManager/system-connections/` | profile files (root only; Wi-Fi passwords are inside) |
| `journalctl -u NetworkManager -f` | NetworkManager log live (DHCP, link up / down, errors) |

### Who is listening, what is connected

| Command | Shows |
|---|---|
| `ss -tulpn` | listening TCP / UDP ports and their processes (with `sudo`) |
| `ss -tnp` | open TCP connections |
| `ping -c 4 192.168.1.1` | is the host reachable |
| `ping -I end0 8.8.8.8` | ping through a chosen interface |
| `traceroute 8.8.8.8` / `tracepath 8.8.8.8` | path to a host |
| `getent hosts example.com` | does DNS resolve the name |
| `sudo tcpdump -ni end0 port 67 or port 68` | watch DHCP traffic (`apt install tcpdump`) |
| `sudo arp-scan -I end0 --localnet` | every device on the LAN (`apt install arp-scan`) |

## Static IP (NetworkManager)

Set address, gateway and DNS in the profile, then re-activate it:

```bash
sudo nmcli connection modify "Wired connection 1" \
    ipv4.method manual \
    ipv4.addresses 192.168.1.50/24 \
    ipv4.gateway 192.168.1.1 \
    ipv4.dns "192.168.1.1 8.8.8.8"
sudo nmcli connection up "Wired connection 1"
```

- `ipv4.method manual` **switches the DHCP client off** for this profile.
- `/24` = mask 255.255.255.0, `/16` = 255.255.0.0.
- Several addresses: `ipv4.addresses "192.168.1.50/24, 10.0.0.5/8"`; add / remove one:
  `nmcli connection modify "Wired connection 1" +ipv4.addresses 10.0.0.5/8` (`-ipv4.addresses` removes).
- Without a gateway (a closed test network): `ipv4.gateway ""`.

> **Over SSH:** when you change the address of the interface you are connected through, the session drops. Connect
> again to the new address. If the new address is wrong, you need a console, another interface or the safety net
> below.

### Back to DHCP

```bash
sudo nmcli connection modify "Wired connection 1" \
    ipv4.method auto \
    ipv4.addresses "" ipv4.gateway "" ipv4.dns ""
sudo nmcli connection up "Wired connection 1"
```

`ipv4.method auto` = DHCP client on. The empty values clear what was left from the static setup.

### DHCP and extra DNS / extra address

```bash
# DHCP, but use own DNS servers instead of the ones DHCP gives
sudo nmcli connection modify "Wired connection 1" ipv4.method auto ipv4.dns "1.1.1.1 8.8.8.8" ipv4.ignore-auto-dns yes
# DHCP plus a fixed second address on the same interface
sudo nmcli connection modify "Wired connection 1" ipv4.method auto ipv4.addresses 10.10.20.1/24
# do not use this interface's gateway as the default route (e.g. a test LAN next to the internet link)
sudo nmcli connection modify "Wired connection 1" ipv4.never-default yes
# prefer one uplink over another (lower = preferred)
sudo nmcli connection modify "Wired connection 1" ipv4.route-metric 100
sudo nmcli connection up "Wired connection 1"
```

### Renew / release a DHCP lease

```bash
sudo nmcli device reapply end0                  # apply profile changes without dropping the link (when possible)
sudo nmcli connection down "Wired connection 1" && sudo nmcli connection up "Wired connection 1"   # new lease
nmcli -f DHCP4 device show end0                 # what the DHCP server sent (lease time, server, options)
```

### No IP at all (interface up, no addresses)

```bash
sudo nmcli connection modify "Wired connection 1" ipv4.method disabled ipv6.method disabled
sudo nmcli connection up "Wired connection 1"
```

Useful for an interface used only for raw traffic, a bridge member or sniffing.

## Profiles: create, enable, disable, delete

```bash
# new wired profile with a static IP, bound to one interface
sudo nmcli connection add type ethernet ifname end0 con-name lab-static \
    ipv4.method manual ipv4.addresses 192.168.10.2/24 ipv4.gateway 192.168.10.1 ipv4.dns 192.168.10.1
# new wired profile with DHCP
sudo nmcli connection add type ethernet ifname enx321e31f9c2f8 con-name usb-lan ipv4.method auto

sudo nmcli connection up lab-static               # activate
sudo nmcli connection down lab-static             # deactivate (stays saved)
sudo nmcli connection modify lab-static connection.autoconnect no        # do not start at boot
sudo nmcli connection modify lab-static connection.autoconnect-priority 10   # higher wins among several
sudo nmcli connection modify lab-static connection.id lab                # rename
sudo nmcli connection delete lab                   # delete the profile

sudo nmcli device disconnect end0                  # take the interface down until connected again
sudo nmcli device connect end0                     # bring it up with the best profile
sudo nmcli device set end0 managed no              # NetworkManager stops touching it (manual `ip` setup)
sudo nmcli device set end0 managed yes
sudo nmcli connection reload                       # after editing files in system-connections/ by hand
```

Two profiles for one port (e.g. *office* DHCP and *lab* static) — switch with `nmcli connection up <name>`.

## Wi-Fi

```bash
nmcli radio wifi                                   # enabled / disabled
sudo nmcli radio wifi on
nmcli device wifi list                             # networks in range (--rescan yes to scan again)
sudo nmcli device wifi connect "Office" password "secret123"            # join; creates a profile
sudo nmcli device wifi connect "Hidden" password "secret123" hidden yes
nmcli -f IN-USE,SSID,SIGNAL,SECURITY device wifi                         # current network and signal
sudo nmcli connection modify "Office" ipv4.method manual ipv4.addresses 192.168.1.60/24 ipv4.gateway 192.168.1.1
nmcli -s -g 802-11-wireless-security.psk connection show "Office"       # saved password (root)
rfkill list                                        # blocked radios; `sudo rfkill unblock wifi`
iw dev wlan0 link                                  # BSSID, frequency, signal, bitrate (apt install iw)
iw list | grep -A10 'Supported interface modes'    # does the adapter support AP mode ("* AP")
```

> The password typed on the command line stays in the shell history. `nmcli --ask device wifi connect "Office"`
> asks for it instead.

### Access point (hotspot) with DHCP server

NetworkManager's *shared* mode = access point + DHCP + DNS + NAT to the internet link (needs `dnsmasq-base`:
`sudo ./install-network.sh` in the panel folder). The panel page **Settings → Network → Access point & DHCP** does
the same with a pool and MAC → IP reservations.

```bash
sudo nmcli connection add type wifi ifname wlan0 con-name my-ap ssid Bench-AP \
    802-11-wireless.mode ap 802-11-wireless.band bg \
    wifi-sec.key-mgmt wpa-psk wifi-sec.psk "bench-pass-1" \
    ipv4.method shared ipv4.addresses 10.10.10.1/24 \
    ipv4.shared-dhcp-range "10.10.10.2,10.10.10.254" ipv4.shared-dhcp-lease-time 3600 \
    ipv6.method ignore
sudo nmcli connection up my-ap

sudo cat /var/lib/NetworkManager/dnsmasq-wlan0.leases    # clients: expiry, MAC, IP, name
iw dev wlan0 station dump                                # associated clients with signal
sudo nmcli connection down my-ap                         # stop; `nmcli device connect wlan0` = client again
```

`shared-dhcp-range` / `-lease-time` need NetworkManager 1.42+ (`nmcli --version`).

## Temporary changes with `ip` (until reboot / reconnect)

Good for a quick test — nothing is saved. On an interface NetworkManager manages, it may overwrite them;
`nmcli device set end0 managed no` first if they must stay.

```bash
sudo ip addr add 192.168.50.10/24 dev end0         # extra address
sudo ip addr del 192.168.50.10/24 dev end0
sudo ip addr flush dev end0                        # remove every address
sudo ip link set end0 down                         # interface off / on
sudo ip link set end0 up
sudo ip route add default via 192.168.1.1          # default gateway
sudo ip route replace default via 192.168.1.254 dev end0
sudo ip route del default
sudo ip route add 10.20.0.0/16 via 192.168.1.5     # route to another network
sudo ip link set end0 mtu 1400
sudo ip link set end0 down; sudo ip link set end0 address 02:11:22:33:44:55; sudo ip link set end0 up   # MAC
sudo ip neigh flush dev end0                       # clear the ARP cache
```

Run a DHCP client by hand (only on an interface NetworkManager does not manage):

```bash
sudo dhclient -v end0        # get an address (package isc-dhcp-client)
sudo dhclient -r end0        # release it
```

## Same settings saved permanently via nmcli: other options

| Setting | Command |
|---|---|
| MTU | `nmcli connection modify "Wired connection 1" 802-3-ethernet.mtu 1400` |
| Fixed / cloned MAC | `nmcli connection modify "Wired connection 1" 802-3-ethernet.cloned-mac-address 02:11:22:33:44:55` |
| Static route | `nmcli connection modify "Wired connection 1" +ipv4.routes "10.20.0.0/16 192.168.1.5"` |
| IPv6 off | `nmcli connection modify "Wired connection 1" ipv6.method disabled` |
| Speed / duplex | `nmcli connection modify "Wired connection 1" 802-3-ethernet.auto-negotiate no 802-3-ethernet.speed 100 802-3-ethernet.duplex full` |
| VLAN 20 on end0 | `nmcli connection add type vlan ifname end0.20 dev end0 id 20 ipv4.method manual ipv4.addresses 192.168.20.2/24` |
| Host name | `sudo hostnamectl set-hostname bench-3` |

Every `modify` takes effect after `nmcli connection up <name>` (or `nmcli device reapply <iface>`).

## Safety net over SSH

A wrong address on the only link locks you out. Schedule the old settings back **before** the change and cancel
it once the new one works:

```bash
# remember: return to DHCP in 3 minutes unless cancelled
sudo systemd-run --on-active=180 --unit=net-undo \
    nmcli connection modify "Wired connection 1" ipv4.method auto ipv4.addresses "" ipv4.gateway "" ipv4.dns "" \
    && echo scheduled
sudo systemd-run --on-active=185 --unit=net-undo-up nmcli connection up "Wired connection 1"

# the risky change
sudo nmcli connection modify "Wired connection 1" ipv4.method manual ipv4.addresses 192.168.1.50/24 ipv4.gateway 192.168.1.1
sudo nmcli connection up "Wired connection 1"

# reconnect to 192.168.1.50 — it works: cancel the undo
sudo systemctl stop net-undo.timer net-undo-up.timer
```

The panel's **Settings → Network** does this automatically (NetworkManager checkpoint, 120 s).

## Systems without NetworkManager

### ifupdown (`/etc/network/interfaces`, classic Debian)

```text
# DHCP
auto eth0
iface eth0 inet dhcp

# static
auto eth0
iface eth0 inet static
    address 192.168.1.50/24
    gateway 192.168.1.1
    dns-nameservers 192.168.1.1 8.8.8.8
```

```bash
sudo ifdown eth0 && sudo ifup eth0       # apply
```

### netplan (Ubuntu, some Armbian images)

`/etc/netplan/01-net.yaml`:

```yaml
network:
  version: 2
  renderer: NetworkManager        # or networkd
  ethernets:
    eth0:
      dhcp4: false                # true = DHCP client on
      addresses: [192.168.1.50/24]
      routes:
        - to: default
          via: 192.168.1.1
      nameservers:
        addresses: [192.168.1.1, 8.8.8.8]
```

```bash
sudo netplan try        # applies and rolls back after 120 s unless you press Enter
sudo netplan apply
```

### systemd-networkd

`/etc/systemd/network/10-eth0.network`:

```ini
[Match]
Name=eth0

[Network]
# DHCP=yes for DHCP instead of the lines below
Address=192.168.1.50/24
Gateway=192.168.1.1
DNS=192.168.1.1
```

```bash
sudo systemctl restart systemd-networkd
networkctl status eth0
```

Which one is in charge: `systemctl is-active NetworkManager systemd-networkd networking`. Only one of them
should manage an interface.

## Troubleshooting

| Symptom | Check |
|---|---|
| No address on the cable | `cat /sys/class/net/end0/carrier` (1 = link), `nmcli device status`, `journalctl -u NetworkManager -n 50` |
| `169.254.x.x` address | link-local fallback — no DHCP server answered |
| Address OK, no internet | `ip route` (default route?), `ping 192.168.1.1`, `ping 8.8.8.8`, then DNS: `getent hosts example.com` |
| Internet by IP, not by name | `cat /etc/resolv.conf`, `nmcli device show end0 \| grep DNS` |
| Two default routes | `ip route` — the lower `metric` wins; set `ipv4.route-metric` or `ipv4.never-default yes` |
| Interface `unmanaged` in nmcli | listed in `/etc/network/interfaces` or `managed no` — `nmcli device set end0 managed yes` |
| Wi-Fi does not appear | `rfkill list`, `nmcli radio wifi on`, `dmesg \| grep -i firmware` |
| IP conflict | `sudo arping -D -I end0 192.168.1.50` — any reply = the address is already used |
