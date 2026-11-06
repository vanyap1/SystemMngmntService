# Linux network and SMB

## NetworkManager instead of networkd (netplan)

`/etc/netplan/10-dhcp-all-interfaces.yaml` — change the renderer:

```yaml
network:
  version: 2
  renderer: NetworkManager     # was: networkd
  ethernets:
    all-eth-interfaces:
      # ...
```

```bash
sudo netplan apply
nmcli device status
```

## Wi-Fi off while the cable is connected

Dispatcher script `/etc/NetworkManager/dispatcher.d/99-wifi-toggle`:

```bash
#!/bin/bash
LAN_INTERFACE="eth0"
INTERFACE=$1
ACTION=$2

if [ "$INTERFACE" = "$LAN_INTERFACE" ]; then
    case "$ACTION" in
        up|activated)
            logger -t "NM-Toggle" "Cable connected on eth0, Wi-Fi off"
            nmcli radio wifi off
            ;;
        down|deactivated)
            logger -t "NM-Toggle" "Cable disconnected from eth0, Wi-Fi on"
            nmcli radio wifi on
            ;;
    esac
fi
```

```bash
sudo chown root:root /etc/NetworkManager/dispatcher.d/99-wifi-toggle
sudo chmod 755 /etc/NetworkManager/dispatcher.d/99-wifi-toggle
```

## Mount a Windows / NAS share (CIFS)

```bash
sudo apt install cifs-utils
sudo mkdir -p /home/pi/serv
sudo mount -t cifs //192.168.1.11/share/vanya/NAS /home/pi/serv \
     -o username=vanya,password=<password>,uid=pi,gid=pi,vers=2.0
sudo umount /home/pi/serv
```

> [!TIP]
> Keep the password out of the command line and history: put `username=vanya` / `password=…` into
> `/root/.smbcred` (`chmod 600`) and use `-o credentials=/root/.smbcred,uid=pi,gid=pi`.
> The same options work in `/etc/fstab` (add `_netdev,nofail`).

## Samba server (share a folder with Windows)

```bash
sudo apt install samba
sudo smbpasswd -a vanya       # the Linux user must exist (adduser)
sudo smbpasswd -e vanya
sudo systemctl restart smbd nmbd
```

`/etc/samba/smb.conf` (minimal):

```ini
[global]
   workgroup = WORKGROUP
   server string = Samba Server
   server role = standalone server
   security = user
   map to guest = bad user
   dns proxy = no
   log file = /var/log/samba/log.%m
   max log size = 1000

[share]
   comment = Home Directory
   path = /home/vanya
   browseable = yes
   writable = yes
   guest ok = no
   valid users = vanya
   create mask = 0777
   directory mask = 0777
```

Windows side: [net use](windows-network.md#network-drives-net-use).
