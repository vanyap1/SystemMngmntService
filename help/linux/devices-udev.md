# Devices, udev, kernel

## udev rules

Access to UART / I²C / GPIO / SPI without root. File `/etc/udev/rules.d/99-customDevRules.rules`:

```bash
# UART
KERNEL=="ttyS[0-9]*", GROUP="dialout", MODE="0660"
# I2C
SUBSYSTEM=="i2c-dev", KERNEL=="i2c-[0-9]*", GROUP="dialout", MODE="0660"
# GPIO (character device)
SUBSYSTEM=="gpio", KERNEL=="gpiochip[0-9]*", GROUP="dialout", MODE="0660"
# SPI
SUBSYSTEM=="spidev", KERNEL=="spidev[0-9]*.*", GROUP="dialout", MODE="0660"
```

Quick and open for everyone (test benches only):

```bash
KERNEL=="i2c-[0-9]*",     MODE="0777"
KERNEL=="gpiochip[0-9]*", MODE="0777"
KERNEL=="spidev[0-9]*.*", MODE="0777"
KERNEL=="ttyUSB[0-9]*",   MODE="0777"
```

Apply and check:

```bash
sudo udevadm control --reload-rules
sudo udevadm trigger
ls -l /dev/ttyS0 /dev/i2c-2 /dev/gpiochip0 /dev/spidev0.0
udevadm info -q property -n /dev/i2c-2      # properties for matching
udevadm info -a -n /dev/video1              # parent attributes (idVendor, idProduct…)
```

Add the user to the group (log in again afterwards):

```bash
sudo usermod -aG dialout vanya
groups vanya
```

> [!NOTE]
> The panel's **Devices → udev** tab shows rules, events and runs `udevadm` without a terminal.

### `i2cdetect: command not found` for a normal user

The tools are in `/usr/sbin`. Add to the end of `~/.profile`:

```bash
export PATH="$PATH:/usr/sbin:/sbin"
```

then `source ~/.profile`.

## Kernel modules

```bash
ls /lib/modules/$(uname -r)/kernel/drivers/media/i2c/ | grep ov    # find camera sensor drivers
lsmod | grep <name>
sudo modprobe <name>
```

Disable a module (example: touchpad multitouch):

```bash
echo "blacklist hid_multitouch" | sudo tee /etc/modprobe.d/blacklist-hid-multitouch.conf
```

## Device tree (dtb ⇄ dts)

```bash
dtc -I dtb -O dts -o h3.dts /boot/dtb/h3-plus2e-custom.dtb     # decompile
dtc -I dts -O dtb -o /boot/dtb/h3-plus2e-custom.dtb h3.dts     # compile
sync && sudo reboot
dmesg | grep -i "machine model"                                # check after boot
```

> [!TIP]
> On Armbian the active dtb is set by `fdtfile=` in `/boot/armbianEnv.txt`.
